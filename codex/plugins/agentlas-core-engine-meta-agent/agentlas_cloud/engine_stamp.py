"""에이전트 패키지에 **어느 엔진으로 지어졌는지**를 남기고, 어긋나면 말한다.

빌드 엔진 버전을 패키지에 기록해, 현재 엔진과의 호환성을 비교할 근거로 쓴다.

그래서 두 가지를 한다.
  1. 빌드가 끝나면 그 엔진 버전을 패키지에 찍는다(``.agentlas/engine-stamp.json``).
  2. 그 패키지를 쓸 때 지금 엔진과 비교해, 다르면 **드리프트로 보고**한다.

이 파일은 판정만 한다 — 자동으로 고치지 않는다. 무엇을 고칠지는 계약 검증기가 이미
말하고 있고(package_contract.verify 의 blockers), 고치는 것은 리패징의 일이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STAMP_REL = Path(".agentlas") / "engine-stamp.json"
SCHEMA_VERSION = "agentlas-engine-stamp/1.0"


def current_engine_version() -> str | None:
    """지금 도는 엔진의 릴리스. 설치 런타임에는 RELEASE 파일이 있고, 저장소 체크아웃에는 없다."""
    try:
        from .update import current_release  # noqa: PLC0415

        return current_release()
    except Exception:
        return None


def read_stamp(workspace: str | Path) -> dict[str, Any] | None:
    """패키지에 찍힌 엔진 스탬프. 없으면 None — 그것도 사실이므로 지어내지 않는다."""
    path = Path(workspace).expanduser() / STAMP_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_stamp(workspace: str | Path, engine_version: str | None = None) -> dict[str, Any] | None:
    """빌드가 끝난 패키지에 엔진 버전을 찍는다.

    버전을 모르면(저장소에서 직접 돌린 경우 등) **찍지 않는다** — "unknown" 을 찍으면
    그 값이 나중에 진짜 버전과 비교돼 거짓 드리프트를 만든다. 모르는 것은 비워 둔다.
    """
    version = engine_version or current_engine_version()
    if not version:
        return None
    from datetime import datetime, timezone  # noqa: PLC0415

    record = {
        "schemaVersion": SCHEMA_VERSION,
        "engineVersion": version,
        "stampedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = Path(workspace).expanduser() / STAMP_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return None
    return record


def drift(workspace: str | Path, engine_version: str | None = None) -> dict[str, Any]:
    """이 패키지가 지금 엔진과 어긋나는가.

    돌려주는 것:
      ``state``  — ``current`` | ``drifted`` | ``unstamped`` | ``unknown_engine``
      ``builtWith`` / ``engineVersion`` — 비교한 두 값(모르면 None)
      ``action`` — 사람이 할 수 있는 한 문장. 판정만 하고 자동으로 고치지 않는다.

    ``unstamped`` 는 ``drifted`` 와 다르다. 스탬프가 없는 패키지는 이 기능보다 먼저
    지어진 것이라 어긋났다고 단정할 수 없다 — 계약 검증으로 확인하라고 말한다.
    """
    running = engine_version or current_engine_version()
    stamp = read_stamp(workspace)
    built_with = str((stamp or {}).get("engineVersion") or "") or None

    if not running:
        return {
            "state": "unknown_engine",
            "builtWith": built_with,
            "engineVersion": None,
            "action": "이 호스트의 엔진 릴리스를 알 수 없어 비교하지 못했습니다(RELEASE 표식 없음).",
        }
    if not built_with:
        return {
            "state": "unstamped",
            "builtWith": None,
            "engineVersion": running,
            "action": (
                "이 패키지에는 어느 엔진으로 지어졌는지가 없습니다. "
                "`agentlas verify <경로>` 로 지금 계약을 통과하는지 확인하고, "
                "떨어지면 패키저로 다시 포장하세요."
            ),
        }
    if built_with == running:
        return {"state": "current", "builtWith": built_with, "engineVersion": running, "action": ""}
    return {
        "state": "drifted",
        "builtWith": built_with,
        "engineVersion": running,
        "action": (
            f"이 패키지는 엔진 {built_with} 때 지어졌고 지금은 {running} 입니다. "
            "그 사이 계약이 바뀌었을 수 있으니 패키저로 다시 포장하세요."
        ),
    }
