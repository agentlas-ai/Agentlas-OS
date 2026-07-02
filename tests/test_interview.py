"""Tests for the briefing interview engine (Work Brief / scorer / lenses)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentlas_cloud.interview import (  # noqa: E402
    AMBIGUITY_THRESHOLD,
    WORK_BRIEF_RELPATH,
    WORK_BRIEF_SCHEMA_VERSION,
    brief_packet_context,
    brief_scope_text,
    completion_check,
    compose_ambiguity,
    interview_directive,
    load_work_brief,
    milestone_of,
    question_budget,
    render_lens_table,
    work_brief_problem,
)


def _valid_brief() -> dict:
    return {
        "schemaVersion": WORK_BRIEF_SCHEMA_VERSION,
        "goal": "링크드인용 제품 홍보 게시물 3종을 한국어로 작성한다",
        "constraints": ["브랜드 어투 유지", "각 300자 이내"],
        "acceptance_criteria": ["게시물 3개", "CTA 포함"],
        "anti_scope": ["광고 집행/캠페인 운영은 하지 않는다"],
        "assumptions": [
            {"text": "타깃은 B2B 구매자", "status": "assumed", "source": "default"}
        ],
        "deferred": [{"topic": "게시 일정", "reason": "user-deferred"}],
        "evaluation_principles": [
            {"name": "brand_fit", "weight": 0.5},
            {"name": "clarity", "weight": 0.5},
        ],
        "exit_conditions": [{"name": "approved", "criteria": "사용자 확정"}],
        "metadata": {"ambiguity_score": 0.14, "surface": "chat"},
    }


class WorkBriefSchemaTests(unittest.TestCase):
    def test_valid_brief_passes(self) -> None:
        self.assertIsNone(work_brief_problem(_valid_brief()))

    def test_goal_must_be_single_line(self) -> None:
        brief = _valid_brief()
        brief["goal"] = "두 줄\n목표"
        self.assertIn("single line", work_brief_problem(brief) or "")

    def test_weights_must_sum_to_one(self) -> None:
        brief = _valid_brief()
        brief["evaluation_principles"] = [{"name": "a", "weight": 0.9}]
        self.assertIn("sum to 1.0", work_brief_problem(brief) or "")

    def test_assumption_source_validated(self) -> None:
        brief = _valid_brief()
        brief["assumptions"] = [{"text": "x", "status": "assumed", "source": "vibes"}]
        self.assertIn("source", work_brief_problem(brief) or "")

    def test_load_from_project_dir_and_invalid_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / WORK_BRIEF_RELPATH
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(_valid_brief()), encoding="utf-8")
            loaded = load_work_brief(tmp)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["goal"], _valid_brief()["goal"])
            target.write_text("{not json", encoding="utf-8")
            self.assertIsNone(load_work_brief(tmp))
        self.assertIsNone(load_work_brief("/nonexistent/dir"))

    def test_scope_text_and_packet_context(self) -> None:
        brief = _valid_brief()
        text = brief_scope_text(brief)
        self.assertIn("링크드인", text)
        self.assertIn("CTA 포함", text)
        packet = brief_packet_context(brief)
        self.assertEqual(packet["goal"], brief["goal"])
        self.assertEqual(packet["anti_scope"], brief["anti_scope"])
        self.assertEqual(packet["ambiguity_score"], 0.14)


class ScorerTests(unittest.TestCase):
    def test_compose_weighted_ambiguity(self) -> None:
        out = compose_ambiguity({"goal": 1.0, "constraints": 1.0, "success": 1.0}, "chat")
        self.assertEqual(out["ambiguity"], 0.0)
        self.assertEqual(out["floor_failures"], [])
        out = compose_ambiguity({"goal": 0.5, "constraints": 0.5, "success": 0.5}, "chat")
        self.assertAlmostEqual(out["ambiguity"], 0.5, places=4)

    def test_floor_failure_despite_good_average(self) -> None:
        # goal 완벽·success 완벽이어도 constraints가 floor(0.65) 미달이면 실패로 표시
        out = compose_ambiguity({"goal": 1.0, "constraints": 0.5, "success": 1.0}, "chat")
        self.assertLess(out["ambiguity"], AMBIGUITY_THRESHOLD)
        self.assertEqual(out["floor_failures"], ["constraints"])

    def test_build_surface_has_context_dimension(self) -> None:
        out = compose_ambiguity(
            {"goal": 0.9, "constraints": 0.9, "success": 0.9, "context": 0.2}, "hep-build"
        )
        self.assertIn("context", out["floor_failures"])

    def test_milestones(self) -> None:
        self.assertEqual(milestone_of(0.55), "INITIAL")
        self.assertEqual(milestone_of(0.35), "PROGRESS")
        self.assertEqual(milestone_of(0.25), "REFINED")
        self.assertEqual(milestone_of(0.15), "READY")

    def test_completion_requires_streak(self) -> None:
        good = {"ambiguity": 0.1, "floor_failures": []}
        bad = {"ambiguity": 0.4, "floor_failures": []}
        # 첫 통과 라운드에서는 종료 불가 (streak 2 필요)
        res = completion_check([bad, good], "stormbreaker", streak_required=2)
        self.assertFalse(res["ready"])
        self.assertEqual(res["reason"], "stability_streak_not_met")
        res = completion_check([bad, good, good], "stormbreaker", streak_required=2)
        self.assertTrue(res["ready"])

    def test_completion_floor_blocks(self) -> None:
        entry = {"ambiguity": 0.1, "floor_failures": ["goal"]}
        res = completion_check([entry, entry], "chat", streak_required=1)
        self.assertFalse(res["ready"])
        self.assertEqual(res["reason"], "dimension_floor_failed")

    def test_min_rounds(self) -> None:
        good = {"ambiguity": 0.05, "floor_failures": []}
        res = completion_check([good], "hep-build", streak_required=1, min_rounds=2)
        self.assertFalse(res["ready"])
        self.assertEqual(res["reason"], "below_min_rounds")


class LensAndDirectiveTests(unittest.TestCase):
    def test_budgets_enforced_shape(self) -> None:
        chat = question_budget("chat")
        self.assertEqual(chat["batch_max"], 5)
        self.assertEqual(chat["total_max"], 5)
        build = question_budget("hep-build")
        self.assertGreaterEqual(build["total_max"], 12)

    def test_lens_table_renders_required_markers(self) -> None:
        table = render_lens_table("hep-build", "ko")
        self.assertIn("anti_scope (필수)", table)
        self.assertIn("[challenge]", table)
        chat_table = render_lens_table("chat", "ko")
        self.assertNotIn("[challenge]", chat_table)

    def test_directive_shape(self) -> None:
        d = interview_directive("stormbreaker", "쇼핑몰 전체 구축해줘", locale="ko")
        self.assertEqual(d["mode"], "briefing_interview")
        self.assertIn("BUDGET", d["directive"])
        self.assertIn("anti_scope", d["directive"])
        self.assertIn("clarity", d["scoring_prompt"])
        self.assertEqual(d["budget"]["total_max"], 8)


if __name__ == "__main__":
    unittest.main()


class PipelineBriefTests(unittest.TestCase):
    def test_detect_stages_scoped_by_brief(self) -> None:
        from agentlas_cloud.networking.pipeline import detect_stages

        # 원문에는 plan 앵커가 없어 기존 가드로는 분해 불가
        query = "쇼핑몰 만들어서 테스트까지 해줘"
        self.assertEqual(detect_stages(query), [])
        # 브리프 텍스트가 스테이지 의도를 보강하고 scoped=True로 가드 완화
        brief_text = "요구사항 스펙 정리 후 구현하고 QA 검증까지"
        stages = detect_stages(query, extra_text=brief_text, scoped=True)
        self.assertGreaterEqual(len(stages), 2)

    def test_plan_pipeline_attaches_work_brief(self) -> None:
        from agentlas_cloud.networking.pipeline import plan_pipeline

        cards = [
            {"id": "local/planner", "name": "Planner", "produces": [{"kind": "prd"}], "consumes": [], "entrypoints": {}},
            {"id": "local/builder", "name": "Builder", "produces": [{"kind": "codebase_change"}], "consumes": [{"kind": "prd"}], "entrypoints": {}},
            {"id": "local/qa", "name": "QA", "produces": [{"kind": "qa_report"}], "consumes": [{"kind": "codebase_change"}], "entrypoints": {}},
        ]
        brief = _valid_brief()
        brief["acceptance_criteria"] = ["기획 스펙 문서", "구현 완료", "테스트 통과"]
        plan = plan_pipeline(
            "기획부터 구현, 테스트까지",
            cards,
            lambda card: 1.0,
            brief=brief,
        )
        self.assertIsNotNone(plan)
        self.assertIn("work_brief", plan)
        self.assertEqual(plan["work_brief"]["goal"], brief["goal"])
        # 브리프 없으면 키 자체가 없음 (하위호환)
        plan_none = plan_pipeline("기획부터 구현, 테스트까지", cards, lambda card: 1.0)
        self.assertIsNotNone(plan_none)
        self.assertNotIn("work_brief", plan_none)
