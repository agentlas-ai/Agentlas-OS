#!/usr/bin/env bash
# Post-install wiring assertions. Run AFTER scripts/install-all-runtimes.sh, on
# the platform that just installed.
#
# scripts/verify-windows-wiring.sh reads the source and asks "is the wiring
# written correctly". This script asks the only question that actually matters:
# after an install that reported success, do the surfaces EXIST and RUN here?
# Every defect this was written for answered "no" on native Windows while the
# installer's own output said everything was fine.
#
# Same script on every platform; the few OS-specific expectations are branched
# explicitly below.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$root/bin/agentlas-python-cache-boundary"

runtime="$HOME/.agentlas/runtime/current"
user_bin="$HOME/.local/bin"
failures=0

# `python3` is not a universal name. Native Windows ships `python.exe` only, and
# actions/setup-python does not guarantee a `python3` alias there, so a step that
# hardcodes `python3` fails for a reason that has nothing to do with the wiring
# it claims to test — a green-looking gate reporting a red platform.
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[[ -n "$PY" ]] || { echo "verify-installed-wiring: no python3/python on PATH" >&2; exit 1; }

fail() {
  echo "verify-installed-wiring: $*" >&2
  failures=$((failures + 1))
}
ok() { echo "  ok  $*"; }

# --workforce-skills-root <dir>: scoped mode. Verify ONLY that the staged
# workforce skills never teach the model to echo the projected candidateSet /
# federationResult back into validate_selection — the session-based protocol
# passes selectionSessionId and Core restores the pinned federation result
# itself; a skill that shows `candidateSet=` / `federationResult=` arguments
# reintroduces the projected-echo defect on every machine it installs to.
# Scoped on purpose: the caller is checking a staging directory before install,
# so this machine's own wiring state must not decide the verdict.
if [[ "${1:-}" == "--workforce-skills-root" ]]; then
  skills_root="${2:-}"
  [[ -n "$skills_root" && -d "$skills_root" ]] || {
    echo "verify-installed-wiring: --workforce-skills-root requires an existing directory" >&2
    exit 1
  }
  for scope in network cloud; do
    skill_file="$skills_root/hephaestus-$scope/SKILL.md"
    [[ -f "$skill_file" ]] || { fail "staged workforce skill missing: $skill_file"; continue; }
    if grep -nE '\b(candidateSet|federationResult)[[:space:]]*=' "$skill_file" >/dev/null; then
      fail "staged skill hephaestus-$scope would echo projected candidateSet/federationResult into validate_selection: $skill_file"
    else
      ok "staged skill hephaestus-$scope passes session-based identifiers only"
    fi
  done
  if [[ "$failures" -gt 0 ]]; then
    echo "verify-installed-wiring: $failures failure(s)." >&2
    exit 1
  fi
  echo "verify-installed-wiring: staged workforce skills verified."
  exit 0
fi

is_windows=0
if agentlas_is_windows; then
  is_windows=1
fi
echo "verify-installed-wiring: platform=$(uname -s) windows=$is_windows"

# 1. The runtime is installed and knows its own version.
[[ -d "$runtime" ]] || fail "runtime not installed at $runtime"
if [[ -f "$runtime/RELEASE" ]]; then
  ok "RELEASE marker: $(tr -d '\r\n' < "$runtime/RELEASE")"
else
  # The version marker is RELEASE — not package.json, not VERSION. A probe that
  # looks for the wrong file reports a healthy install as unverifiable.
  fail "missing $runtime/RELEASE"
fi

# 2. The runner runs. This is the PYTHONPATH proof: if the root reached the
#    interpreter in the wrong form or with the wrong separator, this exits
#    non-zero with ModuleNotFoundError: No module named 'agentlas_cloud'.
version_output="$("$runtime/bin/hephaestus" --version 2>&1)"; version_rc=$?
if [[ "$version_rc" -eq 0 && -n "$version_output" ]]; then
  ok "hephaestus --version: $(printf '%s' "$version_output" | head -1)"
else
  fail "hephaestus --version failed: $(printf '%s' "$version_output" | head -3)"
fi
case "$version_output" in
  *ModuleNotFoundError*) fail "agentlas_cloud is not importable through the launcher" ;;
esac

# 3. agentlas-one is a command, not just a file in the tarball.
for candidate in "$runtime/bin/agentlas-one" "$user_bin/agentlas-one"; do
  [[ -f "$candidate" ]] || fail "missing $candidate"
done
one_output="$("$runtime/bin/agentlas-one" status 2>&1)"; one_rc=$?
if [[ "$one_rc" -eq 0 ]]; then
  ok "agentlas-one status: $(printf '%s' "$one_output" | head -1)"
else
  fail "agentlas-one status failed: $(printf '%s' "$one_output" | head -3)"
fi

# `status` reads a JSON file in shell and never launches the interpreter, so it
# cannot see an interpreter-selection regression — the exact failure this gate
# exists for. `memory` runs the workspace module, so a wrong Python surfaces
# here as a SyntaxError or a "not found" instead of passing silently. It is
# read-only: it measures, it does not enable or seed anything.
memory_output="$("$runtime/bin/agentlas-one" memory 2>&1)"; memory_rc=$?
if [[ "$memory_rc" -eq 0 ]]; then
  ok "agentlas-one memory (exercises the interpreter): $(printf '%s' "$memory_output" | head -1)"
else
  fail "agentlas-one memory failed — the One workspace module did not run: $(printf '%s' "$memory_output" | head -5)"
fi
case "$memory_output" in
  *SyntaxError*)          fail "the selected interpreter cannot parse the One workspace module" ;;
  *"command not found"*)  fail "agentlas-one resolved no usable interpreter" ;;
  *"verification failed"*) fail "One workspace verification failed; the interpreter or workspace seeding is broken" ;;
esac

# 4. Windows-only surfaces. cmd.exe cannot run a bash script or an
#    extensionless file, so without these the commands do not exist outside Git
#    Bash — and the plugin's MCP server cannot be spawned at all.
if [[ "$is_windows" == "1" ]]; then
  for shim in "$runtime/bin/hephaestus.cmd" "$runtime/bin/agentlas-one.cmd" \
              "$user_bin/agentlas-one.cmd" "$user_bin/hep-network.cmd"; do
    [[ -f "$shim" ]] && ok "shim $shim" || fail "missing Windows shim: $shim"
  done
else
  ok "non-Windows: .cmd shims intentionally absent"
fi

# 5. Any host MCP registration this install wrote must carry a launch vector the
#    host can actually spawn.
"$PY" - "$is_windows" "${VERIFY_WIRING_REQUIRE_MCP:-0}" <<'PY' || failures=$((failures + 1))
import json
import os
import sys
from pathlib import Path

is_windows = sys.argv[1] == "1"
require_mcp = sys.argv[2] == "1"
home = Path(os.path.expanduser("~"))
targets = {
    "cursor": (home / ".cursor/mcp.json", ("mcpServers",)),
    "opencode": (home / ".config/opencode/opencode.json", ("mcp",)),
    "antigravity": (home / ".gemini/config/mcp_config.json", ("mcpServers",)),
    "copilot": (home / ".copilot/mcp-config.json", ("mcpServers",)),
}
problems, checked, present = [], 0, 0
for label, (path, keys) in targets.items():
    if not path.is_file():
        continue
    present += 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        problems.append(f"{label}: unreadable config ({exc})")
        continue
    entry = None
    for key in keys:
        section = payload.get(key)
        if isinstance(section, dict) and isinstance(section.get("hephaestus-network"), dict):
            entry = section["hephaestus-network"]
    if entry is None:
        # Every host here is gated on its config DIRECTORY, so a config file that
        # exists is a host the installer decided to register into. No entry means
        # the registration it reported did not land — previously a silent
        # `continue`, which is how this whole check could pass having inspected
        # nothing at all.
        problems.append(f"{label}: {path} exists but carries no hephaestus-network entry")
        continue
    checked += 1
    # OpenCode takes one argv array; everyone else takes command + args.
    argv = entry["command"] if isinstance(entry.get("command"), list) else [entry.get("command"), *entry.get("args", [])]
    argv = [str(part) for part in argv if part is not None]
    if is_windows:
        if argv[:2] != ["cmd", "/c"]:
            problems.append(f"{label}: {argv[:2]} is not spawnable on native Windows; expected cmd /c")
        elif not argv[2].lower().endswith(".cmd"):
            problems.append(f"{label}: {argv[2]} is not a .cmd; a bash script cannot be spawned without a shell")
    else:
        if argv[0].endswith(".cmd") or argv[0] == "cmd":
            problems.append(f"{label}: Windows launch vector written on {sys.platform}")
    if argv[-2:] != ["mcp", "serve"]:
        problems.append(f"{label}: launch vector does not end in `mcp serve`: {argv}")

# A bare machine with no host CLI legitimately has nothing to check, so 0 is not
# a failure by itself — but it must never READ like a pass. Print the denominator
# and let CI, which seeds host config directories precisely so there is something
# to inspect, demand a floor.
if require_mcp and checked == 0:
    problems.append(
        f"inspected 0 host MCP registrations ({present} config file(s) present) "
        "while VERIFY_WIRING_REQUIRE_MCP=1 — the launch-vector assertions never ran"
    )

for problem in problems:
    print(f"verify-installed-wiring: {problem}", file=sys.stderr)
print(f"  ok  checked {checked} of {present} present host MCP config(s)")
raise SystemExit(1 if problems else 0)
PY

# 6. Managed commands reached the user-global directory. `agentlas-one` is the
#    one that never did: it exists only inside the plugin, so without a global
#    copy it is reachable only as /hephaestus:agentlas-one.
if [[ -d "$HOME/.claude/commands" ]]; then
  for name in agentlas-one.md hep-graph.md hep-network.md; do
    [[ -f "$HOME/.claude/commands/$name" ]] && ok "global command $name" \
      || fail "missing global command: ~/.claude/commands/$name"
  done
else
  ok "no ~/.claude/commands (Claude CLI absent on this machine)"
fi

# 7. Runtime-home payloads that only the INSTALLER used to copy. Every consumer
#    of these degrades instead of raising, so their absence is invisible: the
#    curator silently falls back to the embedded ruleset and stamps
#    sha="embedded" on every decision receipt, and `agentlas-one on` reports
#    success having installed no goose/openclaw hooks at all. Assert resolution,
#    not just file presence — the ruleset path is resolved relative to the
#    agentlas_cloud package, so only an import through this runtime proves it.
#
#    Run from INSIDE $runtime, not from wherever this script was invoked: with
#    `-c`, sys.path[0] is the current directory and it beats PYTHONPATH, so a run
#    started in an Agentlas-OS checkout imports the repo's agentlas_cloud and
#    reads the repo's ruleset. Measured: that spelling reported a healthy
#    sha=4c5dd515 for a runtime whose real answer is "embedded".
ruleset_sha="$(cd "$runtime" 2>/dev/null && PYTHONPATH="$runtime" PYTHONNOUSERSITE=1 "$PY" -c \
  'from agentlas_cloud.one_workspace import load_ruleset; print(load_ruleset()[1])' 2>&1)"
case "$ruleset_sha" in
  embedded)
    fail "curator ruleset resolved to the embedded fallback — $runtime/system-agents/curator-ruleset.json is missing (every decision receipt will read sha=embedded)" ;;
  [0-9a-f]*)
    ok "curator ruleset resolved from the runtime: sha=$ruleset_sha" ;;
  *)
    fail "could not resolve the curator ruleset through $runtime: $(printf '%s' "$ruleset_sha" | tail -1)" ;;
esac

for pack in "goose/plugins/agentlas-one" "openclaw/hooks/agentlas-one"; do
  [[ -d "$runtime/$pack" ]] && ok "hook pack $pack" \
    || fail "missing hook pack: $runtime/$pack (agentlas-one on would install no hooks for this host and still report success)"
done

if [[ "$failures" -gt 0 ]]; then
  echo "verify-installed-wiring: $failures failure(s)." >&2
  exit 1
fi
echo "verify-installed-wiring: installed wiring verified."
