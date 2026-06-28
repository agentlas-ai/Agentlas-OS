"""Router Agent cascade (upgrade C): low-confidence decisions escalate to a
host-run LLM reasoning pass; confident routes are untouched; receipts stay
redacted."""

from __future__ import annotations

import json
from pathlib import Path

from agentlas_cloud.networking.router import route_request
from agentlas_cloud.networking.router_agent_call import ROUTER_AGENT_ID, router_escalation


def test_escalation_on_clarify():
    decision = {
        "action": "clarify",
        "clarify_question": "무엇을 하시려나요?",
        "candidates": [{"id": "a", "name": "A", "score": 3.0}],
        "hub": {"results": [{"slug": "h1", "name": "H1", "score": 2.0}]},
    }
    esc = router_escalation(
        decision, query="모호한 요청", locale="ko",
        policy={"router_llm_escalation": True}, query_tokens=["모호"],
    )
    assert esc is not None
    assert esc["mode"] == "escalate_to_router_agent"
    assert esc["agent"] == ROUTER_AGENT_ID
    assert esc["reason"] == "clarify"
    assert esc["context"]["candidates"][0]["id"] == "a"
    assert esc["context"]["hub_candidates"][0]["id"] == "h1"
    assert esc["context"]["query"] == "모호한 요청"


def test_escalation_on_propose_new():
    esc = router_escalation(
        {"action": "propose_new", "suggestions": []},
        query="q", locale="en", policy={}, query_tokens=[],
    )
    assert esc is not None and esc["reason"] == "propose_new"


def test_no_escalation_on_confident_route():
    assert router_escalation(
        {"action": "route", "selected": {"id": "x"}},
        query="q", locale="en", policy={}, query_tokens=[],
    ) is None


def test_no_escalation_when_disabled():
    assert router_escalation(
        {"action": "clarify", "candidates": []},
        query="q", locale="ko", policy={"router_llm_escalation": False}, query_tokens=[],
    ) is None


def test_route_request_attaches_router_agent_and_redacts_receipt(tmp_path: Path):
    # Empty home → no cards, hub disabled → propose_new. Escalation must attach,
    # and the persisted receipt must carry only a redacted summary (no context).
    decision = route_request(
        "zxqw unmatchable nonsense token",
        home=tmp_path, project_dir=tmp_path, use_hub=False,
    )
    assert decision["action"] in ("propose_new", "clarify")
    assert (decision.get("router_agent") or {}).get("agent") == ROUTER_AGENT_ID

    ledger = tmp_path / "ledgers" / "routing-decisions.jsonl"
    assert ledger.exists()
    record = json.loads(ledger.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["router_agent"]["mode"] == "escalate_to_router_agent"
    # The receipt stores only the compact summary, never the directive context.
    assert "context" not in record["router_agent"]
    assert "directive" not in record["router_agent"]
