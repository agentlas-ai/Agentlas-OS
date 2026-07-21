"""Narrow managed-runtime repair for the Desktop Python-cache seal mutation.

This module intentionally lives inside ``agentlas_cloud`` because Desktop
v0.8.58/v0.8.59 ship the v1.1.50 updater, which copies that package into the
managed runtime but does not preserve new root-level bridge files.  The first
repair still runs from the freshly extracted, digest-verified release script;
this copy makes later app launches retryable without an installer.
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
BRIDGE_PAYLOAD = {
    "schemaVersion": 1,
    "purpose": "repair-agentlas-desktop-python-cache-seal",
    "bundleIdentifier": DESKTOP_BUNDLE_ID,
    "teamIdentifier": DESKTOP_TEAM_ID,
    "versions": sorted(DESKTOP_REPAIR_VERSIONS),
}


class DesktopRepairError(RuntimeError):
    pass


def _command(command: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [command, *args], capture_output=True, text=True, timeout=15, check=False
    )


def _exact_marker(path: Path) -> bool:
    try:
        metadata = path.lstat()
        return (
            stat.S_ISREG(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and metadata.st_nlink == 1
            and json.loads(path.read_text(encoding="utf-8")) == BRIDGE_PAYLOAD
        )
    except (OSError, json.JSONDecodeError):
        return False


def _verified_runtime_update_context(source_dir: Path) -> bool:
    """Require a verified extracted release or selected v1.1.56+ runtime."""

    if sys.platform != "darwin" or not os.environ.get("HEPHAESTUS_RUNTIME_ROOT"):
        return False
    root_marker = source_dir / "desktop-update-bridge-v1.json"
    if _exact_marker(root_marker) and any(
        parent.name.startswith("hephaestus-update-") for parent in source_dir.parents
    ):
        return True
    runtime_base = Path(
        os.environ.get("HEPHAESTUS_RUNTIME_BASE")
        or Path.home() / ".agentlas" / "runtime"
    )
    current_link = runtime_base / "current"
    release_marker = source_dir / "RELEASE"
    module_path = Path(__file__)
    package_marker = source_dir / "agentlas_cloud" / "desktop-update-bridge-v1.json"
    try:
        base_metadata = runtime_base.lstat()
        source_metadata = source_dir.lstat()
        current_metadata = current_link.lstat()
        release_metadata = release_marker.lstat()
        module_metadata = module_path.lstat()
        resolved_base = runtime_base.resolve(strict=True)
        resolved_source = source_dir.resolve(strict=True)
        resolved_current = current_link.resolve(strict=True)
        resolved_module = module_path.resolve(strict=True)
        release = release_marker.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if (
        not stat.S_ISDIR(base_metadata.st_mode)
        or stat.S_ISLNK(base_metadata.st_mode)
        or not stat.S_ISDIR(source_metadata.st_mode)
        or stat.S_ISLNK(source_metadata.st_mode)
        or not stat.S_ISLNK(current_metadata.st_mode)
        or not stat.S_ISREG(release_metadata.st_mode)
        or stat.S_ISLNK(release_metadata.st_mode)
        or release_metadata.st_nlink != 1
        or not stat.S_ISREG(module_metadata.st_mode)
        or stat.S_ISLNK(module_metadata.st_mode)
        or module_metadata.st_nlink != 1
        or resolved_current != resolved_source
        or resolved_source.parent != resolved_base
        or resolved_module.parent.parent != resolved_source
        or not _exact_marker(package_marker)
    ):
        return False
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", release)
    return bool(match and tuple(map(int, match.groups())) >= (1, 1, 56))


def _desktop_metadata_is_exact(app_path: Path) -> bool:
    info = app_path / "Contents" / "Info.plist"
    try:
        with info.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return False
    if payload.get("CFBundleIdentifier") != DESKTOP_BUNDLE_ID:
        return False
    if str(payload.get("CFBundleShortVersionString") or "") not in DESKTOP_REPAIR_VERSIONS:
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


def _seal_failure_is_generated_cache_compatible(
    result: subprocess.CompletedProcess[str],
) -> bool:
    if result.returncode == 0:
        return False
    detail = f"{result.stdout}\n{result.stderr}"
    return bool(re.search(
        r"sealed resource is missing or invalid|unsealed contents present|file added|code or signature have been modified",
        detail,
        flags=re.IGNORECASE,
    ))


def _sealed_resource_paths(app_path: Path) -> set[str]:
    signature_root = app_path / "Contents" / "_CodeSignature"
    code_resources = signature_root / "CodeResources"
    for directory in (app_path, app_path / "Contents", signature_root):
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DesktopRepairError("desktop signature directory is linked")
    leaf_metadata = code_resources.lstat()
    if (
        stat.S_ISLNK(leaf_metadata.st_mode)
        or not stat.S_ISREG(leaf_metadata.st_mode)
        or leaf_metadata.st_nlink != 1
    ):
        raise DesktopRepairError("desktop CodeResources is linked")
    with code_resources.open("rb") as handle:
        payload = plistlib.load(handle)
    if not isinstance(payload, dict):
        raise DesktopRepairError("desktop CodeResources is invalid")
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
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DesktopRepairError("desktop resource directory is linked")
    sealed = _sealed_resource_paths(app_path)
    files: list[tuple[Path, int, int, str, list[tuple[Path, int, int]]]] = []
    cache_dirs: list[Path] = []
    visited = 0

    def visit(candidate: Path) -> None:
        nonlocal visited
        visited += 1
        if visited > 100_000:
            raise DesktopRepairError("desktop repair scan limit exceeded")
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            return
        if stat.S_ISDIR(metadata.st_mode):
            for child in candidate.iterdir():
                visit(child)
            if candidate.name == "__pycache__":
                cache_dirs.append(candidate)
            return
        if not stat.S_ISREG(metadata.st_mode) or candidate.suffix.lower() not in {".pyc", ".pyo"}:
            return
        if "__pycache__" not in candidate.parts:
            return
        if metadata.st_nlink != 1:
            raise DesktopRepairError("desktop repair candidate is hard-linked")
        relative = candidate.relative_to(app_path / "Contents").as_posix()
        if relative in sealed:
            raise DesktopRepairError("desktop repair candidate is a signed resource")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        parents: list[tuple[Path, int, int]] = []
        parent = candidate.parent
        while True:
            parent_metadata = parent.lstat()
            if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
                raise DesktopRepairError("desktop repair candidate parent is linked")
            parents.append((parent, parent_metadata.st_dev, parent_metadata.st_ino))
            if parent == resources:
                break
            if resources not in parent.parents:
                raise DesktopRepairError("desktop repair candidate escaped resources")
            parent = parent.parent
        files.append((candidate, metadata.st_dev, metadata.st_ino, digest, parents))

    for name in ("Hephaestus", "python-runtime"):
        root = resources / name
        if not root.exists() or root.is_symlink() or not root.is_dir():
            continue
        visit(root)
    return files, cache_dirs


def _write_record(home: Path, *, app_version: str, status_value: str, digests: list[str]) -> None:
    target = home / ".agentlas" / "desktop-repair" / "bridge-v1.json"
    payload = {
        "schemaVersion": 1,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "bundleIdentifier": DESKTOP_BUNDLE_ID,
        "teamIdentifier": DESKTOP_TEAM_ID,
        "appVersion": app_version,
        "status": status_value,
        "removedCacheSha256": sorted(digests),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        pass


def repair_installed_desktop_python_cache_seal(
    source_dir: Path,
    home: Path | None = None,
    *,
    app_candidates: tuple[Path, ...] | None = None,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    """Retry the known cache-only repair from an exact managed runtime."""

    source = source_dir.expanduser().resolve()
    home_dir = (home or Path.home()).expanduser().resolve()
    if not _verified_runtime_update_context(source):
        return {"status": "not_applicable", "reason": "not_verified_runtime_update"}
    candidates = app_candidates or (
        Path("/Applications/Agentlas.app"),
        home_dir / "Applications" / "Agentlas.app",
    )
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
                        raise DesktopRepairError("desktop repair parent changed identity")
                current = candidate.lstat()
                if (
                    not stat.S_ISREG(current.st_mode)
                    or current.st_nlink != 1
                    or current.st_dev != expected_dev
                    or current.st_ino != expected_ino
                ):
                    raise DesktopRepairError("desktop repair candidate changed identity")
                parent_fd = os.open(candidate.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    pinned_parent = os.fstat(parent_fd)
                    expected_parent = parents[0]
                    if pinned_parent.st_dev != expected_parent[1] or pinned_parent.st_ino != expected_parent[2]:
                        raise DesktopRepairError("desktop repair parent changed before deletion")
                    pinned_file = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
                    if (
                        not stat.S_ISREG(pinned_file.st_mode)
                        or pinned_file.st_nlink != 1
                        or pinned_file.st_dev != expected_dev
                        or pinned_file.st_ino != expected_ino
                    ):
                        raise DesktopRepairError("desktop repair candidate changed before deletion")
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
        except (DesktopRepairError, OSError, plistlib.InvalidFileException):
            return {"status": "blocked", "reason": "cache_removal_failed"}
        if removed == 0:
            return {"status": "blocked", "reason": "no_generated_cache_found"}
        after = _signature_result(app_path)
        gatekeeper = _command(
            "spctl", "-a", "-t", "execute", "--context", "context:primary-signature", "-vv", str(app_path)
        )
        if after.returncode != 0 or gatekeeper.returncode != 0:
            _write_record(home_dir, app_version=app_version, status_value="verification_failed", digests=digests)
            return {"status": "blocked", "reason": "post_repair_verification_failed", "removed": removed}
        _write_record(home_dir, app_version=app_version, status_value="repaired", digests=digests)
        return {"status": "repaired", "removed": removed}
    return {"status": "not_applicable", "reason": "target_not_found"}
