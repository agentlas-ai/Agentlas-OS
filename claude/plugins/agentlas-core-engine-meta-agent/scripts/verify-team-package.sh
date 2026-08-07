#!/usr/bin/env bash
# Verify that a generated Agentlas package is exactly one valid shape:
# single-agent or orchestrated team. This gate checks generated package roots,
# not this meta-agent repository.
#
# The rule itself lives in agentlas_cloud/team_shape.py, NOT here. Both this
# shell gate and `hephaestus contract verify --mode team` are mandatory in the
# same documented flow (AGENTS.md, modes/team-builder.md), and while the rule
# lived inline in this script the contract gate could not see a team at all: it
# passed a zero-worker "team" this gate rejects, so a fill/repair loop that
# trusts the contract only discovered the degenerate shape here. This script is
# the shell entry point, never a second source.
#
# Usage:
#   scripts/verify-team-package.sh [folder]   # default: .
#
# Exit codes: 0 = valid single/team shape, 1 = malformed or degenerate shape.
set -euo pipefail

engine_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${1:-.}"

if [[ ! -d "$target" ]]; then
  echo "verify-team-package: FAIL - target is not a directory: $target" >&2
  exit 1
fi

AGENTLAS_ENGINE_ROOT="$engine_root" python3 - "$target" <<'PY'
import os
import sys

# Resolve the rule from THIS engine checkout, ahead of the cwd python prepends
# for a stdin script — the gate is normally pointed at a package directory, and
# it must never load some other agentlas_cloud that happens to sit there.
sys.path.insert(0, os.environ["AGENTLAS_ENGINE_ROOT"])

from agentlas_cloud.team_shape import check_team_shape

result = check_team_shape(sys.argv[1])
root = result["root"]
notes = result["notes"]

if not result["ok"]:
    print(f"verify-team-package: FAIL {root}")
    print(
        f"workers={result['workers']}; orchestrators={result['orchestrators']}; "
        f"topology={result['topology'] or 'missing'}"
    )
    for message in result["errors"]:
        print(f"- {message}")
    raise SystemExit(1)

print(f"verify-team-package: {notes[0] if notes else 'PASS'}")
print(f"root={root}")
print(
    f"workers={result['workers']}; orchestrators={result['orchestrators']}; "
    f"topology={result['topology']}"
)
PY
