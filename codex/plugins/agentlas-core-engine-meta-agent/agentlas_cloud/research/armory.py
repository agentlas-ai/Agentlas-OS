"""Runtime readiness catalog for detachable research modules."""

from __future__ import annotations

import os
import shutil
from collections import Counter
from typing import Any

from .contracts import ResearchRequest
from .engine import default_registry
from .hardpoints import active_hardpoint_summary
from .loadouts import apply_loadout, loadout_policy
from .policy import module_allowed, weight_allowed
from .registry import AdapterRegistry, ResearchAdapter


ENV_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "search.jina": ("AGENTLAS_JINA_API_KEY", "JINA_API_KEY"),
    "platform.reddit.oauth": ("AGENTLAS_REDDIT_BEARER_TOKEN", "REDDIT_BEARER_TOKEN"),
    "platform.threads": ("AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"),
}

CREDENTIAL_ALTERNATIVES: dict[str, tuple[tuple[str, ...], ...]] = {
    "platform.reddit.oauth": (
        ("AGENTLAS_REDDIT_BEARER_TOKEN",),
        ("REDDIT_BEARER_TOKEN",),
        ("AGENTLAS_REDDIT_CLIENT_ID", "AGENTLAS_REDDIT_CLIENT_SECRET"),
        ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"),
    ),
}

COMMAND_ENV_REQUIREMENTS: dict[str, str] = {
    "browser.playwright_mcp": "AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD",
    "browser.browser_use": "AGENTLAS_BROWSER_USE_SNAPSHOT_CMD",
    "browser.stagehand": "AGENTLAS_STAGEHAND_SNAPSHOT_CMD",
    "browser.steel": "AGENTLAS_STEEL_SNAPSHOT_CMD",
    "browser.hyperagent": "AGENTLAS_HYPERAGENT_SNAPSHOT_CMD",
    "browser.browseros": "AGENTLAS_BROWSEROS_SNAPSHOT_CMD",
}

BINARY_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "browser.agent_cli": ("AGENTLAS_AGENT_BROWSER_BIN", "agent-browser"),
}


def run_research_armory(
    *,
    loadout: str = "auto",
    slot: str = "",
    home: str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """List modules with non-executing readiness checks."""

    selected_registry = registry or default_registry(home=home)
    request = apply_loadout(ResearchRequest(query="armory", loadout=loadout))
    modules = []
    for adapter in selected_registry.adapters:
        manifest = adapter.manifest.to_dict()
        if slot and manifest.get("slot") != slot:
            continue
        allowed, allow_reason = module_allowed(adapter.module_id, request.allowed_modules, request.forbidden_modules)
        weight_ok, weight_reason = weight_allowed(adapter.weight, request.max_weight)
        readiness = module_readiness(adapter)
        modules.append(
            {
                **manifest,
                "in_loadout": adapter.module_id in request.allowed_modules if request.allowed_modules else False,
                "loadout_allowed": allowed,
                "loadout_reason": allow_reason,
                "weight_allowed": weight_ok,
                "weight_reason": weight_reason,
                "readiness": readiness,
            }
        )

    counts = Counter(str(module["readiness"]["state"]) for module in modules)
    slot_counts = Counter(str(module.get("slot") or "unknown") for module in modules)
    mounted_slot_counts = Counter(str(module.get("slot") or "unknown") for module in modules if module["in_loadout"])
    return {
        "schema": "agentlas.research.armory.v0",
        "status": "ok",
        "loadout": loadout_policy(loadout),
        "home": home or "",
        "slot": slot or "all",
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "module_counts": dict(sorted(counts.items())),
        "slot_counts": dict(sorted(slot_counts.items())),
        "mounted_slot_counts": dict(sorted(mounted_slot_counts.items())),
        "modules": modules,
    }


def module_readiness(adapter: ResearchAdapter) -> dict[str, Any]:
    """Return readiness without executing commands, browsers, or network calls."""

    manifest = adapter.manifest.to_dict()
    checks: list[dict[str, Any]] = []
    state = "ready"
    reason = "no_runtime_setup_required"

    credential_alternatives = CREDENTIAL_ALTERNATIVES.get(adapter.module_id, ())
    if credential_alternatives:
        ready_env = _ready_credential_env(credential_alternatives)
        default_missing = list(ENV_REQUIREMENTS.get(adapter.module_id, _dedupe_envs(credential_alternatives)))
        checks.append(
            {
                "kind": "env_alternatives",
                "requirement": " OR ".join("+".join(group) for group in credential_alternatives),
                "status": "ok" if ready_env else "missing",
                "present_env": ready_env[:2],
                "missing_env": [] if ready_env else default_missing,
                "accepted_env_sets": [list(group) for group in credential_alternatives],
            }
        )
        if not ready_env:
            state = "needs_config"
            reason = f"missing_env:{'|'.join(default_missing)}"

    env_aliases = ENV_REQUIREMENTS.get(adapter.module_id, ())
    if env_aliases and not credential_alternatives:
        present = [name for name in env_aliases if os.environ.get(name)]
        checks.append(
            {
                "kind": "env",
                "requirement": "|".join(env_aliases),
                "status": "ok" if present else "missing",
                "present_env": present[:1],
                "missing_env": [] if present else list(env_aliases),
            }
        )
        if not present:
            state = "needs_config"
            reason = f"missing_env:{'|'.join(env_aliases)}"

    command_env = COMMAND_ENV_REQUIREMENTS.get(adapter.module_id)
    if command_env:
        configured = bool(os.environ.get(command_env))
        checks.append(
            {
                "kind": "command_env",
                "requirement": command_env,
                "status": "ok" if configured else "missing",
                "present_env": [command_env] if configured else [],
                "missing_env": [] if configured else [command_env],
            }
        )
        if not configured:
            state = "needs_config"
            reason = f"missing_env:{command_env}"

    binary_requirement = BINARY_REQUIREMENTS.get(adapter.module_id)
    if binary_requirement:
        env_name, binary_name = binary_requirement
        configured = bool(os.environ.get(env_name))
        configured_hardpoint = active_hardpoint_summary(adapter.module_id, home=getattr(adapter, "home", None))
        recipe_configured = bool(configured_hardpoint.get("enabled"))
        installed = bool(shutil.which(binary_name))
        checks.append(
            {
                "kind": "binary",
                "requirement": binary_name,
                "status": "ok" if configured or recipe_configured or installed else "missing",
                "present_env": [env_name] if configured else [],
                "missing_env": [] if configured or recipe_configured or installed else [env_name],
                "binary_found": installed,
                "configured_hardpoint": configured_hardpoint,
            }
        )
        if not configured and not recipe_configured and not installed:
            state = "needs_binary"
            reason = f"missing_binary:{binary_name}"

    checks.extend(_passive_requirement_checks(manifest.get("requires", []), adapter.module_id, home=getattr(adapter, "home", None)))
    return {
        "state": state,
        "reason": reason,
        "activation": manifest.get("activation", ""),
        "default_state": manifest.get("default_state", ""),
        "checks": checks,
    }


def _passive_requirement_checks(requires: list[str], module_id: str, *, home=None) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    env_aliases = ENV_REQUIREMENTS.get(module_id, ())
    command_env = COMMAND_ENV_REQUIREMENTS.get(module_id, "")
    binary_requirement = BINARY_REQUIREMENTS.get(module_id)
    for requirement in requires:
        if requirement.startswith("network:"):
            status = "not_probed"
            reason = "armory_does_not_call_network"
        elif requirement.startswith("permission:"):
            status = "policy_required"
            reason = "permission_scope_must_match_provider_account"
        elif requirement.startswith(("oauth:", "api_key:")):
            present = _module_credentials_ready(module_id, env_aliases=env_aliases)
            status = "ok" if present else "missing_config"
            reason = "env_present" if present else "env_missing"
        elif requirement.startswith("command:"):
            status = "ok" if command_env and os.environ.get(command_env) else "missing_config"
            reason = "command_env_present" if status == "ok" else "command_env_missing"
        elif requirement.startswith("binary:"):
            env_name, binary_name = binary_requirement or ("", requirement.split(":", 1)[1])
            configured_hardpoint = active_hardpoint_summary(module_id, home=home)
            status = (
                "ok"
                if (env_name and os.environ.get(env_name)) or configured_hardpoint.get("enabled") or shutil.which(binary_name)
                else "missing_binary"
            )
            reason = "binary_available" if status == "ok" else "binary_missing"
        elif requirement.startswith("recommended_"):
            status = "recommended"
            reason = "fallback_can_run_but_durable_path_prefers_this"
        else:
            status = "declared"
            reason = "not_executable_by_armory"
        checks.append({"kind": "manifest", "requirement": requirement, "status": status, "reason": reason})
    return checks


def _module_credentials_ready(module_id: str, *, env_aliases: tuple[str, ...]) -> bool:
    alternatives = CREDENTIAL_ALTERNATIVES.get(module_id, ())
    if alternatives:
        return bool(_ready_credential_env(alternatives))
    return any(os.environ.get(name) for name in env_aliases)


def _ready_credential_env(alternatives: tuple[tuple[str, ...], ...]) -> list[str]:
    for group in alternatives:
        if all(os.environ.get(name) for name in group):
            return list(group)
    return []


def _dedupe_envs(alternatives: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for group in alternatives:
        for name in group:
            if name in seen:
                continue
            seen.add(name)
            out.append(name)
    return tuple(out)
