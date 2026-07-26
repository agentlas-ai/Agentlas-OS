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


def _json_version(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        return None
    version = payload.get("version") if isinstance(payload, dict) else None
    return _normal_version(version) or None


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
    source_bound = str(source) in text and f'[plugins."{PLUGIN_ID}"]' in text
    return {
        "host": "codex",
        "detected": shutil.which("codex") is not None and (cache.is_dir() or PLUGIN_ID in text),
        "versions": versions,
        "targetVersion": target,
        "sourceBound": source_bound,
        "current": target in versions and source_bound,
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
    source_bound = str(source / "claude") in marketplace_text
    return {
        "host": "claude",
        "detected": shutil.which("claude") is not None and (cache.is_dir() or PLUGIN_ID in text),
        "versions": versions,
        "targetVersion": target,
        "sourceBound": source_bound,
        "current": target in versions and source_bound,
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
    source_root = source.expanduser().resolve()
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
    if not status["detected"] or status["current"]:
        return {**status, "status": "not_installed" if not status["detected"] else "current"}
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
    return {**verified, "status": "updated" if verified["current"] else "pending_restart", "steps": steps}


def _reconcile_claude(home: Path, source: Path, target: str, execute: bool) -> dict[str, Any]:
    status = _claude_status(home, source, target)
    if not status["detected"] or status["current"]:
        return {**status, "status": "not_installed" if not status["detected"] else "current"}
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
    return {**verified, "status": "updated" if verified["current"] else "pending_reload", "steps": steps}


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
    source_root = source.expanduser().resolve()
    target = _normal_version(release_tag)
    if not target:
        return {"status": "blocked", "reason": "release_tag_missing", "hosts": []}
    hosts = [
        _reconcile_codex(home_dir, source_root, target, execute),
        _reconcile_claude(home_dir, source_root, target, execute),
        _reconcile_gemini(home_dir, source_root, target, execute),
    ]
    failed = [host for host in hosts if host.get("status") in {"blocked", "rolled_back"}]
    return {
        "schemaVersion": "agentlas.host-plugin-reconcile.v1",
        "status": "partial" if failed else "pass",
        "release": f"v{target}",
        "hosts": hosts,
    }
