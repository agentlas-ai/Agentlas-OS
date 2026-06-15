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

from .bootstrap import append_jsonl, networking_home, read_json, read_jsonl, utc_now
from .memory import redact_tokens
from .tokenize import token_set

_HUB_TIMEOUT_SECONDS = 6
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
)


def _hub_url(home: Path) -> str:
    config = read_json(home / "config.json", default={}) or {}
    base = str(config.get("hub_url") or "https://agentlas.cloud").rstrip("/")
    return base


def search_hub(
    query_tokens: list[str],
    home: Path | str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    _ = approved  # Kept for backwards-compatible callers; routing no longer gates Hub lookup.
    safe_tokens = _hub_query_tokens(query_tokens)
    redacted_query = " ".join(dict.fromkeys(safe_tokens))[:200]
    query_key = _cache_key(redacted_query)
    cache_path = base / "cache" / _HUB_CACHE_FILE
    cached_hit = _cached_success(cache_path, query_key)
    if cached_hit is not None:
        return cached_hit

    url = _hub_url(base) + "/api/mcp/v1"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "marketplace.search_agents",
                "arguments": {"q": redacted_query, "limit": _HUB_RESULT_LIMIT},
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hephaestus-network-router",
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
            "detail": str(exc),
            "cached": cached,
            "note": "Hub unreachable — falling back to cached results, then local-only routing.",
        }

    result_object = _extract_result_object(payload)
    if result_object.get("action") == "clarify":
        clarify = _project_clarify(result_object)
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
        return {"status": "clarify", "query": redacted_query, **clarify, "limit": _HUB_RESULT_LIMIT}

    results = _prepare_results(_extract_results_from_object(result_object), set(safe_tokens))
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
    return {"status": "ok", "query": redacted_query, "results": results, "limit": _HUB_RESULT_LIMIT}


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


def _project_clarify(result: dict[str, Any]) -> dict[str, Any]:
    suggestions = result.get("suggestions") if isinstance(result.get("suggestions"), list) else []
    return {
        "action": "clarify",
        "reason": result.get("reason") or "low_confidence",
        "question": result.get("question") or result.get("questionKo") or "Clarify the task before routing.",
        "questionKo": result.get("questionKo"),
        "suggestions": _prepare_results([item for item in suggestions if isinstance(item, dict)], set()),
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


def _prepare_results(results: list[dict[str, Any]], query_tokens: set[str]) -> list[dict[str, Any]]:
    ranked = sorted(
        results,
        key=lambda item: (
            _result_score(item, query_tokens),
            1 if item.get("routingReady") else 0,
            1 if item.get("callable") else 0,
            int(item.get("verifiedInvocations") or 0),
            int(item.get("installCount") or 0),
        ),
        reverse=True,
    )
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
        deduped.append(projected)
        seen_slugs.add(slug)
        if signature:
            seen_signatures.add(signature)
        if len(deduped) >= _HUB_RESULT_LIMIT:
            break
    return deduped


def _result_score(item: dict[str, Any], query_tokens: set[str]) -> int:
    if not query_tokens:
        return 0
    haystack = " ".join(
        str(item.get(field) or "")
        for field in ("slug", "name", "nameEn", "tagline", "taglineEn")
    )
    return len(query_tokens & token_set(haystack))


def _name_signature(item: dict[str, Any]) -> str:
    raw = " ".join(str(item.get(field) or "") for field in ("name", "nameEn", "slug")).lower()
    raw = re.sub(r"\b(agent|builder|pipeline|eval|evaluation|feedback|assistant|tool)\b", " ", raw)
    parts = [part for part in re.split(r"[^a-z0-9가-힣]+", raw) if len(part) >= 2 and not part.isdigit()]
    return "-".join(parts[:5])


def _project_result(item: dict[str, Any]) -> dict[str, Any]:
    projected = {field: item[field] for field in _RESULT_FIELDS if field in item and item[field] is not None}
    if "verifiedInvocations" not in projected and "installCount" in projected:
        projected["verifiedInvocations"] = projected["installCount"]
    return projected
