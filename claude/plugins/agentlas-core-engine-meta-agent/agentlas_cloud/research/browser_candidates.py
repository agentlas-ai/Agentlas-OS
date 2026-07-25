"""Inspectable browser hardpoint candidate catalog.

The catalog is static by design: it records source-backed candidates without
probing package registries, starting browsers, or importing optional SDKs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .armory import module_readiness
from .engine import default_registry
from .registry import AdapterRegistry


BROWSER_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "module_id": "browser.agent_cli",
        "name": "agent-browser",
        "kind": "local_agent_browser_cli",
        "execution_scope": "local_cli_or_selected_provider",
        "data_boundary": "cli_receives_requested_url; provider modes require env credentials outside engine",
        "recommended_for": ["lightest_local_agent_browser", "snapshot_refs", "operator_armed_hardpoint"],
        "not_for": ["unapproved_provider_credentials"],
        "primary_sources": [
            "https://github.com/vercel-labs/agent-browser",
            "https://agent-browser.dev/",
        ],
        "fit": "compact local browser CLI with interactive refs and snapshot output for agents",
        "why_detached": "The binary is useful but optional; missing installs must be nonfatal.",
        "mount_when": "Use as the lightest local agent-browser mount when the CLI is installed or armed.",
        "setup_env": "AGENTLAS_AGENT_BROWSER_BIN",
    },
    {
        "module_id": "browser.playwright_mcp",
        "name": "Playwright MCP",
        "kind": "local_mcp_browser",
        "execution_scope": "local",
        "data_boundary": "local_browser; mcp_client_receives_page_structure",
        "recommended_for": ["js_snapshot", "accessibility_tree", "local_first"],
        "not_for": ["stealth_scale", "login_without_operator_session"],
        "primary_sources": [
            "https://github.com/microsoft/playwright-mcp",
            "https://playwright.dev/docs/getting-started-mcp",
        ],
        "fit": "structured accessibility snapshots through MCP for JS-heavy pages",
        "why_detached": "MCP server and browser dependencies are too heavy for the research core.",
        "mount_when": "Use for local browser snapshots when an MCP client/runtime is already approved.",
        "setup_env": "AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD",
    },
    {
        "module_id": "browser.browser_use",
        "name": "Browser Use",
        "kind": "agentic_browser_harness",
        "execution_scope": "local_or_cloud",
        "data_boundary": "agent_harness_receives_task_and_page_state; cloud_mode_requires_provider_account",
        "recommended_for": ["multi_step_actions", "recovery_loops", "hosted_scale"],
        "not_for": ["default_build_research", "secret_free_core"],
        "primary_sources": [
            "https://github.com/browser-use/browser-use",
            "https://browser-use.com/",
        ],
        "fit": "agentic browser harness with recovery loops and local or hosted browser infrastructure",
        "why_detached": "Runtime, model, stealth, and hosted-browser choices belong outside the core.",
        "mount_when": "Use when an agent needs multi-step browser operation beyond a static snapshot.",
        "setup_env": "AGENTLAS_BROWSER_USE_SNAPSHOT_CMD",
    },
    {
        "module_id": "browser.stagehand",
        "name": "Stagehand",
        "kind": "code_first_agent_browser",
        "execution_scope": "local_or_browserbase",
        "data_boundary": "bridge_command_receives_url; sdk_provider_tokens_stay_outside_engine",
        "recommended_for": ["structured_extract", "selector_brittle_pages", "repeatable_workflows"],
        "not_for": ["default_build_research", "tokenless_core"],
        "primary_sources": [
            "https://github.com/browserbase/stagehand",
            "https://docs.stagehand.dev/v3/first-steps/introduction",
        ],
        "fit": "natural-language plus code browser automation for resilient extraction",
        "why_detached": "AI browser SDKs and provider configuration should stay behind an explicit command bridge.",
        "mount_when": "Use for structured extraction or actions where selectors are brittle.",
        "setup_env": "AGENTLAS_STAGEHAND_SNAPSHOT_CMD",
    },
    {
        "module_id": "browser.steel",
        "name": "Steel Browser",
        "kind": "remote_browser_api",
        "execution_scope": "cloud_or_self_hosted_browser_api",
        "data_boundary": "remote_browser_provider_receives_requested_url_and_session_state",
        "recommended_for": ["isolated_remote_sessions", "anti_bot_public_pages", "scale"],
        "not_for": ["local_only_privacy", "default_build_research"],
        "primary_sources": [
            "https://github.com/steel-dev/steel-browser",
            "https://steel.dev/",
        ],
        "fit": "remote browser/session infrastructure for AI agents and automation",
        "why_detached": "Cloud browser sessions, provider tokens, and proxy policy need operator approval.",
        "mount_when": "Use when isolated hosted browser sessions are worth the extra weight.",
        "setup_env": "AGENTLAS_STEEL_SNAPSHOT_CMD",
    },
    {
        "module_id": "browser.hyperagent",
        "name": "HyperAgent / Hyperbrowser",
        "kind": "cloud_agent_browser",
        "execution_scope": "local_or_hyperbrowser_cloud",
        "data_boundary": "agent_command_receives_task; cloud_mode requires provider key outside engine",
        "recommended_for": ["playwright_plus_ai", "schema_extract", "cloud_browser_scale"],
        "not_for": ["default_build_research", "unknown_trust_boundary"],
        "primary_sources": [
            "https://github.com/hyperbrowserai/HyperAgent",
            "https://www.hyperbrowser.ai/",
        ],
        "fit": "AI-agent browser sessions backed by a browser infrastructure provider",
        "why_detached": "Provider credentials and hosted execution should not be part of the default engine.",
        "mount_when": "Use for approved cloud-browser tasks that need agent-style operation.",
        "setup_env": "AGENTLAS_HYPERAGENT_SNAPSHOT_CMD",
    },
    {
        "module_id": "browser.browseros",
        "name": "BrowserOS",
        "kind": "local_agentic_browser_app",
        "execution_scope": "local_desktop_app",
        "data_boundary": "desktop_browser_profile_and_agent_runtime; command bridge receives requested URL only",
        "recommended_for": ["local_first_privacy", "persistent_manual_agent_browser", "future_bridge_candidate"],
        "not_for": ["unapproved_desktop_profile", "default_build_research"],
        "primary_sources": [
            "https://github.com/browseros-ai/BrowserOS",
            "https://docs.browseros.com/",
        ],
        "fit": "open-source Chromium fork with agent integrations; mount through a local snapshot command when an operator approves the desktop profile boundary",
        "why_detached": "Desktop browser/app state and profile policy are too heavy for default research runs.",
        "mount_when": "Use for approved local-first BrowserOS snapshot flows where persistent browser context is useful.",
        "setup_env": "AGENTLAS_BROWSEROS_SNAPSHOT_CMD",
    },
)


def run_research_browser_candidates(
    *,
    module_id: str = "",
    query: str = "",
    home: Path | str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Return browser candidate fit/readiness without running commands."""

    selected_registry = registry or default_registry(home=home)
    adapters_by_id = {
        adapter.module_id: adapter
        for adapter in selected_registry.adapters
        if getattr(adapter.manifest, "slot", "") == "browser"
    }
    candidates = []
    for candidate in BROWSER_CANDIDATES:
        if module_id and candidate["module_id"] != module_id:
            continue
        adapter = adapters_by_id.get(candidate["module_id"])
        payload = dict(candidate)
        payload["slot"] = "browser"
        payload["weight"] = getattr(adapter, "weight", "browser_heavy") if adapter else "browser_heavy"
        payload["registered"] = adapter is not None
        payload["readiness"] = module_readiness(adapter) if adapter else {"state": "not_registered", "reason": "adapter_missing"}
        payload["operator_approval_required"] = (
            payload["module_id"] != "browser.agent_cli"
            and (
                payload["execution_scope"] != "local"
                or payload["module_id"] in {"browser.browser_use", "browser.steel", "browser.hyperagent", "browser.browseros"}
            )
        )
        payload["mount_plan"] = _mount_plan(payload)
        candidates.append(payload)

    recommendation = _recommend_browser_candidate(query=query, candidates=candidates)
    return {
        "schema": "agentlas.research.browser_candidates.v0",
        "status": "ok" if candidates else "not_found",
        "module": module_id or "all",
        "query": query,
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "home": str(home) if home else "",
        "selection_rule": "core stays browser-free; mount one browser hardpoint only when the task needs JS-heavy or interactive evidence",
        "recommendation": recommendation,
        "candidates": candidates,
    }


def _recommend_browser_candidate(*, query: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    compact = " ".join((query or "").split()).strip()
    if not candidates:
        return {"status": "not_found", "reason": "no_browser_candidates"}
    if not compact:
        return {
            "status": "not_requested",
            "reason": "pass --query to get a non-executing hardpoint recommendation",
            "default_boundary": "use safe/public-web first; browser hardpoints stay detached",
        }
    signals, selection_source = _judged_signals(compact)
    if selection_source == "unavailable":
        # No connected model → do NOT keyword-guess a browser hardpoint. Leave
        # the browser mount undecided and surface the connect-a-model outcome.
        return {
            "status": "needs_model",
            "query": compact,
            "reason": "no_connected_model_cannot_judge_browser_need",
            "preferred_loadout": "safe",
            "mount_browser": False,
            "selection_source": "unavailable",
            "model_status": "unavailable",
            "message": _NO_MODEL_MESSAGE_EN,
            "message_ko": _NO_MODEL_MESSAGE_KO,
        }

    order = _preferred_order(signals)
    by_id = {candidate["module_id"]: candidate for candidate in candidates}
    for module_id in order:
        candidate = by_id.get(module_id)
        if candidate:
            ready = bool(candidate.get("registered") and candidate.get("readiness", {}).get("state") == "ready")
            payload = _recommendation_payload(candidate, compact, signals, ready=ready)
            payload["selection_source"] = selection_source
            return payload
    return {
        "status": "no_match",
        "query": compact,
        "reason": "query_did_not_require_browser_hardpoint",
        "preferred_loadout": "public-web" if signals["public_web"] else "safe",
        "mount_browser": False,
        "selection_source": selection_source,
    }


def _recommendation_payload(candidate: dict[str, Any], query: str, signals: dict[str, bool], *, ready: bool) -> dict[str, Any]:
    mount_plan = candidate.get("mount_plan", {}) if isinstance(candidate.get("mount_plan"), dict) else {}
    return {
        "status": "ready" if ready else "needs_setup",
        "query": query,
        "module_id": candidate["module_id"],
        "name": candidate["name"],
        "kind": candidate["kind"],
        "reason": _recommendation_reason(candidate, signals),
        "preferred_loadout": "browser",
        "mount_browser": True,
        "readiness": candidate.get("readiness", {}),
        "setup_env": candidate.get("setup_env", ""),
        "setup_commands": list(mount_plan.get("setup_commands") or []),
        "check_command": str(mount_plan.get("check_command") or ""),
        "proof_id": str(mount_plan.get("proof_id") or ""),
        "operator_approval_required": candidate.get("operator_approval_required", True),
        "data_boundary": candidate.get("data_boundary", ""),
    }


# Shown when no model is connected and browser need cannot be judged by meaning.
_NO_MODEL_MESSAGE_EN = "No LLM is connected, so I can't decide this. Connect a model in settings."
_NO_MODEL_MESSAGE_KO = "LLM(모델)이 연결되어 있지 않아 이 판단을 할 수 없어요. 설정에서 모델을 연결해 주세요."

# Keyword tuples are REFERENCE HINTS for the connected model only. There is no
# keyword browser verdict: with no model connected the browser need is left
# undecided (no auto-mount).
BROWSER_SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "local_first": ("local", "로컬", "privacy", "private", "프라이버시", "내 맥"),
    "interactive": ("click", "fill", "form", "login", "로그인", "클릭", "입력", "멀티스텝", "multi-step"),
    "structured": ("extract", "schema", "table", "structured", "구조화", "추출", "테이블"),
    "scale_or_stealth": ("scale", "stealth", "captcha", "anti-bot", "차단", "캡차", "스텔스", "대량"),
    "snapshot": (
        "browser",
        "agent-browser",
        "headless",
        "chromium",
        "snapshot",
        "screenshot",
        "accessibility",
        "js-heavy",
        "dynamic",
        "스냅샷",
        "동적",
        "브라우저",
    ),
    "public_web": ("403", "blocked", "waf", "rss", "public page", "공개 페이지"),
}


def _judged_signals(query: str) -> tuple[dict[str, bool], str]:
    """The connected model decides which browser-need traits the task has.

    The keyword tuples are hints only. Returns (signals, source) where source
    is ``"model"`` or ``"unavailable"``. There is no keyword verdict: with no
    model connected every trait is undecided (all False) and labeled
    ``"unavailable"`` so no browser hardpoint is auto-selected.
    """

    none_signals = {name: False for name in BROWSER_SIGNAL_KEYWORDS}
    try:
        from ..judgment import has_judgment_runner, judge_labels
    except Exception:  # pragma: no cover - judgment module is optional at import time
        return none_signals, "unavailable"
    if not has_judgment_runner():
        return none_signals, "unavailable"
    picked, source = judge_labels(
        kind="research-browser-signals",
        question="Which of these browser-need traits does this research task genuinely have?",
        labels=tuple(BROWSER_SIGNAL_KEYWORDS),
        text=query,
        hints={name: list(terms) for name, terms in BROWSER_SIGNAL_KEYWORDS.items()},
        guidance=(
            "local_first = the browser must run locally/privately; interactive = the task "
            "clicks, fills forms, or uses a login; structured = schema/table extraction; "
            "scale_or_stealth = anti-bot or high-volume browsing; snapshot = a rendered "
            "JS-heavy page snapshot is needed; public_web = blocked public pages best served "
            "without a browser. Return an empty list when no real browser evidence is needed."
        ),
        fallback=(),
        multi=True,
    )
    if source != "model":
        return none_signals, "unavailable"
    return {name: name in picked for name in BROWSER_SIGNAL_KEYWORDS}, "model"


def _preferred_order(signals: dict[str, bool]) -> list[str]:
    agent_browser_first = ["browser.agent_cli"]
    if signals["local_first"]:
        return agent_browser_first + ["browser.playwright_mcp", "browser.browseros", "browser.stagehand"]
    if signals["scale_or_stealth"]:
        return agent_browser_first + ["browser.steel", "browser.hyperagent", "browser.browser_use"]
    if signals["structured"]:
        return agent_browser_first + ["browser.stagehand", "browser.hyperagent", "browser.browser_use", "browser.playwright_mcp"]
    if signals["interactive"]:
        return agent_browser_first + ["browser.browser_use", "browser.stagehand", "browser.hyperagent"]
    if signals["snapshot"]:
        return agent_browser_first + ["browser.playwright_mcp", "browser.stagehand"]
    return []


def _recommendation_reason(candidate: dict[str, Any], signals: dict[str, bool]) -> str:
    if candidate.get("module_id") == "browser.agent_cli" and any(
        signals[key] for key in ("local_first", "scale_or_stealth", "structured", "interactive", "snapshot")
    ):
        return "agent_browser_first_for_browser_task"
    if signals["local_first"]:
        return "local_first_browser_requested"
    if signals["scale_or_stealth"]:
        return "scale_or_anti_bot_browser_requested"
    if signals["structured"]:
        return "structured_browser_extraction_requested"
    if signals["interactive"]:
        return "interactive_browser_actions_requested"
    if signals["snapshot"]:
        return "browser_snapshot_requested"
    return f"candidate_fit:{candidate.get('kind')}"


def _mount_plan(candidate: dict[str, Any]) -> dict[str, Any]:
    module_id = str(candidate.get("module_id") or "")
    registered = bool(candidate.get("registered"))
    setup_env = str(candidate.get("setup_env") or "")
    check_command = (
        f"bin/hephaestus research bridge-check --module {module_id} --url https://example.com"
        if registered
        else ""
    )
    setup_commands: list[str] = []
    if module_id == "browser.agent_cli":
        setup_commands = [
            "bin/hephaestus research hardpoints --arm browser.agent_cli --recipe npx-agent-browser",
            "AGENTLAS_AGENT_BROWSER_BIN='npx -y agent-browser' bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com",
        ]
    elif registered and setup_env:
        setup_commands = [
            f"{setup_env}='<snapshot command with {{url}}>' {check_command}",
        ]
    return {
        "status": "bridge_ready" if registered else "candidate_only",
        "proof_id": "browser_hardpoint_live_check" if registered else "",
        "check_command": check_command,
        "setup_commands": setup_commands,
        "ready_when": "readiness.state == ready and bridge-check returns status ok" if registered else "adapter registered with a packet-safe command bridge",
        "commands_will_run": False,
        "network_will_run": False,
    }
