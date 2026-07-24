#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 메모리 계약 3표면 싱크 게이트 (Runtime Doctor 싱크와 동형).
#
# 메모리 로직은 세 곳에 산다:
#   1) 데스크탑  : agentlas_desktop/electron/agents/evolution-hep.ts + memory/context.ts
#                  + store/run-events.ts (풀 아키텍처, TS)
#   2) 터미널    : agentlas_terminal/engine/agentlas-memory-import.cjs 등 (공유 스토어)
#   3) hep 플러그인: agentlas_cloud/{memory_contract,evolution_proposals,context_markers,
#                  memory_import,memory_hook}.py (별도·경량, per-slug)
#
# 계약(셋이 같아야 하는 것):
#   - .agentlas/evolution-proposals.json 모양 = agentlas.evolution-proposals.v1
#   - context_source 마커 이름 = {pm_soul, code_map, sitemap, experience, memory}
#   - 멤버 세포 키 규칙 = slug 를 그대로 cell id 로 (키보존)
#
# 방식: hep(Python)의 계약 상수/모양을 parity 테스트로 검증하고, 데스크탑 체크아웃이
#   로컬에 있으면 TS 계약 문자열을 교차대조한다(공개 체크아웃/CI 에선 자동 스킵).
#   메모리 계약을 바꾸면 세 곳 중 하나라도 어긋날 때 exit 1.
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
