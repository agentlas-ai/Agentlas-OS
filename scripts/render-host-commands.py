#!/usr/bin/env python3
"""Render every host's copy of a `/hep-*` command body from one canonical body.

    The `/agentlas-*` redirect aliases are NOT rendered here — they belong to
    scripts/render-command-aliases.py, which also owns the Kimi skill and Codex
    Agent Skills families. Two generators writing the same files is the same
    disease this one cures, so run them in that order: bodies, then aliases.

WHY THIS EXISTS
    The same command shipped as ten hand-maintained files. Measured 2026-08-17,
    all twelve `/hep-*` commands had drifted: `hep-build` existed in five
    different bodies between 109 and 250 lines, and only the Claude copy still
    carried "a non-empty blocker list means you may not report `completed`".
    Every other runtime was allowed to call a failed build finished. Nobody
    decided that; it is what copying a file by hand five times does over time.

WHAT IS ACTUALLY HOST-SPECIFIC
    Two things, and they are both mechanical:
      1. the file format — YAML frontmatter, no frontmatter, or a TOML wrapper;
      2. how the host spells "the text the user typed" — `$ARGUMENTS`, `{{args}}`,
         or nothing at all.
    The engine-root candidates are NOT host-specific: every copy already probed
    the same variables, so the canonical body lists all of them, including
    `GEMINI_EXTENSION_ROOT`. An unset variable costs nothing on the other hosts.

    Anything else that differs between hosts is drift, and this script erases it
    on purpose.
"""

from __future__ import annotations

import pathlib
import json
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BODIES = ROOT / "contracts" / "commands"
COMMAND_REGISTRY = ROOT / "contracts" / "command-registry.v2.json"
# The one place a host is declared deliverable: contracts/runtime-registry.json
# -> hostAdapters.dirs. scripts/build-runtime-release-asset.sh,
# agentlas_cloud/update.py, and scripts/install-all-runtimes.sh all read that
# same block for what ships. Measured 2026-09-06: `.zcode/commands` below had
# 31 rendered files kept perfectly in sync with the canonical bodies, and
# `.zcode` was never in hostAdapters.dirs — every one of those files was built
# and re-checked here and then silently dropped before the release archive or
# even the local runtime home, because nothing that assembles a delivery
# reads this HOSTS list. A host cannot be rendered here without also being
# declared there; check that instead of trusting three lists to agree by hand.
RUNTIME_REGISTRY = ROOT / "contracts" / "runtime-registry.json"
_HOST_ADAPTER_NAME_RE = re.compile(r"^\.?[a-z0-9][a-z0-9._-]*$")

# (directory, file format, args token, frontmatter lines)
# `args` is None when the host passes the user's text some other way and the
# body must not carry a placeholder at all.
HOSTS = [
    ("claude/plugins/agentlas-core-engine-meta-agent/commands", "md", "$ARGUMENTS", "full"),
    (".claude/commands", "md", "$ARGUMENTS", "full"),
    (".zcode/commands", "md", "$ARGUMENTS", "full"),
    ("antigravity/workflows", "md", None, "description"),
    (".agents/workflows", "md", None, "description"),
    ("codex/prompts", "md", "$ARGUMENTS", "codex"),
    ("opencode/commands", "md", "$ARGUMENTS", "description"),
    ("cursor/plugin/commands", "md", None, "none"),
    (".gemini/commands", "toml", "{{args}}", "toml"),
    ("gemini/extension/commands", "toml", "{{args}}", "toml"),
]

DEFAULT_TOOLS = "Bash, Read, Glob, Grep"

# description / argument-hint / allowed-tools are the only per-command metadata a
# host reads. They were taken from the Claude copies, which were the only ones
# still complete when this table was written.
FRONTMATTER = {
    "hep-build": {
        "description": "Build, repair, or package Agentlas agents and teams with Hephaestus.",
        "argument-hint": "'[ontology|single-agent|team|package] [details...]'",
        "codex-argument-hint": '<request, or "ontology">',
    },
    "hep-upload": {
        "description": "Publish an Agentlas package to Agent Cloud or the public Hub.",
        "argument-hint": "'<package folder> [--visibility private-link|marketplace]'",
        "codex-argument-hint": "<package folder>",
    },
    "hep-login": {
        "description": "Sign this machine into Agentlas (opens the browser sign-in window).",
        "argument-hint": "''",
        "codex-argument-hint": "",
    },
    "hep-update": {
        "description": "Update the installed Agentlas runtime and every host adapter on this machine.",
        "argument-hint": "''",
        "codex-argument-hint": "",
    },
    "hep-orch": {
        "description": "Set or show which model runs the orchestrator and which runs the workers.",
        "argument-hint": "'[orchestrator=<tier|model>] [worker=<tier|model>] | show | clear'",
        "codex-argument-hint": "<orchestrator=tier worker=tier>",
    },
    "hep-network": {
        "description": "Staff a task from registered Local, owner Cloud, and public Hub agents.",
        "argument-hint": "'<request>'",
    },
    "hep-cloud": {
        "description": "Staff a task only from the signed-in owner's Agent Cloud agents.",
        "argument-hint": "'<request>'",
    },
    "hep-hub": {
        "description": "Staff a task only from public Agentlas Hub agents.",
        "argument-hint": "'<request>'",
    },
    "hep-local": {
        "description": "Staff a task only from Agentlas agents registered on this machine.",
        "argument-hint": "'<request>'",
    },
    "hep-call": {
        "description": "Prepare explicitly named Agentlas Hub or Cloud agents.",
        "argument-hint": "'agent-a, agent-b {context}'",
    },
    "hep-graph": {
        "description": "Build an Agentlas automation by describing it, list saved ones, or request a run.",
        "argument-hint": "'[new <what you want> | list | show <name> | run <name>]'",
        "allowed-tools": "Bash, Read",
    },
    "hep-search": {
        "description": "Search Agentlas Cloud and Hub agent candidates without invoking.",
        "argument-hint": "'<request>'",
    },
    "hep-storm": {
        "description": "Run a force-robust Stormbreaker loop — route to real agents, execute a verified pipeline to completion.",
        "argument-hint": "'<goal>'",
        "allowed-tools": "Bash, Read, Glob, Grep, Edit, Write, Task",
    },
    "hep-browser": {
        "description": "Use the Agentlas browser hardpoint for browser-required work.",
        "argument-hint": "'<url-or-query>'",
    },
    "hep-connect": {
        "description": "Connect Agentlas agents or teams to Telegram.",
        "argument-hint": '"[telegram] [agent/team/group name]"',
    },
}


def head(name: str, style: str, title_override: str | None = None) -> str:
    meta = FRONTMATTER[name]
    if style == "none":
        return ""
    if style == "toml":
        return f'description = "{meta["description"]}"\nprompt = """\n'
    lines = [f"description: {meta['description']}"]
    if style == "full":
        lines.append(f"argument-hint: {meta['argument-hint']}")
        lines.append(f"allowed-tools: {meta.get('allowed-tools', DEFAULT_TOOLS)}")
    elif style == "codex":
        lines.append(f"argument-hint: {meta.get('codex-argument-hint', meta['argument-hint'])}")
    return "---\n" + "\n".join(lines) + "\n---\n"


def render(name: str, args_token: str | None, style: str) -> str:
    body = (BODIES / f"{name}.body.md").read_text()
    if args_token is None:
        # No placeholder at all: leaving `{{ARGS}}` on a host that never
        # substitutes it puts a literal token in the model's prompt.
        body = body.replace("Raw arguments:\n`{{ARGS}}`\n\n", "")
        body = body.replace("{{ARGS}}", "the request typed after the command")
    else:
        body = body.replace("{{ARGS}}", args_token)
    text = head(name, style) + body
    if style == "toml":
        text = text.rstrip("\n") + '\n"""\n'
    return text


def registry_command_names() -> set[str]:
    registry = json.loads(COMMAND_REGISTRY.read_text(encoding="utf-8"))
    return {
        str(command["terminalCommand"])
        for command in registry.get("commands", [])
        if isinstance(command, dict) and isinstance(command.get("terminalCommand"), str)
    }


def declared_release_host_dirs() -> set[str]:
    """The host-adapter directories the release/runtime-home actually ships.

    Single source: contracts/runtime-registry.json -> hostAdapters.dirs.
    """
    block = json.loads(RUNTIME_REGISTRY.read_text(encoding="utf-8")).get("hostAdapters")
    if not isinstance(block, dict):
        raise ValueError(f"{RUNTIME_REGISTRY.relative_to(ROOT)} has no hostAdapters block")
    dirs = block.get("dirs")
    if not isinstance(dirs, list) or not dirs:
        raise ValueError(f"{RUNTIME_REGISTRY.relative_to(ROOT)} hostAdapters.dirs is empty or malformed")
    names = {
        name for name in dirs
        if isinstance(name, str) and name not in (".", "..") and _HOST_ADAPTER_NAME_RE.match(name)
    }
    if not names:
        raise ValueError(f"{RUNTIME_REGISTRY.relative_to(ROOT)} hostAdapters.dirs has no valid entries")
    return names


def verify_hosts_are_deliverable() -> list[str]:
    """Every HOSTS directory's top-level component must be a declared, shipped host.

    Rendering a command into a directory nothing ships from is not caught by
    diffing the render against itself — the render is internally consistent
    and still never reaches a user. Cross-check against the one place
    delivery is declared instead.
    """
    declared = declared_release_host_dirs()
    problems = []
    for directory, *_rest in HOSTS:
        top = directory.split("/", 1)[0]
        if top not in declared:
            problems.append(
                f"{directory} is rendered here but {top!r} is not in "
                f"{RUNTIME_REGISTRY.relative_to(ROOT)} hostAdapters.dirs — it would never ship"
            )
    return problems


def main() -> int:
    check = "--check" in sys.argv[1:]
    try:
        registered = registry_command_names()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"command registry unreadable: {exc}")
        return 1
    try:
        delivery_problems = verify_hosts_are_deliverable()
    except (OSError, ValueError) as exc:
        print(f"host-adapter delivery contract unreadable: {exc}")
        return 1
    if delivery_problems:
        for problem in delivery_problems:
            print(f"  FAIL  {problem}")
        return 1
    body_names = {p.stem.removesuffix(".body") for p in BODIES.glob("*.body.md")}
    if body_names != registered:
        print(
            "command registry/body mismatch: "
            f"bodies-only={sorted(body_names - registered)}, "
            f"registry-only={sorted(registered - body_names)}"
        )
        return 1
    names = [n for n in sys.argv[1:] if not n.startswith("--")]
    if not names:
        names = sorted(registered)
    problems: list[str] = []
    missing: list[str] = []
    written = 0
    for name in names:
        if name not in registered:
            problems.append(f"{name} is not registered in {COMMAND_REGISTRY.relative_to(ROOT)}")
            continue
        if not (BODIES / f"{name}.body.md").exists():
            problems.append(f"no canonical body for {name}")
            continue
        for directory, kind, args_token, style in HOSTS:
            target = ROOT / directory / f"{name}.{kind}"
            if not target.parent.exists():
                continue
            # Unifying the copies that exist is a formatting decision. Creating a
            # command where a host never shipped one is a product decision, so
            # this script reports it and leaves it to a person.
            if not target.exists():
                missing.append(f"{target.relative_to(ROOT)} (host does not ship this command yet)")
                continue
            want = render(name, args_token, style)
            if check:
                have = target.read_text() if target.exists() else ""
                if have != want:
                    problems.append(f"{target.relative_to(ROOT)} differs from the canonical render")
            else:
                target.write_text(want)
                written += 1
    if check:
        for problem in problems:
            print(f"  FAIL  {problem}")
        print(f"\n{'command render drift' if problems else 'every host copy matches its canonical body'}"
              f" — {len(problems)} problem(s)")
        return 1 if problems else 0
    for gap in missing:
        print(f"  note  {gap}")
    print(f"rendered {written} host file(s) from {len(names)} canonical body/bodies"
          + (f"; {len(missing)} host/command pair(s) left alone" if missing else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
