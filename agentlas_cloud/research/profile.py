"""Non-executing loadout profile for the research module armory."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .armory import module_readiness
from .contracts import ResearchRequest
from .engine import default_registry
from .loadouts import apply_loadout, loadout_names, loadout_policy
from .policy import WEIGHT_RANKS, module_allowed, weight_allowed
from .registry import AdapterRegistry


def run_research_profile(
    *,
    loadout: str = "",
    source_hints: list[str] | None = None,
    home: Path | str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Compare loadout footprints without network, browser, or receipt work."""

    selected_registry = registry or default_registry(home=home)
    names = [loadout] if loadout else loadout_names()
    profiles = [
        _profile_loadout(name, source_hints=list(source_hints or []), registry=selected_registry)
        for name in names
    ]
    return {
        "schema": "agentlas.research.profile.v0",
        "status": "ok" if profiles else "not_found",
        "loadout": loadout or "all",
        "home": str(home or ""),
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "profiles": profiles,
    }


def _profile_loadout(name: str, *, source_hints: list[str], registry: AdapterRegistry) -> dict[str, Any]:
    request = apply_loadout(
        ResearchRequest(
            query="profile",
            source_hints=source_hints,
            loadout=name,
        )
    )
    allowed_modules = set(request.allowed_modules)
    modules: list[dict[str, Any]] = []
    mounted_slot_counts: Counter[str] = Counter()
    mounted_weight_counts: Counter[str] = Counter()
    readiness_counts: Counter[str] = Counter()
    heaviest = ""

    for adapter in registry.adapters:
        manifest = adapter.manifest.to_dict()
        allowed, allow_reason = module_allowed(adapter.module_id, request.allowed_modules, request.forbidden_modules)
        weight_ok, weight_reason = weight_allowed(adapter.weight, request.max_weight)
        mounted = bool(allowed and weight_ok and adapter.module_id in allowed_modules)
        readiness = module_readiness(adapter)
        if mounted:
            slot = str(manifest.get("slot") or "unknown")
            mounted_slot_counts[slot] += 1
            mounted_weight_counts[adapter.weight] += 1
            readiness_counts[str(readiness.get("state") or "unknown")] += 1
            heaviest = _heavier(heaviest, adapter.weight)
        modules.append(
            {
                "id": adapter.module_id,
                "slot": manifest.get("slot"),
                "weight": adapter.weight,
                "activation": manifest.get("activation"),
                "default_state": manifest.get("default_state"),
                "mounted": mounted,
                "mount_reason": "mounted" if mounted else _mount_reason(allow_reason, weight_reason, adapter.module_id, allowed_modules),
                "readiness": readiness,
            }
        )

    mounted_modules = [module for module in modules if module["mounted"]]
    browser_modules = [module for module in mounted_modules if str(module.get("id", "")).startswith("browser.")]
    external_modules = [
        module
        for module in mounted_modules
        if module.get("weight") in {"external_light", "adaptive_medium", "credentialed_medium", "browser_heavy"}
    ]
    ready_modules = [module for module in mounted_modules if module.get("readiness", {}).get("state") == "ready"]
    unready_modules = [module for module in mounted_modules if module.get("readiness", {}).get("state") != "ready"]
    return {
        "name": name,
        "loadout": loadout_policy(name),
        "request": request.to_dict(),
        "footprint": {
            "total_registered_modules": len(modules),
            "mounted_module_count": len(mounted_modules),
            "detached_module_count": len(modules) - len(mounted_modules),
            "ready_mounted_module_count": len(ready_modules),
            "unready_mounted_module_count": len(mounted_modules) - len(ready_modules),
            "mounted_slot_counts": dict(sorted(mounted_slot_counts.items())),
            "mounted_weight_counts": dict(sorted(mounted_weight_counts.items())),
            "mounted_readiness_counts": dict(sorted(readiness_counts.items())),
            "heaviest_mounted_weight": heaviest,
            "browser_modules_mounted": bool(browser_modules),
            "browser_module_count": len(browser_modules),
            "external_or_credentialed_module_count": len(external_modules),
            "source_hints_considered": list(source_hints),
        },
        "boundaries": {
            "commands_will_run": False,
            "network_will_run": False,
            "credentials_exposed_to_model": False,
            "private_hosts_blocked": True,
            "loadout_max_weight": request.max_weight,
            "browser_requires_explicit_loadout_or_allow": True,
            "adaptive_requires_public_web_or_explicit_allow": True,
        },
        "operator_summary": _operator_summary(
            name=name,
            mounted_modules=mounted_modules,
            ready_modules=ready_modules,
            unready_modules=unready_modules,
        ),
        "mounted_modules": [_compact_module(module) for module in mounted_modules],
    }


def _mount_reason(allow_reason: str, weight_reason: str, module_id: str, allowed_modules: set[str]) -> str:
    if module_id not in allowed_modules:
        return "detached_from_loadout"
    if allow_reason != "allowed":
        return allow_reason
    if weight_reason != "allowed":
        return weight_reason
    return "not_mounted"


def _compact_module(module: dict[str, Any]) -> dict[str, Any]:
    readiness = module.get("readiness", {})
    return {
        "id": module.get("id"),
        "slot": module.get("slot"),
        "weight": module.get("weight"),
        "readiness": {
            "state": readiness.get("state"),
            "reason": readiness.get("reason"),
        },
    }


def _operator_summary(
    *,
    name: str,
    mounted_modules: list[dict[str, Any]],
    ready_modules: list[dict[str, Any]],
    unready_modules: list[dict[str, Any]],
) -> dict[str, Any]:
    browser_modules = [module for module in mounted_modules if str(module.get("id", "")).startswith("browser.")]
    ready_browser = [module for module in ready_modules if str(module.get("id", "")).startswith("browser.")]
    credential_modules = [
        module
        for module in mounted_modules
        if module.get("id") in {"platform.reddit.oauth", "platform.threads", "search.jina"}
    ]
    missing_credentials = [
        module
        for module in credential_modules
        if module.get("readiness", {}).get("state") == "needs_config"
    ]
    setup_actions = _setup_actions(missing_credentials=missing_credentials, browser_modules=browser_modules, ready_browser=ready_browser)
    return {
        "posture": _posture(name=name, mounted_modules=mounted_modules, browser_modules=browser_modules, credential_modules=credential_modules),
        "safe_default": name in {"auto", "safe"},
        "heavy_modules_detached": not browser_modules,
        "operator_approval_recommended": bool(browser_modules),
        "ready_to_run_without_extra_config": not unready_modules or bool(browser_modules and ready_browser and not missing_credentials),
        "ready_browser_hardpoints": [str(module.get("id")) for module in ready_browser],
        "missing_credential_modules": [str(module.get("id")) for module in missing_credentials],
        "unready_mounted_modules": [
            {
                "id": module.get("id"),
                "state": module.get("readiness", {}).get("state"),
                "reason": module.get("readiness", {}).get("reason"),
            }
            for module in unready_modules[:12]
        ],
        "next_actions": setup_actions,
    }


def _posture(
    *,
    name: str,
    mounted_modules: list[dict[str, Any]],
    browser_modules: list[dict[str, Any]],
    credential_modules: list[dict[str, Any]],
) -> str:
    if browser_modules:
        return "browser_heavy"
    if any(module.get("id") in {"platform.reddit.oauth", "platform.threads"} for module in credential_modules):
        return "credentialed_social"
    if any(module.get("weight") == "adaptive_medium" for module in mounted_modules):
        return "adaptive_public"
    if name == "auto":
        return "source_aware_light_default"
    return "light"


def _setup_actions(
    *,
    missing_credentials: list[dict[str, Any]],
    browser_modules: list[dict[str, Any]],
    ready_browser: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    missing_ids = {str(module.get("id")) for module in missing_credentials}
    if "platform.reddit.oauth" in missing_ids:
        actions.append(
            {
                "action": "configure_credentials",
                "module": "platform.reddit.oauth",
                "reason": "reddit_oauth_missing",
                "env": ["AGENTLAS_REDDIT_BEARER_TOKEN", "REDDIT_BEARER_TOKEN"],
                "env_alternatives": [
                    ["AGENTLAS_REDDIT_BEARER_TOKEN"],
                    ["REDDIT_BEARER_TOKEN"],
                    ["AGENTLAS_REDDIT_CLIENT_ID", "AGENTLAS_REDDIT_CLIENT_SECRET"],
                    ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
                ],
                "check_command": "bin/hephaestus research platform-check --module platform.reddit.oauth --source 'reddit:subreddit:redditdev'",
            }
        )
    if "platform.threads" in missing_ids:
        actions.append(
            {
                "action": "configure_credentials",
                "module": "platform.threads",
                "reason": "threads_graph_missing",
                "env": ["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"],
                "check_command": "bin/hephaestus research platform-check --module platform.threads --source 'threads:keyword:agent browser'",
            }
        )
    if browser_modules and not ready_browser:
        actions.append(
            {
                "action": "configure_browser_hardpoint",
                "module": "browser.*",
                "reason": "no_ready_browser_hardpoint",
                "check_command": "bin/hephaestus research hardpoints",
            }
        )
    return actions


def _heavier(current: str, candidate: str) -> str:
    if not current:
        return candidate
    return candidate if WEIGHT_RANKS.get(candidate, 0) > WEIGHT_RANKS.get(current, 0) else current
