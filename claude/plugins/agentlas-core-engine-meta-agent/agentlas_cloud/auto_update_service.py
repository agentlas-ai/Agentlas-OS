"""Preserve legacy scheduler state until ownership is verified.

Current runtimes ignore legacy scheduled update requests. Existing scheduler
registrations remain untouched because a public label is not proof of ownership.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from .windows_console import no_console_window

SERVICE_ID = "com.agentlas.hephaestus-update"
WINDOWS_TASK_NAME = "AgentlasHephaestusUpdate"
COMMAND_TIMEOUT_SECONDS = 20
RETIREMENT_MARKER = "periodic-update-service-retired-v1.json"


def _runtime_base(home: Path) -> Path:
    configured = os.environ.get("HEPHAESTUS_RUNTIME_BASE")
    return Path(configured).expanduser() if configured else home / ".agentlas" / "runtime"


def _text_mode() -> dict[str, Any]:
    """How to decode the service manager's output.

    schtasks prints in the console OEM code page (949 on Korean Windows). The runtime runs
    with PYTHONUTF8=1, so ``text=True`` decoded it as strict UTF-8 and raised
    UnicodeDecodeError on the first Korean error message — swallowed by the caller, so the
    retirement marker was never written and schtasks ran again on every maintenance pass.
    POSIX launchctl/systemctl output is unchanged (``text=True``).
    """
    if os.name == "nt":
        return {"encoding": "oem", "errors": "replace"}
    return {"text": True}


def _run(command: list[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_text_mode(),
            timeout=timeout,
            check=False,
            **no_console_window(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "exitCode": None, "error": type(exc).__name__}
    return {
        "ok": completed.returncode == 0,
        "exitCode": completed.returncode,
        "error": None if completed.returncode == 0 else (completed.stderr or "command_failed").strip()[-300:],
    }


def _write_retirement_marker(home: Path, result: dict[str, Any]) -> None:
    base = _runtime_base(home)
    # ★설치본이 없으면 은퇴시킬 스케줄러도 없다 — 그 사실을 기록하려고 런타임
    # 홈을 짓지 않는다. maybe_auto_update 는 "런타임이 없으면 아무것도 만들지
    # 않는다"를 이미 보장하는데, 그 가드보다 **앞서** 불리는 이 마커 기록이
    # parents=True 로 디렉터리를 먼저 만들어 계약을 깨고 있었다(실측 2026-08-21:
    # 격리 HOME 에 .agentlas/runtime/{periodic-update-service-retired-v1.json,
    # auto-update.json} 이 생김). 가드는 가장 먼저 지나는 문에 있어야 한다.
    if not base.is_dir():
        return
    path = base / RETIREMENT_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    payload = {
        "schemaVersion": "agentlas.periodic-update-service-retirement.v1",
        "retiredAt": int(time.time()),
        "platform": result.get("platform"),
    }
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def auto_update_service_status(
    *,
    home: Path | None = None,
    platform_name: str | None = None,
) -> dict[str, Any]:
    """Report whether a legacy periodic scheduler is still present."""

    home_dir = (home or Path.home()).expanduser().resolve()
    platform_value = (platform_name or sys.platform).lower()
    marker = _runtime_base(home_dir) / RETIREMENT_MARKER
    if platform_value.startswith("darwin"):
        path = home_dir / "Library" / "LaunchAgents" / f"{SERVICE_ID}.plist"
        target = f"gui/{os.getuid()}/{SERVICE_ID}"
        loaded = _run(["launchctl", "print", target]).get("ok", False)
        return {
            "platform": "darwin",
            "installed": path.is_file() or loaded,
            "path": str(path),
            "loaded": loaded,
            "retired": marker.is_file(),
        }
    if platform_value.startswith("linux"):
        unit_dir = home_dir / ".config" / "systemd" / "user"
        paths = [
            unit_dir / "agentlas-hephaestus-update.service",
            unit_dir / "agentlas-hephaestus-update.timer",
        ]
        return {
            "platform": "linux",
            "installed": any(path.is_file() for path in paths),
            "paths": [str(path) for path in paths],
            "retired": marker.is_file(),
        }
    if platform_value.startswith(("win", "cygwin", "msys")):
        state = _runtime_base(home_dir) / "auto-update-service.json"
        queried = _run(["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME])
        return {
            "platform": "windows",
            "installed": state.is_file() or queried.get("ok", False),
            "path": str(state),
            "retired": marker.is_file(),
        }
    return {
        "platform": platform_value,
        "installed": False,
        "retired": marker.is_file(),
        "reason": "unsupported_platform",
    }


def remove_auto_update_service(
    *,
    home: Path | None = None,
    platform_name: str | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    """Preserve scheduler state until ownership can be proven."""
    del home, platform_name, execute
    return {"status": "preserved", "reason": "service_ownership_unverified", "managerInvoked": False}


def install_auto_update_service(
    *,
    home: Path | None = None,
    runtime_root: Path | None = None,
    platform_name: str | None = None,
    execute: bool = True,
    **_: Any,
) -> dict[str, Any]:
    """Compatibility shim; neither creates nor removes a scheduler."""

    del runtime_root
    result = remove_auto_update_service(
        home=home,
        platform_name=platform_name,
        execute=execute,
    )
    result["compatibilityShim"] = True
    return result


def retire_auto_update_service(
    *,
    home: Path | None = None,
    platform_name: str | None = None,
) -> dict[str, Any]:
    """Do not mutate a scheduler based only on its public name."""
    del home, platform_name
    return {"status": "preserved", "reason": "service_ownership_unverified", "managerInvoked": False}
