#!/usr/bin/env bash
set -euo pipefail

repo="${HEPHAESTUS_REPO:-https://github.com/agentlas-ai/Hephaestus}"
codex_repo="${HEPHAESTUS_CODEX_REPO:-agentlas-ai/Hephaestus}"
version="${HEPHAESTUS_VERSION:-v0.7.23}"
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

echo "1/7 macOS/git preflight"
git --version
if [[ "$(uname -s)" == "Darwin" ]]; then
  xcode-select -p >/dev/null 2>&1 || fail "macOS Command Line Tools are not installed. Run: xcode-select --install"
fi
echo "PASS preflight"
echo

echo "2/7 One-touch all-runtime install script"
HOME="$shell_home" CODEX_HOME="$codex_home" HEPHAESTUS_SOURCE_DIR="$PWD" HEPHAESTUS_REF="$version" scripts/install-all-runtimes.sh | tee "$tmp/install-all-runtimes.txt"
rg -q 'Installed/updated runtimes: 5' "$tmp/install-all-runtimes.txt" || fail "one-touch installer did not update the expected five runtimes"
echo "PASS one-touch installer"
echo

echo "3/7 Claude plugin installed by one-touch script"
HOME="$shell_home" claude plugin list | tee "$tmp/claude-plugin-list.txt"
rg -q 'hephaestus@agentlas-core-engine' "$tmp/claude-plugin-list.txt" || fail "Claude plugin list does not show Hephaestus"
HOME="$shell_home" claude plugin details hephaestus@agentlas-core-engine | tee "$tmp/claude-plugin-details.txt"
rg -q 'Skills \(6\)' "$tmp/claude-plugin-details.txt" || fail "Claude details should show six Hephaestus commands"
for expected_skill in hep-build hep-cloud hep-network hep-search hep-call hep-upload; do
  rg -q "$expected_skill" "$tmp/claude-plugin-details.txt" || fail "Claude details missing $expected_skill"
done
if rg -n '0-7-4|mode-classification|agentlas-auto-activation|team-builder-packaging|hephaestus-build|hephaestus-network|hephaestus-cloud|hephaestus-search|hephaestus-call|Skills \(5\)' "$tmp/claude-plugin-details.txt"; then
  fail "Claude details still show stale or duplicate Hephaestus skills"
fi
if find "$shell_home/.claude/plugins/cache/agentlas-core-engine/hephaestus" -path '*/skills/*/SKILL.md' -print -quit | rg -q .; then
  fail "Claude plugin cache should not contain duplicate SKILL.md entries"
fi
echo "PASS Claude install"
echo

echo "4/7 Codex plugin installed by one-touch script"
HOME="$shell_home" CODEX_HOME="$codex_home" codex plugin list | tee "$tmp/codex-plugin-list.txt"
rg -q 'hephaestus@agentlas-core-engine' "$tmp/codex-plugin-list.txt" || fail "Codex plugin list does not show Hephaestus"
echo "PASS Codex install"
echo

echo "5/7 Gemini extension and command installed by one-touch script"
HOME="$shell_home" gemini extensions list 2>&1 | tee "$tmp/gemini-extensions-list.txt"
rg -q 'hephaestus' "$tmp/gemini-extensions-list.txt" || fail "Gemini extension list does not show Hephaestus"
[[ -f "$shell_home/.gemini/commands/hep-build.toml" ]] || fail "Gemini build fallback command was not installed"
[[ -f "$shell_home/.gemini/commands/hep-network.toml" ]] || fail "Gemini network fallback command was not installed"
[[ -f "$shell_home/.gemini/commands/hep-cloud.toml" ]] || fail "Gemini cloud fallback command was not installed"
[[ -f "$shell_home/.gemini/commands/hep-search.toml" ]] || fail "Gemini search fallback command was not installed"
[[ -f "$shell_home/.gemini/commands/hep-call.toml" ]] || fail "Gemini call fallback command was not installed"
[[ -f "$shell_home/.gemini/commands/hep-upload.toml" ]] || fail "Gemini upload fallback command was not installed"
[[ ! -f "$shell_home/.gemini/commands/hephaestus.toml" ]] || fail "Legacy Gemini /hephaestus command should be pruned"
echo "PASS Gemini install"
echo

echo "6/7 First-run Agentlas sign-in surface"
runtime_runner="$shell_home/.agentlas/runtime/current/bin/hephaestus"
[[ -x "$runtime_runner" ]] || fail "runtime runner is not executable: $runtime_runner"
rg -q 'auth ensure --timeout' "$shell_home/.agents/skills/hephaestus-network/SKILL.md" || fail "universal skill does not auto-trigger Agentlas sign-in"
rg -q 'auth ensure --timeout' "$shell_home/.agents/skills/hephaestus-cloud/SKILL.md" || fail "universal cloud skill does not auto-trigger Agentlas sign-in"
rg -q 'auth ensure --timeout' "$codex_home/prompts/hep-network.md" || fail "Codex prompt does not auto-trigger Agentlas sign-in"
[[ -f "$codex_home/prompts/hep-build.md" ]] || fail "Codex build prompt was not installed"
[[ -f "$codex_home/prompts/hep-cloud.md" ]] || fail "Codex cloud prompt was not installed"
[[ -f "$codex_home/prompts/hep-search.md" ]] || fail "Codex search prompt was not installed"
[[ -f "$codex_home/prompts/hep-call.md" ]] || fail "Codex call prompt was not installed"
[[ -f "$codex_home/prompts/hep-upload.md" ]] || fail "Codex upload prompt was not installed"
[[ ! -f "$codex_home/prompts/hephaestus.md" ]] || fail "Legacy Codex /prompts:hephaestus prompt should be pruned"
HOME="$shell_home" "$runtime_runner" auth status | tee "$tmp/auth-status.json"
python3 - "$tmp/auth-status.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
if payload.get("status") not in {"signed_out", "refreshable", "authenticated"}:
    raise SystemExit(f"unexpected auth status: {payload.get('status')}")
if not str(payload.get("token_path") or "").endswith("/.agentlas/auth/agentlas.cloud.json"):
    raise SystemExit(f"unexpected token path: {payload.get('token_path')}")
PY
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n' | HOME="$shell_home" "$runtime_runner" mcp serve | tee "$tmp/mcp-tools.jsonl"
python3 - "$tmp/mcp-tools.jsonl" <<'PY'
import json
import sys
from pathlib import Path

lines = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
tools = {tool["name"] for tool in lines[0]["result"]["tools"]}
for name in ("agentlas_authenticate", "agentlas_auth_status", "hephaestus_hub_invoke", "hephaestus_search", "hephaestus_call"):
    if name not in tools:
        raise SystemExit(f"missing MCP tool: {name}")
PY
echo "PASS first-run sign-in surface"
echo

echo "7/7 Ontology GUI from installed Codex plugin cache"
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
echo "Claude Code: /reload-plugins, then /hep-build, /hep-network, /hep-cloud, /hep-search, /hep-call, /hep-upload"
echo "Codex: /prompts:hep-build, /prompts:hep-network, /prompts:hep-cloud, /prompts:hep-search, /prompts:hep-call, /prompts:hep-upload"
echo "Codex plugin browser: /plugins"
echo "Gemini CLI: /extensions list, /commands list, then /hep-build, /hep-network, /hep-cloud, /hep-search, /hep-call, /hep-upload"
echo

if [[ "$keep" == "1" ]]; then
  echo "Artifacts kept at: $tmp"
else
  echo "Temporary artifacts will be removed."
fi
echo "ALL PASS Hephaestus one-touch install verification"
