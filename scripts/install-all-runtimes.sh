#!/usr/bin/env bash
set -uo pipefail

version="${HEPHAESTUS_REF:-v0.4.4}"
repo="${HEPHAESTUS_REPO:-agentlas-ai/Hephaestus}"
github_url="${HEPHAESTUS_GITHUB_URL:-https://github.com/$repo}"
marketplace_name="${HEPHAESTUS_MARKETPLACE:-agentlas-core-engine}"
plugin_name="${HEPHAESTUS_PLUGIN:-hephaestus}"
old_plugin_name="${HEPHAESTUS_OLD_PLUGIN:-agentlas-meta-agent}"
source_dir="${HEPHAESTUS_SOURCE_DIR:-}"
force="${HEPHAESTUS_FORCE:-1}"
mcp_url="${AGENTLAS_MCP_URL:-https://agentlas.cloud/api/mcp/v1}"

ok=0
failed=0
tmp_source_dir=""

cleanup() {
  if [[ -n "$tmp_source_dir" ]]; then
    rm -rf "$tmp_source_dir"
  fi
}
trap cleanup EXIT

log() {
  printf '%s\n' "$*"
}

warn() {
  printf 'WARN: %s\n' "$*" >&2
}

have() {
  command -v "$1" >/dev/null 2>&1
}

run() {
  log "+ $*"
  "$@"
}

run_yes() {
  log "+ $*"
  printf 'y\n' | "$@"
}

try() {
  log "+ $*"
  "$@"
}

preflight_git() {
  if have git; then
    return 0
  fi
  if [[ "$(uname -s)" == "Darwin" ]] && have xcode-select; then
    warn "git is missing. Starting Apple Command Line Tools installer."
    xcode-select --install >/dev/null 2>&1 || true
  fi
  warn "git is required for Claude/Codex/Gemini marketplace installs. Run git --version after Command Line Tools finishes, then rerun this installer."
  return 1
}

ensure_downloaded_source() {
  if [[ -n "$source_dir" ]]; then
    return 0
  fi
  if [[ -n "$tmp_source_dir" ]]; then
    source_dir="$tmp_source_dir/source"
    return 0
  fi
  if ! have curl || ! have tar; then
    warn "curl and tar are required for Gemini extension install from a remote ref."
    return 1
  fi

  tmp_source_dir="$(mktemp -d)"
  local archive="$tmp_source_dir/hephaestus.tar.gz"
  local archive_url="https://github.com/$repo/archive/$version.tar.gz"
  log "+ curl -fsSL $archive_url -o $archive"
  curl -fsSL "$archive_url" -o "$archive" || return 1
  tar -xzf "$archive" -C "$tmp_source_dir" || return 1
  local extracted
  extracted="$(find "$tmp_source_dir" -maxdepth 1 -type d -name 'Hephaestus-*' | head -n 1)"
  if [[ -z "$extracted" ]]; then
    warn "Downloaded Hephaestus source was not found in archive."
    return 1
  fi
  mv "$extracted" "$tmp_source_dir/source"
  source_dir="$tmp_source_dir/source"
}

# Runtime-neutral install: every adapter (skills, commands, prompts, MCP)
# resolves ~/.agentlas/runtime/current/bin/hephaestus FIRST, so harnesses
# without a plugin cache (OpenCode, OpenClaw, Hermes, Cursor, Ollama-launched
# local models) still find the runner.
install_runtime_home() {
  ensure_downloaded_source || { warn "runtime home install skipped: no source."; return 1; }
  local plain="${version#v}"
  local home_dir="$HOME/.agentlas/runtime/$plain"
  log "== Hephaestus runtime home =="
  rm -rf "$home_dir"
  mkdir -p "$home_dir"
  cp -R "$source_dir/bin" "$source_dir/agentlas_cloud" "$source_dir/ontology" "$home_dir/" || return 1
  ln -sfn "$home_dir" "$HOME/.agentlas/runtime/current"
  log "Installed runner: $HOME/.agentlas/runtime/current/bin/hephaestus"
}

# AgentSkills-spec universal skill: ~/.agents/skills is read natively by
# Codex (USER scope), OpenCode, OpenClaw, Cursor, and Crush.
install_agents_skills() {
  ensure_downloaded_source || return 1
  local src="$source_dir/skills/hephaestus-network"
  [[ -d "$src" ]] || { warn "canonical hephaestus-network skill not found."; return 1; }
  mkdir -p "$HOME/.agents/skills"
  rm -rf "$HOME/.agents/skills/hephaestus-network"
  cp -R "$src" "$HOME/.agents/skills/hephaestus-network"
  log "Installed universal skill: ~/.agents/skills/hephaestus-network"
}

remove_claude_existing() {
  try claude plugin uninstall "$plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try claude plugin uninstall "$old_plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try claude plugin marketplace remove "$marketplace_name" >/dev/null 2>&1 || true
}

install_claude() {
  if ! have claude; then
    warn "Claude CLI not found; skipped Claude plugin install."
    return 0
  fi

  log "== Claude Code plugin =="
  if [[ "$force" == "1" ]]; then
    remove_claude_existing
  else
    try claude plugin marketplace update "$marketplace_name" >/dev/null 2>&1 || true
  fi

  if [[ -n "$source_dir" ]]; then
    run claude plugin marketplace add "$source_dir/claude" || return 1
  else
    run claude plugin marketplace add "$github_url" --sparse .claude-plugin claude/plugins || return 1
  fi

  run claude plugin install "$plugin_name@$marketplace_name" || return 1
  try claude plugin enable "$plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  write_claude_commands || warn "Claude global command refresh failed; copy .claude/commands/hephaestus*.md to ~/.claude/commands manually."
  log "agentlas Hub MCP is bundled with the plugin (.mcp.json) and registers automatically."
  ok=$((ok + 1))
}

# Keep the user-global ~/.claude/commands copies in sync with this release.
# A copy may be a symlink into a local checkout (same file) — skip those.
write_claude_commands() {
  ensure_downloaded_source || return 1
  mkdir -p "$HOME/.claude/commands"
  local name src dest
  for name in hephaestus.md hephaestus-network.md; do
    src="$source_dir/.claude/commands/$name"
    dest="$HOME/.claude/commands/$name"
    if [[ -e "$dest" && "$src" -ef "$dest" ]]; then
      continue
    fi
    cp "$src" "$dest" || return 1
  done
  log "Refreshed ~/.claude/commands/hephaestus.md and hephaestus-network.md"
}

remove_codex_existing() {
  try codex plugin remove "$plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try codex plugin remove "$old_plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try codex plugin marketplace remove "$marketplace_name" >/dev/null 2>&1 || true
}

# Codex plugins cannot register slash commands (skills only), so the explicit
# command surface is a custom prompt: ~/.codex/prompts/<name>.md →
# /prompts:<name>. Top-level files only — Codex ignores subdirectories.
write_codex_prompts() {
  ensure_downloaded_source || return 1
  local prompts_src="$source_dir/codex/prompts"
  [[ -d "$prompts_src" ]] || { warn "codex prompts not found: $prompts_src"; return 1; }
  mkdir -p "$HOME/.codex/prompts"
  cp "$prompts_src"/*.md "$HOME/.codex/prompts/" || return 1
  log "Installed Codex custom prompts: /prompts:hephaestus, /prompts:hephaestus-network"
}

install_codex() {
  if ! have codex; then
    warn "Codex CLI not found; skipped Codex plugin install."
    return 0
  fi

  log "== Codex plugin =="
  if [[ "$force" == "1" ]]; then
    remove_codex_existing
  else
    try codex plugin marketplace upgrade "$marketplace_name" >/dev/null 2>&1 || true
  fi

  if [[ -n "$source_dir" ]]; then
    run codex plugin marketplace add "$source_dir" || return 1
  else
    run codex plugin marketplace add "$repo" --ref "$version" || return 1
  fi

  run codex plugin add "$plugin_name@$marketplace_name" || return 1
  write_codex_prompts || warn "Codex custom prompt install failed; copy codex/prompts/*.md to ~/.codex/prompts manually."
  register_codex_mcp || warn "Codex MCP registration failed; add it manually to ~/.codex/config.toml."
  ok=$((ok + 1))
}

# Codex 플러그인은 MCP 번들을 지원하지 않으므로 config.toml에 직접 등록한다.
# rmcp 클라이언트 플래그가 없으면 HTTP MCP 자체가 붙지 않는다.
register_codex_mcp() {
  local cfg="$HOME/.codex/config.toml"
  mkdir -p "$HOME/.codex"
  touch "$cfg" || return 1

  if ! grep -q 'experimental_use_rmcp_client' "$cfg"; then
    if grep -q '^\[features\]' "$cfg"; then
      awk '{print} /^\[features\]/ && !done {print "experimental_use_rmcp_client = true"; done=1}' \
        "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg" || return 1
    else
      printf '\n[features]\nexperimental_use_rmcp_client = true\n' >> "$cfg"
    fi
  fi

  if ! grep -q '^\[mcp_servers\.agentlas\]' "$cfg"; then
    printf '\n[mcp_servers.agentlas]\nurl = "%s"\n' "$mcp_url" >> "$cfg"
  fi
  if ! grep -q '^\[mcp_servers\.hephaestus-network\]' "$cfg"; then
    printf '\n[mcp_servers.hephaestus-network]\ncommand = "%s"\nargs = ["mcp", "serve"]\n' \
      "$HOME/.agentlas/runtime/current/bin/hephaestus" >> "$cfg"
  fi
  log "Registered agentlas Hub MCP + local hephaestus-network MCP in $cfg"
}

write_gemini_fallback_command() {
  local command_dir="$HOME/.gemini/commands"
  mkdir -p "$command_dir"
  cat > "$command_dir/hephaestus.toml" <<EOF
description = "Run Hephaestus to create/package Agentlas agents or open the ontology GUI."
prompt = """
# /hephaestus

Raw arguments:
{{args}}

Use Hephaestus, the Agentlas Core Engine Meta-Agent. If this workspace contains
\`AGENTS.md\`, \`.agentlas/mode-map.json\`, and
\`.agentlas/global-commands.json\`, read those files first and follow the local
package contract.

If the package files are missing, run this one-touch installer from an OS
terminal:

\`curl -fsSL https://raw.githubusercontent.com/$repo/$version/scripts/install-all-runtimes.sh | bash\`

For creation or packaging work, classify the request as single-agent-builder,
multi-agent-team-builder, or agentlas-packager. Generate or repair the Agentlas
package, verify it, and include \`global_commands\` in the final response.
"""
EOF
  log "Installed Gemini fallback command: $command_dir/hephaestus.toml"

  if [[ -f "$source_dir/gemini/extension/commands/hephaestus-network.toml" ]]; then
    cp "$source_dir/gemini/extension/commands/hephaestus-network.toml" "$command_dir/hephaestus-network.toml"
    log "Installed Gemini fallback command: $command_dir/hephaestus-network.toml"
  fi
}

install_gemini() {
  if ! have gemini; then
    warn "Gemini CLI not found; skipped Gemini extension install."
    return 0
  fi

  log "== Gemini CLI extension and command =="
  try gemini extensions uninstall hephaestus >/dev/null 2>&1 || true
  ensure_downloaded_source || return 1
  local gemini_extension_dir="$source_dir/gemini/extension"
  if [[ ! -f "$gemini_extension_dir/gemini-extension.json" ]]; then
    warn "Gemini extension manifest not found: $gemini_extension_dir/gemini-extension.json"
    return 1
  fi
  if [[ -z "${HEPHAESTUS_SOURCE_DIR:-}" ]]; then
    local stable_gemini_source="$HOME/.gemini/hephaestus-extension-source"
    rm -rf "$stable_gemini_source"
    mkdir -p "$stable_gemini_source"
    cp -R "$gemini_extension_dir"/. "$stable_gemini_source"/
    gemini_extension_dir="$stable_gemini_source"
  fi

  run_yes gemini extensions install "$gemini_extension_dir" --consent --skip-settings || return 1

  write_gemini_fallback_command || return 1
  ok=$((ok + 1))
}

antigravity_present() {
  [[ -d "$HOME/.gemini/antigravity" ]] && return 0
  # "Antigravity IDE" 변형은 별도 데이터 디렉토리(~/.gemini/antigravity-ide)를 쓴다.
  [[ -d "$HOME/.gemini/antigravity-ide" ]] && return 0
  [[ -n "${HEPHAESTUS_FORCE_ANTIGRAVITY:-}" ]] && return 0
  ls -d /Applications/Antigravity*.app >/dev/null 2>&1 && return 0
  return 1
}

install_antigravity() {
  if ! antigravity_present; then
    warn "Antigravity not detected; skipped Antigravity workflow install."
    return 0
  fi

  log "== Antigravity workflow =="
  ensure_downloaded_source || return 1
  local workflow_src="$source_dir/antigravity/workflows/hephaestus.md"
  if [[ ! -f "$workflow_src" ]]; then
    warn "Antigravity workflow not found: $workflow_src"
    return 1
  fi

  # 두 데이터 디렉토리 변형 모두에 설치한다 — 어느 앱을 쓰든 /hephaestus가 보이게.
  local installed=0
  local data_dir
  for data_dir in "$HOME/.gemini/antigravity" "$HOME/.gemini/antigravity-ide"; do
    # 존재하는 데이터 디렉토리에만 설치하되, 둘 다 없으면 기본 경로를 생성한다.
    if [[ -d "$data_dir" || ( "$installed" -eq 0 && "$data_dir" == "$HOME/.gemini/antigravity" ) ]]; then
      local global_dir="$data_dir/global_workflows"
      mkdir -p "$global_dir"
      cp "$workflow_src" "$global_dir/hephaestus.md" || return 1
      log "Installed Antigravity global workflow: $global_dir/hephaestus.md"
      local network_workflow_src="$source_dir/antigravity/workflows/hephaestus-network.md"
      if [[ -f "$network_workflow_src" ]]; then
        cp "$network_workflow_src" "$global_dir/hephaestus-network.md"
        log "Installed Antigravity global workflow: $global_dir/hephaestus-network.md"
      fi
      installed=$((installed + 1))
    fi
  done
  [[ "$installed" -gt 0 ]] || return 1
  register_antigravity_mcp || warn "Antigravity MCP registration failed; add it manually to ~/.gemini/config/mcp_config.json."
  ok=$((ok + 1))
}

# Antigravity는 ~/.gemini/config/mcp_config.json에서 MCP 서버를 읽는다 (serverUrl 키).
register_antigravity_mcp() {
  local cfg_dir="$HOME/.gemini/config"
  local cfg="$cfg_dir/mcp_config.json"
  if ! have python3; then
    warn "python3 not found; add agentlas MCP to $cfg manually."
    return 0
  fi
  mkdir -p "$cfg_dir"
  AGENTLAS_MCP_URL="$mcp_url" python3 - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
url = os.environ["AGENTLAS_MCP_URL"]
try:
    with open(path) as f:
        data = json.load(f)
except (FileNotFoundError, ValueError):
    data = {}
servers = data.setdefault("mcpServers", {})
servers.setdefault("agentlas", {"serverUrl": url})
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
  log "Registered agentlas Hub MCP in $cfg"
}

# Cursor reads global commands (~/.cursor/commands/*.md) and skills
# (~/.cursor/skills, plus ~/.agents/skills) in both the IDE and the CLI.
install_cursor() {
  if [[ ! -d "$HOME/.cursor" ]] && ! have agent && ! have cursor-agent && ! have cursor; then
    warn "Cursor not detected; skipped Cursor command/skill install."
    return 0
  fi
  log "== Cursor commands and skill =="
  ensure_downloaded_source || return 1
  mkdir -p "$HOME/.cursor/commands" "$HOME/.cursor/skills"
  cp "$source_dir/cursor/plugin/commands"/*.md "$HOME/.cursor/commands/" || return 1
  rm -rf "$HOME/.cursor/skills/hephaestus-network"
  cp -R "$source_dir/skills/hephaestus-network" "$HOME/.cursor/skills/hephaestus-network" || return 1
  log "Installed Cursor commands (/hephaestus, /hephaestus-network) and skill."
  ok=$((ok + 1))
}

# OpenCode reads ~/.config/opencode/commands/*.md as /name slash commands and
# ~/.agents/skills natively.
install_opencode() {
  if ! have opencode && [[ ! -d "$HOME/.config/opencode" ]]; then
    warn "OpenCode not detected; skipped OpenCode command install."
    return 0
  fi
  log "== OpenCode commands =="
  ensure_downloaded_source || return 1
  mkdir -p "$HOME/.config/opencode/commands"
  cp "$source_dir/opencode/commands"/*.md "$HOME/.config/opencode/commands/" || return 1
  log "Installed OpenCode commands: /hephaestus, /hephaestus-network"
  ok=$((ok + 1))
}

# OpenClaw loads AgentSkills from ~/.openclaw/skills (and ~/.agents/skills);
# user-invocable skills surface as slash commands via /skill.
install_openclaw() {
  if ! have openclaw && [[ ! -d "$HOME/.openclaw" ]]; then
    warn "OpenClaw not detected; skipped OpenClaw skill install."
    return 0
  fi
  log "== OpenClaw skill =="
  ensure_downloaded_source || return 1
  local skill_src="$source_dir/openclaw/skills/hephaestus-network"
  if have openclaw && openclaw skills install "$skill_src" --global >/dev/null 2>&1; then
    log "Installed OpenClaw skill via: openclaw skills install --global"
  else
    mkdir -p "$HOME/.openclaw/skills"
    rm -rf "$HOME/.openclaw/skills/hephaestus-network"
    cp -R "$skill_src" "$HOME/.openclaw/skills/hephaestus-network" || return 1
    log "Installed OpenClaw skill: ~/.openclaw/skills/hephaestus-network"
  fi
  ok=$((ok + 1))
}

# Hermes Agent (Nous Research) reads AgentSkills from ~/.hermes/skills.
install_hermes() {
  if ! have hermes && [[ ! -d "$HOME/.hermes" ]]; then
    warn "Hermes Agent not detected; skipped Hermes skill install."
    return 0
  fi
  log "== Hermes Agent skill =="
  ensure_downloaded_source || return 1
  mkdir -p "$HOME/.hermes/skills"
  rm -rf "$HOME/.hermes/skills/hephaestus-network"
  cp -R "$source_dir/skills/hephaestus-network" "$HOME/.hermes/skills/hephaestus-network" || return 1
  log "Installed Hermes skill: ~/.hermes/skills/hephaestus-network (MCP: see hermes/README.md)"
  ok=$((ok + 1))
}

# Hephaestus Network 2.0: create or migrate ~/.agentlas/networking on every
# install/upgrade (idempotent; indexes only registered paths, never the home
# folder).
bootstrap_networking() {
  local py=""
  if have python3; then
    py="python3"
  elif have python; then
    py="python"
  else
    warn "python3 not found; skipped Hephaestus Network init. Install Python 3.9+ and run: hephaestus network init"
    return 0
  fi
  if ! ensure_downloaded_source; then
    warn "Hephaestus Network init skipped: could not download the source archive (curl/tar). Run later: hephaestus network init"
    return 0
  fi
  log "== Hephaestus Network (global routing structure) =="
  local init_output
  if ! init_output="$(PYTHONPATH="$source_dir${PYTHONPATH:+:$PYTHONPATH}" "$py" -m agentlas_cloud network init 2>&1)"; then
    warn "Hephaestus Network init failed. Error was:"
    printf '%s\n' "$init_output" | tail -5 >&2
    warn "Retry manually: PYTHONPATH=<hephaestus-source> $py -m agentlas_cloud network init"
    return 1
  fi
  PYTHONPATH="$source_dir${PYTHONPATH:+:$PYTHONPATH}" "$py" -m agentlas_cloud network reindex >/dev/null 2>&1 || true
  log "Initialized ~/.agentlas/networking (cards, policies, ledgers, local memory map)."
}

main() {
  log "Hephaestus one-touch install/update"
  log "repo: $repo"
  log "ref:  $version"
  log "mode: force refresh=${force}"

  preflight_git || exit 1

  install_runtime_home || { warn "Runtime home install failed."; failed=$((failed + 1)); }
  install_agents_skills || { warn "Universal ~/.agents/skills install failed."; failed=$((failed + 1)); }
  install_claude || { warn "Claude install failed."; failed=$((failed + 1)); }
  install_codex || { warn "Codex install failed."; failed=$((failed + 1)); }
  install_gemini || { warn "Gemini install failed."; failed=$((failed + 1)); }
  install_antigravity || { warn "Antigravity install failed."; failed=$((failed + 1)); }
  install_cursor || { warn "Cursor install failed."; failed=$((failed + 1)); }
  install_opencode || { warn "OpenCode install failed."; failed=$((failed + 1)); }
  install_openclaw || { warn "OpenClaw install failed."; failed=$((failed + 1)); }
  install_hermes || { warn "Hermes install failed."; failed=$((failed + 1)); }
  bootstrap_networking || warn "Hephaestus Network init failed; run 'hephaestus network init' manually."

  log ""
  log "Installed/updated runtimes: $ok"
  log "Failed runtimes: $failed"
  log ""
  log "Restart open Claude Code, Codex, Gemini, Antigravity, Cursor, OpenCode, OpenClaw, and Hermes sessions."
  log "Then use:"
  log "  Claude Code: /reload-plugins, then /hephaestus ontology"
  log "  Codex:       /prompts:hephaestus-network, \$hephaestus-network skill, or /plugins"
  log "  Gemini CLI:  /extensions list or /commands list, then /hephaestus"
  log "  Antigravity: reopen the workspace, then /hephaestus"
  log "  Cursor:      /hephaestus-network (command and skill)"
  log "  OpenCode:    /hephaestus-network"
  log "  OpenClaw:    /skill hephaestus-network <request>"
  log "  Hermes:      hephaestus-network skill (+ MCP, see hermes/README.md)"
  log "  Ollama/Gemma/DeepSeek local models: docs/local-models.md (MCP: hephaestus mcp serve)"
  log ""
  log "agentlas Hub MCP (agentlas.search, marketplace.*, agentlas.teams.*) was registered too."
  log "Try a plain-language prompt in any runtime, e.g.:"
  log "  \"agentlas에서 ASO 도와주는 에이전트 찾아줘\"  /  \"find an agentlas agent for app store reviews\""

  if [[ "$ok" -eq 0 || "$failed" -gt 0 ]]; then
    exit 1
  fi
}

main "$@"
