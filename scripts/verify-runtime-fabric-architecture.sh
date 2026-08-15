#!/usr/bin/env bash
# Runtime x Model architecture gates for Agentlas-OS
# (PRD-runtime-model-architecture-EXECUTABLE-2026-08-15 §1.2, rows OS-1..OS-10).
#
# Every row prints PASS/FAIL; the script exits 1 if any row failed. Rows are
# independent — one failure does not hide the others.
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

failed=0
pass() { printf 'PASS  %-6s %s\n' "$1" "$2"; }
fail() { printf 'FAIL  %-6s %s\n' "$1" "$2"; failed=1; }
skip() { printf 'SKIP  %-6s %s — reason: %s\n' "$1" "$2" "$3"; }
# tests/ is local-only in this repository (public release policy: tests and
# fixtures are never published). A gate whose test file is absent is reported
# as SKIP with that reason — never as PASS.
run_gate() {  # $1=id $2=label $3...=command
  local id="$1" label="$2"; shift 2
  local arg
  for arg in "$@"; do
    case "$arg" in
      tests/*) [ -e "$arg" ] || { skip "$id" "$label" "$arg absent (tests/ are local-only, not in the public checkout)"; return 0; } ;;
    esac
  done
  local out
  if out="$("$@" 2>&1)"; then pass "$id" "$label"; else fail "$id" "$label"; printf '%s\n' "$out" | tail -25 | sed 's/^/        /'; fi
}

PY="${AGENTLAS_PYTHON:-python3}"

# OS-1: sync-adapters enforces the builder canon + interview contract mirrors.
os1() {
  bash scripts/sync-adapters.sh --check || return 1
  grep -q '"contracts/builder-interview-research-gate.md"' scripts/sync-adapters.sh || return 1
  grep -q '"agents/10-single-agent-builder/agent.md"' scripts/sync-adapters.sh || return 1
  grep -q '"contracts/runtime-registry.json"' scripts/sync-adapters.sh || return 1
  # Mutation: a one-byte drift in a mirror must be detected, then restored.
  local target="claude/plugins/agentlas-core-engine-meta-agent/agents/10-single-agent-builder/agent.md"
  local backup; backup="$(mktemp)"; cp "$target" "$backup"
  printf '\nDRIFT\n' >> "$target"
  local rc=0
  bash scripts/sync-adapters.sh --check >/dev/null 2>&1 && rc=1
  cp "$backup" "$target"; rm -f "$backup"
  [ "$rc" -eq 0 ] || { echo "mirror mutation was NOT detected"; return 1; }
  bash scripts/sync-adapters.sh --check
}
run_gate OS-1 "sync-adapters enforces contracts + agents mirrors (mutation detected)" os1

# OS-2: agentlas-one uninstall (isolated HOME, via pytest).
run_gate OS-2 "agentlas-one uninstall [--purge] restores and is idempotent" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_agentlas_one_uninstall.py

# OS-3: stdlib ACP v1 client against a real fake agent subprocess.
run_gate OS-3 "stdlib ACP client: init/auth/session-new/prompt/permission/timeout/version" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_acp_client.py

# OS-4: session_inventory channel separation + identity scrub.
run_gate OS-4 "session_inventory provider/model/family/access_path; features identity-free" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_session_inventory_channel.py tests/test_runtime_capability_descriptor.py

# OS-5: runtime registry + status matrix.
os5() {
  "$PY" agentlas_cloud/runtime_registry.py validate || return 1
  bash bin/agentlas-one status --runtimes >/dev/null || return 1
  "$PY" -m pytest -q -p no:cacheprovider tests/test_runtime_registry.py -k "registry or status"
}
run_gate OS-5 "runtime registry validates; agentlas-one status --runtimes renders" os5

# OS-6: workforce circuit breaker regression (turn-scoped, transient only).
run_gate OS-6 "workforce session circuit breaker (existing contract tests)" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_workforce_network_cloud_contracts.py -k circuit

# OS-7: capture-time redaction of subagent observation.
run_gate OS-7 "subagent observer capture-time redaction" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_subagent_observer.py

# OS-8: Agent Plugins 1.0 manifest.
run_gate OS-8 "Agent Plugins 1.0 plugin.json + mcp.json + skills/" bash scripts/verify-agent-plugins-manifest.sh

# OS-9: installer feature detection replaces version sniffing.
run_gate OS-9 "installer: codex skills feature-detected (version only as fallback)" bash tests/test_installer_feature_detection.sh

# OS-10: drift detector exit codes on fixtures.
run_gate OS-10 "drift detector: clean->0, version/health/capability drift->1" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_runtime_registry.py -k drift

# B-2 (Phase B): One reads entrypoints/hook files from the registry; installer/registry parity; drift surface.
run_gate B-2a "One reads the runtime registry (entrypoints, hook files) + installer/registry parity" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_installer_registry_parity.py
run_gate B-2b "runtime drift surfaces in agentlas-one status / statusline (no daemon; daily hook kick, opt-out)" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_agentlas_one_drift.py

# P-2 (OS part): installer default --ref tracks the manifest version.
run_gate P-2 "verify-install-docs (installer HEPHAESTUS_REF == manifest version)" bash scripts/verify-install-docs.sh

if [ "$failed" -ne 0 ]; then
  echo "verify-runtime-fabric-architecture: FAILED"
  exit 1
fi
echo "verify-runtime-fabric-architecture: all gates passed"
