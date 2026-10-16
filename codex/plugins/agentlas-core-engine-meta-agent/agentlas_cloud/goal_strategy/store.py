"""File store for one goal under <project>/.agentlas/goal/<goal_id>/.

plan.json        current plan snapshot, one `revision` integer that every write must quote (compare-and-set)
decisions.jsonl  append-only ledger of plan operations, state changes, shifts and owner reports
kpi.jsonl        append-only KPI samples
state.json       KPI state rows and the open trigger

Writes take an exclusive flock on `.lock`, then replace files by rename, so the app, a daemon and a host session cannot
interleave. A repeated call with the same idempotency key returns the first receipt instead of writing again.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

GOAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class GoalStoreError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class RevisionConflict(GoalStoreError):
    pass


class GoalStore:
    def __init__(self, project_dir: str | os.PathLike[str], goal_id: str):
        if not GOAL_ID_RE.match(goal_id or ""):
            raise GoalStoreError("goal_id_invalid", goal_id)
        project = Path(project_dir).expanduser().resolve()
        if not project.is_dir():
            raise GoalStoreError("project_missing", str(project))
        self.goal_id = goal_id
        self.root = project / ".agentlas" / "goal" / goal_id

    @property
    def plan_path(self) -> Path:
        return self.root / "plan.json"

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.root / ".lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def exists(self) -> bool:
        return self.plan_path.is_file()

    def _read(self, name: str, default: Any) -> Any:
        path = self.root / name
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, name: str, payload: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.root), prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.root / name)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def read_plan(self) -> dict[str, Any] | None:
        return self._read("plan.json", None)

    def write_plan(self, plan: dict[str, Any], expect_revision: int | None) -> dict[str, Any]:
        """Compare-and-set. Call inside `locked()`; returns the stored plan with its new revision."""
        current = self.read_plan()
        have = current["revision"] if current else 0
        if expect_revision is not None and have != expect_revision:
            raise RevisionConflict("revision_conflict", f"expected {expect_revision}, store has {have}")
        stored = dict(plan)
        stored["revision"] = have + 1
        self._write("plan.json", stored)
        return stored

    def read_state(self) -> dict[str, Any]:
        return self._read("state.json", {"kpis": {}, "trigger": None, "owner_hold": None})

    def write_state(self, state: dict[str, Any]) -> None:
        self._write("state.json", state)

    def append(self, name: str, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / name, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def rows(self, name: str) -> list[dict[str, Any]]:
        path = self.root / name
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue  # a torn last line from a crash is skipped, never repaired in place
        return out

    def receipt_for(self, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        for row in reversed(self.rows("decisions.jsonl")):
            if row.get("idempotency_key") == key:
                return row.get("receipt")
        return None
