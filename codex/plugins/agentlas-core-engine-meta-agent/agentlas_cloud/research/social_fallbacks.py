"""Non-executing summary of no-token social research fallbacks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .armory import module_readiness
from .engine import default_registry
from .loadouts import loadout_policy
from .registry import AdapterRegistry


PUBLIC_FALLBACK_MODULES = ("platform.reddit", "platform.threads.public", "read.insane_fetch")
OFFICIAL_SOCIAL_MODULES = ("platform.reddit.oauth", "platform.threads")


def run_research_social_fallbacks(
    *,
    home: Path | str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Describe public social fallbacks without fetching or exposing secrets."""

    selected_registry = registry or default_registry(home=home)
    modules = {
        adapter.module_id: _module_summary(adapter)
        for adapter in selected_registry.adapters
        if adapter.module_id in (*PUBLIC_FALLBACK_MODULES, *OFFICIAL_SOCIAL_MODULES)
    }
    return {
        "schema": "agentlas.research.social_fallbacks.v0",
        "status": "ok",
        "home": str(home or ""),
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "decision": {
            "insane_search_fit": "detachable_reader_cartridge",
            "core_engine_fit": "keep_agentlas_research_engine_as_planner_ranker_receipt_core",
            "stormbreaker_fit": "mount_public_web_by_default; social_loadout_only_when_official_api_is_explicitly_allowed",
        },
        "upstream_reference": {
            "name": "fivetaku/insane-search",
            "url": "https://github.com/fivetaku/insane-search",
            "role": "reference implementation for resilient public-page reading, not a credentialed social API replacement",
        },
        "no_token_coverage": {
            "reddit": [
                "explicit Reddit URLs",
                "subreddit, user, and search source hints",
                "public JSON first, RSS fallback on common blocks",
                "post comments when public JSON returns comment payloads",
            ],
            "threads": [
                "explicit public Threads URLs",
                "username/profile hints through public HTML/meta",
                "keyword discovery only through normal web search fallback until Graph token is configured",
            ],
            "blocked_public_pages": [
                "direct public read",
                "Reddit RSS route",
                "metadata and JSON-LD extraction",
                "Jina Reader fallback when external-reader disclosure is acceptable",
            ],
        },
        "official_api_required_for": [
            "reddit_oauth_live_check",
            "threads_live_graph_check",
            "durable Threads keyword/tag search",
            "Threads posts and replies API reads",
        ],
        "recommended_loadouts": {
            "normal_agent_build_research": "safe",
            "blocked_public_pages": "public-web",
            "reddit_or_threads_market_reaction": "public-web",
            "official_reddit_or_threads_api": "social",
            "js_heavy_or_interactive_pages": "browser",
        },
        "loadout_boundaries": {
            "safe": loadout_policy("safe"),
            "public-web": loadout_policy("public-web"),
            "social": loadout_policy("social"),
            "browser": loadout_policy("browser"),
        },
        "modules": [modules[module_id] for module_id in (*PUBLIC_FALLBACK_MODULES, *OFFICIAL_SOCIAL_MODULES) if module_id in modules],
        "next_commands": [
            "bin/hephaestus research social-fallbacks",
            "bin/hephaestus research preflight 'Threads와 Reddit 반응까지 조사'",
            "bin/hephaestus research read 'reddit:search:agent browser' --loadout public-web",
            "bin/hephaestus research gather 'agent browser Threads Reddit 반응' --loadout public-web --variant reddit --variant threads",
            "bin/hephaestus research credentials",
        ],
    }


def _module_summary(adapter) -> dict[str, Any]:
    manifest = adapter.manifest.to_dict()
    official = adapter.module_id in OFFICIAL_SOCIAL_MODULES
    return {
        "id": adapter.module_id,
        "slot": manifest.get("slot"),
        "weight": manifest.get("weight"),
        "activation": manifest.get("activation"),
        "default_state": manifest.get("default_state"),
        "capabilities": manifest.get("capabilities", []),
        "requires": manifest.get("requires", []),
        "permissions": manifest.get("permissions", []),
        "failure_modes": manifest.get("failure_modes", []),
        "readiness": module_readiness(adapter),
        "no_token": not official,
        "token_required": official,
        "role": _module_role(adapter.module_id),
    }


def _module_role(module_id: str) -> str:
    if module_id == "platform.reddit":
        return "reddit_public_json_rss_fallback"
    if module_id == "platform.threads.public":
        return "threads_public_url_profile_fallback"
    if module_id == "read.insane_fetch":
        return "adaptive_public_page_reader"
    if module_id == "platform.reddit.oauth":
        return "official_reddit_oauth_reader"
    if module_id == "platform.threads":
        return "official_threads_graph_reader"
    return "research_module"
