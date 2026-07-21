#!/usr/bin/env bash
set -uo pipefail

version="${HEPHAESTUS_REF:-v1.1.53}"
repo="${HEPHAESTUS_REPO:-agentlas-ai/Agentlas-OS}"
github_url="${HEPHAESTUS_GITHUB_URL:-https://github.com/$repo}"
marketplace_name="${HEPHAESTUS_MARKETPLACE:-agentlas-core-engine}"
plugin_name="${HEPHAESTUS_PLUGIN:-hephaestus}"
old_plugin_name="${HEPHAESTUS_OLD_PLUGIN:-agentlas-meta-agent}"
requested_source_dir="${HEPHAESTUS_SOURCE_DIR:-}"
source_dir="$requested_source_dir"
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

python_ok() {
  "$@" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}

is_runtime_python_shim() {
  local candidate="$1"
  local resolved=""
  if [[ "$candidate" == */* ]]; then
    resolved="$candidate"
  else
    resolved="$(command -v "$candidate" 2>/dev/null || true)"
  fi
  [[ -n "$resolved" ]] || return 1
  case "$resolved" in
    "$HOME/.agentlas/runtime/"*/bin/python3|"$HOME/.agentlas/runtime/current/bin/python3")
      return 0
      ;;
  esac
  return 1
}

python_candidate_ok() {
  local candidate="$1"
  if is_runtime_python_shim "$candidate"; then
    return 1
  fi
  python_ok "$candidate"
}

resolve_python_cmd() {
  if [[ -n "${HEPHAESTUS_PYTHON:-}" ]] && python_candidate_ok "$HEPHAESTUS_PYTHON"; then
    printf '%s\n' "$HEPHAESTUS_PYTHON"
    return 0
  fi
  local candidate
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [[ -x "$candidate" ]] && python_candidate_ok "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  if have python3 && python_candidate_ok python3; then
    printf '%s\n' python3
    return 0
  fi
  if have python && python_candidate_ok python; then
    printf '%s\n' python
    return 0
  fi
  if have py && py -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    printf '%s\n' 'py -3'
    return 0
  fi
  return 1
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
    warn "curl and tar are required for runtime install from a remote release."
    return 1
  fi

  tmp_source_dir="$(mktemp -d)"
  local asset="hephaestus-runtime-$version.tar.gz"
  local archive="$tmp_source_dir/$asset"
  local checksum="$archive.sha256"
  local archive_url="https://github.com/$repo/releases/download/$version/$asset"
  local checksum_url="$archive_url.sha256"
  log "+ downloading verified release asset $asset"
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL "$archive_url" -o "$archive" || return 1
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL "$checksum_url" -o "$checksum" || return 1
  local expected actual
  expected="$(awk 'NR == 1 { print tolower($1) }' "$checksum")"
  if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    warn "Release checksum metadata is invalid for $asset."
    return 1
  fi
  if have shasum; then
    actual="$(shasum -a 256 "$archive" | awk '{print tolower($1)}')"
  elif have sha256sum; then
    actual="$(sha256sum "$archive" | awk '{print tolower($1)}')"
  elif have openssl; then
    actual="$(openssl dgst -sha256 "$archive" | awk '{print tolower($NF)}')"
  else
    warn "shasum, sha256sum, or openssl is required to verify the runtime release."
    return 1
  fi
  if [[ "$actual" != "$expected" ]]; then
    warn "Runtime release SHA-256 mismatch; refusing to install."
    return 1
  fi
  tar -xzf "$archive" -C "$tmp_source_dir" || return 1
  local extracted
  extracted="$(find "$tmp_source_dir" -maxdepth 1 -type d \( -name 'Agentlas-OS-*' -o -name 'Hephaestus-*' \) | head -n 1)"
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
  local model_source="$source_dir/assets/model2vec/potion-multilingual-128M-int8"
  local model_dest="$home_dir/models/model2vec/potion-multilingual-128M-int8"
  local py=""
  py="$(resolve_python_cmd || true)"
  if [[ -z "$py" ]]; then
    warn "Python 3.9+ is required to verify the bundled local embedding model."
    return 1
  fi
  if [[ ! -d "$model_source" ]]; then
    warn "Bundled Model2Vec asset is missing: $model_source"
    return 1
  fi
  log "== Hephaestus runtime home =="
  rm -rf "$home_dir"
  mkdir -p "$home_dir"
  cp -R "$source_dir/bin" "$source_dir/agentlas_cloud" "$source_dir/career_graph" \
    "$source_dir/ontology" "$source_dir/schemas" "$source_dir/templates" \
    "$home_dir/" || return 1
  mkdir -p "$(dirname "$model_dest")"
  cp -R "$model_source" "$model_dest" || return 1
  if ! PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONPATH="$home_dir${PYTHONPATH:+:$PYTHONPATH}" \
    $py -m ontology.model_assets verify "$model_dest" >/dev/null; then
    warn "Bundled Model2Vec asset failed local checksum/provenance verification; refusing the runtime install."
    return 1
  fi
  chmod +x "$home_dir/bin/hephaestus" \
    "$home_dir/bin/ontology" \
    "$home_dir/bin/career-graph" \
    "$home_dir/bin/hep-build" \
    "$home_dir/bin/hep-network" \
    "$home_dir/bin/hep-local" \
    "$home_dir/bin/hep-cloud" \
    "$home_dir/bin/hep-hub" \
    "$home_dir/bin/hep-search" \
    "$home_dir/bin/hep-browser" \
	    "$home_dir/bin/hep-call" \
	    "$home_dir/bin/hep-upload" \
	    "$home_dir/bin/hep-storm" \
	    "$home_dir/bin/hep-global" \
	    "$home_dir/bin/hep-update" \
	    "$home_dir/bin/agentlas-memory-hook" 2>/dev/null || true
  printf '%s\n' "$version" > "$home_dir/RELEASE"
  write_python3_shim "$home_dir/bin" || true
  if [[ ! -e "$home_dir/bin/Hephaestus" ]]; then
    ln -sfn hephaestus "$home_dir/bin/Hephaestus" 2>/dev/null || true
  fi
  rm -f "$home_dir/bin/Hephaestus-build" "$home_dir/bin/Hephaestus-search" \
        "$home_dir/bin/Hephaestus-call" "$home_dir/bin/Hephaestus-storm" \
        "$home_dir/bin/hephaestus-network" \
        "$home_dir/bin/hephaestus-build" "$home_dir/bin/hephaests-network" \
        "$home_dir/bin/hephaestus-search" "$home_dir/bin/hephaestus-call" \
        "$home_dir/bin/hephaestus-storm" 2>/dev/null || true
  local current_link="$HOME/.agentlas/runtime/current"
  if [[ -e "$current_link" && ! -L "$current_link" ]]; then
    rm -rf "$current_link"
  fi
  ln -sfn "$home_dir" "$current_link"
  log "Installed runner: $HOME/.agentlas/runtime/current/bin/hephaestus"

  local user_bin="$HOME/.local/bin"
  if mkdir -p "$user_bin" 2>/dev/null; then
	  local -a shell_commands=(
	    hephaestus ontology hep-build hep-network hep-local hep-cloud hep-hub hep-search hep-browser hep-call hep-upload hep-storm hep-global hep-update
	  )
    local command
    for command in "${shell_commands[@]}"; do
      rm -f "$user_bin/$command" 2>/dev/null || true
      cat > "$user_bin/$command" <<EOF
#!/usr/bin/env bash
exec "$current_link/bin/$command" "\$@"
EOF
      chmod +x "$user_bin/$command" 2>/dev/null || true
    done
    if [[ -x "$user_bin/hephaestus" ]]; then
      case ":$PATH:" in
	        *":$user_bin:"*) log "Installed shell commands: hephaestus, ontology, hep-build, hep-network, hep-local, hep-cloud, hep-hub, hep-search, hep-browser, hep-call, hep-upload, hep-storm, hep-global" ;;
        *) log "Installed shell commands in $user_bin (add ~/.local/bin to PATH to use them)" ;;
      esac
    fi
  fi
}

write_python3_shim() {
  local bin_dir="$1"
  local py
  py="$(resolve_python_cmd || true)"
  rm -f "$bin_dir/python3" "$bin_dir/python3.cmd" 2>/dev/null || true
  [[ -n "$py" ]] || return 0
  mkdir -p "$bin_dir"
  if [[ "$py" == "py -3" ]]; then
    cat > "$bin_dir/python3" <<'EOF'
#!/usr/bin/env bash
exec py -3 "$@"
EOF
    printf '@py -3 %%*\r\n' > "$bin_dir/python3.cmd"
  else
    cat > "$bin_dir/python3" <<EOF
#!/usr/bin/env bash
exec "$py" "\$@"
EOF
    printf '@"%s" %%*\r\n' "$py" > "$bin_dir/python3.cmd"
  fi
  cat > "$bin_dir/hephaestus.cmd" <<'EOF'
@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
if defined HEPHAESTUS_PYTHON goto use_env_python
if exist "%~dp0python3.cmd" goto use_python3_shim
where py >nul 2>nul
if not errorlevel 1 goto use_py_launcher
where python >nul 2>nul
if not errorlevel 1 goto use_path_python
echo hephaestus: Python 3.9+ not found. Install Python from python.org and rerun hephaestus doctor. 1>&2
exit /b 127

:use_env_python
"%HEPHAESTUS_PYTHON%" -m agentlas_cloud %*
exit /b %ERRORLEVEL%

:use_python3_shim
call "%~dp0python3.cmd" -m agentlas_cloud %*
exit /b %ERRORLEVEL%

:use_py_launcher
py -3 -m agentlas_cloud %*
exit /b %ERRORLEVEL%

:use_path_python
python -m agentlas_cloud %*
exit /b %ERRORLEVEL%
EOF
  cat > "$bin_dir/hephaestus-env.cmd" <<'EOF'
@echo off
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
EOF
  chmod +x "$bin_dir/python3"
}

# AgentSkills-spec universal skill: ~/.agents/skills is read natively by
# Codex (USER scope), OpenCode, OpenClaw, Cursor, and Crush.
install_agents_skills() {
  ensure_downloaded_source || return 1
  mkdir -p "$HOME/.agents/skills"
  local name src
  for name in hephaestus-network hephaestus-cloud hephaestus-storm; do
    src="$source_dir/.agents/skills/$name"
    [[ -d "$src" ]] || src="$source_dir/skills/$name"
    [[ -d "$src" ]] || { warn "canonical $name skill not found."; return 1; }
    rm -rf "$HOME/.agents/skills/$name"
    cp -R "$src" "$HOME/.agents/skills/$name"
  done
  log "Installed universal skills: ~/.agents/skills/hephaestus-network, hephaestus-cloud, and hephaestus-storm"
}

remove_claude_existing() {
  try claude plugin uninstall "$plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try claude plugin uninstall "$old_plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try claude plugin marketplace remove "$marketplace_name" >/dev/null 2>&1 || true
  rm -rf "$HOME/.claude/plugins/cache/$marketplace_name/$plugin_name" 2>/dev/null || true
  rm -rf "$HOME/.claude/plugins/cache/$marketplace_name/$old_plugin_name" 2>/dev/null || true
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

  if [[ -n "$requested_source_dir" ]]; then
    run claude plugin marketplace add "$source_dir/claude" || return 1
  else
    run claude plugin marketplace add "$github_url" --sparse .claude-plugin claude/plugins || return 1
  fi

  run claude plugin install "$plugin_name@$marketplace_name" || return 1
  try claude plugin enable "$plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  write_claude_commands || {
    warn "Claude global command refresh failed; bare /hep-* autocomplete will not persist into the next session."
    return 1
  }
  log "Bundled MCP: local hephaestus-network Core (Cloud/Hub upstream stays behind Core)."
  ok=$((ok + 1))
}

# Keep the user-global ~/.claude/commands copies in sync with this release.
# Remove old entries first so stale symlinks from earlier installers do not
# survive in the host app's command autocomplete cache.
write_claude_commands() {
  ensure_downloaded_source || return 1
  mkdir -p "$HOME/.claude/commands"
  local name src dest
  for name in hep-build.md hep-network.md hep-local.md hep-cloud.md hep-hub.md hep-search.md hep-browser.md hep-call.md hep-upload.md hep-connect.md hep-storm.md; do
    src="$source_dir/.claude/commands/$name"
    dest="$HOME/.claude/commands/$name"
    rm -f "$dest"
    cp "$src" "$dest" || return 1
  done
  rm -f "$HOME/.claude/commands/hephaestus.md" "$HOME/.claude/commands/hephaests-network.md" \
        "$HOME/.claude/commands/hephaestus-build.md" "$HOME/.claude/commands/hephaestus-network.md" \
        "$HOME/.claude/commands/hephaestus-cloud.md" "$HOME/.claude/commands/hephaestus-search.md" \
        "$HOME/.claude/commands/hephaestus-call.md"
  log "Refreshed Claude commands: /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-search, /hep-browser, /hep-call, /hep-upload, /hep-connect, /hep-storm"
}

remove_codex_existing() {
  try codex plugin remove "$plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try codex plugin remove "$old_plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try codex plugin marketplace remove "$marketplace_name" >/dev/null 2>&1 || true
  rm -rf "${CODEX_HOME:-$HOME/.codex}/plugins/cache/$marketplace_name/$plugin_name" 2>/dev/null || true
}

# Codex plugins cannot register slash commands (skills only), so the explicit
# command surface is a custom prompt: ~/.codex/prompts/<name>.md →
# /prompts:<name>. Top-level files only — Codex ignores subdirectories.
write_codex_prompts() {
  ensure_downloaded_source || return 1
  local prompts_src="$source_dir/codex/prompts"
  [[ -d "$prompts_src" ]] || { warn "codex prompts not found: $prompts_src"; return 1; }
  mkdir -p "$HOME/.codex/prompts"
  local name
  for name in hep-build.md hep-network.md hep-local.md hep-cloud.md hep-hub.md hep-search.md hep-browser.md hep-call.md hep-upload.md hep-connect.md hep-storm.md; do
    rm -f "$HOME/.codex/prompts/$name"
    cp "$prompts_src/$name" "$HOME/.codex/prompts/$name" || return 1
  done
  rm -f "$HOME/.codex/prompts/hephaestus.md" "$HOME/.codex/prompts/hephaests-network.md" \
        "$HOME/.codex/prompts/hephaestus-build.md" "$HOME/.codex/prompts/hephaestus-network.md" \
        "$HOME/.codex/prompts/hephaestus-cloud.md" "$HOME/.codex/prompts/hephaestus-search.md" \
        "$HOME/.codex/prompts/hephaestus-call.md"
  log "Installed Codex custom prompts: /prompts:hep-build, /prompts:hep-network, /prompts:hep-local, /prompts:hep-cloud, /prompts:hep-hub, /prompts:hep-search, /prompts:hep-browser, /prompts:hep-call, /prompts:hep-upload, /prompts:hep-connect, /prompts:hep-storm"
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

  if [[ -n "$requested_source_dir" ]]; then
    run codex plugin marketplace add "$source_dir" || return 1
  else
    run codex plugin marketplace add "$repo" --ref "$version" || return 1
  fi

  run codex plugin add "$plugin_name@$marketplace_name" || return 1
  write_codex_prompts || warn "Codex custom prompt install failed; copy codex/prompts/*.md to ~/.codex/prompts manually."
  register_codex_mcp || warn "Codex MCP registration failed; add it manually to ~/.codex/config.toml."
  ok=$((ok + 1))
}

stamp_plugin_cache_releases() {
  local root dir count=0
  for root in \
    "$HOME/.claude/plugins/cache/$marketplace_name/$plugin_name" \
    "${CODEX_HOME:-$HOME/.codex}/plugins/cache/$marketplace_name/$plugin_name"
  do
    [[ -d "$root" ]] || continue
    while IFS= read -r -d '' dir; do
      [[ -f "$dir/bin/hephaestus" ]] || continue
      printf '%s\n' "$version" > "$dir/RELEASE" || true
      write_python3_shim "$dir/bin" || true
      count=$((count + 1))
    done < <(find "$root" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
  done
  if [[ "$count" -gt 0 ]]; then
    log "Stamped plugin cache release markers: $count"
  fi
}

# Codex 플러그인은 MCP 번들을 지원하지 않으므로 config.toml에 직접 등록한다.
# Workforce must have one canonical MCP entrypoint. Remove the old direct
# `agentlas` table (which bypassed Core) and replace the owned local table while
# preserving every unrelated user table. The obsolete remote-MCP feature flag
# is also removed because strict Codex versions reject it.
register_codex_mcp() {
  local cfg="$HOME/.codex/config.toml"
  mkdir -p "$HOME/.codex"
  touch "$cfg" || return 1

  if grep -q '^[[:space:]]*experimental_use_rmcp_client[[:space:]]*=' "$cfg"; then
    sed '/^[[:space:]]*experimental_use_rmcp_client[[:space:]]*=/d' "$cfg" > "$cfg.tmp" \
      && mv "$cfg.tmp" "$cfg" || return 1
  fi

  awk '
    /^[[:space:]]*\[mcp_servers\.("?agentlas"?|"?hephaestus-network"?)(\.|\])[[:space:]]*/ { skip=1; next }
    skip && /^[[:space:]]*\[/ { skip=0 }
    !skip { print }
  ' "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg" || return 1
  printf '\n[mcp_servers.hephaestus-network]\ncommand = "%s"\nargs = ["mcp", "serve"]\n' \
    "$HOME/.agentlas/runtime/current/bin/hephaestus" >> "$cfg"
  log "Registered canonical local hephaestus-network MCP in $cfg"
}

write_gemini_fallback_command() {
  local command_dir="$HOME/.gemini/commands"
  mkdir -p "$command_dir"
  local name
  for name in hep-build.toml hep-network.toml hep-local.toml hep-cloud.toml hep-hub.toml hep-search.toml hep-browser.toml hep-call.toml hep-upload.toml hep-storm.toml; do
    rm -f "$command_dir/$name"
    cp "$source_dir/gemini/extension/commands/$name" "$command_dir/$name" || return 1
  done
  rm -f "$command_dir/hephaestus.toml" "$command_dir/hephaests-network.toml" \
        "$command_dir/hephaestus-build.toml" "$command_dir/hephaestus-network.toml" \
        "$command_dir/hephaestus-cloud.toml" "$command_dir/hephaestus-search.toml" \
        "$command_dir/hephaestus-call.toml"
  log "Installed Gemini fallback commands: /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-search, /hep-browser, /hep-call, /hep-upload, /hep-storm"
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
  chmod +x "$gemini_extension_dir/bin/hephaestus" 2>/dev/null || true
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
  # Current Antigravity installs leave this CLI state directory even before a
  # global_workflows directory exists. Treat it as a presence marker, but keep
  # workflow installation in the documented antigravity/antigravity-ide roots.
  [[ -d "$HOME/.gemini/antigravity-cli" ]] && return 0
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

  # 두 데이터 디렉토리 변형 모두에 설치한다 — 어느 앱을 쓰든 같은 명령 집합이 보이게.
  local installed=0
  local data_dir
  for data_dir in "$HOME/.gemini/antigravity" "$HOME/.gemini/antigravity-ide"; do
    # 존재하는 데이터 디렉토리에만 설치하되, 둘 다 없으면 기본 경로를 생성한다.
    if [[ -d "$data_dir" || ( "$installed" -eq 0 && "$data_dir" == "$HOME/.gemini/antigravity" ) ]]; then
      local global_dir="$data_dir/global_workflows"
      mkdir -p "$global_dir"
      local name
      for name in hep-build.md hep-network.md hep-local.md hep-cloud.md hep-hub.md hep-search.md hep-browser.md hep-call.md hep-upload.md hep-storm.md; do
        rm -f "$global_dir/$name"
        cp "$source_dir/antigravity/workflows/$name" "$global_dir/$name" || return 1
      done
      rm -f "$global_dir/hephaestus.md" "$global_dir/hephaests-network.md" \
            "$global_dir/hephaestus-build.md" "$global_dir/hephaestus-network.md" \
            "$global_dir/hephaestus-cloud.md" "$global_dir/hephaestus-search.md" \
            "$global_dir/hephaestus-call.md"
      log "Installed Antigravity global workflows: /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-search, /hep-browser, /hep-call, /hep-upload, /hep-storm"
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
  local py=""
  py="$(resolve_python_cmd || true)"
  if [[ -z "$py" ]]; then
    warn "python3 not found; add local hephaestus-network MCP to $cfg manually."
    return 0
  fi
  mkdir -p "$cfg_dir"
  AGENTLAS_LOCAL_MCP="$HOME/.agentlas/runtime/current/bin/hephaestus" \
    "$py" - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
local = os.environ["AGENTLAS_LOCAL_MCP"]
try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError as exc:
    raise SystemExit(f"refusing to overwrite invalid MCP config {path}: {exc}")
servers = data.setdefault("mcpServers", {})
servers.pop("agentlas", None)
servers["hephaestus-network"] = {"command": local, "args": ["mcp", "serve"]}
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
  log "Registered canonical local hephaestus-network Core in $cfg"
}

# Cursor uses one merge-safe JSON registry. Migrate the old direct remote key
# away and own only the canonical local Workforce key.
register_cursor_mcp() {
  local cfg="$HOME/.cursor/mcp.json"
  local py=""
  py="$(resolve_python_cmd || true)"
  [[ -n "$py" ]] || { warn "python3 not found; skipped Cursor MCP registration."; return 1; }
  mkdir -p "$(dirname "$cfg")"
  AGENTLAS_LOCAL_MCP="$HOME/.agentlas/runtime/current/bin/hephaestus" \
    "$py" - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError as exc:
    raise SystemExit(f"refusing to overwrite invalid Cursor MCP config {path}: {exc}")
servers = data.setdefault("mcpServers", {})
servers.pop("agentlas", None)
servers["hephaestus-network"] = {
    "command": os.environ["AGENTLAS_LOCAL_MCP"],
    "args": ["mcp", "serve"],
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
}

# OpenCode's global JSON config keeps one local Workforce MCP under `mcp`.
# JSONC-only user configs are left untouched; unrelated keys are preserved.
register_opencode_mcp() {
  local cfg="$HOME/.config/opencode/opencode.json"
  local py=""
  py="$(resolve_python_cmd || true)"
  [[ -n "$py" ]] || { warn "python3 not found; skipped OpenCode MCP registration."; return 1; }
  mkdir -p "$(dirname "$cfg")"
  AGENTLAS_LOCAL_MCP="$HOME/.agentlas/runtime/current/bin/hephaestus" \
    "$py" - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError as exc:
    raise SystemExit(f"refusing to overwrite invalid OpenCode config {path}: {exc}")
servers = data.setdefault("mcp", {})
servers.pop("agentlas", None)
servers["hephaestus-network"] = {
    "type": "local",
    "command": [os.environ["AGENTLAS_LOCAL_MCP"], "mcp", "serve"],
    "enabled": True,
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
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
  local name
  for name in hep-build.md hep-network.md hep-local.md hep-cloud.md hep-hub.md hep-search.md hep-browser.md hep-call.md hep-upload.md hep-storm.md; do
    rm -f "$HOME/.cursor/commands/$name"
    cp "$source_dir/cursor/plugin/commands/$name" "$HOME/.cursor/commands/$name" || return 1
  done
  rm -f "$HOME/.cursor/commands/hephaestus.md" "$HOME/.cursor/commands/hephaests-network.md" \
        "$HOME/.cursor/commands/hephaestus-build.md" "$HOME/.cursor/commands/hephaestus-network.md" \
        "$HOME/.cursor/commands/hephaestus-cloud.md" "$HOME/.cursor/commands/hephaestus-search.md" \
        "$HOME/.cursor/commands/hephaestus-call.md"
  for name in hephaestus-network hephaestus-cloud hephaestus-storm; do
    rm -rf "$HOME/.cursor/skills/$name"
    cp -R "$source_dir/skills/$name" "$HOME/.cursor/skills/$name" || return 1
  done
  register_cursor_mcp || warn "Cursor MCP registration failed; add local hephaestus-network to ~/.cursor/mcp.json manually."
  log "Installed Cursor commands (/hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-search, /hep-browser, /hep-call, /hep-upload, /hep-storm), skills, and canonical Workforce MCP."
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
  local name
  for name in hep-build.md hep-network.md hep-local.md hep-cloud.md hep-hub.md hep-search.md hep-browser.md hep-call.md hep-upload.md hep-storm.md; do
    rm -f "$HOME/.config/opencode/commands/$name"
    cp "$source_dir/opencode/commands/$name" "$HOME/.config/opencode/commands/$name" || return 1
  done
  rm -f "$HOME/.config/opencode/commands/hephaestus.md" "$HOME/.config/opencode/commands/hephaests-network.md" \
        "$HOME/.config/opencode/commands/hephaestus-build.md" "$HOME/.config/opencode/commands/hephaestus-network.md" \
        "$HOME/.config/opencode/commands/hephaestus-cloud.md" "$HOME/.config/opencode/commands/hephaestus-search.md" \
        "$HOME/.config/opencode/commands/hephaestus-call.md"
  register_opencode_mcp || warn "OpenCode MCP registration failed; add local hephaestus-network to ~/.config/opencode/opencode.json manually."
  log "Installed OpenCode commands and canonical Workforce MCP: /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-search, /hep-browser, /hep-call, /hep-upload, /hep-storm"
  ok=$((ok + 1))
}

# Claude and Codex receive their memory hook from the plugin bundle. These
# global-only hosts need merge-safe installation into their documented config
# locations. The helper owns only the Agentlas hook key/files and preserves all
# unrelated user configuration.
install_memory_hooks() {
  ensure_downloaded_source || return 1
  local py=""
  py="$(resolve_python_cmd || true)"
  if [[ -z "$py" ]]; then
    warn "Python 3.9+ not found; skipped Antigravity/Grok/OpenCode memory hooks."
    return 1
  fi
  log "== Local ontology memory hooks =="
  local hook_output=""
  if ! hook_output="$(
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 \
      $py "$source_dir/scripts/install-memory-hooks.py" \
      --source-dir "$source_dir" --home "$HOME" --hosts auto 2>&1
  )"; then
    warn "Local memory hook install failed. Error was:"
    printf '%s\n' "$hook_output" | tail -12 >&2
    return 1
  fi
  log "Installed merge-safe local memory hooks for detected Antigravity, Grok, and OpenCode hosts."
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
  local name skill_src
  mkdir -p "$HOME/.openclaw/skills"
  for name in hephaestus-network hephaestus-cloud hephaestus-storm; do
    skill_src="$source_dir/openclaw/skills/$name"
    if have openclaw && openclaw skills install "$skill_src" --global >/dev/null 2>&1; then
      log "Installed OpenClaw skill via: openclaw skills install --global ($name)"
    else
      rm -rf "$HOME/.openclaw/skills/$name"
      cp -R "$skill_src" "$HOME/.openclaw/skills/$name" || return 1
    fi
  done
  log "Installed OpenClaw skills: hephaestus-network, hephaestus-cloud, and hephaestus-storm"
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
  local name
  for name in hephaestus-network hephaestus-cloud hephaestus-storm; do
    rm -rf "$HOME/.hermes/skills/$name"
    cp -R "$source_dir/skills/$name" "$HOME/.hermes/skills/$name" || return 1
  done
  log "Installed Hermes skills: hephaestus-network, hephaestus-cloud, and hephaestus-storm (MCP: see hermes/README.md)"
  ok=$((ok + 1))
}

# Hephaestus Network 2.0: create or migrate ~/.agentlas/networking on every
# install/upgrade (idempotent; indexes only registered paths, never the home
# folder).
bootstrap_networking() {
  local py=""
  py="$(resolve_python_cmd || true)"
  if [[ -z "$py" ]]; then
    warn "python3 not found; skipped Hephaestus Network init. Install Python 3.9+ and run: hephaestus network init"
    return 0
  fi
  if ! ensure_downloaded_source; then
    warn "Hephaestus Network init skipped: could not download the source archive (curl/tar). Run later: hephaestus network init"
    return 0
  fi
  log "== Hephaestus Network (global routing structure) =="
  local init_output
  if ! init_output="$(PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONPATH="$source_dir${PYTHONPATH:+:$PYTHONPATH}" $py -m agentlas_cloud network init 2>&1)"; then
    warn "Hephaestus Network init failed. Error was:"
    printf '%s\n' "$init_output" | tail -5 >&2
    warn "Retry manually: PYTHONPATH=<hephaestus-source> $py -m agentlas_cloud network init"
    return 1
  fi
  PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONPATH="$source_dir${PYTHONPATH:+:$PYTHONPATH}" $py -m agentlas_cloud network reindex >/dev/null 2>&1 || true
  log "Initialized ~/.agentlas/networking (cards, policies, ledgers, local memory map)."
}

prune_legacy_public_surfaces() {
  local stale_md=(
    hephaestus.md
    hephaests-network.md
    agentlas-auto-activation.md
    agentlas-core-engine-meta-agent.md
    agentlas-packaging.md
    agentlas-security-scan.md
    clarify-question-loop.md
    mode-classification.md
    self-evolving-single-agent.md
    skill-lifecycle-promotion.md
    team-builder-packaging.md
  )
  local name
  for name in "${stale_md[@]}"; do
    rm -f "$HOME/.claude/commands/$name"
    rm -f "$HOME/.codex/prompts/$name"
    rm -f "$HOME/.cursor/commands/$name"
    rm -f "$HOME/.config/opencode/commands/$name"
    rm -f "$HOME/.gemini/antigravity/global_workflows/$name"
    rm -f "$HOME/.gemini/antigravity-ide/global_workflows/$name"
  done
  rm -f "$HOME/.gemini/commands/hephaestus.toml" "$HOME/.gemini/commands/hephaests-network.toml"
  rm -f "$HOME/.gemini/commands/agentlas-auto-activation.toml" \
        "$HOME/.gemini/commands/agentlas-core-engine-meta-agent.toml" \
        "$HOME/.gemini/commands/agentlas-packaging.toml" \
        "$HOME/.gemini/commands/agentlas-security-scan.toml" \
        "$HOME/.gemini/commands/clarify-question-loop.toml" \
        "$HOME/.gemini/commands/mode-classification.toml" \
        "$HOME/.gemini/commands/self-evolving-single-agent.toml" \
        "$HOME/.gemini/commands/skill-lifecycle-promotion.toml" \
        "$HOME/.gemini/commands/team-builder-packaging.toml"
  find "$HOME/.claude/plugins/cache/$marketplace_name/$plugin_name" -maxdepth 1 -type d \
    \( -name '0-7-4' -o -name '0.7.4' \) -exec rm -rf {} + 2>/dev/null || true
  find "${CODEX_HOME:-$HOME/.codex}/plugins/cache/$marketplace_name/$plugin_name" -maxdepth 1 -type d \
    \( -name '0-7-4' -o -name '0.7.4' \) -exec rm -rf {} + 2>/dev/null || true
  log "Pruned legacy visible chat command files and stale 0.7.4 cache folders."
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
  stamp_plugin_cache_releases || warn "Plugin cache release marker refresh failed."
  install_gemini || { warn "Gemini install failed."; failed=$((failed + 1)); }
  install_antigravity || { warn "Antigravity install failed."; failed=$((failed + 1)); }
  install_cursor || { warn "Cursor install failed."; failed=$((failed + 1)); }
  install_opencode || { warn "OpenCode install failed."; failed=$((failed + 1)); }
  install_memory_hooks || { warn "Local ontology memory hook install failed."; failed=$((failed + 1)); }
  install_openclaw || { warn "OpenClaw install failed."; failed=$((failed + 1)); }
	  install_hermes || { warn "Hermes install failed."; failed=$((failed + 1)); }
	  bootstrap_networking || warn "Hephaestus Network init failed; run 'hephaestus network init' manually."
	  if [[ "${HEPHAESTUS_INSTALL_GLOBAL_ROUTER:-0}" == "1" ]]; then
	    "$HOME/.agentlas/runtime/current/bin/hephaestus" global install || warn "Global router prompt install failed; run 'hep-global install' manually."
	  fi
	  prune_legacy_public_surfaces

  log ""
  log "Installed/updated runtimes: $ok"
  log "Failed runtimes: $failed"
  log ""
  log "Public chat surface: core external commands are installed or refreshed; Claude/Codex also get the Telegram connect helper; Agentlas native surfaces use plain language."
  log "Local memory recall: Claude/Codex hooks, Antigravity PreInvocation, and OpenCode system injection are dynamic; Grok uses passive cache refresh plus its static AGENTS.md pointer."
  log "Restart open Claude Code, Codex, Gemini, Antigravity, Cursor, OpenCode, OpenClaw, and Hermes apps."
  log "Then use:"
  log "  Agentlas:    describe the task in plain language; native tools choose the path"
	  log "  Claude Code: /reload-plugins, then /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload, /hep-connect"
	  log "  Codex:       /prompts:hep-build, /prompts:hep-network, /prompts:hep-local, /prompts:hep-cloud, /prompts:hep-hub, /prompts:hep-storm, /prompts:hep-search, /prompts:hep-browser, /prompts:hep-call, /prompts:hep-upload, /prompts:hep-connect"
	  log "  Gemini CLI:  /extensions list or /commands list, then /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload"
	  log "  Antigravity: reopen the workspace, then /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload"
	  log "  Cursor:      /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload"
	  log "  OpenCode:    /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload"
	  log "  OpenClaw:    /skill hephaestus-storm <request> or /skill hephaestus-network <request>"
	  log "  Hermes:      hephaestus-storm/hephaestus-network skills (+ MCP, see hermes/README.md)"
	  log "  Shell/debug: ontology <command>, hep-build \"<request>\", hep-network \"<request>\", hep-local \"<request>\", hep-cloud \"<request>\", hep-hub \"<request>\", hep-search \"<request>\", hep-browser <url-or-query>, hep-call \"agent-a,agent-b\" \"<context>\", hep-upload <agent-folder>, hep-global install, or hep-storm \"<request>\" --background"
  log "  Ollama/Gemma/DeepSeek local models: use the local MCP entrypoint 'hephaestus mcp serve'"
  log ""
  log "MCP topology: hephaestus-network is the only host-visible Workforce entrypoint; Cloud/Hub upstream stays inside Agentlas OS Core."
  log "Try a plain-language prompt in any runtime, e.g.:"
  log "  \"agentlas에서 ASO 도와주는 에이전트 찾아줘\"  /  \"find an agentlas agent for app store reviews\""

  if [[ "$ok" -eq 0 || "$failed" -gt 0 ]]; then
    exit 1
  fi
}

main "$@"
