"""Internal command identity and route resolution for Agentlas hosts.

The public spelling of a command is deliberately not the identity of the
command.  Claude, Codex, a terminal, and a host prompt may spell the same
operation differently; this module gives each of them one stable ``commandId``
and one route vocabulary without changing any existing ``hep-*`` or plugin
name.

This is a runtime contract, not the generated package-level
``.agentlas/global-commands.json`` contract.  The latter describes one output
agent's user-facing command.  This registry describes the Core engine's own
commands and the adapters that invoke it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


COMMAND_REGISTRY_SCHEMA = "agentlas.command-registry.v2"
COMMAND_RESOLUTION_SCHEMA = "agentlas.command-resolution.v1"
COMMAND_REGISTRY_RELATIVE_PATH = Path("contracts") / "command-registry.v2.json"
_COMMAND_ID_RE = re.compile(r"^agentlas\.[a-z0-9][a-z0-9-]*$")
_PUBLIC_COMMAND_RE = re.compile(r"^/hep-[a-z0-9][a-z0-9-]*$")
_TERMINAL_COMMAND_RE = re.compile(r"^hep-[a-z0-9][a-z0-9-]*$")
_SAFE_SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SURFACE_STATUSES = {"executable", "host_model_required", "redirect", "identity_only"}


class CommandRegistryError(ValueError):
    """A malformed or unsafe command registry."""


def _runtime_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root).expanduser().resolve()
    configured = os.environ.get("HEPHAESTUS_RUNTIME_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def registry_path(root: str | Path | None = None) -> Path:
    """Return the registry path without exposing a machine-specific path."""

    return _runtime_root(root) / COMMAND_REGISTRY_RELATIVE_PATH


def _is_safe_relative_path(value: str) -> bool:
    if not value or "\n" in value or "\r" in value:
        return False
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    parts = value.replace("\\", "/").split("/")
    return ".." not in parts and all(part not in {"", "."} for part in parts)


def _normalize(value: str) -> str:
    """Normalize host punctuation while preserving the spaced Agentlas form."""

    result = " ".join(str(value or "").strip().split()).lower()
    if result.startswith("$"):
        result = result[1:]
    if result.startswith("/"):
        result = result[1:]
    if result.startswith("prompts:"):
        result = result[len("prompts:"):]
    if result.startswith("skill:"):
        result = result[len("skill:"):]
    return result


def _body_command_name(body: str) -> str:
    name = Path(body).name
    if not name.startswith("hep-") or not name.endswith(".body.md"):
        return ""
    return name[:-len(".body.md")]


def validate_registry(
    registry: Mapping[str, Any],
    root: str | Path | None = None,
    *,
    check_files: bool = True,
) -> list[str]:
    """Return all structural problems, keeping validation deterministic."""

    problems: list[str] = []
    if not isinstance(registry, Mapping):
        return ["registry must be an object"]
    if registry.get("schemaVersion") != COMMAND_REGISTRY_SCHEMA:
        problems.append(f"schemaVersion must be {COMMAND_REGISTRY_SCHEMA}")
    if not isinstance(registry.get("registryId"), str) or not registry.get("registryId"):
        problems.append("registryId must be a non-empty string")

    compatibility = registry.get("compatibility")
    if not isinstance(compatibility, Mapping):
        problems.append("compatibility must be an object")
    else:
        if compatibility.get("commandIdInternalOnly") is not True:
            problems.append("compatibility.commandIdInternalOnly must be true")
        if compatibility.get("preserveExistingPublicNames") is not True:
            problems.append("compatibility.preserveExistingPublicNames must be true")

    skills = registry.get("universalSkills")
    if not isinstance(skills, list) or not skills:
        problems.append("universalSkills must be a non-empty array")
    else:
        seen_skills: set[str] = set()
        for skill in skills:
            if not isinstance(skill, str) or not _SAFE_SKILL_RE.fullmatch(skill):
                problems.append(f"unsafe universal skill name: {skill!r}")
                continue
            if skill in seen_skills:
                problems.append(f"duplicate universal skill: {skill}")
            seen_skills.add(skill)

    commands = registry.get("commands")
    if not isinstance(commands, list) or not commands:
        problems.append("commands must be a non-empty array")
        return problems

    command_ids: set[str] = set()
    public_commands: set[str] = set()
    terminal_commands: set[str] = set()
    aliases: dict[str, str] = {}
    body_commands: set[str] = set()
    for index, command in enumerate(commands):
        prefix = f"commands[{index}]"
        if not isinstance(command, Mapping):
            problems.append(f"{prefix} must be an object")
            continue
        command_id = command.get("commandId")
        public_command = command.get("publicCommand")
        terminal_command = command.get("terminalCommand")
        body = command.get("body")
        surface_status = command.get("surfaceStatus")
        owning_binary = command.get("owningBinary")
        installed_entrypoint = command.get("installedEntrypoint")
        if not isinstance(command_id, str) or not _COMMAND_ID_RE.fullmatch(command_id):
            problems.append(f"{prefix}.commandId is invalid: {command_id!r}")
        elif command_id in command_ids:
            problems.append(f"duplicate commandId: {command_id}")
        else:
            command_ids.add(command_id)
        if not isinstance(public_command, str) or not _PUBLIC_COMMAND_RE.fullmatch(public_command):
            problems.append(f"{prefix}.publicCommand is invalid: {public_command!r}")
        elif public_command in public_commands:
            problems.append(f"duplicate publicCommand: {public_command}")
        else:
            public_commands.add(public_command)
        if not isinstance(terminal_command, str) or not _TERMINAL_COMMAND_RE.fullmatch(terminal_command):
            problems.append(f"{prefix}.terminalCommand is invalid: {terminal_command!r}")
        elif terminal_command in terminal_commands:
            problems.append(f"duplicate terminalCommand: {terminal_command}")
        else:
            terminal_commands.add(terminal_command)
        if not isinstance(body, str) or not _is_safe_relative_path(body):
            problems.append(f"{prefix}.body must be a safe relative path: {body!r}")
        else:
            body_command = _body_command_name(body)
            if body_command:
                body_commands.add(body_command)
            if check_files:
                base = _runtime_root(root)
                if not (base / body).is_file():
                    problems.append(f"{prefix}.body does not exist: {body}")
        if surface_status not in _SURFACE_STATUSES:
            problems.append(f"{prefix}.surfaceStatus is invalid: {surface_status!r}")
        if surface_status == "identity_only":
            if owning_binary is not None or installed_entrypoint is not None:
                problems.append(f"{prefix} identity_only commands cannot claim an installed entrypoint")
        elif not isinstance(owning_binary, str) or not owning_binary:
            problems.append(f"{prefix}.owningBinary must name the actual executor")
        elif not isinstance(installed_entrypoint, str) or not installed_entrypoint:
            problems.append(f"{prefix}.installedEntrypoint must name the installed surface")
        if surface_status == "redirect" and owning_binary == "hephaestus":
            problems.append(f"{prefix} redirects must name the receiving binary")

        routes = command.get("routes")
        if not isinstance(routes, Mapping) or not isinstance(routes.get("default"), Mapping):
            problems.append(f"{prefix}.routes.default is required")
        else:
            for route_name, route in routes.items():
                if not isinstance(route_name, str) or not route_name:
                    problems.append(f"{prefix} has an invalid route name: {route_name!r}")
                    continue
                if not isinstance(route, Mapping):
                    problems.append(f"{prefix}.routes.{route_name} must be an object")
                    continue
                entrypoint = route.get("entrypoint")
                modes = route.get("inputModes")
                if not isinstance(entrypoint, str) or not re.fullmatch(r"^[a-z0-9][a-z0-9-]*$", entrypoint):
                    problems.append(f"{prefix}.routes.{route_name}.entrypoint is invalid")
                if not isinstance(modes, list) or not modes or any(
                    mode not in {"host_request", "interactive_thread", "headless_export", "local_cli"}
                    for mode in modes
                ):
                    problems.append(f"{prefix}.routes.{route_name}.inputModes is invalid")
        alias_values = command.get("aliases")
        if not isinstance(alias_values, list):
            problems.append(f"{prefix}.aliases must be an array")
        else:
            for alias in alias_values:
                if not isinstance(alias, str) or not alias.strip():
                    problems.append(f"{prefix} contains an empty alias")
                    continue
                normalized = _normalize(alias)
                previous = aliases.get(normalized)
                if previous and previous != command_id:
                    problems.append(f"alias {alias!r} belongs to both {previous} and {command_id}")
                else:
                    aliases[normalized] = str(command_id)

        if isinstance(public_command, str) and isinstance(terminal_command, str):
            public_verb = public_command.removeprefix("/hep-")
            terminal_verb = terminal_command.removeprefix("hep-")
            if public_verb != terminal_verb:
                problems.append(f"{prefix} public/terminal command verbs differ")

    if check_files and isinstance(commands, list):
        base = _runtime_root(root)
        actual_bodies = {
            _body_command_name(path.name)
            for path in (base / "contracts" / "commands").glob("hep-*.body.md")
        }
        actual_bodies.discard("")
        if actual_bodies != body_commands:
            missing = sorted(actual_bodies - body_commands)
            extra = sorted(body_commands - actual_bodies)
            if missing:
                problems.append("command bodies missing from registry: " + ", ".join(missing))
            if extra:
                problems.append("registry bodies missing from contracts/commands: " + ", ".join(extra))
        for skill in skills if isinstance(skills, list) else []:
            skill_paths = (
                base / "skills" / skill / "SKILL.md",
                base / ".agents" / "skills" / skill / "SKILL.md",
            )
            if not any(path.is_file() for path in skill_paths):
                problems.append(f"universal skill is not shipped: {skill}")
    return problems


def load_registry(
    root: str | Path | None = None,
    *,
    check_files: bool = True,
) -> dict[str, Any]:
    path = registry_path(root)
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CommandRegistryError("command_registry_not_found") from exc
    except (OSError, ValueError) as exc:
        raise CommandRegistryError(f"command_registry_unreadable: {exc}") from exc
    problems = validate_registry(registry, root, check_files=check_files)
    if problems:
        raise CommandRegistryError("; ".join(problems))
    return dict(registry)


def registry_digest(registry: Mapping[str, Any]) -> str:
    payload = json.dumps(registry, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _command_aliases(command: Mapping[str, Any]) -> set[str]:
    terminal = str(command.get("terminalCommand", ""))
    verb = terminal.removeprefix("hep-")
    values = {
        str(command.get("commandId", "")),
        str(command.get("publicCommand", "")),
        terminal,
        f"agentlas-{verb}",
        f"agentlas {verb}",
        verb,
        f"hephaestus-{verb}",
        f"prompts:hep-{verb}",
    }
    values.update(str(item) for item in command.get("aliases", []) if isinstance(item, str))
    return {_normalize(value) for value in values if value.strip()}


def _error_resolution(
    value: str,
    code: str,
    *,
    root: str | Path | None = None,
    route: str | None = None,
    check_files: bool = False,
) -> dict[str, Any]:
    try:
        registry = load_registry(root, check_files=check_files)
        version = registry.get("schemaVersion")
        digest = registry_digest(registry)
    except CommandRegistryError:
        version = COMMAND_REGISTRY_SCHEMA
        digest = None
    result: dict[str, Any] = {
        "schemaVersion": COMMAND_RESOLUTION_SCHEMA,
        "status": "error",
        "code": code,
        "input": value,
        "registrySchemaVersion": version,
    }
    if digest:
        result["registryDigest"] = digest
    if route:
        result["requestedRoute"] = route
    return result


def resolve_command(
    value: str,
    route: str | None = None,
    *,
    root: str | Path | None = None,
    check_files: bool = False,
) -> dict[str, Any]:
    """Resolve any supported host spelling to one internal command identity."""

    try:
        registry = load_registry(root, check_files=check_files)
    except CommandRegistryError:
        return _error_resolution(value, "command_registry_invalid", root=root, route=route, check_files=check_files)
    candidate = _normalize(value)
    if not candidate:
        return _error_resolution(value, "empty_command", root=root, route=route, check_files=check_files)

    matches: list[tuple[Mapping[str, Any], str | None]] = []
    for command in registry["commands"]:
        aliases = _command_aliases(command)
        if candidate in aliases:
            matches.append((command, None))
            continue
        # A route is part of the invocation, not part of the public command
        # name. Longest aliases keep `agentlas build` ahead of `agentlas` if a
        # future umbrella alias is added.
        for alias in sorted(aliases, key=len, reverse=True):
            if candidate.startswith(alias + " "):
                suffix = candidate[len(alias):].strip()
                if suffix and " " not in suffix:
                    matches.append((command, suffix))
                break
    if not matches and candidate == "session":
        for command in registry["commands"]:
            routes = command.get("routes") or {}
            if isinstance(routes, Mapping) and any(
                isinstance(item, Mapping) and item.get("entrypoint") == "session"
                for item in routes.values()
            ):
                matches.append((command, "session"))
    if not matches:
        return _error_resolution(value, "unknown_command", root=root, route=route, check_files=check_files)
    if len({str(command.get("commandId")) for command, _ in matches}) > 1:
        return _error_resolution(value, "ambiguous_command", root=root, route=route, check_files=check_files)
    command, suffix = matches[0]
    requested_route = route or suffix or "default"
    if route and suffix and route != suffix:
        return _error_resolution(value, "route_conflict", root=root, route=route, check_files=check_files)
    routes = command.get("routes") or {}
    route_spec = routes.get(requested_route) if isinstance(routes, Mapping) else None
    if not isinstance(route_spec, Mapping):
        return _error_resolution(value, "unknown_route", root=root, route=requested_route, check_files=check_files)
    return {
        "schemaVersion": COMMAND_RESOLUTION_SCHEMA,
        "status": "resolved",
        "commandId": command["commandId"],
        "publicCommand": command["publicCommand"],
        "terminalCommand": command["terminalCommand"],
        "route": requested_route,
        "entrypoint": route_spec["entrypoint"],
        "inputModes": list(route_spec["inputModes"]),
        "hostModelRequired": bool(
            route_spec.get("hostModelRequired", False)
            or command.get("surfaceStatus") == "host_model_required"
        ),
        "surfaceStatus": command["surfaceStatus"],
        "owningBinary": command["owningBinary"],
        "installedEntrypoint": command["installedEntrypoint"],
        "body": command["body"],
        "registrySchemaVersion": registry["schemaVersion"],
        "registryDigest": registry_digest(registry),
    }


def registry_summary(root: str | Path | None = None) -> dict[str, Any]:
    registry = load_registry(root)
    commands = registry["commands"]
    return {
        "schemaVersion": registry["schemaVersion"],
        "status": "ok",
        "registryId": registry["registryId"],
        "registryDigest": registry_digest(registry),
        "commandCount": len(commands),
        "commandIds": [command["commandId"] for command in commands],
        "publicCommands": [command["publicCommand"] for command in commands],
        "surfaces": [
            {
                "commandId": command["commandId"],
                "status": command["surfaceStatus"],
                "owningBinary": command["owningBinary"],
                "installedEntrypoint": command["installedEntrypoint"],
            }
            for command in commands
        ],
        "universalSkills": list(registry["universalSkills"]),
        "publicNamesPreserved": bool(registry["compatibility"]["preserveExistingPublicNames"]),
    }


def check_registry(root: str | Path | None = None) -> dict[str, Any]:
    try:
        registry = load_registry(root)
    except CommandRegistryError as exc:
        return {
            "schemaVersion": COMMAND_RESOLUTION_SCHEMA,
            "status": "error",
            "code": "command_registry_invalid",
            "errors": [str(exc)],
        }
    return {
        "schemaVersion": COMMAND_RESOLUTION_SCHEMA,
        "status": "ok",
        "registrySchemaVersion": registry["schemaVersion"],
        "registryDigest": registry_digest(registry),
        "commandCount": len(registry["commands"]),
        "validatedFiles": True,
    }


def attach_command_context(
    value: str | None = None,
    route: str | None = None,
    *,
    root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Resolve the launcher-provided invocation into process-local env state.

    The environment variables are intentionally internal. They let Core code,
    telemetry, and future adapters agree on identity without making a new user
    command or changing the current ``hep-*`` spelling.
    """

    raw = value or os.environ.get("AGENTLAS_COMMAND_NAME", "")
    if not raw:
        return None
    normalized = _normalize(raw)
    first_token = normalized.split(" ", 1)[0]
    if not (
        first_token == "session"
        or first_token in {"build", "network", "storm", "graph", "local", "cloud", "hub", "search", "browser", "call", "upload", "connect", "login", "orch", "update"}
        or first_token.startswith(("hep-", "agentlas-", "hephaestus-", "prompts:hep-"))
    ):
        return None
    result = resolve_command(raw, route=route, root=root, check_files=False)
    if result.get("status") != "resolved":
        return None
    os.environ["AGENTLAS_COMMAND_ID"] = str(result["commandId"])
    os.environ["AGENTLAS_COMMAND_ROUTE"] = str(result["route"])
    return result
