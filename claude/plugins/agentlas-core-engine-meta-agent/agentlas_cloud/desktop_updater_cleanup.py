"""Narrow recovery bridge for the Desktop v0.8.65/v0.8.66 updater cache.

Those Desktop builds can pause before reaching their update feed when their
legacy cleanup walks through ``app.asar`` as if it were a directory.  Agentlas
OS updates independently, so a verified runtime release can atomically move
only the exact stale ``ShipIt/update.*`` directory named by that failure log.

The bridge deliberately does not touch Application Support, the install
journal, recovery copies, pending downloads, ShipIt state, or the installed
application.  The old Desktop Retry path owns the remaining state transition.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import secrets
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DESKTOP_VERSIONS = {"0.8.65", "0.8.66"}
STALE_PAYLOAD_VERSIONS = {"0.8.65", "0.8.66", "0.9.2"}
DESKTOP_BUNDLE_ID = "com.agentlas.desktop"
DESKTOP_TEAM_ID = "F469CGM7T5"
DESKTOP_AUTHORITY = "Developer ID Application: Jeongmin Kim (F469CGM7T5)"
DESKTOP_REQUIREMENT = (
    'identifier "com.agentlas.desktop" and anchor apple generic and '
    'certificate leaf[field.1.2.840.113635.100.6.1.13] exists and '
    'certificate 1[field.1.2.840.113635.100.6.2.6] exists and '
    'certificate leaf[subject.OU] = "F469CGM7T5"'
)
MARKER_NAME = "desktop-updater-cleanup-bridge-v1.json"
BRIDGE_PAYLOAD = {
    "schemaVersion": 1,
    "purpose": "repair-agentlas-desktop-stale-updater-cache",
    "bundleIdentifier": DESKTOP_BUNDLE_ID,
    "teamIdentifier": DESKTOP_TEAM_ID,
    "versions": sorted(DESKTOP_VERSIONS),
}
MAX_LOG_BYTES = 4 * 1024 * 1024
COMMAND_TIMEOUT_SECONDS = 4
RECOVERY_DEADLINE_SECONDS = 20
MAX_SHIPIT_ENTRIES = 4_096
LOCK_NAME = ".agentlas-recovery.lock"
QUARANTINE_PREFIX = ".agentlas-recovery-"
QUARANTINE_MARKER = "recovery.json"
UPDATE_NAME_PATTERN = re.compile(r"update\.[A-Za-z0-9_-]{1,96}")
BLOCKED_PATH_PATTERN = re.compile(
    r"\[updater\] failed to clear stale ShipIt state Error: ENOTDIR: not a directory, chmod "
    r"'([^'\r\n]+)/Agentlas\.app/Contents/Resources/app\.asar/dist'"
)
RECOVERY_DIALOG = (
    'display dialog "Stale update files were safely set aside. Press Retry. '
    'If the same message remains, quit and reopen Agentlas. Your work and data '
    'were not changed.\\n\\n멈춘 업데이트 파일을 안전하게 격리했습니다. ‘다시 시도’를 누르세요. '
    '같은 문구가 남으면 Agentlas를 종료한 뒤 다시 여세요. 작업과 데이터는 그대로입니다." '
    'with title "Agentlas Update Recovery" buttons {"OK"} default button "OK" '
    'with icon note giving up after 45'
)
PARTIAL_RECOVERY_DIALOG = (
    'display dialog "Update recovery needs one more Agentlas restart. Quit and '
    'reopen Agentlas. Your work and data were not changed.\\n\\n업데이트 복구를 '
    '계속하려면 Agentlas를 한 번 더 종료한 뒤 다시 여세요. 작업과 데이터는 그대로입니다." '
    'with title "Agentlas Update Recovery" buttons {"OK"} default button "OK" '
    'with icon note giving up after 45'
)


class DesktopUpdaterCleanupError(RuntimeError):
    pass


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _command(command: str, *args: str, deadline: float) -> subprocess.CompletedProcess[str]:
    remaining = _remaining(deadline)
    if remaining <= 0:
        return subprocess.CompletedProcess([command, *args], 124, "", "recovery deadline exceeded")
    try:
        return subprocess.run(
            [command, *args],
            capture_output=True,
            text=True,
            timeout=max(0.05, min(COMMAND_TIMEOUT_SECONDS, remaining)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            [command, *args],
            124,
            "",
            f"verification unavailable: {type(exc).__name__}",
        )


def _read_exact_json(path: Path) -> dict[str, Any] | None:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
        ):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            pinned = os.fstat(fd)
            if (
                pinned.st_dev != metadata.st_dev
                or pinned.st_ino != metadata.st_ino
                or pinned.st_uid != metadata.st_uid
                or pinned.st_nlink != 1
                or pinned.st_size > 64 * 1024
            ):
                return None
            payload = json.loads(os.read(fd, pinned.st_size + 1).decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        finally:
            os.close(fd)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _exact_marker(path: Path) -> bool:
    return _read_exact_json(path) == BRIDGE_PAYLOAD


def _verified_runtime_update_context(source_dir: Path) -> bool:
    if sys.platform != "darwin" or not os.environ.get("HEPHAESTUS_RUNTIME_ROOT"):
        return False
    module_path = Path(__file__)
    package_marker = source_dir / "agentlas_cloud" / MARKER_NAME
    try:
        source_metadata = source_dir.lstat()
        module_metadata = module_path.lstat()
        resolved_source = source_dir.resolve(strict=True)
        resolved_module = module_path.resolve(strict=True)
    except OSError:
        return False
    owner = os.getuid()
    if (
        not stat.S_ISDIR(source_metadata.st_mode)
        or stat.S_ISLNK(source_metadata.st_mode)
        or source_metadata.st_uid != owner
        or not stat.S_ISREG(module_metadata.st_mode)
        or stat.S_ISLNK(module_metadata.st_mode)
        or module_metadata.st_uid != owner
        or module_metadata.st_nlink != 1
        or resolved_module.parent.parent != resolved_source
        or not _exact_marker(package_marker)
    ):
        return False

    # First execution comes from the digest-verified release extraction.  The
    # already-shipped updater checks the archive size and SHA-256 first.
    if any(parent.name.startswith("hephaestus-update-") for parent in resolved_source.parents):
        manifest_payload = _read_exact_json(source_dir / "manifest.json")
        release = str((manifest_payload or {}).get("version") or "")
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", release)
        return bool(match and tuple(map(int, match.groups())) >= (1, 1, 57))

    # Later retries must come from the immutable version selected by the
    # managed ``current`` symlink, not from a copied marker.
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
        resolved_current = current_link.resolve(strict=True)
        release = release_marker.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if (
        not stat.S_ISDIR(base_metadata.st_mode)
        or stat.S_ISLNK(base_metadata.st_mode)
        or base_metadata.st_uid != owner
        or not stat.S_ISLNK(current_metadata.st_mode)
        or not stat.S_ISREG(release_metadata.st_mode)
        or stat.S_ISLNK(release_metadata.st_mode)
        or release_metadata.st_uid != owner
        or release_metadata.st_nlink != 1
        or resolved_current != resolved_source
        or resolved_source.parent != resolved_base
    ):
        return False
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", release)
    return bool(match and tuple(map(int, match.groups())) >= (1, 1, 57))


def _displayed_metadata(app_path: Path, deadline: float) -> str | None:
    displayed = _command(
        "/usr/bin/codesign", "-d", "-r-", "--verbose=4", str(app_path), deadline=deadline
    )
    if displayed.returncode != 0:
        return None
    return f"{displayed.stdout}\n{displayed.stderr}"


def _bundle_version(app_path: Path, allowed_versions: set[str], deadline: float) -> str | None:
    info = app_path / "Contents" / "Info.plist"
    try:
        app_metadata_before = app_path.lstat()
        with info.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return None
    version = str(payload.get("CFBundleShortVersionString") or "")
    if payload.get("CFBundleIdentifier") != DESKTOP_BUNDLE_ID or version not in allowed_versions:
        return None
    metadata = _displayed_metadata(app_path, deadline)
    if metadata is None or not all(
        item in metadata
        for item in (
            f"Identifier={DESKTOP_BUNDLE_ID}",
            f"TeamIdentifier={DESKTOP_TEAM_ID}",
            f"Authority={DESKTOP_AUTHORITY}",
        )
    ):
        return None
    signature = _command(
        "/usr/bin/codesign",
        "--verify",
        "--deep",
        "--strict",
        f"-R={DESKTOP_REQUIREMENT}",
        str(app_path),
        deadline=deadline,
    )
    gatekeeper = _command(
        "/usr/sbin/spctl",
        "-a",
        "-t",
        "execute",
        "--context",
        "context:primary-signature",
        "-vv",
        str(app_path),
        deadline=deadline,
    )
    try:
        app_metadata_after = app_path.lstat()
    except OSError:
        return None
    same_app = (
        app_metadata_before.st_dev == app_metadata_after.st_dev
        and app_metadata_before.st_ino == app_metadata_after.st_ino
        and app_metadata_after.st_uid == os.getuid()
        and stat.S_ISDIR(app_metadata_after.st_mode)
        and not stat.S_ISLNK(app_metadata_after.st_mode)
    )
    return version if same_app and signature.returncode == 0 and gatekeeper.returncode == 0 else None


def _desktop_python_matches_app(app_path: Path, executable: Path) -> bool:
    try:
        resolved = executable.resolve(strict=True)
        python_root = (app_path / "Contents" / "Resources" / "python-runtime").resolve(strict=True)
        resolved.relative_to(python_root)
    except (OSError, ValueError):
        return False
    return resolved.is_file()


def _validate_directory(path: Path, *, owner: int, device: int | None = None) -> os.stat_result:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != owner
        or metadata.st_mode & 0o022
        or (device is not None and metadata.st_dev != device)
    ):
        raise DesktopUpdaterCleanupError("cache directory boundary is not private")
    return metadata


def _validate_cache_root(home: Path, root: Path, owner: int) -> os.stat_result:
    try:
        relative = root.relative_to(home)
    except ValueError as exc:
        raise DesktopUpdaterCleanupError("cache root escaped home") from exc
    if relative.parts[:2] != ("Library", "Caches"):
        raise DesktopUpdaterCleanupError("cache root is outside Library/Caches")
    home_metadata = _validate_directory(home, owner=owner)
    current = home
    for part in relative.parts:
        current = current / part
        metadata = _validate_directory(current, owner=owner, device=home_metadata.st_dev)
    return metadata


def _read_regular_text(path: Path, *, owner: int, limit: int) -> str | None:
    try:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != owner
        ):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            pinned = os.fstat(fd)
            if (
                pinned.st_dev != metadata.st_dev
                or pinned.st_ino != metadata.st_ino
                or pinned.st_uid != owner
            ):
                return None
            start = max(0, pinned.st_size - limit)
            os.lseek(fd, start, os.SEEK_SET)
            return os.read(fd, limit).decode("utf-8", errors="replace")
        finally:
            os.close(fd)
    except OSError:
        return None


def _exact_logged_updates(home: Path, shipit: Path, owner: int, deadline: float) -> list[str]:
    text = _read_regular_text(
        home / "Library" / "Logs" / "Agentlas" / "main.log",
        owner=owner,
        limit=MAX_LOG_BYTES,
    )
    if text is None:
        return []
    result: list[str] = []
    for raw in reversed(BLOCKED_PATH_PATTERN.findall(text)):
        if _remaining(deadline) <= 0:
            raise DesktopUpdaterCleanupError("recovery deadline exceeded")
        candidate = Path(raw)
        if (
            candidate.parent == shipit
            and UPDATE_NAME_PATTERN.fullmatch(candidate.name)
            and str(candidate) == str(shipit / candidate.name)
            and candidate.name not in result
        ):
            result.append(candidate.name)
    return result


def _direct_real_updates(
    shipit: Path,
    root_metadata: os.stat_result,
    deadline: float,
) -> list[str]:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(shipit, flags)
    try:
        pinned = os.fstat(fd)
        if pinned.st_dev != root_metadata.st_dev or pinned.st_ino != root_metadata.st_ino:
            raise DesktopUpdaterCleanupError("ShipIt root changed during enumeration")
        result: list[str] = []
        for index, entry in enumerate(os.scandir(fd), start=1):
            if index > MAX_SHIPIT_ENTRIES:
                raise DesktopUpdaterCleanupError("ShipIt entry limit exceeded")
            if _remaining(deadline) <= 0:
                raise DesktopUpdaterCleanupError("recovery deadline exceeded")
            name = entry.name
            if not UPDATE_NAME_PATTERN.fullmatch(name):
                continue
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                result.append(name)
        return sorted(result)
    finally:
        os.close(fd)


def _staged_payload_is_exact(
    shipit: Path,
    update_name: str,
    expected: os.stat_result,
    deadline: float,
) -> bool:
    staged_app = shipit / update_name / "Agentlas.app"
    asar = staged_app / "Contents" / "Resources" / "app.asar"
    try:
        metadata = asar.lstat()
    except OSError:
        return False
    if not (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_nlink == 1
        and metadata.st_uid == os.getuid()
    ):
        return False
    if _bundle_version(staged_app, STALE_PAYLOAD_VERSIONS, deadline) is None:
        return False
    try:
        target_after = (shipit / update_name).lstat()
    except OSError:
        return False
    return bool(
        target_after.st_dev == expected.st_dev
        and target_after.st_ino == expected.st_ino
        and target_after.st_uid == expected.st_uid
        and target_after.st_mode == expected.st_mode
    )


def _read_json_at(parent_fd: int, name: str, *, owner: int) -> dict[str, Any] | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
        try:
            metadata = os.fstat(fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != owner
                or metadata.st_nlink != 1
                or metadata.st_size > 64 * 1024
            ):
                return None
            payload = json.loads(os.read(fd, metadata.st_size + 1).decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        finally:
            os.close(fd)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _find_committed_quarantine(
    shipit: Path,
    root_fd: int,
    root_metadata: os.stat_result,
    *,
    owner: int,
    app_version: str,
    deadline: float,
) -> str | None:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    names: list[str] = []
    for index, entry in enumerate(os.scandir(root_fd), start=1):
        if index > MAX_SHIPIT_ENTRIES:
            raise DesktopUpdaterCleanupError("ShipIt entry limit exceeded")
        if _remaining(deadline) <= 0:
            raise DesktopUpdaterCleanupError("recovery deadline exceeded")
        if entry.name.startswith(QUARANTINE_PREFIX):
            names.append(entry.name)
    for quarantine_name in sorted(names):
        if _remaining(deadline) <= 0:
            raise DesktopUpdaterCleanupError("recovery deadline exceeded")
        try:
            quarantine_fd = os.open(quarantine_name, flags, dir_fd=root_fd)
        except OSError:
            continue
        try:
            metadata = os.fstat(quarantine_fd)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != owner
                or metadata.st_dev != root_metadata.st_dev
                or metadata.st_mode & 0o022
            ):
                continue
            marker = _read_json_at(quarantine_fd, QUARANTINE_MARKER, owner=owner)
            original_name = str((marker or {}).get("originalName") or "")
            if not (
                marker
                and marker.get("schemaVersion") == 1
                and marker.get("purpose") == "quarantine-agentlas-desktop-stale-update"
                and marker.get("appVersion") == app_version
                and UPDATE_NAME_PATTERN.fullmatch(original_name)
                and isinstance(marker.get("device"), int)
                and isinstance(marker.get("inode"), int)
            ):
                continue
            child = os.stat(original_name, dir_fd=quarantine_fd, follow_symlinks=False)
            if not (
                stat.S_ISDIR(child.st_mode)
                and not stat.S_ISLNK(child.st_mode)
                and child.st_uid == owner
                and child.st_dev == marker["device"] == root_metadata.st_dev
                and child.st_ino == marker["inode"]
            ):
                continue
            staged_app = shipit / quarantine_name / original_name / "Agentlas.app"
            if _bundle_version(staged_app, STALE_PAYLOAD_VERSIONS, deadline) is not None:
                return quarantine_name
        except OSError:
            continue
        finally:
            os.close(quarantine_fd)
    if _remaining(deadline) <= 0:
        raise DesktopUpdaterCleanupError("recovery deadline exceeded")
    return None


def _open_recovery_lock(root_fd: int, root_metadata: os.stat_result, owner: int) -> int | None:
    import fcntl

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(LOCK_NAME, flags, 0o600, dir_fd=root_fd)
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != owner
            or metadata.st_dev != root_metadata.st_dev
            or metadata.st_nlink != 1
        ):
            raise DesktopUpdaterCleanupError("recovery lock boundary is unsafe")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        return fd
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _close_recovery_lock(fd: int) -> None:
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _same_target(metadata: os.stat_result, expected: os.stat_result) -> bool:
    return (
        metadata.st_dev == expected.st_dev
        and metadata.st_ino == expected.st_ino
        and metadata.st_uid == expected.st_uid
        and metadata.st_mode == expected.st_mode
        and stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
    )


def _atomic_quarantine_update(
    root_fd: int,
    root_metadata: os.stat_result,
    update_name: str,
    expected: os.stat_result,
    *,
    owner: int,
    app_version: str,
) -> tuple[str, bool]:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    quarantine_fd: int | None = None
    quarantine_name: str | None = None
    committed = False
    try:
        pinned_root = os.fstat(root_fd)
        if (
            pinned_root.st_dev != root_metadata.st_dev
            or pinned_root.st_ino != root_metadata.st_ino
            or pinned_root.st_uid != owner
        ):
            raise DesktopUpdaterCleanupError("ShipIt root changed identity")
        target_before = os.stat(update_name, dir_fd=root_fd, follow_symlinks=False)
        if not _same_target(target_before, expected):
            raise DesktopUpdaterCleanupError("logged update target changed after verification")

        for _ in range(8):
            candidate = f"{QUARANTINE_PREFIX}{secrets.token_hex(12)}"
            try:
                os.mkdir(candidate, 0o700, dir_fd=root_fd)
                quarantine_name = candidate
                break
            except FileExistsError:
                continue
        if quarantine_name is None:
            raise DesktopUpdaterCleanupError("could not allocate recovery quarantine")

        quarantine_fd = os.open(quarantine_name, flags, dir_fd=root_fd)
        quarantine_metadata = os.fstat(quarantine_fd)
        if (
            not stat.S_ISDIR(quarantine_metadata.st_mode)
            or quarantine_metadata.st_uid != owner
            or quarantine_metadata.st_dev != root_metadata.st_dev
        ):
            raise DesktopUpdaterCleanupError("recovery quarantine is unsafe")

        marker_payload = {
            "schemaVersion": 1,
            "purpose": "quarantine-agentlas-desktop-stale-update",
            "appVersion": app_version,
            "originalName": update_name,
            "device": expected.st_dev,
            "inode": expected.st_ino,
        }
        marker_fd = os.open(
            QUARANTINE_MARKER,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=quarantine_fd,
        )
        try:
            os.write(
                marker_fd,
                (json.dumps(marker_payload, sort_keys=True) + "\n").encode("utf-8"),
            )
            os.fsync(marker_fd)
        finally:
            os.close(marker_fd)

        os.rename(
            update_name,
            update_name,
            src_dir_fd=root_fd,
            dst_dir_fd=quarantine_fd,
        )
        committed = True
        try:
            target_after = os.stat(update_name, dir_fd=quarantine_fd, follow_symlinks=False)
            if not _same_target(target_after, expected):
                # The name was replaced between the final stat and rename. Put
                # exactly the moved object back only while the source name is
                # still absent; otherwise leave a typed resumable quarantine.
                try:
                    os.stat(update_name, dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError:
                    os.rename(
                        update_name,
                        update_name,
                        src_dir_fd=quarantine_fd,
                        dst_dir_fd=root_fd,
                    )
                    committed = False
                    raise DesktopUpdaterCleanupError("quarantine identity mismatch rolled back")
                return quarantine_name, False
            try:
                os.fsync(quarantine_fd)
                os.fsync(root_fd)
            except OSError:
                # The live namespace transition already committed. The exact
                # marker+inode resume path below re-recognizes it next launch.
                return quarantine_name, False
            return quarantine_name, True
        except DesktopUpdaterCleanupError:
            raise
        except OSError:
            return quarantine_name, False
    except Exception:
        if not committed and quarantine_fd is not None and quarantine_name is not None:
            try:
                names = os.listdir(quarantine_fd)
                if names == [QUARANTINE_MARKER]:
                    os.unlink(QUARANTINE_MARKER, dir_fd=quarantine_fd)
                    os.close(quarantine_fd)
                    quarantine_fd = None
                    os.rmdir(quarantine_name, dir_fd=root_fd)
            except OSError:
                pass
        raise
    finally:
        if quarantine_fd is not None:
            os.close(quarantine_fd)


def _show_dialog(script: str) -> None:
    try:
        subprocess.Popen(
            ["/usr/bin/osascript", "-e", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        pass


def _show_recovery_dialog() -> None:
    _show_dialog(RECOVERY_DIALOG)


def _show_partial_recovery_dialog() -> None:
    _show_dialog(PARTIAL_RECOVERY_DIALOG)


def repair_installed_desktop_updater_cache(
    source_dir: Path,
    home: Path | None = None,
    *,
    app_candidates: tuple[Path, ...] | None = None,
    python_executable: Path | None = None,
    show_dialog: bool = True,
) -> dict[str, Any]:
    """Quarantine one exact log-proven stale updater payload."""

    deadline = time.monotonic() + RECOVERY_DEADLINE_SECONDS
    source = source_dir.expanduser().resolve()
    home_dir = (home or Path.home()).expanduser().resolve()
    if not _verified_runtime_update_context(source):
        return {"status": "not_applicable", "reason": "not_verified_runtime_update"}
    owner = os.getuid()
    candidates = app_candidates or (
        Path("/Applications/Agentlas.app"),
        home_dir / "Applications" / "Agentlas.app",
    )
    executable = python_executable or Path(sys.executable)
    app_version: str | None = None
    saw_affected_candidate = False
    for app_path in candidates:
        if not app_path.exists() or app_path.is_symlink() or not app_path.is_dir():
            continue
        try:
            with (app_path / "Contents" / "Info.plist").open("rb") as handle:
                candidate_payload = plistlib.load(handle)
            candidate_version = str(candidate_payload.get("CFBundleShortVersionString") or "")
        except (OSError, plistlib.InvalidFileException):
            continue
        if (
            candidate_payload.get("CFBundleIdentifier") != DESKTOP_BUNDLE_ID
            or candidate_version not in DESKTOP_VERSIONS
        ):
            continue
        saw_affected_candidate = True
        if not _desktop_python_matches_app(app_path, executable):
            continue
        app_version = _bundle_version(app_path, DESKTOP_VERSIONS, deadline)
        if app_version is not None:
            break
        return {"status": "blocked", "reason": "running_app_untrusted"}
    if app_version is None:
        return {
            "status": "blocked" if saw_affected_candidate else "not_applicable",
            "reason": "not_desktop_python" if saw_affected_candidate else "target_not_found",
        }

    shipit_root = home_dir / "Library" / "Caches" / "com.agentlas.desktop.ShipIt"
    if not shipit_root.exists() and not shipit_root.is_symlink():
        return {"status": "not_needed", "reason": "shipit_cache_missing"}
    result: dict[str, Any] | None = None
    quarantine_committed = False
    try:
        shipit_metadata = _validate_cache_root(home_dir, shipit_root, owner)
        root_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(shipit_root, root_flags)
        lock_fd: int | None = None
        try:
            pinned_root = os.fstat(root_fd)
            if (
                pinned_root.st_dev != shipit_metadata.st_dev
                or pinned_root.st_ino != shipit_metadata.st_ino
                or pinned_root.st_uid != owner
            ):
                raise DesktopUpdaterCleanupError("ShipIt root changed identity")
            lock_fd = _open_recovery_lock(root_fd, shipit_metadata, owner)
            if lock_fd is None:
                return {"status": "blocked", "reason": "recovery_already_running"}

            logged_updates = _exact_logged_updates(home_dir, shipit_root, owner, deadline)
            direct_updates = _direct_real_updates(shipit_root, shipit_metadata, deadline)
            if not direct_updates:
                prior_quarantine = _find_committed_quarantine(
                    shipit_root,
                    root_fd,
                    shipit_metadata,
                    owner=owner,
                    app_version=app_version,
                    deadline=deadline,
                )
                if prior_quarantine is not None:
                    result = {
                        "status": "repaired",
                        "appVersion": app_version,
                        "quarantined": ["shipit/update.*"],
                        "resumed": True,
                        "nextAction": "retry_or_restart",
                    }
                elif logged_updates:
                    return {"status": "not_needed", "reason": "logged_payload_already_cleared"}
                else:
                    return {"status": "not_needed", "reason": "no_exact_blocked_payload"}
            else:
                update_name = next(
                    (name for name in logged_updates if name in direct_updates),
                    None,
                )
                if update_name is None:
                    return {"status": "blocked", "reason": "no_exact_blocked_payload"}
                target_metadata = os.stat(update_name, dir_fd=root_fd, follow_symlinks=False)
                if (
                    not stat.S_ISDIR(target_metadata.st_mode)
                    or stat.S_ISLNK(target_metadata.st_mode)
                    or target_metadata.st_uid != owner
                    or target_metadata.st_dev != shipit_metadata.st_dev
                ):
                    return {"status": "blocked", "reason": "logged_payload_unsafe"}
                if not _staged_payload_is_exact(
                    shipit_root,
                    update_name,
                    target_metadata,
                    deadline,
                ):
                    return {"status": "blocked", "reason": "stale_payload_untrusted"}
                _, commit_verified = _atomic_quarantine_update(
                    root_fd,
                    shipit_metadata,
                    update_name,
                    target_metadata,
                    owner=owner,
                    app_version=app_version,
                )
                quarantine_committed = True
                remaining_updates = _direct_real_updates(
                    shipit_root,
                    shipit_metadata,
                    deadline,
                )
                if remaining_updates or not commit_verified:
                    result = {
                        "status": "partial",
                        "reason": (
                            "additional_update_payload_remains"
                            if remaining_updates
                            else "quarantine_commit_needs_recheck"
                        ),
                        "quarantined": 1,
                        "nextAction": "restart_for_recovery",
                    }
                else:
                    result = {
                        "status": "repaired",
                        "appVersion": app_version,
                        "quarantined": ["shipit/update.*"],
                        "nextAction": "retry_or_restart",
                    }
        finally:
            if lock_fd is not None:
                _close_recovery_lock(lock_fd)
            os.close(root_fd)
    except (DesktopUpdaterCleanupError, OSError, plistlib.InvalidFileException):
        if quarantine_committed:
            result = {
                "status": "partial",
                "reason": "quarantine_committed_needs_recheck",
                "quarantined": 1,
                "nextAction": "restart_for_recovery",
            }
        else:
            return {"status": "blocked", "reason": "stale_cache_quarantine_failed"}

    if result is None:
        return {"status": "blocked", "reason": "stale_cache_quarantine_failed"}
    if show_dialog and os.environ.get("AGENTLAS_DESKTOP_RECOVERY_DIALOG", "1") != "0":
        if result["status"] == "repaired":
            _show_recovery_dialog()
        elif result["status"] == "partial":
            _show_partial_recovery_dialog()
    return result
