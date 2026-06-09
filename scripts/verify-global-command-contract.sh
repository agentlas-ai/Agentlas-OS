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
  "codex/plugins/agentlas-core-engine-meta-agent/commands/hephaestus.md"
  "gemini/extension/commands/hephaestus.toml"
  ".gemini/commands/hephaestus.toml"
  "gemini/extension/gemini-extension.json"
  "antigravity/workflows/hephaestus.md"
  ".agents/workflows/hephaestus.md"
  "AGENTS.md"
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

commands = {item["runtime"]: item for item in registry.get("commands", [])}
required = {
    "claude-code": ".claude/commands/hephaestus.md",
    "codex": "codex/plugins/agentlas-core-engine-meta-agent/commands/hephaestus.md",
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

for runtime in ("claude-code", "codex", "gemini-cli", "antigravity", "generic-agents-md"):
    if commands[runtime].get("command") != command:
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
