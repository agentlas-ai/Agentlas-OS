"""Local configuration for detachable research hardpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentlas_cloud.networking.bootstrap import atomic_write_json, networking_home, read_json, utc_now

HARDPOINT_CONFIG = "policies/research-hardpoints.json"

HARDPOINT_RECIPES: dict[str, dict[str, Any]] = {
    "npx-agent-browser": {
        "module_id": "browser.agent_cli",
        "label": "agent-browser through npx",
        "argv": ["npx", "-y", "agent-browser"],
        "command_display": "npx -y agent-browser",
        "notes": [
            "Uses npm's npx cache instead of a global install.",
            "The hardpoint receives only the requested public URL after SSRF checks.",
        ],
    }
}


def run_research_hardpoints(
    *,
    action: str = "list",
    module_id: str = "",
    recipe: str = "npx-agent-browser",
    home: Path | str | None = None,
) -> dict[str, Any]:
    """List or update approved local hardpoint recipes without executing them."""

    base = Path(home) if home else networking_home()
    config = load_research_hardpoint_config(base)
    status = "ok"
    error = ""
    if action == "arm":
        status, error = _arm(config, module_id=module_id, recipe=recipe)
        if status == "ok":
            write_research_hardpoint_config(base, config)
    elif action == "disarm":
        status, error = _disarm(config, module_id=module_id)
        if status == "ok":
            write_research_hardpoint_config(base, config)
    elif action != "list":
        status = "invalid_action"
        error = "action must be list, arm, or disarm"

    return {
        "schema": "agentlas.research.hardpoints.v0",
        "status": status,
        "action": action,
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "home": str(base),
        "config_file": str(_config_path(base)),
        "available_recipes": [_recipe_summary(name, payload) for name, payload in sorted(HARDPOINT_RECIPES.items())],
        "hardpoints": _configured_hardpoints(config),
        "error": error,
    }


def load_research_hardpoint_config(home: Path | str | None = None) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    payload = read_json(_config_path(base), default={})
    if not isinstance(payload, dict):
        payload = {}
    modules = payload.get("modules")
    if not isinstance(modules, dict):
        modules = {}
    return {
        "schema": "agentlas.research.hardpoints.v0",
        "updated_at": str(payload.get("updated_at") or ""),
        "modules": {str(key): value for key, value in modules.items() if isinstance(value, dict)},
    }


def write_research_hardpoint_config(home: Path | str, config: dict[str, Any]) -> None:
    config["schema"] = "agentlas.research.hardpoints.v0"
    config["updated_at"] = utc_now()
    atomic_write_json(_config_path(Path(home)), config)


def active_hardpoint_argv(module_id: str, *, home: Path | str | None = None) -> list[str]:
    summary = active_hardpoint_summary(module_id, home=home)
    recipe = HARDPOINT_RECIPES.get(str(summary.get("recipe") or ""))
    return list(recipe.get("argv") or []) if recipe else []


def active_hardpoint_summary(module_id: str, *, home: Path | str | None = None) -> dict[str, Any]:
    if home is None:
        return {"enabled": False, "reason": "no_home_bound"}
    config = load_research_hardpoint_config(home)
    entry = config["modules"].get(module_id)
    if not isinstance(entry, dict) or not entry.get("enabled"):
        return {"enabled": False, "reason": "not_configured"}
    recipe_name = str(entry.get("recipe") or "")
    recipe = HARDPOINT_RECIPES.get(recipe_name)
    if not recipe:
        return {"enabled": False, "reason": "unknown_recipe", "recipe": recipe_name}
    if recipe.get("module_id") != module_id:
        return {"enabled": False, "reason": "recipe_module_mismatch", "recipe": recipe_name}
    return {
        "enabled": True,
        "recipe": recipe_name,
        "label": recipe.get("label"),
        "command_display": recipe.get("command_display"),
        "configured_at": entry.get("configured_at"),
        "updated_at": entry.get("updated_at"),
    }


def _arm(config: dict[str, Any], *, module_id: str, recipe: str) -> tuple[str, str]:
    recipe_payload = HARDPOINT_RECIPES.get(recipe)
    if not recipe_payload:
        return "invalid_recipe", f"unknown_recipe:{recipe}"
    if recipe_payload.get("module_id") != module_id:
        return "invalid_module", f"recipe {recipe} is for {recipe_payload.get('module_id')}"
    now = utc_now()
    existing = config["modules"].get(module_id, {})
    config["modules"][module_id] = {
        "enabled": True,
        "recipe": recipe,
        "configured_at": existing.get("configured_at") or now,
        "updated_at": now,
    }
    return "ok", ""


def _disarm(config: dict[str, Any], *, module_id: str) -> tuple[str, str]:
    if not module_id:
        return "invalid_module", "module_id is required"
    existing = config["modules"].get(module_id)
    if isinstance(existing, dict):
        existing["enabled"] = False
        existing["updated_at"] = utc_now()
        config["modules"][module_id] = existing
    else:
        config["modules"][module_id] = {"enabled": False, "updated_at": utc_now()}
    return "ok", ""


def _configured_hardpoints(config: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for module_id, entry in sorted(config["modules"].items()):
        recipe_name = str(entry.get("recipe") or "")
        recipe = HARDPOINT_RECIPES.get(recipe_name, {})
        out.append(
            {
                "module_id": module_id,
                "enabled": bool(entry.get("enabled")),
                "recipe": recipe_name,
                "recipe_known": bool(recipe),
                "command_display": recipe.get("command_display", ""),
                "configured_at": entry.get("configured_at", ""),
                "updated_at": entry.get("updated_at", ""),
            }
        )
    return out


def _recipe_summary(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "module_id": payload.get("module_id"),
        "label": payload.get("label"),
        "command_display": payload.get("command_display"),
        "notes": list(payload.get("notes") or []),
    }


def _config_path(home: Path) -> Path:
    return home / HARDPOINT_CONFIG
