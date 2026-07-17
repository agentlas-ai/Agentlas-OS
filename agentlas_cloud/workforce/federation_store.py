"""Durable immutable pins for federated Workforce candidate sessions."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any, Mapping

from .contracts import canonical_digest, canonical_json, validate_candidate_set_coverage_gaps
from .federation import LineageVerifier, validate_federation_result
from .privacy import WorkOrderHubBoundaryError, assert_hub_work_order_boundary


WORKFORCE_SOURCE_PIN_SCHEMA = "agentlas.workforce-source-pin.v1"


class FederationSessionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def default_federation_store_path() -> Path:
    override = os.environ.get("AGENTLAS_WORKFORCE_SESSION_STORE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agentlas" / "workforce" / "federation-sessions.sqlite3"


class FederationSessionStore:
    """SQLite reference store with immutable session/digest binding."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        lineage_verifier: LineageVerifier | None = None,
    ):
        self.path = (Path(path) if path else default_federation_store_path()).expanduser()
        self._memory_only = str(self.path) == ":memory:"
        self.lineage_verifier = lineage_verifier
        self._prepare_private_store_path()
        # sqlite3.Connection.__exit__ only commits or rolls back; it does not
        # close the underlying database handle. Pair the transaction context
        # with closing() so every short-lived store operation releases its FD.
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workforce_federation_sessions (
                    selection_session_id TEXT PRIMARY KEY,
                    federation_digest TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    result_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workforce_federation_source_sessions (
                    federated_selection_session_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_selection_session_id TEXT NOT NULL,
                    candidate_set_digest TEXT NOT NULL,
                    candidate_set_json TEXT NOT NULL,
                    stored_digest TEXT NOT NULL,
                    PRIMARY KEY(federated_selection_session_id, source),
                    FOREIGN KEY(federated_selection_session_id)
                      REFERENCES workforce_federation_sessions(selection_session_id)
                      ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS workforce_federated_selections (
                    federated_selection_session_id TEXT NOT NULL,
                    federated_selection_digest TEXT NOT NULL,
                    selection_json TEXT NOT NULL,
                    stored_digest TEXT NOT NULL,
                    PRIMARY KEY(federated_selection_session_id, federated_selection_digest),
                    FOREIGN KEY(federated_selection_session_id)
                      REFERENCES workforce_federation_sessions(selection_session_id)
                      ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS workforce_federation_work_orders (
                    federated_selection_session_id TEXT PRIMARY KEY,
                    work_order_id TEXT NOT NULL,
                    ontology_version TEXT NOT NULL,
                    work_order_digest TEXT NOT NULL,
                    work_order_json TEXT NOT NULL,
                    stored_digest TEXT NOT NULL,
                    FOREIGN KEY(federated_selection_session_id)
                      REFERENCES workforce_federation_sessions(selection_session_id)
                      ON DELETE CASCADE
                );
                """
            )

    def _prepare_private_store_path(self) -> None:
        """Create the session database privately before SQLite may follow it.

        The immediate parent is hardened only when this store created it.  A
        caller-supplied existing directory may be shared with unrelated files,
        so changing that directory's mode would exceed this store's authority.
        The database and every SQLite sidecar are always private regular files.
        """

        if self._memory_only:
            return
        parent = self.path.parent
        try:
            self._assert_safe_parent_chain(parent)
            parent_created = False
            try:
                parent.lstat()
            except FileNotFoundError:
                try:
                    parent.mkdir(parents=True, mode=0o700, exist_ok=False)
                    parent_created = True
                except FileExistsError:
                    # A peer won the creation race. Validate its node without
                    # mutating a directory this process did not create.
                    pass
            self._assert_safe_parent_chain(parent)
            parent_stat = parent.lstat()
            if not stat.S_ISDIR(parent_stat.st_mode) or stat.S_ISLNK(parent_stat.st_mode):
                raise FederationSessionError("federation_session_store_unsafe_path")
            if os.name == "posix" and parent_created:
                os.chmod(parent, 0o700)

            if self.path.is_symlink():
                raise FederationSessionError("federation_session_store_unsafe_path")
            if not self.path.exists():
                flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(self.path, flags, 0o600)
                os.close(descriptor)
            self._harden_private_store_files()
        except FederationSessionError:
            raise
        except (OSError, ValueError) as exc:
            raise FederationSessionError("federation_session_store_unavailable") from exc

    @staticmethod
    def _assert_safe_parent_chain(parent: Path) -> None:
        """Reject link traversal anywhere above the database, not only at leaf."""

        if ".." in parent.parts:
            raise FederationSessionError("federation_session_store_unsafe_path")
        absolute = Path(os.path.abspath(str(parent)))
        current = Path(absolute.anchor)
        for component in absolute.parts[1:]:
            current /= component
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                # macOS exposes trusted system aliases such as /tmp ->
                # /private/tmp and /var -> /private/var.  They are immutable to
                # an unprivileged caller, unlike a user-owned workspace link.
                if os.name == "posix" and metadata.st_uid == 0:
                    continue
                raise FederationSessionError("federation_session_store_unsafe_path")
            if not stat.S_ISDIR(metadata.st_mode):
                raise FederationSessionError("federation_session_store_unsafe_path")

    def _harden_private_store_files(self) -> None:
        if self._memory_only:
            return
        for candidate in (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
            Path(f"{self.path}-journal"),
        ):
            if candidate.is_symlink():
                raise FederationSessionError("federation_session_store_unsafe_path")
            try:
                metadata = candidate.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise FederationSessionError("federation_session_store_unsafe_path")
            if getattr(metadata, "st_nlink", 1) != 1:
                raise FederationSessionError("federation_session_store_unsafe_path")
            if os.name == "posix":
                os.chmod(candidate, 0o600)

    def _connect(self) -> sqlite3.Connection:
        self._prepare_private_store_path()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(self.path), timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            self._harden_private_store_files()
            return connection
        except FederationSessionError:
            if connection is not None:
                connection.close()
            raise
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise FederationSessionError("federation_session_store_unavailable") from exc

    def save(
        self,
        result: Mapping[str, Any],
        *,
        work_order: Mapping[str, Any],
        source_candidate_sets: Mapping[str, Mapping[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        validate_federation_result(result, lineage_verifier=self.lineage_verifier, now=now)
        work_order_payload, work_order_digest = self._accepted_work_order(result, work_order)
        self.purge_expired(now=now)
        candidate_set = result["candidateSet"]
        session_id = str(candidate_set["selectionSessionId"])
        federation_digest = str(result["federationDigest"])
        payload = canonical_json(result)
        result_digest = canonical_digest(result)
        save_status = "pinned"
        try:
            with closing(self._connect()) as connection, connection:
                existing = connection.execute(
                    "SELECT federation_digest, result_digest FROM workforce_federation_sessions WHERE selection_session_id = ?",
                    (session_id,),
                ).fetchone()
                if existing is not None:
                    if existing["federation_digest"] != federation_digest or existing["result_digest"] != result_digest:
                        raise FederationSessionError("federation_session_immutable")
                    save_status = "already_pinned"
                else:
                    connection.execute(
                        """
                        INSERT INTO workforce_federation_sessions(
                            selection_session_id, federation_digest, expires_at, result_json, result_digest
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (session_id, federation_digest, candidate_set["expiresAt"], payload, result_digest),
                    )
                existing_work_order = connection.execute(
                    """
                    SELECT work_order_id, ontology_version, work_order_digest,
                           work_order_json, stored_digest
                    FROM workforce_federation_work_orders
                    WHERE federated_selection_session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if existing_work_order is not None:
                    if (
                        existing_work_order["work_order_id"] != work_order.get("workOrderId")
                        or existing_work_order["ontology_version"] != work_order.get("ontologyVersion")
                        or existing_work_order["work_order_digest"] != work_order_digest
                        or existing_work_order["work_order_json"] != work_order_payload
                        or existing_work_order["stored_digest"] != work_order_digest
                    ):
                        raise FederationSessionError("federation_work_order_immutable")
                else:
                    connection.execute(
                        """
                        INSERT INTO workforce_federation_work_orders(
                            federated_selection_session_id, work_order_id,
                            ontology_version, work_order_digest, work_order_json,
                            stored_digest
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            work_order["workOrderId"],
                            work_order["ontologyVersion"],
                            work_order_digest,
                            work_order_payload,
                            work_order_digest,
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            raise FederationSessionError("federation_digest_already_bound") from exc
        if source_candidate_sets:
            self._save_source_candidate_sets(result, source_candidate_sets)
        return {
            "status": save_status,
            "selectionSessionId": session_id,
            "federationDigest": federation_digest,
            "workOrderDigest": work_order_digest,
        }

    @staticmethod
    def _accepted_work_order(
        result: Mapping[str, Any],
        work_order: Mapping[str, Any],
    ) -> tuple[str, str]:
        """Return the exact accepted canonical WorkOrder bound to ``result``.

        Validation is deliberately repeated at the durable-store boundary. A
        caller cannot bypass schema, pinned-ontology, finite-ID, or privacy
        checks merely because an upstream adapter claimed to have run them.
        """

        if not isinstance(work_order, Mapping):
            raise FederationSessionError("federation_work_order_not_accepted")
        try:
            boundary = assert_hub_work_order_boundary(work_order)
            payload = canonical_json(work_order)
            digest = canonical_digest(work_order)
        except (WorkOrderHubBoundaryError, TypeError, ValueError):
            raise FederationSessionError("federation_work_order_not_accepted") from None
        if boundary.get("workOrderDigest") != digest:
            raise FederationSessionError("federation_work_order_not_accepted")
        candidate_set = result.get("candidateSet")
        if not isinstance(candidate_set, Mapping):
            raise FederationSessionError("federation_work_order_result_binding_mismatch")
        result_slot_ids = [
            str(slot.get("slotId") or "")
            for slot in candidate_set.get("slots") or []
            if isinstance(slot, Mapping)
        ]
        work_order_slot_ids = [
            str(slot.get("slotId") or "")
            for slot in work_order.get("roleSlots") or []
            if isinstance(slot, Mapping)
        ]
        if (
            candidate_set.get("workOrderId") != work_order.get("workOrderId")
            or candidate_set.get("ontologyVersion") != work_order.get("ontologyVersion")
            or result_slot_ids != work_order_slot_ids
        ):
            raise FederationSessionError("federation_work_order_result_binding_mismatch")
        return payload, digest

    def work_order(
        self,
        selection_session_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Load and revalidate the immutable WorkOrder for one session."""

        result = self.get(selection_session_id, now=now)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT work_order_id, ontology_version, work_order_digest,
                       work_order_json, stored_digest
                FROM workforce_federation_work_orders
                WHERE federated_selection_session_id = ?
                """,
                (selection_session_id,),
            ).fetchone()
        if row is None:
            # Existing databases are migrated additively. Legacy sessions stay
            # fail-closed until the exact original WorkOrder is replay-pinned.
            raise FederationSessionError("federation_work_order_not_pinned")
        try:
            work_order = json.loads(row["work_order_json"])
            payload, digest = self._accepted_work_order(result, work_order)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            if isinstance(exc, FederationSessionError):
                raise
            raise FederationSessionError("stored_federation_work_order_invalid") from exc
        if (
            row["work_order_id"] != work_order.get("workOrderId")
            or row["ontology_version"] != work_order.get("ontologyVersion")
            or row["work_order_digest"] != digest
            or row["stored_digest"] != digest
            or row["work_order_json"] != payload
        ):
            raise FederationSessionError("stored_federation_work_order_digest_mismatch")
        return work_order

    def assert_work_order_binding(
        self,
        selection_session_id: str,
        work_order: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> str:
        """Require exact canonical equality with the session-pinned WorkOrder."""

        result = self.get(selection_session_id, now=now)
        supplied_payload, supplied_digest = self._accepted_work_order(result, work_order)
        pinned = self.work_order(selection_session_id, now=now)
        pinned_payload = canonical_json(pinned)
        if supplied_digest != canonical_digest(pinned) or supplied_payload != pinned_payload:
            raise FederationSessionError("federation_work_order_binding_mismatch")
        return supplied_digest

    @staticmethod
    def _validate_source_candidate_set(
        result: Mapping[str, Any],
        source: str,
        candidate_set: Mapping[str, Any],
    ) -> tuple[str, str, str]:
        receipt = next(
            (
                row
                for row in result.get("sourceReceipts") or []
                if isinstance(row, Mapping) and row.get("source") == source and row.get("status") == "succeeded"
            ),
            None,
        )
        expected_keys = {
            "schemaVersion", "selectionSessionId", "workOrderId", "ontologyVersion",
            "candidateSetDigest", "decisionOwner", "historyInfluence", "slots", "issuedAt", "expiresAt",
        }
        if (
            not isinstance(receipt, Mapping)
            or set(candidate_set) != expected_keys
            or candidate_set.get("schemaVersion") != "agentlas.workforce-candidate-set.v1"
            or candidate_set.get("selectionSessionId") != receipt.get("selectionSessionId")
            or candidate_set.get("candidateSetDigest") != receipt.get("candidateSetDigest")
            or candidate_set.get("workOrderId") != result["candidateSet"].get("workOrderId")
            or candidate_set.get("ontologyVersion") != result["candidateSet"].get("ontologyVersion")
            or candidate_set.get("decisionOwner") != "host_llm"
            or candidate_set.get("historyInfluence") != "none"
        ):
            raise FederationSessionError("source_candidate_set_binding_mismatch")
        try:
            validate_candidate_set_coverage_gaps(candidate_set)
            payload = canonical_json(candidate_set)
        except (TypeError, ValueError) as exc:
            raise FederationSessionError("source_candidate_set_invalid") from exc
        if len(payload.encode("utf-8")) > 16 * 1024 * 1024:
            raise FederationSessionError("source_candidate_set_invalid")
        expected_digest = canonical_digest(
            {
                "workOrderId": candidate_set["workOrderId"],
                "ontologyVersion": candidate_set["ontologyVersion"],
                "slots": candidate_set["slots"],
                "historyInfluence": "none",
            }
        )
        if candidate_set.get("candidateSetDigest") != expected_digest:
            raise FederationSessionError("source_candidate_set_digest_mismatch")
        return payload, str(candidate_set["selectionSessionId"]), str(candidate_set["candidateSetDigest"])

    def _save_source_candidate_sets(
        self,
        result: Mapping[str, Any],
        source_candidate_sets: Mapping[str, Mapping[str, Any]],
    ) -> None:
        session_id = str(result["candidateSet"]["selectionSessionId"])
        expected_sources = {
            str(row["source"])
            for row in result.get("sourceReceipts") or []
            if isinstance(row, Mapping) and row.get("status") == "succeeded"
        }
        if set(source_candidate_sets) != expected_sources:
            raise FederationSessionError("source_candidate_set_coverage_mismatch")
        rows: list[tuple[str, str, str, str]] = []
        for source, candidate_set in source_candidate_sets.items():
            payload, source_session_id, candidate_digest = self._validate_source_candidate_set(
                result, str(source), candidate_set
            )
            rows.append((str(source), source_session_id, candidate_digest, payload))
        with closing(self._connect()) as connection, connection:
            for source, source_session_id, candidate_digest, payload in rows:
                stored_digest = canonical_digest(json.loads(payload))
                existing = connection.execute(
                    """
                    SELECT source_selection_session_id, candidate_set_digest, stored_digest
                    FROM workforce_federation_source_sessions
                    WHERE federated_selection_session_id = ? AND source = ?
                    """,
                    (session_id, source),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["source_selection_session_id"] != source_session_id
                        or existing["candidate_set_digest"] != candidate_digest
                        or existing["stored_digest"] != stored_digest
                    ):
                        raise FederationSessionError("source_candidate_set_immutable")
                    continue
                connection.execute(
                    """
                    INSERT INTO workforce_federation_source_sessions(
                        federated_selection_session_id, source, source_selection_session_id,
                        candidate_set_digest, candidate_set_json, stored_digest
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, source, source_session_id, candidate_digest, payload, stored_digest),
                )

    def source_candidate_set(
        self,
        selection_session_id: str,
        source: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        result = self.get(selection_session_id, now=now)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT candidate_set_json, stored_digest
                FROM workforce_federation_source_sessions
                WHERE federated_selection_session_id = ? AND source = ?
                """,
                (selection_session_id, source),
            ).fetchone()
        if row is None:
            raise FederationSessionError("source_candidate_set_not_found")
        candidate_set = json.loads(row["candidate_set_json"])
        if canonical_digest(candidate_set) != row["stored_digest"]:
            raise FederationSessionError("stored_source_candidate_set_digest_mismatch")
        self._validate_source_candidate_set(result, source, candidate_set)
        return candidate_set

    def save_federated_selection(
        self,
        selection: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        expected_keys = {
            "schemaVersion", "status", "federationDigest", "selectionSessionId",
            "candidateSetDigest", "workOrderDigest", "selectionDigest",
            "selectionValidation", "selectedSourcePins", "federatedSelectionDigest",
        }
        if (
            not isinstance(selection, Mapping)
            or set(selection) != expected_keys
            or selection.get("schemaVersion") != "agentlas.workforce-federated-selection-validation.v1"
            or selection.get("status") != "accepted"
        ):
            raise FederationSessionError("federated_selection_not_accepted")
        session_id = str(selection.get("selectionSessionId") or "")
        result = self.get(session_id, now=now)
        pinned_work_order = self.work_order(session_id, now=now)
        validation = selection.get("selectionValidation")
        receipt = validation.get("receipt") if isinstance(validation, Mapping) else None
        if (
            selection.get("federationDigest") != result.get("federationDigest")
            or selection.get("candidateSetDigest") != result["candidateSet"].get("candidateSetDigest")
            or selection.get("workOrderDigest") != canonical_digest(pinned_work_order)
            or not isinstance(selection.get("selectionDigest"), str)
            or not isinstance(validation, Mapping)
            or not isinstance(receipt, Mapping)
            or receipt.get("selectionDigest") != selection.get("selectionDigest")
            or receipt.get("requestExpansionForSlots") != []
            or selection.get("federatedSelectionDigest")
            != canonical_digest(
                {key: value for key, value in selection.items() if key != "federatedSelectionDigest"}
            )
        ):
            raise FederationSessionError("federated_selection_binding_mismatch")
        pins = selection.get("selectedSourcePins")
        if not isinstance(pins, list) or not 1 <= len(pins) <= 128:
            raise FederationSessionError("federated_selection_source_pin_invalid")
        for pin in pins:
            if not isinstance(pin, Mapping):
                raise FederationSessionError("federated_selection_source_pin_invalid")
            authoritative = self.source_pin(
                session_id,
                slot_id=str(pin.get("slotId") or ""),
                agent_definition_id=str(pin.get("agentDefinitionId") or ""),
                agent_release_id=str(pin.get("agentReleaseId") or ""),
                now=now,
            )
            if dict(pin) != authoritative:
                raise FederationSessionError("federated_selection_source_pin_mismatch")
        payload = canonical_json(selection)
        if len(payload.encode("utf-8")) > 4 * 1024 * 1024:
            raise FederationSessionError("federated_selection_invalid")
        digest = str(selection["federatedSelectionDigest"])
        stored_digest = canonical_digest(selection)
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                """
                SELECT stored_digest FROM workforce_federated_selections
                WHERE federated_selection_session_id = ? AND federated_selection_digest = ?
                """,
                (session_id, digest),
            ).fetchone()
            if existing is not None:
                if existing["stored_digest"] != stored_digest:
                    raise FederationSessionError("federated_selection_immutable")
                return {"status": "already_pinned", "federatedSelectionDigest": digest}
            connection.execute(
                """
                INSERT INTO workforce_federated_selections(
                    federated_selection_session_id, federated_selection_digest,
                    selection_json, stored_digest
                ) VALUES (?, ?, ?, ?)
                """,
                (session_id, digest, payload, stored_digest),
            )
        return {"status": "pinned", "federatedSelectionDigest": digest}

    def get_federated_selection(
        self,
        selection_session_id: str,
        federated_selection_digest: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.get(selection_session_id, now=now)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT selection_json, stored_digest FROM workforce_federated_selections
                WHERE federated_selection_session_id = ? AND federated_selection_digest = ?
                """,
                (selection_session_id, federated_selection_digest),
            ).fetchone()
        if row is None:
            raise FederationSessionError("federated_selection_not_pinned")
        selection = json.loads(row["selection_json"])
        if canonical_digest(selection) != row["stored_digest"]:
            raise FederationSessionError("stored_federated_selection_digest_mismatch")
        return selection

    def get(
        self,
        selection_session_id: str,
        *,
        now: datetime | None = None,
        allow_expired: bool = False,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT result_json, result_digest, expires_at FROM workforce_federation_sessions WHERE selection_session_id = ?",
                (selection_session_id,),
            ).fetchone()
        if row is None:
            raise FederationSessionError("federation_session_not_found")
        result = json.loads(row["result_json"])
        if canonical_digest(result) != row["result_digest"]:
            raise FederationSessionError("stored_federation_digest_mismatch")
        validate_federation_result(result, lineage_verifier=self.lineage_verifier, now=now)
        try:
            expiry = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise FederationSessionError("stored_federation_expiry_invalid") from exc
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None or clock.utcoffset() is None:
            raise FederationSessionError("federation_clock_must_be_timezone_aware")
        if not allow_expired and expiry <= clock.astimezone(timezone.utc):
            raise FederationSessionError("federation_session_expired")
        return result

    def purge_expired(self, *, now: datetime | None = None) -> int:
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None or clock.utcoffset() is None:
            raise FederationSessionError("federation_clock_must_be_timezone_aware")
        cutoff = clock.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM workforce_federation_sessions WHERE expires_at <= ?",
                (cutoff,),
            )
        return int(cursor.rowcount)

    def source_pin(
        self,
        selection_session_id: str,
        *,
        slot_id: str,
        agent_definition_id: str,
        agent_release_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        result = self.get(selection_session_id, now=now)
        provenance = next(
            (
                row
                for row in result["candidateProvenance"]
                if row.get("slotId") == slot_id
                and row.get("agentDefinitionId") == agent_definition_id
                and row.get("selectedAgentReleaseId") == agent_release_id
            ),
            None,
        )
        if not isinstance(provenance, Mapping):
            raise FederationSessionError("selected_release_source_pin_missing")
        source = str(provenance.get("selectedSource") or "")
        appearance = next(
            (
                row
                for row in provenance.get("appearances") or []
                if isinstance(row, Mapping)
                and row.get("source") == source
                and row.get("agentReleaseId") == agent_release_id
            ),
            None,
        )
        receipt = next(
            (
                row
                for row in result["sourceReceipts"]
                if isinstance(row, Mapping) and row.get("source") == source and row.get("status") == "succeeded"
            ),
            None,
        )
        if not isinstance(appearance, Mapping) or not isinstance(receipt, Mapping):
            raise FederationSessionError("selected_release_source_pin_missing")
        if appearance.get("candidateSetDigest") != receipt.get("candidateSetDigest"):
            raise FederationSessionError("selected_release_source_pin_mismatch")
        pin = {
            "schemaVersion": WORKFORCE_SOURCE_PIN_SCHEMA,
            "federationDigest": result["federationDigest"],
            "federatedSelectionSessionId": selection_session_id,
            "slotId": slot_id,
            "source": source,
            "sourceSelectionSessionId": receipt["selectionSessionId"],
            "sourceCandidateSetDigest": receipt["candidateSetDigest"],
            "agentDefinitionId": agent_definition_id,
            "agentReleaseId": agent_release_id,
            "releaseVersion": appearance["releaseVersion"],
            "packageHash": appearance["packageHash"],
            "contentDigest": appearance["contentDigest"],
            "entityKind": appearance["entityKind"],
            "lineageAttestation": appearance.get("lineageAttestation"),
        }
        pin["sourcePinDigest"] = canonical_digest(pin)
        return pin


__all__ = [
    "FederationSessionError",
    "FederationSessionStore",
    "WORKFORCE_SOURCE_PIN_SCHEMA",
    "default_federation_store_path",
]
