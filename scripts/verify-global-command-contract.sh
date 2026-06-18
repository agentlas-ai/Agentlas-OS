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
  ".claude/commands/hephaestus.md"
  "codex/prompts/hephaestus.md"
  "gemini/extension/commands/hephaestus.toml"
  ".gemini/commands/hephaestus.toml"
  "gemini/extension/gemini-extension.json"
  "antigravity/workflows/hephaestus.md"
  ".agents/workflows/hephaestus.md"
  "AGENTS.md"
  ".claude/commands/hephaestus-network.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hephaestus-network.md"
  "codex/prompts/hephaestus-network.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-network/SKILL.md"
  "gemini/extension/commands/hephaestus-network.toml"
  ".gemini/commands/hephaestus-network.toml"
  "antigravity/workflows/hephaestus-network.md"
  ".agents/workflows/hephaestus-network.md"
  "skills/hephaestus-network/SKILL.md"
  ".agents/skills/hephaestus-network/SKILL.md"
  "cursor/rules/hephaestus.mdc"
  "cursor/plugin/commands/hephaestus-network.md"
  "opencode/commands/hephaestus-network.md"
  "openclaw/skills/hephaestus-network/SKILL.md"
  "hermes/skills/hephaestus-network/SKILL.md"
  "bin/hephaests-network"
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

# A runtime may expose several commands (e.g. /hephaestus and
# /hephaestus-network); validate the canonical one per runtime.
commands = {}
for item in registry.get("commands", []):
    commands.setdefault(item["runtime"], item)
    if item.get("command") == command:
        commands[item["runtime"]] = item

network_commands = [item for item in registry.get("commands", []) if item.get("command") == "/hephaestus-network"]
if len(network_commands) < 4:
    raise SystemExit("expected /hephaestus-network entries for at least claude-code, codex, gemini-cli, antigravity")
for item in network_commands:
    adapter = item.get("adapterPath")
    if not adapter or not Path(adapter).exists():
        raise SystemExit(f"/hephaestus-network adapter missing: {adapter}")
terminal_aliases = {
    item.get("command"): item
    for item in registry.get("commands", [])
    if item.get("runtime") == "agentlas-terminal"
}
for alias_command, adapter in {
    "Hephaestus": "bin/hephaestus",
    "hephaests-network": "bin/hephaests-network",
}.items():
    item = terminal_aliases.get(alias_command)
    if not item:
        raise SystemExit(f"missing terminal alias: {alias_command}")
    if item.get("adapterPath") != adapter:
        raise SystemExit(f"{alias_command} adapterPath mismatch: {item.get('adapterPath')} != {adapter}")
    if not Path(adapter).exists():
        raise SystemExit(f"{alias_command} adapter file does not exist: {adapter}")
required = {
    "claude-code": ".claude/commands/hephaestus.md",
    "codex": "codex/prompts/hephaestus.md",
    "gemini-cli": "gemini/extension/commands/hephaestus.toml",
    "antigravity": "antigravity/workflows/hephaestus.md",
    "generic-agents-md": "AGENTS.md",
    "agentlas-terminal": "bin/hephaestus",
}
for runtime, adapter in required.items():
    item = commands.get(runtime)
    if not item:
        raise SystemExit(f"missing runtime command: {runtime}")
    if item.get("adapterPath") != adapter:
        raise SystemExit(f"{runtime} adapterPath mismatch: {item.get('adapterPath')} != {adapter}")
    if not Path(adapter).exists():
        raise SystemExit(f"{runtime} adapter file does not exist: {adapter}")

# Codex plugins cannot register slash commands; the explicit surface is the
# /prompts: namespace, so the canonical command appears as /prompts:<name>.
prompt_namespaced = "/prompts:" + command.lstrip("/")
for runtime in ("claude-code", "codex", "gemini-cli", "antigravity", "generic-agents-md"):
    if commands[runtime].get("command") not in (command, prompt_namespaced):
        raise SystemExit(f"{runtime} command does not match canonical command")

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
require_pattern codex/plugins/agentlas-core-engine-meta-agent/skills/agentlas-core-engine-meta-agent/SKILL.md 'global_commands'
require_pattern claude/plugins/agentlas-core-engine-meta-agent/SKILL.md 'global_commands'

echo "Global command contract verification passed."
