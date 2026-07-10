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
  gemini/extension/commands/hep-build.toml
  gemini/extension/commands/hep-network.toml
  gemini/extension/commands/hep-cloud.toml
  gemini/extension/commands/hep-search.toml
  gemini/extension/commands/hep-browser.toml
  gemini/extension/commands/hep-call.toml
  gemini/extension/commands/hep-upload.toml
  .gemini/commands/hep-build.toml
  .gemini/commands/hep-network.toml
  .gemini/commands/hep-cloud.toml
  .gemini/commands/hep-search.toml
  .gemini/commands/hep-browser.toml
  .gemini/commands/hep-call.toml
  .gemini/commands/hep-upload.toml
  manifest.json
  scripts/install.sh
  scripts/install-all-runtimes.sh
  scripts/preflight-macos.sh
)

for path in "${scan_files[@]}"; do
  [[ -e "$path" ]] || fail "missing scan file: $path"
done

expected_version="$(python3 -c 'import json;print(json.load(open("manifest.json"))["version"])')"
expected_tag="v${expected_version}"
expected_tag_re="${expected_tag//./\\.}"

bad_patterns=(
  '/plugin marketplace add agentlas-ai/Agentlas-OS'
  '/plugin install agentlas-meta-agent'
  'codex plugin install'
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

stale_pins="$(rg -oI 'v0\.[0-9]+\.[0-9]+' "${scan_files[@]}" 2>/dev/null | sort -u | grep -v "^${expected_tag}$" || true)"
if [[ -n "$stale_pins" ]]; then
  fail "stale version pins in docs (expected only ${expected_tag}): $(printf '%s ' $stale_pins)"
fi

if rg -n 'agentlas-meta-agent' README*.md claude/README.md codex/README.md \
  | grep -Ev 'agentlas-meta-agent-architecture|agentlas-meta-agent@agentlas-core-engine|agentlas run agentlas-meta-agent|old `agentlas-meta-agent`|still shows `agentlas-meta-agent`|older install still shows `agentlas-meta-agent`|points at `agentlas-meta-agent`|예전 `agentlas-meta-agent`|아직 `agentlas-meta-agent`' \
  >/tmp/hephaestus-old-name-docs.txt; then
  cat /tmp/hephaestus-old-name-docs.txt >&2
  fail "old product name appears in public prose"
fi

for path in README.md README.ko.md codex/README.md; do
  rg -q "codex plugin marketplace add agentlas-ai/Agentlas-OS --ref ${expected_tag_re}" "$path" || fail "missing Codex marketplace command in $path"
  rg -q 'codex plugin add hephaestus@agentlas-core-engine' "$path" || fail "missing Codex add command in $path"
done

rg -q 'Codex does not accept `/plugin marketplace add` inside the app' README.md || fail "README.md does not warn about Codex /plugin"
rg -q 'Codex 앱 안에서는 `/plugin marketplace add`가 동작하지 않습니다' README.ko.md || fail "README.ko.md does not warn about Codex /plugin"
rg -q '/plugins' README.md README.ko.md codex/README.md assets/install-codex-chat.svg assets/install-codex-cli.svg || fail "Codex /plugins browser command missing"
rg -q -- '--target antigravity' README.md README.ko.md antigravity/README.md || fail "Antigravity global router target docs missing"
rg -q 'xcode-select --install' README.md README.ko.md claude/README.md codex/README.md scripts/preflight-macos.sh || fail "macOS xcode-select preflight missing"
rg -q 'git --version' README.md README.ko.md claude/README.md codex/README.md scripts/preflight-macos.sh || fail "git verification missing"
if rg -q 'experimental_use_rmcp_client = true' scripts/install-all-runtimes.sh; then
  fail "obsolete Codex remote-MCP feature flag must not be installed"
fi
rg -q 'releases/download/\$version/\$asset' scripts/install-all-runtimes.sh \
  || fail "one-touch installer must use the digest-bearing release asset"
rg -q 'SHA-256 mismatch' scripts/install-all-runtimes.sh \
  || fail "one-touch installer must fail closed on release digest mismatch"

python3 - <<'PY'
import json
from pathlib import Path

codex = json.loads(Path("codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json").read_text())
claude = json.loads(Path("claude/plugins/agentlas-core-engine-meta-agent/.claude-plugin/plugin.json").read_text())
manifest = json.loads(Path("manifest.json").read_text())
assert codex["id"] == "hephaestus", codex["id"]
assert codex["name"] == "hephaestus", codex["name"]
expected_version = manifest["version"]
assert codex["version"] == expected_version, codex["version"]
# Codex 0.144+ rejects plugin resource paths that are not explicitly relative
# to the plugin root. A bare `skills` value installs successfully but the
# runtime silently ignores every bundled skill.
assert codex["skills"] == "./skills", codex["skills"]
assert codex["interface"]["displayName"] == "Hephaestus", codex["interface"]["displayName"]
assert claude["name"] == "hephaestus", claude["name"]
assert claude["version"] == expected_version, claude["version"]
assert "skills" not in claude, claude.get("skills")
assert manifest["package"] == "hephaestus", manifest["package"]

assert manifest["entrypoints"]["hephaestusCli"].endswith("bin/hephaestus")
assert manifest["entrypoints"]["hephaestusGlobalCli"].endswith("bin/hep-global")
assert manifest["entrypoints"]["claudeHephaestusBuildCommand"].endswith("hep-build.md")
assert manifest["entrypoints"]["claudeHephaestusNetworkCommand"].endswith("hep-network.md")
assert manifest["entrypoints"]["claudeHephaestusCloudCommand"].endswith("hep-cloud.md")
assert manifest["entrypoints"]["claudeHephaestusSearchCommand"].endswith("hep-search.md")
assert manifest["entrypoints"]["claudeHephaestusBrowserCommand"].endswith("hep-browser.md")
assert manifest["entrypoints"]["claudeHephaestusCallCommand"].endswith("hep-call.md")
assert manifest["entrypoints"]["claudeHephaestusUploadCommand"].endswith("hep-upload.md")
assert manifest["entrypoints"]["claudeHephaestusConnectCommand"].endswith("hep-connect.md")
assert manifest["entrypoints"]["codexHephaestusBuildPrompt"].endswith("hep-build.md")
assert manifest["entrypoints"]["codexHephaestusNetworkPrompt"].endswith("hep-network.md")
assert manifest["entrypoints"]["codexHephaestusCloudPrompt"].endswith("hep-cloud.md")
assert manifest["entrypoints"]["codexHephaestusSearchPrompt"].endswith("hep-search.md")
assert manifest["entrypoints"]["codexHephaestusBrowserPrompt"].endswith("hep-browser.md")
assert manifest["entrypoints"]["codexHephaestusCallPrompt"].endswith("hep-call.md")
assert manifest["entrypoints"]["codexHephaestusUploadPrompt"].endswith("hep-upload.md")
assert manifest["entrypoints"]["codexHephaestusConnectPrompt"].endswith("hep-connect.md")
assert manifest["entrypoints"]["geminiExtension"].endswith("gemini-extension.json")
assert manifest["entrypoints"]["geminiHephaestusBuildCommand"].endswith("hep-build.toml")
assert manifest["entrypoints"]["geminiHephaestusNetworkCommand"].endswith("hep-network.toml")
assert manifest["entrypoints"]["geminiHephaestusCloudCommand"].endswith("hep-cloud.toml")
assert manifest["entrypoints"]["geminiHephaestusSearchCommand"].endswith("hep-search.toml")
assert manifest["entrypoints"]["geminiHephaestusBrowserCommand"].endswith("hep-browser.toml")
assert manifest["entrypoints"]["geminiHephaestusCallCommand"].endswith("hep-call.toml")
assert manifest["entrypoints"]["geminiHephaestusUploadCommand"].endswith("hep-upload.toml")
assert manifest["entrypoints"]["antigravityBuildWorkflow"].endswith("antigravity/workflows/hep-build.md")
assert manifest["entrypoints"]["antigravityNetworkWorkflow"].endswith("antigravity/workflows/hep-network.md")
assert manifest["entrypoints"]["antigravityCloudWorkflow"].endswith("antigravity/workflows/hep-cloud.md")
assert manifest["entrypoints"]["antigravitySearchWorkflow"].endswith("antigravity/workflows/hep-search.md")
assert manifest["entrypoints"]["antigravityBrowserWorkflow"].endswith("antigravity/workflows/hep-browser.md")
assert manifest["entrypoints"]["antigravityCallWorkflow"].endswith("antigravity/workflows/hep-call.md")
assert manifest["entrypoints"]["antigravityUploadWorkflow"].endswith("antigravity/workflows/hep-upload.md")
assert manifest["entrypoints"]["agentlasHephaestusConnectWorkflow"].endswith(".agents/workflows/hep-connect.md")
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
  bin/hep-build \
  bin/hep-network \
  bin/hep-cloud \
  bin/hep-search \
  bin/hep-browser \
  bin/hep-call \
  bin/hep-upload \
  bin/hep-storm \
  bin/hep-global \
  bin/ontology \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hep-build \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hep-network \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hep-cloud \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hep-search \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hep-browser \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hep-call \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hep-upload \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hep-storm \
  claude/plugins/agentlas-core-engine-meta-agent/bin/hep-global \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hep-build \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hep-network \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hep-cloud \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hep-search \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hep-browser \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hep-call \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hep-upload \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hep-storm \
  codex/plugins/agentlas-core-engine-meta-agent/bin/hep-global \
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
