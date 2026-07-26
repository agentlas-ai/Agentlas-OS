"""Retire the former per-user periodic Agentlas OS update scheduler.

Agentlas updates are command-triggered and non-blocking: supported host commands
and Agentlas Desktop start the verified updater in the background. Releases
v1.1.63 through v1.1.68 also installed a six-hour OS scheduler. That scheduler
was not part of the intended command-triggered contract, so this module now
exists only to detect and remove already-installed scheduler state.
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

SERVICE_ID = "com.agentlas.hephaestus-update"
WINDOWS_TASK_NAME = "AgentlasHephaestusUpdate"
COMMAND_TIMEOUT_SECONDS = 20
RETIREMENT_MARKER = "periodic-update-service-retired-v1.json"


def _runtime_base(home: Path) -> Path:
    configured = os.environ.get("HEPHAESTUS_RUNTIME_BASE")
    return Path(configured).expanduser() if configured else home / ".agentlas" / "runtime"


def _run(command: list[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "exitCode": None, "error": type(exc).__name__}
    return {
        "ok": completed.returncode == 0,
        "exitCode": completed.returncode,
        "error": None if completed.returncode == 0 else (completed.stderr or "command_failed").strip()[-300:],
    }


def _write_retirement_marker(home: Path, result: dict[str, Any]) -> None:
    path = _runtime_base(home) / RETIREMENT_MARKER
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
    """Remove every known legacy scheduler artifact for the current user."""

    home_dir = (home or Path.home()).expanduser().resolve()
    platform_value = (platform_name or sys.platform).lower()
    removed: list[str] = []
    actions: list[dict[str, Any]] = []

    if platform_value.startswith("darwin"):
        path = home_dir / "Library" / "LaunchAgents" / f"{SERVICE_ID}.plist"
        if execute:
            # Remove by service label first. This also retires a loaded job whose
            # plist came from an obsolete or temporary path.
            actions.append(_run(["launchctl", "bootout", f"gui/{os.getuid()}/{SERVICE_ID}"]))
            actions.append(_run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)]))
        if path.exists():
            path.unlink()
            removed.append(str(path))
    elif platform_value.startswith("linux"):
        if execute and shutil.which("systemctl"):
            actions.append(
                _run(["systemctl", "--user", "disable", "--now", "agentlas-hephaestus-update.timer"])
            )
        unit_dir = home_dir / ".config" / "systemd" / "user"
        for name in ("agentlas-hephaestus-update.service", "agentlas-hephaestus-update.timer"):
            path = unit_dir / name
            if path.exists():
                path.unlink()
                removed.append(str(path))
        if execute and shutil.which("systemctl"):
            actions.append(_run(["systemctl", "--user", "daemon-reload"]))
    elif platform_value.startswith(("win", "cygwin", "msys")):
        if execute:
            actions.append(_run(["schtasks", "/Delete", "/F", "/TN", WINDOWS_TASK_NAME]))
        state = _runtime_base(home_dir) / "auto-update-service.json"
        if state.exists():
            state.unlink()
            removed.append(str(state))
    else:
        return {"status": "blocked", "reason": "unsupported_platform", "platform": platform_value}

    remaining = auto_update_service_status(home=home_dir, platform_name=platform_value)
    result = {
        "status": "retired" if not remaining.get("installed") else "blocked",
        "platform": remaining.get("platform", platform_value),
        "removed": removed,
        "actions": actions,
        "remainingInstalled": bool(remaining.get("installed")),
    }
    if not result["remainingInstalled"]:
        _write_retirement_marker(home_dir, result)
    return result


def retire_auto_update_service(
    *,
    home: Path | None = None,
    platform_name: str | None = None,
) -> dict[str, Any]:
    """Idempotently retire the scheduler while keeping command updates silent."""

    home_dir = (home or Path.home()).expanduser().resolve()
    status = auto_update_service_status(home=home_dir, platform_name=platform_name)
    if not status.get("installed"):
        if not status.get("retired"):
            result = {
                "status": "retired",
                "platform": status.get("platform"),
                "removed": [],
                "remainingInstalled": False,
            }
            _write_retirement_marker(home_dir, result)
            return result
        return {
            "status": "already_retired",
            "platform": status.get("platform"),
            "removed": [],
            "remainingInstalled": False,
        }
    return remove_auto_update_service(home=home_dir, platform_name=platform_name)
