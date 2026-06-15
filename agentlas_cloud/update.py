"""Runtime update checks for the Hephaestus CLI.

The route path only does a small TTL-gated check and prints to stderr. The
explicit ``hephaestus update`` command can install the latest runtime into
``~/.agentlas/runtime/<version>`` and atomically point ``current`` at it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

LATEST_RELEASE_URL = os.environ.get(
    "HEPHAESTUS_LATEST_RELEASE_URL",
    "https://api.github.com/repos/agentlas-ai/Hephaestus/releases/latest",
)
DEFAULT_TTL_SECONDS = 24 * 60 * 60
CORE_DIRS = ("bin", "agentlas_cloud", "ontology")


def current_release(root: Path | None = None) -> str | None:
    runtime_root = root or Path(__file__).resolve().parent.parent
    marker = runtime_root / "RELEASE"
    if not marker.exists():
        return None
    value = marker.read_text(encoding="utf-8").strip()
    return value or None


def run_update(check_only: bool = False, root: Path | None = None) -> dict[str, Any]:
    runtime_root = root or Path(__file__).resolve().parent.parent
    current = current_release(runtime_root)
    latest = fetch_latest_release(force=True)
    status = _release_status(current, latest.get("tag_name"))
    result: dict[str, Any] = {
        "status": status,
        "current": current,
        "latest": latest.get("tag_name"),
        "html_url": latest.get("html_url"),
        "install_command": "hephaestus update",
    }
    if check_only or status != "update_available":
        return result

    installed = install_latest_runtime(latest)
    result.update(installed)
    result["status"] = "updated"
    return result


def maybe_print_update_notice(root: Path | None = None) -> None:
    if os.environ.get("HEPHAESTUS_UPDATE_CHECK", "1") == "0":
        return
    runtime_root = root or Path(__file__).resolve().parent.parent
    current = current_release(runtime_root)
    if not current:
        return
    try:
        latest = fetch_latest_release(force=False)
    except Exception:
        return
    latest_tag = latest.get("tag_name")
    if _release_status(current, latest_tag) != "update_available":
        return
    print(
        f"Hephaestus update available: {latest_tag} (current {current}). Run: hephaestus update",
        file=sys.stderr,
    )


def fetch_latest_release(force: bool = False, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict[str, Any]:
    cache_path = _runtime_base() / "update-check.json"
    if not force:
        cached = _read_json(cache_path)
        epoch = cached.get("epoch") if isinstance(cached, dict) else None
        release = cached.get("release") if isinstance(cached, dict) else None
        if isinstance(epoch, (int, float)) and isinstance(release, dict) and time.time() - float(epoch) < ttl_seconds:
            return release

    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "hephaestus-runtime-update-check",
        },
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        release = json.loads(response.read().decode("utf-8"))
    if not isinstance(release, dict) or not release.get("tag_name"):
        raise ValueError("latest release response missing tag_name")
    _write_json(cache_path, {"epoch": int(time.time()), "release": release})
    return release


def install_latest_runtime(release: dict[str, Any]) -> dict[str, Any]:
    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("release tag_name is required")
    tarball_url = str(release.get("tarball_url") or "").strip()
    if not tarball_url:
        raise ValueError("release tarball_url is required")

    base = _runtime_base()
    target = base / tag.lstrip("v")
    lock = base / ".update.lock"
    _acquire_lock(lock)
    try:
        with tempfile.TemporaryDirectory(prefix="hephaestus-update-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "source.tar.gz"
            _download(tarball_url, archive)
            with tarfile.open(archive, "r:gz") as tf:
                _safe_extract(tf, tmp_path)
            source = next((item for item in tmp_path.iterdir() if item.is_dir()), None)
            if source is None:
                raise ValueError("downloaded release did not contain a source directory")

            tmp_target = base / f".{target.name}.tmp"
            if tmp_target.exists():
                shutil.rmtree(tmp_target)
            tmp_target.mkdir(parents=True)
            for name in CORE_DIRS:
                src = source / name
                if src.exists():
                    shutil.copytree(src, tmp_target / name)
            (tmp_target / "RELEASE").write_text(f"{tag}\n", encoding="utf-8")
            write_python_shims(tmp_target / "bin", sys.executable)
            if target.exists():
                shutil.rmtree(target)
            tmp_target.rename(target)
            _point_current_at(target)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass

    return {
        "runtime_root": str(target),
        "current_link": str(base / "current"),
        "updated_to": tag,
    }


def write_python_shims(bin_dir: Path, executable: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    shell_shim = bin_dir / "python3"
    cmd_shim = bin_dir / "python3.cmd"
    cmd_runner = bin_dir / "hephaestus.cmd"
    env_cmd = bin_dir / "hephaestus-env.cmd"
    shell_shim.write_text(f'#!/usr/bin/env bash\nexec "{executable}" "$@"\n', encoding="utf-8")
    shell_shim.chmod(0o755)
    cmd_shim.write_text(f'@"{executable}" %*\r\n', encoding="utf-8")
    _write_cmd_runner(cmd_runner)
    env_cmd.write_text(
        '@echo off\r\nset "PYTHONUTF8=1"\r\nset "PYTHONIOENCODING=utf-8"\r\nset "PYTHONPATH=%~dp0..;%PYTHONPATH%"\r\n',
        encoding="utf-8",
    )


def _write_cmd_runner(path: Path) -> None:
    path.write_text(
        '@echo off\r\n'
        'set "PYTHONUTF8=1"\r\n'
        'set "PYTHONIOENCODING=utf-8"\r\n'
        'set "PYTHONPATH=%~dp0..;%PYTHONPATH%"\r\n'
        'if exist "%~dp0python3.cmd" (\r\n'
        '  call "%~dp0python3.cmd" -m agentlas_cloud %*\r\n'
        ') else (\r\n'
        '  py -3 -m agentlas_cloud %* || python -m agentlas_cloud %*\r\n'
        ')\r\n',
        encoding="utf-8",
    )


def _release_status(current: str | None, latest: Any) -> str:
    if not latest:
        return "unknown"
    if not current:
        return "missing_release_marker"
    if _version_tuple(str(latest)) > _version_tuple(str(current)):
        return "update_available"
    return "current"


def _version_tuple(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lstrip("vV")
    parts: list[int] = []
    for part in cleaned.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits or "0"))
    return tuple(parts or [0])


def _runtime_base() -> Path:
    return Path(os.environ.get("HEPHAESTUS_RUNTIME_BASE") or Path.home() / ".agentlas" / "runtime")


def _download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "hephaestus-runtime-updater"})
    with urllib.request.urlopen(request, timeout=30) as response, path.open("wb") as out:
        shutil.copyfileobj(response, out)


def _safe_extract(tf: tarfile.TarFile, destination: Path) -> None:
    dest = destination.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(dest) + os.sep):
            raise ValueError(f"unsafe path in release archive: {member.name}")
    tf.extractall(dest)


def _point_current_at(target: Path) -> None:
    current = target.parent / "current"
    if current.exists() or current.is_symlink():
        if current.is_symlink() or current.is_file():
            current.unlink()
        else:
            backup = target.parent / f".current.backup.{int(time.time())}"
            current.rename(backup)
    try:
        current.symlink_to(target, target_is_directory=True)
    except OSError:
        shutil.copytree(target, current, dirs_exist_ok=True)


def _acquire_lock(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"update already running: {path}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
