"""Inspectable contracts for optional browser bridge hardpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentlas_cloud.networking.bootstrap import networking_home

from .adapters.agent_browser_cli import AgentBrowserCliAdapter
from .adapters.command_snapshot import CommandSnapshotAdapter
from .armory import module_readiness
from .engine import ResearchEngine, default_registry
from .policy import DEFAULT_MAX_BYTES, classify_url
from .registry import AdapterRegistry, ResearchAdapter


def run_research_bridge_contracts(
    *,
    module_id: str = "",
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Describe browser bridge contracts without running commands or network."""

    selected_registry = registry or default_registry()
    contracts = [
        _contract_for_adapter(adapter)
        for adapter in selected_registry.adapters
        if adapter.manifest.slot == "browser" and (not module_id or adapter.module_id == module_id)
    ]
    return {
        "schema": "agentlas.research.bridge_contracts.v0",
        "status": "ok" if contracts else "not_found",
        "module": module_id or "all",
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "contracts": contracts,
    }


def run_research_bridge_check(
    *,
    module_id: str,
    url: str,
    home: Path | str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Run one browser bridge hardpoint against a URL and summarize the result."""

    base = Path(home) if home else networking_home()
    selected_registry = registry or default_registry(home=base)
    adapter = _find_browser_adapter(selected_registry, module_id)
    if adapter is None:
        return {
            "schema": "agentlas.research.bridge_check.v0",
            "status": "not_found",
            "module": module_id,
            "url": url,
            "commands_will_run": False,
            "network_will_run": False,
            "credentials_exposed_to_model": False,
            "operator_approval_required": True,
            "error": "browser_module_not_found",
        }

    contract = _contract_for_adapter(adapter)
    url_safe, url_reason = classify_url(url)
    command_ready = contract.get("readiness", {}).get("state") == "ready"
    commands_will_run = bool(url_safe and command_ready)
    result = ResearchEngine(registry=AdapterRegistry([adapter]), home=base).run(
        {
            "query": f"Bridge check for {module_id}",
            "intent": "bridge_check",
            "source_hints": [url],
            "allowed_modules": [module_id],
            "max_weight": "browser_heavy",
            "max_cost": {"requests": 1, "seconds": 120, "tokens": 4000},
        }
    )
    return {
        "schema": "agentlas.research.bridge_check.v0",
        "status": _bridge_check_status(result),
        "module": module_id,
        "url": url,
        "command_execution_requested": True,
        "commands_will_run": commands_will_run,
        "network_will_run": commands_will_run,
        "credentials_exposed_to_model": False,
        "operator_approval_required": True,
        "url_policy": {"safe": url_safe, "reason": url_reason},
        "contract": contract,
        "research_status": result.get("status"),
        "receipt_id": result.get("receipt", {}).get("receipt_id"),
        "request_hash": result.get("request", {}).get("request_hash"),
        "attempts": result.get("receipt", {}).get("attempts", []),
        "result_summaries": [_result_summary(item) for item in result.get("results", [])],
        "browser_execution": result.get("receipt", {}).get("policy", {}).get("browser_execution", {}),
    }


def _contract_for_adapter(adapter: ResearchAdapter) -> dict[str, Any]:
    manifest = adapter.manifest.to_dict()
    if isinstance(adapter, CommandSnapshotAdapter):
        return {
            **_base_contract(adapter, manifest),
            "bridge_kind": "snapshot_command",
            "configured_by": {"env": adapter.env_var},
            "argv_rule": "shlex_split_env; replace {url}; append url as final argument when no {url} placeholder is present",
            "input_contract": {
                "url_argument": "public http/https URL after SSRF guard",
                "ssrf_guard": True,
            },
            "output_contract": {
                "accepted_formats": ["plain_text", "json_object"],
                "accepted_content_fields": list(adapter.output_fields),
                "title_field": "title",
                "limits_field": "limits",
                "sample_json": {
                    "title": "Example Browser Snapshot",
                    adapter.output_fields[0]: "- heading \"Example Browser Snapshot\" [ref=e1]\n- text \"Loaded\"",
                    "limits": [adapter.command_label],
                },
                "max_stdout_bytes": adapter.max_bytes,
            },
            "security_boundary": {
                "command_receives_url": True,
                "provider_tokens_stay_outside_engine": True,
                "secrets_are_not_printed_by_contract": True,
            },
        }
    if isinstance(adapter, AgentBrowserCliAdapter):
        return {
            **_base_contract(adapter, manifest),
            "bridge_kind": "agent_browser_cli",
            "configured_by": {
                "env": "AGENTLAS_AGENT_BROWSER_BIN",
                "local_hardpoint_config": "policies/research-hardpoints.json",
                "binary": "agent-browser",
            },
            "argv_rule": "use AGENTLAS_AGENT_BROWSER_BIN when set, otherwise use an approved local hardpoint recipe, otherwise find agent-browser on PATH",
            "setup_recipes": [
                {
                    "name": "installed_binary",
                    "command": "npm install -g agent-browser",
                    "check": "bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com",
                },
                {
                    "name": "npx_agent_browser_hardpoint",
                    "command": "bin/hephaestus research hardpoints --arm browser.agent_cli --recipe npx-agent-browser",
                    "check": "bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com",
                    "note": "Stores an approved local hardpoint recipe; it does not store arbitrary shell strings or credentials.",
                },
                {
                    "name": "npx_one_shot",
                    "env": {"AGENTLAS_AGENT_BROWSER_BIN": "npx -y agent-browser"},
                    "check": "AGENTLAS_AGENT_BROWSER_BIN='npx -y agent-browser' bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com",
                    "note": "Uses npm's npx cache instead of a global install; the bridge still receives only the requested URL.",
                },
            ],
            "input_contract": {
                "url_argument": "public http/https URL after SSRF guard",
                "ssrf_guard": True,
            },
            "command_sequence": [
                "agent-browser open <url>",
                "agent-browser snapshot -i",
                "agent-browser close",
            ],
            "output_contract": {
                "accepted_formats": ["plain_text"],
                "snapshot_source": "stdout from agent-browser snapshot -i",
                "title_detection": "first heading/title-like line, otherwise first non-empty line",
            },
            "security_boundary": {
                "command_receives_url": True,
                "browser_session_closed_after_snapshot": True,
                "secrets_are_not_printed_by_contract": True,
            },
        }
    return {
        **_base_contract(adapter, manifest),
        "bridge_kind": "unknown_browser_adapter",
        "input_contract": {"url_argument": "public http/https URL after SSRF guard", "ssrf_guard": True},
        "output_contract": {},
        "security_boundary": {"secrets_are_not_printed_by_contract": True},
    }


def _find_browser_adapter(registry: AdapterRegistry, module_id: str) -> ResearchAdapter | None:
    for adapter in registry.adapters:
        if adapter.module_id == module_id and adapter.manifest.slot == "browser":
            return adapter
    return None


def _base_contract(adapter: ResearchAdapter, manifest: dict[str, Any]) -> dict[str, Any]:
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
        "readiness": module_readiness(adapter),
        "engine_defaults": {
            "timeout_seconds": getattr(adapter, "timeout_seconds", None),
            "default_max_bytes": getattr(adapter, "max_bytes", DEFAULT_MAX_BYTES),
        },
    }


def _bridge_check_status(result: dict[str, Any]) -> str:
    results = result.get("results", [])
    if any(item.get("platform") == "browser" and item.get("confidence") != "blocked" for item in results):
        return "ok"
    attempts = result.get("receipt", {}).get("attempts", [])
    statuses = {str(item.get("status") or "") for item in attempts}
    if "blocked" in statuses:
        return "blocked"
    if "module_unavailable" in statuses:
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
