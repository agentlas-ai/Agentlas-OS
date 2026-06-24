"""Dry-run planner for Agentlas research module selection."""

from __future__ import annotations

from typing import Any

from .armory import module_readiness
from .contracts import ResearchRequest
from .engine import (
    _apply_source_hint_budget,
    _auto_search_modules,
    _dedupe,
    _expand_source_hints,
    _max_cost_requests,
    _source_hints_dropped,
    default_registry,
)
from .loadouts import apply_loadout, loadout_policy
from .policy import WEIGHT_RANKS, module_allowed, weight_allowed
from .registry import AdapterRegistry, ResearchAdapter


def run_research_plan(
    request_value: ResearchRequest | dict[str, Any] | str,
    *,
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Preview module routing without running network, browser, or receipt work."""

    request = apply_loadout(ResearchRequest.from_value(request_value))
    selected_registry = registry or default_registry()
    source_hints_before_budget = _expand_source_hints(request)
    source_hints = _apply_source_hint_budget(request, source_hints_before_budget)
    source_hints_dropped = _source_hints_dropped(source_hints_before_budget, source_hints)
    sources = []
    mounted_modules: list[str] = []
    ready_mounted_modules: list[str] = []
    unready_mounted_modules: list[dict[str, str]] = []
    blocked_modules: list[dict[str, str]] = []
    heaviest = ""

    for source_hint in source_hints:
        candidates = []
        for adapter in selected_registry.candidates(source_hint, request):
            planned = _planned_adapter(adapter, request, source_hint)
            candidates.append(planned)
            if planned["status"] == "mounted":
                mounted_modules.append(adapter.module_id)
                heaviest = _heavier(heaviest, adapter.weight)
                if planned["readiness"]["state"] == "ready":
                    ready_mounted_modules.append(adapter.module_id)
                else:
                    unready_mounted_modules.append(
                        {
                            "id": adapter.module_id,
                            "state": planned["readiness"]["state"],
                            "reason": planned["readiness"]["reason"],
                        }
                    )
            else:
                blocked_modules.append(
                    {
                        "id": adapter.module_id,
                        "source_hint": source_hint,
                        "status": planned["status"],
                        "reason": planned["reason"],
                    }
                )
        sources.append(
            {
                "source_hint": source_hint,
                "status": "planned" if candidates else "no_adapter",
                "candidates": candidates,
            }
        )

    mounted_modules = _dedupe(mounted_modules)
    ready_mounted_modules = _dedupe(ready_mounted_modules)
    browser_modules_mounted = any(module.startswith("browser.") for module in mounted_modules)
    browser_modules_ready = any(module.startswith("browser.") for module in ready_mounted_modules)
    return {
        "schema": "agentlas.research.plan.v0",
        "status": "ok" if source_hints else "needs_source",
        "request": request.to_dict(),
        "source_hints_before_budget": source_hints_before_budget,
        "source_hints_used": source_hints,
        "source_hints_dropped_by_budget": source_hints_dropped,
        "mounted_modules": mounted_modules,
        "ready_mounted_modules": ready_mounted_modules,
        "unready_mounted_modules": _dedupe_unready(unready_mounted_modules),
        "blocked_modules": _dedupe_blocked(blocked_modules),
        "sources": sources,
        "policy": {
            "network_will_run": False,
            "receipt_will_be_written": False,
            "credentials_exposed_to_model": False,
            "private_hosts_blocked": True,
            "max_weight": request.max_weight,
            "max_cost_requests": _max_cost_requests(request),
            "source_hint_count_before_budget": len(source_hints_before_budget),
            "source_hint_count_after_budget": len(source_hints),
            "source_hint_budget_limited": bool(source_hints_dropped),
            "estimated_heaviest_weight": heaviest,
            "browser_modules_mounted": browser_modules_mounted,
            "browser_modules_ready": browser_modules_ready,
            "read_strategy": (
                "deep_static_plus_browser"
                if str(request.depth).lower() == "deep" and browser_modules_ready
                else "first_success"
            ),
            "auto_search_modules": _auto_search_modules(request),
            "loadout": loadout_policy(request.loadout),
        },
    }


def _planned_adapter(adapter: ResearchAdapter, request: ResearchRequest, source_hint: str) -> dict[str, Any]:
    manifest = adapter.manifest.to_dict()
    allowed, reason = module_allowed(adapter.module_id, request.allowed_modules, request.forbidden_modules)
    if not allowed:
        status = "forbidden" if reason == "forbidden_module" else "blocked_by_allowlist"
    else:
        allowed, reason = weight_allowed(adapter.weight, request.max_weight)
        status = "mounted" if allowed else "blocked_by_weight"

    return {
        "id": adapter.module_id,
        "source_hint": source_hint,
        "status": status,
        "reason": reason,
        "slot": manifest.get("slot", ""),
        "weight": adapter.weight,
        "activation": manifest.get("activation", ""),
        "default_state": manifest.get("default_state", ""),
        "capabilities": manifest.get("capabilities", []),
        "requires": manifest.get("requires", []),
        "permissions": manifest.get("permissions", []),
        "install_hint": manifest.get("install_hint", ""),
        "readiness": module_readiness(adapter),
    }


def _heavier(current: str, candidate: str) -> str:
    if not current:
        return candidate
    return candidate if WEIGHT_RANKS.get(candidate, 0) > WEIGHT_RANKS.get(current, 0) else current


def _dedupe_blocked(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for item in items:
        key = (item.get("id", ""), item.get("status", ""), item.get("reason", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _dedupe_unready(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for item in items:
        key = (item.get("id", ""), item.get("state", ""), item.get("reason", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
