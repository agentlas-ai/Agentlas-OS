"""Router Agent escalation — no LLM in the engine (BYOC).

When the deterministic router lands on `clarify` or `propose_new`, it can attach
an escalation directive telling the HOST runtime (Claude Code / Codex / Gemini)
to resolve the ambiguous request with the Router Agent: an LLM reasoning pass
that rewrites the intent, re-ranks the candidates by intent fit, and decides
route-vs-clarify-vs-build. The engine itself never calls a model — it only names
the agent and hands over a structured context. The host owns the model call,
keeping the BYOC/BYOM contract intact and the router deterministic + offline.

The raw query travels only inside the local decision object (the host already
has it); receipts persist a redacted summary, never the prompt.
"""

from __future__ import annotations

from typing import Any

ROUTER_AGENT_ID = "agentlas-router-agent"
_ESCALATABLE = {"clarify", "propose_new"}


def _compact(items: Any, *, key: str = "id") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in (items or [])[:8]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get(key) or item.get("id") or item.get("slug"),
                "name": item.get("name") or item.get("nameEn"),
                "score": item.get("score"),
            }
        )
    return out


def router_escalation(
    result: dict[str, Any],
    *,
    query: str,
    locale: str,
    policy: dict[str, Any],
    query_tokens: list[str],
) -> dict[str, Any] | None:
    """Build a host-executed Router Agent directive for a low-confidence decision.

    Returns None when escalation is disabled by policy or the decision is already
    confident (anything other than clarify/propose_new), so confident routes and
    pipelines are never touched.
    """
    if not policy.get("router_llm_escalation", True):
        return None
    action = str(result.get("action") or "")
    hub_results = ((result.get("hub") or {}).get("results")) if isinstance(result.get("hub"), dict) else None
    # hub_candidates 는 "후보를 찾았다"는 이유로 렉시컬 top-1 을 그대로 primary 로 밀지만,
    # 렉시컬 점수는 브랜드/주제어에 쉽게 휘둘려 오선택한다("쓰레드 글 써줘"→PRD 메이커). 후보가 2개 이상이면
    # 호스트 LLM 라우터에 넘겨 '의도 적합도'로 재정렬하게 한다(키워드 나열이 아니라 의미 기반 선택).
    hub_multi = (
        action == "hub_candidates"
        and isinstance(hub_results, list)
        and len({str((r or {}).get("slug") or "") for r in hub_results if isinstance(r, dict)}) >= 2
    )
    if action not in _ESCALATABLE and not hub_multi:
        return None
    return {
        "mode": "escalate_to_router_agent",
        "agent": ROUTER_AGENT_ID,
        "reason": action,
        "locale": locale,
        "context": {
            "query": query,
            "query_tokens": query_tokens,
            "deterministic_action": action,
            "deterministic_question": result.get("clarify_question"),
            "candidates": _compact(result.get("candidates")),
            "hub_candidates": _compact(hub_results, key="slug"),
            "suggestions": _compact(result.get("suggestions")),
        },
        "directive": (
            "The deterministic router could not confidently route this request. "
            "Resolve it with the Router Agent: (1) infer the user's actual intent "
            "and rewrite it into a routable form; (2) re-rank candidates / "
            "hub_candidates by intent fit, not keyword overlap; (3) decide ONE of "
            "— route to the best-fit agent, ask ONE sharp clarification, or propose "
            "building a new agent via hep-build. Prefer a confident route when a "
            "candidate clearly fits; only clarify when genuinely ambiguous. Then run "
            "the chosen agent attached to the current project — do not improvise the "
            "task yourself, and do not call agents context-less in the cloud."
        ),
    }
