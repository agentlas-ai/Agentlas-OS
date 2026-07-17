"""Durable exact-pin receipts for idempotent Workforce preparation.

The cache is intentionally narrower than a runtime cache.  A row is reusable
only for one authenticated account partition, one caller-authored prepare
attempt, one federated/source session, and one exact source pin.  It never
looks up by slug, release alone, or semantic similarity.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .contracts import canonical_digest, canonical_json


WORKFORCE_PREPARE_ATTEMPT_SCHEMA = "agentlas.workforce-prepare-attempt.v1"
WORKFORCE_PREPARE_PIN_BINDING_SCHEMA = "agentlas.workforce-prepare-pin-binding.v1"
WORKFORCE_SOURCE_FETCH_IDEMPOTENCY_SCHEMA = "agentlas.workforce-source-fetch-idempotency.v1"

_MAX_CACHE_ENTRIES = 512
_MAX_CACHE_BYTES = 512 * 1024 * 1024
_MAX_ENTRY_BYTES = 64 * 1024 * 1024
_CLAIM_LEASE_SECONDS = 120
_MAX_CACHE_LIFETIME = timedelta(minutes=30)
_SOURCE_BUNDLE_RECEIPT_SCHEMA = "agentlas.workforce-source-bundle-verification.v1"


class WorkforcePrepareCacheError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _clock(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise WorkforcePrepareCacheError("prepare_cache_clock_must_be_timezone_aware")
    return result.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted")
    return result.astimezone(timezone.utc)


def _sha256(value: Any, *, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise WorkforcePrepareCacheError(code)
    return value


def prepare_attempt_payload(
    occurrence_id: str,
    *,
    work_order_digest: str,
    selection_digest: str,
    federated_selection_digest: str,
    selected_source_pin_digests: Sequence[str],
) -> dict[str, Any]:
    """Build the only accepted caller/Core preparation idempotency envelope."""

    if (
        not isinstance(occurrence_id, str)
        or not occurrence_id.strip()
        or len(occurrence_id.encode("utf-8")) > 512
        or "\x00" in occurrence_id
    ):
        raise WorkforcePrepareCacheError("prepare_occurrence_id_invalid")
    pin_digests = [
        _sha256(value, code="prepare_source_pin_digest_invalid")
        for value in selected_source_pin_digests
    ]
    if not 1 <= len(pin_digests) <= 128 or len(set(pin_digests)) != len(pin_digests):
        raise WorkforcePrepareCacheError("prepare_source_pin_digest_invalid")
    payload: dict[str, Any] = {
        "schemaVersion": WORKFORCE_PREPARE_ATTEMPT_SCHEMA,
        "occurrenceId": occurrence_id,
        "workOrderDigest": _sha256(work_order_digest, code="prepare_work_order_digest_invalid"),
        "selectionDigest": _sha256(selection_digest, code="prepare_selection_digest_invalid"),
        "federatedSelectionDigest": _sha256(
            federated_selection_digest,
            code="prepare_federated_selection_digest_invalid",
        ),
        "selectedSourcePinDigests": pin_digests,
    }
    payload["idempotencyKey"] = canonical_digest(payload)
    return payload


def validate_prepare_attempt(
    value: Mapping[str, Any],
    *,
    work_order: Mapping[str, Any],
    selection: Mapping[str, Any],
    federated_selection: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkforcePrepareCacheError("prepare_idempotency_required")
    required = {
        "schemaVersion", "occurrenceId", "workOrderDigest", "selectionDigest",
        "federatedSelectionDigest", "selectedSourcePinDigests", "idempotencyKey",
    }
    if set(value) != required or value.get("schemaVersion") != WORKFORCE_PREPARE_ATTEMPT_SCHEMA:
        raise WorkforcePrepareCacheError("prepare_idempotency_invalid")
    pins = federated_selection.get("selectedSourcePins")
    if not isinstance(pins, list):
        raise WorkforcePrepareCacheError("prepare_idempotency_invalid")
    expected = prepare_attempt_payload(
        str(value.get("occurrenceId") or ""),
        work_order_digest=canonical_digest(work_order),
        selection_digest=canonical_digest(selection),
        federated_selection_digest=str(federated_selection.get("federatedSelectionDigest") or ""),
        selected_source_pin_digests=[
            str(pin.get("sourcePinDigest") or "") if isinstance(pin, Mapping) else ""
            for pin in pins
        ],
    )
    if dict(value) != expected:
        raise WorkforcePrepareCacheError("prepare_idempotency_binding_mismatch")
    return expected


def source_pin_binding(pin: Mapping[str, Any]) -> dict[str, Any]:
    source = str(pin.get("source") or "")
    if source not in {"local", "cloud", "hub"}:
        raise WorkforcePrepareCacheError("prepare_source_pin_binding_invalid")
    binding = {
        "schemaVersion": WORKFORCE_PREPARE_PIN_BINDING_SCHEMA,
        "source": source,
        "sourceSelectionSessionId": str(pin.get("sourceSelectionSessionId") or ""),
        "sourceCandidateSetDigest": _sha256(
            pin.get("sourceCandidateSetDigest"),
            code="prepare_source_pin_binding_invalid",
        ),
        "sourcePinDigest": _sha256(
            pin.get("sourcePinDigest"),
            code="prepare_source_pin_binding_invalid",
        ),
    }
    if not binding["sourceSelectionSessionId"]:
        raise WorkforcePrepareCacheError("prepare_source_pin_binding_invalid")
    return binding


def source_fetch_idempotency(
    prepare_attempt_digest: str,
    pin: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind one remote fetch to both the prepare attempt and exact pin."""

    binding = source_pin_binding(pin)
    exact_fetch = {
        "source": binding["source"],
        "sourceSelectionSessionId": pin.get("sourceSelectionSessionId"),
        "sourceCandidateSetDigest": pin.get("sourceCandidateSetDigest"),
        "agentDefinitionId": pin.get("agentDefinitionId"),
        "agentReleaseId": pin.get("agentReleaseId"),
        "releaseVersion": pin.get("releaseVersion"),
        "packageHash": pin.get("packageHash"),
        "contentDigest": pin.get("contentDigest"),
        "entityKind": pin.get("entityKind"),
    }
    fetch_binding_digest = canonical_digest(exact_fetch)
    payload = {
        "schemaVersion": WORKFORCE_SOURCE_FETCH_IDEMPOTENCY_SCHEMA,
        "prepareAttemptDigest": _sha256(
            prepare_attempt_digest,
            code="prepare_idempotency_invalid",
        ),
        "selectedSourcePinDigest": binding["sourcePinDigest"],
        "sourceFetchBindingDigest": fetch_binding_digest,
    }
    payload["sourceFetchIdempotencyKey"] = canonical_digest(payload)
    return payload


def _assert_verified_response(
    response: Mapping[str, Any],
    pin: Mapping[str, Any],
    fetch_idempotency: Mapping[str, Any],
) -> None:
    bundle = response.get("runtimeBundle")
    receipt = response.get("verificationReceipt")
    required_receipt_keys = {
        "schemaVersion", "status", "verification", "source",
        "sourceSelectionSessionId", "sourceCandidateSetDigest",
        "agentDefinitionId", "agentReleaseId", "releaseVersion",
        "packageHash", "contentDigest", "entityKind",
        "prepareAttemptDigest", "selectedSourcePinDigest",
        "sourceFetchBindingDigest", "sourceFetchIdempotencyKey",
        "receiptDigest",
    }
    if (
        not isinstance(bundle, Mapping)
        or not isinstance(receipt, Mapping)
        or set(receipt) != required_receipt_keys
        or receipt.get("schemaVersion") != _SOURCE_BUNDLE_RECEIPT_SCHEMA
        or receipt.get("status") != "verified"
        or receipt.get("verification") not in {"verified_transport", "verified_signature"}
        or receipt.get("source") != pin.get("source")
        or receipt.get("receiptDigest")
        != canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    ):
        raise WorkforcePrepareCacheError("prepare_receipt_cache_unverified")
    for field in (
        "sourceSelectionSessionId", "sourceCandidateSetDigest", "agentDefinitionId",
        "agentReleaseId", "releaseVersion", "packageHash", "contentDigest", "entityKind",
    ):
        if receipt.get(field) != pin.get(field):
            raise WorkforcePrepareCacheError("prepare_receipt_cache_unverified")
    for field in (
        "prepareAttemptDigest", "selectedSourcePinDigest",
        "sourceFetchBindingDigest", "sourceFetchIdempotencyKey",
    ):
        if receipt.get(field) != fetch_idempotency.get(field):
            raise WorkforcePrepareCacheError("prepare_receipt_cache_unverified")
    if any(
        bundle.get(field) != pin.get(field)
        for field in ("agentReleaseId", "packageHash", "contentDigest")
    ):
        raise WorkforcePrepareCacheError("prepare_receipt_cache_unverified")


class WorkforcePrepareReceiptCache:
    """SQLite ledger for verified remote bundle/receipt pairs."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        self._memory_only = str(self.path) == ":memory:"
        self._prepare_private_store_path()
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workforce_prepare_attempts (
                    auth_partition TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    binding_digest TEXT NOT NULL,
                    selection_session_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    pin_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(auth_partition, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS workforce_prepare_bundle_receipts (
                    auth_partition TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    source_pin_digest TEXT NOT NULL,
                    pin_binding_json TEXT NOT NULL,
                    pin_binding_digest TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'empty',
                    claim_owner TEXT,
                    claim_expires_at TEXT,
                    response_json TEXT,
                    response_digest TEXT,
                    response_bytes INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(auth_partition, idempotency_key, source_pin_digest),
                    FOREIGN KEY(auth_partition, idempotency_key)
                      REFERENCES workforce_prepare_attempts(auth_partition, idempotency_key)
                      ON DELETE CASCADE,
                    CHECK(state IN ('empty', 'pending', 'verified'))
                );
                CREATE INDEX IF NOT EXISTS workforce_prepare_attempt_expiry
                  ON workforce_prepare_attempts(expires_at);
                """
            )

    def _prepare_private_store_path(self) -> None:
        """Create/re-harden the local receipt store without following links.

        Only a directory created by this cache is made private.  A caller may
        deliberately place the database in an existing shared directory (for
        example, a managed runtime directory under ``/tmp``); changing that
        directory's mode would break unrelated applications and is outside the
        cache's authority.  The database and SQLite sidecars remain private in
        either case.
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
                    # Another process won the creation race.  It owns the
                    # directory mode; validate the node but do not mutate it.
                    pass
            self._assert_safe_parent_chain(parent)
            parent_stat = parent.lstat()
            if not stat.S_ISDIR(parent_stat.st_mode) or stat.S_ISLNK(parent_stat.st_mode):
                raise WorkforcePrepareCacheError("prepare_receipt_cache_unsafe_path")
            if os.name == "posix" and parent_created:
                os.chmod(parent, 0o700)

            if self.path.is_symlink():
                raise WorkforcePrepareCacheError("prepare_receipt_cache_unsafe_path")
            if not self.path.exists():
                flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(self.path, flags, 0o600)
                os.close(descriptor)
            self._harden_private_store_files()
        except WorkforcePrepareCacheError:
            raise
        except (OSError, ValueError) as exc:
            raise WorkforcePrepareCacheError("prepare_receipt_cache_unavailable") from exc

    @staticmethod
    def _assert_safe_parent_chain(parent: Path) -> None:
        """Reject link traversal anywhere above the database, not only at leaf."""

        if ".." in parent.parts:
            raise WorkforcePrepareCacheError("prepare_receipt_cache_unsafe_path")
        absolute = Path(os.path.abspath(str(parent)))
        current = Path(absolute.anchor)
        for component in absolute.parts[1:]:
            current /= component
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                # Permit only immutable system aliases (macOS /tmp and /var),
                # never a caller-owned directory link.
                if os.name == "posix" and metadata.st_uid == 0:
                    continue
                raise WorkforcePrepareCacheError("prepare_receipt_cache_unsafe_path")
            if not stat.S_ISDIR(metadata.st_mode):
                raise WorkforcePrepareCacheError("prepare_receipt_cache_unsafe_path")

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
                raise WorkforcePrepareCacheError("prepare_receipt_cache_unsafe_path")
            try:
                metadata = candidate.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise WorkforcePrepareCacheError("prepare_receipt_cache_unsafe_path")
            if getattr(metadata, "st_nlink", 1) != 1:
                raise WorkforcePrepareCacheError("prepare_receipt_cache_unsafe_path")
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
        except WorkforcePrepareCacheError:
            if connection is not None:
                connection.close()
            raise
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise WorkforcePrepareCacheError("prepare_receipt_cache_unavailable") from exc

    @staticmethod
    def _begin(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _commit(connection: sqlite3.Connection) -> None:
        connection.commit()

    def _purge(self, connection: sqlite3.Connection, clock: datetime) -> None:
        connection.execute(
            "DELETE FROM workforce_prepare_attempts WHERE expires_at <= ?",
            (_timestamp(clock),),
        )

    def bind_attempt(
        self,
        *,
        auth_partition: str,
        prepare_attempt: Mapping[str, Any],
        selection_session_id: str,
        pins: Sequence[Mapping[str, Any]],
        session_expires_at: datetime,
        now: datetime | None = None,
    ) -> None:
        partition = _sha256(auth_partition, code="prepare_auth_partition_invalid")
        key = _sha256(prepare_attempt.get("idempotencyKey"), code="prepare_idempotency_invalid")
        binding_digest = canonical_digest(prepare_attempt)
        clock = _clock(now)
        session_expiry = _clock(session_expires_at)
        expires_at = min(session_expiry, clock + _MAX_CACHE_LIFETIME)
        if expires_at <= clock:
            raise WorkforcePrepareCacheError("prepare_receipt_cache_expired")
        pin_bindings = [source_pin_binding(pin) for pin in pins]
        if not pin_bindings or len(pin_bindings) != len({row["sourcePinDigest"] for row in pin_bindings}):
            raise WorkforcePrepareCacheError("prepare_source_pin_binding_invalid")

        try:
            with closing(self._connect()) as connection:
                self._begin(connection)
                self._purge(connection, clock)
                existing = connection.execute(
                    """
                    SELECT binding_digest, selection_session_id, expires_at, pin_count
                    FROM workforce_prepare_attempts
                    WHERE auth_partition = ? AND idempotency_key = ?
                    """,
                    (partition, key),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["binding_digest"] != binding_digest
                        or existing["selection_session_id"] != selection_session_id
                        or int(existing["pin_count"]) != len(pin_bindings)
                    ):
                        raise WorkforcePrepareCacheError("prepare_idempotency_conflict")
                    rows = connection.execute(
                        """
                        SELECT source_pin_digest, pin_binding_json, pin_binding_digest
                        FROM workforce_prepare_bundle_receipts
                        WHERE auth_partition = ? AND idempotency_key = ?
                        """,
                        (partition, key),
                    ).fetchall()
                    expected = {
                        str(row["sourcePinDigest"]): canonical_json(row)
                        for row in pin_bindings
                    }
                    actual = {
                        str(row["source_pin_digest"]): str(row["pin_binding_json"])
                        for row in rows
                    }
                    if expected != actual or any(
                        row["pin_binding_digest"]
                        != canonical_digest(json.loads(str(row["pin_binding_json"])))
                        for row in rows
                    ):
                        raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted")
                    self._commit(connection)
                    return

                count = int(connection.execute(
                    "SELECT COUNT(*) FROM workforce_prepare_bundle_receipts"
                ).fetchone()[0])
                if count + len(pin_bindings) > _MAX_CACHE_ENTRIES:
                    raise WorkforcePrepareCacheError("prepare_receipt_cache_full")
                stamp = _timestamp(clock)
                connection.execute(
                    """
                    INSERT INTO workforce_prepare_attempts(
                        auth_partition, idempotency_key, binding_digest,
                        selection_session_id, expires_at, pin_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        partition, key, binding_digest, selection_session_id,
                        _timestamp(expires_at), len(pin_bindings), stamp,
                    ),
                )
                for binding in pin_bindings:
                    payload = canonical_json(binding)
                    connection.execute(
                        """
                        INSERT INTO workforce_prepare_bundle_receipts(
                            auth_partition, idempotency_key, source_pin_digest,
                            pin_binding_json, pin_binding_digest, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            partition, key, binding["sourcePinDigest"], payload,
                            canonical_digest(binding), stamp,
                        ),
                    )
                self._commit(connection)
        except WorkforcePrepareCacheError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WorkforcePrepareCacheError("prepare_receipt_cache_unavailable") from exc

    def claim(
        self,
        *,
        auth_partition: str,
        idempotency_key: str,
        pin: Mapping[str, Any],
        now: datetime | None = None,
    ) -> tuple[str, str | dict[str, Any] | None]:
        partition = _sha256(auth_partition, code="prepare_auth_partition_invalid")
        key = _sha256(idempotency_key, code="prepare_idempotency_invalid")
        binding = source_pin_binding(pin)
        clock = _clock(now)
        try:
            with closing(self._connect()) as connection:
                self._begin(connection)
                self._purge(connection, clock)
                row = connection.execute(
                    """
                    SELECT pin_binding_json, pin_binding_digest, state,
                           claim_owner, claim_expires_at, response_json,
                           response_digest, response_bytes
                    FROM workforce_prepare_bundle_receipts
                    WHERE auth_partition = ? AND idempotency_key = ? AND source_pin_digest = ?
                    """,
                    (partition, key, binding["sourcePinDigest"]),
                ).fetchone()
                if row is None:
                    raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted")
                pin_payload = canonical_json(binding)
                if (
                    row["pin_binding_json"] != pin_payload
                    or row["pin_binding_digest"] != canonical_digest(binding)
                ):
                    raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted")
                state = str(row["state"])
                if state == "verified":
                    response_json = row["response_json"]
                    if not isinstance(response_json, str):
                        raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted")
                    if len(response_json.encode("utf-8")) != int(row["response_bytes"]):
                        raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted")
                    response = json.loads(response_json)
                    if (
                        not isinstance(response, Mapping)
                        or canonical_digest(response) != row["response_digest"]
                        or canonical_json(response) != response_json
                    ):
                        raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted")
                    self._commit(connection)
                    return "cached", dict(response)
                if state == "pending":
                    lease = _parse_timestamp(row["claim_expires_at"])
                    if lease > clock:
                        self._commit(connection)
                        return "pending", None
                elif state != "empty":
                    raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted")
                owner = uuid4().hex
                connection.execute(
                    """
                    UPDATE workforce_prepare_bundle_receipts
                    SET state = 'pending', claim_owner = ?, claim_expires_at = ?, updated_at = ?
                    WHERE auth_partition = ? AND idempotency_key = ? AND source_pin_digest = ?
                    """,
                    (
                        owner,
                        _timestamp(clock + timedelta(seconds=_CLAIM_LEASE_SECONDS)),
                        _timestamp(clock), partition, key, binding["sourcePinDigest"],
                    ),
                )
                self._commit(connection)
                return "claimed", owner
        except WorkforcePrepareCacheError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WorkforcePrepareCacheError("prepare_receipt_cache_unavailable") from exc

    def store_verified(
        self,
        *,
        auth_partition: str,
        idempotency_key: str,
        pin: Mapping[str, Any],
        fetch_idempotency: Mapping[str, Any],
        claim_owner: str,
        response: Mapping[str, Any],
        now: datetime | None = None,
    ) -> None:
        partition = _sha256(auth_partition, code="prepare_auth_partition_invalid")
        key = _sha256(idempotency_key, code="prepare_idempotency_invalid")
        binding = source_pin_binding(pin)
        clock = _clock(now)
        _assert_verified_response(response, pin, fetch_idempotency)
        response_json = canonical_json(response)
        response_bytes = len(response_json.encode("utf-8"))
        if response_bytes > _MAX_ENTRY_BYTES:
            raise WorkforcePrepareCacheError("prepare_receipt_cache_entry_too_large")
        try:
            with closing(self._connect()) as connection:
                self._begin(connection)
                self._purge(connection, clock)
                row = connection.execute(
                    """
                    SELECT state, claim_owner, pin_binding_json, pin_binding_digest,
                           response_bytes
                    FROM workforce_prepare_bundle_receipts
                    WHERE auth_partition = ? AND idempotency_key = ? AND source_pin_digest = ?
                    """,
                    (partition, key, binding["sourcePinDigest"]),
                ).fetchone()
                if row is None or row["state"] != "pending" or row["claim_owner"] != claim_owner:
                    raise WorkforcePrepareCacheError("prepare_receipt_cache_claim_lost")
                if (
                    row["pin_binding_json"] != canonical_json(binding)
                    or row["pin_binding_digest"] != canonical_digest(binding)
                ):
                    raise WorkforcePrepareCacheError("prepare_receipt_cache_corrupted")
                total = int(connection.execute(
                    "SELECT COALESCE(SUM(response_bytes), 0) FROM workforce_prepare_bundle_receipts"
                ).fetchone()[0])
                if total - int(row["response_bytes"]) + response_bytes > _MAX_CACHE_BYTES:
                    raise WorkforcePrepareCacheError("prepare_receipt_cache_full")
                connection.execute(
                    """
                    UPDATE workforce_prepare_bundle_receipts
                    SET state = 'verified', claim_owner = NULL, claim_expires_at = NULL,
                        response_json = ?, response_digest = ?, response_bytes = ?, updated_at = ?
                    WHERE auth_partition = ? AND idempotency_key = ? AND source_pin_digest = ?
                    """,
                    (
                        response_json, canonical_digest(response), response_bytes,
                        _timestamp(clock), partition, key, binding["sourcePinDigest"],
                    ),
                )
                self._commit(connection)
        except WorkforcePrepareCacheError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise WorkforcePrepareCacheError("prepare_receipt_cache_unavailable") from exc

    def release_claim(
        self,
        *,
        auth_partition: str,
        idempotency_key: str,
        pin: Mapping[str, Any],
        claim_owner: str,
        now: datetime | None = None,
    ) -> None:
        partition = _sha256(auth_partition, code="prepare_auth_partition_invalid")
        key = _sha256(idempotency_key, code="prepare_idempotency_invalid")
        binding = source_pin_binding(pin)
        clock = _clock(now)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    UPDATE workforce_prepare_bundle_receipts
                    SET state = 'empty', claim_owner = NULL, claim_expires_at = NULL,
                        updated_at = ?
                    WHERE auth_partition = ? AND idempotency_key = ? AND source_pin_digest = ?
                      AND state = 'pending' AND claim_owner = ?
                    """,
                    (
                        _timestamp(clock), partition, key,
                        binding["sourcePinDigest"], claim_owner,
                    ),
                )
        except (OSError, sqlite3.Error) as exc:
            raise WorkforcePrepareCacheError("prepare_receipt_cache_unavailable") from exc


__all__ = [
    "WORKFORCE_PREPARE_ATTEMPT_SCHEMA",
    "WORKFORCE_PREPARE_PIN_BINDING_SCHEMA",
    "WORKFORCE_SOURCE_FETCH_IDEMPOTENCY_SCHEMA",
    "WorkforcePrepareCacheError",
    "WorkforcePrepareReceiptCache",
    "prepare_attempt_payload",
    "source_fetch_idempotency",
    "source_pin_binding",
    "validate_prepare_attempt",
]
