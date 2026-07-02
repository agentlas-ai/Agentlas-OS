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
    "tagline",
    "taglineEn",
    "summary",
    "summaryKo",
    "description",
    "descriptionKo",
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
    "source",
    "entityKind",
    "perCallCredits",
    "ownerName",
    "bookmarkedAt",
    "manifestId",
)


def _hub_url(home: Path) -> str:
    config = read_json(home / "config.json", default={}) or {}
    base = str(config.get("hub_url") or "https://agentlas.cloud").rstrip("/")
    return base


# Hub search scopes (three-scope command model — docs/hephaestus-network-2.0.md):
#   "cloud"   → signed-in user's own Agent Cloud packages.
#   "bookmark"→ signed-in user's saved Hub bookmarks.
#   "network" → public Agentlas Hub marketplace.
SCOPE_NETWORK = "network"
SCOPE_CLOUD = "cloud"
SCOPE_BOOKMARK = "bookmark"
_SCOPE_TOOL = {
    SCOPE_NETWORK: "marketplace.search_agents",
    SCOPE_CLOUD: "cargo.search_agents",
    SCOPE_BOOKMARK: "agent_cloud.search_bookmarks",
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
    owner_scoped = scope in {SCOPE_CLOUD, SCOPE_BOOKMARK}
    safe_tokens = _hub_query_tokens(query_tokens)
    # 의도 브릿지 토큰(예: 카피/쓰레드/홍보 → copywriter·writer·content)을 실제 Hub 검색어에 주입한다.
    # 이게 없으면 클라이언트 재랭킹이 "서버가 반환한 적 없는 후보"를 끌어올릴 수 없다 —
    # "Agentlas 쓰레드 글 써줘"에서 매칭 토큰이 브랜드명뿐이라 카피라이터가 검색조차 안 되는 문제를 고친다.
    _bridged = _bridged_query_tokens(set(safe_tokens))
    _query_terms = list(dict.fromkeys([*safe_tokens, *sorted(_bridged)]))
    redacted_query = " ".join(_query_terms)[:200]
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
    # Owner cloud search asks the Hub to restrict results to the authenticated
    # owner's own packages (`mine: true`). Bookmark search is also authenticated,
    # but it reads saved Hub refs rather than cloud package ownership.
    arguments: dict[str, Any] = {"q": redacted_query, "limit": _HUB_RESULT_LIMIT}
    if scope == SCOPE_CLOUD:
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
    # Cloud and bookmarks are sign-in-gated surfaces; send the stored bearer
    # token so Agentlas Web can resolve the caller workspace. Marketplace
    # search stays anonymous (token omitted).
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
                1 if pair[1].get("routingReady") else 0,
                1 if pair[1].get("callable") else 0,
                _local_context_score(pair[1], local_terms, query_tokens),
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
    return base


def _result_score(item: dict[str, Any], query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    haystack = " ".join(
        str(item.get(field) or "")
        for field in ("slug", "name", "nameEn", "tagline", "taglineEn")
    )
    haystack_tokens = token_set(haystack)
    score = float(len(query_tokens & haystack_tokens))
    bridged = _bridged_query_tokens(query_tokens)
    if bridged:
        score += 0.75 * len(bridged & haystack_tokens)
    return score


def _bridged_query_tokens(query_tokens: set[str]) -> set[str]:
    bridges: set[str] = set()
    # 글쓰기·SNS·홍보 의도어를 copywriter/writer role 토큰으로 확장한다. "쓰레드에 올릴 글 써줘"
    # 처럼 사용자가 '카피라이터'라는 단어를 안 써도, 실제 의도(콘텐츠 작성)에 맞는 에이전트를
    # 후보로 끌어오기 위함. (토큰화에서 살아남는 표현 위주로 트리거를 잡는다.)
    if query_tokens & {
        "카피", "카피라이터", "문구", "글쓰기", "쓰기", "써줘", "작성", "적어",
        "쓰레드", "스레드", "포스팅", "포스트", "게시글", "게시물", "홍보", "링크드인",
        "sns", "thread", "threads", "post", "posting", "linkedin", "tweet", "트윗",
        "블로그", "blog", "copywriting", "copywriter", "content", "카피라이팅",
    }:
        bridges.update({"copy", "copywriter", "writer", "content", "marketing"})
    if query_tokens & {"한국어", "한글"}:
        bridges.add("korean")
    if query_tokens & {"영어", "영문"}:
        bridges.add("english")
    if query_tokens & {"근거", "주장"}:
        bridges.add("claim")
    if query_tokens & {"원장"}:
        bridges.add("ledger")
    return bridges - query_tokens


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
