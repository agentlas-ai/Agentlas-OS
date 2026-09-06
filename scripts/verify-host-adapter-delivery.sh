#!/usr/bin/env bash
# Host-adapter delivery parity: a host cannot be declared in one place and
# missing in another.
#
# Three independent lists used to describe "which hosts get command/skill
# adapters": scripts/render-host-commands.py's HOSTS, scripts/render-
# host-skills.py's MIRROR_ROOTS, and contracts/runtime-registry.json's
# hostAdapters.dirs (the set scripts/build-runtime-release-asset.sh,
# agentlas_cloud/update.py, and scripts/install-all-runtimes.sh all read for
# what actually ships). Measured 2026-09-06 by building the real release
# archive from a scratch clone: `.zcode/commands` had 31 files rendered and
# kept in sync by render-host-commands.py, `.zcode` was never in
# hostAdapters.dirs, and the release tarball carried zero `.zcode` files —
# `render-host-commands.py --check` was green the entire time because it only
# compares its own output against itself.
#
# This gate fails in both directions:
#   1. a host rendered by render-host-commands.py or render-host-skills.py
#      whose top-level directory is not in hostAdapters.dirs (declared to
#      render, never declared to ship — the `.zcode` case); and
#   2. a host declared in hostAdapters.dirs whose directory does not exist, or
#      is empty, at the committed HEAD (declared to ship, nothing there to
#      ship — the historical amp/warp/amazonq case, where the directories
#      were deleted and only the last of three copies was ever updated).
#
# Direction 1 calls the render scripts' own delivery-check functions directly
# (verify_hosts_are_deliverable / verify_mirror_roots_are_deliverable) instead
# of re-deriving HOSTS/MIRROR_ROOTS here — a fourth copy of the same list is
# the disease this gate exists to cure, not a second cure for it.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

root = Path(".").resolve()


def _load(module_name: str, filename: str):
    # Filenames use hyphens (render-host-commands.py), which are not valid in
    # `import` statements, so load them by path instead of adding a fourth
    # renamed copy of either script.
    spec = importlib.util.spec_from_file_location(module_name, root / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


problems: list[str] = []

# --- direction 1: rendered here, but not declared to ship -------------------
commands_mod = _load("render_host_commands", "render-host-commands.py")
skills_mod = _load("render_host_skills", "render-host-skills.py")

try:
    problems.extend(commands_mod.verify_hosts_are_deliverable())
except (OSError, ValueError) as exc:
    problems.append(f"render-host-commands.py delivery contract unreadable: {exc}")

try:
    problems.extend(skills_mod.verify_mirror_roots_are_deliverable())
except (OSError, ValueError) as exc:
    problems.append(f"render-host-skills.py delivery contract unreadable: {exc}")

# --- direction 2: declared to ship, but nothing there at HEAD ---------------
registry_path = root / "contracts" / "runtime-registry.json"
block = json.loads(registry_path.read_text(encoding="utf-8")).get("hostAdapters")
if not isinstance(block, dict) or not isinstance(block.get("dirs"), list) or not block["dirs"]:
    problems.append(f"{registry_path.relative_to(root)} has no usable hostAdapters.dirs")
    dirs = []
else:
    dirs = [d for d in block["dirs"] if isinstance(d, str)]

for name in dirs:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", name],
        cwd=root, capture_output=True, text=True,
    )
    entries = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not entries:
        problems.append(
            f"{name!r} is declared in hostAdapters.dirs but has no committed files at HEAD "
            "(git ls-tree found nothing) — it would ship as an empty/missing directory"
        )

if problems:
    for problem in problems:
        print(f"  FAIL  {problem}", file=sys.stderr)
    print(f"\nverify-host-adapter-delivery: {len(problems)} problem(s)", file=sys.stderr)
    raise SystemExit(1)

print(f"verify-host-adapter-delivery: {len(dirs)} declared host(s) all have committed adapters, "
      "and every rendered host is declared.")
PY
