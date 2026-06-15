"""Agentlas Hub fallback (MCP-compatible discovery).

Privacy contract:
- the raw prompt is never sent to the Hub — only redacted, normalized tokens;
- Hub lookup is a router operation, not final tool execution;
- offline machines degrade to the local cache, then to local-only routing.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..auth import ensure_access_token
from .bootstrap import append_jsonl, networking_home, read_json, read_jsonl, utc_now
from .card_store import load_global_cards
from .memory import redact_tokens
from .tokenize import token_set

_HUB_TIMEOUT_SECONDS = int(os.environ.get("HEPHAESTUS_HUB_TIMEOUT_SECONDS", "12") or "12")
_HUB_RESULT_LIMIT = int(os.environ.get("HEPHAESTUS_HUB_RESULT_LIMIT", "10") or "10")
_HUB_CACHE_TTL_SECONDS = int(os.environ.get("HEPHAESTUS_HUB_CACHE_TTL_SECONDS", "600") or "600")
HUB_TARGET = "agentlas-hub"
_HUB_CACHE_FILE = "hub-search.jsonl"
_RESULT_FIELDS = (
    "slug",
    "name",
    "nameEn",
    "kind",
    "callable",
    "routingReady",
    "routingStatus",
    "trustGrade",
    "installCount",
    "verifiedInvocations",
    "lastRoutingSuccessAt",
    "evalPassRate",
    "rating",
    "clusterSize",
    "alternateSlugs",
)


def _hub_url(home: Path) -> str:
    config = read_json(home / "config.json", default={}) or {}
    base = str(config.get("hub_url") or "https://agentlas.cloud").rstrip("/")
    return base


# Hub search scopes (three-scope command model — docs/hephaestus-network-2.0.md):
#   "network" → public Agentlas Hub marketplace (others' published agents).
#   "cloud"   → the signed-in user's OWN cloud packages only (보관함). These are
#               owner-scoped: the Hub filters to packages this account owns, and
#               they are restorable by the owner (call-priced at a flat 1 credit).
SCOPE_NETWORK = "network"
SCOPE_CLOUD = "cloud"
_SCOPE_TOOL = {
    SCOPE_NETWORK: "marketplace.search_agents",
    SCOPE_CLOUD: "cargo.search_agents",
}


def search_hub(
    query_tokens: list[str],
    home: Path | str | None = None,
    approved: bool = False,
    scope: str = SCOPE_NETWORK,
) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    _ = approved  # Kept for backwards-compatible callers; routing no longer gates Hub lookup.
    scope = scope if scope in _SCOPE_TOOL else SCOPE_NETWORK
    owner_scoped = scope == SCOPE_CLOUD
    safe_tokens = _hub_query_tokens(query_tokens)
    redacted_query = " ".join(dict.fromkeys(safe_tokens))[:200]
    local_terms = _local_inventory_terms(base)
    recommendation_intent = _recommendation_intent(set(safe_tokens))
    local_fingerprint = _local_inventory_fingerprint(local_terms)
    # Cache is keyed by scope too, so an owner-cloud lookup never serves (or
    # poisons) a public-marketplace result for the same query and vice versa.
    query_key = _cache_key(f"{scope}|{redacted_query}|local:{local_fingerprint}")
    cache_path = base / "cache" / _HUB_CACHE_FILE
    cached_hit = _cached_success(cache_path, query_key)
    if cached_hit is not None:
        cached_hit["scope"] = scope
        return cached_hit

    url = _hub_url(base) + "/api/mcp/v1"
    # Owner-scoped cloud search asks the Hub to restrict results to the
    # authenticated owner's own packages (`mine: true`). The marketplace search
    # has no such filter — it spans every public agent.
    arguments: dict[str, Any] = {"q": redacted_query, "limit": _HUB_RESULT_LIMIT}
    if owner_scoped:
        arguments["mine"] = True
        arguments["scope"] = "owner"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": _SCOPE_TOOL[scope],
                "arguments": arguments,
            },
        }
    ).encode("utf-8")
    # The owner cloud is a sign-in-gated surface (cargo.*); send the stored
    # bearer token when this is an owner-scoped lookup so the Hub can resolve
    # "mine". Marketplace search stays anonymous (token omitted).
    token = ensure_access_token(_hub_url(base), interactive=False) if owner_scoped else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hephaestus-network-router",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_HUB_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        cached = [entry for entry in read_jsonl(cache_path, limit=20)]
        return {
            "status": "offline",
            "scope": scope,
            "detail": str(exc),
            "cached": cached,
            "note": "Hub unreachable — falling back to cached results, then local-only routing.",
        }

    result_object = _extract_result_object(payload)
    if result_object.get("action") == "clarify":
        clarify = _project_clarify(result_object, local_terms, recommendation_intent)
        append_jsonl(
            cache_path,
            {
                "ts": utc_now(),
                "epoch": int(time.time()),
                "key": query_key,
                "q": redacted_query,
                "action": "clarify",
                "count": 0,
            },
        )
        return {"status": "clarify", "scope": scope, "query": redacted_query, **clarify, "limit": _HUB_RESULT_LIMIT}

    results = _prepare_results(
        _extract_results_from_object(result_object),
        set(safe_tokens),
        local_terms,
        recommendation_intent,
    )
    append_jsonl(
        cache_path,
        {
            "ts": utc_now(),
            "epoch": int(time.time()),
            "key": query_key,
            "q": redacted_query,
            "count": len(results),
            "results": results,
            "slugs": [item.get("slug") for item in results[:_HUB_RESULT_LIMIT]],
        },
    )
    return {"status": "ok", "scope": scope, "query": redacted_query, "results": results, "limit": _HUB_RESULT_LIMIT}


def _extract_results(payload: Any) -> list[dict[str, Any]]:
    return _extract_results_from_object(_extract_result_object(payload))


def _extract_result_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    result = payload.get("result")
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        parsed = json.loads(item.get("text") or "")
                    except ValueError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
        return result
    return {}


def _extract_results_from_object(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("results"), list):
        return [entry for entry in result["results"] if isinstance(entry, dict)]
    return []


def _project_clarify(
    result: dict[str, Any],
    local_terms: set[str] | None = None,
    recommendation_intent: bool = False,
) -> dict[str, Any]:
    suggestions = result.get("suggestions") if isinstance(result.get("suggestions"), list) else []
    return {
        "action": "clarify",
        "reason": result.get("reason") or "low_confidence",
        "question": result.get("question") or result.get("questionKo") or "Clarify the task before routing.",
        "questionKo": result.get("questionKo"),
        "suggestions": _prepare_results(
            [item for item in suggestions if isinstance(item, dict)],
            set(),
            local_terms or set(),
            recommendation_intent,
        ),
    }


def _cache_key(redacted_query: str) -> str:
    return sha256(redacted_query.encode("utf-8")).hexdigest()[:16]


def _hub_query_tokens(query_tokens: list[str]) -> list[str]:
    redacted = [token for token in redact_tokens(query_tokens) if token != "[redacted]"]
    hangul_words = [token for token in redacted if re.fullmatch(r"[가-힣]{3,}", token)]
    cleaned: list[str] = []
    for token in redacted:
        if re.fullmatch(r"[가-힣]{2}", token) and any(token in word for word in hangul_words):
            continue
        cleaned.append(token)
    return list(dict.fromkeys(cleaned))


def _cached_success(path: Path, key: str) -> dict[str, Any] | None:
    now = time.time()
    for entry in reversed(read_jsonl(path, limit=100)):
        if entry.get("key") != key:
            continue
        epoch = entry.get("epoch")
        if not isinstance(epoch, (int, float)) or now - float(epoch) > _HUB_CACHE_TTL_SECONDS:
            return None
        results = entry.get("results")
        if not isinstance(results, list):
            return None
        return {
            "status": "ok",
            "query": entry.get("q") or "",
            "results": [item for item in results if isinstance(item, dict)],
            "cached": True,
            "limit": _HUB_RESULT_LIMIT,
        }
    return None


def _prepare_results(
    results: list[dict[str, Any]],
    query_tokens: set[str],
    local_terms: set[str] | None = None,
    recommendation_intent: bool = False,
) -> list[dict[str, Any]]:
    local_terms = local_terms or set()
    # Client re-rank by query relevance with local inventory as a weak
    # tiebreaker. The Hub's order is preserved as the final, stable tiebreaker
    # (enumerate index) so that when the client has no stronger signal it does
    # not churn the Hub's sophisticated ranking. Relevance (_combined_score) is
    # specificity-aware via the Hub fields it reads, so this corrects a clearly
    # off-query top result without inverting an already-good Hub order.
    ranked = [
        item
        for _index, item in sorted(
            enumerate(results),
            key=lambda pair: (
                _combined_score(pair[1], query_tokens, local_terms, recommendation_intent),
                _result_score(pair[1], query_tokens),
                _local_context_score(pair[1], local_terms, query_tokens),
                1 if pair[1].get("routingReady") else 0,
                1 if pair[1].get("callable") else 0,
                int(pair[1].get("verifiedInvocations") or 0),
                int(pair[1].get("installCount") or 0),
                -pair[0],
            ),
            reverse=True,
        )
    ]
    deduped: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    seen_signatures: set[str] = set()
    for item in ranked:
        slug = str(item.get("slug") or "")
        signature = _name_signature(item)
        if slug in seen_slugs or (signature and signature in seen_signatures):
            continue
        projected = _project_result(item)
        if not projected.get("slug"):
            continue
        local_score = _local_context_score(item, local_terms, query_tokens)
        if local_score > 0:
            projected["localContextScore"] = local_score
            if recommendation_intent:
                projected["localContextReason"] = "matches-local-inventory"
        deduped.append(projected)
        seen_slugs.add(slug)
        if signature:
            seen_signatures.add(signature)
        if len(deduped) >= _HUB_RESULT_LIMIT:
            break
    return deduped


def _combined_score(
    item: dict[str, Any],
    query_tokens: set[str],
    local_terms: set[str],
    recommendation_intent: bool,
) -> float:
    base = float(_result_score(item, query_tokens))
    local = float(_local_context_score(item, local_terms, query_tokens))
    if recommendation_intent:
        return base + min(local, 5.0)
    return base + min(local, 1.0) * 0.15


def _result_score(item: dict[str, Any], query_tokens: set[str]) -> int:
    if not query_tokens:
        return 0
    haystack = " ".join(
        str(item.get(field) or "")
        for field in ("slug", "name", "nameEn", "tagline", "taglineEn")
    )
    return len(query_tokens & token_set(haystack))


def _local_context_score(item: dict[str, Any], local_terms: set[str], query_tokens: set[str]) -> int:
    if not local_terms:
        return 0
    haystack = " ".join(
        str(item.get(field) or "")
        for field in ("slug", "name", "nameEn", "tagline", "taglineEn")
    )
    result_terms = token_set(haystack)
    overlap = (result_terms & local_terms) - query_tokens - _GENERIC_LOCAL_TERMS
    return min(8, len(overlap))


def _name_signature(item: dict[str, Any]) -> str:
    raw = " ".join(str(item.get(field) or "") for field in ("name", "nameEn", "slug")).lower()
    raw = re.sub(r"\b(agent|builder|pipeline|eval|evaluation|feedback|assistant|tool)\b", " ", raw)
    parts = [part for part in re.split(r"[^a-z0-9가-힣]+", raw) if len(part) >= 2 and not part.isdigit()]
    return "-".join(parts[:5])


_GENERIC_LOCAL_TERMS = {
    "agent",
    "agents",
    "assistant",
    "builder",
    "pipeline",
    "tool",
    "team",
    "workflow",
    "에이전트",
    "도구",
    "팀",
}

_RECOMMENDATION_TERMS = {
    "recommend",
    "recommendation",
    "suggest",
    "suggestion",
    "new",
    "next",
    "missing",
    "complement",
    "complementary",
    "improve",
    "upgrade",
    "추천",
    "추천좀",
    "새기능",
    "신규",
    "보완",
    "추가",
    "필요",
    "어울",
}


def _recommendation_intent(query_tokens: set[str]) -> bool:
    return bool(query_tokens & _RECOMMENDATION_TERMS)


def _local_inventory_fingerprint(local_terms: set[str]) -> str:
    if not local_terms:
        return "none"
    joined = "\n".join(sorted(local_terms))
    return sha256(joined.encode("utf-8")).hexdigest()[:10]


def _local_inventory_terms(home: Path) -> set[str]:
    try:
        cards, _ = load_global_cards(home)
    except Exception:
        return set()
    terms: set[str] = set()
    for card in cards:
        if card.get("stale"):
            continue
        terms.update(token_set(_local_card_text(card)))
    return {term for term in terms if term not in _GENERIC_LOCAL_TERMS and len(term) >= 2}


def _local_card_text(card: dict[str, Any]) -> str:
    chunks: list[str] = [
        str(card.get("id") or ""),
        str(card.get("canonical_id") or ""),
        str(card.get("name") or ""),
        str(card.get("name_ko") or ""),
        str(card.get("summary") or ""),
        str(card.get("summary_ko") or ""),
        " ".join(str(item) for item in card.get("aliases") or []),
        " ".join(str(item) for item in card.get("capabilities") or []),
    ]
    for trigger in card.get("trigger_examples") or []:
        if isinstance(trigger, dict):
            chunks.append(str(trigger.get("text") or ""))
        else:
            chunks.append(str(trigger))
    return " ".join(chunks)


def _project_result(item: dict[str, Any]) -> dict[str, Any]:
    projected = {field: item[field] for field in _RESULT_FIELDS if field in item and item[field] is not None}
    if "verifiedInvocations" not in projected and "installCount" in projected:
        projected["verifiedInvocations"] = projected["installCount"]
    return projected
