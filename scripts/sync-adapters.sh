#!/usr/bin/env bash
# C-1: keep runtime code adapters as exact mirrors of the canonical core.
#
# Runtime code (career_graph/, ontology/, agentlas_cloud/, bin/hephaestus) must
# be byte-identical in every runtime adapter directory — adapters mirror the
# canonical core, they are never a second source. The large Model2Vec payload is
# a canonical runtime-release asset and is intentionally not duplicated into
# plugin mirrors. SKILL.md bodies are NOT checked here either, but not because
# they may differ — scripts/render-host-skills.py owns them, keeping each host's
# frontmatter and one shared body. They were believed to be "intentionally
# condensed per runtime" until 2026-08-17, when that turned out to mean openclaw
# shipped the upload skill without its irreversibility warning.
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
  "schemas"
  "templates"
  # Mode contracts are named by .agentlas/mode-map.json. A build that can read
  # the map but not the contract it points at falls back to improvising, and
  # that improvisation is invisible: the package still gets written.
  "modes"
)

# NOTE: SKILL.md bodies are now rendered by scripts/render-host-skills.py.
# Hook commands are host-specific: Claude and Codex expose different plugin
# root variables and should report their own host identity. Keep their source
# directories separate while still enforcing exact adapter mirrors.
hook_dir_mirrors=(
  "hooks/claude:claude/plugins/agentlas-core-engine-meta-agent/hooks"
  "hooks/codex:codex/plugins/agentlas-core-engine-meta-agent/hooks"
)

code_files=(
  "package-contract.json"
  # Canonical curator judgment data (G1~G8). Every executor loads values from
  # this file; one_workspace.py resolves it relative to agentlas_cloud/, so the
  # runtime and every plugin mirror must carry it. curator-fixtures/ stays
  # repo-only (public bundles never ship test material).
  "system-agents/curator-ruleset.json"
  # /hep-build opens with "read AGENTS.md, read the mode map, run the interview
  # gate, run the shape gate". None of those four files shipped, so the command
  # only ever worked inside this repository — in a user's own project the reads
  # found nothing (or, worse, the user's own AGENTS.md) and the model improvised
  # the whole build. Measured on three packages built 2026-07-28/29 outside this
  # repo: 5 of 18 required artifacts present, contract verify 23 blockers each.
  "AGENTS.md"
  ".agentlas/mode-map.json"
  # Builder procedure canon + interview gate contract. These four files ARE the
  # build: without them the deployed hephaestus:*-builder subagents are a 20-line
  # metadata shell that improvises the interview (measured 2026-08-12: the plugin
  # mirror had the shell but not the 187-line procedure, so no CLI runtime ever
  # showed the interview). The mirrors happened to match on 2026-08-15, but
  # --check never compared them — a drift here was undetectable. Listed as files,
  # not as a directory: contracts/ carries untracked node_modules/ and test/ that
  # must never be rsynced into a shipped bundle.
  "contracts/builder-interview-research-gate.md"
  # Runtime registry: `agentlas-one status --runtimes` reads it from the runtime
  # home, so every mirror must carry the same rows.
  "contracts/runtime-registry.json"
  "agents/10-single-agent-builder/agent.md"
  "agents/20-multi-agent-team-builder/agent.md"
  "agents/30-agentlas-packager/agent.md"
  # NOT shipped into adapter mirrors. The release archive check refuses any
  # `docs/` path inside a plugin bundle, and it is right to: internal design
  # and research notes are not end-user install material. Added here earlier
  # so /hep-build could cite it; the citation has to point at the repo, not
  # at a copy inside every published bundle.
  "bin/hephaestus"
  "bin/agentlas-python-cache-boundary"
  "bin/ontology"
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
  "bin/hep-update"
  "bin/hephaestus.cmd"
  "bin/agentlas-memory-hook"
  "bin/agentlas-one"
  # PRD §4.17 — One 서랍 쓰기 관문. 훅은 부르기만 하고 판정은 이 파일이 한다. 미러에 없으면
  # 플러그인 루트에서 실행 파일을 못 찾고, 훅은 (fail-closed 설계대로) 모든 쓰기를 거절한다.
  "bin/agentlas-one-drawer-guard"
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
  "skills/routing-card-authoring/SKILL.md:.agents/skills/routing-card-authoring/SKILL.md"
  "skills/routing-card-authoring/SKILL.md:codex/plugins/agentlas-core-engine-meta-agent/skills/routing-card-authoring/SKILL.md"
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
  "skills/hephaestus-upload/SKILL.md:.agents/skills/hephaestus-upload/SKILL.md"
  "skills/hephaestus-upload/SKILL.md:codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-upload/SKILL.md"
  "skills/hephaestus-upload/SKILL.md:gemini/extension/skills/hephaestus-upload/SKILL.md"
  "skills/hephaestus-upload/SKILL.md:cursor/plugin/skills/hephaestus-upload/SKILL.md"
  "skills/hephaestus-upload/SKILL.md:hermes/skills/hephaestus-upload/SKILL.md"
  "skills/hephaestus-storm/SKILL.md:.agents/skills/hephaestus-storm/SKILL.md"
  "skills/hephaestus-storm/SKILL.md:codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-storm/SKILL.md"
  "skills/hephaestus-storm/SKILL.md:hermes/skills/hephaestus-storm/SKILL.md"
  ".agentlas/routing-card.json:claude/plugins/agentlas-core-engine-meta-agent/.agentlas/routing-card.json"
  ".agentlas/routing-card.json:codex/plugins/agentlas-core-engine-meta-agent/.agentlas/routing-card.json"
  ".agentlas/routing-card.json:gemini/extension/.agentlas/routing-card.json"
  "cursor/rules/hephaestus.mdc:cursor/plugin/rules/hephaestus.mdc"
)

# EVERY plugin command gets a user-global copy. This is a glob on purpose: the
# hardcoded list it replaces silently omitted `agentlas-one.md` entirely and
# `hep-graph.md` from the installer's set, and a plugin command with no global
# copy is only reachable as `/hephaestus:<name>` — which is why "agentlas one on
# doesn't exist" was true on every machine that had not been hand-edited.
claude_command_dir="claude/plugins/agentlas-core-engine-meta-agent/commands"
for command_path in "$claude_command_dir"/*.md; do
  [[ -e "$command_path" ]] || continue
  skill_mirrors+=("$command_path:.claude/commands/$(basename "$command_path")")
done

# Same rule for the other two in-repo mirrors. These lists were left hardcoded
# when the Claude one became a glob, and they were ALREADY stale: hep-hub and
# hep-local were missing from both, so `.gemini/commands/hep-hub.toml` and
# `.agents/workflows/hep-local.md` still carried the pre-fix contract (echo the
# whole candidateSet back) while their sources had moved on — and `--check`
# reported clean because it never compared those pairs.
for command_path in gemini/extension/commands/*.toml; do
  [[ -e "$command_path" ]] || continue
  skill_mirrors+=("$command_path:.gemini/commands/$(basename "$command_path")")
done
for command_path in antigravity/workflows/*.md; do
  [[ -e "$command_path" ]] || continue
  skill_mirrors+=("$command_path:.agents/workflows/$(basename "$command_path")")
done

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

for pair in "${hook_dir_mirrors[@]}"; do
  src="${pair%%:*}"
  dest="${pair##*:}"
  if [[ "$mode" == "--check" ]]; then
    check_dir "$src" "$dest"
  else
    sync_dir "$src" "$dest"
  fi
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
