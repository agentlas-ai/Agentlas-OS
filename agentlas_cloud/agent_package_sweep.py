"""설치된 에이전트 패키지를 한 바퀴 돌며, 지금 계약과 어긋난 것을 이름으로 말한다.

실측 2026-08-19. 이 머신의 로컬 에이전트 7개 중 **6개가 지금 계약 검증에 떨어진다**:
5개는 그 사이 필수가 된 ``.agentlas/build-profile.json`` 이 없고, 하나는 생성 도구에
``/Users/...`` 절대경로가 박혀 있다. 어느 것도 자기가 낡았다고 말하지 못했고, 쓰는
사람은 업로드할 때에야 알게 된다.

한 패키지씩 열어 보는 것으로는 이 상태를 못 본다 — 한 바퀴 돌아야 "6/7" 이 보인다.
그래서 스윕이 있다.

**고치지는 않는다.** 무엇이 틀렸는지는 계약 검증기가 이미 말하고 있고, 고치는 것은
리패징의 일이다. 여기서 자동으로 파일을 만들어 넣으면, 빌더가 안 만든 것을 스윕이
대신 만들어 주는 셈이라 **빌더 결함이 영원히 안 보인다**. 판정과 수리를 같은 자리에
두지 않는다.

멱등하다 — 같은 스윕을 두 번 돌려도 원장에 한 번만 남는다(memory_hook 의 사다리와
같은 계약).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SWEEP_ID = "agent-package-contract-sweep/1.0"


def local_agents_home() -> Path:
    """설치된 에이전트 패키지가 사는 곳.

    ``~/.agentlas/networking/hub-agents`` 와 혼동하지 않는다 — 실측 2026-08-19:
    그쪽 81개는 전부 **서랍(메모리)** 이고 패키지가 아니었다(AGENTS.md·agentlas.json
    이 하나도 없다). 라우터가 학습을 넣는 곳과 패키지가 사는 곳이 다르다.
    """
    override = os.environ.get("AGENTLAS_AGENT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agentlas" / "agentlas-agent"


def _is_package(path: Path) -> bool:
    return (path / "AGENTS.md").is_file() or (path / "agentlas.json").is_file()


def sweep(home: str | Path | None = None) -> dict[str, Any]:
    """설치된 패키지 전부를 계약으로 재고, 결과를 한 장으로 돌려준다."""
    base = Path(home).expanduser() if home else local_agents_home()
    report: dict[str, Any] = {
        "home": str(base),
        "sweepId": SWEEP_ID,
        "packages": [],
        "ok": 0,
        "failing": 0,
        "skipped": 0,
    }
    if not base.is_dir():
        report["error"] = f"agent home not found: {base}"
        return report

    from .package_contract import verify  # noqa: PLC0415

    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if not _is_package(entry):
            # 패키지가 아닌 디렉터리(서랍·작업 폴더)는 계약 대상이 아니다.
            report["skipped"] += 1
            continue
        try:
            result = verify(str(entry))
        except Exception as exc:  # noqa: BLE001 - 한 패키지의 실패가 스윕을 멈추지 않는다
            report["packages"].append({"slug": entry.name, "state": "unreadable", "detail": str(exc)[:200]})
            report["failing"] += 1
            continue
        blockers = list(result.get("blockers") or [])
        drift = result.get("engine_drift") or {}
        row = {
            "slug": entry.name,
            "state": "ok" if result.get("ok") else "failing",
            "blockers": blockers[:4],
            "engine": drift.get("state"),
            "builtWith": drift.get("builtWith"),
        }
        report["packages"].append(row)
        report["ok" if result.get("ok") else "failing"] += 1
    return report


def render(report: dict[str, Any]) -> str:
    """사람이 읽는 한 화면. 무엇이 몇 개 틀렸는지 먼저 말한다."""
    if report.get("error"):
        return f"agent package sweep: {report['error']}"
    lines = [
        f"agent package sweep — {report['ok']} ok / {report['failing']} failing"
        f" ({report['skipped']} skipped) in {report['home']}",
    ]
    for row in report.get("packages", []):
        if row["state"] == "ok":
            continue
        lines.append(f"  {row['slug']}: {row['state']} (engine={row.get('engine')})")
        for blocker in row.get("blockers", []):
            lines.append(f"    - {blocker}")
    return "\n".join(lines)


def record(report: dict[str, Any], ledger: str | Path | None = None) -> Path | None:
    """스윕이 돌았다는 사실만 원장에 남긴다(판정 내용은 화면과 반환값에 있다)."""
    path = Path(ledger).expanduser() if ledger else (Path.home() / ".agentlas" / "migrations.jsonl")
    from datetime import datetime, timezone  # noqa: PLC0415

    entry = {
        "id": SWEEP_ID,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": report.get("ok"),
        "failing": report.get("failing"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return path
