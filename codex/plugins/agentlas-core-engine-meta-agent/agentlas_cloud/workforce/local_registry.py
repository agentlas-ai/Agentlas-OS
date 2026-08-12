"""OS-owned registry and projection outbox for explicitly imported agents."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from ..networking.bootstrap import atomic_write_json, networking_home, read_json
from ..networking.card_lint import effective_status, routing_ineligibility_reasons
from .compiler import compile_workforce_profile
from .contracts import canonical_digest, verify_profile_integrity
from .execution import WORKFORCE_EXECUTION_GRAPH_SCHEMA
from .federation import (
    WORKFORCE_LINEAGE_ATTESTATION_SCHEMA,
    validate_lineage_attestation,
    workforce_lineage_claim_digest,
)
from .package_adapter import (
    PackageAdaptationError,
    inspect_package,
    materialize_package,
    snapshot_package_hash,
)

try:
    import fcntl

    def _lock(handle: Any) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _unlock(handle: Any) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
except ImportError:  # pragma: no cover - Windows packaged runtime
    import msvcrt

    def _lock(handle: Any) -> None:
        handle.seek(0)
        if not handle.read(1):
            handle.seek(0)
            handle.write("0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock(handle: Any) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


LOCAL_REGISTRATION_SCHEMA = "agentlas.local-workforce-registration.v1"
LOCAL_PROJECTION_EVENT_SCHEMA = "agentlas.local-workforce-projection-event.v1"
LOCAL_VERIFIED_IDENTITY_SCHEMA = "agentlas.local-workforce-verified-identity.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _detached(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


_WORKER_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._:@-]+")
_TEAM_MEMBER_ENTRY_NAMES = ("agent.md", "AGENTS.md")
_TEAM_MEMBER_MAX = 32


def _local_team_execution_graph(
    *,
    package_root: Path,
    entry_relative: str,
    manager_content: str,
) -> dict[str, Any]:
    """Project a local team package's organization into an execution graph.

    The manager is the team's own entrypoint directive; workers are the member
    directives under `agents/<member>/`. Contents are read through the same
    bounded no-follow reader as the entrypoint, so a symlinked or oversized
    member file fails closed instead of escaping the package.
    """

    members_root = package_root / "agents"
    workers: list[dict[str, str]] = []
    if members_root.is_dir() and not members_root.is_symlink():
        for member_dir in sorted(members_root.iterdir(), key=lambda item: item.name):
            if not member_dir.is_dir() or member_dir.is_symlink():
                continue
            entry = next(
                (
                    member_dir / name
                    for name in _TEAM_MEMBER_ENTRY_NAMES
                    if (member_dir / name).is_file() and not (member_dir / name).is_symlink()
                ),
                None,
            )
            if entry is None:
                continue
            relative = entry.relative_to(package_root).as_posix()
            if relative == entry_relative:
                continue
            content = _bounded_nofollow_text(entry, maximum=200_000)
            if not content.strip():
                continue
            worker_id = _WORKER_ID_SAFE_RE.sub("-", member_dir.name).strip("-") or member_dir.name
            workers.append({"id": worker_id[:255], "path": relative, "content": content})
    if not workers:
        # Refuse to invent an organization. A team package with no readable
        # member directive is a packaging defect, and reporting it here is what
        # lets the caller see the real cause.
        raise KeyError("local_team_execution_graph_unavailable")
    if len(workers) > _TEAM_MEMBER_MAX:
        raise KeyError("local_team_execution_graph_too_large")
    return {
        "schemaVersion": WORKFORCE_EXECUTION_GRAPH_SCHEMA,
        "manager": {"path": entry_relative, "content": manager_content},
        "workers": workers,
    }


def _bounded_nofollow_text(path: Path, *, maximum: int) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise KeyError("local_runtime_bundle_file_invalid") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise KeyError("local_runtime_bundle_file_invalid")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            block = os.read(descriptor, min(65_536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        if len(raw) > maximum:
            raise KeyError("local_runtime_bundle_file_invalid")
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KeyError("local_runtime_bundle_file_invalid") from exc
    finally:
        os.close(descriptor)


def default_local_workforce_home() -> Path:
    override = os.environ.get("AGENTLAS_LOCAL_WORKFORCE_HOME")
    return Path(override).expanduser() if override else networking_home().parent / "workforce" / "local"


class LocalWorkforceRegistry:
    """Register one explicit root at a time; never scan a home directory."""

    def __init__(self, home: Path | str | None = None, *, user_home: Path | str | None = None):
        self.home = (Path(home) if home else default_local_workforce_home()).expanduser().resolve()
        self.user_home = (Path(user_home) if user_home else Path.home()).expanduser().resolve()
        for relative in ("definitions", "releases", "outbox", "quarantine", "staging"):
            (self.home / relative).mkdir(parents=True, exist_ok=True)
        # Releases dropped by the last active_profiles() integrity pass.
        self.last_integrity_drops = 0

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with open(self.home / ".registry.lock", "a+", encoding="utf-8") as handle:
            _lock(handle)
            try:
                yield
            finally:
                _unlock(handle)

    def _explicit_root(self, source_root: Path | str) -> Path:
        root = Path(source_root).expanduser().resolve()
        filesystem_root = Path(root.anchor).resolve()
        if root in {filesystem_root, self.user_home}:
            raise PackageAdaptationError(
                "source_scope_forbidden",
                "register a specific package root",
                "A filesystem root or your home directory is too broad to import. Register the folder that holds the agent or team itself.",
            )
        try:
            self.home.relative_to(root)
        except ValueError:
            pass
        else:
            raise PackageAdaptationError(
                "source_scope_forbidden",
                "package cannot contain its registry",
                f"This root contains the local Workforce registry at {self.home}. Register a folder that does not enclose it.",
            )
        return root

    def _definition_path(self, definition_id: str) -> Path:
        return self.home / "definitions" / f"{_token(definition_id)}.json"

    def _release_dir(self, definition_id: str, release_id: str) -> Path:
        return self.home / "releases" / _token(definition_id) / _token(release_id)

    def _records(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted((self.home / "definitions").glob("*.json")):
            value = read_json(path, default=None)
            if isinstance(value, Mapping):
                rows.append(dict(value))
        return rows

    def _by_source(self, root: Path) -> dict[str, Any] | None:
        return next((row for row in self._records() if row.get("sourceRoot") == str(root)), None)

    def _find(self, target: Path | str) -> dict[str, Any] | None:
        text = str(target)
        if text.startswith("definition:"):
            value = read_json(self._definition_path(text), default=None)
            return dict(value) if isinstance(value, Mapping) else None
        try:
            return self._by_source(Path(text).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            return None

    def _next_cursor(self) -> int:
        path = self.home / "OUTBOX_CURSOR"
        try:
            cursor = int(path.read_text(encoding="utf-8")) + 1
        except (OSError, ValueError):
            cursor = 1
        fd, temporary = tempfile.mkstemp(dir=str(self.home), prefix=".cursor-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(str(cursor) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return cursor

    def _publish_event(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        cursor = self._next_cursor()
        base = {
            "schemaVersion": LOCAL_PROJECTION_EVENT_SCHEMA,
            "eventType": event_type,
            "cursor": cursor,
            "occurredAt": _now(),
            "payload": _detached(payload),
        }
        event = {
            **base,
            "eventId": "local-workforce-event:" + canonical_digest(base).split(":", 1)[1][:32],
        }
        atomic_write_json(self.home / "outbox" / f"{cursor:020d}.json", event)
        return event

    def _quarantine(self, source: Path | str, error: PackageAdaptationError) -> dict[str, Any]:
        """Refuse in words the caller can act on, not just a code and a digest.

        Two different surfaces are built here and they have different audiences.
        The projection event is replicated outward, so it stays digest-only: a
        local absolute path is the user's private data and must not leak into
        the outbox. The returned object is the answer to the person who just
        typed the path, so it echoes that path back and carries the human
        message the raise site already wrote plus its remediation. Returning
        only `error.code` dropped both and left a path typo reading as
        "quarantined / source_missing / sha256:…".
        """

        source_ref = str(source)
        payload = {
            "reasonCode": error.code,
            "sourceRefDigest": canonical_digest({"sourceRoot": source_ref}),
        }
        event = self._publish_event("quarantine", payload)
        # The outbox copy above stays digest-only (it replicates outward), but
        # quarantine/ never leaves this machine — and reconcile() runs in the
        # background, so the human-readable refusal returned below is never
        # seen by anyone. Storing only the digest here left the user with
        # "quarantine / source_secret_material_forbidden / sha256:…" and no way
        # to learn WHICH folder or WHY (measured 2026-08-12: three repeating
        # quarantine events, undiagnosable without recomputing digests).
        atomic_write_json(
            self.home / "quarantine" / f"{event['cursor']:020d}.json",
            {
                **event,
                "localDiagnostics": {
                    "sourceRoot": source_ref,
                    "message": str(error),
                    **({"remediation": error.remediation} if error.remediation else {}),
                },
            },
        )
        refusal = {
            "schemaVersion": LOCAL_REGISTRATION_SCHEMA,
            "status": "quarantined",
            "reasonCode": error.code,
            "sourceRoot": source_ref,
            "message": str(error),
            "projectionEvent": event,
        }
        if error.remediation:
            refusal["remediation"] = error.remediation
        return refusal

    def _routing_verdict(self, release_dir: Path) -> dict[str, Any]:
        """Read back the routing verdict a stored release was compiled with.

        The verdict lives in the release profile, which is what staffing reads,
        so every other surface derives it from there instead of keeping a second
        copy that can drift. Registries written before the demotion was recorded
        have `routingEligible: false` with nothing beside it; the OS-owned
        snapshot next to the profile is the exact package that was compiled, so
        the reason is re-derived from it rather than left blank.
        """

        profile = read_json(release_dir / "profile.json", default=None)
        operational = profile.get("operational") if isinstance(profile, Mapping) else None
        if not isinstance(operational, Mapping):
            return {}
        verdict: dict[str, Any] = {"routingEligible": bool(operational.get("routingEligible"))}
        if verdict["routingEligible"]:
            return verdict
        card = read_json(release_dir / "package" / ".agentlas" / "routing-card.json", default=None)
        reasons = [str(item) for item in operational.get("unavailableReasons") or []]
        if not reasons and isinstance(card, dict):
            reasons = routing_ineligibility_reasons(card)
        if isinstance(card, dict):
            verdict["routingStatus"] = effective_status(card)
        if reasons:
            verdict["routingStatusReason"] = "; ".join(reasons)
        return verdict

    def _replay(
        self,
        release_dir: Path,
        registration: Mapping[str, Any],
        source_root: Path,
    ) -> dict[str, Any]:
        """Replay a cached registration without replaying a silent demotion.

        Re-registering an unchanged package short-circuits to the stored
        receipt, so this is the second way a caller reaches "active but never
        staffed": a registry written before the demotion was recorded carries
        no routing verdict at all, and replaying it verbatim prints the same
        bare success the fresh path no longer prints.
        """

        replay = {**dict(registration), "status": "active", "idempotent": True}
        if "routingEligible" in replay:
            return replay
        replay.update(self._routing_verdict(release_dir))
        if replay.get("routingStatusReason"):
            replay["remediation"] = (
                f"Registered, but /hep-local will not staff it yet. Fix the above in "
                f"{source_root}/.agentlas/routing-card.json, then run `workforce local-register` again."
            )
        return replay

    def _identity(
        self,
        *,
        source_identity: str,
        package_hash: str,
        previous: Mapping[str, Any] | None,
        verified_identity: Mapping[str, Any] | None,
        identity_verifier: Callable[[str, str, Mapping[str, Any], Mapping[str, Any]], bool] | None,
    ) -> tuple[str, str, str, dict[str, str], str]:
        if previous and verified_identity is None:
            return (
                str(previous["agentDefinitionId"]),
                "",
                "",
                dict(previous["lineageAttestation"]),
                str(previous["sourceIdentity"]),
            )
        if verified_identity is not None:
            required = {
                "schemaVersion",
                "agentDefinitionId",
                "agentReleaseId",
                "releaseVersion",
                "packageHash",
                "contentDigest",
                "entityKind",
                "lineageAttestation",
            }
            if set(verified_identity) != required or not required <= set(verified_identity):
                raise PackageAdaptationError("verified_identity_invalid", "verified identity fields are invalid")
            if verified_identity.get("schemaVersion") != LOCAL_VERIFIED_IDENTITY_SCHEMA:
                raise PackageAdaptationError("verified_identity_invalid", "verified identity schema is invalid")
            if verified_identity.get("packageHash") != package_hash:
                raise PackageAdaptationError("verified_identity_package_mismatch", "verified package hash does not match")
            try:
                attestation = validate_lineage_attestation(verified_identity.get("lineageAttestation"))
            except ValueError as exc:
                raise PackageAdaptationError("verified_identity_invalid", "lineage attestation is invalid") from exc
            if previous and verified_identity.get("agentDefinitionId") != previous.get("agentDefinitionId"):
                raise PackageAdaptationError("verified_identity_invalid", "verified definition identity changed")
            appearance = {
                "source": "local",
                "agentReleaseId": verified_identity["agentReleaseId"],
                "releaseVersion": verified_identity["releaseVersion"],
                "packageHash": verified_identity["packageHash"],
                "contentDigest": verified_identity["contentDigest"],
                "entityKind": verified_identity["entityKind"],
                "lineageAttestation": attestation,
            }
            if (
                identity_verifier is None
                or attestation.get("claimDigest")
                != workforce_lineage_claim_digest(str(verified_identity["agentDefinitionId"]), appearance)
                or not isinstance(attestation.get("proof"), Mapping)
                or identity_verifier(
                    "local",
                    str(verified_identity["agentDefinitionId"]),
                    attestation,
                    appearance,
                )
                is not True
            ):
                raise PackageAdaptationError("verified_identity_unproven", "verified identity proof failed")
            return (
                str(verified_identity["agentDefinitionId"]),
                str(verified_identity["agentReleaseId"]),
                str(verified_identity["releaseVersion"]),
                attestation,
                f"verified:{attestation['lineageDigest']}",
            )
        definition_id = f"definition:local:{_token(source_identity)[:32]}"
        release_id = f"release:local:{_token(definition_id + ':' + package_hash)[:48]}"
        attestation = {
            "schemaVersion": WORKFORCE_LINEAGE_ATTESTATION_SCHEMA,
            "lineageDigest": canonical_digest({"sourceIdentity": source_identity}),
            "issuer": "agentlas-os-local-registry",
            "verification": "verified_local_registry",
        }
        return definition_id, release_id, package_hash.removeprefix("sha256:")[:12], attestation, source_identity

    def register(
        self,
        source_root: Path | str,
        *,
        verified_identity: Mapping[str, Any] | None = None,
        identity_verifier: Callable[[str, str, Mapping[str, Any], Mapping[str, Any]], bool] | None = None,
        managed_by: str = "explicit",
    ) -> dict[str, Any]:
        """Import one root; verified cross-source identity is API-only."""

        try:
            root = self._explicit_root(source_root)
        except PackageAdaptationError as exc:
            with self._locked():
                return self._quarantine(source_root, exc)
        with self._locked():
            previous = self._by_source(root)
            try:
                inspection = inspect_package(root)
                if verified_identity is not None and verified_identity.get("entityKind") != (
                    inspection.entity_kind if inspection.entity_kind in {"agent", "team", "group"} else "agent"
                ):
                    raise PackageAdaptationError("verified_identity_invalid", "verified entity kind differs from package")
                card_id = str((inspection.routing_card or {}).get("canonical_id") or (inspection.routing_card or {}).get("id") or "")
                source_identity = f"routing-card:{card_id}" if card_id else f"explicit-root:{root}"
                definition_id, release_id, release_version, attestation, stable_source_identity = self._identity(
                    source_identity=source_identity,
                    package_hash=inspection.package_hash,
                    previous=previous,
                    verified_identity=verified_identity,
                    identity_verifier=identity_verifier,
                )
                if previous:
                    if str(previous.get("sourceIdentity") or "").startswith("verified:"):
                        current_dir = self._release_dir(
                            str(previous["agentDefinitionId"]), str(previous["currentReleaseId"])
                        )
                        current_registration = read_json(current_dir / "registration.json", default={}) or {}
                        if current_registration.get("packageHash") == inspection.package_hash:
                            return self._replay(current_dir, current_registration, root)
                        if verified_identity is None:
                            raise PackageAdaptationError(
                                "verified_identity_required",
                                "a changed verified package requires a new verified identity receipt",
                            )
                    if verified_identity is None:
                        release_id = f"release:local:{_token(definition_id + ':' + inspection.package_hash)[:48]}"
                        release_version = inspection.package_hash.removeprefix("sha256:")[:12]
                existing = read_json(self._definition_path(definition_id), default=None)
                if isinstance(existing, Mapping) and existing.get("sourceRoot") != str(root) and existing.get("status") == "active":
                    raise PackageAdaptationError(
                        "identity_conflict",
                        "another active root claims this definition",
                        f"Another registered folder already owns this identity: {existing.get('sourceRoot')}. Remove it with `workforce local-remove`, or give this copy its own id in .agentlas/routing-card.json.",
                    )

                final_dir = self._release_dir(definition_id, release_id)
                if final_dir.is_dir():
                    registration = read_json(final_dir / "registration.json", default=None)
                    profile = read_json(final_dir / "profile.json", default=None)
                    if isinstance(registration, Mapping) and isinstance(profile, Mapping):
                        verify_profile_integrity(profile)
                        return self._replay(final_dir, registration, root)

                stage = Path(tempfile.mkdtemp(prefix="import-", dir=str(self.home / "staging")))
                package_stage = stage / "package"
                try:
                    materialized = materialize_package(
                        inspection,
                        package_stage,
                        definition_id=definition_id,
                        release_id=release_id,
                    )
                    status = effective_status(materialized.routing_card)
                    team_ready = materialized.routing_card.get("type") != "team" or bool(
                        materialized.team_graph
                        and materialized.team_graph.get("authoritative")
                        and materialized.team_graph.get("manager")
                    )
                    # Demote out loud. `effective_status` returns a bare word and
                    # drops the evidence, so this site used to compute
                    # routingEligible=False and hand the compiler an empty reason
                    # list: the receipt still said "active", and the only trace
                    # left was `gap:excluded:release-not-routing-eligible` at
                    # staffing time, which names no card and no fix. The lint
                    # reasons come back from the same decision that demoted the
                    # card, so the answer to "why is /hep-local not using it"
                    # ships with the registration instead of being reconstructed.
                    routing_eligible = status in {"routing_ready", "trusted"} and team_ready
                    unavailable_reasons = ([] if team_ready else ["team_graph_not_authoritative"]) + (
                        routing_ineligibility_reasons(materialized.routing_card)
                    )
                    profile = compile_workforce_profile(
                        agent_definition_id=definition_id,
                        agent_release_id=release_id,
                        package_hash=inspection.package_hash,
                        release_version=release_version,
                        routing_card=materialized.routing_card,
                        manifest=materialized.manifest,
                        mcp_requirements=list(materialized.mcp_requirements),
                        team_graph=materialized.team_graph,
                        operational={
                            "callable": True,
                            "installable": True,
                            "routingEligible": routing_eligible,
                            "unavailableReasons": unavailable_reasons,
                            "sourceRefs": [str(package_stage), inspection.entrypoint],
                        },
                    )
                    expected_content = verified_identity.get("contentDigest") if verified_identity else None
                    if expected_content and profile.get("provenance", {}).get("contentDigest") != expected_content:
                        raise PackageAdaptationError("verified_identity_content_mismatch", "compiled content digest differs")
                    verify_profile_integrity(profile)
                    snapshot_hash = snapshot_package_hash(package_stage)
                    prior_release = str(previous.get("currentReleaseId") or "") if previous else ""
                    registration = {
                        "schemaVersion": LOCAL_REGISTRATION_SCHEMA,
                        "status": "active",
                        "agentDefinitionId": definition_id,
                        "agentReleaseId": release_id,
                        "releaseVersion": release_version,
                        "packageHash": inspection.package_hash,
                        "snapshotHash": snapshot_hash,
                        "contentDigest": profile["provenance"]["contentDigest"],
                        "entityKind": profile["entityKind"],
                        "sourceRoot": str(root),
                        "sourceKind": inspection.source_kind,
                        "sourceIdentity": stable_source_identity,
                        "packageRoot": str(final_dir / "package"),
                        "entrypoint": inspection.entrypoint,
                        "lineageAttestation": attestation,
                        "managedBy": managed_by,
                        "registeredAt": _now(),
                        "supersedesReleaseId": prior_release or None,
                        "routingEligible": routing_eligible,
                        "routingStatus": status,
                    }
                    if not routing_eligible:
                        # `status: "active"` is the release lifecycle, not a
                        # promise of staffing, and on its own it reads as
                        # success. Carry the demotion on the receipt the person
                        # is looking at, using the routing card's own
                        # `routing_status_reason` vocabulary, and say which
                        # command stops working until it is fixed.
                        registration["routingStatusReason"] = "; ".join(unavailable_reasons)
                        registration["remediation"] = (
                            f"Registered, but /hep-local will not staff it yet. Fix the above in "
                            f"{root}/.agentlas/routing-card.json, then run `workforce local-register` again."
                        )
                    atomic_write_json(stage / "registration.json", registration)
                    atomic_write_json(stage / "profile.json", profile)
                    final_dir.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(stage, final_dir)
                except Exception:
                    shutil.rmtree(stage, ignore_errors=True)
                    raise

                definition = {
                    "agentDefinitionId": definition_id,
                    "currentReleaseId": release_id,
                    "status": "active",
                    "sourceRoot": str(root),
                    "sourceIdentity": stable_source_identity,
                    "lineageAttestation": attestation,
                    "managedBy": managed_by,
                    "updatedAt": _now(),
                }
                atomic_write_json(self._definition_path(definition_id), definition)
                event = self._publish_event(
                    "upsert",
                    {
                        "agentDefinitionId": definition_id,
                        "agentReleaseId": release_id,
                        "registration": registration,
                        "workforceProfile": profile,
                    },
                )
                return {**registration, "projectionEvent": event}
            except PackageAdaptationError as exc:
                return self._quarantine(root, exc)

    def reconcile(self, networking_root: Path | str | None = None) -> dict[str, Any]:
        """Reconcile only paths explicitly registered in networking state.

        ``sources.json`` roots are not themselves imported.  We use the same
        bounded routing-card traversal as the networking registry and register
        each card's package root.  Global cards contribute only an existing,
        absolute ``source.ref``.  Plugins are catalog/tool supply, never
        Workforce workers.
        """

        from ..networking.card_store import iter_source_cards, load_global_cards

        base = (Path(networking_root) if networking_root else networking_home()).expanduser().resolve()
        explicit_roots: set[Path] = set()
        sources = (read_json(base / "sources.json", default={}) or {}).get("sources") or []
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            try:
                source_root = Path(str(source.get("path") or "")).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if source_root in {self.user_home, Path(source_root.anchor).resolve()} or not source_root.is_dir():
                continue
            for card_path, card in iter_source_cards(source_root):
                if not isinstance(card, Mapping) or card.get("type") not in {"agent", "team"}:
                    continue
                package_root = card_path.parent.parent.resolve()
                if package_root.is_dir():
                    explicit_roots.add(package_root)

        cards, _ = load_global_cards(base)
        for card in cards:
            if card.get("type") not in {"agent", "team"} or card.get("stale"):
                continue
            source = card.get("source") if isinstance(card.get("source"), Mapping) else {}
            raw_ref = source.get("ref")
            if not raw_ref:
                continue
            try:
                package_root = Path(str(raw_ref)).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if package_root.is_absolute() and package_root.is_dir():
                explicit_roots.add(package_root)

        registrations: list[dict[str, Any]] = []
        for root in sorted(explicit_roots):
            registrations.append(self.register(root, managed_by="networking"))
        current = {str(root) for root in explicit_roots}
        removed: list[str] = []
        for record in self._records():
            if (
                record.get("managedBy") == "networking"
                and record.get("status") == "active"
                and str(record.get("sourceRoot")) not in current
            ):
                outcome = self.unregister(str(record["agentDefinitionId"]))
                if outcome.get("status") == "removed":
                    removed.append(str(record["agentDefinitionId"]))
        # Second route to the same silence: reconcile registers each root
        # through register(), so a rejected root already carries its reason and
        # remediation — but reporting only the count threw them away and the
        # user was told "quarantined: 2" with no way to learn which folders or
        # why. Carry the refusals through instead of counting them.
        quarantined = [row for row in registrations if row.get("status") == "quarantined"]
        return {
            "status": "reconciled",
            "explicitPackageRoots": len(explicit_roots),
            "active": len(self.active_profiles()),
            "registered": sum(1 for row in registrations if row.get("status") == "active" and not row.get("idempotent")),
            "unchanged": sum(1 for row in registrations if row.get("idempotent")),
            "quarantined": len(quarantined),
            "quarantinedSources": [
                {
                    key: row[key]
                    for key in ("sourceRoot", "reasonCode", "message", "remediation")
                    if key in row
                }
                for row in quarantined
            ],
            "removed": removed,
        }

    def unregister(self, target: Path | str) -> dict[str, Any]:
        with self._locked():
            record = self._find(target)
            if record is None or record.get("status") != "active":
                # Second route to the same code-only refusal. `local-remove`
                # answers the same person who just typed a path, and a typo got
                # back the bare token "not_found": no echo of what was looked
                # up, no statement of what a target may be, no way to see what
                # is registered. Say it in words here for the same reason
                # `_quarantine` does, and keep `status` unchanged so
                # `reconcile`'s `== "removed"` test still reads the same.
                return {
                    "status": "not_found",
                    "target": str(target),
                    "message": "no active local registration matches this target",
                    "remediation": (
                        "A target is either a registered source folder or a `definition:` id. "
                        "Run `workforce local-list` to see what is registered on this machine."
                    ),
                }
            record["status"] = "removed"
            record["updatedAt"] = _now()
            atomic_write_json(self._definition_path(str(record["agentDefinitionId"])), record)
            event = self._publish_event(
                "delete",
                {
                    "agentDefinitionId": record["agentDefinitionId"],
                    "agentReleaseId": record["currentReleaseId"],
                },
            )
            return {"status": "removed", "projectionEvent": event}

    def list_registrations(self) -> list[dict[str, Any]]:
        """Every registered definition, each carrying its routing verdict.

        A definition record only knows the release lifecycle, so this listing
        answered "what do I have registered" with `status: "active"` for agents
        /hep-local will never staff — the same silence the registration receipt
        used to print, one command later. Attach the verdict from the release
        profile staffing actually reads.
        """

        rows: list[dict[str, Any]] = []
        for record in self._records():
            row = dict(record)
            row.update(
                self._routing_verdict(
                    self._release_dir(
                        str(record.get("agentDefinitionId")), str(record.get("currentReleaseId"))
                    )
                )
            )
            rows.append(row)
        return sorted(rows, key=lambda row: str(row.get("agentDefinitionId")))

    def active_profiles(self) -> list[dict[str, Any]]:
        """Every locally registered release whose stored profile still verifies.

        The integrity check used to run unguarded, so one truncated or edited
        `profile.json` raised out of the whole loop and the caller turned that
        into `source_unavailable` for the entire local source — the same code it
        emits when the machine cannot be reached. Every other locally registered
        agent disappeared from the menu, and the reason shown was an outage that
        was not happening. A corrupt release is one candidate that cannot be
        offered, not a source that is down: skip it and keep the rest. The count
        is exposed on `last_integrity_drops` so the caller can report it.
        """

        profiles: list[dict[str, Any]] = []
        dropped = 0
        for record in self._records():
            if record.get("status") != "active":
                continue
            release_dir = self._release_dir(str(record["agentDefinitionId"]), str(record["currentReleaseId"]))
            profile = read_json(release_dir / "profile.json", default=None)
            if not isinstance(profile, Mapping):
                continue
            try:
                verify_profile_integrity(profile)
            except ValueError:
                dropped += 1
                continue
            profiles.append(dict(profile))
        self.last_integrity_drops = dropped
        return profiles

    def lineage_attestations(self) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for record in self._records():
            if record.get("status") == "active" and isinstance(record.get("lineageAttestation"), Mapping):
                result[str(record["agentDefinitionId"])] = validate_lineage_attestation(
                    record["lineageAttestation"]
                )
        return result

    def _staged_snapshot_hash(self, package_root: Path) -> str:
        """Re-hash the staged release, refusing in borrow-side words.

        The same hashing code serves import and borrow, so its refusals are
        written for someone who just typed a path — at borrow time nobody typed
        anything and "check the path for a typo" is the wrong instruction for a
        staged copy the registry itself owns. Keep `code` byte-identical so the
        wire contract and every consumer switching on it are untouched, and
        replace only the sentence and the remediation. Re-raise rather than
        absorb: this must stay a refusal, never a silent empty hash.
        """

        try:
            return snapshot_package_hash(package_root)
        except PackageAdaptationError as exc:
            raise PackageAdaptationError(
                exc.code,
                f"this release's staged copy is no longer readable ({exc})",
                "The imported copy under the local Workforce registry was changed or removed after registration. Re-import the source folder with `workforce local-register <path>`.",
            ) from exc

    def runtime_bundle(self, release_id: str) -> dict[str, Any]:
        record = next(
            (row for row in self._records() if row.get("currentReleaseId") == release_id and row.get("status") == "active"),
            None,
        )
        if record is None:
            raise KeyError("local_release_not_found")
        release_dir = self._release_dir(str(record["agentDefinitionId"]), release_id)
        registration = read_json(release_dir / "registration.json", default=None)
        profile = read_json(release_dir / "profile.json", default=None)
        if not isinstance(registration, Mapping) or not isinstance(profile, Mapping):
            raise KeyError("local_release_not_found")
        verify_profile_integrity(profile)
        if (
            registration.get("agentDefinitionId") != record.get("agentDefinitionId")
            or registration.get("agentReleaseId") != release_id
            or profile.get("agentDefinitionId") != record.get("agentDefinitionId")
            or profile.get("agentReleaseId") != release_id
            or profile.get("packageHash") != registration.get("packageHash")
            or profile.get("provenance", {}).get("contentDigest") != registration.get("contentDigest")
        ):
            raise KeyError("local_runtime_bundle_identity_mismatch")
        package_root = release_dir / "package"
        if self._staged_snapshot_hash(package_root) != registration.get("snapshotHash"):
            raise KeyError("local_runtime_bundle_snapshot_drift")
        entry_value = str(registration.get("entrypoint") or "AGENTS.md")
        entry_relative = Path(entry_value)
        if entry_relative.is_absolute() or ".." in entry_relative.parts or "\\" in entry_value:
            raise KeyError("local_runtime_bundle_entrypoint_invalid")
        entrypoint = (package_root / entry_relative).resolve()
        try:
            entrypoint.relative_to(package_root.resolve())
        except ValueError as exc:
            raise KeyError("local_runtime_bundle_entrypoint_invalid") from exc
        if entrypoint.is_symlink():
            raise KeyError("local_runtime_bundle_entrypoint_invalid")
        instructions = _bounded_nofollow_text(entrypoint, maximum=2_000_000)
        manifest_path = package_root / "agentlas.json"
        if manifest_path.exists():
            try:
                manifest_value = json.loads(_bounded_nofollow_text(manifest_path, maximum=1_000_000))
            except ValueError as exc:
                raise KeyError("local_runtime_bundle_manifest_invalid") from exc
            if not isinstance(manifest_value, Mapping):
                raise KeyError("local_runtime_bundle_manifest_invalid")
            manifest = dict(manifest_value)
        else:
            manifest = {}
        if self._staged_snapshot_hash(package_root) != registration.get("snapshotHash"):
            raise KeyError("local_runtime_bundle_snapshot_drift")
        bundle: dict[str, Any] = {
            "agentReleaseId": release_id,
            "packageHash": registration["packageHash"],
            "contentDigest": registration["contentDigest"],
            "directiveBundle": {"instructions": instructions},
            "toolPermissions": dict(manifest.get("toolPermissions") or {}),
            "allowRead": list(manifest.get("allowRead") or []),
            "denyRead": list(manifest.get("denyRead") or []),
            "status": "ready",
        }
        # A team is not executable without its organization: prepare_execution
        # rejects a team bundle with team_execution_graph_missing. Local teams
        # used to ship without one, so every locally registered team failed at
        # preparation while the surface reported a bind problem instead.
        if str(profile.get("entityKind") or "") == "team":
            bundle["executionGraph"] = _local_team_execution_graph(
                package_root=package_root,
                entry_relative=entry_relative.as_posix(),
                manager_content=instructions,
            )
        return bundle

    def events_after(self, cursor: int = 0) -> list[dict[str, Any]]:
        if not isinstance(cursor, int) or cursor < 0:
            raise ValueError("outbox_cursor_invalid")
        rows: list[dict[str, Any]] = []
        for path in sorted((self.home / "outbox").glob("*.json")):
            value = read_json(path, default=None)
            if isinstance(value, Mapping) and int(value.get("cursor") or 0) > cursor:
                rows.append(dict(value))
        return rows


__all__ = [
    "LOCAL_PROJECTION_EVENT_SCHEMA",
    "LOCAL_REGISTRATION_SCHEMA",
    "LOCAL_VERIFIED_IDENTITY_SCHEMA",
    "LocalWorkforceRegistry",
    "default_local_workforce_home",
]
