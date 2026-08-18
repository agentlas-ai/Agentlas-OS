#!/usr/bin/env python3
"""오케스트레이터/워커 모델 지정이 실제로 도는지 — 입력부터 영수증까지.

병(2026-08-18 실측): 배정 로직은 멀쩡한데 두 입력이 비어 한 번도 돌지 않았다.
  ① 정책 — AGENTLAS_MODEL_ALLOCATION_POLICY_JSON에 사람이 손으로 JSON을 넣는 길뿐이라
     어떤 머신에도 설정돼 있지 않았다.
  ② 인벤토리 — 호스트는 모델 id만 알려주는데, context_window가 없으면 호환 검사가
     모든 후보를 떨어뜨려 `requested_exact_model_unavailable`로 끝났다.

실행: python3 scripts/test-orch-policy.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentlas_cloud.model_allocation import (  # noqa: E402
    ASSUMED_CONTEXT_WINDOW,
    resolve_model_allocation,
)

passed = 0


def ok(name: str) -> None:
    global passed
    passed += 1
    print(f"  ok {name}")


def decision(tier: str, model: str, effort: str, phase: str) -> dict:
    return {
        "schemaVersion": "agentlas.model-allocation-decision.v1",
        "decisionId": "dec-001",
        "phase": phase,
        "authoredBy": "parent-ai",
        "selectorVersion": "host-llm-1",
        "reasonCodes": ["bounded-scope"],
        "features": {
            "complexity": "simple", "risk": "low", "inputTokens": 8000,
            "expectedOutputTokens": 1000, "toolRequired": False,
            "multimodalRequired": False, "parallelFanout": 1,
        },
        "selection": {
            "tier": tier, "effort": effort, "fallbackTiers": [], "maxEscalations": 0,
            "exactModelId": model, "provider": "anthropic",
        },
    }


# 호스트가 실제로 주는 수준의 인벤토리 — context_window 없음.
HOST_INVENTORY = [
    {"session_id": "s1", "model": "claude-opus-5", "provider": "anthropic",
     "tier": "frontier", "supported_efforts": ["low", "medium", "high"], "active": True},
    {"session_id": "s2", "model": "claude-haiku-4-5", "provider": "anthropic",
     "tier": "economy", "supported_efforts": ["low", "medium"], "active": False},
]

# ── ② 인벤토리 빈칸 보완 ────────────────────────────────────────────────
worker = resolve_model_allocation(
    decision("economy", "claude-haiku-4-5", "low", "execute"),
    HOST_INVENTORY, policy={}, role="worker", expected_phase="execute",
)
assert worker["status"] == "resolved", f"호스트가 주는 인벤토리로 배정이 실패한다: {worker['reasonCodes']}"
assert worker["resolved"]["modelId"] == "claude-haiku-4-5"
ok("context_window 없는 실제 인벤토리로 워커 배정이 된다(회귀 감시)")

assert "inventory_context_window_assumed" in worker["reasonCodes"], \
    "가정한 컨텍스트 창이 영수증에 드러나지 않는다 — 알릴 수 없는 완화는 하지 않는다"
ok("가정한 컨텍스트 창이 영수증에 표시된다")

measured = resolve_model_allocation(
    decision("economy", "claude-haiku-4-5", "low", "execute"),
    [dict(HOST_INVENTORY[1], context_window=200_000, active=True)],
    policy={}, role="worker", expected_phase="execute",
)
assert "inventory_context_window_assumed" not in measured["reasonCodes"], \
    "실측값이 있는데도 가정으로 표시된다"
ok("호스트가 실제 값을 주면 가정 표시가 붙지 않는다")

big = resolve_model_allocation(
    {**decision("economy", "claude-haiku-4-5", "low", "execute"),
     "features": {**decision("economy", "x", "low", "execute")["features"],
                  "inputTokens": ASSUMED_CONTEXT_WINDOW * 2}},
    HOST_INVENTORY, policy={}, role="worker", expected_phase="execute",
)
assert big["status"] != "resolved", "가정 하한을 넘는 작업까지 통과시키면 가정이 거짓말이 된다"
ok("가정 하한을 넘는 작업은 여전히 거절된다")

# ── 오너 목표 시나리오 ──────────────────────────────────────────────────
orch = resolve_model_allocation(
    decision("frontier", "claude-opus-5", "high", "plan"),
    HOST_INVENTORY, policy={}, role="orchestrator", expected_phase="plan",
)
assert orch["resolved"]["modelId"] == "claude-opus-5"
assert worker["resolved"]["modelId"] == "claude-haiku-4-5"
ok("오케스트레이터=opus, 워커=haiku가 동시에 성립한다")

# ── 정책 상한이 실제로 막는가 ───────────────────────────────────────────
clamped = resolve_model_allocation(
    decision("frontier", "claude-opus-5", "high", "execute"),
    HOST_INVENTORY, policy={"worker": {"maxTier": "economy"}},
    role="worker", expected_phase="execute",
)
assert clamped["status"] != "resolved"
assert any("cost_policy" in code for code in clamped["reasonCodes"]), clamped["reasonCodes"]
ok("worker 상한이 frontier 요구를 거절한다")

# ── ① 정책 저장 수단 ────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    env = {**os.environ, "AGENTLAS_ONE_DIR": tmp}
    env.pop("AGENTLAS_MODEL_ALLOCATION_POLICY_JSON", None)
    # 사용자 창구는 hep-orch다(agentlas-one orch는 내부 구현). 게이트도 그 창구로 검증한다.
    orch = str(ROOT / "bin" / "hep-orch")
    subprocess.run([orch, "orchestrator=frontier", "worker=economy"],
                   env=env, check=True, capture_output=True, text=True)
    saved = json.loads((Path(tmp) / "model-policy.json").read_text())
    assert saved == {"orchestrator": {"maxTier": "frontier"}, "worker": {"maxTier": "economy"}}, saved
    ok("hep-orch가 정책을 파일로 저장한다")

    from agentlas_cloud import mcp_stdio
    loaded = mcp_stdio._host_model_allocation_policy()  # noqa: SLF001
    assert loaded.get("worker", {}).get("maxTier") == "economy", \
        f"MCP 서버가 정책 파일을 읽지 못한다: {loaded}"
    ok("MCP 서버가 환경변수 없이 그 파일을 읽는다")

    status = subprocess.run([str(ROOT / "bin" / "agentlas-one"), "statusline"],
                            env={**env, "HOME": os.environ["HOME"]},
                            input='{"workspace":{"current_dir":"/tmp/proj"}}',
                            capture_output=True, text=True)
    # 상태줄은 One이 꺼져 있으면 조용히 빠진다 — 켜져 있을 때만 내용을 검사한다.
    if status.stdout.strip():
        assert "⚙" in status.stdout, f"상태줄에 모델 정책이 없다: {status.stdout!r}"
        ok("상태줄이 오케스트레이터→워커를 보여준다")
    else:
        print("  skip 상태줄(One이 이 환경에서 꺼져 있음)")

# ── 명령서·One 지침에 실제로 적혔는가 ───────────────────────────────────
network = (ROOT / "contracts/commands/hep-network.body.md").read_text()
assert "hep-orch" in network and "context_window" in network
ok("hep-network 명령서가 필수 필드와 설정법을 말한다")

one_skill = (ROOT / "skills/agentlas-operations/SKILL.md").read_text()
assert "model.resolve_allocation" in one_skill and "hep-orch" in one_skill
ok("One 운영 지침이 워커 배정을 지시한다(hep-network 밖에서도)")

hosts = [
    "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-orch.md",
    ".claude/commands/hep-orch.md",
    "codex/prompts/hep-orch.md",
    "opencode/commands/hep-orch.md",
    "cursor/plugin/commands/hep-orch.md",
    "antigravity/workflows/hep-orch.md",
    "gemini/extension/commands/hep-orch.toml",
]
absent = [h for h in hosts if not (ROOT / h).is_file()]
assert not absent, f"hep-orch가 없는 호스트: {absent}"
ok("hep-orch 슬래시 명령이 모든 호스트에 있다")

assert (ROOT / "bin" / "hep-orch").is_file(), "bin/hep-orch 실행 파일이 없다"
ok("bin/hep-orch 실행 파일이 있다")

# 역할 분리가 실제로 두 모델을 띄우는 호스트는 Claude Code뿐이다. 그 한계를 말하지
# 않으면 순차 호스트 사용자가 아낀 줄로 오해한다 — 영수증이 하지 않는 거짓말이다.
orch_body = (ROOT / "contracts/commands/hep-orch.body.md").read_text()
assert "Claude Code" in orch_body and "sequence" in orch_body, \
    "hep-orch가 호스트별 실행 한계를 말하지 않는다"
ok("hep-orch가 Claude Code 전용 한계를 명시한다")

readme = (ROOT / "README.md").read_text()
assert "/hep-orch" in readme and "/hep-update" in readme, "README 명령표에 빠졌다"
# 줄바꿈에 걸리지 않도록 공백을 접어서 검사한다(문단 재배치에 깨지지 않게).
readme_flat = " ".join(readme.split())
assert "only puts two models to work on Claude Code" in readme_flat, \
    "README가 호스트 한계를 말하지 않는다"
ok("README가 두 명령과 그 한계를 담는다")

for name in ("hep-update",):
    hosts_missing = [d for d, kind, *_ in
                     [("claude/plugins/agentlas-core-engine-meta-agent/commands", "md"),
                      (".claude/commands", "md"), ("codex/prompts", "md"),
                      ("opencode/commands", "md"), ("antigravity/workflows", "md")]
                     if not (ROOT / d / f"{name}.{kind}").is_file()]
    assert not hosts_missing, f"{name}이 없는 호스트: {hosts_missing}"
ok("hep-update 슬래시 명령이 호스트에 있다")

print(f"\north-policy: {passed} checks passed")
