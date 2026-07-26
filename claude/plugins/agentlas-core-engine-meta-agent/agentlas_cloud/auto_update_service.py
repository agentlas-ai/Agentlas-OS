"""Per-user, cross-platform scheduling for Agentlas OS updates.

The scheduler never downloads or installs bytes itself.  It only invokes the
managed ``current`` runner, whose updater verifies the tag-specific GitHub
release asset digest before activating a runtime and reconciling host adapters.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SERVICE_ID = "com.agentlas.hephaestus-update"
WINDOWS_TASK_NAME = "AgentlasHephaestusUpdate"
DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60
COMMAND_TIMEOUT_SECONDS = 20


def _runtime_base(home: Path) -> Path:
    configured = os.environ.get("HEPHAESTUS_RUNTIME_BASE")
    return Path(configured).expanduser() if configured else home / ".agentlas" / "runtime"


def _runner(runtime_root: Path) -> Path:
    name = "hephaestus.cmd" if os.name == "nt" else "hephaestus"
    return runtime_root / "bin" / name


def _atomic_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    with tmp.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, mode)
    tmp.replace(path)


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


def _service_command(runtime_root: Path) -> list[str]:
    return [str(_runner(runtime_root)), "hep-update", "--scheduled"]


def _macos_install(home: Path, runtime_root: Path, execute: bool) -> dict[str, Any]:
    path = home / "Library" / "LaunchAgents" / f"{SERVICE_ID}.plist"
    logs = home / "Library" / "Logs" / "Agentlas"
    logs.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": SERVICE_ID,
        "ProgramArguments": _service_command(runtime_root),
        "RunAtLoad": True,
        "StartInterval": DEFAULT_INTERVAL_SECONDS,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": str(logs / "hephaestus-update.log"),
        "StandardErrorPath": str(logs / "hephaestus-update.err.log"),
    }
    _atomic_write(path, plistlib.dumps(payload, fmt=plistlib.FMT_XML))
    activation = {"ok": True, "skipped": not execute}
    if execute:
        domain = f"gui/{os.getuid()}"
        _run(["launchctl", "bootout", domain, str(path)])
        activation = _run(["launchctl", "bootstrap", domain, str(path)])
    return {"platform": "darwin", "status": "installed", "path": str(path), "activation": activation}


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _linux_install(home: Path, runtime_root: Path, execute: bool) -> dict[str, Any]:
    unit_dir = home / ".config" / "systemd" / "user"
    service = unit_dir / "agentlas-hephaestus-update.service"
    timer = unit_dir / "agentlas-hephaestus-update.timer"
    command = " ".join(_systemd_quote(part) for part in _service_command(runtime_root))
    service_text = (
        "[Unit]\n"
        "Description=Agentlas OS verified runtime and host adapter update\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={command}\n"
        "Nice=10\n"
    )
    timer_text = (
        "[Unit]\n"
        "Description=Check for Agentlas OS updates every six hours\n\n"
        "[Timer]\n"
        "OnBootSec=5m\n"
        "OnUnitActiveSec=6h\n"
        "Persistent=true\n"
        "RandomizedDelaySec=10m\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    _atomic_write(service, service_text.encode("utf-8"))
    _atomic_write(timer, timer_text.encode("utf-8"))
    activation = {"ok": True, "skipped": not execute}
    if execute and shutil.which("systemctl"):
        reload_result = _run(["systemctl", "--user", "daemon-reload"])
        enable_result = _run(
            ["systemctl", "--user", "enable", "--now", "agentlas-hephaestus-update.timer"]
        )
        activation = {"ok": reload_result["ok"] and enable_result["ok"], "reload": reload_result, "enable": enable_result}
    elif execute:
        activation = {"ok": False, "error": "systemctl_user_unavailable"}
    return {
        "platform": "linux",
        "status": "installed" if activation["ok"] else "installed_pending_enable",
        "paths": [str(service), str(timer)],
        "activation": activation,
    }


def _windows_install(home: Path, runtime_root: Path, execute: bool) -> dict[str, Any]:
    command = subprocess.list2cmdline(_service_command(runtime_root))
    arguments = [
        "schtasks",
        "/Create",
        "/F",
        "/SC",
        "HOURLY",
        "/MO",
        "6",
        "/TN",
        WINDOWS_TASK_NAME,
        "/TR",
        command,
    ]
    activation = {"ok": True, "skipped": not execute}
    if execute:
        activation = _run(arguments)
    state = _runtime_base(home) / "auto-update-service.json"
    _atomic_write(
        state,
        (
            json.dumps(
                {
                    "schemaVersion": "agentlas.auto-update-service.v1",
                    "platform": "windows",
                    "task": WINDOWS_TASK_NAME,
                    "command": _service_command(runtime_root),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )
    return {"platform": "windows", "status": "installed" if activation["ok"] else "blocked", "path": str(state), "activation": activation}


def install_auto_update_service(
    *,
    home: Path | None = None,
    runtime_root: Path | None = None,
    platform_name: str | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    home_dir = (home or Path.home()).expanduser().resolve()
    selected_root = (runtime_root or (_runtime_base(home_dir) / "current")).expanduser()
    if not selected_root.is_absolute():
        selected_root = Path.cwd() / selected_root
    runner = _runner(selected_root)
    if not runner.is_file():
        return {"status": "blocked", "reason": "managed_runner_missing", "runner": str(runner)}
    platform_value = (platform_name or sys.platform).lower()
    if platform_value.startswith("darwin"):
        return _macos_install(home_dir, selected_root, execute)
    if platform_value.startswith("linux"):
        return _linux_install(home_dir, selected_root, execute)
    if platform_value.startswith(("win", "cygwin", "msys")):
        return _windows_install(home_dir, selected_root, execute)
    return {"status": "blocked", "reason": "unsupported_platform", "platform": platform_value}


def auto_update_service_status(
    *,
    home: Path | None = None,
    platform_name: str | None = None,
) -> dict[str, Any]:
    home_dir = (home or Path.home()).expanduser().resolve()
    platform_value = (platform_name or sys.platform).lower()
    if platform_value.startswith("darwin"):
        path = home_dir / "Library" / "LaunchAgents" / f"{SERVICE_ID}.plist"
        return {"platform": "darwin", "installed": path.is_file(), "path": str(path)}
    if platform_value.startswith("linux"):
        unit_dir = home_dir / ".config" / "systemd" / "user"
        paths = [
            unit_dir / "agentlas-hephaestus-update.service",
            unit_dir / "agentlas-hephaestus-update.timer",
        ]
        return {"platform": "linux", "installed": all(path.is_file() for path in paths), "paths": [str(path) for path in paths]}
    if platform_value.startswith(("win", "cygwin", "msys")):
        state = _runtime_base(home_dir) / "auto-update-service.json"
        return {"platform": "windows", "installed": state.is_file(), "path": str(state)}
    return {"platform": platform_value, "installed": False, "reason": "unsupported_platform"}


def remove_auto_update_service(
    *,
    home: Path | None = None,
    platform_name: str | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    home_dir = (home or Path.home()).expanduser().resolve()
    platform_value = (platform_name or sys.platform).lower()
    removed: list[str] = []
    if platform_value.startswith("darwin"):
        path = home_dir / "Library" / "LaunchAgents" / f"{SERVICE_ID}.plist"
        if execute and path.exists():
            _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)])
        if path.exists():
            path.unlink()
            removed.append(str(path))
    elif platform_value.startswith("linux"):
        if execute and shutil.which("systemctl"):
            _run(["systemctl", "--user", "disable", "--now", "agentlas-hephaestus-update.timer"])
        unit_dir = home_dir / ".config" / "systemd" / "user"
        for name in ("agentlas-hephaestus-update.service", "agentlas-hephaestus-update.timer"):
            path = unit_dir / name
            if path.exists():
                path.unlink()
                removed.append(str(path))
        if execute and shutil.which("systemctl"):
            _run(["systemctl", "--user", "daemon-reload"])
    elif platform_value.startswith(("win", "cygwin", "msys")):
        if execute:
            _run(["schtasks", "/Delete", "/F", "/TN", WINDOWS_TASK_NAME])
        state = _runtime_base(home_dir) / "auto-update-service.json"
        if state.exists():
            state.unlink()
            removed.append(str(state))
    else:
        return {"status": "blocked", "reason": "unsupported_platform", "platform": platform_value}
    return {"status": "removed", "platform": platform_value, "removed": removed}
