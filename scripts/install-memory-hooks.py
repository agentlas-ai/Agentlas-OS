#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

# This file is also the post-activation bridge used by older managed-runtime
# updaters. Those callers can start it with a Python executable inside a signed
# desktop bundle and without any bytecode boundary. Establish the boundary
# before importing the rest of the installer so this compatibility process
# itself cannot add caches to that bundle.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
if os.name == "nt":
    _BOOTSTRAP_HOME = os.path.realpath(
        os.environ.get("HOME") or os.environ.get("USERPROFILE") or "C:\\"
    )
    _BOOTSTRAP_CACHE_PREFIX = os.path.join(
        _BOOTSTRAP_HOME,
        "AppData",
        "Local",
        "Agentlas",
        "PythonCache",
    )
else:
    _BOOTSTRAP_HOME = os.path.realpath(os.environ.get("HOME") or "/tmp")
    if sys.platform == "darwin":
        _BOOTSTRAP_CACHE_PREFIX = os.path.join(
            _BOOTSTRAP_HOME,
            "Library",
            "Caches",
            "Agentlas",
            "python",
        )
    else:
        _BOOTSTRAP_CACHE_PREFIX = os.path.join(
            _BOOTSTRAP_HOME,
            ".cache",
            "agentlas",
            "python",
        )
_BOOTSTRAP_EXECUTABLE = os.path.realpath(sys.executable)
_BOOTSTRAP_MARKER = f".app{os.sep}Contents{os.sep}Resources"
if _BOOTSTRAP_MARKER in _BOOTSTRAP_EXECUTABLE:
    _BOOTSTRAP_RESOURCES = (
        _BOOTSTRAP_EXECUTABLE.split(_BOOTSTRAP_MARKER, 1)[0]
        + _BOOTSTRAP_MARKER
    )
    try:
        _BOOTSTRAP_INSIDE_RESOURCES = (
            os.path.commonpath((_BOOTSTRAP_RESOURCES, _BOOTSTRAP_CACHE_PREFIX))
            == _BOOTSTRAP_RESOURCES
        )
    except ValueError:
        _BOOTSTRAP_INSIDE_RESOURCES = False
    if _BOOTSTRAP_INSIDE_RESOURCES:
        _BOOTSTRAP_CACHE_PREFIX = os.path.join(
            "/tmp" if os.name != "nt" else "C:\\Windows\\Temp",
            f"agentlas-python-{os.getuid() if hasattr(os, 'getuid') else 'user'}",
        )
os.environ["PYTHONPYCACHEPREFIX"] = _BOOTSTRAP_CACHE_PREFIX
sys.pycache_prefix = _BOOTSTRAP_CACHE_PREFIX

import argparse
import hashlib
import json
import plistlib
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parent.parent
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from agentlas_cloud.desktop_repair import (
    repair_installed_desktop_python_cache_seal as run_desktop_repair_bridge,
)
from agentlas_cloud.desktop_updater_cleanup import (
    repair_installed_desktop_updater_cache as run_desktop_updater_cleanup_bridge,
)
from agentlas_cloud.memory_hosts import INSTALLABLE_HOSTS, MEMORY_HOOK_HOSTS
from agentlas_cloud.update import (
    _safe_python_cache_prefix,
    reconcile_legacy_host_plugin_transition,
)


BEGIN_MARKER = "<!-- AGENTLAS:MEMORY-HOOK:BEGIN -->"
END_MARKER = "<!-- AGENTLAS:MEMORY-HOOK:END -->"
# Derived from the shared host table (agentlas_cloud/memory_hosts.py) so this
# installer and the hook's own host dispatch can never disagree by hand.
SUPPORTED_HOSTS = INSTALLABLE_HOSTS
DESKTOP_REPAIR_MARKER = "desktop-update-bridge-v1.json"
DESKTOP_REPAIR_VERSIONS = {"0.8.58", "0.8.59"}
DESKTOP_BUNDLE_ID = "com.agentlas.desktop"
DESKTOP_TEAM_ID = "F469CGM7T5"
DESKTOP_AUTHORITY = "Developer ID Application: Jeongmin Kim (F469CGM7T5)"
DESKTOP_REQUIREMENT = (
    'identifier "com.agentlas.desktop" and anchor apple generic and '
    'certificate leaf[field.1.2.840.113635.100.6.1.13] exists and '
    'certificate 1[field.1.2.840.113635.100.6.2.6] exists and '
    'certificate leaf[subject.OU] = "F469CGM7T5"'
)
RUNTIME_SHIM_FILES = (
    "python3",
    "python3.cmd",
    "hephaestus.cmd",
    "hephaestus-env.cmd",
)
RUNTIME_VERSION_RE = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


class InstallError(RuntimeError):
    pass


def _command(command: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [command, *args], capture_output=True, text=True, timeout=15, check=False
    )


def _verified_runtime_update_context(source_dir: Path) -> bool:
    if sys.platform != "darwin" or not os.environ.get("HEPHAESTUS_RUNTIME_ROOT"):
        return False
    marker = source_dir / DESKTOP_REPAIR_MARKER
    try:
        source_metadata = source_dir.lstat()
        marker_metadata = marker.lstat()
        if (
            not stat.S_ISDIR(source_metadata.st_mode)
            or stat.S_ISLNK(source_metadata.st_mode)
            or not stat.S_ISREG(marker_metadata.st_mode)
            or stat.S_ISLNK(marker_metadata.st_mode)
            or marker_metadata.st_nlink != 1
        ):
            return False
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload != {
        "schemaVersion": 1,
        "purpose": "repair-agentlas-desktop-python-cache-seal",
        "bundleIdentifier": DESKTOP_BUNDLE_ID,
        "teamIdentifier": DESKTOP_TEAM_ID,
        "versions": sorted(DESKTOP_REPAIR_VERSIONS),
    }:
        return False

    # A freshly downloaded, digest-verified runtime is extracted under this
    # private temporary prefix before activation. Keep that first-run bridge.
    if any(parent.name.startswith("hephaestus-update-") for parent in source_dir.parents):
        return True

    # Retrying after activation must use the exact managed runtime selected by
    # ~/.agentlas/runtime/current. A marker copied to an arbitrary directory is
    # not sufficient. v1.1.55 is the first version with this managed-context
    # contract; later patch/minor releases remain eligible without another
    # one-shot bridge.
    runtime_base = Path(
        os.environ.get("HEPHAESTUS_RUNTIME_BASE")
        or Path.home() / ".agentlas" / "runtime"
    )
    current_link = runtime_base / "current"
    release_marker = source_dir / "RELEASE"
    try:
        base_metadata = runtime_base.lstat()
        current_metadata = current_link.lstat()
        release_metadata = release_marker.lstat()
        resolved_base = runtime_base.resolve(strict=True)
        resolved_source = source_dir.resolve(strict=True)
        resolved_current = current_link.resolve(strict=True)
        release = release_marker.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if (
        not stat.S_ISDIR(base_metadata.st_mode)
        or stat.S_ISLNK(base_metadata.st_mode)
        or not stat.S_ISLNK(current_metadata.st_mode)
        or not stat.S_ISREG(release_metadata.st_mode)
        or stat.S_ISLNK(release_metadata.st_mode)
        or release_metadata.st_nlink != 1
        or resolved_current != resolved_source
        or resolved_source.parent != resolved_base
    ):
        return False
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", release)
    return bool(match and tuple(map(int, match.groups())) >= (1, 1, 55))


def _desktop_metadata_is_exact(app_path: Path) -> bool:
    info = app_path / "Contents" / "Info.plist"
    try:
        with info.open("rb") as handle:
            plist = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return False
    if plist.get("CFBundleIdentifier") != DESKTOP_BUNDLE_ID:
        return False
    if str(plist.get("CFBundleShortVersionString") or "") not in DESKTOP_REPAIR_VERSIONS:
        return False
    displayed = _command("codesign", "-d", "-r-", "--verbose=4", str(app_path))
    metadata = f"{displayed.stdout}\n{displayed.stderr}"
    return (
        displayed.returncode == 0
        and f"Identifier={DESKTOP_BUNDLE_ID}" in metadata
        and f"TeamIdentifier={DESKTOP_TEAM_ID}" in metadata
        and f"Authority={DESKTOP_AUTHORITY}" in metadata
    )


def _desktop_python_matches_app(app_path: Path, executable: Path) -> bool:
    try:
        resolved = executable.resolve(strict=True)
        python_root = (app_path / "Contents" / "Resources" / "python-runtime").resolve(strict=True)
        resolved.relative_to(python_root)
    except (OSError, ValueError):
        return False
    return resolved.is_file()


def _signature_result(app_path: Path) -> subprocess.CompletedProcess[str]:
    return _command(
        "codesign", "--verify", "--deep", "--strict",
        f"-R={DESKTOP_REQUIREMENT}", str(app_path),
    )


def _seal_failure_is_generated_cache_compatible(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    detail = f"{result.stdout}\n{result.stderr}"
    return bool(re.search(
        r"sealed resource is missing or invalid|unsealed contents present|file added|code or signature have been modified",
        detail,
        flags=re.IGNORECASE,
    ))


def _sealed_resource_paths(app_path: Path) -> set[str]:
    code_resources = app_path / "Contents" / "_CodeSignature" / "CodeResources"
    for directory in (app_path, app_path / "Contents", app_path / "Contents" / "_CodeSignature"):
        try:
            metadata = directory.lstat()
        except OSError as exc:
            raise InstallError("desktop signature directory is unreadable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise InstallError("desktop signature directory is linked")
    try:
        leaf_metadata = code_resources.lstat()
    except OSError as exc:
        raise InstallError("desktop CodeResources is unreadable") from exc
    if (
        stat.S_ISLNK(leaf_metadata.st_mode)
        or not stat.S_ISREG(leaf_metadata.st_mode)
        or leaf_metadata.st_nlink != 1
    ):
        raise InstallError("desktop CodeResources is linked")
    try:
        with code_resources.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        raise InstallError("desktop CodeResources is unreadable")
    if not isinstance(payload, dict):
        raise InstallError("desktop CodeResources is invalid")
    sealed: set[str] = set()
    for key in ("files", "files2"):
        entries = payload.get(key)
        if isinstance(entries, dict):
            sealed.update(name for name in entries if isinstance(name, str))
    return sealed


def _python_cache_candidates(
    app_path: Path,
) -> tuple[list[tuple[Path, int, int, str, list[tuple[Path, int, int]]]], list[Path]]:
    resources = app_path / "Contents" / "Resources"
    for directory in (app_path, app_path / "Contents", resources):
        try:
            metadata = directory.lstat()
        except OSError as exc:
            raise InstallError("desktop resource directory is unreadable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise InstallError("desktop resource directory is linked")
    sealed = _sealed_resource_paths(app_path)
    files: list[tuple[Path, int, int, str, list[tuple[Path, int, int]]]] = []
    cache_dirs: list[Path] = []
    visited = 0

    def visit(candidate: Path) -> None:
        nonlocal visited
        visited += 1
        if visited > 100_000:
            raise InstallError("desktop repair scan limit exceeded")
        metadata = candidate.lstat()
        mode = metadata.st_mode
        if stat.S_ISLNK(mode):
            return
        if stat.S_ISDIR(mode):
            for child in candidate.iterdir():
                visit(child)
            if candidate.name == "__pycache__":
                cache_dirs.append(candidate)
            return
        if not stat.S_ISREG(mode) or candidate.suffix.lower() not in {".pyc", ".pyo"}:
            return
        if "__pycache__" not in candidate.parts:
            return
        if metadata.st_nlink != 1:
            raise InstallError("desktop repair candidate is hard-linked")
        relative = candidate.relative_to(app_path / "Contents").as_posix()
        if relative in sealed:
            raise InstallError("desktop repair candidate is a signed resource")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        parents: list[tuple[Path, int, int]] = []
        parent = candidate.parent
        while True:
            parent_metadata = parent.lstat()
            if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
                raise InstallError("desktop repair candidate parent is linked")
            parents.append((parent, parent_metadata.st_dev, parent_metadata.st_ino))
            if parent == resources:
                break
            if resources not in parent.parents:
                raise InstallError("desktop repair candidate escaped resources")
            parent = parent.parent
        files.append((candidate, metadata.st_dev, metadata.st_ino, digest, parents))

    for name in ("Hephaestus", "python-runtime"):
        root = resources / name
        if not root.exists() or root.is_symlink() or not root.is_dir():
            continue
        visit(root)
    return files, cache_dirs


def _write_desktop_repair_record(
    home: Path,
    *,
    app_version: str,
    status: str,
    digests: list[str],
) -> None:
    record = {
        "schemaVersion": 1,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "bundleIdentifier": DESKTOP_BUNDLE_ID,
        "teamIdentifier": DESKTOP_TEAM_ID,
        "appVersion": app_version,
        "status": status,
        "removedCacheSha256": sorted(digests),
    }
    target = home / ".agentlas" / "desktop-repair" / "bridge-v1.json"
    try:
        _atomic_write(target, json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass


def repair_installed_desktop_python_cache_seal(
    source_dir: Path,
    home: Path,
    *,
    app_candidates: tuple[Path, ...] | None = None,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    if not _verified_runtime_update_context(source_dir):
        return {"status": "not_applicable", "reason": "not_verified_update_context"}
    candidates = app_candidates or (Path("/Applications/Agentlas.app"), home / "Applications" / "Agentlas.app")
    executable = python_executable or Path(sys.executable)
    for app_path in candidates:
        if not app_path.exists() or app_path.is_symlink() or not app_path.is_dir():
            continue
        if not _desktop_metadata_is_exact(app_path):
            continue
        if not _desktop_python_matches_app(app_path, executable):
            return {"status": "blocked", "reason": "not_desktop_python"}
        try:
            with (app_path / "Contents" / "Info.plist").open("rb") as handle:
                app_version = str(plistlib.load(handle).get("CFBundleShortVersionString") or "")
        except (OSError, plistlib.InvalidFileException):
            return {"status": "blocked", "reason": "metadata_unreadable"}
        before = _signature_result(app_path)
        if before.returncode == 0:
            return {"status": "not_needed", "reason": "seal_valid"}
        if not _seal_failure_is_generated_cache_compatible(before):
            return {"status": "blocked", "reason": "non_cache_signature_failure"}
        try:
            files, cache_dirs = _python_cache_candidates(app_path)
            removed = 0
            digests: list[str] = []
            for candidate, expected_dev, expected_ino, digest, parents in files:
                for parent, parent_dev, parent_ino in parents:
                    current_parent = parent.lstat()
                    if (
                        stat.S_ISLNK(current_parent.st_mode)
                        or not stat.S_ISDIR(current_parent.st_mode)
                        or current_parent.st_dev != parent_dev
                        or current_parent.st_ino != parent_ino
                    ):
                        raise InstallError("desktop repair candidate parent changed identity")
                current = candidate.lstat()
                if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                    raise InstallError("desktop repair candidate changed type")
                if current.st_dev != expected_dev or current.st_ino != expected_ino:
                    raise InstallError("desktop repair candidate changed identity")
                parent_fd = os.open(candidate.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    pinned_parent = os.fstat(parent_fd)
                    expected_parent = parents[0]
                    if pinned_parent.st_dev != expected_parent[1] or pinned_parent.st_ino != expected_parent[2]:
                        raise InstallError("desktop repair candidate parent changed before deletion")
                    pinned_file = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
                    if (
                        not stat.S_ISREG(pinned_file.st_mode)
                        or pinned_file.st_nlink != 1
                        or pinned_file.st_dev != expected_dev
                        or pinned_file.st_ino != expected_ino
                    ):
                        raise InstallError("desktop repair candidate changed before deletion")
                    os.unlink(candidate.name, dir_fd=parent_fd)
                finally:
                    os.close(parent_fd)
                removed += 1
                digests.append(digest)
            for directory in sorted(cache_dirs, key=lambda item: len(item.parts), reverse=True):
                try:
                    if not directory.is_symlink() and not any(directory.iterdir()):
                        directory.rmdir()
                except OSError:
                    pass
        except (InstallError, OSError):
            return {"status": "blocked", "reason": "cache_removal_failed"}
        if removed == 0:
            return {"status": "blocked", "reason": "no_generated_cache_found"}
        after = _signature_result(app_path)
        gatekeeper = _command(
            "spctl", "-a", "-t", "execute", "--context", "context:primary-signature", "-vv", str(app_path)
        )
        if after.returncode != 0 or gatekeeper.returncode != 0:
            _write_desktop_repair_record(
                home, app_version=app_version, status="verification_failed", digests=digests
            )
            return {"status": "blocked", "reason": "post_repair_verification_failed", "removed": removed}
        _write_desktop_repair_record(home, app_version=app_version, status="repaired", digests=digests)
        return {"status": "repaired", "removed": removed}
    return {"status": "not_applicable", "reason": "target_not_found"}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(content, encoding="utf-8")
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def _regular_single_link(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise InstallError(f"managed runtime file is unreadable: {path.name}") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise InstallError(f"managed runtime file is not a private regular file: {path.name}")
    return metadata


def _directory_identity(path: Path) -> tuple[int, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise InstallError(f"managed runtime directory is unreadable: {path.name}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise InstallError(f"managed runtime directory is linked: {path.name}")
    return metadata.st_dev, metadata.st_ino


def _file_digest(path: Path) -> str:
    _regular_single_link(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_runtime_version(source_dir: Path) -> str:
    manifest = source_dir / "manifest.json"
    _regular_single_link(manifest)
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError("runtime source manifest is unreadable") from exc
    version = str(payload.get("version") or "") if isinstance(payload, dict) else ""
    if not RUNTIME_VERSION_RE.fullmatch(version):
        raise InstallError("runtime source version is invalid")
    return version


def _validate_runtime_copy(root: Path, source_dir: Path, version: str) -> None:
    _directory_identity(root)
    release = root / "RELEASE"
    _regular_single_link(release)
    if release.read_text(encoding="utf-8").strip() != f"v{version}":
        raise InstallError("managed runtime release does not match verified source")
    for relative in (
        Path("scripts") / "install-memory-hooks.py",
        Path("agentlas_cloud") / "update.py",
    ):
        if _file_digest(root / relative) != _file_digest(source_dir / relative):
            raise InstallError("managed runtime content does not match verified source")
    bin_dir = root / "bin"
    _directory_identity(bin_dir)
    for name in RUNTIME_SHIM_FILES:
        _regular_single_link(bin_dir / name)


def _managed_runtime_copies(
    source_dir: Path,
    home: Path,
) -> tuple[str, list[Path]]:
    source_identity = _directory_identity(source_dir)
    try:
        resolved_source = source_dir.resolve(strict=True)
    except OSError as exc:
        raise InstallError("runtime source cannot be resolved") from exc
    if _directory_identity(resolved_source) != source_identity:
        raise InstallError("runtime source changed identity")
    if not any(parent.name.startswith("hephaestus-update-") for parent in resolved_source.parents):
        raise InstallError("not a verified runtime update extraction")

    version = _source_runtime_version(resolved_source)
    configured_base = Path(
        os.environ.get("HEPHAESTUS_RUNTIME_BASE")
        or home / ".agentlas" / "runtime"
    ).expanduser()
    if not configured_base.is_absolute():
        raise InstallError("managed runtime base must be absolute")
    base_identity = _directory_identity(configured_base)
    try:
        runtime_base = configured_base.resolve(strict=True)
    except OSError as exc:
        raise InstallError("managed runtime base cannot be resolved") from exc
    if _directory_identity(runtime_base) != base_identity:
        raise InstallError("managed runtime base changed identity")

    target = runtime_base / version
    if target.parent != runtime_base:
        raise InstallError("managed runtime target escaped its base")
    _validate_runtime_copy(target, resolved_source, version)

    current = runtime_base / "current"
    try:
        current_metadata = current.lstat()
    except OSError as exc:
        raise InstallError("managed runtime current pointer is unreadable") from exc
    copies = [target]
    if stat.S_ISLNK(current_metadata.st_mode):
        if current_metadata.st_nlink != 1:
            raise InstallError("managed runtime current pointer is not private")
        try:
            resolved_current = current.resolve(strict=True)
        except OSError as exc:
            raise InstallError("managed runtime current pointer is broken") from exc
        if resolved_current != target.resolve(strict=True):
            raise InstallError("managed runtime current pointer does not select the verified release")
    elif stat.S_ISDIR(current_metadata.st_mode):
        # Windows and restricted POSIX hosts can fall back to a private copy
        # when creating a directory symlink is unavailable. Repair both the
        # active current copy and the versioned target. Active-first ordering
        # keeps the selected runtime safe even if a later filesystem write
        # fails after all preflight validation has passed.
        _validate_runtime_copy(current, resolved_source, version)
        copies = [current, target]
    else:
        raise InstallError("managed runtime current pointer has an unsafe type")
    return version, copies


def _shim_payloads(
    executable: Path,
    cache_prefix: Path,
) -> dict[str, tuple[str, int]]:
    executable_text = str(executable)
    if any(character in executable_text for character in ("\r", "\n", "\x00")):
        raise InstallError("Python executable path is unsafe")
    if os.name == "nt" and any(character in executable_text for character in ('"', "%")):
        raise InstallError("Python executable path cannot be represented safely")
    shell_executable = shlex.quote(executable_text)
    shell_cache_prefix = shlex.quote(str(cache_prefix))
    if os.name == "nt":
        cmd_cache = f'set "PYTHONPYCACHEPREFIX={cache_prefix}"\r\n'
    else:
        cmd_cache = (
            'if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\\Agentlas\\PythonCache") '
            'else (set "PYTHONPYCACHEPREFIX=%TEMP%\\Agentlas-PythonCache")\r\n'
        )
    python_cmd = (
        '@echo off\r\n'
        'setlocal\r\n'
        'set "PYTHONDONTWRITEBYTECODE=1"\r\n'
        f"{cmd_cache}"
        f'"{executable_text}" %*\r\n'
        'exit /b %ERRORLEVEL%\r\n'
    )
    hephaestus_cmd = (
        '@echo off\r\n'
        'setlocal\r\n'
        'set "PYTHONUTF8=1"\r\n'
        'set "PYTHONIOENCODING=utf-8"\r\n'
        'set "PYTHONDONTWRITEBYTECODE=1"\r\n'
        f"{cmd_cache}"
        'set "PYTHONPATH=%~dp0..;%PYTHONPATH%"\r\n'
        'if defined HEPHAESTUS_PYTHON goto use_env_python\r\n'
        'if exist "%~dp0python3.cmd" goto use_python3_shim\r\n'
        'where py >nul 2>nul\r\n'
        'if not errorlevel 1 goto use_py_launcher\r\n'
        'where python >nul 2>nul\r\n'
        'if not errorlevel 1 goto use_path_python\r\n'
        'echo hephaestus: Python 3.9+ not found. Install Python from python.org and rerun hephaestus doctor. 1>&2\r\n'
        'exit /b 127\r\n'
        '\r\n'
        ':use_env_python\r\n'
        '"%HEPHAESTUS_PYTHON%" -m agentlas_cloud %*\r\n'
        'exit /b %ERRORLEVEL%\r\n'
        '\r\n'
        ':use_python3_shim\r\n'
        'call "%~dp0python3.cmd" -m agentlas_cloud %*\r\n'
        'exit /b %ERRORLEVEL%\r\n'
        '\r\n'
        ':use_py_launcher\r\n'
        'py -3 -m agentlas_cloud %*\r\n'
        'exit /b %ERRORLEVEL%\r\n'
        '\r\n'
        ':use_path_python\r\n'
        'python -m agentlas_cloud %*\r\n'
        'exit /b %ERRORLEVEL%\r\n'
    )
    env_cmd = (
        '@echo off\r\n'
        'set "PYTHONUTF8=1"\r\n'
        'set "PYTHONIOENCODING=utf-8"\r\n'
        'set "PYTHONDONTWRITEBYTECODE=1"\r\n'
        f"{cmd_cache}"
        'set "PYTHONPATH=%~dp0..;%PYTHONPATH%"\r\n'
    )
    return {
        "python3": (
            '#!/usr/bin/env bash\n'
            'export PYTHONDONTWRITEBYTECODE=1\n'
            f"export PYTHONPYCACHEPREFIX={shell_cache_prefix}\n"
            f"exec {shell_executable} \"$@\"\n",
            0o755,
        ),
        "python3.cmd": (python_cmd, 0o644),
        "hephaestus.cmd": (hephaestus_cmd, 0o644),
        "hephaestus-env.cmd": (env_cmd, 0o644),
    }


def _atomic_replace_runtime_files(
    bin_dir: Path,
    payloads: dict[str, tuple[str, int]],
) -> None:
    parent_dev, parent_ino = _directory_identity(bin_dir)
    expected: dict[str, tuple[int, int]] = {}
    for name in payloads:
        metadata = _regular_single_link(bin_dir / name)
        expected[name] = (metadata.st_dev, metadata.st_ino)

    prepared: dict[str, Path] = {}
    try:
        for name, (content, mode) in payloads.items():
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{name}.bridge-",
                suffix=".tmp",
                dir=bin_dir,
                text=False,
            )
            temporary = Path(temporary_name)
            prepared[name] = temporary
            try:
                encoded = content.encode("utf-8")
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, mode)
                temporary_metadata = temporary.lstat()
                if (
                    not stat.S_ISREG(temporary_metadata.st_mode)
                    or temporary_metadata.st_nlink != 1
                ):
                    raise InstallError("atomic shim replacement created an unsafe temporary file")
            except Exception:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise

        current_parent = bin_dir.lstat()
        if (
            stat.S_ISLNK(current_parent.st_mode)
            or not stat.S_ISDIR(current_parent.st_mode)
            or current_parent.st_dev != parent_dev
            or current_parent.st_ino != parent_ino
        ):
            raise InstallError("managed runtime bin directory changed identity")
        for name, identity in expected.items():
            current = _regular_single_link(bin_dir / name)
            if (current.st_dev, current.st_ino) != identity:
                raise InstallError("managed runtime shim changed identity")

        for name in payloads:
            os.replace(prepared[name], bin_dir / name)
            prepared.pop(name)
        try:
            directory_fd = os.open(bin_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Windows and some filesystems do not permit fsync on directories;
            # each file replacement above is still atomic.
            pass
    finally:
        for temporary in prepared.values():
            try:
                temporary.unlink()
            except OSError:
                pass


def repair_managed_runtime_python_shims(
    source_dir: Path,
    home: Path,
) -> dict[str, Any]:
    try:
        version, runtime_copies = _managed_runtime_copies(source_dir, home)
        executable = Path(sys.executable).resolve(strict=True)
        if not executable.is_file():
            raise InstallError("Python executable is not a regular file")
        cache_prefix = _safe_python_cache_prefix(str(executable), home)
        payloads = _shim_payloads(executable, cache_prefix)
    except (InstallError, OSError, ValueError):
        return {"status": "not_applicable", "reason": "unverified_runtime_update_context"}
    try:
        for runtime_root in runtime_copies:
            _atomic_replace_runtime_files(runtime_root / "bin", payloads)
            for name, (content, mode) in payloads.items():
                path = runtime_root / "bin" / name
                metadata = _regular_single_link(path)
                if path.read_bytes() != content.encode("utf-8"):
                    raise InstallError("managed runtime shim verification failed")
                if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != mode:
                    raise InstallError("managed runtime shim mode verification failed")
        return {
            "status": "repaired",
            "runtimeVersion": version,
            "runtimeCopies": len(runtime_copies),
            "shimCount": len(payloads) * len(runtime_copies),
        }
    except (InstallError, OSError, ValueError):
        return {"status": "blocked", "reason": "shim_repair_failed"}


def run_host_plugin_transition_bridge(source_dir: Path, home: Path) -> dict[str, Any]:
    """Run the target release's bounded, non-recursive v1.2.32 transition."""

    try:
        version, runtime_copies = _managed_runtime_copies(source_dir, home)
        runtime_root = runtime_copies[-1]
        if not (runtime_root / "host_adapters").is_dir():
            return {
                "schemaVersion": "agentlas.legacy-host-plugin-transition.v1",
                "status": "not_applicable",
                "reason": "host_adapter_bundle_missing",
                "release": f"v{version}",
                "bounded": True,
                "vendorCliInvoked": False,
            }
        return reconcile_legacy_host_plugin_transition(
            source_dir,
            runtime_root,
            f"v{version}",
            home=home,
        )
    except (InstallError, OSError, ValueError) as exc:
        return {
            "schemaVersion": "agentlas.legacy-host-plugin-transition.v1",
            "status": "not_applicable",
            "reason": "unverified_runtime_update_context",
            "error": str(exc),
            "bounded": True,
            "vendorCliInvoked": False,
        }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"refusing to overwrite invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise InstallError(f"refusing to overwrite non-object JSON: {path}")
    return payload


def _copy_owned(source: Path, target: Path) -> None:
    if not source.is_file():
        raise InstallError(f"missing hook asset: {source}")
    _atomic_write(target, source.read_text(encoding="utf-8"))


def install_antigravity(source_dir: Path, home: Path) -> list[str]:
    source = source_dir / "antigravity" / "hooks" / "agentlas-memory.json"
    incoming = _read_json(source)
    if set(incoming) != {"agentlas-memory"}:
        raise InstallError(f"invalid Agentlas Antigravity hook asset: {source}")
    target = home / ".gemini" / "config" / "hooks.json"
    merged = _read_json(target)
    merged["agentlas-memory"] = incoming["agentlas-memory"]
    _atomic_write(target, json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return [str(target)]


def _managed_block(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    start = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < start:
        raise InstallError(f"invalid managed memory rule asset: {source}")
    return text[start : end + len(END_MARKER)].strip()


def _merge_markdown_block(target: Path, block: str) -> None:
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    begin_count = existing.count(BEGIN_MARKER)
    end_count = existing.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise InstallError(f"refusing to repair ambiguous managed markers: {target}")
    if begin_count == 1:
        existing = re.sub(
            re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER),
            "",
            existing,
            count=1,
            flags=re.DOTALL,
        )
    prefix = existing.rstrip()
    content = f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"
    _atomic_write(target, content)


def install_grok(source_dir: Path, home: Path) -> list[str]:
    hook_source = source_dir / "grok" / "hooks" / "agentlas-memory.json"
    hook_target = home / ".grok" / "hooks" / "agentlas-memory.json"
    _copy_owned(hook_source, hook_target)
    rule_source = source_dir / "grok" / "agentlas-memory-rule.md"
    rule_target = home / ".grok" / "AGENTS.md"
    _merge_markdown_block(rule_target, _managed_block(rule_source))
    return [str(hook_target), str(rule_target)]


def install_opencode(source_dir: Path, home: Path) -> list[str]:
    source = source_dir / "opencode" / "plugins" / "agentlas-memory.js"
    target = home / ".config" / "opencode" / "plugins" / "agentlas-memory.js"
    _copy_owned(source, target)
    return [str(target)]


def _detected_hosts(home: Path) -> list[str]:
    hosts: list[str] = []
    for spec in MEMORY_HOOK_HOSTS:
        if not spec.installable:
            continue
        if (
            any(os.environ.get(name) for name in spec.detect_env)
            or any(shutil.which(binary) for binary in spec.detect_binaries)
            or any((home / relative).is_dir() for relative in spec.detect_dirs)
        ):
            hosts.append(spec.id)
    return hosts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install merge-safe Agentlas host memory hooks")
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument(
        "--hosts",
        default="auto",
        help=f"auto, all, or a comma-separated subset of {','.join(SUPPORTED_HOSTS)}",
    )
    args = parser.parse_args(argv)
    source_dir = args.source_dir.expanduser().resolve()
    home = args.home.expanduser().resolve()
    if args.hosts == "auto":
        hosts = _detected_hosts(home)
    elif args.hosts == "all":
        hosts = list(SUPPORTED_HOSTS)
    else:
        hosts = [item.strip() for item in args.hosts.split(",") if item.strip()]
        unknown = sorted(set(hosts) - set(SUPPORTED_HOSTS))
        if unknown:
            parser.error(f"unsupported hosts: {', '.join(unknown)}")
    # Derived from the shared host table: a host marked installable there
    # without an install_<host>() here fails loudly at startup instead of
    # silently missing from `--hosts all`.
    installers = {host: globals()[f"install_{host}"] for host in SUPPORTED_HOSTS}
    installed: dict[str, Any] = {}
    errors: dict[str, str] = {}
    runtime_shim_repair = repair_managed_runtime_python_shims(source_dir, home)
    host_plugin_transition = run_host_plugin_transition_bridge(source_dir, home)
    # v1.2.32's parent updater preserves only the `installed` and `errors`
    # objects from this subprocess. Keep the typed receipt under `installed` as
    # a compatibility envelope, and also expose it directly to newer callers.
    installed["host_plugin_transition"] = host_plugin_transition
    if host_plugin_transition.get("status") == "blocked":
        errors["host_plugin_transition"] = str(
            host_plugin_transition.get("reason") or "transition_blocked"
        )
    try:
        # v1.1.56 callers terminate this installer after 30 seconds. Run the
        # bounded v0.8.65/v0.8.66 updater recovery first so an unrelated older
        # duplicate app cannot consume its delivery window.
        desktop_updater_cleanup = run_desktop_updater_cleanup_bridge(source_dir, home)
    except Exception:
        # Desktop recovery must never roll back an otherwise verified Agentlas
        # OS update. Keep the failure typed and retryable on the next launch.
        desktop_updater_cleanup = {"status": "blocked", "reason": "bridge_failed"}
    desktop_repair = run_desktop_repair_bridge(source_dir, home)
    for host in hosts:
        try:
            installed[host] = installers[host](source_dir, home)
        except (InstallError, OSError) as exc:
            errors[host] = str(exc)
    print(
        json.dumps(
            {
                "status": "pass" if not errors else "fail",
                "installed": installed,
                "errors": errors,
                "runtime_shim_repair": runtime_shim_repair,
                "host_plugin_transition": host_plugin_transition,
                "desktop_repair": desktop_repair,
                "desktop_updater_cleanup": desktop_updater_cleanup,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
