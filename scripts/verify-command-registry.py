#!/usr/bin/env python3
"""Verify the internal commandId registry against Core command sources.

This gate intentionally does not require host adapters to contain a new public
name. Their public names stay compatible; the registry only proves that each
existing spelling resolves to one internal identity and route.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentlas_cloud.command_registry import (  # noqa: E402
    CommandRegistryError,
    load_registry,
    resolve_command,
)


def main() -> int:
    try:
        registry = load_registry(ROOT)
    except CommandRegistryError as exc:
        print(f"verify-command-registry: {exc}", file=sys.stderr)
        return 1

    expected_ids = {str(command["commandId"]) for command in registry["commands"]}
    body_names = {
        path.name.removeprefix("hep-").removesuffix(".body.md")
        for path in (ROOT / "contracts" / "commands").glob("hep-*.body.md")
    }
    registered_names = {
        str(command["terminalCommand"]).removeprefix("hep-")
        for command in registry["commands"]
    }
    if body_names != registered_names:
        print(
            "verify-command-registry: canonical command bodies and registry disagree: "
            f"bodies-only={sorted(body_names - registered_names)}, "
            f"registry-only={sorted(registered_names - body_names)}",
            file=sys.stderr,
        )
        return 1

    for command in registry["commands"]:
        verb = str(command["terminalCommand"]).removeprefix("hep-")
        probes = [
            str(command["publicCommand"]),
            str(command["terminalCommand"]),
            f"/agentlas-{verb}",
            f"/agentlas {verb}",
        ]
        for probe in probes:
            result = resolve_command(probe, root=ROOT)
            if result.get("status") != "resolved" or result.get("commandId") != command["commandId"]:
                print(
                    f"verify-command-registry: {probe!r} did not resolve to {command['commandId']}: {result}",
                    file=sys.stderr,
                )
                return 1
        for route_name in (command.get("routes") or {}):
            result = resolve_command(str(command["publicCommand"]), route=route_name, root=ROOT)
            if result.get("status") != "resolved" or result.get("route") != route_name:
                print(
                    f"verify-command-registry: route {command['commandId']}/{route_name} is not resolvable: {result}",
                    file=sys.stderr,
                )
                return 1

    # Every rendered hep-* adapter must name a command that exists in the
    # registry. Coverage remains host-specific, but an invented verb is never
    # allowed to become a second semantic source.
    for directory in (
        ROOT / ".claude" / "commands",
        ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "commands",
        ROOT / "codex" / "prompts",
        ROOT / "gemini" / "extension" / "commands",
        ROOT / ".gemini" / "commands",
        ROOT / "antigravity" / "workflows",
        ROOT / ".agents" / "workflows",
        ROOT / "cursor" / "plugin" / "commands",
        ROOT / "opencode" / "commands",
    ):
        if not directory.is_dir():
            continue
        for path in directory.glob("hep-*.md"):
            verb = path.stem.removeprefix("hep-")
            if verb not in registered_names:
                print(f"verify-command-registry: unregistered adapter {path.relative_to(ROOT)}", file=sys.stderr)
                return 1
        for path in directory.glob("hep-*.toml"):
            verb = path.stem.removeprefix("hep-")
            if verb not in registered_names:
                print(f"verify-command-registry: unregistered adapter {path.relative_to(ROOT)}", file=sys.stderr)
                return 1

    print(
        "verify-command-registry: "
        f"{len(expected_ids)} commandId(s), {len(body_names)} canonical body/bodies, "
        "public names preserved",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
