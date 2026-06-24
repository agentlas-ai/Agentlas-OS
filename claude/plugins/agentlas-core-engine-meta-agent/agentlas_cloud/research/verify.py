"""Live proof runner for the Agentlas Research Engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentlas_cloud.networking.bootstrap import networking_home

from .armory import module_readiness
from .bridge_contracts import run_research_bridge_check
from .engine import default_registry
from .platform_contracts import run_research_platform_check
from .proofs import run_research_proofs
from .registry import ResearchAdapter


VERIFY_TARGETS: tuple[dict[str, Any], ...] = (
    {
        "id": "reddit_public_live_check",
        "kind": "public",
        "module_id": "platform.reddit",
        "source": "reddit:subreddit:redditdev",
        "runner": "platform",
    },
    {
        "id": "threads_public_live_check",
        "kind": "public",
        "module_id": "platform.threads.public",
        "source": "threads:lookup:instagram",
        "runner": "platform",
    },
    {
        "id": "browser_hardpoint_live_check",
        "kind": "browser",
        "module_id": "browser.*",
        "source": "https://example.com",
        "runner": "browser",
    },
    {
        "id": "reddit_oauth_live_check",
        "kind": "credentialed",
        "module_id": "platform.reddit.oauth",
        "source": "reddit:subreddit:redditdev",
        "runner": "platform",
    },
    {
        "id": "threads_live_graph_check",
        "kind": "credentialed",
        "module_id": "platform.threads",
        "source": "threads:keyword:agent browser",
        "runner": "platform",
    },
)


def run_research_verify(
    *,
    home: Path | str | None = None,
    include_public: bool = True,
    include_browser: bool = True,
    include_credentialed: bool = True,
    browser_url: str = "https://example.com",
) -> dict[str, Any]:
    """Run selected live checks and return the updated proof state."""

    base = Path(home) if home else networking_home()
    registry = default_registry(home=base)
    adapters = {adapter.module_id: adapter for adapter in registry.adapters}
    checks = []
    for target in VERIFY_TARGETS:
        if target["kind"] == "public" and not include_public:
            checks.append(_skipped(target, "excluded_by_flag", adapters))
            continue
        if target["kind"] == "browser" and not include_browser:
            checks.append(_skipped(target, "excluded_by_flag", adapters))
            continue
        if target["kind"] == "credentialed" and not include_credentialed:
            checks.append(_skipped(target, "excluded_by_flag", adapters))
            continue
        checks.append(_run_target(target, adapters=adapters, base=base, browser_url=browser_url))

    proof_state = run_research_proofs(home=base, limit=20, registry=registry)
    check_failed = any(item["status"] not in {"ok", "skipped_not_ready", "skipped"} for item in checks)
    goal_ready = bool((proof_state.get("completion") or {}).get("goal_ready"))
    return {
        "schema": "agentlas.research.verify.v0",
        "status": "failed" if check_failed else ("ok" if goal_ready else "partial"),
        "commands_will_run": True,
        "network_will_run": True,
        "credentials_exposed_to_model": False,
        "home": str(base),
        "checks": checks,
        "proofs": {
            "required_proofs": proof_state.get("required_proofs", []),
            "public_fallback_proofs": proof_state.get("public_fallback_proofs", []),
            "completion": proof_state.get("completion", {}),
        },
    }


def _run_target(
    target: dict[str, Any],
    *,
    adapters: dict[str, ResearchAdapter],
    base: Path,
    browser_url: str,
) -> dict[str, Any]:
    if target["runner"] == "browser":
        return _run_browser_target(target, adapters=adapters, base=base, browser_url=browser_url)

    adapter = adapters.get(str(target["module_id"]))
    if adapter is None:
        return {**_target_summary(target), "status": "not_found", "readiness": {"state": "missing"}, "receipt_id": None}
    readiness = module_readiness(adapter)
    if readiness.get("state") != "ready":
        return {
            **_target_summary(target),
            "status": "skipped_not_ready",
            "readiness": readiness,
            "receipt_id": None,
            "attempts": [],
        }
    result = run_research_platform_check(module_id=str(target["module_id"]), source_hint=str(target["source"]), home=base)
    return {
        **_target_summary(target),
        "status": result.get("status"),
        "readiness": readiness,
        "receipt_id": result.get("receipt_id"),
        "attempts": _attempt_summaries(result.get("attempts", [])),
        "result_count": len(result.get("result_summaries", [])) if isinstance(result.get("result_summaries"), list) else 0,
    }


def _run_browser_target(
    target: dict[str, Any],
    *,
    adapters: dict[str, ResearchAdapter],
    base: Path,
    browser_url: str,
) -> dict[str, Any]:
    readiness = _browser_readiness(adapters)
    selected_module = readiness.get("selected_module")
    if not selected_module:
        return {
            **_target_summary(target, source=browser_url),
            "status": "skipped_not_ready",
            "readiness": readiness,
            "receipt_id": None,
            "attempts": [],
        }
    result = run_research_bridge_check(module_id=str(selected_module), url=browser_url, home=base)
    return {
        **_target_summary(target, source=browser_url),
        "selected_module_id": selected_module,
        "status": result.get("status"),
        "readiness": readiness,
        "receipt_id": result.get("receipt_id"),
        "attempts": _attempt_summaries(result.get("attempts", [])),
        "result_count": len(result.get("result_summaries", [])) if isinstance(result.get("result_summaries"), list) else 0,
    }


def _skipped(target: dict[str, Any], reason: str, adapters: dict[str, ResearchAdapter]) -> dict[str, Any]:
    adapter = adapters.get(str(target["module_id"]))
    readiness = _browser_readiness(adapters) if target.get("runner") == "browser" else module_readiness(adapter) if adapter else {"state": "missing"}
    return {
        **_target_summary(target),
        "status": "skipped",
        "reason": reason,
        "readiness": readiness,
        "receipt_id": None,
        "attempts": [],
    }


def _browser_readiness(adapters: dict[str, ResearchAdapter]) -> dict[str, Any]:
    readiness = {
        adapter.module_id: module_readiness(adapter)
        for adapter in adapters.values()
        if adapter.manifest.slot == "browser"
    }
    ready_modules = [module_id for module_id, payload in readiness.items() if payload.get("state") == "ready"]
    return {
        "state": "ready" if ready_modules else "missing",
        "selected_module": ready_modules[0] if ready_modules else "",
        "ready_modules": ready_modules,
        "modules": readiness,
    }


def _target_summary(target: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    return {
        "id": target.get("id"),
        "kind": target.get("kind"),
        "module_id": target.get("module_id"),
        "source": source if source is not None else target.get("source"),
    }


def _attempt_summaries(attempts: Any) -> list[dict[str, Any]]:
    if not isinstance(attempts, list):
        return []
    return [
        {
            "module": attempt.get("module"),
            "status": attempt.get("status"),
            "reason": attempt.get("reason"),
        }
        for attempt in attempts[:8]
        if isinstance(attempt, dict)
    ]
