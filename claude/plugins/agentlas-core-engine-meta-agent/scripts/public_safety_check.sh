#!/usr/bin/env bash
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "public_safety_check: run this inside the output agent repository" >&2
  exit 1
fi

hits_file="$(mktemp)"
trap 'rm -f "$hits_file"' EXIT

# Only exact copies at the engine's declared checker paths are self-rules.
# A modified copy or a checker-named file elsewhere still needs a full scan.
checker_pathspecs=()
for checker_path in \
  scripts/public_safety_check.sh \
  claude/plugins/agentlas-core-engine-meta-agent/scripts/public_safety_check.sh \
  codex/plugins/agentlas-core-engine-meta-agent/scripts/public_safety_check.sh; do
  if [[ -f "$checker_path" ]] && cmp -s "${BASH_SOURCE[0]}" "$checker_path"; then
    checker_pathspecs+=(":(exclude)$checker_path")
  fi
done

check_pattern() {
  local label="$1"
  local pattern="$2"

  if git grep -nE --untracked --exclude-standard -- "$pattern" -- "${checker_pathspecs[@]}" >"$hits_file"; then
    echo "public_safety_check: blocked by ${label}" >&2
    cat "$hits_file" >&2
    exit 1
  fi
}

check_pattern "private user path" '/Users/[A-Za-z0-9._-]+/'
check_pattern "private local volume" '/Volumes/[A-Za-z0-9._ -]+/'
check_pattern "GitHub token" 'gh[opsu]_[A-Za-z0-9_]{20,}'
check_pattern "OpenAI-style API token" 'sk-[A-Za-z0-9_-]{20,}'
check_pattern "Google API key" 'AIza[0-9A-Za-z_-]{20,}'
check_pattern "OpenCrab MCP credential" 'ocm_[A-Za-z0-9_-]{20,}'
check_pattern "private key block" 'BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY'
check_pattern "service account material" 'firebase-adminsdk|serviceAccountKey|client_email.*gserviceaccount'

echo "Public safety check passed."
