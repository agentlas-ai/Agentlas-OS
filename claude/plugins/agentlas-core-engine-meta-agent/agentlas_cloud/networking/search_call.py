"""Power-user search and explicit call helpers for Hephaestus Network.

`/hep-network` stays the simple borrow surface: the router decides
whether a task is single-agent, clarify, or a temporary task force. These
helpers expose two deliberate advanced moves:

- search: show owner-cloud, saved bookmarks, and public-Hub candidates side by side;
- call: prepare exactly the agent slugs the user named.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .bootstrap import networking_home
from .hub_fallback import search_hub
from .hub_invocation import invoke_hub_agent
from .receipts import write_receipt
from .tokenize import has_hangul, word_tokens


DEFAULT_SEARCH_LIMIT = 10


def search_agents(
    query: str,
    *,
    home: Path | str | None = None,
    project_dir: Path | str = ".",
    runtime: str | None = "terminal",
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> dict[str, Any]:
    """Return owner-cloud, bookmarked, and public-Hub search sections without invoking."""

    base = Path(home) if home else networking_home()
    tokens = word_tokens(query)
    limit = _normalize_limit(limit)
    cloud_raw = _search_scope(tokens, query, home=base, scope="cloud")
    bookmark_raw = _search_scope(tokens, query, home=base, scope="bookmark")
    hub_raw = _search_scope(tokens, query, home=base, scope="network")
    sections = {
        "cloud": _section("cloud", cloud_raw, query, limit),
        "bookmarks": _section("bookmarks", bookmark_raw, query, limit),
        "hub": _section("hub", hub_raw, query, limit),
    }
    candidates = [
        {"id": f"{section}/{item.get('slug')}", "score": item.get("score")}
        for section, payload in sections.items()
        for item in payload.get("results", [])
        if isinstance(item, dict) and item.get("slug")
    ]
    receipt_id = write_receipt(
        action="agent_search",
        query_tokens=tokens,
        candidates=candidates,
        selected=None,
        reasons=["cloud_bookmark_hub_sections", "candidate_only"],
        locale="ko" if has_hangul(query) else "en",
        runtime=runtime,
        router_chain=["hep-search"],
        match_reason="explicit_candidate_search",
        allowed_by=["redacted_hub_search", "owner_cloud_search", "saved_bookmark_search"],
        fallback_scope=None,
        home=base,
    )
    return {
        "schema": "hephaestus.search.v1",
        "action": "agent_search",
        "query": query,
        "project_dir": str(project_dir),
        "limit_per_section": limit,
        "sections": sections,
        "receipt_id": receipt_id,
        "notes": [
            "No agent was invoked.",
            "cloud = signed-in owner's own saved/shared packages.",
            "bookmarks = Hub agents the signed-in workspace saved.",
            "hub = public Agentlas Hub marketplace.",
        ],
    }


def call_agents(
    agents: list[str] | str,
    context: str,
    *,
    home: Path | str | None = None,
    project_dir: Path | str = ".",
    runtime: str | None = "terminal",
    version: str = "latest",
    local_inventory: list[str] | None = None,
) -> dict[str, Any]:
    """Prepare exactly the named Hub/cloud agent bundles.

    The caller runtime still owns model execution. This function fetches BYOM
    runtime bundles and writes execution receipts through `invoke_hub_agent`.
    """

    base = Path(home) if home else networking_home()
    refs = parse_agent_refs(agents)
    if not refs:
        return {
            "schema": "hephaestus.call.v1",
            "action": "agent_call",
            "status": "error",
            "error": "no agent refs provided",
            "agents": [],
            "context": context,
        }
    results: list[dict[str, Any]] = []
    for ref in refs:
        parsed = _parse_ref(ref)
        decision = {
            "action": "hub_candidates",
            "receipt_id": None,
            "hub": {
                "scope": parsed["scope"],
                "results": [
                    {
                        "slug": parsed["slug"],
                        "kind": "cloud-callable",
                        "entityKind": parsed.get("entity_kind"),
                        "callable": True,
                        "name": parsed["slug"],
                    }
                ],
            },
        }
        result = invoke_hub_agent(
            context,
            slug=parsed["slug"],
            hub_decision=decision,
            project_dir=project_dir,
            home=base,
            version=version,
            local_inventory=local_inventory or [],
            expected_entity_kind=parsed.get("entity_kind"),
        )
        result["requested_ref"] = ref
        result["requested_scope"] = parsed["scope"]
        if parsed.get("entity_kind"):
            result["requested_entity_kind"] = parsed["entity_kind"]
        results.append(result)

    statuses = {str(item.get("status") or "unknown") for item in results}
    tokens = word_tokens(context)
    receipt_id = write_receipt(
        action="agent_call",
        query_tokens=tokens + [item["slug"] for item in (_parse_ref(ref) for ref in refs)],
        candidates=[{"id": item.get("slug"), "score": None} for item in results],
        selected=",".join(str(item.get("slug") or item.get("requested_ref") or "") for item in results),
        reasons=["explicit_agent_call"],
        locale="ko" if has_hangul(context) else "en",
        runtime=runtime,
        router_chain=["hep-call"],
        match_reason="explicit_agent_refs",
        allowed_by=["user_named_agents", "hub_runtime_bundle"],
        fallback_scope=None,
        home=base,
    )
    return {
        "schema": "hephaestus.call.v1",
        "action": "agent_call",
        "status": "prepared" if statuses == {"prepared"} else "partial" if "prepared" in statuses else "failed",
        "context": context,
        "project_dir": str(project_dir),
        "receipt_id": receipt_id,
        "agents": results,
        "next_step": (
            "Caller runtime executes each returned bundle with its own model. "
            "Agentlas Hub returns runtime instructions; it does not run the LLM."
        ),
    }


def parse_agent_refs(value: list[str] | str) -> list[str]:
    if isinstance(value, list):
        raw = ",".join(str(item) for item in value)
    else:
        raw = str(value or "")
    refs = [item.strip() for item in re.split(r"[,\n]+", raw) if item.strip()]
    return list(dict.fromkeys(refs))


def _search_scope(tokens: list[str], query: str, *, home: Path, scope: str) -> dict[str, Any]:
    raw = search_hub(tokens, home=home, approved=True, scope=scope)
    if _has_results(raw):
        return raw
    expanded = _expanded_tokens(query, tokens)
    if expanded == list(dict.fromkeys(tokens)):
        return raw
    retry = search_hub(expanded, home=home, approved=True, scope=scope)
    if _has_results(retry) or retry.get("status") == "ok":
        retry["expandedFrom"] = raw.get("query") or " ".join(tokens)
        retry["fallbackReason"] = raw.get("status") or raw.get("reason") or "empty_results"
        return retry
    return raw


def _has_results(raw: dict[str, Any]) -> bool:
    return isinstance(raw.get("results"), list) and bool(raw.get("results"))


def _expanded_tokens(query: str, tokens: list[str]) -> list[str]:
    expanded = list(dict.fromkeys(tokens))
    haystack = " ".join([query, *tokens]).lower()
    additions: list[str] = []
    if any(term in haystack for term in ("시장", "market", "산업", "industry")):
        additions.extend(["market", "industry", "trend"])
    if any(term in haystack for term in ("리포트", "보고서", "report", "dossier")):
        additions.extend(["report", "brief", "dossier", "writer"])
    if any(term in haystack for term in ("리서치", "조사", "research", "자료", "정보")):
        additions.extend(["research", "intelligence", "analyst"])
    if any(term in haystack for term in ("분석", "analysis", "analytics")):
        additions.extend(["analysis", "analytics", "analyst"])
    if any(term in haystack for term in ("쓸만한", "찾아", "추천", "recommend", "suitable", "best")):
        additions.extend(["recommend", "suitable", "agent"])
    if any(term in haystack for term in ("투자", "주식", "금융", "finance", "investment", "stock", "equity")):
        additions.extend(["finance", "investment", "equity"])
    if any(term in haystack for term in ("마케팅", "marketing", "growth", "campaign")):
        additions.extend(["marketing", "growth"])
    if any(term in haystack for term in ("코드", "개발", "버그", "code", "dev", "bug")):
        additions.extend(["code", "developer", "engineering"])
    for token in additions:
        if token not in expanded:
            expanded.append(token)
    return expanded


def _parse_ref(ref: str) -> dict[str, str]:
    value = ref.strip().strip("`")
    value = value.lstrip("@")
    scope = "hub"
    entity_kind = ""
    slash_parts = value.split("/", 2)
    if len(slash_parts) == 3 and slash_parts[0].lower() in {"hub", "cloud"} and slash_parts[1].lower() in {"agent", "team"}:
        scope = slash_parts[0].lower()
        entity_kind = slash_parts[1].lower()
        value = slash_parts[2]
    if ":" in value:
        prefix, rest = value.split(":", 1)
        if prefix.lower() in {"hub", "network", "cloud", "bookmark", "bookmarks"}:
            scope = "cloud" if prefix.lower() == "cloud" else "hub"
            value = rest
    # Router/card ids carry a local marketplace tier (for example
    # ``paid/agent-name`` or ``free/agent-name``), while Hub runtime bundle
    # endpoints address the canonical slug only.  Treat those prefixes as
    # metadata, not as part of the requested slug.  Without this bridge a route
    # decision handed directly to hep-call becomes ``paid-agent-name`` and the
    # Hub correctly answers agent_not_found.
    tier, separator, remainder = value.partition("/")
    if separator and tier.lower() in {"paid", "free", "private", "restricted", "network", "hub"}:
        value = remainder
    return {"slug": _slug(value), "scope": scope, "entity_kind": entity_kind}


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")


def _section(scope: str, raw: dict[str, Any], query: str, limit: int) -> dict[str, Any]:
    results = raw.get("results") if isinstance(raw.get("results"), list) else []
    return {
        "scope": scope,
        "status": raw.get("status"),
        "query": raw.get("query"),
        "cached": bool(raw.get("cached", False)),
        "results": [_candidate(scope, item, index, query) for index, item in enumerate(results[:limit], start=1)],
        **({"expandedFrom": raw.get("expandedFrom")} if raw.get("expandedFrom") else {}),
        **({"fallbackReason": raw.get("fallbackReason")} if raw.get("fallbackReason") else {}),
        **({"detail": raw.get("detail")} if raw.get("detail") else {}),
        **({"question": raw.get("question") or raw.get("questionKo")} if raw.get("status") == "clarify" else {}),
        **({"note": raw.get("note")} if raw.get("note") else {}),
    }


def _candidate(scope: str, item: dict[str, Any], rank: int, query: str) -> dict[str, Any]:
    slug = str(item.get("slug") or "")
    name = item.get("nameEn") or item.get("name") or slug
    description = _description(item)
    return {
        "rank": rank,
        "scope": scope,
        "slug": slug,
        "name": name,
        "description": description,
        "kind": item.get("kind"),
        "callable": bool(item.get("callable", item.get("kind") == "cloud-callable")),
        "routingReady": item.get("routingReady"),
        "trustGrade": item.get("trustGrade"),
        "evalPassRate": item.get("evalPassRate"),
        "rating": item.get("rating"),
        "installCount": item.get("installCount"),
        "verifiedInvocations": item.get("verifiedInvocations"),
        "score": _display_score(item),
        "why": _why(item, query, description),
    }


def _description(item: dict[str, Any]) -> str:
    for key in ("taglineEn", "tagline", "summary", "summaryKo", "description", "descriptionKo"):
        value = item.get(key)
        if value:
            return str(value)
    kind = str(item.get("kind") or "agent")
    return f"{kind} package from Agentlas."


def _why(item: dict[str, Any], query: str, description: str) -> str:
    bits = []
    if item.get("routingReady"):
        bits.append("routing-ready")
    if item.get("callable") or item.get("kind") == "cloud-callable":
        bits.append("callable")
    if item.get("localContextReason"):
        bits.append(str(item["localContextReason"]))
    if not bits:
        bits.append("matched search query")
    return f"{', '.join(bits)} for: {query[:80]}" if not description else ", ".join(bits)


def _display_score(item: dict[str, Any]) -> float | None:
    for key in ("score", "rating", "evalPassRate"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _normalize_limit(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_SEARCH_LIMIT
    return max(1, min(25, parsed))


def parse_local_inventory(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except ValueError:
        return parse_agent_refs(value)
    if isinstance(payload, list):
        return [str(item) for item in payload if str(item).strip()]
    return []
