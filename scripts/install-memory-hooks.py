#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BEGIN_MARKER = "<!-- AGENTLAS:MEMORY-HOOK:BEGIN -->"
END_MARKER = "<!-- AGENTLAS:MEMORY-HOOK:END -->"
SUPPORTED_HOSTS = ("antigravity", "grok", "opencode")
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


class InstallError(RuntimeError):
    pass


def _command(command: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [command, *args], capture_output=True, text=True, timeout=15, check=False
    )


def _verified_runtime_update_context(source_dir: Path) -> bool:
    if sys.platform != "darwin" or not os.environ.get("HEPHAESTUS_RUNTIME_ROOT"):
        return False
    if not any(parent.name.startswith("hephaestus-update-") for parent in source_dir.parents):
        return False
    marker = source_dir / DESKTOP_REPAIR_MARKER
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload == {
        "schemaVersion": 1,
        "purpose": "repair-agentlas-desktop-python-cache-seal",
        "bundleIdentifier": DESKTOP_BUNDLE_ID,
        "teamIdentifier": DESKTOP_TEAM_ID,
        "versions": sorted(DESKTOP_REPAIR_VERSIONS),
    }


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
    if (
        os.environ.get("HEPHAESTUS_FORCE_ANTIGRAVITY")
        or (home / ".gemini" / "antigravity").is_dir()
        or (home / ".gemini" / "antigravity-ide").is_dir()
        or (home / ".gemini" / "antigravity-cli").is_dir()
    ):
        hosts.append("antigravity")
    if shutil.which("grok") or (home / ".grok").is_dir():
        hosts.append("grok")
    if shutil.which("opencode") or (home / ".config" / "opencode").is_dir():
        hosts.append("opencode")
    return hosts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install merge-safe Agentlas host memory hooks")
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument(
        "--hosts",
        default="auto",
        help="auto, all, or a comma-separated subset of antigravity,grok,opencode",
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
    installers = {
        "antigravity": install_antigravity,
        "grok": install_grok,
        "opencode": install_opencode,
    }
    installed: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    desktop_repair = repair_installed_desktop_python_cache_seal(source_dir, home)
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
                "desktop_repair": desktop_repair,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
