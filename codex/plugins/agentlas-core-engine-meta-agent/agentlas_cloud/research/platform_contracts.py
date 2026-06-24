"""Inspectable contracts for optional social platform cartridges."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .armory import module_readiness
from .engine import ResearchEngine, default_registry
from .policy import classify_url
from .registry import AdapterRegistry, ResearchAdapter


PLATFORM_SOURCE_HINTS: dict[str, list[str]] = {
    "platform.reddit.oauth": [
        "https://www.reddit.com/r/redditdev/",
        "https://www.reddit.com/r/redditdev/comments/<id>/<slug>/",
        "reddit:subreddit:<name>",
        "reddit:r:<name>",
        "reddit:user:<name>",
        "reddit:u:<name>",
        "reddit:search:<query>",
    ],
    "platform.reddit": [
        "https://www.reddit.com/r/redditdev/",
        "https://www.reddit.com/r/redditdev/comments/<id>/<slug>/",
        "reddit:subreddit:<name>",
        "reddit:r:<name>",
        "reddit:user:<name>",
        "reddit:u:<name>",
        "reddit:search:<query>",
    ],
    "platform.threads": [
        "threads:keyword:<query>",
        "threads:tag:<tag>",
        "threads:profile:<threads-user-id|me>",
        "threads:lookup:<username>",
        "threads:posts:<threads-user-id|me>",
        "threads:replies:<threads-user-id|me>",
        "threads:me",
    ],
    "platform.threads.public": [
        "https://www.threads.net/@<username>",
        "https://www.threads.net/@<username>/post/<id>",
        "threads:lookup:<username>",
        "threads:profile:<username>",
        "threads:user:<username>",
        "threads:url:<threads-public-url>",
    ],
}

PLATFORM_CREDENTIAL_ENVS: dict[str, list[str]] = {
    "platform.reddit.oauth": [
        "AGENTLAS_REDDIT_BEARER_TOKEN",
        "REDDIT_BEARER_TOKEN",
        "AGENTLAS_REDDIT_CLIENT_ID",
        "AGENTLAS_REDDIT_CLIENT_SECRET",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
    ],
    "platform.threads": ["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"],
}

PLATFORM_RUNTIME_NOTES: dict[str, list[str]] = {
    "platform.reddit.oauth": [
        "Uses oauth.reddit.com JSON endpoints for explicit Reddit URLs and Reddit source hints.",
        "Accepts a pre-issued bearer token or exchanges Reddit app client id/secret for an app-only OAuth token.",
        "Records compact Reddit rate-limit headers, never bearer token values.",
        "Does not silently fall through to platform.reddit during platform-check.",
    ],
    "platform.reddit": [
        "Uses www.reddit.com JSON first, then RSS for explicit Reddit URLs and Reddit source hints.",
        "Labels public fallback results with oauth_preferred/public_json_fallback/public_rss_fallback limits.",
        "No credential is required, but Reddit may rate-limit or block public fallback reads.",
    ],
    "platform.threads": [
        "Uses official graph.threads.net API endpoints only.",
        "Supports keyword/tag search plus profile, lookup, posts, and replies source hints.",
        "Does not scrape Threads pages when no official token is configured.",
    ],
    "platform.threads.public": [
        "Uses public Threads HTML/meta tags for explicit Threads URLs and username/profile hints.",
        "Does not run keyword search or hidden scraping; official Graph API remains the durable search path.",
        "Labels output as public_html_fallback and official_api_preferred.",
    ],
}


def run_research_platform_contracts(
    *,
    module_id: str = "",
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Describe platform cartridge contracts without running network."""

    selected_registry = registry or default_registry()
    contracts = [
        _contract_for_adapter(adapter)
        for adapter in selected_registry.adapters
        if adapter.manifest.slot == "platform" and (not module_id or adapter.module_id == module_id)
    ]
    return {
        "schema": "agentlas.research.platform_contracts.v0",
        "status": "ok" if contracts else "not_found",
        "module": module_id or "all",
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "contracts": contracts,
    }


def run_research_platform_check(
    *,
    module_id: str,
    source_hint: str,
    home: Path | str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Run one selected platform cartridge and summarize its proof receipt."""

    selected_registry = registry or default_registry()
    adapter = _find_platform_adapter(selected_registry, module_id)
    if adapter is None:
        return {
            "schema": "agentlas.research.platform_check.v0",
            "status": "not_found",
            "module": module_id,
            "source_hint": source_hint,
            "commands_will_run": False,
            "network_will_run": False,
            "credentials_exposed_to_model": False,
            "error": "platform_module_not_found",
        }

    contract = _contract_for_adapter(adapter)
    source_policy = _source_policy(adapter, source_hint)
    readiness = contract.get("readiness", {})
    network_will_run = bool(
        readiness.get("state") == "ready"
        and source_policy.get("safe") is True
        and source_policy.get("supported") is True
    )
    result = ResearchEngine(registry=AdapterRegistry([adapter]), home=home).run(
        {
            "query": f"Platform check for {module_id}",
            "intent": "platform_check",
            "source_hints": [source_hint],
            "allowed_modules": [module_id],
            "max_weight": "credentialed_medium",
            "max_cost": {"requests": 1, "seconds": 120, "tokens": 4000},
        }
    )
    return {
        "schema": "agentlas.research.platform_check.v0",
        "status": _platform_check_status(result),
        "module": module_id,
        "source_hint": source_hint,
        "commands_will_run": False,
        "network_will_run": network_will_run,
        "credentials_exposed_to_model": False,
        "operator_approval_required": False,
        "source_policy": source_policy,
        "contract": contract,
        "research_status": result.get("status"),
        "receipt_id": result.get("receipt", {}).get("receipt_id"),
        "request_hash": result.get("request", {}).get("request_hash"),
        "attempts": result.get("receipt", {}).get("attempts", []),
        "result_summaries": [_result_summary(item) for item in result.get("results", [])],
    }


def _contract_for_adapter(adapter: ResearchAdapter) -> dict[str, Any]:
    manifest = adapter.manifest.to_dict()
    return {
        "id": adapter.module_id,
        "slot": manifest.get("slot"),
        "weight": manifest.get("weight"),
        "activation": manifest.get("activation"),
        "default_state": manifest.get("default_state"),
        "capabilities": manifest.get("capabilities", []),
        "requires": manifest.get("requires", []),
        "permissions": manifest.get("permissions", []),
        "privacy": manifest.get("privacy", ""),
        "failure_modes": manifest.get("failure_modes", []),
        "readiness": module_readiness(adapter),
        "source_hints": PLATFORM_SOURCE_HINTS.get(adapter.module_id, []),
        "credential_env": PLATFORM_CREDENTIAL_ENVS.get(adapter.module_id, []),
        "credential_boundary": {
            "tokens_read_from_environment_only": bool(PLATFORM_CREDENTIAL_ENVS.get(adapter.module_id)),
            "secret_values_printed": False,
            "results_include_tokens": False,
        },
        "runtime_notes": PLATFORM_RUNTIME_NOTES.get(adapter.module_id, []),
        "check_examples": _check_examples(adapter.module_id),
    }


def _find_platform_adapter(registry: AdapterRegistry, module_id: str) -> ResearchAdapter | None:
    for adapter in registry.adapters:
        if adapter.module_id == module_id and adapter.manifest.slot == "platform":
            return adapter
    return None


def _source_policy(adapter: ResearchAdapter, source_hint: str) -> dict[str, Any]:
    supported = adapter.can_handle(source_hint, _check_request(module_id=adapter.module_id, source_hint=source_hint))
    parsed = urlsplit(source_hint)
    if parsed.scheme in {"http", "https"}:
        safe, reason = classify_url(source_hint)
        return {"safe": safe, "reason": reason, "supported": supported, "kind": "url"}
    return {
        "safe": supported,
        "reason": "platform_hint" if supported else "unsupported_source_hint",
        "supported": supported,
        "kind": "platform_hint",
    }


def _check_request(*, module_id: str, source_hint: str):
    from .contracts import ResearchRequest

    return ResearchRequest(
        query=f"Platform check for {module_id}",
        intent="platform_check",
        source_hints=[source_hint],
        allowed_modules=[module_id],
        max_weight="credentialed_medium",
        max_cost={"requests": 1, "seconds": 120, "tokens": 4000},
    )


def _platform_check_status(result: dict[str, Any]) -> str:
    results = result.get("results", [])
    if any(item.get("platform") in {"reddit", "threads"} and item.get("confidence") != "blocked" for item in results):
        return "ok"
    attempts = result.get("receipt", {}).get("attempts", [])
    statuses = {str(item.get("status") or "") for item in attempts}
    modules = {str(item.get("module") or "") for item in attempts}
    if "blocked" in statuses:
        return "blocked"
    if "module_unavailable" in statuses and any(module.startswith("platform.") for module in modules):
        return "not_ready"
    if "error" in statuses:
        return "failed"
    return "partial"


def _result_summary(item: dict[str, Any]) -> dict[str, Any]:
    content = str(item.get("content_markdown") or "")
    return {
        "title": item.get("title"),
        "url": item.get("url"),
        "platform": item.get("platform"),
        "confidence": item.get("confidence"),
        "limits": item.get("limits", []),
        "content_preview": content[:500],
    }


def _check_examples(module_id: str) -> list[dict[str, str]]:
    if module_id == "platform.reddit.oauth":
        return [
            {
                "name": "oauth_reddit_subreddit",
                "env": "AGENTLAS_REDDIT_BEARER_TOKEN or REDDIT_BEARER_TOKEN or AGENTLAS_REDDIT_CLIENT_ID+AGENTLAS_REDDIT_CLIENT_SECRET",
                "command": "bin/hephaestus research platform-check --module platform.reddit.oauth --source reddit:subreddit:redditdev",
            }
        ]
    if module_id == "platform.reddit":
        return [
            {
                "name": "public_reddit_search",
                "command": "bin/hephaestus research platform-check --module platform.reddit --source 'reddit:search:agent browser'",
            }
        ]
    if module_id == "platform.threads":
        return [
            {
                "name": "threads_keyword_search",
                "env": "AGENTLAS_THREADS_ACCESS_TOKEN or THREADS_ACCESS_TOKEN",
                "command": "bin/hephaestus research platform-check --module platform.threads --source 'threads:keyword:agent browser'",
            }
        ]
    if module_id == "platform.threads.public":
        return [
            {
                "name": "public_threads_profile",
                "command": "bin/hephaestus research platform-check --module platform.threads.public --source threads:lookup:agentlas",
            }
        ]
    return []
