#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

fail() {
  echo "verify-builder-quality-contract: $*" >&2
  exit 1
}

need_file() {
  [[ -f "$1" ]] || fail "missing required file: $1"
}

need_pattern() {
  local path="$1"
  local pattern="$2"
  rg -q "$pattern" "$path" || fail "missing pattern in $path: $pattern"
}

required_files=(
  "docs/builder-interview-research-gate.md"
  "docs/builder-quality-research-basis.md"
  "templates/builder-interview.md.tpl"
  "templates/research-sources.md.tpl"
  "templates/tool-selection.md.tpl"
  "templates/domain-expert-synthesis.md.tpl"
  "templates/prompt-performance-contract.md.tpl"
  "templates/capability-eval-plan.json.tpl"
)

for path in "${required_files[@]}"; do
  need_file "$path"
done

core_files=(
  "AGENTS.md"
  "agent.md"
  ".agents/agentlas-core-engine-meta-agent/agent.md"
  "agents/10-single-agent-builder/agent.md"
  "agents/20-multi-agent-team-builder/agent.md"
  "agents/30-agentlas-packager/agent.md"
  "modes/single-agent-creator.md"
  "modes/team-builder.md"
  "modes/agentlas-packager.md"
  "skills/self-evolving-single-agent/SKILL.md"
  "skills/team-builder-packaging/SKILL.md"
  "skills/agentlas-packaging/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-build/SKILL.md"
)

for path in "${core_files[@]}"; do
  need_pattern "$path" "builder-interview-research-gate"
  need_pattern "$path" "docs/builder-interview.md"
  need_pattern "$path" "docs/research-sources.md"
  need_pattern "$path" "docs/tool-selection.md"
  need_pattern "$path" "docs/domain-expert-synthesis.md"
  need_pattern "$path" "docs/prompt-performance-contract.md"
  need_pattern "$path" "capability-eval-plan"
  need_pattern "$path" "similar agent"
  need_pattern "$path" "academic"
done

runtime_files=(
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hephaestus-build.md"
  ".claude/commands/hephaestus-build.md"
  "codex/prompts/hephaestus-build.md"
  "gemini/extension/commands/hephaestus-build.toml"
  ".gemini/commands/hephaestus-build.toml"
  "antigravity/workflows/hephaestus-build.md"
  ".agents/workflows/hephaestus-build.md"
  "cursor/plugin/commands/hephaestus-build.md"
  "opencode/commands/hephaestus-build.md"
)

for path in "${runtime_files[@]}"; do
  need_pattern "$path" "Builder Interview"
  need_pattern "$path" "8-12"
  need_pattern "$path" "interview_research"
  need_pattern "$path" "similar agent"
  need_pattern "$path" "academic/professional"
  need_pattern "$path" "docs/domain-expert-synthesis.md"
done

template_files=(
  "templates/AGENTS.md.tpl"
  "templates/runtime-matrix.md.tpl"
)

for path in "${template_files[@]}"; do
  need_pattern "$path" "docs/builder-interview.md"
  need_pattern "$path" "docs/research-sources.md"
  need_pattern "$path" "docs/tool-selection.md"
  need_pattern "$path" "docs/domain-expert-synthesis.md"
  need_pattern "$path" "docs/prompt-performance-contract.md"
  need_pattern "$path" "capability-eval-plan"
done

need_pattern "docs/builder-interview-research-gate.md" "Ask a first batch of 8-12"
need_pattern "docs/builder-interview-research-gate.md" "official documentation or primary sources"
need_pattern "docs/builder-interview-research-gate.md" "similar agent repositories"
need_pattern "docs/builder-interview-research-gate.md" "academic papers"
need_pattern "docs/builder-interview-research-gate.md" "docs/domain-expert-synthesis.md"
need_pattern "docs/builder-interview-research-gate.md" "Tool and Plugin Selection"
need_pattern "docs/builder-interview-research-gate.md" "Prompt Performance Contract"
need_pattern "docs/builder-quality-research-basis.md" "ReAct"
need_pattern "docs/builder-quality-research-basis.md" "Reflexion"
need_pattern "docs/builder-quality-research-basis.md" "DSPy"

echo "Builder quality contract verification passed."
