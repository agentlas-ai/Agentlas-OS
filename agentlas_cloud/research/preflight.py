"""Non-executing mount preflight for the research module armory."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .armory import module_readiness
from .contracts import ResearchRequest
from .engine import default_registry
from .loadouts import apply_loadout, loadout_policy
from .planner import run_research_plan
from .policy import module_allowed, weight_allowed
from .recommend import run_research_recommendation
from .registry import AdapterRegistry


HEAVY_WEIGHTS = {"adaptive_medium", "credentialed_medium", "browser_heavy"}


def run_research_preflight(
    *,
    query: str,
    source_hints: list[str] | None = None,
    loadout: str = "recommended",
    depth: str = "quick",
    follow_results: int | None = None,
    query_variants: list[str] | None = None,
    max_requests: int | None = None,
    max_weight: str = "",
    allowed_modules: list[str] | None = None,
    forbidden_modules: list[str] | None = None,
    home: Path | str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Preview a build-time research mount without network, browser, or receipts."""

    compact_query = " ".join(query.split()).strip()
    hints = [hint.strip() for hint in source_hints or [] if hint and hint.strip()]
    preview_hints = hints or ([f"search:auto:{compact_query}"] if compact_query else [])
    selected_registry = registry or default_registry(home=home)
    recommendation = None
    request = _request_from_inputs(
        query=compact_query,
        source_hints=preview_hints,
        loadout=loadout,
        depth=depth,
        follow_results=follow_results,
        query_variants=list(query_variants or []),
        max_requests=max_requests,
        max_weight=max_weight,
        allowed_modules=list(allowed_modules or []),
        forbidden_modules=list(forbidden_modules or []),
    )

    if loadout == "recommended":
        recommendation = run_research_recommendation(
            query=compact_query,
            source_hints=hints,
            home=home,
        )
        request = _request_from_recommendation(
            request,
            recommendation=recommendation,
            explicit_follow_results=follow_results is not None,
            explicit_max_requests=max_requests is not None,
            explicit_depth=bool(depth and depth != "quick"),
            explicit_variants=bool(query_variants),
        )

    request = apply_loadout(request)
    plan = run_research_plan(request, registry=selected_registry)
    modules = _preflight_modules(selected_registry, request)
    slot_summary = _slot_summary(modules)
    mounted = [module for module in modules if module["mounted"]]
    heavy_mounted = [module for module in mounted if module["weight"] in HEAVY_WEIGHTS]
    readiness_blockers = [
        {
            "id": module["id"],
            "slot": module["slot"],
            "state": module["readiness"]["state"],
            "reason": module["readiness"]["reason"],
            "missing_env": _missing_env(module["readiness"]),
            "accepted_env_sets": _accepted_env_sets(module["readiness"]),
        }
        for module in mounted
        if module["readiness"]["state"] != "ready"
    ]
    browser_modules_mounted = any(str(module["id"]).startswith("browser.") for module in mounted)
    mount_decision = _mount_decision(
        request=request,
        mounted=mounted,
        heavy_mounted=heavy_mounted,
        readiness_blockers=readiness_blockers,
        recommendation=recommendation,
    )
    return {
        "schema": "agentlas.research.preflight.v0",
        "status": "ok" if compact_query or preview_hints else "needs_query",
        "commands_will_run": False,
        "network_will_run": False,
        "browser_will_run": False,
        "credentials_exposed_to_model": False,
        "home": str(home or ""),
        "query": compact_query,
        "requested_loadout": loadout,
        "resolved_loadout": request.loadout,
        "recommendation": _compact_recommendation(recommendation),
        "request": request.to_dict(),
        "summary": {
            "selected_loadout": request.loadout,
            "max_weight": request.max_weight,
            "mounted_module_count": len(mounted),
            "detached_module_count": len(modules) - len(mounted),
            "heavy_mounted_module_count": len(heavy_mounted),
            "browser_modules_mounted": browser_modules_mounted,
            "browser_module_count": slot_summary.get("browser", {}).get("mounted_count", 0),
            "readiness_blocker_count": len(readiness_blockers),
            "source_hint_count_before_budget": plan["policy"]["source_hint_count_before_budget"],
            "source_hint_count_after_budget": plan["policy"]["source_hint_count_after_budget"],
            "source_hint_budget_limited": plan["policy"]["source_hint_budget_limited"],
            "estimated_heaviest_weight": plan["policy"]["estimated_heaviest_weight"],
        },
        "slot_summary": slot_summary,
        "mounted_modules": [_compact_module(module) for module in mounted],
        "heavy_modules_mounted": [_compact_module(module) for module in heavy_mounted],
        "heavy_modules_detached": [
            _compact_module(module)
            for module in modules
            if not module["mounted"] and module["weight"] in HEAVY_WEIGHTS
        ],
        "readiness_blockers": readiness_blockers,
        "mount_decision": mount_decision,
        "plan_preview": {
            "source_hints_before_budget": plan["source_hints_before_budget"],
            "source_hints_used": plan["source_hints_used"],
            "source_hints_dropped_by_budget": plan["source_hints_dropped_by_budget"],
            "mounted_modules": plan["mounted_modules"],
            "unready_mounted_modules": plan["unready_mounted_modules"],
            "policy": plan["policy"],
        },
        "boundaries": {
            "default_stays_light": True,
            "heavy_modules_are_detachable": True,
            "browser_requires_browser_or_full_loadout_or_explicit_allow": True,
            "social_credentials_checked_by_readiness_not_exposed": True,
            "preflight_executes_modules": False,
        },
        "loadout": loadout_policy(request.loadout),
    }


def _request_from_inputs(
    *,
    query: str,
    source_hints: list[str],
    loadout: str,
    depth: str,
    follow_results: int | None,
    query_variants: list[str],
    max_requests: int | None,
    max_weight: str,
    allowed_modules: list[str],
    forbidden_modules: list[str],
) -> ResearchRequest:
    max_cost = {"requests": max(0, int(max_requests))} if max_requests is not None else {}
    return ResearchRequest(
        query=query or "Research preflight",
        intent="preflight",
        source_hints=list(source_hints),
        loadout=loadout,
        depth=depth or "quick",
        follow_results=max(0, int(follow_results)) if follow_results is not None else 0,
        query_variants=list(query_variants),
        max_weight=max_weight or "",
        max_cost=max_cost,
        allowed_modules=list(allowed_modules),
        forbidden_modules=list(forbidden_modules),
    )


def _request_from_recommendation(
    request: ResearchRequest,
    *,
    recommendation: dict[str, Any],
    explicit_follow_results: bool,
    explicit_max_requests: bool,
    explicit_depth: bool,
    explicit_variants: bool,
) -> ResearchRequest:
    rec = recommendation.get("recommendation") if isinstance(recommendation, dict) else {}
    if not isinstance(rec, dict):
        rec = {}
    variants = list(request.query_variants)
    if not explicit_variants:
        variants = [str(item) for item in rec.get("query_variants") or []]
    max_cost = dict(request.max_cost or {})
    if not explicit_max_requests:
        max_requests = rec.get("max_requests")
        if isinstance(max_requests, int) and max_requests > 0:
            max_cost["requests"] = max_requests
    return ResearchRequest(
        query=request.query,
        intent=request.intent,
        source_hints=list(request.source_hints),
        loadout=str(rec.get("loadout") or "safe"),
        depth=str(request.depth if explicit_depth else (rec.get("depth") or request.depth or "quick")),
        follow_results=(
            request.follow_results
            if explicit_follow_results
            else int(rec.get("follow_results") or request.follow_results or 0)
        ),
        query_variants=variants,
        max_weight=request.max_weight,
        max_cost=max_cost,
        allowed_modules=list(request.allowed_modules),
        forbidden_modules=list(request.forbidden_modules),
    )


def _preflight_modules(registry: AdapterRegistry, request: ResearchRequest) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    allowed_set = set(request.allowed_modules)
    for adapter in registry.adapters:
        manifest = adapter.manifest.to_dict()
        allow_ok, allow_reason = module_allowed(adapter.module_id, request.allowed_modules, request.forbidden_modules)
        weight_ok, weight_reason = weight_allowed(adapter.weight, request.max_weight)
        in_loadout = adapter.module_id in allowed_set if allowed_set else allow_ok
        mounted = bool(in_loadout and allow_ok and weight_ok)
        readiness = module_readiness(adapter)
        modules.append(
            {
                "id": adapter.module_id,
                "slot": manifest.get("slot", ""),
                "weight": adapter.weight,
                "mounted": mounted,
                "mount_reason": "mounted" if mounted else _mount_reason(in_loadout, allow_reason, weight_reason),
                "readiness": readiness,
                "activation": manifest.get("activation", ""),
                "default_state": manifest.get("default_state", ""),
            }
        )
    return modules


def _slot_summary(modules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counts: dict[str, Counter[str]] = {}
    mounted_by_slot: dict[str, list[str]] = {}
    for module in modules:
        slot = str(module.get("slot") or "unknown")
        counts.setdefault(slot, Counter())
        counter = counts[slot]
        counter["total_count"] += 1
        if module["mounted"]:
            counter["mounted_count"] += 1
            mounted_by_slot.setdefault(slot, []).append(str(module["id"]))
            if module["readiness"]["state"] == "ready":
                counter["ready_mounted_count"] += 1
            else:
                counter["unready_mounted_count"] += 1
        else:
            counter["detached_count"] += 1
    return {
        slot: {
            "total_count": counter.get("total_count", 0),
            "mounted_count": counter.get("mounted_count", 0),
            "detached_count": counter.get("detached_count", 0),
            "ready_mounted_count": counter.get("ready_mounted_count", 0),
            "unready_mounted_count": counter.get("unready_mounted_count", 0),
            "mounted_modules": mounted_by_slot.get(slot, []),
        }
        for slot, counter in sorted(counts.items())
    }


def _mount_reason(in_loadout: bool, allow_reason: str, weight_reason: str) -> str:
    if not in_loadout:
        return "detached_from_loadout"
    if allow_reason != "allowed":
        return allow_reason
    if weight_reason != "allowed":
        return weight_reason
    return "not_mounted"


def _compact_module(module: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": module["id"],
        "slot": module["slot"],
        "weight": module["weight"],
        "readiness": {
            "state": module["readiness"]["state"],
            "reason": module["readiness"]["reason"],
        },
        "mount_reason": module["mount_reason"],
    }


def _compact_recommendation(recommendation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not recommendation:
        return None
    rec = recommendation.get("recommendation")
    if not isinstance(rec, dict):
        return None
    return {
        "loadout": rec.get("loadout"),
        "depth": rec.get("depth"),
        "follow_results": rec.get("follow_results"),
        "max_requests": rec.get("max_requests"),
        "query_variants": list(rec.get("query_variants") or []),
        "reasons": list(rec.get("reasons") or []),
        "mount_decision": rec.get("mount_decision") if isinstance(rec.get("mount_decision"), dict) else {},
        "suggested_command": rec.get("suggested_command"),
    }


def _mount_decision(
    *,
    request: ResearchRequest,
    mounted: list[dict[str, Any]],
    heavy_mounted: list[dict[str, Any]],
    readiness_blockers: list[dict[str, Any]],
    recommendation: dict[str, Any] | None,
) -> dict[str, Any]:
    mounted_ids = {str(module.get("id") or "") for module in mounted}
    recommendation_decision: dict[str, Any] = {}
    if isinstance(recommendation, dict):
        rec = recommendation.get("recommendation")
        if isinstance(rec, dict) and isinstance(rec.get("mount_decision"), dict):
            recommendation_decision = dict(rec["mount_decision"])
    browser_mounted = any(module_id.startswith("browser.") for module_id in mounted_ids)
    credentialed_social_mounted = bool({"platform.reddit.oauth", "platform.threads"} & mounted_ids)
    public_social_mounted = bool({"platform.reddit", "platform.threads.public"} & mounted_ids)
    return {
        "source": "recommendation" if recommendation_decision else "explicit_loadout",
        "selected_loadout": request.loadout,
        "mode": recommendation_decision.get("mode") or _decision_mode(request.loadout),
        "browser_hardpoints": "mounted" if browser_mounted else "detached",
        "credentialed_social": "mounted" if credentialed_social_mounted else "detached",
        "public_social_fallbacks": "mounted" if public_social_mounted else "detached",
        "adaptive_public_reader": "mounted" if "read.insane_fetch" in mounted_ids else "detached",
        "heavy_modules": "mounted" if heavy_mounted else "detached",
        "operator_approval_recommended": browser_mounted or request.loadout == "full",
        "readiness": "blocked_by_config" if readiness_blockers else "ready_or_optional",
        "readiness_blockers": [str(item.get("id") or "") for item in readiness_blockers[:8]],
        "next_escalation": recommendation_decision.get("next_escalation") or _next_escalation(request.loadout),
        "core_boundary": "preflight_does_not_run_network_or_browser; it only previews detachable mounts",
    }


def _decision_mode(loadout: str) -> str:
    if loadout == "safe":
        return "light_core_only"
    if loadout == "public-web":
        return "adaptive_public_reader_without_browser"
    if loadout == "social":
        return "social_cartridges_without_browser"
    if loadout == "browser":
        return "browser_hardpoint_required"
    if loadout == "full":
        return "operator_approved_full_mount"
    return "unknown"


def _next_escalation(loadout: str) -> str:
    order = ["safe", "public-web", "social", "browser", "full"]
    try:
        return order[order.index(loadout) + 1]
    except (ValueError, IndexError):
        return ""


def _missing_env(readiness: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    checks = readiness.get("checks")
    if not isinstance(checks, list):
        return missing
    for check in checks:
        if not isinstance(check, dict):
            continue
        missing.extend(str(value) for value in check.get("missing_env") or [])
    return _dedupe(missing)


def _accepted_env_sets(readiness: dict[str, Any]) -> list[list[str]]:
    accepted: list[list[str]] = []
    checks = readiness.get("checks")
    if not isinstance(checks, list):
        return accepted
    for check in checks:
        if not isinstance(check, dict):
            continue
        for group in check.get("accepted_env_sets") or []:
            if isinstance(group, list):
                accepted.append([str(value) for value in group])
    return accepted


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
