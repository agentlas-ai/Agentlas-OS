from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agentlas_cloud.cli import main as cli_main
from agentlas_cloud.networking.run_journal import RunJournal, default_journal_path


def run_cli(argv: list[str]) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cli_main(argv)
    return code, json.loads(buffer.getvalue())


class RunJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = RunJournal(Path(self.tmp.name) / "run.jsonl")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_completed_steps_are_skipped_on_resume(self) -> None:
        self.journal.start_step("plan")
        self.journal.complete_step("plan")
        self.journal.start_step("build")
        self.journal.complete_step("build")
        plan = self.journal.resume_plan()
        self.assertEqual(plan["completed"], ["plan", "build"])
        self.assertEqual(plan["dangling"], [])
        self.assertIsNone(plan["resume_from"])
        self.assertFalse(plan["hard_stop"])

    def test_dangling_step_is_the_resume_point(self) -> None:
        self.journal.start_step("plan")
        self.journal.complete_step("plan")
        self.journal.start_step("render")  # interrupted, never completes
        plan = self.journal.resume_plan()
        self.assertEqual(plan["completed"], ["plan"])
        self.assertEqual(plan["dangling"], ["render"])
        self.assertEqual(plan["resume_from"], "render")

    def test_loop_trips_hard_stop(self) -> None:
        for _ in range(3):
            self.journal.start_step("flaky", signature="flaky-sig")
        plan = self.journal.resume_plan(loop_threshold=3)
        self.assertIn("flaky", plan["loops"])
        self.assertTrue(plan["hard_stop"])

    def test_repair_dangling_is_idempotent(self) -> None:
        self.journal.start_step("plan")
        self.journal.complete_step("plan")
        self.journal.start_step("render")
        first = self.journal.repair_dangling(reason="killed")
        self.assertEqual([r["step_id"] for r in first], ["render"])
        # A repaired-but-not-completed step is still retryable, but repairing
        # again does not double-seal it.
        second = self.journal.repair_dangling()
        self.assertEqual(second, [])
        plan = self.journal.resume_plan()
        self.assertEqual(plan["resume_from"], "render")
        self.assertEqual(plan["dangling"], ["render"])

    def test_failed_step_is_resume_point_not_completed(self) -> None:
        self.journal.start_step("upload")
        self.journal.fail_step("upload", error="429 rate limited")
        plan = self.journal.resume_plan()
        self.assertEqual(plan["failed"], ["upload"])
        self.assertEqual(plan["resume_from"], "upload")

    def test_verify_flags_terminal_without_start(self) -> None:
        self.journal.complete_step("ghost")
        report = self.journal.verify()
        self.assertEqual(report["status"], "fail")
        self.assertTrue(report["issues"])

    def test_verify_passes_on_clean_journal(self) -> None:
        self.journal.start_step("a")
        self.journal.complete_step("a")
        self.assertEqual(self.journal.verify()["status"], "pass")

    def test_seq_is_monotonic(self) -> None:
        a = self.journal.start_step("a")
        b = self.journal.complete_step("a")
        self.assertEqual(a["seq"], 1)
        self.assertEqual(b["seq"], 2)

    def test_default_journal_path_is_sanitized(self) -> None:
        path = default_journal_path(self.tmp.name, "../danger/run id")
        self.assertTrue(str(path).endswith("dangerrunid.jsonl"))
        self.assertEqual(
            path.parent,
            (Path(self.tmp.name) / ".agentlas" / "stormbreaker" / "journal").resolve(),
        )


class VerifierFirstAndClarificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = RunJournal(Path(self.tmp.name) / "run.jsonl")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_completed_without_verification_is_unverified(self) -> None:
        self.journal.start_step("step")
        self.journal.complete_step("step")
        plan = self.journal.resume_plan()
        self.assertEqual(plan["unverified"], ["step"])
        gate = self.journal.final_gate()
        self.assertFalse(gate["ok"])
        self.assertIn("unverified", gate["blockers"])

    def test_passing_verification_clears_the_gate(self) -> None:
        self.journal.plan_step("step", verifier="output file exists and parses")
        self.journal.start_step("step")
        self.journal.complete_step("step")
        self.journal.verify_step("step", passed=True, evidence="parsed ok")
        plan = self.journal.resume_plan()
        self.assertEqual(plan["unverified"], [])
        self.assertTrue(self.journal.final_gate()["ok"])

    def test_failed_verification_blocks(self) -> None:
        self.journal.start_step("step")
        self.journal.complete_step("step")
        self.journal.verify_step("step", passed=False, evidence="schema mismatch")
        gate = self.journal.final_gate()
        self.assertFalse(gate["ok"])
        self.assertIn("verify_failed", gate["blockers"])

    def test_allow_unverified_relaxes_gate(self) -> None:
        self.journal.start_step("step")
        self.journal.complete_step("step")
        gate = self.journal.final_gate(require_verification=False)
        self.assertTrue(gate["ok"])

    def test_open_question_blocks_run(self) -> None:
        self.journal.start_step("step")
        self.journal.request_clarification("step", "which account?")
        plan = self.journal.resume_plan()
        self.assertEqual(plan["awaiting_clarification"], ["step"])
        self.assertTrue(plan["blocked"])
        self.assertIn("awaiting_clarification", self.journal.final_gate()["blockers"])

    def test_resolved_question_unblocks(self) -> None:
        self.journal.start_step("step")
        self.journal.request_clarification("step", "which account?")
        self.journal.resolve_clarification("step", "the main account")
        self.journal.complete_step("step")
        self.journal.verify_step("step", passed=True)
        plan = self.journal.resume_plan()
        self.assertEqual(plan["awaiting_clarification"], [])
        self.assertFalse(plan["blocked"])
        self.assertTrue(self.journal.final_gate()["ok"])


class RunJournalCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = self.tmp.name
        journal = RunJournal(default_journal_path(self.project, "demo"))
        journal.start_step("plan")
        journal.complete_step("plan")
        journal.start_step("render")  # interrupted

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cli_status_reports_resume_point(self) -> None:
        code, payload = run_cli(["stormbreaker", "journal", "status", "--run-id", "demo", "--project", self.project])
        self.assertEqual(code, 0)
        self.assertEqual(payload["resume_from"], "render")
        self.assertEqual(payload["completed"], ["plan"])

    def test_cli_repair_then_verify(self) -> None:
        code, payload = run_cli(["stormbreaker", "journal", "repair", "--run-id", "demo", "--project", self.project])
        self.assertEqual(code, 0)
        self.assertEqual([r["step_id"] for r in payload["repaired"]], ["render"])
        code, verify = run_cli(["stormbreaker", "journal", "verify", "--run-id", "demo", "--project", self.project])
        self.assertEqual(code, 0)
        self.assertEqual(verify["status"], "pass")

    def test_cli_gate_blocks_unfinished_run(self) -> None:
        # demo run has a dangling 'render' step, so the final gate must not pass.
        code, payload = run_cli(["stormbreaker", "journal", "gate", "--run-id", "demo", "--project", self.project])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("dangling", payload["blockers"])


if __name__ == "__main__":
    unittest.main()
