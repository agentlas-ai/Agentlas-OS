#!/usr/bin/env bash
# Build this working tree into a runtime and install it into an isolated HOME.
#
# Why this exists: a fix that lands only in an adapter never reaches anyone. The
# installed runtime overwrites `~/.claude/plugins/cache/...` from its own
# `host_adapters/` bundle on first run, so a locally repaired plugin is reverted
# to the published bytes — measured 2026-08-07 by md5, and it is the mechanism
# behind "we fixed this many times and nothing changed". Testing against a
# hand-dropped plugin therefore measures the wrong thing. This installs the
# whole runtime, the way a user gets it.
#
#   scripts/iso-install.sh <iso-root> [version]
#
# Leaves <iso-root>/home as a HOME that has never seen Agentlas except for what
# this script put there, and <iso-root>/work as an empty project area.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
iso="${1:?usage: iso-install.sh <iso-root> [version]}"
version="${2:-0.0.0-local}"

bash "$root/scripts/sync-adapters.sh" >/dev/null

rm -rf "$iso"
mkdir -p "$iso/home" "$iso/work"
runtime="$iso/home/.agentlas/runtime/$version"
mkdir -p "$runtime/host_adapters"

for dir in agentlas_cloud career_graph ontology schemas templates scripts bin modes; do
  [ -d "$root/$dir" ] || continue
  rsync -a --exclude '__pycache__' --exclude '.DS_Store' "$root/$dir/" "$runtime/$dir/"
done
for file in package-contract.json desktop-update-bridge-v1.json AGENTS.md; do
  [ -f "$root/$file" ] && cp "$root/$file" "$runtime/$file"
done
printf '%s\n' "$version" > "$runtime/RELEASE"

for host in claude codex; do
  src="$root/$host/plugins/agentlas-core-engine-meta-agent"
  [ -d "$src" ] || continue
  dest="$runtime/host_adapters/$host/plugins/agentlas-core-engine-meta-agent"
  mkdir -p "$dest"
  rsync -a --exclude '__pycache__' --exclude '.DS_Store' "$src/" "$dest/"
done

ln -sfn "$runtime" "$iso/home/.agentlas/runtime/current"

engine="$iso/home/.agentlas/runtime/current/host_adapters/claude/plugins/agentlas-core-engine-meta-agent"
echo "iso home    : $iso/home"
echo "iso work    : $iso/work"
echo "runtime     : $runtime ($(du -sh "$runtime" | cut -f1))"
echo "engine root : \$HOME/.agentlas/runtime/current/host_adapters/claude/plugins/agentlas-core-engine-meta-agent"

# The runtime and the adapters it installs must be one generation, or the
# product runs one engine and tells the host about another.
python3 "$root/scripts/verify-name-to-thing.py" --engine "$engine" --runtime "$runtime"
