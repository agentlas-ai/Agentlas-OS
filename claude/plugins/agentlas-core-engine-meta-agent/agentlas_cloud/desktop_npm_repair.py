"""Recover only the two known unsigned Desktop npm additions, without deletion.

The old updater invokes the new release's install-memory-hooks.py after archive
digest verification. This bridge also retries from the selected managed runtime.
No package code is imported or executed. A successful transaction preserves the
original signing envelope and requires full codesign and Gatekeeper verification.
"""

from __future__ import annotations

import ctypes
import hashlib
import itertools
import json
import os
import plistlib
import posixpath
import re
import secrets
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .desktop_repair import DESKTOP_AUTHORITY, DESKTOP_BUNDLE_ID, DESKTOP_REQUIREMENT, DESKTOP_TEAM_ID

VERSIONS = {"1.2.14", "1.2.15"}
MARKER_NAME = "desktop-npm-repair-bridge-v1.json"
MARKER = {
    "schemaVersion": 1,
    "purpose": "quarantine-agentlas-desktop-unsealed-claude-grok",
    "bundleIdentifier": DESKTOP_BUNDLE_ID,
    "teamIdentifier": DESKTOP_TEAM_ID,
    "versions": sorted(VERSIONS),
}
NODE = "Contents/Resources/node-runtime"
PACKAGES = (("@anthropic-ai/claude-code", "claude"), ("@xai-official/grok", "grok"))
ALLOWED_PATHS = frozenset(
    relative
    for package, binary in PACKAGES
    for relative in (
        f"{NODE}/lib/node_modules/{package}",
        f"{NODE}/lib/node_modules/{package.split('/')[0]}",
        f"{NODE}/bin/{binary}",
    )
)
DEADLINE_SECONDS = 20.0
MAX_ENTRIES = 30_000
MAX_BYTES = 512 * 1024 * 1024
JOURNAL_LIMIT = 64 * 1024
# The hook installer imports this module on every supported host. Only Darwin
# enters the repair; importing it must remain safe on Windows.
DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


class RepairBlocked(Exception):
    """An internal, finite reason code; never include paths or command output."""


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RepairBlocked("deadline_exceeded")
    return remaining


def _identity(metadata: os.stat_result) -> list[int]:
    return [metadata.st_dev, metadata.st_ino, metadata.st_uid, stat.S_IFMT(metadata.st_mode)]


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    """Open every path component without following a symlink."""
    if not path.is_absolute() or ".." in path.parts:
        raise RepairBlocked("unsafe_directory")
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _relative_directory(root: int, relative: str) -> Iterator[int]:
    fd = os.dup(root)
    try:
        for part in relative.split("/") if relative else ():
            if part in ("", ".", ".."):
                raise RepairBlocked("unsafe_directory")
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _read_at(fd: int, name: str, limit: int) -> bytes:
    leaf = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        metadata = os.fstat(leaf)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > limit:
            raise RepairBlocked("unsafe_metadata")
        chunks = []
        size = 0
        while True:
            chunk = os.read(leaf, min(1024 * 1024, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise RepairBlocked("metadata_limit")
        after = os.fstat(leaf)
        if (metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise RepairBlocked("metadata_changed")
        return b"".join(chunks)
    finally:
        os.close(leaf)


def _read_path(path: Path, limit: int = JOURNAL_LIMIT) -> bytes:
    with _directory(path.parent) as fd:
        return _read_at(fd, path.name, limit)


def _verified_context(source: Path) -> bool:
    if sys.platform != "darwin" or not os.environ.get("HEPHAESTUS_RUNTIME_ROOT"):
        return False
    try:
        # This is an update-context check, not a substitute for archive trust.
        if Path(__file__).resolve().parent.parent != source or source.is_symlink():
            return False
        with _directory(source) as fd:
            if os.fstat(fd).st_uid != os.getuid():
                return False
        if json.loads(_read_path(source / "agentlas_cloud" / MARKER_NAME)) != MARKER:
            return False
        if any(p.name.startswith("hephaestus-update-") for p in source.parents):
            release = str(json.loads(_read_path(source / "manifest.json"))["version"])
        else:
            base = Path(os.environ.get("HEPHAESTUS_RUNTIME_BASE") or Path.home() / ".agentlas/runtime")
            with _directory(base) as fd:
                if os.fstat(fd).st_uid != os.getuid():
                    return False
            current = base / "current"
            if not current.is_symlink() or current.resolve(strict=True) != source:
                return False
            release = _read_path(source / "RELEASE").decode().strip().removeprefix("v")
            if source.parent != base:
                generations = base / ".generations"
                if source.parent != generations or not re.fullmatch(
                    re.escape(release) + r"\.[A-Za-z0-9]{6}", source.name
                ):
                    return False
                with _directory(generations) as fd:
                    if os.fstat(fd).st_uid != os.getuid():
                        return False
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", release)
        return bool(match and tuple(map(int, match.groups())) >= (1, 2, 47))
    except (OSError, ValueError, KeyError, RepairBlocked):
        return False


def _command(command: list[str], deadline: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False,
                              timeout=min(6.0, _remaining(deadline)))
    except subprocess.TimeoutExpired as exc:
        raise RepairBlocked("verification_timeout") from exc


def _signing_identity(app: Path, deadline: float) -> str:
    result = _command(["/usr/bin/codesign", "-d", "-r-", "--verbose=4", str(app)], deadline)
    lines = set((result.stdout + "\n" + result.stderr).splitlines())
    expected = {f"Identifier={DESKTOP_BUNDLE_ID}", f"TeamIdentifier={DESKTOP_TEAM_ID}",
                f"Authority={DESKTOP_AUTHORITY}"}
    hashes = [line[7:] for line in lines if re.fullmatch(r"CDHash=[0-9a-f]{40}", line)]
    if result.returncode != 0 or not expected.issubset(lines) or len(hashes) != 1:
        raise RepairBlocked("official_identity_unavailable")
    return hashes[0]


def _signature(app: Path, deadline: float) -> bool:
    return _command(["/usr/bin/codesign", "--verify", "--deep", "--strict",
                     f"-R={DESKTOP_REQUIREMENT}", str(app)], deadline).returncode == 0


def _gatekeeper(app: Path, deadline: float) -> bool:
    return _command(["/usr/sbin/spctl", "-a", "-t", "execute", "--context",
                     "context:primary-signature", "-vv", str(app)], deadline).returncode == 0


def _writers_idle(app: Path, deadline: float) -> None:
    result = _command(["/bin/ps", "-axo", "uid=,comm=,args="], deadline)
    if result.returncode != 0 or len(result.stdout) > 4 * 1024 * 1024:
        raise RepairBlocked("process_state_unavailable")
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3 or parts[0] != str(os.getuid()):
            continue
        command, arguments = parts[1:]
        # npm changes its process title and may omit its original prefix. A
        # same-owner npm writer therefore conservatively defers this repair.
        if (str(app / NODE) in command + " " + arguments
                or re.search(r"(?:^|[ /])npm (?:install|update|uninstall|rebuild)\b", command + " " + arguments)):
            raise RepairBlocked("npm_or_bundled_cli_active")


def _envelope(app_fd: int) -> tuple[dict[str, Any], set[str], str]:
    with _relative_directory(app_fd, "Contents") as fd:
        info_bytes = _read_at(fd, "Info.plist", 1024 * 1024)
    with _relative_directory(app_fd, "Contents/_CodeSignature") as fd:
        resources_bytes = _read_at(fd, "CodeResources", 32 * 1024 * 1024)
    info, resources = plistlib.loads(info_bytes), plistlib.loads(resources_bytes)
    if not isinstance(info, dict) or not isinstance(resources, dict) or not isinstance(resources.get("files2"), dict):
        raise RepairBlocked("invalid_signing_envelope")
    sealed: set[str] = set()
    for key in ("files", "files2"):
        entries = resources.get(key, {})
        if not isinstance(entries, dict):
            raise RepairBlocked("invalid_signing_envelope")
        for name in entries:
            if not isinstance(name, str) or name.startswith("/") or "\\" in name or any(
                part in ("", ".", "..") for part in name.split("/")
            ):
                raise RepairBlocked("invalid_sealed_path")
            sealed.add("Contents/" + name)
    if not sealed:
        raise RepairBlocked("empty_signing_envelope")
    digest = hashlib.sha256(info_bytes + b"\0" + resources_bytes).hexdigest()
    return info, sealed, digest


def _unsigned(relative: str, sealed: set[str]) -> None:
    # An enclosing sealed nested-code object protects all descendants too.
    # Case-fold conservatively on macOS, including case-insensitive volumes.
    relative = relative.casefold()
    if any(relative == p or relative.startswith(p + "/") or p.startswith(relative + "/")
           for p in (name.casefold() for name in sealed)):
        raise RepairBlocked("candidate_is_sealed")


def _snapshot(fd: int, name: str, deadline: float, *, link_root: str | None = None,
              original_name: str | None = None) -> str:
    digest = hashlib.sha256()
    count = size = 0
    device = os.fstat(fd).st_dev

    def visit(parent: int, leaf: str, relative: str) -> None:
        nonlocal count, size
        _remaining(deadline)
        count += 1
        if count > MAX_ENTRIES or relative.count("/") > 64:
            raise RepairBlocked("scan_limit")
        metadata = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        if metadata.st_dev != device or metadata.st_uid != os.getuid():
            raise RepairBlocked("candidate_owner_or_device")
        digest.update(json.dumps([relative, _identity(metadata), metadata.st_mode,
                                  metadata.st_size, metadata.st_mtime_ns], sort_keys=True).encode())
        if stat.S_ISLNK(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise RepairBlocked("candidate_type_or_hardlink")
            target = os.readlink(leaf, dir_fd=parent)
            if link_root is not None:
                normalized = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
                if target.startswith("/") or not normalized.startswith(link_root + "/"):
                    raise RepairBlocked("candidate_link_escape")
            digest.update(os.fsencode(target))
        elif stat.S_ISDIR(metadata.st_mode):
            child = os.open(leaf, DIR_FLAGS, dir_fd=parent)
            try:
                if _identity(os.fstat(child)) != _identity(metadata):
                    raise RepairBlocked("candidate_changed")
                with os.scandir(child) as scan:
                    names = [entry.name for entry in itertools.islice(scan, MAX_ENTRIES + 1)]
                if len(names) > MAX_ENTRIES:
                    raise RepairBlocked("scan_limit")
                for entry in sorted(names):
                    visit(child, entry, relative + "/" + entry)
            finally:
                os.close(child)
        elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            size += metadata.st_size
            if size > MAX_BYTES:
                raise RepairBlocked("scan_limit")
            child = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                if _identity(os.fstat(child)) != _identity(metadata):
                    raise RepairBlocked("candidate_changed")
                read = 0
                while True:
                    _remaining(deadline)
                    chunk = os.read(child, 1024 * 1024)
                    if not chunk:
                        break
                    read += len(chunk)
                    if read > metadata.st_size:
                        raise RepairBlocked("candidate_changed")
                    digest.update(chunk)
                if read != metadata.st_size:
                    raise RepairBlocked("candidate_changed")
            finally:
                os.close(child)
        else:
            raise RepairBlocked("candidate_type_or_hardlink")
        after = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        if (_identity(metadata), metadata.st_mtime_ns, metadata.st_ctime_ns, metadata.st_size) != (
            _identity(after), after.st_mtime_ns, after.st_ctime_ns, after.st_size
        ):
            raise RepairBlocked("candidate_changed")

    visit(fd, name, original_name or name)
    return digest.hexdigest()


def _exists(fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _plan(app_fd: int, sealed: set[str], deadline: float) -> list[dict[str, Any]]:
    entries = []
    for package, binary in PACKAGES:
        scope, package_leaf = package.split("/")
        scope_path = f"{NODE}/lib/node_modules/{scope}"
        package_path = f"{scope_path}/{package_leaf}"
        with _relative_directory(app_fd, f"{NODE}/lib/node_modules") as modules:
            if _exists(modules, scope) is None:
                continue
        with _relative_directory(app_fd, scope_path) as scope_fd:
            children = os.listdir(scope_fd)
            if package_leaf not in children:
                # Empty scopes are not enough evidence of the observed incident.
                continue
        with _relative_directory(app_fd, package_path) as package_fd:
            package_json = json.loads(_read_at(package_fd, "package.json", 1024 * 1024))
            if not isinstance(package_json, dict) or package_json.get("name") != package:
                raise RepairBlocked("package_identity_mismatch")
            bins = package_json.get("bin")
            target = bins.get(binary) if isinstance(bins, dict) else bins
            if not isinstance(target, str) or target.startswith("/") or any(
                part in ("", "..") for part in target.split("/")
            ):
                raise RepairBlocked("package_bin_mismatch")
            target = posixpath.normpath(target)
        relative = scope_path if children == [package_leaf] else package_path
        # Preserve unrelated entries in the scope; never move a generic npm tree.
        link_root = scope + "/" + package_leaf if relative == scope_path else package_leaf
        candidates = [(relative, link_root)]
        with _relative_directory(app_fd, f"{NODE}/bin") as bin_fd:
            metadata = _exists(bin_fd, binary)
            if metadata is not None:
                if not stat.S_ISLNK(metadata.st_mode) or os.readlink(binary, dir_fd=bin_fd) != (
                    "../lib/node_modules/" + package + "/" + target
                ):
                    raise RepairBlocked("bin_link_mismatch")
                candidates.insert(0, (f"{NODE}/bin/{binary}", None))
        for relative, link_root in candidates:
            _unsigned(relative, sealed)
            parent, leaf = relative.rsplit("/", 1)
            with _relative_directory(app_fd, parent) as fd:
                entries.append({"path": relative, "identity": _identity(os.stat(leaf, dir_fd=fd, follow_symlinks=False)),
                                "parent": _identity(os.fstat(fd)), "linkRoot": link_root,
                                "sha256": _snapshot(fd, leaf, deadline, link_root=link_root)})
    return entries


def _rename_exclusive(source_fd: int, source: str, target_fd: int, target: str) -> None:
    # Darwin RENAME_EXCL is atomic: a concurrent destination is never replaced.
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    rename = libc.renameatx_np
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(source_fd, os.fsencode(source), target_fd, os.fsencode(target), 0x00000004) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    os.fsync(source_fd)
    os.fsync(target_fd)


def _save(fd: int, journal: dict[str, Any]) -> None:
    name = ".journal-" + secrets.token_hex(8)
    leaf = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        data = json.dumps(journal, sort_keys=True).encode()
        if len(data) > JOURNAL_LIMIT:
            raise RepairBlocked("journal_limit")
        view = memoryview(data)
        while view:
            view = view[os.write(leaf, view):]
        os.fsync(leaf)
    finally:
        os.close(leaf)
    os.replace(name, "journal.json", src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def _validate_journal(journal: Any, app_identity: list[int], envelope: str, cdhash: str) -> None:
    if not isinstance(journal, dict) or journal.get("schemaVersion") != 1 or journal.get("purpose") != MARKER["purpose"]:
        raise RepairBlocked("invalid_journal")
    if journal.get("appIdentity") != app_identity or journal.get("envelope") != envelope or journal.get("cdhash") != cdhash:
        raise RepairBlocked("journal_app_changed")
    if journal.get("state") not in {"prepared", "verifying", "repaired", "rolling_back", "rolled_back", "rollback_conflict"}:
        raise RepairBlocked("invalid_journal")
    entries = journal.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 4:
        raise RepairBlocked("invalid_journal")
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or entry["path"] not in ALLOWED_PATHS or entry["path"] in names:
            raise RepairBlocked("invalid_journal")
        names.add(entry["path"])
        if not all(isinstance(entry.get(key), list) and len(entry[key]) == 4 and all(type(n) is int for n in entry[key])
                   for key in ("identity", "parent")):
            raise RepairBlocked("invalid_journal")
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))):
            raise RepairBlocked("invalid_journal")
    if any(a.startswith(b + "/") for a in names for b in names if a != b):
        raise RepairBlocked("invalid_journal")


def _rollback(app_fd: int, quarantine_fd: int, journal: dict[str, Any]) -> bool:
    journal["state"] = "rolling_back"
    # A full disk must not prevent restoring already moved objects. The last
    # durable prepared journal still allows recovery by their inode locations.
    try:
        _save(quarantine_fd, journal)
    except (OSError, RepairBlocked):
        pass
    conflict = False
    for index, entry in reversed(list(enumerate(journal["entries"]))):
        parent, leaf = entry["path"].rsplit("/", 1)
        try:
            with _relative_directory(app_fd, parent) as fd:
                if _identity(os.fstat(fd)) != entry["parent"]:
                    raise RepairBlocked("parent_changed")
                source = _exists(fd, leaf)
                moved = _exists(quarantine_fd, str(index))
                if moved is None:
                    if source is None or _identity(source) != entry["identity"]:
                        conflict = True
                    continue
                if _identity(moved) != entry["identity"] or source is not None:
                    conflict = True
                    continue
                _rename_exclusive(quarantine_fd, str(index), fd, leaf)
        except (OSError, RepairBlocked):
            conflict = True
    journal["state"] = "rollback_conflict" if conflict else "rolled_back"
    try:
        _save(quarantine_fd, journal)
    except (OSError, RepairBlocked):
        return False
    return not conflict


def _check_app(app: Path, app_fd: int, envelope: str) -> None:
    with _directory(app) as current:
        if _identity(os.fstat(current)) != _identity(os.fstat(app_fd)) or _envelope(current)[2] != envelope:
            raise RepairBlocked("app_changed")


def _transaction(app: Path, app_fd: int, quarantine_fd: int, version: str, sealed: set[str],
                 envelope: str, cdhash: str, deadline: float,
                 initial_entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    app_identity = _identity(os.fstat(app_fd))
    if _exists(quarantine_fd, "journal.json"):
        metadata = os.stat("journal.json", dir_fd=quarantine_fd, follow_symlinks=False)
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise RepairBlocked("unsafe_journal")
        journal = json.loads(_read_at(quarantine_fd, "journal.json", JOURNAL_LIMIT))
        _validate_journal(journal, app_identity, envelope, cdhash)
        if journal.get("state") not in {"repaired", "rolled_back"}:
            # A crash between rename and journal update is inferred from inode
            # locations. Restore first; never infer success from a partial move.
            restored = _rollback(app_fd, quarantine_fd, journal)
            return {"status": "blocked", "reason": "interrupted_repair_rolled_back" if restored else "rollback_conflict"}
        if journal.get("state") == "repaired":
            for index, entry in enumerate(journal["entries"]):
                moved = _exists(quarantine_fd, str(index))
                if moved is None or _identity(moved) != entry["identity"]:
                    raise RepairBlocked("quarantine_changed")
            _check_app(app, app_fd, envelope)
            if _signature(app, deadline) and _gatekeeper(app, deadline):
                _check_app(app, app_fd, envelope)
                return {"status": "not_needed", "reason": "previous_repair_verified"}
            return {"status": "blocked", "reason": "post_repair_app_changed"}
    if initial_entries is None and _signature(app, deadline):
        return {"status": "not_needed", "reason": "seal_valid"}
    entries = initial_entries if initial_entries is not None else _plan(app_fd, sealed, deadline)
    if not entries:
        return {"status": "blocked", "reason": "no_known_npm_additions"}
    journal = {"schemaVersion": 1, "purpose": MARKER["purpose"], "appIdentity": app_identity,
               "appVersion": version, "envelope": envelope, "cdhash": cdhash,
               "entries": entries, "state": "prepared"}
    _save(quarantine_fd, journal)
    try:
        for index, entry in enumerate(entries):
            _remaining(deadline)
            _check_app(app, app_fd, envelope)
            _writers_idle(app, deadline)
            parent, leaf = entry["path"].rsplit("/", 1)
            with _relative_directory(app_fd, parent) as fd:
                if _identity(os.fstat(fd)) != entry["parent"] or _snapshot(
                    fd, leaf, deadline, link_root=entry["linkRoot"]
                ) != entry["sha256"]:
                    raise RepairBlocked("candidate_changed")
                _rename_exclusive(fd, leaf, quarantine_fd, str(index))
                if _identity(os.stat(str(index), dir_fd=quarantine_fd, follow_symlinks=False)) != entry["identity"]:
                    raise RepairBlocked("candidate_changed")
                if _snapshot(quarantine_fd, str(index), deadline, link_root=entry["linkRoot"],
                             original_name=leaf) != entry["sha256"]:
                    raise RepairBlocked("candidate_changed")
        journal["state"] = "verifying"
        _save(quarantine_fd, journal)
        if not _signature(app, deadline) or not _gatekeeper(app, deadline):
            raise RepairBlocked("post_repair_verification_failed")
        if _signing_identity(app, deadline) != cdhash:
            raise RepairBlocked("original_signature_changed")
        _check_app(app, app_fd, envelope)
        _writers_idle(app, deadline)
        # Do not accept an addition recreated while verification was running.
        for entry in entries:
            parent, leaf = entry["path"].rsplit("/", 1)
            with _relative_directory(app_fd, parent) as fd:
                if _exists(fd, leaf) is not None:
                    raise RepairBlocked("addition_recreated")
        journal["state"] = "repaired"
        _save(quarantine_fd, journal)
        return {"status": "repaired", "reason": "original_trust_restored", "quarantined": len(entries)}
    except (OSError, RepairBlocked, ValueError) as exc:
        reason = str(exc) if isinstance(exc, RepairBlocked) else "filesystem_unavailable"
        journal["failure"] = reason
        restored = _rollback(app_fd, quarantine_fd, journal)
        return {"status": "blocked", "reason": reason if restored else "rollback_conflict", "rolledBack": restored}


def repair_installed_desktop_npm_seal(source_dir: Path, home: Path | None = None, *,
                                    app_candidates: tuple[Path, ...] | None = None,
                                    python_executable: Path | None = None) -> dict[str, Any]:
    """Fail closed, bounded, and independent of the overall OS update outcome."""
    try:
        source = source_dir.expanduser().resolve(strict=True)
    except OSError:
        return {"status": "not_applicable", "reason": "not_verified_runtime_update"}
    if not _verified_context(source):
        return {"status": "not_applicable", "reason": "not_verified_runtime_update"}
    deadline = time.monotonic() + DEADLINE_SECONDS
    executable = python_executable or Path(sys.executable)
    candidates = app_candidates or (Path("/Applications/Agentlas.app"), (home or Path.home()) / "Applications/Agentlas.app")
    try:
        for app in candidates:
            if not app.exists():
                continue
            # A non-Desktop terminal update must not mutate a running app.
            python_root = app / "Contents/Resources/python-runtime"
            try:
                executable.resolve(strict=True).relative_to(python_root.resolve(strict=True))
                if not executable.is_file():
                    continue
                with _directory(python_root):
                    pass
            except (OSError, ValueError):
                continue
            with _directory(app) as app_fd:
                if os.fstat(app_fd).st_uid != os.getuid():
                    raise RepairBlocked("app_not_owned")
                info, sealed, envelope = _envelope(app_fd)
                version = str(info.get("CFBundleShortVersionString") or "")
                if info.get("CFBundleIdentifier") != DESKTOP_BUNDLE_ID or version not in VERSIONS:
                    continue
                cdhash = _signing_identity(app, deadline)
                with _directory(app.parent) as parent_fd:
                    key = hashlib.sha256(json.dumps(_identity(os.fstat(app_fd))).encode()).hexdigest()[:24]
                    name = ".agentlas-npm-recovery-" + key
                    initial_entries = None
                    if _exists(parent_fd, name) is None:
                        if _signature(app, deadline):
                            return {"status": "not_needed", "reason": "seal_valid"}
                        _writers_idle(app, deadline)
                        initial_entries = _plan(app_fd, sealed, deadline)
                        if not initial_entries:
                            return {"status": "blocked", "reason": "no_known_npm_additions"}
                    try:
                        os.mkdir(name, 0o700, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                    except FileExistsError:
                        pass
                    with _relative_directory(parent_fd, name) as quarantine_fd:
                        metadata = os.fstat(quarantine_fd)
                        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077 or metadata.st_dev != os.fstat(app_fd).st_dev:
                            raise RepairBlocked("unsafe_quarantine")
                        lock = os.open("lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=quarantine_fd)
                        try:
                            import fcntl
                            metadata = os.fstat(lock)
                            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_uid != os.getuid():
                                raise RepairBlocked("unsafe_lock")
                            try:
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            except BlockingIOError:
                                return {"status": "blocked", "reason": "repair_busy"}
                            return _transaction(app, app_fd, quarantine_fd, version, sealed, envelope, cdhash,
                                                deadline, initial_entries)
                        finally:
                            os.close(lock)
    except RepairBlocked as exc:
        return {"status": "blocked", "reason": str(exc)}
    except (OSError, ValueError, plistlib.InvalidFileException):
        return {"status": "blocked", "reason": "filesystem_or_metadata_unavailable"}
    return {"status": "not_applicable", "reason": "target_or_desktop_python_not_found"}
