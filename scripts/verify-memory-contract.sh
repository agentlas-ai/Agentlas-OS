#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# Memory contract three-surface sync gate (isomorphic to the Runtime Doctor sync).
#
# Memory logic lives in three places:
#   1) Desktop:   agentlas_desktop/electron/agents/evolution-hep.ts + memory/context.ts
#                 + store/run-events.ts (full architecture, TS)
#   2) Terminal:  agentlas_terminal/engine/agentlas-memory-import.cjs and others (shared store)
#   3) hep plugin: agentlas_cloud/{memory_contract,evolution_proposals,context_markers,
#                 memory_import,memory_hook}.py (separate, lightweight, per-slug)
#
# Contract (what must match across all three):
#   - .agentlas/evolution-proposals.json shape = agentlas.evolution-proposals.v1
#   - context_source marker names = {pm_soul, code_map, sitemap, experience, memory}
#   - member cell key rule = the slug itself as the cell id (key preserved)
#
# Method: verifies hep's (Python) contract constants/shapes via a parity test,
#   and cross-checks TS contract strings if a Desktop checkout is present
#   locally (auto-skipped on a public checkout/CI). exit 1 if the memory
#   contract changes and any of the three surfaces disagrees.
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${HEPHAESTUS_PYTHON:-python3}"
GATE_TEST="tests/test_memory_hook_parity.py"

# The parity test lives under the gitignored tests/ tree (never shipped in the
# public allowlist), so a public checkout won't have it — skip like the Runtime
# Doctor gate does when its fixtures are absent (development-machine-only gate).
if [ ! -f "$GATE_TEST" ]; then
  echo "[verify-memory-contract] $GATE_TEST not found — skipped (development-machine-only gate)"
  exit 0
fi

echo "[verify-memory-contract] running hep-plugin parity gate ..."
# stdlib unittest — no third-party test dependency required for the gate.
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PY" "$GATE_TEST"

echo "[verify-memory-contract] PASS"
