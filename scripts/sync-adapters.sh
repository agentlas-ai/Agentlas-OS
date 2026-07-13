#!/usr/bin/env bash
# C-1: keep runtime code adapters as exact mirrors of the canonical core.
#
# Code assets (career_graph/, ontology/, agentlas_cloud/, bin/hephaestus) must be
# byte-identical in every runtime adapter directory — adapters mirror the
# canonical core, they are never a second source. SKILL.md adapters are
# intentionally condensed per runtime and are NOT byte-checked here.
#
# Usage:
#   scripts/sync-adapters.sh           # render core into adapter mirrors
#   scripts/sync-adapters.sh --check   # fail on drift (CI / verify-package)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

mode="${1:-sync}"

plugin_roots=(
  "claude/plugins/agentlas-core-engine-meta-agent"
  "codex/plugins/agentlas-core-engine-meta-agent"
)

code_dirs=(
  "career_graph"
  "ontology"
  "agentlas_cloud"
  "templates"
)

code_files=(
  "bin/hephaestus"
  "bin/career-graph"
  "bin/hep-build"
  "bin/hep-network"
  "bin/hep-cloud"
  "bin/hep-search"
  "bin/hep-browser"
  "bin/hep-call"
  "bin/hep-upload"
  "bin/hep-storm"
  "bin/hep-global"
  "bin/hephaestus.cmd"
)

# Byte-mirrored skill copies at the repo root (.agents/skills); plugin skill
# files are condensed adapters and excluded on purpose.
#
# Exception: hephaestus-network is byte-identical EVERYWHERE — it is the
# universal AgentSkills-spec surface (Codex, OpenCode, OpenClaw, Cursor, Crush,
# Hermes all read ~/.agents/skills), so the canonical copy is mirrored into
# every runtime adapter. The OpenClaw copy is NOT mirrored (it carries an extra
# metadata frontmatter line); keep its body in sync manually.
skill_mirrors=(
  "skills/mode-classification/SKILL.md:.agents/skills/mode-classification/SKILL.md"
  "skills/clarify-question-loop/SKILL.md:.agents/skills/clarify-question-loop/SKILL.md"
  "skills/agentlas-auto-activation/SKILL.md:.agents/skills/agentlas-auto-activation/SKILL.md"
  "skills/skill-lifecycle-promotion/SKILL.md:.agents/skills/skill-lifecycle-promotion/SKILL.md"
  "skills/hephaestus-network/SKILL.md:.agents/skills/hephaestus-network/SKILL.md"
  "skills/hephaestus-network/SKILL.md:codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-network/SKILL.md"
  "skills/hephaestus-network/SKILL.md:gemini/extension/skills/hephaestus-network/SKILL.md"
  "skills/hephaestus-network/SKILL.md:cursor/plugin/skills/hephaestus-network/SKILL.md"
  "skills/hephaestus-network/SKILL.md:hermes/skills/hephaestus-network/SKILL.md"
  "skills/hephaestus-cloud/SKILL.md:.agents/skills/hephaestus-cloud/SKILL.md"
  "skills/hephaestus-cloud/SKILL.md:codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-cloud/SKILL.md"
  "skills/hephaestus-cloud/SKILL.md:gemini/extension/skills/hephaestus-cloud/SKILL.md"
  "skills/hephaestus-cloud/SKILL.md:cursor/plugin/skills/hephaestus-cloud/SKILL.md"
  "skills/hephaestus-cloud/SKILL.md:hermes/skills/hephaestus-cloud/SKILL.md"
  "skills/hephaestus-storm/SKILL.md:.agents/skills/hephaestus-storm/SKILL.md"
  "skills/hephaestus-storm/SKILL.md:codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-storm/SKILL.md"
  "skills/hephaestus-storm/SKILL.md:hermes/skills/hephaestus-storm/SKILL.md"
  ".agentlas/routing-card.json:claude/plugins/agentlas-core-engine-meta-agent/.agentlas/routing-card.json"
  ".agentlas/routing-card.json:codex/plugins/agentlas-core-engine-meta-agent/.agentlas/routing-card.json"
  ".agentlas/routing-card.json:gemini/extension/.agentlas/routing-card.json"
  "cursor/rules/hephaestus.mdc:cursor/plugin/rules/hephaestus.mdc"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-build.md:.claude/commands/hep-build.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-network.md:.claude/commands/hep-network.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-cloud.md:.claude/commands/hep-cloud.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-search.md:.claude/commands/hep-search.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-browser.md:.claude/commands/hep-browser.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-call.md:.claude/commands/hep-call.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-upload.md:.claude/commands/hep-upload.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-connect.md:.claude/commands/hep-connect.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-storm.md:.claude/commands/hep-storm.md"
  "gemini/extension/commands/hep-build.toml:.gemini/commands/hep-build.toml"
  "gemini/extension/commands/hep-network.toml:.gemini/commands/hep-network.toml"
  "gemini/extension/commands/hep-cloud.toml:.gemini/commands/hep-cloud.toml"
  "gemini/extension/commands/hep-search.toml:.gemini/commands/hep-search.toml"
  "gemini/extension/commands/hep-browser.toml:.gemini/commands/hep-browser.toml"
  "gemini/extension/commands/hep-call.toml:.gemini/commands/hep-call.toml"
  "gemini/extension/commands/hep-upload.toml:.gemini/commands/hep-upload.toml"
  "gemini/extension/commands/hep-storm.toml:.gemini/commands/hep-storm.toml"
  "antigravity/workflows/hep-build.md:.agents/workflows/hep-build.md"
  "antigravity/workflows/hep-network.md:.agents/workflows/hep-network.md"
  "antigravity/workflows/hep-cloud.md:.agents/workflows/hep-cloud.md"
  "antigravity/workflows/hep-search.md:.agents/workflows/hep-search.md"
  "antigravity/workflows/hep-browser.md:.agents/workflows/hep-browser.md"
  "antigravity/workflows/hep-call.md:.agents/workflows/hep-call.md"
  "antigravity/workflows/hep-upload.md:.agents/workflows/hep-upload.md"
  "antigravity/workflows/hep-storm.md:.agents/workflows/hep-storm.md"
)

drift=0

check_dir() {
  local src="$1" dest="$2"
  if ! diff -rq -x "__pycache__" -x ".DS_Store" "$src" "$dest" > /dev/null 2>&1; then
    echo "adapter drift: $dest != $src" >&2
    drift=1
  fi
}

check_file() {
  local src="$1" dest="$2"
  if ! diff -q "$src" "$dest" > /dev/null 2>&1; then
    echo "adapter drift: $dest != $src" >&2
    drift=1
  fi
}

sync_dir() {
  local src="$1" dest="$2"
  mkdir -p "$dest"
  rsync -a --delete --exclude "__pycache__" --exclude ".DS_Store" "$src/" "$dest/"
}

sync_file() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
}

for plugin in "${plugin_roots[@]}"; do
  for dir in "${code_dirs[@]}"; do
    if [[ "$mode" == "--check" ]]; then
      check_dir "$dir" "$plugin/$dir"
    else
      sync_dir "$dir" "$plugin/$dir"
    fi
  done
  for file in "${code_files[@]}"; do
    if [[ "$mode" == "--check" ]]; then
      check_file "$file" "$plugin/$file"
    else
      sync_file "$file" "$plugin/$file"
    fi
  done
done

for pair in "${skill_mirrors[@]}"; do
  src="${pair%%:*}"
  dest="${pair##*:}"
  if [[ "$mode" == "--check" ]]; then
    check_file "$src" "$dest"
  else
    sync_file "$src" "$dest"
  fi
done

if [[ "$mode" == "--check" ]]; then
  [[ "$drift" == "0" ]] || exit 1
  echo "sync-adapters: no drift."
else
  echo "sync-adapters: core rendered into adapter mirrors."
fi
