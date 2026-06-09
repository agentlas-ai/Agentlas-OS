#!/usr/bin/env bash
set -euo pipefail

repo="${HEPHAESTUS_REPO:-https://github.com/agentlas-ai/Hephaestus}"
codex_repo="${HEPHAESTUS_CODEX_REPO:-agentlas-ai/Hephaestus}"
version="${HEPHAESTUS_VERSION:-v0.2.8}"
keep="${HEPHAESTUS_KEEP_SMOKE_DIR:-0}"

fail() {
  echo "verify-one-touch-install: $*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "git is not available. On macOS run: xcode-select --install"
command -v rg >/dev/null 2>&1 || fail "rg is not available"
command -v claude >/dev/null 2>&1 || fail "claude CLI is not available"
command -v codex >/dev/null 2>&1 || fail "codex CLI is not available"
command -v gemini >/dev/null 2>&1 || fail "gemini CLI is not available"
command -v python3 >/dev/null 2>&1 || fail "python3 is not available"

tmp="$(mktemp -d)"
if [[ "$keep" != "1" ]]; then
  trap 'rm -rf "$tmp"' EXIT
fi

shell_home="$tmp/shell-home"
codex_home="$shell_home/.codex"
project="$tmp/project"
ontology_json="$tmp/ontology-result.json"

mkdir -p "$codex_home" "$shell_home" "$project"

echo "=== Hephaestus one-touch install verification ==="
echo "repo: $repo"
echo "codex repo: $codex_repo"
echo "version: $version"
echo "workdir: $tmp"
echo

echo "1/5 macOS/git preflight"
git --version
if [[ "$(uname -s)" == "Darwin" ]]; then
  xcode-select -p >/dev/null 2>&1 || fail "macOS Command Line Tools are not installed. Run: xcode-select --install"
fi
echo "PASS preflight"
echo

echo "2/6 One-touch all-runtime install script"
HOME="$shell_home" CODEX_HOME="$codex_home" HEPHAESTUS_SOURCE_DIR="$PWD" HEPHAESTUS_REF="$version" scripts/install-all-runtimes.sh | tee "$tmp/install-all-runtimes.txt"
rg -q 'Installed/updated runtimes: 3' "$tmp/install-all-runtimes.txt" || fail "one-touch installer did not update all three runtimes"
echo "PASS one-touch installer"
echo

echo "3/6 Claude plugin installed by one-touch script"
HOME="$shell_home" claude plugin list | tee "$tmp/claude-plugin-list.txt"
rg -q 'hephaestus@agentlas-core-engine' "$tmp/claude-plugin-list.txt" || fail "Claude plugin list does not show Hephaestus"
echo "PASS Claude install"
echo

echo "4/6 Codex plugin installed by one-touch script"
HOME="$shell_home" CODEX_HOME="$codex_home" codex plugin list | tee "$tmp/codex-plugin-list.txt"
rg -q 'hephaestus@agentlas-core-engine' "$tmp/codex-plugin-list.txt" || fail "Codex plugin list does not show Hephaestus"
echo "PASS Codex install"
echo

echo "5/6 Gemini extension and command installed by one-touch script"
HOME="$shell_home" gemini extensions list 2>&1 | tee "$tmp/gemini-extensions-list.txt"
rg -q 'hephaestus' "$tmp/gemini-extensions-list.txt" || fail "Gemini extension list does not show Hephaestus"
[[ -f "$shell_home/.gemini/commands/hephaestus.toml" ]] || fail "Gemini fallback command was not installed"
echo "PASS Gemini install"
echo

echo "6/6 Ontology GUI from installed Codex plugin cache"
runner="$(find "$codex_home/plugins/cache/agentlas-core-engine/hephaestus" -path '*/bin/hephaestus' -type f | sort | tail -1)"
[[ -n "$runner" ]] || fail "installed Hephaestus runner not found"
[[ -x "$runner" ]] || fail "installed Hephaestus runner is not executable: $runner"
"$runner" ontology --no-open "$project" | tee "$ontology_json"
python3 - "$ontology_json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
if payload.get("status") != "gui_ready":
    raise SystemExit(f"unexpected status: {payload.get('status')}")
verify = payload.get("verify", {})
if verify.get("status") != "pass":
    raise SystemExit(f"unexpected verify status: {verify.get('status')}")
for key in ("gui_path", "db_path", "inbox_path"):
    path = Path(payload[key])
    if key == "gui_path":
        if not path.is_file():
            raise SystemExit(f"missing GUI file: {path}")
    elif not path.exists():
        raise SystemExit(f"missing path: {path}")
print(f"GUI: {payload['gui_url']}")
print(f"DB: {payload['db_path']}")
print(f"Inbox: {payload['inbox_path']}")
PY
echo "PASS ontology GUI"
echo

echo "Expected in-app commands after install"
echo "Claude Code: /reload-plugins"
echo "Claude/Codex: /hephaestus ontology"
echo "Codex plugin browser: /plugins"
echo "Gemini CLI: /extensions list, /commands list, /hephaestus"
echo

if [[ "$keep" == "1" ]]; then
  echo "Artifacts kept at: $tmp"
else
  echo "Temporary artifacts will be removed."
fi
echo "ALL PASS Hephaestus one-touch install verification"
