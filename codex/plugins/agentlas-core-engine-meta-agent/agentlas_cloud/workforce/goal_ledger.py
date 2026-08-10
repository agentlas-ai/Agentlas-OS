"""Persistent-goal ledger — the durable state that turns "goal" into a loop.

The three existing goal assets never shared state:

* Desktop ``goalMode`` was a prompt prefix (no persistence);
* ``goal_binding.py`` is a roster accounting book (who is hired, not what
  remains to be done);
* ``continuousMode``/Stormbreaker is an execution loop whose only continuation
  signal was a model-authored marker.

This module owns the missing half: an objective with acceptance criteria, a
task list, cycle accounting, and a **host-owned continue decision** that does
not depend on the model remembering to emit a marker.  The contract mirrors
``networking/goal_loop.py``: progress is measured with a ``progress_key``
(identical consecutive keys mean "no progress"), and a stall streak blocks the
goal so a human is called instead of burning cycles forever.

Storage lives in the same SQLite file as ``goal_bindings``
(``~/.agentlas/networking/workforce-goals.sqlite3``) so ``goal_id`` is one
shared axis across the roster store and this ledger, for every surface
(Desktop, terminal, Claude Code adapters).

Budgets here are **goal budgets** (wallclock deadline, total cycles, cumulative
cost, no-progress stall).  They are deliberately separate from per-turn watchdog
budgets (idle/active-tool/ceiling minutes), which protect a single CLI call and
must not be conflated with "how long may this goal live" — a goal may run for
days or a year.

No prompt text beyond the objective/task summaries is persisted; no
credentials, model output transcripts, or private package content.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator, Mapping

from .goal_binding import _GOAL_ID_RE, default_goal_store_path

GOAL_LEDGER_SCHEMA = "agentlas.goal-ledger.v1"
GOAL_LEDGER_DECISION_SCHEMA = "agentlas.goal-ledger-decision.v1"

GOAL_STATUSES = frozenset({"active", "completed", "cancelled", "blocked"})
GOAL_TERMINAL_STATUSES = frozenset({"completed", "cancelled"})
TASK_STATES = frozenset({"todo", "doing", "done", "blocked"})
OPEN_TASK_STATES = ("todo", "doing", "blocked")

#: After this many consecutive no-progress cycles the goal is blocked and a
#: human is called (the "don't run away" half of the goal-loop contract).
DEFAULT_STALL_WINDOW = 5

#: A goal created before the model decomposed the objective still needs one
#: open task, otherwise the continue decision dead-ends at "no open tasks"
#: before the first cycle ever runs.
BOOTSTRAP_TASK_ID = "task:bootstrap"
BOOTSTRAP_TASK_SUMMARY = (
    "Decompose the objective into concrete tasks and verify the acceptance criteria"
)

# Continue-decision reason codes (machine markers — hosts must branch on these,
# never on prose).
REASON_GOAL_NOT_FOUND = "goal_not_found"
REASON_GOAL_TERMINAL = "goal_terminal"
REASON_GOAL_BLOCKED = "goal_blocked"
REASON_BUDGET_WALLCLOCK = "budget_wallclock_exhausted"
REASON_BUDGET_CYCLES = "budget_cycles_exhausted"
REASON_BUDGET_COST = "budget_cost_exhausted"
REASON_NO_OPEN_TASKS = "no_open_tasks"
REASON_OPEN_TASKS_REMAIN = "open_tasks_remain"

BLOCKED_REASON_STALL = "no_progress_stall"


class GoalLedgerError(ValueError):
    """Finite goal-ledger failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _assert_goal_id(goal_id: str) -> str:
    value = str(goal_id or "").strip()
    if not _GOAL_ID_RE.fullmatch(value):
        raise GoalLedgerError("goal_ledger_goal_id_invalid")
    return value


def _parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _task_id_for_summary(summary: str) -> str:
    digest = hashlib.sha256(summary.strip().encode("utf-8")).hexdigest()[:16]
    return f"task:{digest}"


def _bounded(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


class GoalLedgerStore:
    """SQLite-backed persistent-goal ledger shared by every local host surface."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else default_goal_store_path()
        self._ensure_store()

    def _ensure_store(self) -> None:
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.exists() and self.path.is_symlink():
            raise GoalLedgerError("goal_ledger_store_unsafe")
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS goal_ledger (
                  goal_id TEXT PRIMARY KEY,
                  objective TEXT NOT NULL,
                  acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
                  status TEXT NOT NULL DEFAULT 'active',
                  project_path TEXT,
                  wallclock_deadline TEXT,
                  max_cycles INTEGER,
                  max_cost_usd REAL,
                  cost_used_usd REAL NOT NULL DEFAULT 0,
                  cycle_count INTEGER NOT NULL DEFAULT 0,
                  no_progress_streak INTEGER NOT NULL DEFAULT 0,
                  stall_window INTEGER NOT NULL DEFAULT 5,
                  last_progress_key TEXT,
                  last_outcome TEXT,
                  last_cycle_at TEXT,
                  next_cycle_at TEXT,
                  blocked_reason TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS goal_tasks (
                  goal_id TEXT NOT NULL,
                  task_id TEXT NOT NULL,
                  state TEXT NOT NULL DEFAULT 'todo',
                  summary TEXT NOT NULL,
                  evidence_ref TEXT,
                  blocked_reason TEXT,
                  discovered_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY (goal_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_goal_tasks_state
                  ON goal_tasks(goal_id, state);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── goal lifecycle ─────────────────────────────────────────────

    def create(
        self,
        *,
        goal_id: str,
        objective: str,
        acceptance_criteria: Iterable[str] = (),
        project_dir: str | Path | None = None,
        wallclock_deadline: str | None = None,
        max_cycles: int | None = None,
        max_cost_usd: float | None = None,
        stall_window: int | None = None,
        tasks: Iterable[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """Idempotent upsert.

        * Missing goal → new active row (plus a bootstrap task when no task list
          was provided, so the continue decision never dead-ends before cycle 1).
        * Existing non-terminal goal → objective/criteria/budgets are updated
          only when explicitly provided; counters are preserved.
        * Existing terminal goal → reactivated as a new campaign: status back to
          ``active``, stall streak and blocked reason cleared, cumulative
          ``cycle_count``/cost preserved for honest accounting.
        """

        goal_id = _assert_goal_id(goal_id)
        objective_text = str(objective or "").strip()[:2_000]
        criteria = [str(c).strip()[:500] for c in acceptance_criteria if str(c).strip()][:32]
        window = int(stall_window) if stall_window is not None and int(stall_window) >= 1 else None
        timestamp = _now()
        with self._connect() as conn:
            prior = conn.execute(
                "SELECT * FROM goal_ledger WHERE goal_id = ?", (goal_id,)
            ).fetchone()
            if prior is None:
                if not objective_text:
                    raise GoalLedgerError("goal_ledger_objective_required")
                conn.execute(
                    """
                    INSERT INTO goal_ledger
                      (goal_id, objective, acceptance_criteria_json, status, project_path,
                       wallclock_deadline, max_cycles, max_cost_usd, stall_window,
                       created_at, updated_at)
                    VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        goal_id,
                        objective_text,
                        json.dumps(criteria, ensure_ascii=False),
                        _bounded(project_dir, 1_024),
                        _bounded(wallclock_deadline, 64),
                        max_cycles,
                        max_cost_usd,
                        window or DEFAULT_STALL_WINDOW,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                updates: list[str] = ["updated_at = ?"]
                params: list[Any] = [timestamp]
                if objective_text:
                    updates.append("objective = ?")
                    params.append(objective_text)
                if criteria:
                    updates.append("acceptance_criteria_json = ?")
                    params.append(json.dumps(criteria, ensure_ascii=False))
                if wallclock_deadline is not None:
                    updates.append("wallclock_deadline = ?")
                    params.append(_bounded(wallclock_deadline, 64))
                if max_cycles is not None:
                    updates.append("max_cycles = ?")
                    params.append(int(max_cycles))
                if max_cost_usd is not None:
                    updates.append("max_cost_usd = ?")
                    params.append(float(max_cost_usd))
                if window is not None:
                    updates.append("stall_window = ?")
                    params.append(window)
                if str(prior["status"]) != "active":
                    # Reactivation is a fresh campaign, not a silent overwrite:
                    # the stall streak restarts but the cumulative counters stay.
                    updates.extend(
                        [
                            "status = 'active'",
                            "blocked_reason = NULL",
                            "no_progress_streak = 0",
                            "last_progress_key = NULL",
                            "completed_at = NULL",
                        ]
                    )
                params.append(goal_id)
                conn.execute(
                    f"UPDATE goal_ledger SET {', '.join(updates)} WHERE goal_id = ?",
                    params,
                )
            requested = [
                {
                    "task_id": _bounded(task.get("task_id"), 160) or _task_id_for_summary(str(task.get("summary") or "")),
                    "summary": str(task.get("summary") or "").strip()[:500],
                    "state": task.get("state") if task.get("state") in TASK_STATES else "todo",
                }
                for task in tasks
                if isinstance(task, Mapping) and str(task.get("summary") or "").strip()
            ]
            open_count = self._open_task_count(conn, goal_id)
            if not requested and prior is None and open_count == 0:
                requested = [
                    {
                        "task_id": BOOTSTRAP_TASK_ID,
                        "summary": BOOTSTRAP_TASK_SUMMARY,
                        "state": "todo",
                    }
                ]
            for task in requested:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO goal_tasks
                      (goal_id, task_id, state, summary, discovered_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (goal_id, task["task_id"], task["state"], task["summary"], timestamp, timestamp),
                )
        return self.get(goal_id) or {}

    def get(self, goal_id: str) -> dict[str, Any] | None:
        goal_id = _assert_goal_id(goal_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM goal_ledger WHERE goal_id = ?", (goal_id,)
            ).fetchone()
            if row is None:
                return None
            open_count = self._open_task_count(conn, goal_id)
        try:
            criteria = json.loads(row["acceptance_criteria_json"] or "[]")
        except json.JSONDecodeError:
            criteria = []
        return {
            "schemaVersion": GOAL_LEDGER_SCHEMA,
            "goalId": row["goal_id"],
            "objective": row["objective"],
            "acceptanceCriteria": criteria if isinstance(criteria, list) else [],
            "status": row["status"],
            "projectPath": row["project_path"],
            "budget": {
                "wallclockDeadline": row["wallclock_deadline"],
                "maxCycles": row["max_cycles"],
                "maxCostUsd": row["max_cost_usd"],
                "costUsedUsd": row["cost_used_usd"],
                "stallWindow": row["stall_window"],
            },
            "cycleCount": row["cycle_count"],
            "noProgressStreak": row["no_progress_streak"],
            "lastProgressKey": row["last_progress_key"],
            "lastOutcome": row["last_outcome"],
            "lastCycleAt": row["last_cycle_at"],
            "nextCycleAt": row["next_cycle_at"],
            "blockedReason": row["blocked_reason"],
            "openTaskCount": open_count,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "completedAt": row["completed_at"],
        }

    def complete_goal(
        self,
        *,
        goal_id: str,
        status: str = "completed",
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Explicit terminal (or human-call ``blocked``) transition.

        ``completed``/``cancelled`` are terminal; ``blocked`` keeps the goal
        recoverable (a later ``create`` reactivates it).  On ``completed`` the
        remaining open tasks are closed as done with a goal-terminal evidence
        marker, so the ledger never shows a completed goal with open work.
        """

        goal_id = _assert_goal_id(goal_id)
        if status not in {"completed", "cancelled", "blocked"}:
            raise GoalLedgerError("goal_ledger_terminal_status_invalid")
        timestamp = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM goal_ledger WHERE goal_id = ?", (goal_id,)
            ).fetchone()
            if row is None:
                raise GoalLedgerError("goal_ledger_goal_not_found")
            conn.execute(
                """
                UPDATE goal_ledger
                SET status = ?, blocked_reason = ?, updated_at = ?,
                    completed_at = CASE WHEN ? IN ('completed','cancelled') THEN ? ELSE completed_at END
                WHERE goal_id = ?
                """,
                (
                    status,
                    _bounded(reason, 240) if status == "blocked" else None,
                    timestamp,
                    status,
                    timestamp,
                    goal_id,
                ),
            )
            if status == "completed":
                conn.execute(
                    """
                    UPDATE goal_tasks
                    SET state = 'done', evidence_ref = COALESCE(evidence_ref, 'goal-terminal'),
                        updated_at = ?
                    WHERE goal_id = ? AND state IN ('todo','doing','blocked')
                    """,
                    (timestamp, goal_id),
                )
        return {
            "schemaVersion": GOAL_LEDGER_SCHEMA,
            "goalId": goal_id,
            "status": status,
            "reason": _bounded(reason, 240),
            "completedAt": timestamp if status in GOAL_TERMINAL_STATUSES else None,
        }

    # ── tasks ──────────────────────────────────────────────────────

    def add_tasks(self, goal_id: str, tasks: Iterable[Mapping[str, Any] | str]) -> dict[str, Any]:
        goal_id = _assert_goal_id(goal_id)
        timestamp = _now()
        added = 0
        with self._connect() as conn:
            if conn.execute(
                "SELECT 1 FROM goal_ledger WHERE goal_id = ?", (goal_id,)
            ).fetchone() is None:
                raise GoalLedgerError("goal_ledger_goal_not_found")
            for raw in tasks:
                entry: Mapping[str, Any] = {"summary": raw} if isinstance(raw, str) else raw
                summary = str(entry.get("summary") or "").strip()[:500]
                if not summary:
                    continue
                task_id = _bounded(entry.get("task_id"), 160) or _task_id_for_summary(summary)
                state = entry.get("state") if entry.get("state") in TASK_STATES else "todo"
                result = conn.execute(
                    """
                    INSERT OR IGNORE INTO goal_tasks
                      (goal_id, task_id, state, summary, discovered_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (goal_id, task_id, state, summary, timestamp, timestamp),
                )
                added += int(result.rowcount > 0)
            if added:
                conn.execute(
                    "UPDATE goal_ledger SET updated_at = ? WHERE goal_id = ?",
                    (timestamp, goal_id),
                )
        return {"schemaVersion": GOAL_LEDGER_SCHEMA, "goalId": goal_id, "added": added}

    def list_open_tasks(self, goal_id: str) -> list[dict[str, Any]]:
        goal_id = _assert_goal_id(goal_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, state, summary, evidence_ref, blocked_reason,
                       discovered_at, updated_at
                FROM goal_tasks
                WHERE goal_id = ? AND state IN ('todo','doing','blocked')
                ORDER BY discovered_at, task_id
                """,
                (goal_id,),
            ).fetchall()
        return [
            {
                "taskId": row["task_id"],
                "state": row["state"],
                "summary": row["summary"],
                "evidenceRef": row["evidence_ref"],
                "blockedReason": row["blocked_reason"],
                "discoveredAt": row["discovered_at"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]

    def complete_task(
        self,
        goal_id: str,
        task_id: str,
        *,
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        goal_id = _assert_goal_id(goal_id)
        task_id = str(task_id or "").strip()
        if not task_id:
            raise GoalLedgerError("goal_ledger_task_id_invalid")
        timestamp = _now()
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE goal_tasks
                SET state = 'done', evidence_ref = ?, blocked_reason = NULL, updated_at = ?
                WHERE goal_id = ? AND task_id = ?
                """,
                (_bounded(evidence_ref, 500), timestamp, goal_id, task_id),
            )
            if result.rowcount == 0:
                raise GoalLedgerError("goal_ledger_task_not_found")
            conn.execute(
                "UPDATE goal_ledger SET updated_at = ? WHERE goal_id = ?",
                (timestamp, goal_id),
            )
        return {
            "schemaVersion": GOAL_LEDGER_SCHEMA,
            "goalId": goal_id,
            "taskId": task_id,
            "state": "done",
        }

    # ── cycles + continue decision ─────────────────────────────────

    def record_cycle(
        self,
        goal_id: str,
        *,
        progress_key: str | None = None,
        cost_usd: float = 0.0,
        outcome: str | None = None,
        next_cycle_at: str | None = None,
    ) -> dict[str, Any]:
        """Account one loop cycle, then return the fresh continue decision.

        Progress uses the ``goal_loop.py`` contract: a non-empty ``progress_key``
        identical to the previous one is "no progress"; ``stall_window``
        consecutive no-progress cycles block the goal and call a human.
        """

        goal_id = _assert_goal_id(goal_id)
        timestamp = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, no_progress_streak, stall_window, last_progress_key,"
                " blocked_reason FROM goal_ledger WHERE goal_id = ?",
                (goal_id,),
            ).fetchone()
            if row is None:
                raise GoalLedgerError("goal_ledger_goal_not_found")
            key = _bounded(progress_key, 500)
            if key is not None and row["last_progress_key"] == key:
                streak = int(row["no_progress_streak"]) + 1
            else:
                streak = 0
            stalled = str(row["status"]) == "active" and streak >= int(row["stall_window"])
            # A stall is a pause, not a grave. A goal meant to run for months will
            # sit still for a stretch and then move again; if the only way out of
            # `blocked` were a human, every such goal would die the first quiet
            # week — and these loops run precisely when nobody is watching. Real
            # progress (a new key, so the work actually changed) clears the block
            # the same way it clears the streak. Blocks a person set, and every
            # terminal status, stay put.
            unstalled = (
                streak == 0
                and key is not None
                and str(row["status"]) == "blocked"
                and str(row["blocked_reason"] or "") == BLOCKED_REASON_STALL
            )
            conn.execute(
                """
                UPDATE goal_ledger
                SET cycle_count = cycle_count + 1,
                    cost_used_usd = cost_used_usd + ?,
                    no_progress_streak = ?,
                    last_progress_key = COALESCE(?, last_progress_key),
                    last_outcome = COALESCE(?, last_outcome),
                    last_cycle_at = ?,
                    next_cycle_at = ?,
                    status = CASE WHEN ? THEN 'blocked' WHEN ? THEN 'active' ELSE status END,
                    blocked_reason = CASE WHEN ? THEN ? WHEN ? THEN NULL ELSE blocked_reason END,
                    updated_at = ?
                WHERE goal_id = ?
                """,
                (
                    max(0.0, float(cost_usd or 0.0)),
                    streak,
                    key,
                    _bounded(outcome, 240),
                    timestamp,
                    _bounded(next_cycle_at, 64),
                    1 if stalled else 0,
                    1 if unstalled else 0,
                    1 if stalled else 0,
                    BLOCKED_REASON_STALL,
                    1 if unstalled else 0,
                    timestamp,
                    goal_id,
                ),
            )
        return self.should_continue(goal_id)

    def should_continue(self, goal_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Host-owned continue decision.

        ``continue`` is true exactly when the goal is active, at least one task
        is open, and every configured budget still has headroom.  This is the
        Codex-shaped "goal != achieved → keep going" predicate; the model marker
        is OR-ed with it by hosts, never replaced by it.
        """

        goal_id = _assert_goal_id(goal_id)
        goal = self.get(goal_id)
        instant = now or datetime.now(timezone.utc)

        def decision(cont: bool, reason: str) -> dict[str, Any]:
            return {
                "schemaVersion": GOAL_LEDGER_DECISION_SCHEMA,
                "goalId": goal_id,
                "continue": cont,
                "reason": reason,
                "status": goal["status"] if goal else None,
                "openTaskCount": goal["openTaskCount"] if goal else 0,
                "cycleCount": goal["cycleCount"] if goal else 0,
                "objective": goal["objective"] if goal else None,
                "blockedReason": goal["blockedReason"] if goal else None,
                "budget": goal["budget"] if goal else None,
            }

        if goal is None:
            return decision(False, REASON_GOAL_NOT_FOUND)
        if goal["status"] in GOAL_TERMINAL_STATUSES:
            return decision(False, REASON_GOAL_TERMINAL)
        if goal["status"] == "blocked":
            return decision(False, REASON_GOAL_BLOCKED)
        deadline = _parse_instant(goal["budget"]["wallclockDeadline"])
        if deadline is not None and instant >= deadline:
            return decision(False, REASON_BUDGET_WALLCLOCK)
        max_cycles = goal["budget"]["maxCycles"]
        if max_cycles is not None and int(goal["cycleCount"]) >= int(max_cycles):
            return decision(False, REASON_BUDGET_CYCLES)
        max_cost = goal["budget"]["maxCostUsd"]
        if max_cost is not None and float(goal["budget"]["costUsedUsd"]) >= float(max_cost):
            return decision(False, REASON_BUDGET_COST)
        if int(goal["openTaskCount"]) <= 0:
            return decision(False, REASON_NO_OPEN_TASKS)
        return decision(True, REASON_OPEN_TASKS_REMAIN)

    def _open_task_count(self, conn: sqlite3.Connection, goal_id: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM goal_tasks"
            " WHERE goal_id = ? AND state IN ('todo','doing','blocked')",
            (goal_id,),
        ).fetchone()
        return int(row["n"] if row else 0)


def goal_ledger_should_continue(goal_id: str) -> dict[str, Any]:
    """Convenience read for hook/CLI callers."""

    return GoalLedgerStore().should_continue(goal_id)


__all__ = [
    "GOAL_LEDGER_SCHEMA",
    "GOAL_LEDGER_DECISION_SCHEMA",
    "GOAL_STATUSES",
    "GOAL_TERMINAL_STATUSES",
    "TASK_STATES",
    "DEFAULT_STALL_WINDOW",
    "BOOTSTRAP_TASK_ID",
    "GoalLedgerError",
    "GoalLedgerStore",
    "goal_ledger_should_continue",
]
