"""Durable, account-partitioned Workforce bindings for multi-turn goals.

A Hub lease answers a billing question ("is another borrow charge due?").  It
does not define how long a host keeps an already selected roster attached to a
goal.  This store owns that separate local continuity contract:

* exact prepared releases are appended to a goal roster;
* the roster remains active until an explicit completion transition;
* every host turn records a content-free reuse/recruit/block decision;
* account and project partitions prevent cross-owner/cross-workspace bleed.

The store deliberately persists no task prompt, directive bundle, model output,
credentials, or private package content.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Iterator, Mapping

from .contracts import canonical_digest


WORKFORCE_GOAL_BINDING_SCHEMA = "agentlas.workforce-goal-binding.v1"
WORKFORCE_GOAL_CONTEXT_SCHEMA = "agentlas.workforce-goal-context.v1"
WORKFORCE_GOAL_TURN_SCHEMA = "agentlas.workforce-goal-turn.v1"
_GOAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_DECISIONS = frozenset({"reuse", "recruit", "local-only", "blocked", "standby"})
_TERMINAL_STATUSES = frozenset({"completed", "cancelled"})
_OPAQUE_LABEL_RE = re.compile(r"^(release|agr_|definition)[:_]?[0-9a-f]{8,}", re.IGNORECASE)
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class WorkforceGoalBindingError(ValueError):
    """Finite local continuity failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _agentlas_home() -> Path:
    return Path(os.environ.get("AGENTLAS_HOME") or (Path.home() / ".agentlas")).expanduser()


def default_goal_store_path() -> Path:
    return _agentlas_home() / "networking" / "workforce-goals.sqlite3"


def default_goal_runtime_root() -> Path:
    return _agentlas_home() / "networking" / "workforce-goal-runtime"


def unsigned_local_partition() -> str:
    """The fixed partition every signed-out machine shares."""

    return canonical_digest(
        {
            "schemaVersion": "agentlas.workforce-local-account-partition.v1",
            "scope": "unsigned-local",
        }
    )


def current_account_partition() -> str:
    """Return the same rotation-stable account partition used by preparation.

    An unsigned local-only user gets a stable machine-local partition.  Remote
    Hub/Cloud rows cannot be bound to that fallback.
    """

    try:
        from .source_service import _default_hub_auth_partition

        partition = _default_hub_auth_partition()
    except (OSError, RuntimeError, ValueError):
        partition = None
    if partition:
        return partition
    return canonical_digest(
        {
            "schemaVersion": "agentlas.workforce-local-account-partition.v1",
            "scope": "unsigned-local",
        }
    )


def account_partition_for_subject(
    account_subject: str,
    *,
    base_url: str | None = None,
) -> str:
    value = str(account_subject or "").strip()
    if not _HASH_RE.fullmatch(value):
        raise WorkforceGoalBindingError("workforce_goal_account_subject_invalid")
    if base_url is None:
        try:
            from ..auth import normalize_base_url

            resolved_base_url = normalize_base_url()
        except (OSError, RuntimeError, ValueError):
            resolved_base_url = "https://agentlas.cloud"
    else:
        resolved_base_url = str(base_url).rstrip("/")
    if not resolved_base_url.startswith(("https://", "http://")):
        raise WorkforceGoalBindingError("workforce_goal_account_origin_invalid")
    return canonical_digest(
        {
            "schemaVersion": "agentlas.workforce-auth-cache-partition.v2",
            "baseUrl": resolved_base_url,
            "accountSubject": value,
        }
    )


def _project_identity(project_dir: str | Path) -> tuple[str, str]:
    try:
        resolved = Path(project_dir).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkforceGoalBindingError("workforce_goal_project_unavailable") from exc
    if not resolved.is_dir():
        raise WorkforceGoalBindingError("workforce_goal_project_unavailable")
    value = str(resolved)
    return canonical_digest(
        {
            "schemaVersion": "agentlas.workforce-project-partition.v1",
            "resolvedPath": value,
        }
    ), value


def _assert_goal_id(goal_id: str) -> str:
    value = str(goal_id or "").strip()
    if not _GOAL_ID_RE.fullmatch(value):
        raise WorkforceGoalBindingError("workforce_goal_id_invalid")
    return value


def implicit_goal_id(
    *,
    work_order: Mapping[str, Any] | None = None,
    requested_goal_id: str | None = None,
) -> str:
    """Return a stable binding id without requiring the user to say "goal".

    Hosts should pass their durable Task/conversation id when available.  When
    they do not, the already-required redacted WorkOrder id becomes the stable
    first-contact seed.  The raw task brief is never included.
    """

    if isinstance(requested_goal_id, str) and requested_goal_id.strip():
        return _assert_goal_id(requested_goal_id)
    work_order_id = (
        str(work_order.get("workOrderId") or "").strip()
        if isinstance(work_order, Mapping)
        else ""
    )
    if not work_order_id:
        raise WorkforceGoalBindingError("workforce_goal_seed_missing")
    digest = hashlib.sha256(work_order_id.encode("utf-8")).hexdigest()[:40]
    return f"goal:auto:{digest}"


def resolve_continuity_goal_id(
    *,
    project_dir: str | Path,
    work_order: Mapping[str, Any] | None = None,
    requested_goal_id: str | None = None,
    store: "WorkforceGoalStore | None" = None,
) -> str:
    """Resolve the goal a preparation belongs to, preferring the incumbent.

    ★암묵 goal 은 WorkOrder 마다가 아니라 프로젝트 연속성마다 하나다.

    implicit_goal_id 는 workOrderId 에서 파생되므로 새 작업마다 새 goal 이
    생겼다. SKILL.md 4절은 "이후 준비는 incumbent goalId 로 새 릴리스만
    덧붙인다"고 규정하는데, incumbent 를 **찾는** 단계가 어디에도 구현돼 있지
    않아 호스트가 goalId 를 직접 넘겨야만 성립했다. 실측 2026-08-21: 프로젝트
    하나에 활성 goal 3개·로스터 21행이 쌓였고 그중 19행(90%)은 한 번도 쓰인
    적이 없다. 읽기 상한이 8이라 조회 비용도 함께 자란다. 명시 goalId 가
    없으면 이 프로젝트의 현직 자동 goal 에 추가한다 — "recruitment is additive"
    를 정책 문장이 아니라 코드로.
    """

    if isinstance(requested_goal_id, str) and requested_goal_id.strip():
        return _assert_goal_id(requested_goal_id)
    try:
        incumbent = (store or WorkforceGoalStore()).context(project_dir=project_dir)
    except (OSError, sqlite3.Error, WorkforceGoalBindingError):
        incumbent = {"goals": []}
    for candidate in incumbent.get("goals") or []:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("goalId") or "")
        if candidate.get("status") == "active" and candidate_id.startswith("goal:auto:"):
            return candidate_id
    return implicit_goal_id(work_order=work_order, requested_goal_id=None)


def workforce_preparation_ready(result: Any) -> bool:
    """Return whether preparation pinned a non-empty executable roster."""

    if not isinstance(result, Mapping) or result.get("status") != "prepared":
        return False
    if result.get("issues"):
        return False
    prepared_plan = result
    nested_plan = result.get("executionPlan")
    if isinstance(nested_plan, Mapping):
        prepared_plan = nested_plan
        if prepared_plan.get("status") != "prepared" or prepared_plan.get("issues"):
            return False
    roster = prepared_plan.get("executionRoster")
    return isinstance(roster, list) and bool(roster)


def workforce_preparation_refusal(action: str, result: Any) -> dict[str, Any]:
    """Preserve a preparation refusal before any goal-binding attempt."""

    payload = dict(result) if isinstance(result, Mapping) else {}
    issues = payload.get("issues")
    nested_plan = payload.get("executionPlan")
    if not isinstance(issues, list) and isinstance(nested_plan, Mapping):
        issues = nested_plan.get("issues")
    return {
        **payload,
        "action": action,
        "status": payload.get("status") or "rejected",
        "error": payload.get("error") or "workforce_preparation_not_executable",
        "issues": list(issues) if isinstance(issues, list) else [],
        "executionAllowed": False,
        "preparedButUnbound": False,
    }


def _execution_plan(preparation: Mapping[str, Any]) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    if preparation.get("schemaVersion") in {
        "agentlas.workforce-federated-preparation.v1",
        "agentlas.workforce-terminal-continuation.v1",
        "agentlas.workforce-desktop-continuation.v1",
    }:
        plan = preparation.get("executionPlan")
        pins = preparation.get("runtimeSourcePins")
    else:
        plan = preparation
        pins = []
    if not isinstance(plan, Mapping) or plan.get("status") != "prepared":
        raise WorkforceGoalBindingError("workforce_goal_preparation_not_ready")
    roster = plan.get("executionRoster")
    if not isinstance(roster, list) or not roster:
        raise WorkforceGoalBindingError("workforce_goal_roster_empty")
    if not isinstance(pins, list):
        pins = []
    return plan, [row for row in pins if isinstance(row, Mapping)]


def _source_by_pair(pins: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for pin in pins:
        key = (str(pin.get("slotId") or ""), str(pin.get("agentReleaseId") or ""))
        source = str(pin.get("source") or "")
        if key[0] and key[1] and source in {"local", "cloud", "hub"}:
            result[key] = source
    return result


def _roster_rows(
    preparation: Mapping[str, Any],
    labels: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
    plan, pins = _execution_plan(preparation)
    sources = _source_by_pair(pins)
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, raw in enumerate(plan["executionRoster"]):
        if not isinstance(raw, Mapping):
            raise WorkforceGoalBindingError("workforce_goal_roster_invalid")
        slot_id = str(raw.get("slotId") or "")
        definition_id = str(raw.get("agentDefinitionId") or "")
        release_id = str(raw.get("agentReleaseId") or "")
        package_hash = str(raw.get("packageHash") or "")
        content_digest = str(raw.get("contentDigest") or "")
        bundle_digest = str(raw.get("bundleDigest") or "")
        if (
            not slot_id
            or not definition_id
            or not release_id
            or not _HASH_RE.fullmatch(package_hash)
            or not _HASH_RE.fullmatch(content_digest)
            or not _HASH_RE.fullmatch(bundle_digest)
        ):
            raise WorkforceGoalBindingError("workforce_goal_roster_invalid")
        source = sources.get((slot_id, release_id), "local")
        roster_key = canonical_digest(
            {
                "schemaVersion": "agentlas.workforce-goal-roster-key.v1",
                "source": source,
                "slotId": slot_id,
                "agentDefinitionId": definition_id,
                "agentReleaseId": release_id,
                "packageHash": package_hash,
                "contentDigest": content_digest,
            }
        )
        if roster_key in seen:
            continue
        seen.add(roster_key)
        label_value = (labels or {}).get(release_id)
        label = str(label_value).strip()[:160] if isinstance(label_value, str) else release_id
        output.append(
            {
                "rosterKey": roster_key,
                "ordinal": ordinal,
                "source": source,
                "slotId": slot_id,
                "agentDefinitionId": definition_id,
                "agentReleaseId": release_id,
                "releaseVersion": str(raw.get("releaseVersion") or "")[:160] or None,
                "packageHash": package_hash,
                "contentDigest": content_digest,
                "bundleDigest": bundle_digest,
                "entityKind": str(raw.get("entityKind") or "")[:32] or None,
                "label": label,
            }
        )
    if not output:
        raise WorkforceGoalBindingError("workforce_goal_roster_empty")
    return plan, output


class WorkforceGoalStore:
    """SQLite-backed append-only roster bindings shared by local host adapters."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        account_partition: str | None = None,
        runtime_root: str | Path | None = None,
    ):
        self.path = Path(path).expanduser() if path else default_goal_store_path()
        self.runtime_root = (
            Path(runtime_root).expanduser()
            if runtime_root
            else (
                self.path.parent / "workforce-goal-runtime"
                if path is not None
                else default_goal_runtime_root()
            )
        )
        self.account_partition = account_partition or current_account_partition()
        if not _HASH_RE.fullmatch(self.account_partition):
            raise WorkforceGoalBindingError("workforce_goal_account_partition_invalid")
        self._ensure_store()

    def _ensure_store(self) -> None:
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.exists() and self.path.is_symlink():
            raise WorkforceGoalBindingError("workforce_goal_store_unsafe")
        if os.name == "posix":
            os.chmod(parent, 0o700)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS goal_bindings (
                  binding_id TEXT PRIMARY KEY,
                  goal_id TEXT NOT NULL,
                  account_partition TEXT NOT NULL,
                  project_key TEXT NOT NULL,
                  project_path TEXT NOT NULL,
                  goal_label TEXT,
                  status TEXT NOT NULL,
                  roster_revision INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  completed_at TEXT,
                  completion_reason TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_goal_binding_scope
                  ON goal_bindings(account_partition, project_key, goal_id);
                CREATE INDEX IF NOT EXISTS idx_goal_binding_active
                  ON goal_bindings(account_partition, project_key, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS goal_roster (
                  binding_id TEXT NOT NULL,
                  roster_key TEXT NOT NULL,
                  ordinal INTEGER NOT NULL,
                  source TEXT NOT NULL,
                  slot_id TEXT NOT NULL,
                  agent_definition_id TEXT NOT NULL,
                  agent_release_id TEXT NOT NULL,
                  release_version TEXT,
                  package_hash TEXT NOT NULL,
                  content_digest TEXT NOT NULL,
                  bundle_digest TEXT NOT NULL,
                  entity_kind TEXT,
                  display_label TEXT NOT NULL,
                  state TEXT NOT NULL,
                  added_revision INTEGER NOT NULL,
                  added_at TEXT NOT NULL,
                  last_used_at TEXT,
                  PRIMARY KEY(binding_id, roster_key),
                  FOREIGN KEY(binding_id) REFERENCES goal_bindings(binding_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS goal_turns (
                  binding_id TEXT NOT NULL,
                  turn_id TEXT NOT NULL,
                  occurred_at TEXT NOT NULL,
                  host_runtime TEXT,
                  decision TEXT NOT NULL,
                  used_roster_keys_json TEXT NOT NULL,
                  local_skill_ids_json TEXT NOT NULL,
                  gap_codes_json TEXT NOT NULL,
                  PRIMARY KEY(binding_id, turn_id),
                  FOREIGN KEY(binding_id) REFERENCES goal_bindings(binding_id) ON DELETE CASCADE
                );
                """
            )
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def _binding_runtime_dir(self, binding_id: str) -> Path:
        digest = binding_id.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise WorkforceGoalBindingError("workforce_goal_binding_id_invalid")
        return self.runtime_root / digest

    def _write_runtime_plan(
        self,
        *,
        binding_id: str,
        revision: int,
        preparation: Mapping[str, Any],
        roster_rows: Iterable[Mapping[str, Any]],
        created_at: str,
    ) -> None:
        root = self.runtime_root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink():
            raise WorkforceGoalBindingError("workforce_goal_runtime_cache_unsafe")
        directory = self._binding_runtime_dir(binding_id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink():
            raise WorkforceGoalBindingError("workforce_goal_runtime_cache_unsafe")
        payload = {
            "schemaVersion": "agentlas.workforce-goal-runtime-plan.v1",
            "bindingId": binding_id,
            "revision": revision,
            "createdAt": created_at,
            "sources": sorted(set(str(row.get("source") or "") for row in roster_rows)),
            "rosterKeys": [str(row.get("rosterKey") or "") for row in roster_rows],
            "agentReleaseIds": [str(row.get("agentReleaseId") or "") for row in roster_rows],
            "preparation": preparation,
        }
        target = directory / f"{revision:08d}.json"
        temporary = directory / f".{revision:08d}.{os.getpid()}.tmp"
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            remaining = memoryview(data.encode("utf-8"))
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise WorkforceGoalBindingError("workforce_goal_runtime_cache_write_failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, target)
        if os.name == "posix":
            os.chmod(root, 0o700)
            os.chmod(directory, 0o700)
            os.chmod(target, 0o600)

    @staticmethod
    def _lease_expirations(value: Any) -> list[str]:
        expirations: list[str] = []
        pending: list[tuple[Any, str]] = [(value, "")]
        visited = 0
        while pending:
            current, container_key = pending.pop()
            visited += 1
            if visited > 20_000:
                break
            if isinstance(current, Mapping):
                for key, child in current.items():
                    lease_expiry_key = key in {"leasedUntil", "leaseExpiresAt"} or (
                        key == "expiresAt" and "lease" in container_key.lower()
                    )
                    if lease_expiry_key and isinstance(child, str):
                        if child.endswith("Z") or "+" in child:
                            try:
                                datetime.fromisoformat(child.replace("Z", "+00:00"))
                            except ValueError:
                                pass
                            else:
                                expirations.append(child)
                    elif isinstance(child, (Mapping, list)):
                        pending.append((child, str(key)))
            elif isinstance(current, list):
                pending.extend((child, container_key) for child in current)
        return expirations

    @classmethod
    def _remote_execution_authorized(cls, preparation: Mapping[str, Any], instant: datetime) -> bool:
        """Accept exactly the authority each signed runtime row proves.

        Paid borrowed Hub/Cloud rows still require a live server lease. Owner
        and free rows do not mint rental leases, so their digest-bound
        ``charge.basis`` is the authoritative zero-credit execution proof.
        """
        execution_plan = preparation.get("executionPlan")
        if not isinstance(execution_plan, Mapping):
            return False
        roster = execution_plan.get("executionRoster")
        if not isinstance(roster, list) or not roster:
            return False
        for row in roster:
            if not isinstance(row, Mapping):
                return False
            directive = row.get("directiveBundle")
            envelope = directive.get("runtimeEnvelope") if isinstance(directive, Mapping) else None
            if not isinstance(envelope, Mapping):
                return False
            charge = envelope.get("charge")
            basis = charge.get("basis") if isinstance(charge, Mapping) else None
            if basis in {"owned", "free"}:
                continue
            expirations = cls._lease_expirations(envelope)
            if not expirations:
                return False
            try:
                parsed = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in expirations]
            except ValueError:
                return False
            if not parsed or not all(value > instant for value in parsed):
                return False
        return True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def bind(
        self,
        *,
        goal_id: str,
        project_dir: str | Path,
        preparation: Mapping[str, Any],
        goal_label: str | None = None,
        roster_labels: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        goal_id = _assert_goal_id(goal_id)
        project_key, project_path = _project_identity(project_dir)
        plan, rows = _roster_rows(preparation, roster_labels)
        if any(row["source"] in {"hub", "cloud"} for row in rows):
            if self.account_partition == unsigned_local_partition():
                raise WorkforceGoalBindingError("workforce_goal_remote_account_required")
        timestamp = _now()
        label = str(goal_label or "").strip()[:240] or None
        binding_id = canonical_digest(
            {
                "schemaVersion": WORKFORCE_GOAL_BINDING_SCHEMA,
                "accountPartition": self.account_partition,
                "projectKey": project_key,
                "goalId": goal_id,
            }
        )
        with self._connect() as conn:
            prior = conn.execute(
                "SELECT status, roster_revision FROM goal_bindings WHERE binding_id = ?",
                (binding_id,),
            ).fetchone()
            if prior is not None and str(prior["status"]) in _TERMINAL_STATUSES:
                raise WorkforceGoalBindingError("workforce_goal_already_terminal")
            revision = int(prior["roster_revision"]) + 1 if prior is not None else 1
            conn.execute(
                """
                INSERT INTO goal_bindings
                  (binding_id, goal_id, account_partition, project_key, project_path,
                   goal_label, status, roster_revision, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(binding_id) DO UPDATE SET
                  goal_label = COALESCE(excluded.goal_label, goal_bindings.goal_label),
                  status = 'active',
                  roster_revision = excluded.roster_revision,
                  updated_at = excluded.updated_at
                """,
                (
                    binding_id,
                    goal_id,
                    self.account_partition,
                    project_key,
                    project_path,
                    label,
                    revision,
                    timestamp,
                    timestamp,
                ),
            )
            inserted = 0
            for row in rows:
                result = conn.execute(
                    """
                    INSERT OR IGNORE INTO goal_roster
                      (binding_id, roster_key, ordinal, source, slot_id,
                       agent_definition_id, agent_release_id, release_version,
                       package_hash, content_digest, bundle_digest, entity_kind,
                       display_label, state, added_revision, added_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'standby', ?, ?)
                    """,
                    (
                        binding_id,
                        row["rosterKey"],
                        row["ordinal"],
                        row["source"],
                        row["slotId"],
                        row["agentDefinitionId"],
                        row["agentReleaseId"],
                        row["releaseVersion"],
                        row["packageHash"],
                        row["contentDigest"],
                        row["bundleDigest"],
                        row["entityKind"],
                        row["label"],
                        revision,
                        timestamp,
                    ),
                )
                inserted += int(result.rowcount > 0)
            if inserted == 0 and prior is not None:
                conn.execute(
                    "UPDATE goal_bindings SET roster_revision = ?, updated_at = ? WHERE binding_id = ?",
                    (int(prior["roster_revision"]), timestamp, binding_id),
                )
        runtime_revision = revision if prior is None or inserted else int(prior["roster_revision"])
        self._write_runtime_plan(
            binding_id=binding_id,
            revision=runtime_revision,
            preparation=preparation,
            roster_rows=rows,
            created_at=timestamp,
        )
        context = self.context(goal_id=goal_id, project_dir=project_path)
        context["bindAction"] = "created" if prior is None else ("recruited" if inserted else "reused")
        context["addedRosterCount"] = inserted
        context["preparationReceiptId"] = plan.get("preparationReceiptId")
        return context

    def context(
        self,
        *,
        project_dir: str | Path,
        goal_id: str | None = None,
        include_terminal: bool = False,
    ) -> dict[str, Any]:
        project_key, _ = _project_identity(project_dir)
        params: list[Any] = [self.account_partition, project_key]
        where = "account_partition = ? AND project_key = ?"
        if goal_id is not None:
            where += " AND goal_id = ?"
            params.append(_assert_goal_id(goal_id))
        if not include_terminal:
            where += " AND status = 'active'"
        with self._connect() as conn:
            bindings = conn.execute(
                f"SELECT * FROM goal_bindings WHERE {where} ORDER BY updated_at DESC LIMIT 8",
                params,
            ).fetchall()
            goals: list[dict[str, Any]] = []
            for binding in bindings:
                roster_rows = conn.execute(
                    """
                    SELECT roster_key, source, slot_id, agent_definition_id,
                           agent_release_id, release_version, entity_kind,
                           display_label, state, added_revision, added_at, last_used_at
                    FROM goal_roster
                    WHERE binding_id = ?
                    ORDER BY added_revision, ordinal, agent_release_id
                    """,
                    (binding["binding_id"],),
                ).fetchall()
                goals.append(
                    {
                        "bindingId": binding["binding_id"],
                        "goalId": binding["goal_id"],
                        "goalLabel": binding["goal_label"],
                        "status": binding["status"],
                        "rosterRevision": binding["roster_revision"],
                        "createdAt": binding["created_at"],
                        "updatedAt": binding["updated_at"],
                        "completedAt": binding["completed_at"],
                        "roster": [
                            {
                                "rosterKey": row["roster_key"],
                                "source": row["source"],
                                "slotId": row["slot_id"],
                                "agentDefinitionId": row["agent_definition_id"],
                                "agentReleaseId": row["agent_release_id"],
                                "releaseVersion": row["release_version"],
                                "entityKind": row["entity_kind"],
                                "label": row["display_label"],
                                "state": row["state"],
                                "addedRevision": row["added_revision"],
                                "addedAt": row["added_at"],
                                "lastUsedAt": row["last_used_at"],
                            }
                            for row in roster_rows
                        ],
                    }
                )
        # Signing in switches the partition, so rosters bound while signed out
        # stop appearing here. Nothing was deleted — the reader is looking in a
        # different drawer — but to the user "I signed in and my team vanished"
        # is indistinguishable from data loss (measured 2026-08-25: 2 goals /
        # 21 roster rows visible before login, `goals: []` after). Merging
        # across partitions is a cross-account write and needs an owner
        # decision; SAYING the other drawer is non-empty does not. Count only.
        unsigned_leftovers = 0
        if self.account_partition != unsigned_local_partition():
            with self._connect() as conn:
                unsigned_leftovers = int(
                    conn.execute(
                        "SELECT count(*) FROM goal_bindings"
                        " WHERE account_partition = ? AND project_key = ? AND status = 'active'",
                        (unsigned_local_partition(), project_key),
                    ).fetchone()[0]
                )
        payload: dict[str, Any] = {
            "schemaVersion": WORKFORCE_GOAL_CONTEXT_SCHEMA,
            "accountPartition": self.account_partition,
            "projectKey": project_key,
            "goals": goals,
            "continuityPolicy": {
                "terminalOnlyOnExplicitCompletion": True,
                "leaseExpiryDoesNotCompleteGoal": True,
                "reuseRosterBeforeRecruitment": True,
                "recruitmentIsAdditive": True,
                "standbyMeansBoundNotContinuouslyExecuting": True,
            },
        }
        if unsigned_leftovers:
            payload["signedOutGoalsForThisProject"] = unsigned_leftovers
            payload["signedOutGoalsNotice"] = (
                "This project has active goal bindings created before sign-in. "
                "They live in the signed-out local drawer and are not shown "
                "here; sign out to see them, or ask the owner to migrate them."
            )
        return payload

    def runtime_context(
        self,
        *,
        project_dir: str | Path,
        goal_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        context = self.context(project_dir=project_dir, goal_id=goal_id)
        if not context["goals"]:
            return {
                "schemaVersion": "agentlas.workforce-goal-runtime-context.v1",
                "status": "not-bound",
                "goals": [],
            }
        instant = now or datetime.now(timezone.utc)
        goals: list[dict[str, Any]] = []
        for goal in context["goals"]:
            directory = self._binding_runtime_dir(goal["bindingId"])
            plans: list[dict[str, Any]] = []
            if directory.is_dir() and not directory.is_symlink():
                for path in sorted(directory.glob("*.json"))[:128]:
                    try:
                        if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
                            continue
                        payload = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    if (
                        not isinstance(payload, Mapping)
                        or payload.get("schemaVersion") != "agentlas.workforce-goal-runtime-plan.v1"
                        or payload.get("bindingId") != goal["bindingId"]
                        or not isinstance(payload.get("preparation"), Mapping)
                    ):
                        continue
                    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
                    remote = any(source in {"cloud", "hub"} for source in sources)
                    expirations = self._lease_expirations(payload["preparation"])
                    parsed_expirations = [
                        datetime.fromisoformat(value.replace("Z", "+00:00"))
                        for value in expirations
                    ]
                    lease_expires_at = min(parsed_expirations).isoformat().replace("+00:00", "Z") if parsed_expirations else None
                    lease_active = (
                        not remote
                        or self._remote_execution_authorized(payload["preparation"], instant)
                        or bool(parsed_expirations and all(value > instant for value in parsed_expirations))
                    )
                    plans.append(
                        {
                            "revision": payload.get("revision"),
                            "createdAt": payload.get("createdAt"),
                            "sources": sources,
                            "rosterKeys": [
                                str(value)
                                for value in (payload.get("rosterKeys") or [])
                                if isinstance(value, str) and _HASH_RE.fullmatch(value)
                            ],
                            "agentReleaseIds": [
                                str(value)
                                for value in (payload.get("agentReleaseIds") or [])
                                if isinstance(value, str)
                            ],
                            "leaseExpiresAt": lease_expires_at,
                            "status": "ready" if lease_active else "lease-refresh-required",
                            **({"preparation": payload["preparation"]} if lease_active else {}),
                        }
                    )
            goals.append(
                {
                    "goalId": goal["goalId"],
                    "bindingId": goal["bindingId"],
                    "status": goal["status"],
                    "plans": plans,
                    "executionAllowed": any(plan["status"] == "ready" for plan in plans),
                }
            )
        return {
            "schemaVersion": "agentlas.workforce-goal-runtime-context.v1",
            "status": "ready" if all(goal["executionAllowed"] for goal in goals) else "refresh-required",
            "goals": goals,
        }

    def record_turn(
        self,
        *,
        goal_id: str,
        project_dir: str | Path,
        turn_id: str,
        decision: str,
        used_roster_keys: Iterable[str] = (),
        local_skill_ids: Iterable[str] = (),
        gap_codes: Iterable[str] = (),
        host_runtime: str | None = None,
    ) -> dict[str, Any]:
        goal_id = _assert_goal_id(goal_id)
        turn_id = str(turn_id or "").strip()
        if not _GOAL_ID_RE.fullmatch(turn_id):
            raise WorkforceGoalBindingError("workforce_goal_turn_id_invalid")
        if decision not in _DECISIONS:
            raise WorkforceGoalBindingError("workforce_goal_turn_decision_invalid")
        context = self.context(project_dir=project_dir, goal_id=goal_id)
        if not context["goals"]:
            raise WorkforceGoalBindingError("workforce_goal_active_binding_not_found")
        goal = context["goals"][0]
        known = {row["rosterKey"] for row in goal["roster"]}
        used = sorted(set(str(value) for value in used_roster_keys))
        if any(value not in known for value in used):
            raise WorkforceGoalBindingError("workforce_goal_turn_roster_mismatch")
        skills = sorted(set(str(value).strip()[:160] for value in local_skill_ids if str(value).strip()))[:128]
        gaps = sorted(set(str(value).strip()[:160] for value in gap_codes if str(value).strip()))[:128]
        timestamp = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO goal_turns
                  (binding_id, turn_id, occurred_at, host_runtime, decision,
                   used_roster_keys_json, local_skill_ids_json, gap_codes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(binding_id, turn_id) DO UPDATE SET
                  host_runtime = excluded.host_runtime,
                  decision = excluded.decision,
                  used_roster_keys_json = excluded.used_roster_keys_json,
                  local_skill_ids_json = excluded.local_skill_ids_json,
                  gap_codes_json = excluded.gap_codes_json
                """,
                (
                    goal["bindingId"],
                    turn_id,
                    timestamp,
                    str(host_runtime or "").strip()[:80] or None,
                    decision,
                    json.dumps(used, separators=(",", ":")),
                    json.dumps(skills, separators=(",", ":")),
                    json.dumps(gaps, separators=(",", ":")),
                ),
            )
            if used:
                placeholders = ",".join("?" for _ in used)
                conn.execute(
                    f"""
                    UPDATE goal_roster SET state = 'active', last_used_at = ?
                    WHERE binding_id = ? AND roster_key IN ({placeholders})
                    """,
                    (timestamp, goal["bindingId"], *used),
                )
                conn.execute(
                    f"""
                    UPDATE goal_roster SET state = 'standby'
                    WHERE binding_id = ? AND roster_key NOT IN ({placeholders})
                    """,
                    (goal["bindingId"], *used),
                )
            else:
                conn.execute(
                    "UPDATE goal_roster SET state = 'standby' WHERE binding_id = ?",
                    (goal["bindingId"],),
                )
            conn.execute(
                "UPDATE goal_bindings SET updated_at = ? WHERE binding_id = ?",
                (timestamp, goal["bindingId"]),
            )
        return {
            "schemaVersion": WORKFORCE_GOAL_TURN_SCHEMA,
            "status": "recorded",
            "goalId": goal_id,
            "turnId": turn_id,
            "decision": decision,
            "usedRosterKeys": used,
            "localSkillIds": skills,
            "gapCodes": gaps,
            "occurredAt": timestamp,
        }

    def complete(
        self,
        *,
        goal_id: str,
        project_dir: str | Path,
        explicit_completion: bool,
        status: str = "completed",
        reason: str = "explicit-host-goal-terminal",
    ) -> dict[str, Any]:
        if explicit_completion is not True:
            raise WorkforceGoalBindingError("workforce_goal_explicit_completion_required")
        goal_id = _assert_goal_id(goal_id)
        if status not in _TERMINAL_STATUSES:
            raise WorkforceGoalBindingError("workforce_goal_terminal_status_invalid")
        context = self.context(project_dir=project_dir, goal_id=goal_id)
        if not context["goals"]:
            raise WorkforceGoalBindingError("workforce_goal_active_binding_not_found")
        goal = context["goals"][0]
        timestamp = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE goal_bindings
                SET status = ?, updated_at = ?, completed_at = ?, completion_reason = ?
                WHERE binding_id = ? AND status = 'active'
                """,
                (status, timestamp, timestamp, str(reason or "")[:160], goal["bindingId"]),
            )
            conn.execute(
                "UPDATE goal_roster SET state = 'released' WHERE binding_id = ?",
                (goal["bindingId"],),
            )
        runtime_dir = self._binding_runtime_dir(goal["bindingId"])
        if runtime_dir.is_dir() and not runtime_dir.is_symlink():
            for path in runtime_dir.glob("*.json"):
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            try:
                runtime_dir.rmdir()
            except OSError:
                pass
        return {
            "schemaVersion": WORKFORCE_GOAL_BINDING_SCHEMA,
            "status": status,
            "goalId": goal_id,
            "bindingId": goal["bindingId"],
            "completedAt": timestamp,
            "leaseStateChanged": False,
        }


def _readable_roster_name(row: Mapping[str, Any]) -> str:
    """A roster line a person can read.

    Automatic binding used to store no label at all, so `display_label` fell
    back to a release id. Those rows still exist, and a warning made of hashes
    is a warning nobody acts on. Prefer the stored name; otherwise name the
    post plus a short id so the row is still identifiable.
    """

    label = str(row.get("label") or "").strip()
    release_id = str(row.get("agentReleaseId") or "").strip()
    if label and label != release_id and not _OPAQUE_LABEL_RE.match(label):
        return label[:80]
    slot = str(row.get("slotId") or "slot").removeprefix("slot:")
    return f"{slot}({release_id[-8:] or 'unknown'})"


def prepared_not_executed_notice(project_dir: str | Path) -> str:
    """One user-facing sentence when a bound roster was prepared and never run.

    ★"내는 결과에는 유저가 볼 수 있는 사실이 있어야 한다" 의 실행판.

    실행 단계(SKILL.md 6·7절)는 전부 모델에게 주는 지시였고, 그것을 관측하는
    호스트 장치가 하나도 없었다. 그래서 "준비만 하고 종료"가 명백한 계약 위반인데
    아무도 못 잡았다 — 실측 2026-08-21: 이 프로젝트 로스터 21행 중 19행(90%)이
    lastUsedAt=null, 즉 실행됐다는 주장조차 없었다. 세션 종료는 모든 설치가
    반드시 지나는 한 지점이므로, 새 훅 이벤트를 등록하지 않고 여기서 사실을
    말한다. 막지는 않는다 — 판단은 사람이 하고, 침묵만 없앤다.
    """

    try:
        context = WorkforceGoalStore().context(project_dir=project_dir)
    except (OSError, sqlite3.Error, WorkforceGoalBindingError, ValueError):
        return ""
    names: list[str] = []
    goals = 0
    for goal in context.get("goals") or []:
        if not isinstance(goal, Mapping) or goal.get("status") != "active":
            continue
        pending = [
            _readable_roster_name(row)
            for row in goal.get("roster") or []
            if isinstance(row, Mapping) and not row.get("lastUsedAt")
        ]
        if pending:
            goals += 1
            names.extend(pending)
    if not names:
        return ""
    unique = list(dict.fromkeys(names))
    shown = ", ".join(unique[:6])
    if len(unique) > 6:
        shown += f", +{len(unique) - 6} more"
    return (
        f"Agentlas Workforce: {len(names)} prepared agent(s) across {goals} active goal(s) "
        f"have never been executed — {shown}. Preparation is not delivery. Either run them and record "
        "the turn with workforce.record_goal_turn, or tell the user the roster is prepared but not executed."
    )


def compact_goal_context(
    project_dir: str | Path,
    *,
    account_partition: str | None = None,
    limit: int = 3,
) -> list[str]:
    """Return bounded prompt-safe lines for SessionStart/UserPromptSubmit hooks."""

    try:
        context = WorkforceGoalStore(account_partition=account_partition).context(project_dir=project_dir)
    except (OSError, sqlite3.Error, WorkforceGoalBindingError):
        return []
    lines: list[str] = []
    for goal in context["goals"][: max(1, min(8, limit))]:
        roster = ", ".join(
            f"{row['label']} [{row['source']} {row['agentReleaseId']}] ({row['state']})"
            for row in goal["roster"][:32]
        )
        lines.append(
            "workforce-goal: "
            f"id={goal['goalId']}; status={goal['status']}; revision={goal['rosterRevision']}; "
            f"roster={roster or '(empty)'}"
        )
    if lines:
        lines.append(
            "workforce-policy: this roster is bound until explicit goal completion; "
            "on this turn reuse it plus local skills when sufficient, recruit only a real gap, "
            "and treat standby as durable availability rather than a continuously running model. "
            "A 24-hour Hub lease affects the next server-side charge only and never ends this binding."
        )
    return lines


def bind_prepared_goal(
    *,
    work_order: Mapping[str, Any],
    project_dir: str | Path,
    preparation: Mapping[str, Any],
    requested_goal_id: str | None = None,
    goal_label: str | None = None,
    roster_labels: Mapping[str, Any] | None = None,
    store: WorkforceGoalStore | None = None,
) -> dict[str, Any]:
    """Mandatory post-prepare gate used by CLI/MCP/Desktop/Terminal adapters."""

    goal_store = store or WorkforceGoalStore()
    resolved_goal_id = resolve_continuity_goal_id(
        project_dir=project_dir,
        work_order=work_order,
        requested_goal_id=requested_goal_id,
        store=goal_store,
    )
    return goal_store.bind(
        goal_id=resolved_goal_id,
        project_dir=project_dir,
        preparation=preparation,
        goal_label=goal_label or "automatic Workforce continuity",
        roster_labels=roster_labels,
    )


__all__ = [
    "WORKFORCE_GOAL_BINDING_SCHEMA",
    "WORKFORCE_GOAL_CONTEXT_SCHEMA",
    "WORKFORCE_GOAL_TURN_SCHEMA",
    "WorkforceGoalBindingError",
    "WorkforceGoalStore",
    "compact_goal_context",
    "prepared_not_executed_notice",
    "bind_prepared_goal",
    "account_partition_for_subject",
    "current_account_partition",
    "default_goal_store_path",
    "default_goal_runtime_root",
    "implicit_goal_id",
    "resolve_continuity_goal_id",
    "workforce_preparation_ready",
    "workforce_preparation_refusal",
]
