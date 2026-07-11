#!/usr/bin/env bash
# Agent Ontology CI gate (plan §12): fail the build on an invalid graph,
# topology drift, or a failing test suite. Non-zero exit blocks CI / commit.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
PY="${HEPHAESTUS_PYTHON:-python3}"

echo "[ao-gate] 1/4 ensure canonical project graph is materialized"
if [[ ! -f "$root/.agentlas/agent-ontology/grammar.json" ]]; then
  PYTHONPATH="$root" "$PY" -m agentlas_cloud ao migrate "$root" --overwrite >/dev/null
  echo "[ao-gate]   graph materialized for clean checkout"
else
  echo "[ao-gate]   existing graph preserved for drift detection"
fi

echo "[ao-gate] 2/4 ao lint (grammar + deny/require axioms)"
PYTHONPATH="$root" "$PY" -m agentlas_cloud ao lint >/dev/null
echo "[ao-gate]   lint OK"

echo "[ao-gate] 3/4 ao diff (AO vs generated view — drift = fail)"
PYTHONPATH="$root" "$PY" -m agentlas_cloud ao diff >/dev/null
echo "[ao-gate]   no drift"

echo "[ao-gate] 4/4 pytest"
PYTHONPATH="$root" "$PY" -m pytest -q
echo "[ao-gate] PASS"
