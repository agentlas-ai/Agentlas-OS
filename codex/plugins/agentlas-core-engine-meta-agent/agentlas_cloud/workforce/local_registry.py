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

from ..networking.bootstrap import append_jsonl, atomic_write_json, networking_home, read_json, utc_now
from ..networking.card_lint import effective_status, routing_ineligibility_reasons
from .compiler import COMPILER_VERSION, compile_workforce_profile, team_graph_ready
from .contracts import canonical_digest, content_tokens, verify_profile_integrity
from .execution import WORKFORCE_EXECUTION_GRAPH_SCHEMA
from .federation import (
    WORKFORCE_LINEAGE_ATTESTATION_SCHEMA,
    validate_lineage_attestation,
    workforce_lineage_claim_digest,
)
from .package_adapter import (
    PackageAdaptationError,
    closed_card,
    inspect_package,
    materialize_package,
    snapshot_package_hash,
)

_O_BINARY = getattr(os, "O_BINARY", 0)  # Windows: os.open() fds are text mode without it

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
# The local registration rules, one value for every place that must notice when
# they change: a stored profile carries it as `provenance.localRules` and is
# recompiled when it differs; card adoption and `local-autoregister` put it in
# their attempt keys so a root an earlier rule refused is judged again. Raise it
# when what registers, or how a registration is judged, changes.
# 3: a team's manager is derived from its members; one credential, secret or
#    linked file is left out of the snapshot instead of refusing the package.
LOCAL_RULES_VERSION = "3"


def _profile_is_current(profile: Mapping[str, Any]) -> bool:
    """Replay a stored profile only when this engine would compile the same one.

    `compilerVersion` stays at the released value (see compiler.COMPILER_VERSION),
    so an older engine on the same machine, which compares only that field, keeps
    replaying this engine's profiles instead of rewriting them.
    """

    provenance = profile.get("provenance") if isinstance(profile.get("provenance"), Mapping) else {}
    return (
        str(provenance.get("compilerVersion") or "") == COMPILER_VERSION
        and str(provenance.get("localRules") or "") == LOCAL_RULES_VERSION
    )


def _stamp_local_rules(profile: dict[str, Any]) -> dict[str, Any]:
    # Outside the content digest (semantic + qualification), so the stamp never changes identity.
    profile["provenance"]["localRules"] = LOCAL_RULES_VERSION
    return profile


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_WINDOWS_RELEASE_TOKEN_CHARS = 16


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
        descriptor = os.open(path, flags | _O_BINARY)
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


def _local_routing(status: str, team_ready: bool, routing_card: Mapping[str, Any]) -> tuple[bool, list[str], list[str]]:
    """Eligibility of an agent the owner registered on this machine.

    Benchmark counts and verification grades rank and label an agent; they never keep the owner's own
    agent out of the owner's own local search. Only a stale source or a card that
    fails lint outright (quarantined) or a team with no runnable graph (no member to lead or to work,
    or an explicit `authoritative: false`) is held back. A manager no file names is derived from the
    members (package_adapter._derived_team_graph) and reported as a warning. What a
    public listing would still want is returned as warnings, not as reasons.
    """

    if not team_ready:
        return False, ["team_graph_not_authoritative", *routing_ineligibility_reasons(routing_card)], []
    if status in {"stale", "quarantined"}:
        return False, routing_ineligibility_reasons(routing_card), []
    warnings = [] if status in {"routing_ready", "trusted"} else routing_ineligibility_reasons(routing_card)
    return True, [], warnings


def _team_manager_warning(team_graph: Mapping[str, Any] | None) -> list[str]:
    """Say on the receipt that the team's manager was picked, not declared.

    Starts with a fixed code so a reader can match it without parsing the prose.
    """

    if not isinstance(team_graph, Mapping) or team_graph.get("derived") is not True:
        return []
    manager = str(team_graph.get("manager") or "").removeprefix("node:")
    rule = (
        "its folder name marks it as the lead"
        if team_graph.get("managerRule") == "lead-named-member"
        else "it is the first member in name order"
    )
    return [
        f"team_manager_derived: no file names the team's manager, so agents/{manager} leads because {rule}; "
        'set "orchestrator" in .agentlas/agent-card.json to choose another member'
    ]


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
        legacy = self.home / "releases" / _token(definition_id) / _token(release_id)
        if os.name != "nt" or legacy.is_dir():
            return legacy
        # Windows MAX_PATH: two 64-char digests plus `package\` left ~67 characters of the
        # 259 for the package's own paths under C:\Users\<name>\.agentlas\workforce\local,
        # and the bundled Python cannot create longer paths unless LongPathsEnabled is set
        # (off by default). New Windows releases use 16-hex-digit names (64 bits; the full
        # ids stay in registration.json). An existing full-length release is still found
        # and used as it is, so registries written before this change keep working.
        return (
            self.home
            / "releases"
            / _token(definition_id)[:_WINDOWS_RELEASE_TOKEN_CHARS]
            / _token(release_id)[:_WINDOWS_RELEASE_TOKEN_CHARS]
        )

    def _records(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted((self.home / "definitions").glob("*.json")):
            value = read_json(path, default=None)
            if isinstance(value, Mapping):
                rows.append(dict(value))
        return rows

    def _by_source(self, root: Path) -> dict[str, Any] | None:
        return next((row for row in self._records() if row.get("sourceRoot") == str(root)), None)

    def _moved_definition(self, package_hash: str, root: Path) -> dict[str, Any] | None:
        """The one active definition whose folder is gone but whose registered bytes equal ``root``'s: a move.

        Content decides, so no hint file is needed. Two or more such definitions are ambiguous and are left alone
        (the caller then behaves as before). A folder that still exists is a real second copy, never a move.
        """

        found: list[dict[str, Any]] = []
        for row in self._records():
            old = str(row.get("sourceRoot") or "")
            if row.get("status") != "active" or not old or old == str(root):
                continue
            if str(row.get("sourceIdentity") or "").startswith("verified:"):
                continue
            try:
                if Path(old).exists():
                    continue
            except OSError:
                continue  # cannot tell whether it is gone (permissions): not a move
            definition_id, release_id = str(row.get("agentDefinitionId") or ""), str(row.get("currentReleaseId") or "")
            if not definition_id or not release_id:
                continue
            stored = read_json(self._release_dir(definition_id, release_id) / "registration.json", default=None)
            if isinstance(stored, Mapping) and stored.get("packageHash") == package_hash:
                found.append(row)
        return found[0] if len(found) == 1 else None

    def _repoint_cards(self, old_root: str, new_root: str) -> None:
        """Best effort: global cards that named the old folder now name the new one. Writes the card file only
        (not save_card), so the desktop is not told about a "new" local agent."""

        try:
            from ..networking.card_store import card_path, content_hash, load_global_cards

            base = networking_home().expanduser()
            cards, _ = load_global_cards(base)
            for card in cards:
                source = card.get("source")
                if not isinstance(source, dict) or str(source.get("ref") or "") != old_root:
                    continue
                path = Path(str(card.pop("_card_path", "") or card_path(base, card)))
                source["ref"] = new_root
                card.setdefault("integrity", {})["content_hash"] = content_hash(card)
                atomic_write_json(path, card)
        except Exception:  # noqa: BLE001 - a card that could not be re-pointed never fails the move
            return

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
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
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
        force_restage: bool = False,
    ) -> dict[str, Any]:
        """Import one root; verified cross-source identity is API-only.

        ``force_restage`` rebuilds the stored copy of a release even when the
        source is unchanged. A release id is derived from the package hash, so
        without it re-registering a damaged snapshot replays the damage.
        """

        try:
            root = self._explicit_root(source_root)
        except PackageAdaptationError as exc:
            with self._locked():
                return self._quarantine(source_root, exc)
        with self._locked():
            previous = self._by_source(root)
            try:
                inspection = inspect_package(root)
                # A folder that moved (the desktop's agents-folder move, a renamed parent, a new drive letter) is the
                # same agent: keep its id instead of minting a second one or refusing with identity_conflict.
                moved_from = None
                if previous is None and verified_identity is None:
                    moved_from = self._moved_definition(inspection.package_hash, root)
                    previous = moved_from
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
                if (
                    moved_from is None
                    and isinstance(existing, Mapping)
                    and existing.get("sourceRoot") != str(root)
                    and existing.get("status") == "active"
                ):
                    raise PackageAdaptationError(
                        "identity_conflict",
                        "another active root claims this definition",
                        f"Another registered folder already owns this identity: {existing.get('sourceRoot')}. Remove it with `workforce local-remove`, or give this copy its own id in .agentlas/routing-card.json.",
                    )

                final_dir = self._release_dir(definition_id, release_id)
                if final_dir.is_dir() and not force_restage and moved_from is None:
                    registration = read_json(final_dir / "registration.json", default=None)
                    profile = read_json(final_dir / "profile.json", default=None)
                    if isinstance(registration, Mapping) and isinstance(profile, Mapping):
                        verify_profile_integrity(profile)
                        # 저장된 compilerVersion 또는 localRules 가 현재와 다르면 프로필을 재컴파일한다.
                        # 패키지 바이트가 같으면 packageHash·releaseId·경로를 보존하며, 프로필과
                        # contentDigest 를 registration.json 과 함께 원자적으로 교체한다.
                        if _profile_is_current(profile):
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
                    status = effective_status(closed_card(materialized.routing_card, package_stage))
                    team_ready = materialized.routing_card.get("type") != "team" or team_graph_ready(
                        materialized.team_graph
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
                    routing_eligible, unavailable_reasons, routing_warnings = _local_routing(
                        status, team_ready, closed_card(materialized.routing_card, package_stage)
                    )
                    routing_warnings = [*routing_warnings, *_team_manager_warning(materialized.team_graph)]
                    profile = _stamp_local_rules(compile_workforce_profile(
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
                    ))
                    expected_content = verified_identity.get("contentDigest") if verified_identity else None
                    if expected_content and profile.get("provenance", {}).get("contentDigest") != expected_content:
                        raise PackageAdaptationError("verified_identity_content_mismatch", "compiled content digest differs")
                    verify_profile_integrity(profile)
                    snapshot_hash = snapshot_package_hash(package_stage)
                    prior_release = str(previous.get("currentReleaseId") or "") if previous else ""
                    if moved_from is not None and prior_release == release_id:
                        prior_release = ""  # same bytes at a new place: a re-point, not a new version
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
                    if routing_warnings:
                        registration["routingWarnings"] = routing_warnings
                    if inspection.advisories:
                        # Files the snapshot left out (credentials, secrets, links) and a
                        # repository-shaped folder, by name only; the rest registered.
                        registration["advisories"] = list(inspection.advisories)
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
                    # `os.replace` refuses a non-empty destination directory.
                    # Before the compiler-version trigger, an existing release
                    # always returned through `_replay` and this line only ever
                    # saw a fresh path; a recompile of an already-imported
                    # release lands here with the old directory in place and
                    # raised `Directory not empty` (caught in a dry run against
                    # a copy of the live registry, 2026-08-19). Swap through a
                    # retired name so the release directory is never observed
                    # half-written, and only then drop the old copy.
                    retired: Path | None = None
                    if final_dir.is_dir():
                        retired = stage.parent / f"retired-{final_dir.name}-{_token(str(final_dir))[:12]}"
                        shutil.rmtree(retired, ignore_errors=True)
                        os.replace(final_dir, retired)
                    try:
                        os.replace(stage, final_dir)
                    except Exception:
                        if retired is not None and not final_dir.exists():
                            os.replace(retired, final_dir)
                            retired = None
                        raise
                    if retired is not None:
                        shutil.rmtree(retired, ignore_errors=True)
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
                moved_result: dict[str, Any] = {}
                if moved_from is not None:
                    old_root = str(moved_from.get("sourceRoot") or "")
                    self._repoint_cards(old_root, str(root))
                    moved_result = {"movedFrom": old_root}
                return {**registration, "projectionEvent": event, **moved_result}
            except PackageAdaptationError as exc:
                return self._quarantine(root, exc)

    def repair_stale_profiles(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Recompile stored releases whose profile predates the current compiler.

        Refresh stored compiled profiles after compilerVersion changes, even
        when the original source folder has moved or is no longer available.
        Recompile from the stored release so obsolete identifiers do not persist.

        The materialized package lives inside the release directory itself, so
        the repair never needs the import source: it recompiles from the bytes
        the registry already owns and keeps the definition, release, and package
        identity unchanged. Only the profile content and its content digest move.
        """

        repaired: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        current = 0
        with self._locked():
            for definition_dir in sorted((self.home / "releases").glob("*")):
                if not definition_dir.is_dir():
                    continue
                for release_dir in sorted(definition_dir.glob("*")):
                    if not release_dir.is_dir():
                        continue
                    profile = read_json(release_dir / "profile.json", default=None)
                    registration = read_json(release_dir / "registration.json", default=None)
                    if not isinstance(profile, Mapping) or not isinstance(registration, Mapping):
                        continue
                    if _profile_is_current(profile):
                        current += 1
                        continue
                    stored = profile.get("provenance") if isinstance(profile.get("provenance"), Mapping) else {}
                    identity = {
                        "agentDefinitionId": str(registration.get("agentDefinitionId") or ""),
                        "agentReleaseId": str(registration.get("agentReleaseId") or ""),
                        "storedCompilerVersion": str(stored.get("compilerVersion") or "") or None,
                        "storedLocalRules": str(stored.get("localRules") or "") or None,
                    }
                    package_root = release_dir / "package"
                    if not package_root.is_dir():
                        failed.append({**identity, "reasonCode": "stored_package_missing"})
                        continue
                    if dry_run:
                        repaired.append({**identity, "status": "would_recompile"})
                        continue
                    try:
                        rebuilt = self._recompile_stored_release(
                            release_dir, registration, package_root
                        )
                    except (PackageAdaptationError, OSError, TypeError, ValueError) as exc:
                        failed.append(
                            {
                                **identity,
                                "reasonCode": getattr(exc, "code", None) or type(exc).__name__,
                                "message": str(exc)[:200],
                            }
                        )
                        continue
                    repaired.append({**identity, "status": "recompiled", **rebuilt})
        return {
            "status": "repaired" if not dry_run else "inspected",
            "compilerVersion": COMPILER_VERSION,
            "localRules": LOCAL_RULES_VERSION,
            "alreadyCurrent": current,
            "repaired": len(repaired),
            "failed": len(failed),
            "repairedReleases": repaired[:200],
            "failedReleases": failed[:200],
        }

    def _recompile_stored_release(
        self,
        release_dir: Path,
        registration: Mapping[str, Any],
        package_root: Path,
    ) -> dict[str, Any]:
        """Rebuild one stored profile in place from the registry's own package."""

        inspection = inspect_package(package_root)
        routing_card = inspection.routing_card
        if not isinstance(routing_card, Mapping):
            raise PackageAdaptationError(
                "stored_package_not_native",
                "the stored package carries no routing card to recompile from",
            )
        status = effective_status(closed_card(routing_card, package_root))
        team_ready = routing_card.get("type") != "team" or team_graph_ready(inspection.team_graph)
        routing_eligible, unavailable_reasons, routing_warnings = _local_routing(status, team_ready, closed_card(routing_card, package_root))
        routing_warnings = [*routing_warnings, *_team_manager_warning(inspection.team_graph)]
        profile = _stamp_local_rules(compile_workforce_profile(
            agent_definition_id=str(registration["agentDefinitionId"]),
            agent_release_id=str(registration["agentReleaseId"]),
            # Identity is not recomputed: the stored package is the same bytes
            # that produced this release, and a repair that moved packageHash
            # would invalidate every pin already handed out for it.
            package_hash=str(registration["packageHash"]),
            release_version=str(registration.get("releaseVersion") or ""),
            routing_card=routing_card,
            manifest=inspection.manifest,
            mcp_requirements=list(inspection.mcp_requirements),
            team_graph=inspection.team_graph,
            operational={
                "callable": True,
                "installable": True,
                "routingEligible": routing_eligible,
                "unavailableReasons": unavailable_reasons,
                "sourceRefs": [str(package_root), inspection.entrypoint],
            },
        ))
        verify_profile_integrity(profile)
        # The receipt's reason and warnings belong to the verdict just computed. A
        # team demoted by an older compiler kept `routingStatusReason` and its
        # remediation after the recompile made it routable, so the receipt said
        # both "eligible" and "will not staff it".
        updated = {
            **{
                key: value
                for key, value in registration.items()
                if key not in {"routingStatusReason", "remediation", "routingWarnings"}
            },
            "contentDigest": profile["provenance"]["contentDigest"],
            "entityKind": profile["entityKind"],
            "routingEligible": routing_eligible,
            "routingStatus": status,
            "repairedAt": _now(),
        }
        if routing_warnings:
            updated["routingWarnings"] = routing_warnings
        if not routing_eligible:
            updated["routingStatusReason"] = "; ".join(unavailable_reasons)
            updated["remediation"] = registration.get("remediation") or (
                f"Registered, but /hep-local will not staff it yet. Fix the above in "
                f"{registration.get('sourceRoot')}/.agentlas/routing-card.json, then run `workforce local-register` again."
            )
        atomic_write_json(release_dir / "profile.json", profile)
        atomic_write_json(release_dir / "registration.json", updated)
        self._publish_event(
            "upsert",
            {
                "agentDefinitionId": updated["agentDefinitionId"],
                "agentReleaseId": updated["agentReleaseId"],
                "registration": updated,
                "workforceProfile": profile,
            },
        )
        return {"contentDigest": updated["contentDigest"]}

    def refresh_registered_sources(self) -> dict[str, Any]:
        """Re-import the current bytes for every active registered source.

        A local registration is an immutable execution snapshot, not a live
        view of its import folder. That is the right property for a prepared
        execution, but discovery must refresh the unpinned inventory first or
        an edited source can remain invisible indefinitely. Refresh only roots
        already present in the local registry: this updates registered agents
        without silently widening ``/hep-local`` to every card found on disk.

        ``register()`` keeps the old release when a source disappears or fails
        validation, and returns a new content-addressed release when its safe
        snapshot changes. Existing ownership (explicit vs networking) is
        preserved rather than being rewritten as a side effect of discovery.
        """

        records = [
            record
            for record in self._records()
            if record.get("status") == "active" and record.get("sourceRoot")
        ]
        refreshed = 0
        unchanged = 0
        missing = 0
        quarantined: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        seen_roots: set[str] = set()

        for record in records:
            source_root = str(record.get("sourceRoot") or "").strip()
            if not source_root or source_root in seen_roots:
                continue
            seen_roots.add(source_root)
            try:
                root = Path(source_root).expanduser()
                if not root.is_dir():
                    missing += 1
                    continue
                managed_by = str(record.get("managedBy") or "explicit")
                outcome = self.register(root, managed_by=managed_by)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                failed.append(
                    {
                        "sourceRoot": source_root,
                        "reasonCode": type(exc).__name__,
                        "message": str(exc)[:200],
                    }
                )
                continue

            if outcome.get("status") == "active":
                if outcome.get("idempotent"):
                    unchanged += 1
                else:
                    refreshed += 1
            elif outcome.get("status") == "quarantined":
                quarantined.append(
                    {
                        key: outcome[key]
                        for key in ("sourceRoot", "reasonCode", "message", "remediation")
                        if key in outcome
                    }
                )

        return {
            "status": "refreshed",
            "registered": len(seen_roots),
            "refreshed": refreshed,
            "unchanged": unchanged,
            "missing": missing,
            "quarantined": len(quarantined),
            "quarantinedSources": quarantined[:200],
            "failed": len(failed),
            "failedSources": failed[:200],
        }

    def adopt_new_networking_cards(self, networking_root: Path | str | None = None) -> dict[str, Any]:
        """Register the package root of a networking card the roster has never seen.

        Discovery refreshes only roots that are already registered, so an agent
        built after the last registration kept a healthy card and stayed
        invisible to every search (measured 2026-10-11: 20 card roots unseen,
        including a freshly built video producer, while the registry's last
        write was a week old). The card store is the owner's own explicit list
        — it is not a scan of the home folder — so adopting from it keeps the
        "never widen to whatever is on disk" rule that refresh protects.

        Two limits keep this safe to run on every search:

        - A root that already has a definition record is left alone, whatever
          its status. A user who removed an agent is not silently given it back.
        - A root that was refused is not retried until its card's package hash
          changes; otherwise every search would write another quarantine file.
        """

        from ..networking.card_store import load_global_cards

        base = (Path(networking_root) if networking_root else networking_home()).expanduser().resolve()
        cards, _ = load_global_cards(base)
        state_path = self.home / "adoption-state.json"
        state = read_json(state_path, default={}) or {}
        if not isinstance(state, dict):
            state = {}
        known = {str(record.get("sourceRoot")) for record in self._records()}
        adopted = skipped = attempted_before = 0
        tried_this_run: set[str] = set()
        refused: list[dict[str, Any]] = []
        changed = False
        for card in cards:
            if card.get("type") not in {"agent", "team"} or card.get("stale"):
                continue
            source = card.get("source") if isinstance(card.get("source"), Mapping) else {}
            raw_ref = source.get("ref")
            if not raw_ref:
                continue
            try:
                root = Path(str(raw_ref)).expanduser()
                if not root.is_absolute() or not root.is_dir():
                    continue
                root = root.resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if root in {self.user_home, Path(root.anchor).resolve()}:
                continue
            key = str(root)
            if key in known:
                skipped += 1
                continue
            # The rules version is part of the attempt key: a root an earlier rule refused is judged again.
            package_hash = str(source.get("package_hash") or "") + "|rules" + LOCAL_RULES_VERSION
            # One folder can carry several cards (an agent card and a team card),
            # each with its own package hash; remember every attempt, not the last.
            attempts = state.get(key) if isinstance(state.get(key), dict) else {}
            if package_hash in attempts or key in tried_this_run:
                attempted_before += 1
                continue
            tried_this_run.add(key)
            try:
                outcome = self.register(root, managed_by="networking")
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                attempts[package_hash] = {"status": "failed", "reasonCode": type(exc).__name__}
                state[key] = attempts
                changed = True
                refused.append({"sourceRoot": key, "reasonCode": type(exc).__name__})
                continue
            attempts[package_hash] = {
                "status": str(outcome.get("status")),
                **({"reasonCode": outcome["reasonCode"]} if outcome.get("reasonCode") else {}),
            }
            state[key] = attempts
            changed = True
            known.add(key)
            if outcome.get("status") == "active":
                adopted += 1
            else:
                refused.append({"sourceRoot": key, "reasonCode": str(outcome.get("reasonCode") or outcome.get("status"))})
        if changed:
            atomic_write_json(state_path, state)
        return {
            "status": "adopted",
            "adopted": adopted,
            "refused": len(refused),
            "refusedSources": refused[:200],
            "alreadyRegistered": skipped,
            "alreadyAttempted": attempted_before,
        }

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
            # A registration serves its own snapshot, so a vanished source
            # folder does not break a call, but the author deserves to know the
            # copy can no longer be refreshed.
            source_root = str(record.get("sourceRoot") or "")
            row["sourceState"] = "present" if source_root and Path(source_root).expanduser().is_dir() else "missing"
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

    def retrieval_hints(self) -> dict[str, dict[str, Any]]:
        """Publisher-written trigger sentences, keyed by release id.

        These are read from the STAGED package copy under the registry, not from
        the folder the user imported: the original can move or be deleted, and
        the staged copy is the one `packageHash` covers.

        They deliberately never enter the profile. `contentDigest` is computed
        over `semantic` + `qualification` (compiler.py), so folding retrieval
        hints into the profile would change its digest and the identities used
        by sessions, goal rosters, and pin equality checks.
        A hint that changes nothing durable can be added, dropped, or corrected
        at any time; a profile field cannot.
        """

        hints: dict[str, dict[str, Any]] = {}
        for record in self._records():
            if record.get("status") != "active":
                continue
            release_id = str(record.get("currentReleaseId") or "")
            if not release_id:
                continue
            release_dir = self._release_dir(str(record["agentDefinitionId"]), release_id)
            card = read_json(release_dir / "package" / ".agentlas" / "routing-card.json", default=None)
            if not isinstance(card, Mapping):
                continue
            sentences: list[str] = []
            for item in card.get("trigger_examples") or []:
                text = item.get("text") if isinstance(item, Mapping) else item
                if isinstance(text, str) and text.strip():
                    sentences.append(text.strip())
            for item in card.get("capabilities") or []:
                if isinstance(item, str) and item.strip():
                    sentences.append(item.strip())
            if not sentences:
                continue
            hints[release_id] = {
                "triggerTokens": [content_tokens(sentence) for sentence in sentences[:64]]
            }
        return hints

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

    def admitted_lazy_asset(self, root: Path, relative: str) -> dict[str, Any] | None:
        """Existing active release custody, not a manifest/path identity claim.

        This admits catalogue observation only. The actual lazy reader still
        decides allowRead/denyRead and is the only consumer of the source body.
        """
        from ..agent_revisions import asset_path, asset_role
        relative = asset_path(relative)
        role = asset_role(relative)
        if role not in {"knowledge", "tool"}:
            return None
        root = root.absolute()
        if root.is_symlink() or any(p.is_symlink() for p in root.parents):
            return None
        matches = []
        for row in self._records():
            if row.get("status") != "active" or not row.get("currentReleaseId"):
                continue
            staged = self._release_dir(str(row["agentDefinitionId"]), str(row["currentReleaseId"])) / "package"
            # Only this already-admitted immutable staged location is eligible.
            # An identical unregistered copy or a sourceRoot move is not custody.
            if staged.absolute() == root:
                matches.append(row)
        if len(matches) != 1:
            return None
        record = _detached(matches[0])
        actor, release = str(record["agentDefinitionId"]), str(record["currentReleaseId"])
        release_dir = self._release_dir(actor, release)
        registration = read_json(release_dir / "registration.json", default=None)
        profile = read_json(release_dir / "profile.json", default=None)
        if not isinstance(registration, Mapping) or not isinstance(profile, Mapping):
            return None
        verify_profile_integrity(profile)
        if (registration.get("agentDefinitionId") != actor or registration.get("agentReleaseId") != release
            or profile.get("agentDefinitionId") != actor or profile.get("agentReleaseId") != release
            or profile.get("packageHash") != registration.get("packageHash")
            or profile.get("provenance", {}).get("contentDigest") != registration.get("contentDigest")):
            return None
        root_identity = root.stat()
        root_key = (root_identity.st_dev, root_identity.st_ino, root_identity.st_mode)
        if root_identity.st_dev <= 0 or root_identity.st_ino <= 0 or not stat.S_ISDIR(root_identity.st_mode):
            # Unknown native file identity cannot prove relocation custody.
            return None
        expected_hash = registration.get("snapshotHash")
        # Base package hashes intentionally exclude the self-referential
        # manifest. Its current lazy-read policy still needs an exact fence.
        manifest_digest = hashlib.sha256(_bounded_nofollow_text(root / "agentlas.json", maximum=1_000_000).encode("utf-8")).hexdigest()

        def current() -> None:
            latest = read_json(self._definition_path(actor), default=None)
            current_root = root.stat()
            if (latest != record or root.is_symlink() or any(p.is_symlink() for p in root.parents)
                or (current_root.st_dev, current_root.st_ino, current_root.st_mode) != root_key
                or read_json(release_dir / "registration.json", default=None) != registration
                or read_json(release_dir / "profile.json", default=None) != profile
                or hashlib.sha256(_bounded_nofollow_text(root / "agentlas.json", maximum=1_000_000).encode("utf-8")).hexdigest() != manifest_digest
                or self._staged_snapshot_hash(root) != expected_hash):
                raise KeyError("local_lazy_asset_custody_changed")
        current()
        return {"actor": actor, "version": release, "root": root, "path": relative, "role": role, "assert_current": current}

    def runtime_bundle(self, release_id: str) -> dict[str, Any]:
        from ..memory_package_sources import capture_owner, observe_declarations, generated_declaration
        source_owner = capture_owner()
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
        if generated_declaration(instructions):
            raise KeyError("generated_memory_not_package_declaration")
        manifest_path = package_root / "agentlas.json"
        if manifest_path.exists():
            try:
                manifest_text = _bounded_nofollow_text(manifest_path, maximum=1_000_000)
                manifest_value = json.loads(manifest_text)
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
        # The registry, active release and exact staged snapshot admit this
        # original declaration. Metadata cannot turn an arbitrary path/hash
        # into a package or recover a revoked/unregistered release.
        declarations = [{"path": entry_relative.as_posix(), "role": "instruction",
            "digest": hashlib.sha256(instructions.encode("utf-8")).hexdigest(), "byteLength": len(instructions.encode("utf-8"))}]
        if manifest_path.exists():
            declarations.append({"path":"agentlas.json","role":"manifest","digest":hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),"byteLength":len(manifest_text.encode("utf-8"))})
        for worker in bundle.get("executionGraph", {}).get("workers", []):
            body = worker["content"]
            if generated_declaration(body): raise KeyError("generated_memory_not_package_declaration")
            declarations.append({"path":worker["path"],"role":"instruction","digest":hashlib.sha256(body.encode("utf-8")).hexdigest(),"byteLength":len(body.encode("utf-8"))})
        skills = manifest.get("skills") or []
        if not isinstance(skills, list): skills = []
        for value in skills[:128]:
            relative = value if isinstance(value,str) else value.get("path") if isinstance(value,Mapping) else None
            if not isinstance(relative,str) or not relative or "\\" in relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                continue
            candidates = [relative] if relative.endswith("SKILL.md") else [relative.rstrip("/")+"/SKILL.md", "skills/"+relative.rstrip("/")+"/SKILL.md"]
            target = next((package_root / item for item in candidates if (package_root/item).is_file()), None)
            if target is None: continue
            if target.is_symlink() or any(part.is_symlink() for part in target.parents if part.is_relative_to(package_root)):
                continue
            body = _bounded_nofollow_text(target, maximum=512*1024)
            if generated_declaration(body): raise KeyError("generated_memory_not_package_declaration")
            declarations.append({"path":target.relative_to(package_root).as_posix(),"role":"skill","digest":hashlib.sha256(body.encode("utf-8")).hexdigest(),"byteLength":len(body.encode("utf-8"))})
        def source_current() -> None:
            latest = next((row for row in self._records() if row.get("agentDefinitionId") == record["agentDefinitionId"] and row.get("status") == "active"), None)
            if (not latest or latest.get("currentReleaseId") != release_id or latest.get("sourceRoot") != record.get("sourceRoot")
                or self._staged_snapshot_hash(package_root) != registration.get("snapshotHash")):
                raise KeyError("local_runtime_bundle_snapshot_drift")
        bundle["declarationSourceRefs"] = observe_declarations(source_owner,actor=str(record["agentDefinitionId"]),root=package_root,
            version=release_id,assets=declarations,assert_current=source_current)
        # Agentlas 2.0: no drawer ledger row is written here any more. Its only reader (the Stop hook's borrowed-agent attribution) no longer
        # runs (' 4), and an agent's memory is its own folder's, not `networking/hub-agents/<slug>`.
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
