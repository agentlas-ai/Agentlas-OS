#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

fail() {
  echo "verify-install-docs: $*" >&2
  exit 1
}

scan_files=(
  README.md
  README.ko.md
  README.zh-CN.md
  README.ja.md
  README.hi.md
  claude/README.md
  codex/README.md
  assets/install-claude-code-chat.svg
  assets/install-claude-cli.svg
  assets/install-codex-chat.svg
  assets/install-codex-cli.svg
  assets/install-codex-desktop-settings.svg
  .agents/plugins/marketplace.json
  codex/.agents/plugins/marketplace.json
  codex/marketplace.json
  .claude-plugin/marketplace.json
  claude/.claude-plugin/marketplace.json
  codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json
  claude/plugins/agentlas-core-engine-meta-agent/.claude-plugin/plugin.json
  gemini/extension/gemini-extension.json
  gemini/extension/commands/hephaestus.toml
  .gemini/commands/hephaestus.toml
  manifest.json
  scripts/install.sh
  scripts/install-all-runtimes.sh
  scripts/preflight-macos.sh
)

for path in "${scan_files[@]}"; do
  [[ -e "$path" ]] || fail "missing scan file: $path"
done

bad_patterns=(
  '/plugin marketplace add agentlas-ai/Hephaestus'
  '/plugin install agentlas-meta-agent'
  'codex plugin install'
  'v0\.2\.1'
  'v0\.1\.5'
  'Install Codex plugin by slash command'
  'Codex plugin slash'
  'Codex 플러그인 slash'
  '用 slash command 安装 Codex'
  'Codex plugin を slash command'
  'Type these commands directly into Codex'
  'Codex 안에 그대로 입력'
  'Codex にそのまま入力'
  'सीधे Codex में type'
)

for pattern in "${bad_patterns[@]}"; do
  if rg -n "$pattern" "${scan_files[@]}" >/tmp/hephaestus-install-doc-bad.txt; then
    cat /tmp/hephaestus-install-doc-bad.txt >&2
    fail "bad install-doc pattern still present: $pattern"
  fi
done

if rg -n 'agentlas-meta-agent' README*.md claude/README.md codex/README.md \
  | grep -Ev 'agentlas-meta-agent-architecture|agentlas-meta-agent@agentlas-core-engine|agentlas run agentlas-meta-agent|old `agentlas-meta-agent`|still shows `agentlas-meta-agent`|older install still shows `agentlas-meta-agent`|points at `agentlas-meta-agent`|예전 `agentlas-meta-agent`|아직 `agentlas-meta-agent`' \
  >/tmp/hephaestus-old-name-docs.txt; then
  cat /tmp/hephaestus-old-name-docs.txt >&2
  fail "old product name appears in public prose"
fi

for path in README.md README.ko.md codex/README.md; do
  rg -q 'codex plugin marketplace add agentlas-ai/Hephaestus --ref v0\.2\.8' "$path" || fail "missing Codex marketplace command in $path"
  rg -q 'codex plugin add hephaestus@agentlas-core-engine' "$path" || fail "missing Codex add command in $path"
done

rg -q 'Codex does not accept `/plugin marketplace add` inside the app' README.md || fail "README.md does not warn about Codex /plugin"
rg -q 'Codex 앱 안에서는 `/plugin marketplace add`가 동작하지 않습니다' README.ko.md || fail "README.ko.md does not warn about Codex /plugin"
rg -q '/plugins' README.md README.ko.md codex/README.md assets/install-codex-chat.svg assets/install-codex-cli.svg || fail "Codex /plugins browser command missing"
rg -q 'xcode-select --install' README.md README.ko.md claude/README.md codex/README.md scripts/preflight-macos.sh || fail "macOS xcode-select preflight missing"
rg -q 'git --version' README.md README.ko.md claude/README.md codex/README.md scripts/preflight-macos.sh || fail "git verification missing"

python3 - <<'PY'
import json
from pathlib import Path

codex = json.loads(Path("codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json").read_text())
claude = json.loads(Path("claude/plugins/agentlas-core-engine-meta-agent/.claude-plugin/plugin.json").read_text())
manifest = json.loads(Path("manifest.json").read_text())
assert codex["id"] == "hephaestus", codex["id"]
assert codex["name"] == "hephaestus", codex["name"]
assert codex["version"] == "0.2.8", codex["version"]
assert codex["interface"]["displayName"] == "Hephaestus", codex["interface"]["displayName"]
assert claude["name"] == "hephaestus", claude["name"]
assert claude["version"] == "0.2.8", claude["version"]
assert manifest["package"] == "hephaestus", manifest["package"]
assert manifest["version"] == "0.2.8", manifest["version"]
assert manifest["entrypoints"]["claudeHephaestusCommand"].endswith("hephaestus.md")
assert manifest["entrypoints"]["codexHephaestusCommand"].endswith("hephaestus.md")
assert manifest["entrypoints"]["geminiExtension"].endswith("gemini-extension.json")
assert manifest["entrypoints"]["geminiHephaestusCommand"].endswith("hephaestus.toml")
assert manifest["entrypoints"]["antigravityWorkflow"].endswith("antigravity/workflows/hephaestus.md")
assert manifest["entrypoints"]["antigravityProjectWorkflow"].endswith(".agents/workflows/hephaestus.md")
assert manifest["entrypoints"]["globalCommands"].endswith("global-commands.json")

for path in [
    ".agents/plugins/marketplace.json",
    "codex/.agents/plugins/marketplace.json",
    "codex/marketplace.json",
    ".claude-plugin/marketplace.json",
    "claude/.claude-plugin/marketplace.json",
]:
    payload = json.loads(Path(path).read_text())
    names = [plugin["name"] for plugin in payload["plugins"]]
    assert "hephaestus" in names, (path, names)
PY

for path in \
  bin/hephaestus \
  bin/ontology \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus \
  scripts/install.sh \
  scripts/install-all-runtimes.sh \
  scripts/preflight-macos.sh \
  scripts/verify-install-docs.sh \
  scripts/verify-global-command-contract.sh \
  scripts/verify-one-touch-install.sh \
  scripts/run-one-touch-terminal.command \
  scripts/verify-package.sh \
  scripts/public_safety_check.sh \
  scripts/verify-ontology-runtime.sh; do
  [[ -x "$path" ]] || fail "not executable: $path"
done

echo "Install docs verification passed."
