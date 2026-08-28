"""Reconcile vendor plugin registries to one verified Agentlas OS release.

Runtime adapter files are already copied from a digest-verified release archive.
This module additionally moves the host-owned plugin registries so Codex,
Claude Code, and Gemini stop advertising or reloading an older marketplace
version.  Each host is isolated and restored from a private local snapshot if
its CLI fails.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PLUGIN_ID = "hephaestus@agentlas-core-engine"
MARKETPLACE_ID = "agentlas-core-engine"
COMMAND_TIMEOUT_SECONDS = 90


def _normal_version(value: Any) -> str:
    return str(value or "").strip().lstrip("vV")


def _canonical_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser()


def _stable_adapter_source(source: Path, home: Path) -> Path:
    """Return the version-independent `current/...` path for an adapter bundle.

    Registering the versioned directory pins a host marketplace to one release:
    the next update installs a new version, nothing re-registers the host, and
    the host keeps loading the old bundle — or loses the plugin entirely once
    that version directory is gone. Measured on a live machine: the Claude
    marketplace was bound to `.../runtime/1.1.110/host_adapters/claude` while
    1.2.0 was installed.

    The bundle is still VALIDATED at its versioned path by the caller; only the
    path handed to host registries becomes stable. os.path.abspath is used
    instead of resolve() on purpose: resolve() would follow the symlink straight
    back to the versioned directory and reintroduce the pin.
    """
    current = home / ".agentlas" / "runtime" / "current"
    candidate = current / source.name
    if not candidate.is_dir():
        # Nothing usable to point at. Never hand a host registry a path that does
        # not exist: Path.resolve() is non-strict, so a dangling `current`
        # symlink and a pruned version directory resolve to the SAME missing
        # string and would otherwise compare equal.
        return source
    try:
        if candidate.resolve() == source.resolve():
            return Path(os.path.abspath(str(candidate)))
        # `current` is a real directory, not a symlink: this is the normal
        # Windows layout, because symlink creation there needs admin rights or
        # Developer Mode and update.py falls back to copytree. Comparing
        # resolved paths can never match in that layout, so compare the release
        # marker instead — same release means the stable path is equivalent.
        if not current.is_symlink():
            current_release = _release_marker(current)
            source_release = _release_marker(source.parent)
            if current_release and current_release == source_release:
                return Path(os.path.abspath(str(candidate)))
    except OSError:
        return source
    return source


def _release_marker(root: Path) -> str | None:
    """The RELEASE marker a runtime directory carries, or None."""
    try:
        return _normal_version((root / "RELEASE").read_text(encoding="utf-8")) or None
    except (OSError, ValueError):
        return None


def _source_bound(text: str, source: Path, leaf: str = "") -> bool:
    """A host may record either the stable path we passed or the version it
    resolves to, so accept both rather than reconciling on every single run."""
    if not text:
        return False
    stable = source / leaf if leaf else source
    candidates = {str(stable)}
    try:
        resolved = source.resolve()
        candidates.add(str(resolved / leaf if leaf else resolved))
    except OSError:
        pass
    return any(candidate in text for candidate in candidates)


def _json_version(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        return None
    version = payload.get("version") if isinstance(payload, dict) else None
    return _normal_version(version) or None


def _claude_ledger_state(installed: Path, cache: Path, target: str) -> dict[str, Any]:
    """Check Claude's version/path ledger against the materialized target.

    The updater historically rewrote old cache directories in place, leaving
    Claude's ledger at (for example) ``1.2.26`` while the files inside claimed
    ``1.2.32``. Cache contents alone therefore cannot prove that a new Claude
    process will load the requested release.
    """

    try:
        payload = json.loads(installed.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    plugins = payload.get("plugins") if isinstance(payload, dict) else None
    expected_path = cache / target
    try:
        expected_path = expected_path.resolve()
    except OSError:
        pass
    first: dict[str, Any] | None = None
    if isinstance(plugins, dict):
        for plugin_id, entries in plugins.items():
            if not str(plugin_id).startswith(PLUGIN_ID.split("@", 1)[0] + "@"):
                continue
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                install_path = entry.get("installPath")
                recorded = _normal_version(entry.get("version"))
                if not isinstance(install_path, str) or not install_path.strip():
                    continue
                candidate = Path(install_path).expanduser()
                try:
                    candidate = candidate.resolve()
                except OSError:
                    pass
                state = {
                    "entryFound": True,
                    "version": recorded or None,
                    "installPath": str(install_path),
                    "current": False,
                }
                if first is None:
                    first = state
                manifest_version = _json_version(candidate / ".claude-plugin" / "plugin.json")
                if recorded == target and candidate == expected_path and manifest_version == target:
                    return {**state, "current": True}
    return first or {
        "entryFound": False,
        "version": None,
        "installPath": None,
        "current": False,
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Persist one host ledger without exposing a partially written file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.agentlas-{os.getpid()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _migrate_claude_ledger(installed: Path, cache: Path, target: str) -> dict[str, Any]:
    """Point Claude's next load at the verified exact-version cache.

    This intentionally changes only Agentlas entries in Claude's ledger.  It
    does not uninstall, replace, or delete the old cache directory, so a live
    Claude process can keep using the bytes it already loaded until restart.
    """

    target_path = cache / target
    manifest_version = _json_version(target_path / ".claude-plugin" / "plugin.json")
    if manifest_version != target:
        return {"ok": False, "changed": False, "reason": "verified_target_cache_missing"}
    try:
        payload = json.loads(installed.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "changed": False, "reason": "ledger_unreadable", "error": str(exc)}
    plugins = payload.get("plugins") if isinstance(payload, dict) else None
    if not isinstance(plugins, dict):
        return {"ok": False, "changed": False, "reason": "ledger_plugins_missing"}

    changed = False
    entry_found = False
    prefix = PLUGIN_ID.split("@", 1)[0] + "@"
    for plugin_id, entries in plugins.items():
        if not str(plugin_id).startswith(prefix):
            continue
        candidates = entries if isinstance(entries, list) else [entries]
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            entry_found = True
            if _normal_version(entry.get("version")) != target or entry.get("installPath") != str(target_path):
                entry["version"] = target
                entry["installPath"] = str(target_path)
                changed = True
    if not entry_found:
        return {"ok": False, "changed": False, "reason": "ledger_entry_missing"}
    if changed:
        try:
            _write_json_atomic(installed, payload)
        except OSError as exc:
            return {"ok": False, "changed": False, "reason": "ledger_write_failed", "error": str(exc)}
    verified = _claude_ledger_state(installed, cache, target)
    return {
        "ok": bool(verified["current"]),
        "changed": changed,
        "reason": None if verified["current"] else "ledger_verify_failed",
        "ledgerVersion": verified["version"],
        "ledgerInstallPath": verified["installPath"],
    }


def _plugin_process_state(path: Path) -> str:
    """Return ``active``, ``inactive``, or ``unknown`` for a cache path."""

    if os.name == "nt":
        return "unknown"
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    try:
        needle = str(path.expanduser().resolve())
    except OSError:
        needle = str(path.expanduser())
    for line in (result.stdout or "").splitlines():
        try:
            pid_text, command = line.strip().split(None, 1)
            if int(pid_text) == os.getpid():
                continue
        except (ValueError, IndexError):
            continue
        if any(
            marker in command
            for marker in (f"{needle}/", f"{needle} ", f"{needle}\t", f'{needle}"', f"{needle}'")
        ) or command.endswith(needle):
            return "active"
    return "inactive"


def _cache_versions(root: Path, manifest: Path) -> list[str]:
    versions: list[str] = []
    if not root.is_dir():
        return versions
    for child in root.iterdir():
        if not child.is_dir() or child.is_symlink():
            continue
        value = _json_version(child / manifest)
        if value:
            versions.append(value)
    return sorted(set(versions))


def _run(command: list[str], *, home: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    try:
        completed = subprocess.run(
            command,
            cwd=str(home),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "exitCode": None, "error": type(exc).__name__}
    return {
        "ok": completed.returncode == 0,
        "exitCode": completed.returncode,
        "error": None if completed.returncode == 0 else (completed.stderr or completed.stdout or "command_failed").strip()[-400:],
    }


class _Snapshot:
    def __init__(self, paths: list[Path]):
        self.paths = paths
        self.tmp: tempfile.TemporaryDirectory[str] | None = None
        self.root: Path | None = None
        self.records: list[tuple[Path, Path, bool]] = []

    def __enter__(self) -> "_Snapshot":
        self.tmp = tempfile.TemporaryDirectory(prefix="agentlas-host-update-")
        self.root = Path(self.tmp.name)
        for index, path in enumerate(self.paths):
            backup = self.root / str(index)
            existed = path.exists() or path.is_symlink()
            if existed:
                if path.is_dir() and not path.is_symlink():
                    shutil.copytree(path, backup)
                else:
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, backup, follow_symlinks=False)
            self.records.append((path, backup, existed))
        return self

    def restore(self) -> None:
        for path, backup, existed in reversed(self.records):
            if path.exists() or path.is_symlink():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            if not existed:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if backup.is_dir() and not backup.is_symlink():
                shutil.copytree(backup, path)
            else:
                shutil.copy2(backup, path, follow_symlinks=False)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.tmp is not None:
            self.tmp.cleanup()


def _run_required(command: list[str], *, home: Path, steps: list[dict[str, Any]]) -> bool:
    result = _run(command, home=home)
    steps.append({"command": command[:3], **result})
    return bool(result["ok"])


def _run_best_effort(command: list[str], *, home: Path, steps: list[dict[str, Any]]) -> None:
    result = _run(command, home=home)
    steps.append({"command": command[:3], **result, "bestEffort": True})


def _codex_status(home: Path, source: Path, target: str) -> dict[str, Any]:
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    cache = codex_home / "plugins" / "cache" / MARKETPLACE_ID / "hephaestus"
    versions = _cache_versions(cache, Path(".codex-plugin") / "plugin.json")
    config = codex_home / "config.toml"
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        text = ""
    source_bound = _source_bound(text, source) and f'[plugins."{PLUGIN_ID}"]' in text
    persisted_current = target in versions and source_bound
    active_paths: list[str] = []
    process_state_unknown = False
    if cache.is_dir():
        for child in cache.iterdir():
            if not child.is_dir() or child.is_symlink():
                continue
            state = _plugin_process_state(child)
            if state == "active":
                active_paths.append(str(child))
            elif state == "unknown":
                process_state_unknown = True
    target_path = cache / target
    stale_active_paths = [path for path in active_paths if _canonical_path(Path(path)) != _canonical_path(target_path)]
    installed_state = cache.is_dir() or PLUGIN_ID in text
    cli_available = shutil.which("codex") is not None
    return {
        "host": "codex",
        "detected": installed_state,
        "cliAvailable": cli_available,
        "versions": versions,
        "targetVersion": target,
        "sourceBound": source_bound,
        "exactCacheCurrent": target in versions,
        "nextLoadCurrent": persisted_current,
        "activeProcess": "active" if active_paths else "unknown" if process_state_unknown else "inactive",
        "activeInstallPaths": active_paths,
        "staleActiveInstallPaths": stale_active_paths,
        "loadedReleaseVerified": bool(active_paths) and not stale_active_paths and str(target_path) in active_paths,
        "current": persisted_current and not stale_active_paths,
        "codexHome": str(codex_home),
    }


def _claude_status(home: Path, source: Path, target: str) -> dict[str, Any]:
    plugin_root = home / ".claude" / "plugins"
    cache = plugin_root / "cache" / MARKETPLACE_ID / "hephaestus"
    versions = _cache_versions(cache, Path(".claude-plugin") / "plugin.json")
    installed = plugin_root / "installed_plugins.json"
    try:
        text = installed.read_text(encoding="utf-8")
    except OSError:
        text = ""
    marketplace = plugin_root / "known_marketplaces.json"
    try:
        marketplace_text = marketplace.read_text(encoding="utf-8")
    except OSError:
        marketplace_text = ""
    source_bound = _source_bound(marketplace_text, source, "claude")
    ledger = _claude_ledger_state(installed, cache, target)
    active_process = (
        _plugin_process_state(Path(ledger["installPath"]))
        if ledger.get("installPath")
        else "inactive"
    )
    installed_state = cache.is_dir() or PLUGIN_ID in text
    cli_available = shutil.which("claude") is not None
    return {
        "host": "claude",
        "detected": installed_state,
        "cliAvailable": cli_available,
        "versions": versions,
        "targetVersion": target,
        "sourceBound": source_bound,
        "ledgerCurrent": bool(ledger["current"]),
        "ledgerVersion": ledger["version"],
        "ledgerInstallPath": ledger["installPath"],
        "activeProcess": active_process,
        "exactCacheCurrent": target in versions,
        "nextLoadCurrent": target in versions and source_bound and bool(ledger["current"]),
        "loadedReleaseVerified": active_process == "inactive" and bool(ledger["current"]),
        "current": target in versions and source_bound and bool(ledger["current"]),
    }


def _gemini_status(home: Path, source: Path, target: str) -> dict[str, Any]:
    extension = home / ".gemini" / "extensions" / "hephaestus"
    installed_version = _json_version(extension / "gemini-extension.json")
    install_meta = extension / ".gemini-extension-install.json"
    try:
        meta_text = install_meta.read_text(encoding="utf-8")
    except OSError:
        meta_text = ""
    stable_source = home / ".gemini" / "hephaestus-extension-source"
    source_bound = str(stable_source) in meta_text
    return {
        "host": "gemini",
        "detected": extension.is_dir() or stable_source.is_dir(),
        "version": installed_version,
        "targetVersion": target,
        "sourceBound": source_bound,
        "current": installed_version == target and source_bound,
        "cliAvailable": shutil.which("gemini") is not None,
    }


def host_plugin_status(source: Path, release_tag: str, *, home: Path | None = None) -> dict[str, Any]:
    home_dir = (home or Path.home()).expanduser().resolve()
    source_root = _stable_adapter_source(source.expanduser().resolve(), home_dir)
    target = _normal_version(release_tag)
    return {
        "schemaVersion": "agentlas.host-plugin-status.v1",
        "release": f"v{target}",
        "hosts": [
            _codex_status(home_dir, source_root, target),
            _claude_status(home_dir, source_root, target),
            _gemini_status(home_dir, source_root, target),
        ],
    }


def _reconcile_codex(home: Path, source: Path, target: str, execute: bool) -> dict[str, Any]:
    status = _codex_status(home, source, target)
    if not status["detected"]:
        return {
            **status,
            "status": "not_installed",
            "reloadRequired": False,
        }
    if status["nextLoadCurrent"] and status.get("staleActiveInstallPaths"):
        return {
            **status,
            "status": "pending_reload",
            "reason": "active_plugin_process",
            "reloadRequired": True,
        }
    if status["current"]:
        return {**status, "status": "current", "reloadRequired": False}
    # Codex' install/remove commands may replace the whole marketplace cache.
    # Never run them while any versioned cache is live (or process inspection
    # is inconclusive), even when the persistent source binding still needs
    # repair. The next command after closing Codex retries this reconciliation.
    if status.get("activeProcess") != "inactive":
        process_state = status.get("activeProcess")
        return {
            **status,
            "status": "pending_restart",
            "reason": (
                "active_plugin_process_blocks_persistent_repair"
                if process_state == "active"
                else "plugin_process_state_unknown"
            ),
            "reloadRequired": True,
            "retryRequired": True,
            "retryCommand": "hephaestus hep-update",
        }
    if not status["cliAvailable"]:
        return {
            **status,
            "status": "blocked",
            "reason": "vendor_cli_unavailable",
            "reloadRequired": False,
        }
    commands = [
        ["codex", "plugin", "remove", PLUGIN_ID],
        ["codex", "plugin", "marketplace", "remove", MARKETPLACE_ID],
        ["codex", "plugin", "marketplace", "add", str(source)],
        ["codex", "plugin", "add", PLUGIN_ID],
    ]
    if not execute:
        return {**status, "status": "planned", "commands": [command[:3] for command in commands]}
    codex_home = Path(status["codexHome"])
    protected = [
        codex_home / "config.toml",
        codex_home / "plugins" / "cache" / MARKETPLACE_ID,
        codex_home / ".tmp" / "marketplaces" / MARKETPLACE_ID,
    ]
    steps: list[dict[str, Any]] = []
    with _Snapshot(protected) as snapshot:
        _run_best_effort(commands[0], home=home, steps=steps)
        _run_best_effort(commands[1], home=home, steps=steps)
        if not _run_required(commands[2], home=home, steps=steps) or not _run_required(commands[3], home=home, steps=steps):
            snapshot.restore()
            return {**status, "status": "rolled_back", "steps": steps}
    verified = _codex_status(home, source, target)
    return {
        **verified,
        "status": "pending_reload" if verified["current"] else "pending_restart",
        "reloadRequired": True,
        "reason": "host_process_not_reloaded" if verified["current"] else "host_restart_required",
        "steps": steps,
    }


def _reconcile_claude(home: Path, source: Path, target: str, execute: bool) -> dict[str, Any]:
    status = _claude_status(home, source, target)
    if not status["detected"] or status["current"]:
        return {
            **status,
            "status": "not_installed" if not status["detected"] else "current",
            "reloadRequired": False,
        }
    marketplace_source = source / "claude"
    commands = [
        ["claude", "plugin", "uninstall", PLUGIN_ID],
        ["claude", "plugin", "marketplace", "remove", MARKETPLACE_ID],
        ["claude", "plugin", "marketplace", "add", str(marketplace_source), "--scope", "user"],
        ["claude", "plugin", "install", PLUGIN_ID, "--scope", "user"],
        ["claude", "plugin", "enable", PLUGIN_ID],
    ]
    if not execute:
        return {**status, "status": "planned", "commands": [command[:3] for command in commands]}
    plugin_root = home / ".claude" / "plugins"
    installed = plugin_root / "installed_plugins.json"
    cache = plugin_root / "cache" / MARKETPLACE_ID / "hephaestus"
    previous_install_path = status.get("ledgerInstallPath")
    previous_process_state = status.get("activeProcess", "inactive")
    ledger_migration = _migrate_claude_ledger(installed, cache, target)
    if ledger_migration.get("ok"):
        verified = _claude_status(home, source, target)
        if previous_install_path and previous_process_state != "inactive":
            reason = (
                "active_plugin_process"
                if previous_process_state == "active"
                else "plugin_process_state_unknown"
            )
            return {
                **verified,
                "status": "pending_reload",
                "reason": reason,
                "reloadRequired": True,
                "loadedReleaseVerified": False,
                "current": False,
                "activeProcess": previous_process_state,
                "activeInstallPath": previous_install_path,
                "ledgerMigration": ledger_migration,
            }
        return {
            **verified,
            "status": "updated" if verified["current"] else "pending_reload",
            "reloadRequired": not bool(verified["current"]),
            "ledgerMigration": ledger_migration,
        }

    # Do not ask Claude to uninstall/reinstall a cache directory while a live
    # Claude/MCP process still points at the old ledger path. The target payload
    # must remain intact and the incomplete persisted transition is explicit.
    if status.get("ledgerInstallPath") and status.get("activeProcess") != "inactive":
        reason = (
            "active_plugin_process"
            if status.get("activeProcess") == "active"
            else "plugin_process_state_unknown"
        )
        return {
            **status,
            "status": "pending_reload",
            "reason": reason,
            "reloadRequired": True,
            "ledgerMigration": ledger_migration,
        }
    if not status["cliAvailable"]:
        return {
            **status,
            "status": "blocked",
            "reason": "vendor_cli_unavailable",
            "reloadRequired": False,
            "ledgerMigration": ledger_migration,
        }
    protected = [
        plugin_root / "installed_plugins.json",
        plugin_root / "known_marketplaces.json",
        plugin_root / "cache" / MARKETPLACE_ID,
        plugin_root / "marketplaces" / MARKETPLACE_ID,
    ]
    steps: list[dict[str, Any]] = []
    with _Snapshot(protected) as snapshot:
        _run_best_effort(commands[0], home=home, steps=steps)
        _run_best_effort(commands[1], home=home, steps=steps)
        for command in commands[2:4]:
            if not _run_required(command, home=home, steps=steps):
                snapshot.restore()
                return {**status, "status": "rolled_back", "steps": steps}
        _run_best_effort(commands[4], home=home, steps=steps)
    verified = _claude_status(home, source, target)
    return {
        **verified,
        "status": "updated" if verified["current"] else "pending_reload",
        "reloadRequired": not bool(verified["current"]),
        "steps": steps,
        "ledgerMigration": ledger_migration,
    }


def reconcile_host_plugin_transition_without_cli(
    source: Path,
    release_tag: str,
    *,
    home: Path | None = None,
    unsafe_legacy_paths: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Finish one legacy-updater transition without invoking vendor CLIs.

    The v1.2.32 updater executes the target release's memory-hook installer only
    after it has activated the new runtime. That subprocess has a strict
    30-second parent timeout, so this bridge is deliberately filesystem-only:
    exact caches must already be materialized, and only Agentlas' Claude ledger
    entries may be migrated. Host state is then reread from disk.
    """

    home_dir = (home or Path.home()).expanduser().resolve()
    source_root = _stable_adapter_source(source.expanduser().resolve(), home_dir)
    target = _normal_version(release_tag)
    legacy = unsafe_legacy_paths or {}
    if not target:
        return {
            "schemaVersion": "agentlas.host-plugin-transition.v1",
            "status": "blocked",
            "reason": "release_tag_missing",
            "hosts": [],
        }

    codex_home = Path(os.environ.get("CODEX_HOME") or home_dir / ".codex")
    codex_cache = codex_home / "plugins" / "cache" / MARKETPLACE_ID / "hephaestus"
    codex_config = codex_home / "config.toml"
    try:
        codex_text = codex_config.read_text(encoding="utf-8")
    except OSError:
        codex_text = ""
    codex_detected = codex_cache.is_dir() or PLUGIN_ID in codex_text
    codex_exact = _json_version(
        codex_cache / target / ".codex-plugin" / "plugin.json"
    ) == target
    codex_source_bound = _source_bound(codex_text, source_root) and f'[plugins."{PLUGIN_ID}"]' in codex_text

    plugin_root = home_dir / ".claude" / "plugins"
    claude_cache = plugin_root / "cache" / MARKETPLACE_ID / "hephaestus"
    installed = plugin_root / "installed_plugins.json"
    marketplace = plugin_root / "known_marketplaces.json"
    try:
        installed_text = installed.read_text(encoding="utf-8")
    except OSError:
        installed_text = ""
    try:
        marketplace_text = marketplace.read_text(encoding="utf-8")
    except OSError:
        marketplace_text = ""
    claude_detected = claude_cache.is_dir() or PLUGIN_ID in installed_text
    claude_exact = _json_version(
        claude_cache / target / ".claude-plugin" / "plugin.json"
    ) == target
    claude_source_bound = _source_bound(marketplace_text, source_root, "claude")
    ledger_before = _claude_ledger_state(installed, claude_cache, target)
    ledger_migration: dict[str, Any] = {
        "ok": not claude_detected,
        "changed": False,
        "reason": "host_not_installed" if not claude_detected else "exact_target_cache_missing",
    }
    if claude_detected and claude_exact:
        ledger_migration = _migrate_claude_ledger(installed, claude_cache, target)
    ledger_after = _claude_ledger_state(installed, claude_cache, target)

    hosts = [
        {
            "host": "codex",
            "detected": codex_detected,
            "cliAvailable": shutil.which("codex") is not None,
            "exactCacheCurrent": codex_exact,
            "sourceBound": codex_source_bound,
            "current": (not codex_detected) or (codex_exact and codex_source_bound),
            "status": (
                "not_installed"
                if not codex_detected
                else "current"
                if codex_exact and codex_source_bound
                else "blocked"
            ),
        },
        {
            "host": "claude",
            "detected": claude_detected,
            "cliAvailable": shutil.which("claude") is not None,
            "exactCacheCurrent": claude_exact,
            "sourceBound": claude_source_bound,
            "ledgerBefore": ledger_before,
            "ledgerMigration": ledger_migration,
            "ledgerCurrent": bool(ledger_after["current"]),
            "ledgerVersion": ledger_after["version"],
            "ledgerInstallPath": ledger_after["installPath"],
            "current": (
                (not claude_detected)
                or (claude_exact and claude_source_bound and bool(ledger_after["current"]))
            ),
            "status": (
                "not_installed"
                if not claude_detected
                else "current"
                if claude_exact and claude_source_bound and bool(ledger_after["current"])
                else "blocked"
            ),
        },
    ]
    blockers = [
        {"host": host["host"], "reason": "persistent_state_not_current"}
        for host in hosts
        if host["status"] == "blocked"
    ]
    unsafe_paths = sorted({path for paths in legacy.values() for path in paths})
    unsafe_hosts = sorted(host for host, paths in legacy.items() if paths)
    status = "blocked" if blockers else "pending_reload" if unsafe_paths else "pass"
    return {
        "schemaVersion": "agentlas.host-plugin-transition.v1",
        "status": status,
        "release": f"v{target}",
        "bounded": True,
        "vendorCliInvoked": False,
        "reloadRequired": bool(unsafe_paths),
        "pendingHosts": unsafe_hosts,
        "unsafeLegacyInPlace": bool(unsafe_paths),
        "unsafeLegacyPaths": unsafe_paths,
        "reason": "legacy_updater_replaced_cache_in_place" if unsafe_paths else None,
        "blockers": blockers,
        "hosts": hosts,
    }


def _replace_directory(source: Path, destination: Path) -> None:
    tmp = destination.parent / f".{destination.name}.agentlas-update-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(source, tmp)
    if destination.exists():
        shutil.rmtree(destination)
    tmp.rename(destination)


def _reconcile_gemini(home: Path, source: Path, target: str, execute: bool) -> dict[str, Any]:
    status = _gemini_status(home, source, target)
    if not status["detected"] or status["current"]:
        return {**status, "status": "not_installed" if not status["detected"] else "current"}
    extension_source = source / "gemini" / "extension"
    stable_source = home / ".gemini" / "hephaestus-extension-source"
    installed = home / ".gemini" / "extensions" / "hephaestus"
    if not execute:
        return {**status, "status": "planned"}
    if not extension_source.is_dir():
        return {**status, "status": "blocked", "reason": "verified_extension_source_missing"}
    steps: list[dict[str, Any]] = []
    with _Snapshot([stable_source, installed]) as snapshot:
        _replace_directory(extension_source, stable_source)
        if shutil.which("gemini"):
            _run_best_effort(["gemini", "extensions", "uninstall", "hephaestus"], home=home, steps=steps)
            command = [
                "gemini",
                "extensions",
                "install",
                str(stable_source),
                "--consent",
                "--skip-settings",
            ]
            if not _run_required(command, home=home, steps=steps):
                snapshot.restore()
                return {**status, "status": "rolled_back", "steps": steps}
        else:
            _replace_directory(extension_source, installed)
            (installed / ".gemini-extension-install.json").write_text(
                json.dumps({"source": str(stable_source), "type": "local"}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    verified = _gemini_status(home, source, target)
    return {**verified, "status": "updated" if verified["current"] else "pending_restart", "steps": steps}


def reconcile_host_plugins(
    source: Path,
    release_tag: str,
    *,
    home: Path | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    home_dir = (home or Path.home()).expanduser().resolve()
    source_root = _stable_adapter_source(source.expanduser().resolve(), home_dir)
    target = _normal_version(release_tag)
    if not target:
        return {"status": "blocked", "reason": "release_tag_missing", "hosts": []}
    hosts = [
        _reconcile_codex(home_dir, source_root, target, execute),
        _reconcile_claude(home_dir, source_root, target, execute),
        _reconcile_gemini(home_dir, source_root, target, execute),
    ]
    failed = [host for host in hosts if host.get("status") in {"blocked", "rolled_back"}]
    pending = [
        host["host"]
        for host in hosts
        if host.get("status") in {"pending_reload", "pending_restart"}
        or bool(host.get("reloadRequired"))
    ]
    return {
        "schemaVersion": "agentlas.host-plugin-reconcile.v1",
        "status": "partial" if failed else "pending_reload" if pending else "pass",
        "release": f"v{target}",
        "reloadRequired": bool(pending),
        "pendingHosts": pending,
        "hosts": hosts,
    }
