"""Runtime update checks for the Hephaestus CLI.

The explicit ``hephaestus update`` command can install the latest runtime into
``~/.agentlas/runtime/<version>`` and atomically point ``current`` at it. Normal
command paths start a detached, fail-silent auto-update worker at most once per
TTL window so the user's command does not wait on network or install work.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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
HEP_COMMANDS = ("hep-build", "hep-network", "hep-cloud", "hep-search", "hep-call", "hep-upload")
HEP_SKILLS = ("hephaestus-network", "hephaestus-cloud")
AUTO_UPDATE_MARKER = "auto-update.json"


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


def maybe_auto_update(root: Path | None = None, *, background: bool = True) -> None:
    """Start a fail-silent runtime auto-update check.

    This function intentionally returns ``None`` for every outcome. It never
    raises, never prints, and by default never performs network or install work
    in the caller process.
    """

    try:
        if _auto_update_disabled():
            return
        runtime_root = root or Path(__file__).resolve().parent.parent
        current = current_release(runtime_root)
        if not _is_comparable_release(current):
            return
        base = _runtime_base()
        if (base / ".update.lock").exists():
            return
        marker_path = base / AUTO_UPDATE_MARKER
        marker = _read_json(marker_path)
        if _marker_recent(marker.get("last_started_epoch")):
            return
        _write_json(
            marker_path,
            {
                **marker,
                "last_started_epoch": int(time.time()),
                "current": current,
                "runtime_root": str(runtime_root),
            },
        )
        if background:
            _spawn_auto_update_worker(runtime_root)
        else:
            _run_auto_update_once(runtime_root)
    except Exception:
        return


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
    adapter_sync: dict[str, Any] = {"updated": [], "skipped_missing": [], "failed": []}
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
            adapter_sync = sync_installed_runtime_adapters(source)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass

    return {
        "runtime_root": str(target),
        "current_link": str(base / "current"),
        "updated_to": tag,
        "adapter_sync": adapter_sync,
    }


def sync_installed_runtime_adapters(source: Path, home: Path | None = None) -> dict[str, Any]:
    """Refresh already-installed command and skill adapters from ``source``.

    Only exact destination paths that already exist are overwritten. This keeps
    auto-update from installing a runtime surface the user never set up.
    """

    home_dir = home or Path.home()
    updated: list[str] = []
    skipped_missing: list[str] = []
    failed: list[dict[str, str]] = []

    for src_rel, dest in _installed_adapter_file_targets(source, home_dir):
        src = source / src_rel
        if not src.exists() or not dest.exists():
            skipped_missing.append(str(dest))
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            updated.append(str(dest))
        except Exception as exc:
            failed.append({"path": str(dest), "error": str(exc)})

    for src_rel, dest in _installed_adapter_dir_targets(source, home_dir):
        src = source / src_rel
        if not src.is_dir() or not dest.exists():
            skipped_missing.append(str(dest))
            continue
        try:
            _replace_directory(src, dest)
            updated.append(str(dest))
        except Exception as exc:
            failed.append({"path": str(dest), "error": str(exc)})

    return {
        "updated": updated,
        "skipped_missing": skipped_missing,
        "failed": failed,
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
    if not _is_comparable_release(current) or not _is_comparable_release(str(latest)):
        return "unknown"
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


def _is_comparable_release(value: str | None) -> bool:
    if not value:
        return False
    cleaned = value.strip().lstrip("vV")
    return any(ch.isdigit() for ch in cleaned)


def _runtime_base() -> Path:
    return Path(os.environ.get("HEPHAESTUS_RUNTIME_BASE") or Path.home() / ".agentlas" / "runtime")


def _auto_update_disabled() -> bool:
    return os.environ.get("HEPHAESTUS_AUTO_UPDATE", "1") == "0" or os.environ.get("HEPHAESTUS_UPDATE_CHECK", "1") == "0"


def _marker_recent(epoch: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    return isinstance(epoch, (int, float)) and time.time() - float(epoch) < ttl_seconds


def _run_auto_update_once(root: Path | None = None) -> dict[str, Any]:
    runtime_root = root or Path(__file__).resolve().parent.parent
    current = current_release(runtime_root)
    marker_path = _runtime_base() / AUTO_UPDATE_MARKER
    marker = _read_json(marker_path)
    if not _is_comparable_release(current):
        result = {"status": "skipped", "reason": "missing_or_uncomparable_release", "current": current}
        _write_json(marker_path, {**marker, **result, "last_checked_epoch": int(time.time())})
        return result

    latest = fetch_latest_release(force=False)
    latest_tag = latest.get("tag_name")
    status = _release_status(current, latest_tag)
    result: dict[str, Any] = {
        "status": status,
        "current": current,
        "latest": latest_tag,
        "last_checked_epoch": int(time.time()),
    }
    if status != "update_available":
        _write_json(marker_path, {**marker, **result})
        return result
    if marker.get("last_applied_tag") == latest_tag and _marker_recent(marker.get("last_applied_epoch")):
        result["status"] = "skipped"
        result["reason"] = "already_applied_recently"
        _write_json(marker_path, {**marker, **result})
        return result

    installed = install_latest_runtime(latest)
    result.update(installed)
    result["status"] = "updated"
    result["last_applied_tag"] = latest_tag
    result["last_applied_epoch"] = int(time.time())
    _write_json(marker_path, {**marker, **result})
    return result


def _spawn_auto_update_worker(runtime_root: Path) -> None:
    env = os.environ.copy()
    env["HEPHAESTUS_AUTO_UPDATE_WORKER"] = "1"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(runtime_root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as stdout, open(os.devnull, "wb") as stderr:
        subprocess.Popen(
            [sys.executable, "-m", "agentlas_cloud.update", "--auto-update-worker", str(runtime_root)],
            cwd=str(runtime_root),
            env=env,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            start_new_session=True,
        )


def _installed_adapter_file_targets(source: Path, home: Path) -> list[tuple[Path, Path]]:
    targets: list[tuple[Path, Path]] = []
    for command in HEP_COMMANDS:
        targets.extend(
            [
                (Path(".claude") / "commands" / f"{command}.md", home / ".claude" / "commands" / f"{command}.md"),
                (Path("codex") / "prompts" / f"{command}.md", home / ".codex" / "prompts" / f"{command}.md"),
                (Path("cursor") / "plugin" / "commands" / f"{command}.md", home / ".cursor" / "commands" / f"{command}.md"),
                (Path("opencode") / "commands" / f"{command}.md", home / ".config" / "opencode" / "commands" / f"{command}.md"),
                (Path("antigravity") / "workflows" / f"{command}.md", home / ".gemini" / "antigravity" / "global_workflows" / f"{command}.md"),
                (
                    Path("antigravity") / "workflows" / f"{command}.md",
                    home / ".gemini" / "antigravity-ide" / "global_workflows" / f"{command}.md",
                ),
                (
                    Path("gemini") / "extension" / "commands" / f"{command}.toml",
                    home / ".gemini" / "commands" / f"{command}.toml",
                ),
                (
                    Path("gemini") / "extension" / "commands" / f"{command}.toml",
                    home / ".gemini" / "hephaestus-extension-source" / "commands" / f"{command}.toml",
                ),
            ]
        )
    return [(src_rel, dest) for src_rel, dest in targets if (source / src_rel).exists()]


def _installed_adapter_dir_targets(source: Path, home: Path) -> list[tuple[Path, Path]]:
    targets: list[tuple[Path, Path]] = []
    if (source / "gemini" / "extension").is_dir():
        targets.append((Path("gemini") / "extension", home / ".gemini" / "hephaestus-extension-source"))
    for skill in HEP_SKILLS:
        targets.extend(
            [
                (Path("skills") / skill, home / ".agents" / "skills" / skill),
                (Path("skills") / skill, home / ".cursor" / "skills" / skill),
                (Path("openclaw") / "skills" / skill, home / ".openclaw" / "skills" / skill),
                (Path("skills") / skill, home / ".hermes" / "skills" / skill),
            ]
        )
    return [(src_rel, dest) for src_rel, dest in targets if (source / src_rel).is_dir()]


def _replace_directory(src: Path, dest: Path) -> None:
    tmp = dest.parent / f".{dest.name}.tmp-{os.getpid()}"
    if tmp.exists() or tmp.is_symlink():
        if tmp.is_dir() and not tmp.is_symlink():
            shutil.rmtree(tmp)
        else:
            tmp.unlink()
    shutil.copytree(src, tmp)
    if dest.exists() or dest.is_symlink():
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    tmp.rename(dest)


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


def _main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) == 2 and args[0] == "--auto-update-worker":
        try:
            _run_auto_update_once(Path(args[1]))
        except Exception:
            return 0
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
