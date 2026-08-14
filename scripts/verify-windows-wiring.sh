#!/usr/bin/env bash
# Windows/Linux wiring contract.
#
# Everything this gate checks was true and shipping for months while a native
# Windows install looked successful: the local Core MCP server could not start on
# ANY host (every registration hardcoded an extensionless bash runner, and
# Windows spawns stdio servers without a shell), PYTHONPATH was joined with ':'
# so `agentlas_cloud` was unimportable, the plugin hooks embedded a backslash
# path that Git Bash ate as escape sequences, and `agentlas-one` was never put on
# PATH at all. Nothing failed loudly — the surfaces were simply absent, and the
# host silently fell back to the remote Hub with no menu projection.
#
# These are STATIC assertions about the wiring. The behavioural half runs on a
# real windows-latest runner in CI (.github/workflows/cross-platform-wiring.yml).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

failures=0
fail() {
  echo "verify-windows-wiring: $*" >&2
  failures=$((failures + 1))
}

installer="scripts/install-all-runtimes.sh"
boundary="bin/agentlas-python-cache-boundary"

# 1. The platform question is answered in exactly one place.
for helper in agentlas_is_windows agentlas_path_sep agentlas_native_path agentlas_mcp_launch; do
  grep -q "^${helper}()" "$boundary" || fail "$boundary is missing $helper()"
done
grep -q "agentlas_load_platform_helpers" "$installer" \
  || fail "$installer does not load the canonical platform helpers"
# A second copy of the platform rule is how the original bug survived.
grep -q "^agentlas_is_windows()" "$installer" \
  && fail "$installer re-implements agentlas_is_windows; source the canonical helper instead"

# 2. Launcher PYTHONPATH and interpreter selection — asserted on BEHAVIOUR.
#
#    An earlier version of this gate grepped for the buggy `${PYTHONPATH:+:...}`
#    literal and for the string `bin/python3`. Both were decorative: the regex
#    used `\+`, which is the BRE one-or-more quantifier rather than a literal
#    plus, so it matched nothing ever; and a mere mention of `bin/python3`
#    anywhere in a file says nothing about the order it is tried in. Ask the
#    scripts what they DO instead.
python3 - <<'PY' || failures=$((failures + 1))
import re
import sys
from pathlib import Path

LAUNCHERS = [
    "bin/hephaestus",
    "bin/ontology",
    "bin/career-graph",
    "bin/agentlas-memory-hook",
    "bin/agentlas-one",
]
problems = []
for name in LAUNCHERS:
    path = Path(name)
    if not path.is_file():
        problems.append(f"missing launcher: {name}")
        continue
    raw = path.read_text(encoding="utf-8")
    # Judge CODE, not prose. These files explain the very bug being checked for,
    # so a comment mentioning `python3` would otherwise read as a violation.
    text = "\n".join(
        "" if line.lstrip().startswith("#") else re.sub(r"\s#.*$", "", line)
        for line in raw.splitlines()
    )

    # A colon-joined PYTHONPATH is one unusable entry on Windows. Match the shape
    # semantically: any PYTHONPATH assignment that appends with a literal ':'.
    for match in re.finditer(r'PYTHONPATH="[^"\n]*"', text):
        value = match.group(0)
        if ":$PYTHONPATH" in value or ":${PYTHONPATH" in value:
            problems.append(f"{name}: colon-joined PYTHONPATH: {value}")

    # The runtime's own verified shim must be tried BEFORE bare python3/python.
    shim = text.find("$root/bin/python3")
    if shim < 0:
        shim = text.find("_one_root/bin/python3")
    if shim < 0:
        problems.append(f"{name}: never tries the runtime python3 shim")
        continue
    bare = re.search(r'(?<![/\w])python3(?![.\w])', text)
    if bare and bare.start() < shim:
        line = text[:bare.start()].count("\n") + 1
        problems.append(
            f"{name}:{line}: bare `python3` is tried before the runtime shim at "
            f"line {text[:shim].count(chr(10)) + 1}"
        )

for problem in problems:
    print(f"verify-windows-wiring: {problem}", file=sys.stderr)
raise SystemExit(1 if problems else 0)
PY

for launcher in bin/hephaestus bin/ontology bin/career-graph bin/agentlas-memory-hook; do
  grep -q "agentlas_native_path" "$launcher" \
    || fail "$launcher does not convert the runtime root for a native interpreter"
done

# 3. Every host MCP registration renders from the one launch vector — counted by
#    CALL SITE, not by how many times the helper's name appears in the file. The
#    previous `grep -c >= 8` was satisfied by a comment mentioning the name while
#    a real registration hand-rolled its own JSON.
render_sites="$(grep -cE '^[^#]*runtime_mcp_launch_render (json|toml|yaml)' "$installer" || true)"
[[ "$render_sites" -ge 8 ]] \
  || fail "only $render_sites host registration(s) render from runtime_mcp_launch_render; expected >= 8 (codex, claude/gemini, goose, cursor, opencode, amp, copilot, amazonq)"
# Any MCP registration must take its command from the rendered entry. Catch the
# bare runner path reaching a config writer under ANY variable name.
bare_runner="$(grep -nE '^[^#]*(AGENTLAS_LOCAL_MCP|[A-Za-z_]+)="\$HOME/\.agentlas/runtime/current/bin/hephaestus"' "$installer" || true)"
if [[ -n "$bare_runner" ]]; then
  echo "$bare_runner" >&2
  fail "a bare runner path is assigned above; pass the rendered launch entry instead"
fi
grep -q "^register_claude_mcp()" "$installer" \
  || fail "$installer is missing register_claude_mcp (Windows user-scope MCP)"
grep -q "register_claude_mcp || warn" "$installer" \
  || fail "register_claude_mcp is defined but never called from install_claude"

# 4. Windows command shims exist for every shell command, not just hephaestus.
grep -q "^write_windows_command_shims()" "$installer"   || fail "$installer is missing write_windows_command_shims"
grep -q "write_windows_command_shims" "$installer"   || fail "write_windows_command_shims is never called for the runtime bin"
grep -q "agentlas-one$" <(grep -A2 "local -a shell_commands=(" "$installer")   || fail "agentlas-one is missing from shell_commands; it would never reach PATH"

# 5. Hook commands must not embed the raw plugin root as a path, and must stay
#    POSIX. Asserted on the DECODED command strings: reasoning about backslashes
#    through JSON escaping plus shell quoting is how this class of bug hides.
python3 - <<'PY' || failures=$((failures + 1))
import json
import sys
from pathlib import Path

problems = []
for path in (Path("hooks/claude/hooks.json"), Path("hooks/codex/hooks.json")):
    if not path.is_file():
        problems.append(f"missing {path}")
        continue
    payload = json.loads(path.read_text(encoding="utf-8"))
    for event, groups in (payload.get("hooks") or {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                command = str(hook.get("command", ""))
                if "PLUGIN_ROOT" not in command:
                    continue
                where = f"{path}:{event}"
                # On Windows the host expands the plugin root to C:\... and Git
                # Bash reads \U, \p, \s as escape sequences
                # (anthropics/claude-code#21878).
                for raw in ("${CLAUDE_PLUGIN_ROOT}/", "${CODEX_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-}}/"):
                    if raw in command:
                        problems.append(f"{where}: uses the plugin root directly as a path ({raw}...)")
                if "tr '\\\\' '/'" not in command:
                    problems.append(f"{where}: does not normalize backslashes with tr")
                # ${var//x/y} is a bashism; /bin/sh is dash on Debian and Ubuntu,
                # and the docs say hook commands go to `sh -c` there.
                if "//\\\\//" in command:
                    problems.append(f"{where}: uses bash ${{var//x/y}}; dash cannot parse it")

for problem in problems:
    print(f"verify-windows-wiring: {problem}", file=sys.stderr)
raise SystemExit(1 if problems else 0)
PY

# 5b. Both install paths must produce the SAME runtime layout. The updater built
#     host_adapters/ and this script did not, so the commands that locate the
#     engine (.claude/commands/hep-build.md, agentlas.md probe
#     runtime/current/host_adapters/{claude,codex}/plugins/...) reported "run the
#     installer first" on a machine that had just run the installer.
python3 - <<'PY' || failures=$((failures + 1))
import re
import sys
from pathlib import Path

problems = []
installer = Path("scripts/install-all-runtimes.sh").read_text(encoding="utf-8")
updater = Path("agentlas_cloud/update.py").read_text(encoding="utf-8")

if 'HOST_ADAPTER_BUNDLE_DIR="host_adapters"' not in installer:
    problems.append("scripts/install-all-runtimes.sh does not declare HOST_ADAPTER_BUNDLE_DIR")
if "host_adapter_dirs=(" not in installer:
    problems.append("scripts/install-all-runtimes.sh does not build the host-adapter bundle")

def bash_set(text):
    match = re.search(r"host_adapter_dirs=\(\n(.*?)\n\)", text, re.S)
    if not match:
        return set()
    return set(re.findall(r'[.\w-]+', match.group(1).replace('"', " ")))

def python_set(text):
    match = re.search(r"HOST_ADAPTER_DIRS = \(\n(.*?)\n\)", text, re.S)
    if not match:
        return set()
    return set(re.findall(r'"([^"]+)"', match.group(1)))

installer_set, updater_set = bash_set(installer), python_set(updater)
if not updater_set:
    problems.append("agentlas_cloud/update.py no longer declares HOST_ADAPTER_DIRS")
elif installer_set != updater_set:
    only_installer = sorted(installer_set - updater_set)
    only_updater = sorted(updater_set - installer_set)
    problems.append(
        "host-adapter bundle sets disagree between the two install paths; "
        f"installer-only={only_installer} updater-only={only_updater}"
    )

for problem in problems:
    print(f"verify-windows-wiring: {problem}", file=sys.stderr)
raise SystemExit(1 if problems else 0)
PY

# 6. Host registries must not be pinned to one release directory.
grep -q "_stable_adapter_source" agentlas_cloud/host_update.py \
  || fail "agentlas_cloud/host_update.py does not stabilise the adapter source path"
grep -q "def _source_bound" agentlas_cloud/host_update.py \
  || fail "agentlas_cloud/host_update.py is missing the dual-form source_bound check"

if [[ "$failures" -gt 0 ]]; then
  echo "verify-windows-wiring: $failures failure(s)." >&2
  exit 1
fi
echo "Windows/Linux wiring contract verification passed."
