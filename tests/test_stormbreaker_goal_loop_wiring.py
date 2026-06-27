"""Integration tests for goal-loop wiring into the Stormbreaker packet executor.

These drive `_run_packet_goal_loop` with real shell commands in a temp project,
so they exercise the full path: packet command -> goal verifier -> stability
outcome. Commands are `true`/`echo`/`[` only, so they are instant and portable.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentlas_cloud.networking.stormbreaker_runner import _run_packet_goal_loop  # noqa: E402


class StormbreakerGoalLoopWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = tempfile.mkdtemp(prefix="sb-goal-proj-")
        self.write_scope = tempfile.mkdtemp(prefix="sb-goal-ws-")

    def _run(self, packet, executor_command):
        from pathlib import Path

        ws = Path(self.write_scope)
        return _run_packet_goal_loop(
            packet,
            project=Path(self.project),
            write_scope=ws,
            packet_file=ws / "packet.json",
            stdout_file=ws / "stdout.log",
            stderr_file=ws / "stderr.log",
            executor_command=executor_command,
            execute_card_commands=False,
            timeout_seconds=30,
        )

    def test_loop_reaches_goal(self) -> None:
        # Each iteration bumps a counter; goal verifier passes when counter >= 3.
        executor = "n=$(cat counter 2>/dev/null || echo 0); n=$((n+1)); echo $n > counter"
        goal = 'n=$(cat counter 2>/dev/null || echo 0); echo "n=$n"; [ "$n" -ge 3 ]'
        packet = {"packet_id": "p1", "stage": "build", "loop": {"goal_command": goal, "max_iterations": 10}}
        result = self._run(packet, executor)
        self.assertTrue(result["ok"], result["detail"])
        self.assertEqual(result["goal_loop"]["outcome"], "reached_goal")
        self.assertEqual(result["goal_loop"]["iterations"], 3)
        self.assertIn("passed", result["goal_loop"]["evidence"])

    def test_loop_stalls_when_flatlined(self) -> None:
        # Iteration does nothing; goal never passes and its output never changes.
        executor = "true"
        goal = "echo stuck; false"
        packet = {
            "packet_id": "p2",
            "stage": "build",
            "loop": {"goal_command": goal, "max_iterations": 50, "stall_window": 3},
        }
        result = self._run(packet, executor)
        self.assertFalse(result["ok"])
        self.assertEqual(result["goal_loop"]["outcome"], "stalled")
        # baseline + 3 identical repeats -> stall trips on iteration 4.
        self.assertEqual(result["goal_loop"]["iterations"], 4)

    def test_loop_tolerates_transient_failures(self) -> None:
        # Iterations 1-2 exit nonzero (transient), iteration 3 succeeds AND meets goal.
        executor = 'n=$(cat c 2>/dev/null || echo 0); n=$((n+1)); echo $n > c; [ "$n" -ge 3 ]'
        goal = 'n=$(cat c 2>/dev/null || echo 0); echo "n=$n"; [ "$n" -ge 3 ]'
        packet = {
            "packet_id": "p3",
            "stage": "build",
            "loop": {"goal_command": goal, "max_iterations": 10, "max_consecutive_failures": 3},
        }
        result = self._run(packet, executor)
        self.assertTrue(result["ok"], result["detail"])
        self.assertEqual(result["goal_loop"]["outcome"], "reached_goal")

    def test_goal_loop_summary_is_journaled(self) -> None:
        from pathlib import Path

        executor = "n=$(cat counter 2>/dev/null || echo 0); n=$((n+1)); echo $n > counter"
        goal = '[ "$(cat counter 2>/dev/null || echo 0)" -ge 2 ]'
        packet = {"packet_id": "p4", "stage": "build", "loop": {"goal_command": goal}}
        result = self._run(packet, executor)
        self.assertTrue(result["ok"])
        # A goal-loop journal was written under the write scope.
        journal = Path(self.write_scope) / "goal-loop-journal.jsonl"
        self.assertTrue(journal.is_file())
        self.assertIn("goal-", journal.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
