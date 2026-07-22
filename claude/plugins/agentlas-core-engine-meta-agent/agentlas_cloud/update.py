"""Runtime update checks for the Hephaestus CLI.

The explicit ``hephaestus hep-update`` command can install the latest runtime into
``~/.agentlas/runtime/<version>`` and atomically point ``current`` at it. Normal
command paths start a detached, fail-silent auto-update worker at most once per
TTL window so the user's command does not wait on network or install work.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

LATEST_RELEASE_URL = os.environ.get(
    "HEPHAESTUS_LATEST_RELEASE_URL",
    "https://api.github.com/repos/agentlas-ai/Agentlas-OS/releases/latest",
)
DEFAULT_TTL_SECONDS = 24 * 60 * 60
LOCK_STALE_SECONDS = 60 * 60
HEALTHCHECK_TIMEOUT_SECONDS = 15
MEMORY_HOOK_SYNC_TIMEOUT_SECONDS = 30
MAX_RUNTIME_ARCHIVE_BYTES = 256 * 1024 * 1024
# schemas/ carries the Workforce/Network contract files (workforce-work-order
# 등). 2026-07-16 실측: 릴리스 아카이브에는 포함·강제되는데 이 목록에 없어서
# 설치본에서만 통째로 유실 → 관리형 런타임의 hep-network가 스키마 결손으로 정지.
RUNTIME_DIRS = ("bin", "agentlas_cloud", "career_graph", "ontology", "templates")
RUNTIME_OPTIONAL_DIRS = ("schemas",)
RUNTIME_FILES = ("package-contract.json",)
RUNTIME_BRIDGE_FILES = (
    "desktop-update-bridge-v1.json",
    "scripts/install-memory-hooks.py",
)
MODEL2VEC_ASSET_NAME = "potion-multilingual-128M-int8"
LEGACY_MODEL2VEC_ASSET_NAME = "potion-base-8M-int8"
MODEL2VEC_ASSET_NAMES = (MODEL2VEC_ASSET_NAME, LEGACY_MODEL2VEC_ASSET_NAME)
RELEASE_MODEL2VEC_PATH = Path("assets") / "model2vec" / MODEL2VEC_ASSET_NAME
RUNTIME_MODEL2VEC_PATH = Path("models") / "model2vec" / MODEL2VEC_ASSET_NAME
HEP_COMMANDS = (
    "hep-build",
    "hep-network",
    "hep-cloud",
    "hep-search",
    "hep-browser",
    "hep-call",
    "hep-upload",
    "hep-storm",
)
HEP_SKILLS = ("hephaestus-network", "hephaestus-cloud", "hephaestus-storm")
AUTO_UPDATE_MARKER = "auto-update.json"

# Legacy in-adapter auto-update preflight. Older releases shipped command
# adapters that began with an ``if [ "${HEPHAESTUS_APP_AUTO_UPDATE ...; then
# ... curl <install-all-runtimes.sh> | HEPHAESTUS_FORCE=1 bash ... fi`` stanza.
# Host permission classifiers (e.g. Claude Code auto mode) block piping a remote
# script into bash on *every* machine, so the preflight is dead weight that can
# never succeed. The runner's own urllib-based self-update replaces it, so the
# durable fix is to strip the stanza from installed adapters in place — network
# free and independent of which release is published.
LEGACY_PREFLIGHT_START = 'if [ "${HEPHAESTUS_APP_AUTO_UPDATE'
LEGACY_PREFLIGHT_MARKERS = (
    "HEPHAESTUS_APP_AUTO_UPDATE",
    "NEEDS_HEP_UPDATE",
    "HEPHAESTUS_FORCE=1 bash",
    "hephaestus-app-auto-update",
)


def _strip_legacy_preflight(text: str) -> tuple[str, bool]:
    """Remove the legacy ``curl | bash`` auto-update preflight stanza.

    The stanza is a self-contained ``if ...; then ... fi`` block (with nested
    ``if`` statements) that opens with :data:`LEGACY_PREFLIGHT_START`. We locate
    that opener and consume lines until the matching ``fi`` returns nesting depth
    to zero, then swallow a single trailing blank line. Everything before and
    after — the still-valid runner resolution body — is preserved verbatim.
    Returns ``(new_text, changed)``.
    """

    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith(LEGACY_PREFLIGHT_START):
            start = index
            break
    if start is None:
        return text, False

    depth = 0
    end = None
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("if ") and stripped.endswith("then"):
            depth += 1
        elif stripped == "fi":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        return text, False

    cut_end = end + 1
    if cut_end < len(lines) and lines[cut_end].strip() == "":
        cut_end += 1
    new_text = "".join(lines[:start] + lines[cut_end:])
    return new_text, new_text != text


# Stale "runner not found" message that older adapters emitted; it references the
# now-removed preflight log. Normalize it so a sanitized adapter carries none of
# the legacy markers and the staleness scan skips it on the next pass.
LEGACY_NOT_FOUND_MESSAGE = (
    "Hephaestus runtime not found after app auto-update preflight. "
    "See /tmp/hephaestus-app-auto-update.log if it exists."
)
CLEAN_NOT_FOUND_MESSAGE = "Hephaestus runtime not found. Run the installer first."


def _sanitize_adapter_text(text: str) -> tuple[str, bool]:
    """Apply every legacy-preflight repair to one adapter's text.

    Strips the ``curl | bash`` stanza and normalizes the stale not-found message
    so the result is free of all :data:`LEGACY_PREFLIGHT_MARKERS`. Returns
    ``(new_text, changed)``.
    """

    new_text, _ = _strip_legacy_preflight(text)
    if LEGACY_NOT_FOUND_MESSAGE in new_text:
        new_text = new_text.replace(LEGACY_NOT_FOUND_MESSAGE, CLEAN_NOT_FOUND_MESSAGE)
    return new_text, new_text != text


def _adapter_paths(home: Path) -> list[Path]:
    """Enumerate installed hep-* command and skill adapter files across runtimes.

    Both command adapters (``.md`` / ``.toml``) and skill adapters
    (``SKILL.md``) shipped the legacy preflight, so both must be scanned.
    Destinations only — derivable from ``home`` without a release source, so the
    staleness scan stays network free.
    """

    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    paths: list[Path] = []
    for command in HEP_COMMANDS:
        paths.extend(
            [
                home / ".claude" / "commands" / f"{command}.md",
                codex_home / "prompts" / f"{command}.md",
                home / ".cursor" / "commands" / f"{command}.md",
                home / ".config" / "opencode" / "commands" / f"{command}.md",
                home / ".gemini" / "antigravity" / "global_workflows" / f"{command}.md",
                home / ".gemini" / "antigravity-ide" / "global_workflows" / f"{command}.md",
                home / ".gemini" / "commands" / f"{command}.toml",
                home / ".gemini" / "hephaestus-extension-source" / "commands" / f"{command}.toml",
            ]
        )
    for skill in HEP_SKILLS:
        paths.extend(
            [
                home / ".agents" / "skills" / skill / "SKILL.md",
                home / ".cursor" / "skills" / skill / "SKILL.md",
                home / ".openclaw" / "skills" / skill / "SKILL.md",
                home / ".hermes" / "skills" / skill / "SKILL.md",
                home / ".gemini" / "hephaestus-extension-source" / "skills" / skill / "SKILL.md",
            ]
        )
    cache_roots = [
        home / ".claude" / "plugins" / "cache" / "agentlas-core-engine" / "hephaestus",
        codex_home / "plugins" / "cache" / "agentlas-core-engine" / "hephaestus",
    ]
    for cache_root in cache_roots:
        if not cache_root.is_dir():
            continue
        for child in cache_root.iterdir():
            if not child.is_dir() or child.is_symlink():
                continue
            for runtime in ("claude", "codex"):
                command_dir = child / runtime / "plugins" / "agentlas-core-engine-meta-agent" / "commands"
                if command_dir.is_dir():
                    for command in HEP_COMMANDS:
                        paths.append(command_dir / f"{command}.md")
            for skill in HEP_SKILLS:
                paths.append(child / "skills" / skill / "SKILL.md")
    return paths


def reconcile_adapters(home: Path | None = None) -> dict[str, Any]:
    """Strip the legacy curl|bash auto-update preflight from installed adapters.

    Network free and release independent: repairs adapters in place so the
    permission-blocked preflight is purged on any machine — even one already on
    the latest runtime, where version-gated adapter sync never fires. Fail-silent
    per file; a single unreadable adapter never aborts the sweep.
    """

    home_dir = home or Path.home()
    sanitized: list[str] = []
    for path in _adapter_paths(home_dir):
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if not any(marker in text for marker in LEGACY_PREFLIGHT_MARKERS):
                continue
            new_text, changed = _sanitize_adapter_text(text)
            if not changed:
                continue
            tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
            tmp.write_text(new_text, encoding="utf-8")
            tmp.replace(path)
            sanitized.append(str(path))
        except Exception:
            continue
    return {"sanitized": sanitized, "count": len(sanitized)}


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
        "install_command": "hephaestus hep-update",
    }
    if not check_only:
        reconciled = reconcile_adapters()
        if reconciled["count"]:
            result["adapters_sanitized"] = reconciled["sanitized"]
    if check_only or status not in {"update_available", "missing_release_marker"}:
        return result

    installed = install_latest_runtime(latest)
    result.update(installed)
    result["status"] = "updated" if status == "update_available" else "recovered_missing_release_marker"
    return result


def maybe_auto_update(root: Path | None = None, *, background: bool = True) -> None:
    """Start a fail-silent runtime auto-update check.

    This function intentionally returns ``None`` for every outcome. It never
    raises, never prints, and by default never performs network or install work
    in the caller process.
    """

    try:
        # Always self-heal stale command adapters first. This is network free
        # and must run even when version auto-update is disabled, because the
        # legacy curl|bash preflight is blocked by host classifiers on every
        # machine and would otherwise persist forever once the runtime is
        # already current (version-gated adapter sync never re-fires).
        try:
            reconcile_adapters()
        except Exception:
            pass
        if _auto_update_disabled():
            return
        runtime_root = root or Path(__file__).resolve().parent.parent
        current = current_release(runtime_root)
        if current is not None and not _is_comparable_release(current):
            return
        base = _runtime_base()
        lock_path = base / ".update.lock"
        recovered_stale_lock = False
        if _path_present(lock_path):
            if not _remove_stale_lock(lock_path):
                return
            recovered_stale_lock = True
        marker_path = base / AUTO_UPDATE_MARKER
        marker = _read_json(marker_path)
        if not recovered_stale_lock and _marker_recent(marker.get("last_started_epoch")):
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
        f"Hephaestus update available: {latest_tag} (current {current}). Run: hephaestus hep-update",
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
    archive_asset = _verified_runtime_archive_asset(release)
    tarball_url = archive_asset["url"]
    expected_sha256 = archive_asset["sha256"]
    expected_size = archive_asset["size"]

    base = _runtime_base()
    target = base / _runtime_version_dir_name(tag)
    lock = base / ".update.lock"
    adapter_sync: dict[str, Any] = {"updated": [], "skipped_missing": [], "failed": []}
    memory_hook_sync: dict[str, Any] = {"status": "not_run", "installed": {}, "errors": {}}
    archive_sha256 = ""
    staged_target: Path | None = None
    installed_model_path: Path | None = None
    lock_token = _acquire_lock(lock)
    try:
        with tempfile.TemporaryDirectory(prefix="hephaestus-update-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "source.tar.gz"
            _download(tarball_url, archive)
            actual_size = archive.stat().st_size
            if actual_size != expected_size:
                raise ValueError(
                    "release archive size mismatch: "
                    f"expected {expected_size} bytes, got {actual_size} bytes"
                )
            archive_sha256 = _sha256_file(archive)
            if archive_sha256 != expected_sha256:
                raise ValueError(
                    "release archive digest mismatch: "
                    f"expected sha256:{expected_sha256}, got sha256:{archive_sha256}"
                )
            with tarfile.open(archive, "r:gz") as tf:
                _safe_extract(tf, tmp_path)
            source_dirs = [item for item in tmp_path.iterdir() if item.is_dir()]
            if len(source_dirs) != 1:
                raise ValueError("downloaded release must contain exactly one source directory")
            source = source_dirs[0]
            source_model = _validate_runtime_layout(source, release_source=True)

            staged_target = _unique_sibling(target, "staged")
            staged_target.mkdir(parents=True)
            for name in RUNTIME_DIRS:
                src = source / name
                shutil.copytree(src, staged_target / name)
            for name in RUNTIME_OPTIONAL_DIRS:
                src = source / name
                if src.is_dir():
                    shutil.copytree(src, staged_target / name)
            for name in RUNTIME_FILES:
                src = source / name
                if src.is_file():
                    shutil.copy2(src, staged_target / name)
            for relative_name in RUNTIME_BRIDGE_FILES:
                src = source / relative_name
                dest = staged_target / relative_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            runtime_model = staged_target / "models" / "model2vec" / source_model.name
            runtime_model.parent.mkdir(parents=True)
            shutil.copytree(source_model, runtime_model)
            installed_model_path = target / "models" / "model2vec" / source_model.name
            (staged_target / "RELEASE").write_text(f"{tag}\n", encoding="utf-8")
            write_python_shims(staged_target / "bin", sys.executable)
            _healthcheck_runtime(staged_target)
            _activate_runtime(staged_target, target)
            staged_target = None
            adapter_sync = sync_installed_runtime_adapters(source)
            memory_hook_sync = sync_installed_memory_hooks(source)
    finally:
        if staged_target is not None and _path_present(staged_target):
            _remove_path(staged_target)
        _release_lock(lock, lock_token)

    return {
        "runtime_root": str(target),
        "current_link": str(base / "current"),
        "updated_to": tag,
        "archive_digest": f"sha256:{archive_sha256}",
        "digest_verified": True,
        "archive_asset": archive_asset["name"],
        "model_root": str(installed_model_path or target / RUNTIME_MODEL2VEC_PATH),
        "model_verified": True,
        "adapter_sync": adapter_sync,
        "memory_hook_sync": memory_hook_sync,
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

    source_release = _source_release_tag(source)
    for src_rel, dest in _installed_plugin_cache_targets(source, home_dir):
        src = source / src_rel
        if not src.is_dir() or not dest.exists():
            skipped_missing.append(str(dest))
            continue
        try:
            _replace_directory(src, dest)
            if source_release:
                (dest / "RELEASE").write_text(f"{source_release}\n", encoding="utf-8")
            write_python_shims(dest / "bin", sys.executable)
            updated.append(str(dest))
        except Exception as exc:
            failed.append({"path": str(dest), "error": str(exc)})

    return {
        "updated": updated,
        "skipped_missing": skipped_missing,
        "failed": failed,
    }


def sync_installed_memory_hooks(source: Path, home: Path | None = None) -> dict[str, Any]:
    """Install merge-safe memory hooks for hosts detected on this machine.

    Claude and Codex hook manifests live inside their plugin bundles and are
    refreshed by :func:`sync_installed_runtime_adapters`. Antigravity, Grok,
    and OpenCode use global host files, so a runtime self-update must invoke the
    same owned-key/managed-block installer as the one-touch install. Hook repair
    is reported independently: an invalid user config is preserved and does not
    roll back an otherwise healthy, digest-verified runtime update.
    """

    installer = source / "scripts" / "install-memory-hooks.py"
    home_dir = (home or Path.home()).expanduser().resolve()
    if not installer.is_file():
        return {
            "status": "fail",
            "installed": {},
            "errors": {"installer": f"missing hook installer: {installer}"},
        }

    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(installer),
                "--source-dir",
                str(source),
                "--home",
                str(home_dir),
                "--hosts",
                "auto",
            ],
            cwd=str(source),
            env=env,
            capture_output=True,
            text=True,
            timeout=MEMORY_HOOK_SYNC_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "fail", "installed": {}, "errors": {"installer": str(exc)}}

    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        detail = (completed.stderr or completed.stdout or "invalid installer output").strip()[-500:]
        return {"status": "fail", "installed": {}, "errors": {"installer": detail}}
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "installed": {},
            "errors": {"installer": "hook installer returned a non-object response"},
        }
    installed = payload.get("installed") if isinstance(payload.get("installed"), dict) else {}
    errors = payload.get("errors") if isinstance(payload.get("errors"), dict) else {}
    status = "pass" if completed.returncode == 0 and payload.get("status") == "pass" else "fail"
    if status == "fail" and not errors:
        detail = (completed.stderr or "hook installer failed without an error record").strip()[-500:]
        errors = {"installer": detail}
    desktop_repair = payload.get("desktop_repair")
    if not isinstance(desktop_repair, dict):
        desktop_repair = {"status": "not_applicable", "reason": "not_reported"}
    desktop_updater_cleanup = payload.get("desktop_updater_cleanup")
    if not isinstance(desktop_updater_cleanup, dict):
        desktop_updater_cleanup = {"status": "not_applicable", "reason": "not_reported"}
    return {
        "status": status,
        "installed": installed,
        "errors": errors,
        "desktop_repair": desktop_repair,
        "desktop_updater_cleanup": desktop_updater_cleanup,
    }


def retry_installed_desktop_repair(source: Path, home: Path | None = None) -> dict[str, Any]:
    marker = source / "desktop-update-bridge-v1.json"
    installer = source / "scripts" / "install-memory-hooks.py"
    if marker.is_file() and installer.is_file():
        result = sync_installed_memory_hooks(source, home)
        repair = result.get("desktop_repair")
        return repair if isinstance(repair, dict) else {"status": "not_applicable", "reason": "not_reported"}

    # Desktop v0.8.58/v0.8.59 ship the v1.1.50 updater. It copies the complete
    # agentlas_cloud package but not newly added root bridge files. The embedded
    # module and exact marker therefore remain available for every later app
    # launch even if the freshly extracted one-shot repair did not finish.
    try:
        from agentlas_cloud.desktop_repair import repair_installed_desktop_python_cache_seal

        return repair_installed_desktop_python_cache_seal(source, home)
    except (ImportError, OSError):
        return {"status": "not_applicable", "reason": "bridge_not_installed"}


def retry_installed_desktop_updater_cleanup(source: Path, home: Path | None = None) -> dict[str, Any]:
    """Retry the v0.8.65/v0.8.66 stale updater cleanup from managed Core."""

    marker = source / "agentlas_cloud" / "desktop-updater-cleanup-bridge-v1.json"
    if not marker.is_file():
        return {"status": "not_applicable", "reason": "bridge_not_installed"}
    try:
        from agentlas_cloud.desktop_updater_cleanup import repair_installed_desktop_updater_cache

        return repair_installed_desktop_updater_cache(source, home)
    except (ImportError, OSError):
        return {"status": "not_applicable", "reason": "bridge_not_installed"}
    except Exception:
        # The runtime updater remains fail-silent and can try again later. Do
        # not let a Desktop cache repair failure block a verified OS update.
        return {"status": "blocked", "reason": "bridge_failed"}


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
        'setlocal\r\n'
        'set "PYTHONUTF8=1"\r\n'
        'set "PYTHONIOENCODING=utf-8"\r\n'
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
        'exit /b %ERRORLEVEL%\r\n',
        encoding="utf-8",
    )


_SEMVER_RE = re.compile(
    r"^[vV]?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _parse_semver(value: Any) -> tuple[str, str, str, tuple[str, ...]] | None:
    if not isinstance(value, str):
        return None
    match = _SEMVER_RE.fullmatch(value.strip())
    if not match:
        return None
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
    if any(item.isascii() and item.isdigit() and len(item) > 1 and item.startswith("0") for item in prerelease):
        return None
    return match.group(1), match.group(2), match.group(3), prerelease


def _compare_numeric_identifier(left: str, right: str) -> int:
    if len(left) != len(right):
        return -1 if len(left) < len(right) else 1
    if left == right:
        return 0
    return -1 if left < right else 1


def _compare_semver(left: Any, right: Any) -> int | None:
    """Return SemVer 2.0.0 precedence; build metadata does not affect it."""

    parsed_left = _parse_semver(left)
    parsed_right = _parse_semver(right)
    if parsed_left is None or parsed_right is None:
        return None
    for left_core, right_core in zip(parsed_left[:3], parsed_right[:3]):
        compared = _compare_numeric_identifier(left_core, right_core)
        if compared:
            return compared
    left_pre = parsed_left[3]
    right_pre = parsed_right[3]
    if not left_pre and not right_pre:
        return 0
    if not left_pre:
        return 1
    if not right_pre:
        return -1
    for index in range(max(len(left_pre), len(right_pre))):
        if index >= len(left_pre):
            return -1
        if index >= len(right_pre):
            return 1
        left_item = left_pre[index]
        right_item = right_pre[index]
        if left_item == right_item:
            continue
        left_numeric = left_item.isascii() and left_item.isdigit()
        right_numeric = right_item.isascii() and right_item.isdigit()
        if left_numeric and right_numeric:
            return _compare_numeric_identifier(left_item, right_item)
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_item < right_item else 1
    return 0


def _release_status(current: str | None, latest: Any) -> str:
    if not latest:
        return "unknown"
    if not current:
        return "missing_release_marker"
    comparison = _compare_semver(str(latest), current)
    if comparison is None:
        return "unknown"
    if comparison > 0:
        return "update_available"
    return "current"


def _is_comparable_release(value: str | None) -> bool:
    return _parse_semver(value) is not None


def _runtime_base() -> Path:
    return Path(os.environ.get("HEPHAESTUS_RUNTIME_BASE") or Path.home() / ".agentlas" / "runtime")


def _auto_update_disabled() -> bool:
    return os.environ.get("HEPHAESTUS_AUTO_UPDATE", "1") == "0" or os.environ.get("HEPHAESTUS_UPDATE_CHECK", "1") == "0"


def _marker_recent(epoch: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    return isinstance(epoch, (int, float)) and time.time() - float(epoch) < ttl_seconds


def _run_auto_update_once(root: Path | None = None) -> dict[str, Any]:
    runtime_root = root or Path(__file__).resolve().parent.parent
    desktop_repair = retry_installed_desktop_repair(runtime_root)
    desktop_updater_cleanup = retry_installed_desktop_updater_cleanup(runtime_root)
    current = current_release(runtime_root)
    marker_path = _runtime_base() / AUTO_UPDATE_MARKER
    marker = _read_json(marker_path)
    if current is not None and not _is_comparable_release(current):
        result = {
            "status": "skipped",
            "reason": "uncomparable_release",
            "current": current,
            "desktop_repair": desktop_repair,
            "desktop_updater_cleanup": desktop_updater_cleanup,
        }
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
        "desktop_repair": desktop_repair,
        "desktop_updater_cleanup": desktop_updater_cleanup,
    }
    if status not in {"update_available", "missing_release_marker"}:
        _write_json(marker_path, {**marker, **result})
        return result
    if marker.get("last_applied_tag") == latest_tag and _marker_recent(marker.get("last_applied_epoch")):
        result["status"] = "skipped"
        result["reason"] = "already_applied_recently"
        _write_json(marker_path, {**marker, **result})
        return result

    installed = install_latest_runtime(latest)
    result.update(installed)
    result["status"] = "updated" if status == "update_available" else "recovered_missing_release_marker"
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
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    targets: list[tuple[Path, Path]] = []
    for command in HEP_COMMANDS:
        targets.extend(
            [
                (Path(".claude") / "commands" / f"{command}.md", home / ".claude" / "commands" / f"{command}.md"),
                (Path("codex") / "prompts" / f"{command}.md", codex_home / "prompts" / f"{command}.md"),
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


def _installed_plugin_cache_targets(source: Path, home: Path) -> list[tuple[Path, Path]]:
    targets: list[tuple[Path, Path]] = []
    claude_src = Path("claude") / "plugins" / "agentlas-core-engine-meta-agent"
    codex_src = Path("codex") / "plugins" / "agentlas-core-engine-meta-agent"
    cache_roots = [
        (
            claude_src,
            home / ".claude" / "plugins" / "cache" / "agentlas-core-engine" / "hephaestus",
        ),
        (
            codex_src,
            Path(os.environ.get("CODEX_HOME") or home / ".codex")
            / "plugins"
            / "cache"
            / "agentlas-core-engine"
            / "hephaestus",
        ),
    ]
    for src_rel, cache_root in cache_roots:
        if not (source / src_rel).is_dir() or not cache_root.is_dir():
            continue
        for child in cache_root.iterdir():
            if child.is_dir() and not child.is_symlink() and (child / "bin" / "hephaestus").exists():
                targets.append((src_rel, child))
    return targets


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


def _source_release_tag(source: Path) -> str | None:
    marker = source / "RELEASE"
    if marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            return value
    manifest = source / "manifest.json"
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (FileNotFoundError, ValueError, OSError, AttributeError):
        return None
    if not version:
        return None
    value = str(version).strip()
    return value if value.startswith("v") else f"v{value}"


def _runtime_version_dir_name(tag: str) -> str:
    version = tag.lstrip("vV")
    alphanumeric = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    allowed = f"{alphanumeric}._+-"
    if (
        not version
        or version in {".", ".."}
        or version[0] not in alphanumeric
        or any(ch not in allowed for ch in version)
        or Path(version).name != version
    ):
        raise ValueError(f"unsafe release tag: {tag}")
    return version


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.removeprefix("sha256:")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError("release archive digest must be a SHA-256 value")
    return text


def _verified_runtime_archive_asset(release: dict[str, Any]) -> dict[str, Any]:
    """Select the tag-specific GitHub release asset and require its API digest.

    GitHub-generated ``tarball_url`` archives are mutable delivery responses and
    carry no publisher-visible digest in the releases API. Runtime updates must
    therefore use the explicitly uploaded ``hephaestus-runtime-vX.Y.Z.tar.gz``
    asset whose exact size and SHA-256 are part of the release metadata. Missing
    metadata fails closed before any network request.
    """

    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("release tag_name is required")
    expected_name = f"hephaestus-runtime-{tag}.tar.gz"
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError(f"release is missing verified runtime asset: {expected_name}")
    for asset in assets:
        if not isinstance(asset, dict) or str(asset.get("name") or "") != expected_name:
            continue
        url = str(asset.get("browser_download_url") or "").strip()
        if not url.startswith("https://github.com/"):
            raise ValueError("release runtime asset must use a GitHub HTTPS download URL")
        digest = asset.get("digest")
        if not digest:
            raise ValueError(f"release runtime asset is missing SHA-256 metadata: {expected_name}")
        size = asset.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError(f"release runtime asset has invalid size metadata: {expected_name}")
        if size > MAX_RUNTIME_ARCHIVE_BYTES:
            raise ValueError(
                f"release runtime asset exceeds {MAX_RUNTIME_ARCHIVE_BYTES} bytes: {expected_name}"
            )
        return {
            "name": expected_name,
            "url": url,
            "sha256": _normalize_sha256(digest),
            "size": size,
        }
    raise ValueError(f"release is missing verified runtime asset: {expected_name}")


def _model_path(runtime_root: Path, *, release_source: bool) -> Path | None:
    base = runtime_root / ("assets" if release_source else "models") / "model2vec"
    for name in MODEL2VEC_ASSET_NAMES:
        candidate = base / name
        if candidate.is_dir():
            return candidate
    return None


def _validate_runtime_layout(runtime_root: Path, *, release_source: bool = False) -> Path:
    missing: list[str] = []
    for name in RUNTIME_DIRS:
        if not (runtime_root / name).is_dir():
            missing.append(f"{name}/")
    for relative in (
        Path("bin") / "hephaestus",
        Path("agentlas_cloud") / "__init__.py",
        Path("agentlas_cloud") / "__main__.py",
        Path("agentlas_cloud") / "cli.py",
        Path("agentlas_cloud") / "update.py",
        Path("agentlas_cloud") / "desktop_repair.py",
        Path("agentlas_cloud") / "desktop-update-bridge-v1.json",
        Path("agentlas_cloud") / "desktop_updater_cleanup.py",
        Path("agentlas_cloud") / "desktop-updater-cleanup-bridge-v1.json",
        Path("career_graph") / "__init__.py",
        Path("career_graph") / "runtime.py",
        Path("ontology") / "__init__.py",
        Path("ontology") / "model_assets.py",
        Path("templates") / "agentlas.json.tpl",
        Path("desktop-update-bridge-v1.json"),
        Path("scripts") / "install-memory-hooks.py",
    ):
        if not (runtime_root / relative).is_file():
            missing.append(str(relative))
    if release_source:
        for relative in (
            Path("antigravity") / "hooks" / "agentlas-memory.json",
            Path("grok") / "hooks" / "agentlas-memory.json",
            Path("grok") / "agentlas-memory-rule.md",
            Path("opencode") / "plugins" / "agentlas-memory.js",
        ):
            if not (runtime_root / relative).is_file():
                missing.append(str(relative))
    # Old signed releases predate the package-contract/schemas surface. Keep
    # them installable for rollback, but any runtime that ships the command
    # module must carry the complete root contract and Workforce schemas.
    if (runtime_root / "agentlas_cloud" / "package_contract.py").is_file():
        for relative in (
            Path("package-contract.json"),
            Path("schemas") / "package-contract.schema.json",
            Path("schemas") / "workforce-work-order.schema.json",
            Path("schemas") / "workforce-selection.schema.json",
        ):
            if not (runtime_root / relative).is_file():
                missing.append(str(relative))
    model_path = _model_path(runtime_root, release_source=release_source)
    if model_path is None:
        layout = "assets" if release_source else "models"
        missing.append(f"{layout}/model2vec/<verified-asset>/")
    if missing:
        raise ValueError(f"release runtime layout is incomplete: {', '.join(missing)}")

    from ontology.model_assets import ModelAssetError, verify_model_asset

    try:
        verify_model_asset(model_path)
    except (ModelAssetError, OSError, ValueError) as exc:
        layout = "release" if release_source else "installed runtime"
        raise ValueError(f"{layout} Model2Vec asset failed verification: {model_path}") from exc
    return model_path


def _healthcheck_runtime(runtime_root: Path) -> None:
    """Import the runnable surfaces from exactly the candidate runtime."""

    model_path = _validate_runtime_layout(runtime_root)
    try:
        resolved_root = runtime_root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"runtime healthcheck could not resolve {runtime_root}") from exc

    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env["PYTHONPATH"] = str(resolved_root)
    env["PYTHONNOUSERSITE"] = "1"
    env["HEPHAESTUS_HEALTHCHECK_ROOT"] = str(resolved_root)
    env["HEPHAESTUS_HEALTHCHECK_MODEL"] = str(model_path.resolve(strict=True))
    check = (
        "import os\n"
        "from pathlib import Path\n"
        "import agentlas_cloud\n"
        "import agentlas_cloud.cli\n"
        "import agentlas_cloud.update\n"
        "import career_graph\n"
        "import ontology\n"
        "from ontology.model_assets import verify_model_asset\n"
        "root = Path(os.environ['HEPHAESTUS_HEALTHCHECK_ROOT']).resolve()\n"
        "modules = (agentlas_cloud, agentlas_cloud.cli, agentlas_cloud.update, career_graph, ontology)\n"
        "bad = [m.__name__ for m in modules if root not in Path(m.__file__).resolve().parents]\n"
        "verify_model_asset(Path(os.environ['HEPHAESTUS_HEALTHCHECK_MODEL']))\n"
        "raise SystemExit(8 if bad else 0)\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", check],
            cwd=str(resolved_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=HEALTHCHECK_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"runtime healthcheck timed out after {HEALTHCHECK_TIMEOUT_SECONDS}s") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-500:]
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"runtime healthcheck failed with exit code {completed.returncode}{suffix}")


def _download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "hephaestus-runtime-updater"})
    with urllib.request.urlopen(request, timeout=30) as response, path.open("wb") as out:
        shutil.copyfileobj(response, out)


def _safe_extract(tf: tarfile.TarFile, destination: Path) -> None:
    """Extract regular files/directories without trusting tar link semantics."""

    dest = destination.resolve()
    planned: list[tuple[tarfile.TarInfo, Path]] = []
    seen: set[Path] = set()
    for member in tf.getmembers():
        if member.issym() or member.islnk():
            raise ValueError(f"archive links are not allowed: {member.name}")
        if not member.isdir() and not member.isfile():
            raise ValueError(f"unsupported archive member type: {member.name}")
        if not member.name or "\x00" in member.name or "\\" in member.name:
            raise ValueError(f"unsafe path in release archive: {member.name}")
        archive_path = PurePosixPath(member.name)
        if archive_path.is_absolute() or any(part == ".." for part in archive_path.parts):
            raise ValueError(f"unsafe path in release archive: {member.name}")
        parts = [part for part in archive_path.parts if part not in {"", "."}]
        if not parts and not member.isdir():
            raise ValueError(f"unsafe path in release archive: {member.name}")
        target = dest.joinpath(*parts).resolve()
        try:
            inside_destination = Path(os.path.commonpath((str(dest), str(target)))) == dest
        except ValueError:
            inside_destination = False
        if not inside_destination:
            raise ValueError(f"unsafe path in release archive: {member.name}")
        if target in seen:
            raise ValueError(f"duplicate path in release archive: {member.name}")
        seen.add(target)
        planned.append((member, target))

    for member, target in planned:
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = tf.extractfile(member)
        if source is None:
            raise ValueError(f"could not read archive member: {member.name}")
        try:
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
        except FileExistsError as exc:
            raise ValueError(f"archive member would overwrite an existing path: {member.name}") from exc
        target.chmod(0o755 if member.mode & 0o111 else 0o644)


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if not _path_present(path):
        return
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _unique_sibling(path: Path, label: str) -> Path:
    return path.with_name(f".{path.name}.{label}.{os.getpid()}.{time.time_ns()}")


def _replace_runtime_target(staged: Path, target: Path) -> Path | None:
    backup: Path | None = None
    if _path_present(target):
        backup = _unique_sibling(target, "backup")
        target.rename(backup)
    try:
        staged.rename(target)
    except Exception:
        if backup is not None and _path_present(backup) and not _path_present(target):
            backup.rename(target)
        raise
    return backup


def _restore_runtime_target(target: Path, backup: Path | None) -> None:
    if backup is not None and not _path_present(backup):
        raise RuntimeError(f"runtime rollback backup is missing: {backup}")
    _remove_path(target)
    if backup is not None:
        backup.rename(target)


def _activate_runtime(staged: Path, target: Path) -> None:
    target_backup = _replace_runtime_target(staged, target)
    current_state: dict[str, str] | None = None
    try:
        current_state = _point_current_at(target)
        _healthcheck_runtime(target.parent / "current")
    except Exception as exc:
        rollback_errors: list[str] = []
        if current_state is not None:
            try:
                _restore_current(target.parent, current_state)
            except Exception as rollback_exc:
                rollback_errors.append(f"current: {rollback_exc}")
        try:
            _restore_runtime_target(target, target_backup)
        except Exception as rollback_exc:
            rollback_errors.append(f"target: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(f"runtime activation failed and rollback was incomplete: {'; '.join(rollback_errors)}") from exc
        raise

    _discard_current_state(current_state)
    if target_backup is not None and _path_present(target_backup):
        try:
            _remove_path(target_backup)
        except OSError:
            pass


def _point_current_at(target: Path) -> dict[str, str]:
    current = target.parent / "current"
    replacement = _unique_sibling(current, "next")
    try:
        replacement.symlink_to(target, target_is_directory=True)
    except OSError:
        _remove_path(replacement)
        shutil.copytree(target, replacement)

    try:
        if current.is_symlink():
            previous_target = os.readlink(current)
            try:
                os.replace(replacement, current)
                return {"kind": "symlink", "target": previous_target}
            except OSError:
                backup = _unique_sibling(current, "backup")
                current.rename(backup)
                try:
                    replacement.rename(current)
                except Exception:
                    backup.rename(current)
                    raise
                return {"kind": "backup", "path": str(backup)}

        if _path_present(current):
            backup = _unique_sibling(current, "backup")
            current.rename(backup)
            try:
                replacement.rename(current)
            except Exception:
                backup.rename(current)
                raise
            return {"kind": "backup", "path": str(backup)}

        replacement.rename(current)
        return {"kind": "missing"}
    finally:
        if _path_present(replacement):
            _remove_path(replacement)


def _restore_current(runtime_base: Path, state: dict[str, str]) -> None:
    current = runtime_base / "current"
    kind = state.get("kind")
    if kind == "missing":
        _remove_path(current)
        return
    if kind == "backup":
        backup = Path(state["path"])
        _remove_path(current)
        backup.rename(current)
        return
    if kind == "symlink":
        replacement = _unique_sibling(current, "rollback")
        try:
            replacement.symlink_to(state["target"], target_is_directory=True)
            try:
                os.replace(replacement, current)
            except OSError:
                _remove_path(current)
                replacement.rename(current)
        finally:
            if _path_present(replacement):
                _remove_path(replacement)
        return
    raise ValueError(f"unknown current state: {kind}")


def _discard_current_state(state: dict[str, str]) -> None:
    if state.get("kind") != "backup":
        return
    backup = Path(state["path"])
    if _path_present(backup):
        try:
            _remove_path(backup)
        except OSError:
            pass


def _read_lock_metadata(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    try:
        payload = json.loads(raw)
    except ValueError:
        try:
            return {"pid": int(raw)}
        except (TypeError, ValueError):
            return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, int):
        return {"pid": payload}
    return {}


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _lock_is_stale(path: Path, stale_seconds: int = LOCK_STALE_SECONDS) -> bool:
    if path.is_symlink():
        return True
    try:
        stat_result = os.lstat(path)
    except FileNotFoundError:
        return True
    metadata = _read_lock_metadata(path)
    created = metadata.get("created_epoch")
    try:
        created_epoch = float(created)
    except (TypeError, ValueError):
        created_epoch = float(stat_result.st_mtime)
    if max(0.0, time.time() - created_epoch) >= stale_seconds:
        return True
    try:
        pid = int(metadata.get("pid"))
    except (TypeError, ValueError):
        return False
    return not _pid_is_running(pid)


def _stat_fingerprint(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mtime_ns, value.st_size)


def _remove_stale_lock(path: Path) -> bool:
    """Remove a stale lock if it did not change while being inspected."""

    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return True
    if not _lock_is_stale(path):
        return False
    try:
        after = os.lstat(path)
    except FileNotFoundError:
        return True
    if _stat_fingerprint(before) != _stat_fingerprint(after):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _acquire_lock(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            if _remove_stale_lock(path):
                continue
            raise RuntimeError(f"update already running: {path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "created_epoch": int(time.time()), "token": token}, fh, sort_keys=True)
            fh.write("\n")
        return token
    raise RuntimeError(f"could not acquire update lock: {path}")


def _release_lock(path: Path, token: str) -> None:
    if path.is_symlink():
        return
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return
    if _read_lock_metadata(path).get("token") != token:
        return
    try:
        after = os.lstat(path)
    except FileNotFoundError:
        return
    if _stat_fingerprint(before) != _stat_fingerprint(after):
        return
    try:
        path.unlink()
    except OSError:
        return


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
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
