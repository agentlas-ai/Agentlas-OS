#!/usr/bin/env bash
set -uo pipefail

version="${HEPHAESTUS_REF:-v0.2.6}"
repo="${HEPHAESTUS_REPO:-agentlas-ai/Hephaestus}"
github_url="${HEPHAESTUS_GITHUB_URL:-https://github.com/$repo}"
marketplace_name="${HEPHAESTUS_MARKETPLACE:-agentlas-core-engine}"
plugin_name="${HEPHAESTUS_PLUGIN:-hephaestus}"
old_plugin_name="${HEPHAESTUS_OLD_PLUGIN:-agentlas-meta-agent}"
source_dir="${HEPHAESTUS_SOURCE_DIR:-}"
force="${HEPHAESTUS_FORCE:-1}"

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
  ok=$((ok + 1))
}

remove_codex_existing() {
  try codex plugin remove "$plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try codex plugin remove "$old_plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try codex plugin marketplace remove "$marketplace_name" >/dev/null 2>&1 || true
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
  ok=$((ok + 1))
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

main() {
  log "Hephaestus one-touch install/update"
  log "repo: $repo"
  log "ref:  $version"
  log "mode: force refresh=${force}"

  preflight_git || exit 1

  install_claude || { warn "Claude install failed."; failed=$((failed + 1)); }
  install_codex || { warn "Codex install failed."; failed=$((failed + 1)); }
  install_gemini || { warn "Gemini install failed."; failed=$((failed + 1)); }

  log ""
  log "Installed/updated runtimes: $ok"
  log "Failed runtimes: $failed"
  log ""
  log "Restart open Claude Code, Codex, and Gemini sessions."
  log "Then use:"
  log "  Claude Code: /reload-plugins, then /hephaestus ontology"
  log "  Codex:       /plugins, then /hephaestus ontology"
  log "  Gemini CLI:  /extensions list or /commands list, then /hephaestus"

  if [[ "$ok" -eq 0 || "$failed" -gt 0 ]]; then
    exit 1
  fi
}

main "$@"
