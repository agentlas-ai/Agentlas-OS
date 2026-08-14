#!/usr/bin/env bash
# Runtime-home parity between the two independent install paths.
#
# A runtime home is written by TWO programs that share no code:
#   scripts/install-all-runtimes.sh   (first install)
#   agentlas_cloud/update.py          (every auto-update after that)
# Whatever the first one copies, the second must copy too — a machine that
# installed once and then only ever auto-updated gets the updater's set forever.
#
# This has now cost the same defect twice. `system-agents/curator-ruleset.json`
# was added to the installer and not the updater, so the curator silently fell
# back to its embedded defaults and stamped sha="embedded" on every decision
# receipt; the goose/openclaw hook packs had the identical gap, and
# `agentlas-one on` reported success having installed no hooks for those hosts.
# Neither raised. Both are the shape a test suite cannot see, because nothing
# fails — the runtime is simply missing a payload nobody asserts.
#
# The gate asserts the CONTRACT (installer payload set is a subset of the
# updater's), not the wording of either file, and refuses to pass when it cannot
# read enough to judge.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[[ -n "$PY" ]] || { echo "verify-runtime-home-parity: no python3/python on PATH" >&2; exit 1; }

"$PY" - "$root" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
installer = root / "scripts" / "install-all-runtimes.sh"
updater = root / "agentlas_cloud" / "update.py"
release = root / "scripts" / "build-runtime-release-asset.sh"

problems = []


def die(message):
    print(f"verify-runtime-home-parity: {message}", file=sys.stderr)
    raise SystemExit(1)


# --- what the installer copies into the runtime home -------------------------
text = installer.read_text(encoding="utf-8")
start = text.find("install_runtime_home() {")
if start < 0:
    die(f"could not find install_runtime_home() in {installer}")
body = text[start:]
end = body.find("\n}\n")
if end < 0:
    die("install_runtime_home() has no closing brace")
body = body[:end]

# Join backslash continuations so a multi-line `cp` is one statement: the
# destination lives on the last line and the sources on the ones before it.
joined = re.sub(r"\\\n\s*", " ", body)

loop_words = {}
for var, words in re.findall(r"for\s+(\w+)\s+in\s+([^;\n]+);\s*do", joined):
    if "${" in words or '"' in words:
        continue  # array expansion (host adapters) — not a literal payload list
    loop_words[var] = words.split()

installer_payload = set()
for line in joined.splitlines():
    if "$source_dir/" not in line:
        continue
    if not re.search(r"\b(cp|copy_tree_without_python_cache)\b", line):
        continue
    for token in re.findall(r"\$source_dir/(\$?[A-Za-z0-9_.\-]+)", line):
        if token.startswith("$"):
            expanded = loop_words.get(token[1:])
            if expanded is None:
                continue
            filtered = [x for x in expanded if x not in ('manifest.json', 'scripts')]
            installer_payload.update(filtered)
        else:
            if token not in ('manifest.json', 'scripts'):
                installer_payload.add(token)

# Floor: the copy stanza has never been smaller than this. A parse that silently
# degrades to a handful of names would make the whole gate pass on nothing.
if len(installer_payload) < 8:
    die(
        "parsed only "
        f"{len(installer_payload)} runtime-home payload(s) from the installer "
        f"({sorted(installer_payload)}) — the copy stanza changed shape and this "
        "gate can no longer read it. Fix the gate; do not delete it."
    )

# --- what the updater copies -------------------------------------------------
updater_text = updater.read_text(encoding="utf-8")


def tuple_names(name):
    match = re.search(rf"^{name} = \(([^)]*)\)", updater_text, re.MULTILINE)
    if not match:
        die(f"could not find {name} in {updater}")
    return set(re.findall(r'"([^"]+)"', match.group(1)))


updater_payload = tuple_names("RUNTIME_DIRS") | tuple_names("RUNTIME_OPTIONAL_DIRS") | tuple_names("RUNTIME_FILES")

for name in sorted(installer_payload - updater_payload):
    problems.append(
        f"{name!r} is copied into the runtime home by the installer but by neither "
        "RUNTIME_DIRS, RUNTIME_OPTIONAL_DIRS nor RUNTIME_FILES in agentlas_cloud/"
        "update.py — an auto-updated machine loses it"
    )

# --- and the release archive must actually ship it ---------------------------
# An optional copy of a path the archive never contains is a no-op, so the two
# halves of the fix have to be checked together (a release asset entry without an
# install copy, and an install copy without a release asset entry, are both real
# defects this product has shipped).
release_text = release.read_text(encoding="utf-8")
match = re.search(r"^runtime_paths=\(([^)]*)\)", release_text, re.MULTILINE)
if not match:
    die(f"could not find runtime_paths=( ... ) in {release}")
release_paths = set(re.findall(r'"([^"]+)"', match.group(1)))
release_tops = {path.split("/", 1)[0] for path in release_paths}

for name in sorted(installer_payload):
    if name.split("/", 1)[0] not in release_tops:
        problems.append(
            f"{name!r} reaches the runtime home on a source install but is not in "
            "runtime_paths in scripts/build-runtime-release-asset.sh, so the "
            "released archive does not carry it and the updater cannot copy it"
        )

print(f"  installer runtime-home payload: {', '.join(sorted(installer_payload))}")
for problem in problems:
    print(f"verify-runtime-home-parity: {problem}", file=sys.stderr)
if problems:
    raise SystemExit(1)
print("verify-runtime-home-parity: installer and updater write the same runtime home.")
PY
