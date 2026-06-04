#!/usr/bin/env bash
set -euo pipefail

target="${1:-$PWD}"
force="${AGENTLAS_META_OS_FORCE:-0}"
repo_tarball="${AGENTLAS_META_OS_TARBALL_URL:-https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/archive/refs/heads/main.tar.gz}"

usage() {
  cat <<'EOF'
Usage:
  scripts/install.sh [target-dir]

Environment:
  AGENTLAS_META_OS_SOURCE=/path/to/local/package
  AGENTLAS_META_OS_FORCE=1
  AGENTLAS_META_OS_TARBALL_URL=https://example/package.tar.gz
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

if [[ -n "${AGENTLAS_META_OS_SOURCE:-}" ]]; then
  source_dir="$AGENTLAS_META_OS_SOURCE"
else
  archive="$tmp_dir/package.tar.gz"
  curl -fsSL "$repo_tarball" -o "$archive"
  tar -xzf "$archive" -C "$tmp_dir"
  source_dir="$(find "$tmp_dir" -maxdepth 1 -type d -name 'agent_agentlas_core_engine_meta_agent-*' | head -n 1)"
fi

if [[ ! -d "$source_dir" ]]; then
  echo "install: package source not found" >&2
  exit 1
fi

mkdir -p "$target"

copy_root_file() {
  local name="$1"
  local src="$source_dir/$name"
  local dst="$target/$name"
  if [[ ! -f "$src" ]]; then
    return
  fi
  if [[ -e "$dst" && "$force" != "1" ]]; then
    cp "$src" "$target/${name%.md}.agentlas-meta.md"
  else
    cp "$src" "$dst"
  fi
}

copy_dir() {
  local name="$1"
  local src="$source_dir/$name"
  if [[ -d "$src" ]]; then
    mkdir -p "$target/$name"
    cp -R "$src"/. "$target/$name"/
  fi
}

for file in AGENTS.md CLAUDE.md GEMINI.md README.md ARCHITECTURE.md agent.md manifest.json LICENSE SECURITY.md; do
  copy_root_file "$file"
done

for dir in agents modes skills .agents .agentlas .claude .gemini codex docs schemas templates examples scripts; do
  copy_dir "$dir"
done

if [[ -d "$target/scripts" ]]; then
  chmod +x "$target"/scripts/*.sh 2>/dev/null || true
fi

echo "Agentlas Core Engine Meta-Agent Team installed into: $target"
echo "Read AGENTS.md, then run: scripts/verify-package.sh"
