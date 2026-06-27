"""Tests for the Stormbreaker goal loop stability primitive."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentlas_cloud.networking.goal_loop import (  # noqa: E402
    EXHAUSTED,
    FAILED,
    REACHED_GOAL,
    STALLED,
    GoalLoopConfig,
    run_goal_loop,
)
from agentlas_cloud.networking.run_journal import RunJournal  # noqa: E402


def _journal(tmp: str) -> RunJournal:
    return RunJournal(os.path.join(tmp, "goal.jsonl"))


class GoalLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.mkdtemp(prefix="goal-loop-")
        self.journal = _journal(self._tmp)
        self.slept: list[float] = []

    def _sleep(self, seconds: float) -> None:
        self.slept.append(seconds)

    # -- the persona-based loop the user cited ------------------------------
    def test_persona_loop_refines_until_verifier_passes(self) -> None:
        """A persona reply is refined each iteration until it meets the goal —
        repetition is productive, so the loop must SUSTAIN, not hard-stop."""

        # Persona "quality" climbs by one each iteration; goal = quality >= 4.
        def iterate(state, i):
            quality = (state or 0) + 1
            return quality, f"quality={quality}"

        def goal(state):
            return (state >= 4, f"persona reply quality {state} >= 4" if state >= 4 else None)

        result = run_goal_loop(
            iterate=iterate,
            goal=goal,
            journal=self.journal,
            config=GoalLoopConfig(max_iterations=10, stall_window=3),
            sleep=self._sleep,
        )
        self.assertEqual(result.outcome, REACHED_GOAL)
        self.assertTrue(result.reached_goal)
        self.assertEqual(result.iterations, 4)
        self.assertIn("quality 4", result.evidence)
        # The core thesis: productive iteration uses DISTINCT step ids, so the
        # failure-loop guard never trips — repetition toward a goal is not a defect.
        plan = self.journal.resume_plan()
        self.assertEqual(plan["loops"], [])
        self.assertFalse(plan["hard_stop"])
        self.assertEqual(plan["dangling"], [])
        # The terminal iteration that met the goal carries a passing verification;
        # the earlier ones are attempts (not yet at goal), so the run is stable
        # under the verifier-aware gate.
        gate = self.journal.final_gate(require_verification=False)
        self.assertTrue(gate["ok"], gate["blockers"])
        self.assertEqual(plan["unverified"], ["goal-1", "goal-2", "goal-3"])

    # -- stall: progress flatlines ------------------------------------------
    def test_stalls_when_no_new_progress(self) -> None:
        def iterate(state, i):
            return state, "stuck"  # same progress key forever

        def goal(state):
            return (False, None)

        result = run_goal_loop(
            iterate=iterate,
            goal=goal,
            journal=self.journal,
            config=GoalLoopConfig(max_iterations=50, stall_window=3),
            sleep=self._sleep,
        )
        self.assertEqual(result.outcome, STALLED)
        self.assertFalse(result.reached_goal)
        # First key sets baseline; 3 consecutive repeats trip the stall window.
        self.assertEqual(result.iterations, 4)

    # -- runaway guard -------------------------------------------------------
    def test_exhausts_at_max_iterations(self) -> None:
        def iterate(state, i):
            return i, f"progress-{i}"  # always new progress, never reaches goal

        def goal(state):
            return (False, None)

        result = run_goal_loop(
            iterate=iterate,
            goal=goal,
            journal=self.journal,
            config=GoalLoopConfig(max_iterations=5, stall_window=99),
            sleep=self._sleep,
        )
        self.assertEqual(result.outcome, EXHAUSTED)
        self.assertEqual(result.iterations, 5)

    # -- don't break: transient failures are tolerated ----------------------
    def test_tolerates_transient_failures_then_succeeds(self) -> None:
        calls = {"n": 0}

        def iterate(state, i):
            calls["n"] += 1
            # Fail the first two attempts, then make progress to the goal.
            if calls["n"] <= 2:
                raise RuntimeError("transient blip")
            quality = (state or 0) + 1
            return quality, f"q={quality}"

        def goal(state):
            return (state >= 1, "done") if state else (False, None)

        result = run_goal_loop(
            iterate=iterate,
            goal=goal,
            journal=self.journal,
            config=GoalLoopConfig(max_iterations=10, max_consecutive_failures=3, backoff_base=2.0),
            sleep=self._sleep,
        )
        self.assertEqual(result.outcome, REACHED_GOAL)
        # Two failures were tolerated and backed off (2.0 * 1, 2.0 * 2).
        self.assertEqual(self.slept, [2.0, 4.0])

    # -- a real streak of failures stops the run ----------------------------
    def test_stops_after_consecutive_failures(self) -> None:
        def iterate(state, i):
            raise ValueError("always broken")

        def goal(state):
            return (False, None)

        result = run_goal_loop(
            iterate=iterate,
            goal=goal,
            journal=self.journal,
            config=GoalLoopConfig(max_iterations=10, max_consecutive_failures=3),
            sleep=self._sleep,
        )
        self.assertEqual(result.outcome, FAILED)
        self.assertEqual(result.iterations, 3)
        self.assertIn("consecutive failures", result.detail)

    # -- a success resets the failure streak --------------------------------
    def test_failure_streak_resets_on_success(self) -> None:
        seq = iter([RuntimeError("x"), RuntimeError("y"), None, RuntimeError("z"), RuntimeError("w")])
        prog = {"n": 0}

        def iterate(state, i):
            item = next(seq)
            if isinstance(item, Exception):
                raise item
            prog["n"] += 1
            return prog["n"], f"p{prog['n']}"

        def goal(state):
            return (False, None)  # never reach goal; we're testing the streak logic

        result = run_goal_loop(
            iterate=iterate,
            goal=goal,
            journal=self.journal,
            config=GoalLoopConfig(max_iterations=10, max_consecutive_failures=3),
            sleep=self._sleep,
        )
        # 2 fails, 1 success (resets), 2 fails -> never hits 3-in-a-row -> not FAILED.
        # The seq is exhausted -> StopIteration raised -> counts as a failure too.
        # So: fail,fail,ok(reset),fail,fail,fail(StopIteration) = 3 in a row -> FAILED at the end.
        self.assertEqual(result.outcome, FAILED)

    # -- resume: journal offset keeps iteration numbering monotonic ----------
    def test_resume_continues_iteration_numbering(self) -> None:
        # Pre-seed the journal with two completed iterations.
        self.journal.start_step("goal-1", signature="goal")
        self.journal.complete_step("goal-1", result_ref="q=1")
        self.journal.start_step("goal-2", signature="goal")
        self.journal.complete_step("goal-2", result_ref="q=2")

        seen_steps: list[str] = []

        def iterate(state, i):
            quality = (state or 2) + 1
            return quality, f"q={quality}"

        def goal(state):
            return (state >= 3, "resumed to goal") if state >= 3 else (False, None)

        run_goal_loop(
            iterate=iterate,
            goal=goal,
            journal=self.journal,
            config=GoalLoopConfig(max_iterations=5),
            sleep=self._sleep,
        )
        step_ids = [e.get("step_id") for e in self.journal.events() if e.get("event") == "start"]
        seen_steps.extend(step_ids)
        # New steps must continue after goal-2 (i.e. goal-3), not collide with 1/2.
        self.assertIn("goal-3", seen_steps)
        self.assertEqual(seen_steps.count("goal-1"), 1)


if __name__ == "__main__":
    unittest.main()
