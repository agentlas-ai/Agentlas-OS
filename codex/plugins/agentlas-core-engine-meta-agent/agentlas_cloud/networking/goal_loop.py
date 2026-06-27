"""Stormbreaker Goal Loop — sustain a task toward a goal without stalling or running away.

The Run Journal (`run_journal.py`) hardens Stormbreaker against *failure* loops:
a step that keeps restarting trips a hard stop so the run stops burning cycles.
That is the right guard for "the same step keeps dying." It is the WRONG guard
for a goal-seeking task — "keep refining the persona reply until it passes" — where
repetition is the point, not a defect.

This module adds the missing half: a controller that auto-constructs a loop for a
task and drives it **until the goal verifies**, while staying stable —

- **don't break (안 끊기게):** a transient iteration failure does not kill the loop.
  It is journaled and retried with backoff, up to `max_consecutive_failures` in a
  row. Only a genuine streak of hard failures stops the run.
- **don't run away:** a hard `max_iterations` ceiling, plus stall detection —
  if `stall_window` consecutive iterations make no new progress, the loop stops as
  `stalled` instead of spinning forever. Progress is measured, not assumed.
- **keep the goal until done (될때까지 목표 유지):** the loop only reports
  `reached_goal` when the goal predicate verifies; it never claims success on a
  bare "it ran."
- **survive a hard stop:** every iteration is a Run Journal step, so a killed loop
  resumes its iteration numbering from the journal instead of colliding or
  restarting from zero.

Pure standard library, deterministic (the only nondeterminism — sleep between
retries — is injected), local-first. No model calls; the caller supplies the
`iterate` and `goal` callables (e.g. a persona agent and its verifier).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .run_journal import RunJournal

# Outcomes
REACHED_GOAL = "reached_goal"
STALLED = "stalled"
EXHAUSTED = "exhausted"
FAILED = "failed"


@dataclass
class GoalLoopConfig:
    """Stability budget for one goal loop."""

    max_iterations: int = 25
    # Stop as `stalled` after this many *consecutive* no-progress iterations.
    stall_window: int = 3
    # Tolerate transient iteration failures; stop as `failed` only after this many
    # in a row (a single success resets the streak).
    max_consecutive_failures: int = 3
    # Backoff seconds = backoff_base * failure_streak (0 disables waiting; tests
    # inject a fake sleep so they never actually wait).
    backoff_base: float = 0.0
    backoff_cap: float = 30.0

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.stall_window < 1:
            raise ValueError("stall_window must be >= 1")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")


@dataclass
class GoalLoopResult:
    outcome: str
    iterations: int
    reached_goal: bool
    evidence: str | None
    progress_trail: list[str] = field(default_factory=list)
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "outcome": self.outcome,
            "reached_goal": self.reached_goal,
            "iterations": self.iterations,
            "evidence": self.evidence,
            "progress_trail": self.progress_trail,
            "detail": self.detail,
        }


def run_goal_loop(
    *,
    iterate: Callable[[Any, int], tuple[Any, str]],
    goal: Callable[[Any], tuple[bool, str | None]],
    journal: RunJournal,
    config: GoalLoopConfig | None = None,
    initial_state: Any = None,
    step_prefix: str = "goal",
    sleep: Callable[[float], None] = time.sleep,
) -> GoalLoopResult:
    """Drive ``iterate`` toward ``goal`` under the stability budget in ``config``.

    Contracts:
    - ``iterate(state, iteration) -> (new_state, progress_key)`` does one unit of
      work and returns the updated state plus a string that fingerprints *progress*
      (a score, a hash, a status). Identical consecutive keys mean "no progress."
      It may raise to signal a transient failure.
    - ``goal(state) -> (done: bool, evidence)`` decides whether the goal is met.
      A truthy ``done`` is the ONLY way the loop reports success.

    The loop numbers its journal steps after any iterations already recorded, so a
    resumed run continues instead of colliding.
    """

    cfg = config or GoalLoopConfig()
    state = initial_state
    trail: list[str] = []
    consecutive_failures = 0
    stall_streak = 0
    last_progress: str | None = None

    start_index = _resume_offset(journal, step_prefix)

    iteration = 0
    while iteration < cfg.max_iterations:
        iteration += 1
        step_id = f"{step_prefix}-{start_index + iteration}"
        journal.start_step(step_id, signature=step_prefix)
        try:
            state, progress_key = iterate(state, iteration)
            progress_key = str(progress_key)
        except Exception as exc:  # transient failure — don't break the loop
            consecutive_failures += 1
            journal.fail_step(step_id, error=f"{type(exc).__name__}: {exc}")
            if consecutive_failures >= cfg.max_consecutive_failures:
                return GoalLoopResult(
                    outcome=FAILED,
                    iterations=iteration,
                    reached_goal=False,
                    evidence=None,
                    progress_trail=trail,
                    detail=f"{consecutive_failures} consecutive failures; last: {type(exc).__name__}: {exc}",
                )
            sleep(min(cfg.backoff_base * consecutive_failures, cfg.backoff_cap))
            continue

        consecutive_failures = 0
        journal.complete_step(step_id, result_ref=progress_key)

        # Progress accounting: a repeat of the previous key is "no progress."
        if last_progress is not None and progress_key == last_progress:
            stall_streak += 1
        else:
            stall_streak = 0
        last_progress = progress_key
        trail.append(progress_key)

        done, evidence = goal(state)
        if done:
            # Verifier-first: the goal predicate IS the proof, so record it.
            journal.verify_step(step_id, True, evidence=evidence)
            return GoalLoopResult(
                outcome=REACHED_GOAL,
                iterations=iteration,
                reached_goal=True,
                evidence=evidence,
                progress_trail=trail,
            )

        if stall_streak >= cfg.stall_window:
            return GoalLoopResult(
                outcome=STALLED,
                iterations=iteration,
                reached_goal=False,
                evidence=None,
                progress_trail=trail,
                detail=f"no new progress for {cfg.stall_window} consecutive iterations (key={progress_key!r})",
            )

    return GoalLoopResult(
        outcome=EXHAUSTED,
        iterations=cfg.max_iterations,
        reached_goal=False,
        evidence=None,
        progress_trail=trail,
        detail=f"max_iterations ({cfg.max_iterations}) reached without verifying the goal",
    )


def _resume_offset(journal: RunJournal, step_prefix: str) -> int:
    """Highest iteration index already recorded for this loop, so a resumed run
    keeps counting up instead of re-using step ids."""

    highest = 0
    prefix = f"{step_prefix}-"
    for event in journal.events():
        step_id = str(event.get("step_id") or "")
        if not step_id.startswith(prefix):
            continue
        tail = step_id[len(prefix) :]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return highest
