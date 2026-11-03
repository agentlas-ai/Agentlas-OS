"""Explicit Antigravity (agy) registration for the standalone engine.

Antigravity has no session-only plugin or MCP loader (`agy --settings` rejects
`mcpServers`), so unlike the Claude/Codex session launcher this host is wired
only when the user asks: `agentlas-os host install antigravity` hands the
pinned standalone plugin to agy's own `plugin install`, and `host remove
antigravity` uninstalls it. agy owns its configuration writes. The plugin and
its MCP server are named apart from any legacy Agentlas registration so both
can coexist.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .host_core import Conflict, _identity, _namespace, prepare_generation
from .windows_console import no_console_window

PLUGIN = 'agentlas-os-core'
SERVER = 'agentlas-os'
LEGACY_SERVER = 'hephaestus-network'
_TIMEOUT = 120


def _agy() -> str:
    path = shutil.which('agy')
    if not path:
        raise Conflict('antigravity_cli_unavailable')
    return path


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([_agy(), *args], capture_output=True, text=True, timeout=_TIMEOUT, check=False,
                          stdin=subprocess.DEVNULL, **no_console_window())


def _installed() -> dict | None:
    listed = _run('plugin', 'list', '--json')
    if listed.returncode != 0:
        raise Conflict('antigravity_plugin_list_failed')
    try:
        plugins = json.loads(listed.stdout or '[]')
    except ValueError as exc:
        raise Conflict('antigravity_plugin_list_unreadable') from exc
    return next((p for p in plugins if isinstance(p, dict) and p.get('name') == PLUGIN), None)


def _pinned_runtime(entry: dict) -> str | None:
    try:
        config = json.loads((Path(entry['path']) / 'mcp_config.json').read_text(encoding='utf-8'))
        args = config['mcpServers'][SERVER]['args']
        return str(args[3])  # -B -c <bootstrap> <root> <base> <module> ...
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def _stage(root: Path, home: Path) -> tuple[Path, str]:
    info = prepare_generation(root, home, 'claude')
    source = Path(info['generation']) / 'plugin'
    target_parent = home / '.agentlas' / 'os-host-plugins' / 'core' / 'antigravity'
    for ancestor in (target_parent, *target_parent.parents):
        if ancestor.is_symlink():
            raise Conflict('symlink_path')
    target = target_parent / Path(info['generation']).name
    if target.exists():
        shutil.rmtree(target)
    target_parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=False)
    mcp = target / '.mcp.json'
    config = json.loads(mcp.read_text(encoding='utf-8'))
    servers = config.get('mcpServers') or {}
    if LEGACY_SERVER in servers:
        servers[SERVER] = servers.pop(LEGACY_SERVER)
    mcp.write_text(json.dumps({'mcpServers': servers}, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return target, info['version']


def status(root, home) -> dict:
    try:
        root, home, _ = _identity(root, home, 'claude', 'core')
        _namespace(home)
        entry = _installed()
        if entry is None:
            return {'host': 'antigravity', 'status': 'missing', 'hostConfigurationChanged': False,
                    'next': 'agentlas-os host install antigravity'}
        pinned = _pinned_runtime(entry)
        state = 'connected' if pinned == str(root) and entry.get('enabled') is not False else 'outdated'
        return {'host': 'antigravity', 'status': state, 'plugin': PLUGIN, 'mcpServer': SERVER,
                'version': entry.get('version'), 'enabled': entry.get('enabled'), 'runtime': pinned,
                'skills': entry.get('skills', []), 'sessionReloadRequired': state == 'connected'}
    except (Conflict, OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'host': 'antigravity', 'status': 'conflict' if isinstance(exc, Conflict) else 'error',
                'reason': str(exc) if isinstance(exc, Conflict) else type(exc).__name__}


def install(root, home) -> dict:
    try:
        root, home, _ = _identity(root, home, 'claude', 'core')
        staged, version = _stage(root, home)
        done = _run('plugin', 'install', str(staged))
        if done.returncode != 0:
            return {'host': 'antigravity', 'status': 'error', 'reason': 'antigravity_plugin_install_failed',
                    'detail': (done.stderr or done.stdout).strip()[-400:], 'hostConfigurationChanged': None}
        result = status(root, home)
        result.update({'hostConfigurationChanged': True, 'installedVersion': version})
        return result
    except (Conflict, OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'host': 'antigravity', 'status': 'conflict' if isinstance(exc, Conflict) else 'error',
                'reason': str(exc) if isinstance(exc, Conflict) else type(exc).__name__}


def remove(root, home) -> dict:
    try:
        root, home, _ = _identity(root, home, 'claude', 'core')
        if _installed() is None:
            return {'host': 'antigravity', 'status': 'missing', 'hostConfigurationChanged': False}
        done = _run('plugin', 'uninstall', PLUGIN)
        if done.returncode != 0:
            return {'host': 'antigravity', 'status': 'error', 'reason': 'antigravity_plugin_uninstall_failed',
                    'detail': (done.stderr or done.stdout).strip()[-400:]}
        return {**status(root, home), 'hostConfigurationChanged': True}
    except (Conflict, OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'host': 'antigravity', 'status': 'conflict' if isinstance(exc, Conflict) else 'error',
                'reason': str(exc) if isinstance(exc, Conflict) else type(exc).__name__}
