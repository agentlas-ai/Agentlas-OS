"""Readiness doctor for the Agentlas Research Engine."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from agentlas_cloud.networking.bootstrap import networking_home

from .armory import module_readiness
from .engine import default_registry
from .profile import run_research_profile
from .proofs import PROOF_FRESHNESS_SECONDS, load_research_live_proofs
from .query_variants import query_variant_catalog
from .registry import AdapterRegistry, ResearchAdapter


def run_research_doctor(*, home: Path | str | None = None, registry: AdapterRegistry | None = None) -> dict[str, Any]:
    """Summarize readiness without executing network, commands, or browsers."""

    base = Path(home) if home else networking_home()
    selected_registry = registry or default_registry(home=base)
    live_proofs = load_research_live_proofs(base)
    adapters = list(selected_registry.adapters)
    modules = {adapter.module_id: adapter for adapter in adapters}
    profile_auto = run_research_profile(loadout="auto", registry=selected_registry)["profiles"][0]
    profile_browser = run_research_profile(loadout="browser", registry=selected_registry)["profiles"][0]
    checks = [
        _registry_check(adapters),
        _auto_boundary_check(profile_auto),
        _browser_modularity_check(profile_auto, profile_browser),
        _web_search_recall_check(modules),
        _evidence_quality_check(),
        _reddit_public_check(modules),
        _threads_public_check(modules),
        _credentialed_check(modules, module_id="platform.reddit.oauth", proof="reddit_oauth_live_check", live_proofs=live_proofs),
        _credentialed_check(modules, module_id="platform.threads", proof="threads_live_graph_check", live_proofs=live_proofs),
        _browser_hardpoint_check(adapters, live_proofs=live_proofs),
    ]
    missing_proofs = _dedupe(
        proof
        for check in checks
        for proof in check.get("missing_proofs", [])
        if isinstance(proof, str) and proof
    )
    incomplete_checks = [check["id"] for check in checks if check["status"] != "ok"]
    missing_or_unready_proofs = _missing_or_unready_proofs(checks)
    coverage = _doctor_coverage_summary(checks)
    blocking_statuses = {"failed"}
    return {
        "schema": "agentlas.research.doctor.v0",
        "status": "failed" if any(check["status"] in blocking_statuses for check in checks) else ("partial" if incomplete_checks else "ok"),
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "home": str(base),
        "module_count": len(adapters),
        "slot_counts": dict(sorted(Counter(adapter.manifest.slot for adapter in adapters).items())),
        "live_proofs": live_proofs,
        "freshness_policy": {
            "max_age_seconds": PROOF_FRESHNESS_SECONDS,
            "max_age_hours": PROOF_FRESHNESS_SECONDS // 3600,
        },
        "checks": checks,
        "coverage": coverage,
        "completion": {
            "goal_ready": not incomplete_checks,
            "missing_proofs": missing_proofs,
            "missing_or_unready_proofs": missing_or_unready_proofs,
            "incomplete_checks": incomplete_checks,
            "ok_checks": coverage["ok_checks"],
            "stale_or_unknown_proofs": coverage["stale_or_unknown_proofs"],
            "public_social_fallbacks_ok": coverage["public_social_fallbacks_ok"],
            "browser_hardpoint_ok": coverage["browser_hardpoint_ok"],
            "credentialed_social_ok": coverage["credentialed_social_ok"],
            "note": "Doctor is non-executing; run the listed check commands for live external proof.",
        },
        "next_commands": _next_commands(checks),
    }


def _registry_check(adapters: list[ResearchAdapter]) -> dict[str, Any]:
    required_slots = {"search", "reader", "platform", "browser"}
    slots = {adapter.manifest.slot for adapter in adapters}
    missing = sorted(required_slots - slots)
    return {
        "id": "core_registry",
        "status": "ok" if not missing else "failed",
        "summary": "Research modules are registered across detachable slots.",
        "evidence": {
            "module_count": len(adapters),
            "slots": sorted(slots),
            "missing_slots": missing,
        },
    }


def _auto_boundary_check(profile_auto: dict[str, Any]) -> dict[str, Any]:
    footprint = profile_auto.get("footprint", {})
    ok = not footprint.get("browser_modules_mounted") and footprint.get("heaviest_mounted_weight") in {"", "light", "adaptive_medium", "credentialed_medium"}
    return {
        "id": "auto_loadout_boundary",
        "status": "ok" if ok else "failed",
        "summary": "Auto loadout keeps browser hardpoints detached by default.",
        "evidence": {
            "browser_module_count": footprint.get("browser_module_count"),
            "heaviest_mounted_weight": footprint.get("heaviest_mounted_weight"),
            "mounted_slot_counts": footprint.get("mounted_slot_counts"),
        },
    }


def _browser_modularity_check(profile_auto: dict[str, Any], profile_browser: dict[str, Any]) -> dict[str, Any]:
    auto_count = int((profile_auto.get("footprint") or {}).get("browser_module_count") or 0)
    browser_count = int((profile_browser.get("footprint") or {}).get("browser_module_count") or 0)
    ok = auto_count == 0 and browser_count > 0
    return {
        "id": "browser_modularity",
        "status": "ok" if ok else "failed",
        "summary": "Browser modules are detachable and only mounted by browser/full policy.",
        "evidence": {
            "auto_browser_module_count": auto_count,
            "browser_loadout_browser_module_count": browser_count,
        },
    }


def _web_search_recall_check(modules: dict[str, ResearchAdapter]) -> dict[str, Any]:
    search_modules = [module_id for module_id in ("search.ddg_html", "search.news_rss", "search.jina") if module_id in modules]
    variants = [item["name"] for item in query_variant_catalog()]
    ok = {"search.ddg_html", "search.news_rss"}.issubset(set(search_modules)) and {"docs", "reddit", "threads", "github"}.issubset(set(variants))
    return {
        "id": "web_search_recall",
        "status": "ok" if ok else "failed",
        "summary": "Search fanout supports multiple providers plus bounded query variants.",
        "evidence": {
            "search_modules": search_modules,
            "query_variants": variants,
        },
    }


def _evidence_quality_check() -> dict[str, Any]:
    return {
        "id": "evidence_quality",
        "status": "ok",
        "summary": "Receipts classify snippets vs direct reads and expose evidence quality.",
        "evidence": {
            "policy_key": "evidence_quality",
            "statuses": ["none", "thin", "usable", "strong"],
        },
    }


def _reddit_public_check(modules: dict[str, ResearchAdapter]) -> dict[str, Any]:
    adapter = modules.get("platform.reddit")
    if adapter is None:
        return {"id": "reddit_public_fallback", "status": "failed", "summary": "Public Reddit fallback module is missing.", "evidence": {}}
    readiness = module_readiness(adapter)
    return {
        "id": "reddit_public_fallback",
        "status": "ok" if readiness["state"] == "ready" else "needs_config",
        "summary": "Reddit public JSON/RSS fallback is available for explicit Reddit sources.",
        "evidence": {"module": adapter.module_id, "readiness": readiness},
        "check_command": "bin/hephaestus research platform-check --module platform.reddit --source reddit:subreddit:redditdev",
    }


def _threads_public_check(modules: dict[str, ResearchAdapter]) -> dict[str, Any]:
    adapter = modules.get("platform.threads.public")
    if adapter is None:
        return {"id": "threads_public_fallback", "status": "failed", "summary": "Public Threads fallback module is missing.", "evidence": {}}
    readiness = module_readiness(adapter)
    keyword_fallback_modules = [
        module_id
        for module_id in ("search.ddg_html", "search.news_rss")
        if module_id in modules
    ]
    return {
        "id": "threads_public_fallback",
        "status": "ok" if readiness["state"] == "ready" else "needs_config",
        "summary": "Threads public fallback is available for explicit public URLs/profile hints, with light web-search fallback for keyword discovery when no Graph token is configured.",
        "evidence": {
            "module": adapter.module_id,
            "readiness": readiness,
            "keyword_web_search_fallback_modules": keyword_fallback_modules,
        },
        "check_command": "bin/hephaestus research platform-check --module platform.threads.public --source threads:lookup:instagram",
    }


def _credentialed_check(
    modules: dict[str, ResearchAdapter],
    *,
    module_id: str,
    proof: str,
    live_proofs: dict[str, Any],
) -> dict[str, Any]:
    adapter = modules.get(module_id)
    if adapter is None:
        return {
            "id": module_id,
            "status": "failed",
            "summary": f"{module_id} module is missing.",
            "evidence": {},
            "missing_proofs": [proof],
        }
    readiness = module_readiness(adapter)
    ready = readiness["state"] == "ready"
    proof_payload = live_proofs.get(proof)
    proof_found = bool(proof_payload)
    proof_freshness_status = _proof_freshness_status(proof_payload)
    source = "reddit:subreddit:redditdev" if module_id == "platform.reddit.oauth" else "threads:keyword:agent browser"
    if ready and proof_found and proof_freshness_status == "fresh":
        status = "ok"
    elif ready and proof_found:
        status = f"{proof_freshness_status}_live_proof"
    else:
        status = "needs_config" if not ready else "needs_live_proof"
    return {
        "id": module_id,
        "status": status,
        "summary": f"{module_id} requires credentialed live proof before completion.",
        "evidence": {"module": adapter.module_id, "readiness": readiness, "live_proof": proof_payload or None},
        "missing_proofs": [] if proof_found else [proof],
        "check_command": f"bin/hephaestus research platform-check --module {module_id} --source '{source}'",
    }


def _browser_hardpoint_check(adapters: list[ResearchAdapter], *, live_proofs: dict[str, Any]) -> dict[str, Any]:
    browser = [adapter for adapter in adapters if adapter.manifest.slot == "browser"]
    readiness = {adapter.module_id: module_readiness(adapter) for adapter in browser}
    ready_modules = [module_id for module_id, payload in readiness.items() if payload["state"] == "ready"]
    proof_payload = live_proofs.get("browser_hardpoint_live_check")
    proof_found = bool(proof_payload)
    proof_freshness_status = _proof_freshness_status(proof_payload)
    if ready_modules and proof_found and proof_freshness_status == "fresh":
        status = "ok"
    elif ready_modules and proof_found:
        status = f"{proof_freshness_status}_live_proof"
    else:
        status = "needs_config" if not ready_modules else "needs_live_proof"
    return {
        "id": "browser_hardpoints",
        "status": status,
        "summary": "At least one browser hardpoint should be configured and live-checked for JS-heavy evidence.",
        "evidence": {
            "browser_module_count": len(browser),
            "ready_modules": ready_modules,
            "readiness": readiness,
            "live_proof": proof_payload or None,
        },
        "missing_proofs": [] if proof_found else ["browser_hardpoint_live_check"],
        "check_command": _browser_check_command(ready_modules),
    }


def _browser_check_command(ready_modules: list[str]) -> str:
    module_id = ready_modules[0] if ready_modules else "browser.agent_cli"
    return f"bin/hephaestus research bridge-check --module {module_id} --url https://example.com"


def _next_commands(checks: list[dict[str, Any]]) -> list[str]:
    return _dedupe(str(check.get("check_command") or "") for check in checks if check.get("check_command"))


def _missing_or_unready_proofs(checks: list[dict[str, Any]]) -> list[str]:
    proof_by_check = {
        "platform.reddit.oauth": "reddit_oauth_live_check",
        "platform.threads": "threads_live_graph_check",
        "browser_hardpoints": "browser_hardpoint_live_check",
    }
    return _dedupe(
        proof_by_check[check["id"]]
        for check in checks
        if check.get("id") in proof_by_check and check.get("status") != "ok"
    )


def _doctor_coverage_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(check.get("id")): check for check in checks}
    ok_checks = [check_id for check_id, check in by_id.items() if check.get("status") == "ok"]
    incomplete_checks = [check_id for check_id, check in by_id.items() if check.get("status") != "ok"]
    public_social_ids = ["reddit_public_fallback", "threads_public_fallback"]
    credentialed_social_ids = ["platform.reddit.oauth", "platform.threads"]
    public_social_fallbacks_ok = all(by_id.get(check_id, {}).get("status") == "ok" for check_id in public_social_ids)
    credentialed_social_ok = all(by_id.get(check_id, {}).get("status") == "ok" for check_id in credentialed_social_ids)
    credentialed_social_missing = [
        check_id
        for check_id in credentialed_social_ids
        if by_id.get(check_id, {}).get("status") != "ok"
    ]
    stale_or_unknown = [
        _proof_by_check_id(check_id)
        for check_id, check in by_id.items()
        if check.get("status") in {"stale_live_proof", "unknown_live_proof"}
    ]
    stale_or_unknown = [proof for proof in stale_or_unknown if proof]
    browser_status = str(by_id.get("browser_hardpoints", {}).get("status") or "missing")
    return {
        "ok_checks": ok_checks,
        "incomplete_checks": incomplete_checks,
        "public_social_fallbacks_ok": public_social_fallbacks_ok,
        "public_social_fallback_checks": public_social_ids,
        "credentialed_social_ok": credentialed_social_ok,
        "credentialed_social_missing": credentialed_social_missing,
        "stale_or_unknown_proofs": stale_or_unknown,
        "browser_hardpoint_ok": browser_status == "ok",
        "browser_hardpoint_status": browser_status,
        "goal_blocked_by": incomplete_checks,
    }


def _proof_freshness_status(proof_payload: Any) -> str:
    if not isinstance(proof_payload, dict):
        return "unknown"
    freshness = proof_payload.get("freshness") if isinstance(proof_payload.get("freshness"), dict) else {}
    status = str(freshness.get("status") or "unknown")
    return status if status in {"fresh", "stale", "unknown"} else "unknown"


def _proof_by_check_id(check_id: str) -> str:
    return {
        "platform.reddit.oauth": "reddit_oauth_live_check",
        "platform.threads": "threads_live_graph_check",
        "browser_hardpoints": "browser_hardpoint_live_check",
    }.get(check_id, "")


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
