#!/usr/bin/env bash
set -uo pipefail

export PYTHONDONTWRITEBYTECODE=1

agentlas_installer_python_cache_prefix() {
  local home_real prefix
  [[ -n "${HOME:-}" && "$HOME" == /* && -d "$HOME" ]] || return 1
  home_real="$(cd -P "$HOME" 2>/dev/null && pwd)" || return 1
  case "$(uname -s 2>/dev/null || true)" in
    Darwin) prefix="$home_real/Library/Caches/Agentlas/python" ;;
    *) prefix="$home_real/.cache/agentlas/python" ;;
  esac
  [[ "$prefix" == /* && "$prefix" != *$'\n'* && "$prefix" != *$'\r'* ]] || return 1
  case "$prefix" in
    *.app/Contents/Resources|*.app/Contents/Resources/*|*/resources|*/resources/*)
      return 1
      ;;
  esac
  printf '%s\n' "$prefix"
}

PYTHONPYCACHEPREFIX="$(agentlas_installer_python_cache_prefix)" || {
  printf '%s\n' "Agentlas OS installer could not establish a safe external Python cache directory." >&2
  exit 78
}
export PYTHONPYCACHEPREFIX

version="${HEPHAESTUS_REF:-v1.1.111}"
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

# Platform helpers (agentlas_is_windows / agentlas_native_path /
# agentlas_path_sep / agentlas_mcp_launch) are canonical in
# bin/agentlas-python-cache-boundary. The installer SOURCES them from the
# downloaded release instead of re-implementing them: a second copy of "how do
# we spell a path on Windows" is exactly how every MCP registration below ended
# up hardcoding an extensionless bash runner that native Windows cannot spawn.
agentlas_load_platform_helpers() {
  if declare -F agentlas_is_windows >/dev/null 2>&1; then
    return 0
  fi
  ensure_downloaded_source || return 1
  # shellcheck source=/dev/null
  source "$source_dir/bin/agentlas-python-cache-boundary" || return 1
  declare -F agentlas_is_windows >/dev/null 2>&1
}

# PYTHONPATH for a runtime root, in the form the interpreter on THIS platform can
# read: native path, native separator. The colon-joined POSIX form this replaces
# produces one unusable entry on Windows, and the symptom is
# `ModuleNotFoundError: No module named 'agentlas_cloud'`.
installer_pythonpath() {
  local root="$1" native sep
  if agentlas_load_platform_helpers >/dev/null 2>&1; then
    native="$(agentlas_native_path "$root")"
    sep="$(agentlas_path_sep)"
  else
    native="$root"
    sep=":"
  fi
  if [[ -n "${PYTHONPATH:-}" ]]; then
    printf '%s%s%s\n' "$native" "$sep" "$PYTHONPATH"
  else
    printf '%s\n' "$native"
  fi
}

# Absolute path of the installed local Core MCP runner, without extension.
runtime_mcp_runner() {
  printf '%s\n' "$HOME/.agentlas/runtime/current/bin/hephaestus"
}

# One place decides how a host must spell "launch the local Core MCP server":
# command on the first line, then one argument per line. Eight host
# registrations render from this, so the platform rule is fixed once instead of
# eight times.
runtime_mcp_launch_fields() {
  local runner
  runner="$(runtime_mcp_runner)"
  if agentlas_load_platform_helpers; then
    agentlas_mcp_launch "$runner"
  else
    warn "Platform helpers unavailable; assuming a POSIX MCP launch vector."
    printf '%s\n' "$runner" "mcp" "serve"
  fi
}

# Render the launch vector for a config format. Everything goes through
# json.dumps because a Windows path carries backslashes, and an unescaped
# backslash silently corrupts JSON, TOML and YAML alike.
runtime_mcp_launch_render() {
  local shape="$1" py=""
  py="$(resolve_python_cmd || true)"
  [[ -n "$py" ]] || return 1
  # shellcheck disable=SC2086
  runtime_mcp_launch_fields | AGENTLAS_RENDER_SHAPE="$shape" $py -c 'import json, os, sys
fields = [line.rstrip("\n") for line in sys.stdin if line.strip()]
if not fields:
    raise SystemExit(1)
command, args = fields[0], fields[1:]
shape = os.environ["AGENTLAS_RENDER_SHAPE"]
array = "[" + ", ".join(json.dumps(a) for a in args) + "]"
if shape == "json":
    print(json.dumps({"command": command, "args": args}))
elif shape == "toml":
    print("command = " + json.dumps(command))
    print("args = " + array)
elif shape == "yaml":
    print("cmd: " + json.dumps(command))
    print("args: " + array)
else:
    raise SystemExit(f"unknown render shape: {shape}")'
}

# Commands that live in the repo for the repo's own adapter surface and are
# never installed into a user's global command directory.
project_only_commands=(
  "meta-agent.md"
)

# The managed command set is DERIVED from the release, never typed out again.
# Six hardcoded copies of this list is how `agentlas-one` reached no machine and
# `hep-graph` reached no installer, while every other command shipped fine.
managed_command_files() {
  ensure_downloaded_source || return 1
  local dir="$source_dir/.claude/commands"
  if [[ ! -d "$dir" ]]; then
    warn "release is missing .claude/commands; cannot derive the managed command set."
    return 1
  fi
  local path name skip excluded
  for path in "$dir"/*.md; do
    [[ -e "$path" ]] || continue
    name="$(basename "$path")"
    skip=0
    for excluded in "${project_only_commands[@]}"; do
      [[ "$name" == "$excluded" ]] && skip=1
    done
    [[ "$skip" == "1" ]] && continue
    printf '%s\n' "$name"
  done
}

# The managed commands a given runtime actually has an adapter for. Intersecting
# with what the release ships means a runtime is never asked to install a file
# that does not exist, and a newly added command reaches every runtime that
# carries it without editing this script again.
runtime_command_files() {
  local adapter_dir="$1" name
  managed_command_files | while IFS= read -r name; do
    [[ -f "$adapter_dir/$name" ]] && printf '%s\n' "$name"
  done
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
  # system-agents/ carries the canonical curator-ruleset.json. one_workspace.py
  # resolves it as here.parent/system-agents/curator-ruleset.json, so without it
  # the stop-hook curator falls back to the embedded ruleset on every install and
  # stamps sha="embedded" into every decision receipt (2026-08-12 set 4). The
  # release archive ships only that one file under system-agents/.
  cp -R "$source_dir/bin" "$source_dir/agentlas_cloud" "$source_dir/career_graph" \
    "$source_dir/ontology" "$source_dir/schemas" "$source_dir/templates" \
    "$source_dir/system-agents" \
    "$home_dir/" || return 1
  # Hook packs must travel with the runner: `agentlas-one on` installs them, and
  # a user who never re-runs the installer would otherwise never receive them.
  local pack
  for pack in goose openclaw; do
    [[ -d "$source_dir/$pack" ]] || continue
    rm -rf "${home_dir:?}/$pack"
    cp -R "$source_dir/$pack" "$home_dir/$pack" || return 1
  done
  cp "$source_dir/package-contract.json" "$home_dir/package-contract.json" || return 1
  mkdir -p "$(dirname "$model_dest")"
  cp -R "$model_source" "$model_dest" || return 1
  if ! PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONPATH="$(installer_pythonpath "$home_dir")" \
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
	    "$home_dir/bin/agentlas-memory-hook" \
	    "$home_dir/bin/agentlas-one" 2>/dev/null || true
  printf '%s\n' "$version" > "$home_dir/RELEASE"
  write_python3_shim "$home_dir/bin" || true
  write_windows_command_shims "$home_dir/bin" || true
  if [[ ! -e "$home_dir/bin/Hephaestus" ]]; then
    ln -sfn hephaestus "$home_dir/bin/Hephaestus" 2>/dev/null || true
  fi
  # Agentlas Terminal owns the `agentlas` shell command as an independent
  # product surface. Core must not shadow it with a Hephaestus alias.
  rm -f "$home_dir/bin/agentlas" 2>/dev/null || true
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
    # Older Core releases installed this exact managed shim. Remove only that
    # retired alias; preserve an independently installed Agentlas Terminal
    # launcher or any other user-owned command.
    local legacy_agentlas_shim="$user_bin/agentlas"
    local legacy_agentlas_exec="exec \"$current_link/bin/agentlas\" \"\$@\""
    if [[ -f "$legacy_agentlas_shim" ]] \
      && [[ "$(sed -n '1p' "$legacy_agentlas_shim")" == "#!/usr/bin/env bash" ]] \
      && [[ "$(sed -n '2p' "$legacy_agentlas_shim")" == "$legacy_agentlas_exec" ]] \
      && [[ "$(wc -l < "$legacy_agentlas_shim" | tr -d '[:space:]')" == "2" ]]; then
      rm -f "$legacy_agentlas_shim"
      log "Removed retired Core-owned agentlas alias; Agentlas Terminal keeps command ownership."
    fi
	  # agentlas-one belongs here: it is the documented switch for the persistent
	  # personal agent, and leaving it out of this list is why `agentlas-one on`
	  # was not a command on any machine — the runner shipped, but nothing put it
	  # on PATH.
	  local -a shell_commands=(
	    hephaestus ontology hep-build hep-network hep-local hep-cloud hep-hub hep-search hep-browser hep-call hep-upload hep-storm hep-global hep-update agentlas-one
	  )
    local command
    local windows_shims=0
    agentlas_load_platform_helpers >/dev/null 2>&1 || true
    for command in "${shell_commands[@]}"; do
      rm -f "$user_bin/$command" 2>/dev/null || true
      cat > "$user_bin/$command" <<EOF
#!/usr/bin/env bash
exec "$current_link/bin/$command" "\$@"
EOF
      chmod +x "$user_bin/$command" 2>/dev/null || true
      # A bash shim is invisible to cmd.exe and PowerShell, so on Windows the
      # same command also needs a .cmd sibling. Without it none of these
      # commands exist outside Git Bash.
      if declare -F agentlas_is_windows >/dev/null 2>&1 && agentlas_is_windows; then
        rm -f "$user_bin/$command.cmd" 2>/dev/null || true
        {
          printf '@echo off\r\n'
          printf 'setlocal\r\n'
          printf '"%s" %%*\r\n' "$(agentlas_native_path "$current_link/bin/$command.cmd")"
          printf 'if errorlevel 1 exit /b %%ERRORLEVEL%%\r\n'
        } > "$user_bin/$command.cmd" 2>/dev/null && windows_shims=$((windows_shims + 1))
      fi
    done
    if [[ -x "$user_bin/hephaestus" ]]; then
      case ":$PATH:" in
	        *":$user_bin:"*) log "Installed shell commands: ${shell_commands[*]}" ;;
        *) log "Installed shell commands in $user_bin (add ~/.local/bin to PATH to use them)" ;;
      esac
    fi
    if [[ "$windows_shims" -gt 0 ]]; then
      log "Installed $windows_shims Windows .cmd shims in $user_bin (add it to PATH for cmd.exe and PowerShell)."
    fi
  fi
}

write_python3_shim() {
  local bin_dir="$1"
  local py py_cache py_cache_quoted
  py="$(resolve_python_cmd || true)"
  rm -f "$bin_dir/python3" "$bin_dir/python3.cmd" 2>/dev/null || true
  [[ -n "$py" ]] || return 0
  py_cache="$(agentlas_installer_python_cache_prefix)" || return 1
  printf -v py_cache_quoted '%q' "$py_cache"
  mkdir -p "$bin_dir"
  if [[ "$py" == "py -3" ]]; then
    cat > "$bin_dir/python3" <<EOF
#!/usr/bin/env bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX=$py_cache_quoted
exec py -3 "\$@"
EOF
    cat > "$bin_dir/python3.cmd" <<'EOF'
@echo off
setlocal
set "PYTHONDONTWRITEBYTECODE=1"
if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\Agentlas\PythonCache") else (set "PYTHONPYCACHEPREFIX=%TEMP%\Agentlas-PythonCache")
py -3 %*
exit /b %ERRORLEVEL%
EOF
  else
    cat > "$bin_dir/python3" <<EOF
#!/usr/bin/env bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX=$py_cache_quoted
exec "$py" "\$@"
EOF
    cat > "$bin_dir/python3.cmd" <<EOF
@echo off
setlocal
set "PYTHONDONTWRITEBYTECODE=1"
if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\Agentlas\PythonCache") else (set "PYTHONPYCACHEPREFIX=%TEMP%\Agentlas-PythonCache")
"$py" %*
exit /b %ERRORLEVEL%
EOF
  fi
  cat > "$bin_dir/hephaestus.cmd" <<'EOF'
@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\Agentlas\PythonCache") else (set "PYTHONPYCACHEPREFIX=%TEMP%\Agentlas-PythonCache")
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
set "PYTHONDONTWRITEBYTECODE=1"
if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\Agentlas\PythonCache") else (set "PYTHONPYCACHEPREFIX=%TEMP%\Agentlas-PythonCache")
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
EOF
  chmod +x "$bin_dir/python3"
}

# Every shell command in the runtime is a bash script, and cmd.exe cannot run a
# bash script or an extensionless file at all. On Windows each one therefore
# needs a .cmd sibling that hands the script to the bash that is running this
# installer — resolved to an absolute native path, because bash.exe is usually
# NOT on the PATH that cmd.exe and PowerShell see.
#
# hephaestus.cmd is deliberately excluded: it is the native Python entrypoint
# written by write_python3_shim and must not be routed through bash.
write_windows_command_shims() {
  local bin_dir="$1"
  agentlas_load_platform_helpers >/dev/null 2>&1 || return 0
  agentlas_is_windows || return 0

  local bash_path bash_native
  bash_path="$(command -v bash 2>/dev/null || true)"
  [[ -n "$bash_path" ]] || { warn "bash not found; skipped Windows command shims."; return 0; }
  bash_native="$(agentlas_native_path "$bash_path")" || return 0

  local name script written=0
  for script in "$bin_dir"/*; do
    [[ -f "$script" ]] || continue
    name="$(basename "$script")"
    case "$name" in
      *.cmd|python3|hephaestus|Hephaestus) continue ;;
    esac
    # Only wrap actual shell scripts; a data file must not become a command.
    head -1 "$script" 2>/dev/null | grep -q '^#!.*sh' || continue
    {
      printf '@echo off\r\n'
      printf 'setlocal\r\n'
      printf '"%s" "%s" %%*\r\n' "$bash_native" "$(agentlas_native_path "$script")"
      printf 'exit /b %%ERRORLEVEL%%\r\n'
    } > "$bin_dir/$name.cmd" 2>/dev/null && written=$((written + 1))
  done
  [[ "$written" -gt 0 ]] && log "Wrote $written Windows .cmd wrappers in $bin_dir"
  return 0
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

  # `marketplace add` fails when the marketplace is already registered, and a
  # hard `return 1` here used to abandon the whole Claude step: no plugin
  # install, no command refresh, and the previous release's plugin cache left in
  # place as the live one. An already-registered marketplace is a success state
  # for this installer, so absorb it with `update` and keep going.
  local marketplace_source=""
  if [[ -n "$requested_source_dir" ]]; then
    marketplace_source="$source_dir/claude"
    run claude plugin marketplace add "$marketplace_source" \
      || try claude plugin marketplace update "$marketplace_name" >/dev/null 2>&1 \
      || warn "Marketplace $marketplace_name could not be added or updated; continuing with the registered copy."
  else
    run claude plugin marketplace add "$github_url" --sparse .claude-plugin claude/plugins \
      || try claude plugin marketplace update "$marketplace_name" >/dev/null 2>&1 \
      || warn "Marketplace $marketplace_name could not be added or updated; continuing with the registered copy."
  fi

  run claude plugin install "$plugin_name@$marketplace_name" || return 1
  try claude plugin enable "$plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  write_claude_commands || {
    warn "Claude global command refresh failed; bare /hep-* autocomplete will not persist into the next session."
    return 1
  }
  register_claude_mcp || warn "Windows user-scope MCP registration failed; run the command printed above manually."
  prune_claude_plugin_cache || warn "Old plugin cache versions were left in place."
  log "Bundled MCP: local hephaestus-network Core (Cloud/Hub upstream stays behind Core)."
  ok=$((ok + 1))
}

# The plugin's own .mcp.json points at the extensionless bash runner, and a
# plugin manifest has no platform-conditional key to fix that (Claude Code
# plugins reference: command/args/env plus ${CLAUDE_PLUGIN_ROOT}, nothing else).
# Native Windows spawns stdio servers WITHOUT a shell, so that entry can never
# start there and the whole local Workforce surface is missing — which is how a
# Windows session ends up talking to the remote Hub with no menu projection.
#
# Register a user-scope server on Windows only. Claude Code namespaces plugin
# MCP tools separately from user-scope ones, so this does not collide with the
# POSIX plugin channel; on macOS/Linux the plugin entry is already correct and
# this function is a no-op.
register_claude_mcp() {
  agentlas_load_platform_helpers || return 1
  agentlas_is_windows || return 0

  local -a fields=()
  local field
  while IFS= read -r field; do
    [[ -n "$field" ]] && fields+=("$field")
  done < <(runtime_mcp_launch_fields)
  [[ "${#fields[@]}" -ge 2 ]] || return 1

  try claude mcp remove hephaestus-network --scope user >/dev/null 2>&1 || true
  run claude mcp add --scope user hephaestus-network -- "${fields[@]}" || return 1
  log "Registered user-scope hephaestus-network MCP for native Windows."
}

# Plugin cache versions accumulate without bound (measured: seven releases in
# one cache). Keep the active version and one rollback target; anything older is
# an orphan that only confuses `claude plugin` output.
prune_claude_plugin_cache() {
  local cache="$HOME/.claude/plugins/cache/$marketplace_name/$plugin_name"
  [[ -d "$cache" ]] || return 0
  local keep="${version#v}"
  local -a stale=()
  local dir name
  while IFS= read -r dir; do
    name="$(basename "$dir")"
    [[ "$name" == "$keep" ]] && continue
    stale+=("$name")
  done < <(find "$cache" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
  # sort -V keeps the newest non-active version as the rollback target.
  local -a ordered=()
  while IFS= read -r name; do
    [[ -n "$name" ]] && ordered+=("$name")
  done < <(printf '%s\n' "${stale[@]+"${stale[@]}"}" | sort -t. -k1,1n -k2,2n -k3,3n)
  local total="${#ordered[@]}"
  [[ "$total" -gt 1 ]] || return 0
  local index=0
  local removed=0
  while [[ "$index" -lt $((total - 1)) ]]; do
    rm -rf "$cache/${ordered[$index]}" 2>/dev/null && removed=$((removed + 1))
    index=$((index + 1))
  done
  [[ "$removed" -gt 0 ]] && log "Pruned $removed orphaned plugin cache version(s); kept $keep and ${ordered[$((total - 1))]}."
  return 0
}

# Keep the user-global ~/.claude/commands copies in sync with this release.
# Remove old entries first so stale symlinks from earlier installers do not
# survive in the host app's command autocomplete cache.
write_claude_commands() {
  ensure_downloaded_source || return 1
  mkdir -p "$HOME/.claude/commands"
  local name src dest installed=""
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    src="$source_dir/.claude/commands/$name"
    dest="$HOME/.claude/commands/$name"
    rm -f "$dest"
    cp "$src" "$dest" || return 1
    installed+=" /${name%.md}"
  done < <(managed_command_files)
  [[ -n "$installed" ]] || { warn "No managed Claude commands were derived from the release."; return 1; }
  rm -f "$HOME/.claude/commands/hephaestus.md" "$HOME/.claude/commands/hephaests-network.md" \
        "$HOME/.claude/commands/hephaestus-build.md" "$HOME/.claude/commands/hephaestus-network.md" \
        "$HOME/.claude/commands/hephaestus-cloud.md" "$HOME/.claude/commands/hephaestus-search.md" \
        "$HOME/.claude/commands/hephaestus-call.md"
  # Report what was actually installed. A hardcoded sentence here would have
  # kept claiming a complete set while two commands were missing from it.
  log "Refreshed Claude commands:$installed"
}

remove_codex_existing() {
  try codex plugin remove "$plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try codex plugin remove "$old_plugin_name@$marketplace_name" >/dev/null 2>&1 || true
  try codex plugin marketplace remove "$marketplace_name" >/dev/null 2>&1 || true
  rm -rf "${CODEX_HOME:-$HOME/.codex}/plugins/cache/$marketplace_name/$plugin_name" 2>/dev/null || true
}

# Codex 0.117+ removed custom prompts in favor of plugin skills. Keep the
# prompt copier only for older Codex releases and remove only our managed dead
# prompt files on current releases so the installer does not advertise a
# command the host rejects.
codex_custom_prompts_supported() {
  local raw parsed major minor rest
  raw="$(codex --version 2>/dev/null || true)"
  parsed="$(printf '%s\n' "$raw" | sed -nE 's/^[^0-9]*([0-9]+)\.([0-9]+)(\.[0-9]+)?.*/\1.\2/p' | head -1)"
  [[ "$parsed" =~ ^[0-9]+\.[0-9]+$ ]] || return 1
  major="${parsed%%.*}"
  rest="${parsed#*.}"
  minor="${rest%%.*}"
  [[ "$major" == "0" && "$minor" -lt 117 ]]
}

prune_managed_codex_prompts() {
  local name
  while IFS= read -r name; do
    [[ -n "$name" ]] && rm -f "$HOME/.codex/prompts/$name"
  done < <(managed_command_files)
}

write_codex_prompts() {
  ensure_downloaded_source || return 1
  if ! codex_custom_prompts_supported; then
    prune_managed_codex_prompts
    log 'Codex 0.117+ skill entrypoints: $hephaestus-build, $hephaestus-network, $hephaestus-cloud, $hephaestus-upload, $hephaestus-storm'
    return 0
  fi
  local prompts_src="$source_dir/codex/prompts"
  [[ -d "$prompts_src" ]] || { warn "codex prompts not found: $prompts_src"; return 1; }
  mkdir -p "$HOME/.codex/prompts"
  local name installed=""
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    rm -f "$HOME/.codex/prompts/$name"
    cp "$prompts_src/$name" "$HOME/.codex/prompts/$name" || return 1
    installed+=" /prompts:${name%.md}"
  done < <(runtime_command_files "$prompts_src")
  rm -f "$HOME/.codex/prompts/hephaestus.md" "$HOME/.codex/prompts/hephaests-network.md" \
        "$HOME/.codex/prompts/hephaestus-build.md" "$HOME/.codex/prompts/hephaestus-network.md" \
        "$HOME/.codex/prompts/hephaestus-cloud.md" "$HOME/.codex/prompts/hephaestus-search.md" \
        "$HOME/.codex/prompts/hephaestus-call.md"
  log "Installed Codex custom prompts:$installed"
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
  write_codex_prompts || warn "Codex command-surface install failed; reinstall the Hephaestus plugin skills."
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

# The Codex plugin doesn't support MCP bundles, so register directly in config.toml.
# Workforce must have one canonical MCP entrypoint. Remove the old direct
# `agentlas` table (which bypassed Core) and replace the owned local table while
# preserving every unrelated user table. The obsolete remote-MCP feature flag
# is also removed because strict Codex versions reject it.
register_codex_mcp() {
  local cfg="$HOME/.codex/config.toml"
  local preserved_env_table
  mkdir -p "$HOME/.codex"
  touch "$cfg" || return 1

  if grep -q '^[[:space:]]*experimental_use_rmcp_client[[:space:]]*=' "$cfg"; then
    sed '/^[[:space:]]*experimental_use_rmcp_client[[:space:]]*=/d' "$cfg" > "$cfg.tmp" \
      && mv "$cfg.tmp" "$cfg" || return 1
  fi

  # The installer owns the command and args, but the operator owns model pins,
  # provider choices, and other server-launch environment policy. Preserve the
  # complete Codex-generated env subtable without reading or logging its values.
  # This keeps AGENTLAS_MODEL_ALLOCATION_POLICY_JSON stable across updates.
  preserved_env_table="$(
    awk '
      /^[[:space:]]*\[mcp_servers\.("?hephaestus-network"?)\.env\][[:space:]]*$/ {
        capture=1
        print
        next
      }
      capture && /^[[:space:]]*\[/ { capture=0 }
      capture { print }
    ' "$cfg"
  )"

  awk '
    /^[[:space:]]*\[mcp_servers\.("?agentlas"?|"?hephaestus-network"?)(\.|\])[[:space:]]*/ { skip=1; next }
    skip && /^[[:space:]]*\[/ { skip=0 }
    !skip { print }
  ' "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg" || return 1
  local codex_launch=""
  codex_launch="$(runtime_mcp_launch_render toml)" || {
    warn "Could not render the local Core MCP launch vector for Codex."
    return 1
  }
  printf '\n[mcp_servers.hephaestus-network]\n%s\n' "$codex_launch" >> "$cfg"
  if [[ -n "$preserved_env_table" ]]; then
    printf '\n%s\n' "$preserved_env_table" >> "$cfg"
  fi
  log "Registered canonical local hephaestus-network MCP in $cfg"
}

write_gemini_fallback_command() {
  local command_dir="$HOME/.gemini/commands"
  mkdir -p "$command_dir"
  local name
  for name in hep-build.toml hep-network.toml hep-local.toml hep-cloud.toml hep-hub.toml hep-search.toml hep-browser.toml hep-call.toml hep-upload.toml hep-storm.toml agentlas.toml; do
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
  # The "Antigravity IDE" variant uses a separate data directory (~/.gemini/antigravity-ide).
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

  log "== Antigravity workflow & plugins =="
  ensure_downloaded_source || return 1

  # Install into both data directory variants — so the same command set shows up whichever app you use.
  local installed=0
  local data_dir
  for data_dir in "$HOME/.gemini/antigravity" "$HOME/.gemini/antigravity-ide"; do
    # Install only into a data directory that exists, but create the default path if neither exists.
    if [[ -d "$data_dir" || ( "$installed" -eq 0 && "$data_dir" == "$HOME/.gemini/antigravity" ) ]]; then
      local global_dir="$data_dir/global_workflows"
      mkdir -p "$global_dir"
      local name workflows=""
      while IFS= read -r name; do
        [[ -n "$name" ]] || continue
        rm -f "$global_dir/$name"
        cp "$source_dir/antigravity/workflows/$name" "$global_dir/$name" || return 1
        workflows+=" /${name%.md}"
      done < <(runtime_command_files "$source_dir/antigravity/workflows")
      rm -f "$global_dir/hephaestus.md" "$global_dir/hephaests-network.md" \
            "$global_dir/hephaestus-build.md" "$global_dir/hephaestus-network.md" \
            "$global_dir/hephaestus-cloud.md" "$global_dir/hephaestus-search.md" \
            "$global_dir/hephaestus-call.md"
      log "Installed Antigravity global workflows:$workflows"
      installed=$((installed + 1))
    fi
  done

  # Install Agentlas OS plugin & skills into ~/.gemini/config/plugins/agentlas-os
  local plugin_target="$HOME/.gemini/config/plugins/agentlas-os"
  mkdir -p "$plugin_target/skills"
  cat > "$plugin_target/plugin.json" <<EOF
{
  "name": "agentlas-os",
  "version": "${version#v}",
  "description": "Agentlas OS & Hephaestus global agent workforce runtime for Antigravity",
  "author": {
    "name": "Agentlas Team"
  },
  "license": "Apache-2.0"
}
EOF
  if [[ -d "$source_dir/skills" ]]; then
    cp -R "$source_dir/skills"/* "$plugin_target/skills/" 2>/dev/null || true
    log "Installed Antigravity plugin and skills into $plugin_target"
  fi

  [[ "$installed" -gt 0 ]] || return 1
  register_antigravity_mcp || warn "Antigravity MCP registration failed; add it manually to ~/.gemini/config/mcp_config.json."
  ok=$((ok + 1))
}

# Antigravity reads MCP servers from ~/.gemini/config/mcp_config.json (the serverUrl key).
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
  AGENTLAS_LOCAL_MCP_ENTRY="$(runtime_mcp_launch_render json)" \
    "$py" - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
entry = json.loads(os.environ["AGENTLAS_LOCAL_MCP_ENTRY"])
try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError as exc:
    raise SystemExit(f"refusing to overwrite invalid MCP config {path}: {exc}")
servers = data.setdefault("mcpServers", {})
servers.pop("agentlas", None)
servers["hephaestus-network"] = dict(entry)
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
  AGENTLAS_LOCAL_MCP_ENTRY="$(runtime_mcp_launch_render json)" \
    "$py" - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
entry = json.loads(os.environ["AGENTLAS_LOCAL_MCP_ENTRY"])
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError as exc:
    raise SystemExit(f"refusing to overwrite invalid Cursor MCP config {path}: {exc}")
servers = data.setdefault("mcpServers", {})
servers.pop("agentlas", None)
servers["hephaestus-network"] = dict(entry)
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
  AGENTLAS_LOCAL_MCP_ENTRY="$(runtime_mcp_launch_render json)" \
    "$py" - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
entry = json.loads(os.environ["AGENTLAS_LOCAL_MCP_ENTRY"])
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
    # OpenCode takes one argv array rather than command + args.
    "command": [entry["command"], *entry["args"]],
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
  local name cursor_commands=""
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    rm -f "$HOME/.cursor/commands/$name"
    cp "$source_dir/cursor/plugin/commands/$name" "$HOME/.cursor/commands/$name" || return 1
    cursor_commands+=" /${name%.md}"
  done < <(runtime_command_files "$source_dir/cursor/plugin/commands")
  rm -f "$HOME/.cursor/commands/hephaestus.md" "$HOME/.cursor/commands/hephaests-network.md" \
        "$HOME/.cursor/commands/hephaestus-build.md" "$HOME/.cursor/commands/hephaestus-network.md" \
        "$HOME/.cursor/commands/hephaestus-cloud.md" "$HOME/.cursor/commands/hephaestus-search.md" \
        "$HOME/.cursor/commands/hephaestus-call.md"
  for name in hephaestus-network hephaestus-cloud hephaestus-storm; do
    rm -rf "$HOME/.cursor/skills/$name"
    cp -R "$source_dir/skills/$name" "$HOME/.cursor/skills/$name" || return 1
  done
  register_cursor_mcp || warn "Cursor MCP registration failed; add local hephaestus-network to ~/.cursor/mcp.json manually."
  log "Installed Cursor commands ($cursor_commands ), skills, and canonical Workforce MCP."
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
  local name opencode_commands=""
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    rm -f "$HOME/.config/opencode/commands/$name"
    cp "$source_dir/opencode/commands/$name" "$HOME/.config/opencode/commands/$name" || return 1
    opencode_commands+=" /${name%.md}"
  done < <(runtime_command_files "$source_dir/opencode/commands")
  rm -f "$HOME/.config/opencode/commands/hephaestus.md" "$HOME/.config/opencode/commands/hephaests-network.md" \
        "$HOME/.config/opencode/commands/hephaestus-build.md" "$HOME/.config/opencode/commands/hephaestus-network.md" \
        "$HOME/.config/opencode/commands/hephaestus-cloud.md" "$HOME/.config/opencode/commands/hephaestus-search.md" \
        "$HOME/.config/opencode/commands/hephaestus-call.md"
  register_opencode_mcp || warn "OpenCode MCP registration failed; add local hephaestus-network to ~/.config/opencode/opencode.json manually."
  log "Installed OpenCode commands and canonical Workforce MCP:$opencode_commands"
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
  install_openclaw_hook || warn "OpenClaw memory hook install failed; skills remain installed."
  ok=$((ok + 1))
}

# OpenClaw has no session-end event, so the One checkpoint runs on the commands
# that close a session. Copying is the fallback when the CLI is unavailable.
install_openclaw_hook() {
  local hook_src="$source_dir/openclaw/hooks/agentlas-one"
  [[ -d "$hook_src" ]] || { warn "OpenClaw hook source missing: $hook_src"; return 1; }
  if have openclaw && openclaw hooks install "$hook_src" >/dev/null 2>&1; then
    log "Installed OpenClaw hook via: openclaw hooks install (agentlas-one)"
    return 0
  fi
  mkdir -p "$HOME/.openclaw/hooks"
  rm -rf "$HOME/.openclaw/hooks/agentlas-one"
  cp -R "$hook_src" "$HOME/.openclaw/hooks/agentlas-one" || return 1
  log "Installed OpenClaw hook by copy: agentlas-one"
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

# goose (Block) reads the project AGENTS.md natively; its only global surface
# is the MCP extension table in ~/.config/goose/config.yaml. YAML cannot be
# merged safely without extra dependencies, so only a missing config is
# created; an existing config is never rewritten.
install_goose() {
  if ! have goose && [[ ! -d "$HOME/.config/goose" ]]; then
    warn "goose not detected; skipped goose MCP registration."
    return 0
  fi
  log "== goose MCP =="
  local cfg="$HOME/.config/goose/config.yaml"
  if [[ -f "$cfg" ]]; then
    if grep -q 'hephaestus-network' "$cfg"; then
      log "goose config already references hephaestus-network; left $cfg untouched."
    else
      warn "goose config exists; add the hephaestus-network extension manually (see goose/README.md)."
    fi
  else
    mkdir -p "$(dirname "$cfg")"
    local goose_launch=""
    goose_launch="$(runtime_mcp_launch_render yaml | sed 's/^/    /')" || {
      warn "Could not render the local Core MCP launch vector for goose."
      return 1
    }
    cat > "$cfg" <<EOF
extensions:
  hephaestus-network:
    enabled: true
    type: stdio
$goose_launch
    timeout: 300
EOF
    log "Registered canonical local hephaestus-network MCP in $cfg"
  fi
  log "goose reads the project AGENTS.md natively; no goose-specific instruction copy is installed."
  install_goose_hook || warn "goose SessionEnd hook install failed; MCP registration remains."
  ok=$((ok + 1))
}

# goose loads user plugins from ~/.agents/plugins/<name>/hooks/hooks.json and
# uses the same hook manifest shape as Claude Code. Write only our own plugin
# directory so unrelated plugins stay untouched.
install_goose_hook() {
  local src="$source_dir/goose/plugins/agentlas-one"
  [[ -d "$src" ]] || { warn "goose hook source missing: $src"; return 1; }
  local dest="$HOME/.agents/plugins/agentlas-one"
  mkdir -p "$(dirname "$dest")"
  rm -rf "$dest"
  cp -R "$src" "$dest" || return 1
  log "Installed goose SessionEnd hook: ~/.agents/plugins/agentlas-one"
}

# Amp (Sourcegraph) reads the project AGENTS.md natively; its only global
# surface is ~/.config/amp/settings.json. Own only the canonical Workforce MCP
# key and preserve every unrelated setting.
install_amp() {
  if ! have amp && [[ ! -d "$HOME/.config/amp" ]]; then
    warn "Amp not detected; skipped Amp MCP registration."
    return 0
  fi
  log "== Amp MCP =="
  local cfg="$HOME/.config/amp/settings.json"
  local py=""
  py="$(resolve_python_cmd || true)"
  [[ -n "$py" ]] || { warn "python3 not found; add local hephaestus-network to $cfg manually."; return 1; }
  mkdir -p "$(dirname "$cfg")"
  AGENTLAS_LOCAL_MCP_ENTRY="$(runtime_mcp_launch_render json)" \
    "$py" - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
entry = json.loads(os.environ["AGENTLAS_LOCAL_MCP_ENTRY"])
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError as exc:
    raise SystemExit(f"refusing to overwrite invalid Amp settings {path}: {exc}")
servers = data.setdefault("amp.mcpServers", {})
servers.pop("agentlas", None)
servers["hephaestus-network"] = dict(entry)
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
  log "Registered canonical local hephaestus-network MCP in $cfg (Amp reads the project AGENTS.md natively)."
  ok=$((ok + 1))
}

# GitHub Copilot CLI reads the project AGENTS.md natively; its only global
# surface is ~/.copilot/mcp-config.json.
install_copilot_cli() {
  if ! have copilot && [[ ! -d "$HOME/.copilot" ]]; then
    warn "Copilot CLI not detected; skipped Copilot CLI MCP registration."
    return 0
  fi
  log "== Copilot CLI MCP =="
  local cfg="$HOME/.copilot/mcp-config.json"
  local py=""
  py="$(resolve_python_cmd || true)"
  [[ -n "$py" ]] || { warn "python3 not found; add local hephaestus-network to $cfg manually."; return 1; }
  mkdir -p "$(dirname "$cfg")"
  AGENTLAS_LOCAL_MCP_ENTRY="$(runtime_mcp_launch_render json)" \
    "$py" - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
entry = json.loads(os.environ["AGENTLAS_LOCAL_MCP_ENTRY"])
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError as exc:
    raise SystemExit(f"refusing to overwrite invalid Copilot MCP config {path}: {exc}")
servers = data.setdefault("mcpServers", {})
servers.pop("agentlas", None)
servers["hephaestus-network"] = {
    "type": "local",
    **entry,
    "tools": ["*"],
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
  log "Registered canonical local hephaestus-network MCP in $cfg (Copilot CLI reads the project AGENTS.md natively)."
  ok=$((ok + 1))
}

# Warp's agent reads the project AGENTS.md natively; the adapter installs only
# the hep-network workflow. Warp manages MCP servers in-app (see warp/README.md).
install_warp() {
  if [[ ! -d "$HOME/.warp" && ! -d "/Applications/Warp.app" ]]; then
    warn "Warp not detected; skipped Warp workflow install."
    return 0
  fi
  log "== Warp workflow =="
  ensure_downloaded_source || return 1
  mkdir -p "$HOME/.warp/workflows"
  local name
  for name in hep-network.yaml; do
    rm -f "$HOME/.warp/workflows/$name"
    cp "$source_dir/warp/workflows/$name" "$HOME/.warp/workflows/$name" || return 1
  done
  log "Installed Warp workflow: hep-network (Warp reads the project AGENTS.md natively)."
  ok=$((ok + 1))
}

# Amazon Q Developer CLI reads the project AGENTS.md natively; its only global
# surface is ~/.aws/amazonq/mcp.json. Its `q` command name collides with other
# tools, so detection uses the config directory only.
install_amazonq() {
  if [[ ! -d "$HOME/.aws/amazonq" ]]; then
    warn "Amazon Q Developer CLI not detected; skipped Amazon Q MCP registration."
    return 0
  fi
  log "== Amazon Q MCP =="
  local cfg="$HOME/.aws/amazonq/mcp.json"
  local py=""
  py="$(resolve_python_cmd || true)"
  [[ -n "$py" ]] || { warn "python3 not found; add local hephaestus-network to $cfg manually."; return 1; }
  mkdir -p "$(dirname "$cfg")"
  AGENTLAS_LOCAL_MCP_ENTRY="$(runtime_mcp_launch_render json)" \
    "$py" - "$cfg" <<'PY' || return 1
import json, os, sys
path = sys.argv[1]
entry = json.loads(os.environ["AGENTLAS_LOCAL_MCP_ENTRY"])
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError as exc:
    raise SystemExit(f"refusing to overwrite invalid Amazon Q MCP config {path}: {exc}")
servers = data.setdefault("mcpServers", {})
servers.pop("agentlas", None)
servers["hephaestus-network"] = dict(entry)
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
  log "Registered canonical local hephaestus-network MCP in $cfg (Amazon Q reads the project AGENTS.md natively)."
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
  if ! init_output="$(PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONPATH="$(installer_pythonpath "$source_dir")" $py -m agentlas_cloud network init 2>&1)"; then
    warn "Hephaestus Network init failed. Error was:"
    printf '%s\n' "$init_output" | tail -5 >&2
    warn "Retry manually: PYTHONPATH=<hephaestus-source> $py -m agentlas_cloud network init"
    return 1
  fi
  PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONPATH="$(installer_pythonpath "$source_dir")" $py -m agentlas_cloud network reindex >/dev/null 2>&1 || true
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
	  install_goose || { warn "goose install failed."; failed=$((failed + 1)); }
	  install_amp || { warn "Amp install failed."; failed=$((failed + 1)); }
	  install_copilot_cli || { warn "Copilot CLI install failed."; failed=$((failed + 1)); }
	  install_warp || { warn "Warp install failed."; failed=$((failed + 1)); }
	  install_amazonq || { warn "Amazon Q install failed."; failed=$((failed + 1)); }
	  bootstrap_networking || warn "Hephaestus Network init failed; run 'hephaestus network init' manually."
	  if [[ "${HEPHAESTUS_INSTALL_GLOBAL_ROUTER:-0}" == "1" ]]; then
	    "$HOME/.agentlas/runtime/current/bin/hephaestus" global install || warn "Global router prompt install failed; run 'hep-global install' manually."
	  fi
	  "$HOME/.agentlas/runtime/current/bin/hephaestus" hep-update --remove-service >/dev/null 2>&1 \
	    || warn "Legacy periodic update service cleanup was deferred; the next /hep-* command will retry it."
	  prune_legacy_public_surfaces

  log ""
  log "Installed/updated runtimes: $ok"
  log "Failed runtimes: $failed"
  log ""
  log "Public chat surface: core external commands are installed or refreshed; Claude/Codex also get the Telegram connect helper; Agentlas native surfaces use plain language."
  log "Local memory recall: Claude/Codex hooks, Antigravity PreInvocation, and OpenCode system injection are dynamic; Grok uses passive cache refresh plus its static AGENTS.md pointer."
  log "Automatic updates: Desktop startup and /hep-* commands launch a verified, rate-limited background update without delaying the current task."
  log "Restart open Claude Code, Codex, Gemini, Antigravity, Cursor, OpenCode, OpenClaw, Hermes, goose, Amp, Copilot CLI, Warp, and Amazon Q apps."
  log "Then use:"
  log "  Agentlas:    describe the task in plain language; native tools choose the path"
	  log "  Claude Code: /reload-plugins, then /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload, /hep-connect"
	  log '  Codex:       $hephaestus-build, $hephaestus-network, $hephaestus-cloud, $hephaestus-storm; use plain language for local/hub/search/browser/call/upload/connect'
	  log "  Gemini CLI:  /extensions list or /commands list, then /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload"
	  log "  Antigravity: reopen the workspace, then /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload"
	  log "  Cursor:      /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload"
	  log "  OpenCode:    /hep-build, /hep-network, /hep-local, /hep-cloud, /hep-hub, /hep-storm, /hep-search, /hep-browser, /hep-call, /hep-upload"
	  log "  OpenClaw:    /skill hephaestus-storm <request> or /skill hephaestus-network <request>"
	  log "  Hermes:      hephaestus-storm/hephaestus-network skills (+ MCP, see hermes/README.md)"
	  log "  goose/Amp/Copilot CLI/Amazon Q: project AGENTS.md is read natively; use the hephaestus-network MCP tools"
	  log "  Warp:        hep-network workflow (project AGENTS.md is read natively)"
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
