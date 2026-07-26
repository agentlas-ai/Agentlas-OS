#!/usr/bin/env bash
# Verify that a generated Agentlas package is exactly one valid shape:
# single-agent or orchestrated team. This gate checks generated package roots,
# not this meta-agent repository.
#
# Usage:
#   scripts/verify-team-package.sh [folder]   # default: .
#
# Exit codes: 0 = valid single/team shape, 1 = malformed or degenerate shape.
set -euo pipefail

target="${1:-.}"

if [[ ! -d "$target" ]]; then
  echo "verify-team-package: FAIL - target is not a directory: $target" >&2
  exit 1
fi

python3 - "$target" <<'PY'
import json
import re
import sys
from pathlib import Path
from typing import Any

root = Path(sys.argv[1]).resolve()
errors: list[str] = []
notes: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def rel(path: Path) -> str:
    return path.relative_to(root).as_posix()


def load_blueprint() -> dict[str, Any]:
    path = root / ".agentlas" / "company-blueprint.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid .agentlas/company-blueprint.json: {exc}")
        return {}
    if not isinstance(value, dict):
        fail(".agentlas/company-blueprint.json must be a JSON object")
        return {}
    return value


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def agent_files() -> list[Path]:
    visible = sorted((root / "agents").glob("*/agent.md"))
    if visible:
        return visible
    return sorted((root / ".agents").glob("*/agent.md"))


def collect_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, str):
        refs.add(value)
    elif isinstance(value, dict):
        for key in ("id", "name", "role", "path", "agent", "node"):
            nested = value.get(key)
            if isinstance(nested, str):
                refs.add(nested)
        for nested in value.values():
            refs.update(collect_refs(nested))
    elif isinstance(value, list):
        for nested in value:
            refs.update(collect_refs(nested))
    return refs


blueprint = load_blueprint()
topology = blueprint.get("topology") if isinstance(blueprint.get("topology"), str) else ""
nodes = blueprint.get("nodes") if isinstance(blueprint.get("nodes"), list) else []
edges = blueprint.get("edges") if isinstance(blueprint.get("edges"), list) else []
orchestrator_refs = {
    normalize(ref)
    for key in ("orchestrator", "router")
    for ref in collect_refs(blueprint.get(key))
    if ref
}


def node_strings_for_agent(path: Path) -> set[str]:
    strings = {path.parent.name, rel(path)}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_path = node.get("path")
        if isinstance(node_path, str) and normalize(node_path) == normalize(rel(path)):
            for key in ("id", "name", "role", "path", "type"):
                value = node.get(key)
                if isinstance(value, str):
                    strings.add(value)
    return {normalize(value) for value in strings if value}


def is_orchestrator_path(path: Path) -> bool:
    name = normalize(path.parent.name)
    return (
        name == "00-orchestrator"
        or name == "orchestrator"
        or name == "hq"
        or name.endswith("-orchestrator")
        or name.endswith("-hq")
    )


def is_orchestrator_agent(path: Path) -> bool:
    return is_orchestrator_path(path) or bool(orchestrator_refs & node_strings_for_agent(path))


agents = agent_files()
orchestrator_agents = [path for path in agents if is_orchestrator_agent(path)]
worker_agents = [path for path in agents if path not in orchestrator_agents]


def blueprint_points_to_orchestrator_node() -> bool:
    if not orchestrator_refs:
        return False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        strings = {
            normalize(str(node.get(key, "")))
            for key in ("id", "name", "role", "path", "type")
            if node.get(key)
        }
        if orchestrator_refs & strings:
            return True
    return False


has_orchestrator = bool(orchestrator_agents) or blueprint_points_to_orchestrator_node()
worker_count = len(worker_agents)


def iter_package_paths() -> list[str]:
    results: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", "__pycache__", "node_modules", ".venv"} for part in path.parts):
            continue
        results.append(rel(path))
    return results


path_haystack = "\n".join(normalize(path) for path in iter_package_paths())
blueprint_haystack_parts: list[str] = []
for node in nodes:
    if not isinstance(node, dict):
        continue
    for key in ("id", "name", "role", "path", "type"):
        value = node.get(key)
        if isinstance(value, str):
            blueprint_haystack_parts.append(normalize(value))
blueprint_haystack = "\n".join(blueprint_haystack_parts)
haystack = f"{path_haystack}\n{blueprint_haystack}"


def has_component(label: str, needles: list[str]) -> bool:
    for needle in needles:
        if normalize(needle) in haystack:
            return True
    fail(f"missing TEAM requirement: {label} role or contract file")
    return False


def check_global_command() -> None:
    path = root / ".agentlas" / "global-commands.json"
    if not path.exists():
        fail("missing TEAM requirement: .agentlas/global-commands.json")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid .agentlas/global-commands.json: {exc}")
        return
    commands = payload.get("commands")
    canonical = payload.get("canonicalCommand")
    if not isinstance(canonical, str) or not canonical.strip():
        fail("missing TEAM requirement: .agentlas/global-commands.json canonicalCommand")
        return
    if not isinstance(commands, list) or not commands:
        fail("missing TEAM requirement: .agentlas/global-commands.json commands")
        return

    def command_token(value: str) -> str:
        token = value.strip()
        if token.startswith("/prompts:"):
            token = "/" + token.split(":", 1)[1]
        elif not token.startswith("/"):
            token = "/" + token
        return token

    distinct = {
        command_token(command.get("command", ""))
        for command in commands
        if isinstance(command, dict) and isinstance(command.get("command"), str) and command.get("command", "").strip()
    }
    canonical_token = command_token(canonical)
    if canonical_token not in distinct:
        fail("TEAM global commands must expose the HQ canonicalCommand")
    if len(distinct) != 1:
        fail(f"TEAM global commands must expose one public HQ command, found {sorted(distinct)}")


def runtime_execution_graph_declared() -> tuple[bool, str]:
    """Can the Hub runtime build this package as a team?

    Structural checks above prove the FILES exist. The runtime instead reads a
    declared manager and roster, and a package can satisfy every check here and
    still be uncallable once published — which is how 26 published teams became
    unsellable. Mirror exactly what the runtime accepts so the failure surfaces
    while the author still has the package.
    """
    manager_keys = ("entrypoints.orchestrator", "entrypoint", "orchestrator", "entry")
    roster_keys = ("roster", "workers", "members", "team", "agents")
    containers = (
        "agents", "team", "teams", "crew", "members", "roles",
        "subagents", "sub-agents", "squad", "staff", "hr-departments", "departments",
    )

    team_manifest = load_json(root / "manifest.json") or {}
    package_manifest = load_json(root / "agentlas.json") or {}

    def manager_from(doc: dict, allow_entry: bool) -> str:
        entrypoints = doc.get("entrypoints")
        if isinstance(entrypoints, dict) and isinstance(entrypoints.get("orchestrator"), str):
            return entrypoints["orchestrator"]
        for key in ("entrypoint", "orchestrator"):
            if isinstance(doc.get(key), str):
                return doc[key]
        # `entry` is the PACKAGE entrypoint in agentlas.json and the TEAM manager
        # only in the team's own manifest.json.
        if allow_entry and isinstance(doc.get("entry"), str):
            return doc["entry"]
        return ""

    manager = manager_from(team_manifest, allow_entry=True) or manager_from(package_manifest, allow_entry=False)
    if not manager:
        return False, (
            "runtime cannot find a manager: declare it as "
            f"{manager_keys[0]} in manifest.json (or {', '.join(manager_keys[1:])})"
        )

    declared_roster = next(
        (team_manifest[key] for key in roster_keys if isinstance(team_manifest.get(key), list) and team_manifest[key]),
        None,
    )
    if declared_roster:
        return True, ""
    for container in containers:
        base = root / container
        if not base.is_dir():
            continue
        if any(base.glob("*/agent.md")) or any(base.glob("*/AGENTS.md")) or any(base.glob("*.md")):
            return True, ""
    return False, (
        "runtime cannot find a roster: declare `roster` in manifest.json or place each "
        f"member under one of {', '.join(containers[:4])}/<name>/agent.md"
    )


if worker_count >= 2 or topology not in ("", "single-agent"):
    graph_ok, graph_detail = runtime_execution_graph_declared()
    if not graph_ok:
        fail(f"team package would not be callable after publishing — {graph_detail}")

if worker_count == 0:
    fail("no worker agent.md files found under agents/*/agent.md or .agents/*/agent.md")
elif worker_count == 1:
    if topology == "single-agent" and not has_orchestrator:
        notes.append(f"PASS(single): 1 worker, topology={topology}")
    elif topology == "single-agent" and has_orchestrator:
        fail("contradiction: topology single-agent must not include an orchestrator/HQ")
    else:
        fail(f"contradiction: 1 worker requires topology single-agent, found {topology or 'missing'}")
else:
    if topology == "single-agent":
        fail(f"contradiction: topology single-agent with {worker_count} worker agent.md files")
    if not has_orchestrator:
        fail(
            f"degenerate team: {worker_count} workers without an orchestrator/HQ — "
            "collapse to a single-agent package or add an orchestrator/HQ + blueprint topology"
        )
    if not blueprint:
        fail("missing TEAM requirement: .agentlas/company-blueprint.json")
    if not topology:
        fail("missing TEAM requirement: company-blueprint topology")
    if not nodes:
        fail("missing TEAM requirement: company-blueprint nodes")
    if not edges:
        fail("missing TEAM requirement: company-blueprint edges")
    has_component("PM Soul", ["pm-soul", "pm soul", "project-owner", "project owner"])
    has_component("Memory Curator", ["memory-curator", "memory curator"])
    has_component("Policy Gate", ["policy-gate", "policy gate"])
    has_component("eval judge", ["eval-judge", "eval judge", "evaluation-judge", "evaluation judge"])
    has_component("QA/evidence gate", ["qa-evidence-gate", "qa evidence gate", "evidence-gate", "evidence gate"])
    if not (root / ".agentlas" / "memory-map.json").exists():
        fail("missing TEAM requirement: .agentlas/memory-map.json")
    if not (root / ".agentlas" / "memory-tickets.jsonl").exists():
        fail("missing TEAM requirement: .agentlas/memory-tickets.jsonl")
    check_global_command()
    if not errors:
        notes.append(
            f"PASS(team): {worker_count} workers, orchestrator/HQ present, topology={topology}"
        )

if errors:
    print(f"verify-team-package: FAIL {root}")
    print(f"workers={worker_count}; orchestrators={len(orchestrator_agents)}; topology={topology or 'missing'}")
    for message in errors:
        print(f"- {message}")
    raise SystemExit(1)

print(f"verify-team-package: {notes[0] if notes else 'PASS'}")
print(f"root={root}")
print(f"workers={worker_count}; orchestrators={len(orchestrator_agents)}; topology={topology}")
PY
