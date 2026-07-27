#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

fail() {
  echo "verify-global-command-contract: $*" >&2
  exit 1
}

required_files=(
  "docs/global-command-contract.md"
  ".agentlas/global-commands.json"
  "schemas/global-commands.schema.json"
  "templates/global-commands.json.tpl"
  "templates/antigravity-workflow.md.tpl"
  ".claude/commands/hep-build.md"
  ".claude/commands/hep-network.md"
  ".claude/commands/hep-storm.md"
  ".claude/commands/hep-cloud.md"
  ".claude/commands/hep-search.md"
  ".claude/commands/hep-browser.md"
  ".claude/commands/hep-call.md"
  ".claude/commands/hep-upload.md"
  ".claude/commands/hep-connect.md"
  "codex/prompts/hep-build.md"
  "codex/prompts/hep-network.md"
  "codex/prompts/hep-storm.md"
  "codex/prompts/hep-cloud.md"
  "codex/prompts/hep-search.md"
  "codex/prompts/hep-browser.md"
  "codex/prompts/hep-call.md"
  "codex/prompts/hep-upload.md"
  "codex/prompts/hep-connect.md"
  "gemini/extension/commands/hep-build.toml"
  "gemini/extension/commands/hep-network.toml"
  "gemini/extension/commands/hep-storm.toml"
  "gemini/extension/commands/hep-cloud.toml"
  "gemini/extension/commands/hep-search.toml"
  "gemini/extension/commands/hep-browser.toml"
  "gemini/extension/commands/hep-call.toml"
  "gemini/extension/commands/hep-upload.toml"
  ".gemini/commands/hep-build.toml"
  ".gemini/commands/hep-network.toml"
  ".gemini/commands/hep-storm.toml"
  ".gemini/commands/hep-cloud.toml"
  ".gemini/commands/hep-search.toml"
  ".gemini/commands/hep-browser.toml"
  ".gemini/commands/hep-call.toml"
  ".gemini/commands/hep-upload.toml"
  "gemini/extension/gemini-extension.json"
  "antigravity/workflows/hep-build.md"
  "antigravity/workflows/hep-network.md"
  "antigravity/workflows/hep-storm.md"
  "antigravity/workflows/hep-cloud.md"
  "antigravity/workflows/hep-search.md"
  "antigravity/workflows/hep-browser.md"
  "antigravity/workflows/hep-call.md"
  "antigravity/workflows/hep-upload.md"
  ".agents/workflows/hep-build.md"
  ".agents/workflows/hep-network.md"
  ".agents/workflows/hep-storm.md"
  ".agents/workflows/hep-cloud.md"
  ".agents/workflows/hep-search.md"
  ".agents/workflows/hep-browser.md"
  ".agents/workflows/hep-call.md"
  ".agents/workflows/hep-upload.md"
  ".agents/workflows/hep-connect.md"
  "AGENTS.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-build.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-network.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-storm.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-cloud.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-search.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-browser.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-call.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-upload.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-connect.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-build/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-network/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-storm/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-cloud/SKILL.md"
  "skills/hephaestus-network/SKILL.md"
  "skills/hephaestus-storm/SKILL.md"
  "skills/hephaestus-cloud/SKILL.md"
  ".agents/skills/hephaestus-network/SKILL.md"
  ".agents/skills/hephaestus-storm/SKILL.md"
  ".agents/skills/hephaestus-cloud/SKILL.md"
  "cursor/rules/hephaestus.mdc"
  "cursor/plugin/commands/hep-build.md"
  "cursor/plugin/commands/hep-network.md"
  "cursor/plugin/commands/hep-storm.md"
  "cursor/plugin/commands/hep-cloud.md"
  "cursor/plugin/commands/hep-search.md"
  "cursor/plugin/commands/hep-browser.md"
  "cursor/plugin/commands/hep-call.md"
  "cursor/plugin/commands/hep-upload.md"
  "opencode/commands/hep-build.md"
  "opencode/commands/hep-network.md"
  "opencode/commands/hep-storm.md"
  "opencode/commands/hep-cloud.md"
  "opencode/commands/hep-search.md"
  "opencode/commands/hep-browser.md"
  "opencode/commands/hep-call.md"
  "opencode/commands/hep-upload.md"
  "openclaw/skills/hephaestus-network/SKILL.md"
  "openclaw/skills/hephaestus-storm/SKILL.md"
  "openclaw/skills/hephaestus-cloud/SKILL.md"
  "hermes/skills/hephaestus-network/SKILL.md"
  "hermes/skills/hephaestus-storm/SKILL.md"
  "hermes/skills/hephaestus-cloud/SKILL.md"
  "bin/hep-build"
  "bin/hep-network"
  "bin/hep-cloud"
  "bin/hep-search"
  "bin/hep-browser"
  "bin/hep-call"
  "bin/hep-upload"
  "bin/hep-storm"
  "agentlas_cloud/mcp_stdio.py"
  "docs/local-models.md"
  "docs/hephaestus-network-2.0.md"
  "docs/runtime-fallback-adapters.md"
  "schemas/routing-card.schema.json"
)

for path in "${required_files[@]}"; do
  [[ -e "$path" ]] || fail "missing required file: $path"
done

python3 - <<'PY'
import json
import re
from pathlib import Path

registry = json.loads(Path(".agentlas/global-commands.json").read_text(encoding="utf-8"))
command = registry.get("canonicalCommand")
if not re.fullmatch(r"/[a-z0-9][a-z0-9-]*(?::[a-z0-9][a-z0-9-]*)?", command or ""):
    raise SystemExit(f"invalid canonicalCommand: {command!r}")

# A runtime may expose several commands; validate the canonical one per runtime.
commands = {}
for item in registry.get("commands", []):
    commands.setdefault(item["runtime"], item)
    if item.get("command") == command:
        commands[item["runtime"]] = item

build_commands = [item for item in registry.get("commands", []) if item.get("command") == "/hep-build"]
if len(build_commands) < 4:
    raise SystemExit("expected /hep-build entries for at least claude-code, codex, gemini-cli, antigravity")
for item in build_commands:
    adapter = item.get("adapterPath")
    if not adapter or not Path(adapter).exists():
        raise SystemExit(f"/hep-build adapter missing: {adapter}")

network_commands = [item for item in registry.get("commands", []) if item.get("command") == "/hep-network"]
if len(network_commands) < 4:
    raise SystemExit("expected /hep-network entries for at least claude-code, codex, gemini-cli, antigravity")
for item in network_commands:
    adapter = item.get("adapterPath")
    if not adapter or not Path(adapter).exists():
        raise SystemExit(f"/hep-network adapter missing: {adapter}")
terminal_aliases = {
    item.get("command"): item
    for item in registry.get("commands", [])
    if item.get("runtime") == "agentlas-terminal"
}
for alias_command, adapter in {
    "hep-build": "bin/hep-build",
    "hep-network": "bin/hep-network",
    "hep-cloud": "bin/hep-cloud",
    "hep-search": "bin/hep-search",
    "hep-browser": "bin/hep-browser",
    "hep-call": "bin/hep-call",
    "hep-upload": "bin/hep-upload",
    "hep-storm": "bin/hep-storm",
}.items():
    item = terminal_aliases.get(alias_command)
    if not item:
        raise SystemExit(f"missing terminal alias: {alias_command}")
    if item.get("adapterPath") != adapter:
        raise SystemExit(f"{alias_command} adapterPath mismatch: {item.get('adapterPath')} != {adapter}")
    if not Path(adapter).exists():
        raise SystemExit(f"{alias_command} adapter file does not exist: {adapter}")

for command_name in ("/hep-search", "/prompts:hep-search", "/hep-browser", "/prompts:hep-browser", "/hep-call", "/prompts:hep-call", "/hep-upload", "/prompts:hep-upload", "/hep-connect", "/prompts:hep-connect", "hephaestus_search", "hephaestus_call"):
    if not any(item.get("command") == command_name for item in registry.get("commands", [])):
        raise SystemExit(f"missing power-user command registry entry: {command_name}")
connect_entries = {
    item["runtime"]: item
    for item in registry.get("commands", [])
    if item.get("command") in ("/hep-connect", "/prompts:hep-connect")
}
for runtime, adapter in {
    "claude-code": ".claude/commands/hep-connect.md",
    "codex": "codex/prompts/hep-connect.md",
    "agentlas-workflow": ".agents/workflows/hep-connect.md",
}.items():
    item = connect_entries.get(runtime)
    if not item:
        raise SystemExit(f"missing /hep-connect registry entry for {runtime}")
    if item.get("adapterPath") != adapter:
        raise SystemExit(f"{runtime} /hep-connect adapterPath mismatch: {item.get('adapterPath')} != {adapter}")
    if not Path(adapter).exists():
        raise SystemExit(f"{runtime} /hep-connect adapter file does not exist: {adapter}")
required = {
    "claude-code": ".claude/commands/hep-build.md",
    "codex": "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-build/SKILL.md",
    "gemini-cli": "gemini/extension/commands/hep-build.toml",
    "antigravity": "antigravity/workflows/hep-build.md",
    "generic-agents-md": "AGENTS.md",
    "agentlas-terminal": "bin/hep-build",
}
for runtime, adapter in required.items():
    item = commands.get(runtime)
    if not item:
        raise SystemExit(f"missing runtime command: {runtime}")
    if item.get("adapterPath") != adapter:
        raise SystemExit(f"{runtime} adapterPath mismatch: {item.get('adapterPath')} != {adapter}")
    if not Path(adapter).exists():
        raise SystemExit(f"{runtime} adapter file does not exist: {adapter}")

prompt_namespaced = "/prompts:" + command.lstrip("/")
for runtime in ("claude-code", "codex", "gemini-cli", "antigravity", "generic-agents-md"):
    expected_commands = (
        ("$hephaestus-build",)
        if runtime == "codex"
        else (command, prompt_namespaced)
    )
    if commands[runtime].get("command") not in expected_commands:
        raise SystemExit(f"{runtime} command does not match canonical command")

codex_network = next(
    (
        item
        for item in registry.get("commands", [])
        if item.get("runtime") == "codex"
        and item.get("command") == "$hephaestus-network"
    ),
    None,
)
if not codex_network:
    raise SystemExit("missing current Codex $hephaestus-network skill entry")
if codex_network.get("adapterPath") != "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-network/SKILL.md":
    raise SystemExit("Codex network skill adapter path mismatch")

message = registry.get("postCreationUserMessage", {})
if message.get("required") is not True:
    raise SystemExit("postCreationUserMessage.required must be true")
template = message.get("template", "")
for expected in ("Claude Code", "Codex", "Gemini CLI", "Antigravity", "Agentlas terminal"):
    if expected not in template:
        raise SystemExit(f"post creation template missing {expected}")
PY

require_pattern() {
  local path="$1"
  local pattern="$2"
  rg -q "$pattern" "$path" || fail "missing pattern in $path: $pattern"
}

require_pattern AGENTS.md '\.agentlas/global-commands\.json'
require_pattern agent.md 'global_commands'
require_pattern agents/10-single-agent-builder/agent.md 'global command'
require_pattern agents/20-multi-agent-team-builder/agent.md 'orchestrator/HQ global command'
require_pattern agents/30-agentlas-packager/agent.md 'global command'
require_pattern modes/single-agent-creator.md '\.agentlas/global-commands\.json'
require_pattern modes/team-builder.md '\.agentlas/global-commands\.json'
require_pattern modes/agentlas-packager.md '\.agentlas/global-commands\.json'
require_pattern docs/llm-runtime-architecture.md 'Global Command'
require_pattern docs/global-command-contract.md 'post-creation'
require_pattern templates/AGENTS.md.tpl 'Global Command'
require_pattern templates/runtime-matrix.md.tpl 'Global Command'

# Generated packages must also receive an Antigravity workflow surface.
require_pattern templates/global-commands.json.tpl '"runtime": "antigravity"'
require_pattern templates/global-commands.json.tpl 'antigravity/workflows'
require_pattern templates/antigravity-workflow.md.tpl 'COMMAND_SLUG'
require_pattern templates/antigravity-workflow.md.tpl 'global_workflows'
require_pattern templates/AGENTS.md.tpl 'Antigravity'
require_pattern templates/runtime-matrix.md.tpl 'Antigravity'
require_pattern agents/10-single-agent-builder/agent.md 'Antigravity'
require_pattern agents/20-multi-agent-team-builder/agent.md 'Antigravity'
require_pattern agents/30-agentlas-packager/agent.md 'Antigravity'
require_pattern modes/single-agent-creator.md 'Antigravity'
require_pattern modes/team-builder.md 'Antigravity'
require_pattern modes/agentlas-packager.md 'Antigravity'
require_pattern codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-build/SKILL.md 'global_commands'
require_pattern claude/plugins/agentlas-core-engine-meta-agent/commands/hep-build.md 'global_commands'

echo "Global command contract verification passed."
