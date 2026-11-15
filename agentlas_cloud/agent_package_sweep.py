"""설치된 에이전트 패키지를 한 바퀴 돌며, 지금 계약과 어긋난 것을 이름으로 말한다.

설치된 패키지들의 계약 검증 결과를 모아 사용자가 호환성 문제를 확인하게 한다.

스윕은 개별 패키지 결과를 모아 설치 상태를 한 번에 보여 준다.

**고치지는 않는다.** 무엇이 틀렸는지는 계약 검증기가 이미 말하고 있고, 고치는 것은
리패징의 일이다. 여기서 자동으로 파일을 만들어 넣으면, 빌더가 안 만든 것을 스윕이
대신 만들어 주는 셈이라 **빌더 결함이 영원히 안 보인다**. 판정과 수리를 같은 자리에
두지 않는다.

멱등하다 — 같은 스윕을 두 번 돌려도 원장에 한 번만 남는다(memory_hook 의 사다리와
같은 계약).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SWEEP_ID = "agent-package-contract-sweep/1.0"


def local_agents_home() -> Path:
    """설치된 에이전트 패키지가 사는 곳.

    패키지 저장소와 networking/hub-agents 메모리 서랍은 구분한다.
    AGENTS.md 또는 agentlas.json 을 가진 설치 패키지를 대상으로 한다.
    """
    # 2.0: one resolver for the agents root (AGENTLAS_AGENT_HOME -> agents-root.json -> ~/.agentlas/agents).
    from .agent_home import agents_root  # noqa: PLC0415

    return agents_root()


def _is_package(path: Path) -> bool:
    return (path / "AGENTS.md").is_file() or (path / "agentlas.json").is_file()


def sweep(home: str | Path | None = None) -> dict[str, Any]:
    """설치된 패키지 전부를 계약으로 재고, 결과를 한 장으로 돌려준다."""
    if home:
        bases = [Path(home).expanduser()]
    else:
        from .agent_home import agent_homes_to_read  # noqa: PLC0415

        # The agents root and the pre-2.0 `agentlas-agent` home are both read.
        bases = agent_homes_to_read() or [local_agents_home()]
    base = bases[0]
    report: dict[str, Any] = {
        "home": str(base),
        "sweepId": SWEEP_ID,
        "packages": [],
        "ok": 0,
        "failing": 0,
        "skipped": 0,
    }
    if not home:
        from .agent_home import agents_root_status  # noqa: PLC0415

        # Say what the configured root is and why it is not readable (an unplugged drive), instead of
        # reporting "not found" for a default folder nobody configured.
        report["rootStatus"] = agents_root_status()
    bases = [item for item in bases if item.is_dir()]
    if not bases:
        status = report.get("rootStatus") or {}
        if status.get("configured") and not status.get("available"):
            report["error"] = f"agents folder not available: {status.get('path') or 'agents-root.json'} ({status.get('reason')}); reconnect it"
        else:
            report["error"] = f"agent home not found: {base}"
        return report

    from .package_contract import verify  # noqa: PLC0415

    entries: list[Path] = []
    seen_names: set[str] = set()
    for item in bases:
        for entry in sorted(item.iterdir()):
            # The first home wins: a folder with the same name in the older home is the same agent left behind.
            if entry.name in seen_names:
                report["skipped"] += 1
                continue
            seen_names.add(entry.name)
            entries.append(entry)
    for entry in entries:
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
