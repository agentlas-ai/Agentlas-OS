"""Explicit plugin registration for hosts without a session-only loader.

Antigravity (`agy`) and Grok (`grok`) cannot load a plugin or MCP server for a
single session (`agy --settings` rejects `mcpServers`; grok has no plugin-dir
option), so unlike the Claude/Codex session launcher these hosts are wired only
when the user asks: `agentlas-os host install <host>` hands the pinned
standalone plugin to the host's own `plugin install`, and `host remove <host>`
uninstalls it. The host owns its configuration writes. The plugin and its MCP
server are named apart from any legacy Agentlas registration so both coexist.
Agentlas Desktop reaches these hosts over ACP and is not involved here.
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
_MAX_COPIES = 8

# Measured: agy 1.4.12, grok 1.0.70.
HOSTS = {
    'antigravity': {
        'cli': 'agy',
        'install': ('plugin', 'install', '{path}'),
        'uninstall': ('plugin', 'uninstall', PLUGIN),
        'list': ('plugin', 'list', '--json'),
        'mcpFile': 'mcp_config.json',
        # agy namespaces a plugin's MCP server as <plugin>_<server>.
        'permissionRule': f'mcp({PLUGIN}_{SERVER}/*)',
    },
    'grok': {
        'cli': 'grok',
        'install': ('plugin', 'install', '{path}', '--trust'),
        'uninstall': ('plugin', 'uninstall', PLUGIN),
        'list': ('plugin', 'list', '--json'),
        'mcpFile': '.mcp.json',
        'permissionRule': None,
    },
}


def _spec(host: str) -> dict:
    if host not in HOSTS:
        raise Conflict('unsupported_plugin_host')
    return HOSTS[host]


def _cli(host: str) -> str:
    path = shutil.which(_spec(host)['cli'])
    if not path:
        raise Conflict(f'{host}_cli_unavailable')
    return path


def _run(host: str, args) -> subprocess.CompletedProcess:
    return subprocess.run([_cli(host), *args], capture_output=True, text=True, timeout=_TIMEOUT, check=False,
                          stdin=subprocess.DEVNULL, **no_console_window())


def _installed(host: str) -> list[dict]:
    """Every installed copy of our plugin; grok keys copies by source path, so several can coexist."""
    listed = _run(host, _spec(host)['list'])
    if listed.returncode != 0:
        raise Conflict(f'{host}_plugin_list_failed')
    text = listed.stdout or '[]'
    try:
        plugins = json.loads(text[text.index('['):text.rindex(']') + 1]) if '[' in text else []
    except ValueError as exc:
        raise Conflict(f'{host}_plugin_list_unreadable') from exc
    return [p for p in plugins if isinstance(p, dict) and p.get('name') == PLUGIN]


def _uninstall_all(host: str) -> subprocess.CompletedProcess | None:
    """Uninstall removes one copy per call (measured grok 1.0.70); repeat until none is left."""
    for _ in range(_MAX_COPIES):
        if not _installed(host):
            return None
        done = _run(host, _spec(host)['uninstall'])
        if done.returncode != 0:
            return done
    if _installed(host):
        raise Conflict(f'{host}_plugin_copies_remain')
    return None


def _pinned_runtime(host: str, entry: dict) -> str | None:
    try:
        config = json.loads((Path(entry['path']) / _spec(host)['mcpFile']).read_text(encoding='utf-8'))
        args = config['mcpServers'][SERVER]['args']
        return str(args[3])  # -B -c <bootstrap> <root> <base> <module> ...
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def _stage(host: str, root: Path, home: Path) -> tuple[Path, str]:
    info = prepare_generation(root, home, 'claude')
    source = Path(info['generation']) / 'plugin'
    target_parent = home / '.agentlas' / 'os-host-plugins' / 'core' / host
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


def _error(host: str, exc: BaseException) -> dict:
    return {'host': host, 'status': 'conflict' if isinstance(exc, Conflict) else 'error',
            'reason': str(exc) if isinstance(exc, Conflict) else type(exc).__name__}


def status(host: str, root, home) -> dict:
    try:
        spec = _spec(host)
        root, home, _ = _identity(root, home, 'claude', 'core')
        _namespace(home)
        entries = _installed(host)
        if not entries:
            return {'host': host, 'status': 'missing', 'hostConfigurationChanged': False,
                    'next': f'agentlas-os host install {host}'}
        entry = entries[-1]
        pinned = _pinned_runtime(host, entry)
        # A second copy would expose a second, older tool set: only one current copy is connected.
        state = ('connected' if len(entries) == 1 and pinned == str(root) and entry.get('enabled') is not False
                 else 'outdated')
        result = {'host': host, 'status': state, 'plugin': PLUGIN, 'mcpServer': SERVER,
                  'version': entry.get('version'), 'runtime': pinned, 'installedCopies': len(entries),
                  'sessionReloadRequired': state == 'connected'}
        if state == 'outdated':
            result['next'] = f'agentlas-os host install {host}'
        if spec['permissionRule']:
            result['headlessPermissionRule'] = spec['permissionRule']
        return result
    except (Conflict, OSError, ValueError, subprocess.SubprocessError) as exc:
        return _error(host, exc)


def install(host: str, root, home) -> dict:
    try:
        spec = _spec(host)
        root, home, _ = _identity(root, home, 'claude', 'core')
        staged, version = _stage(host, root, home)
        failed = _uninstall_all(host)
        if failed is not None:
            return {'host': host, 'status': 'error', 'reason': f'{host}_plugin_uninstall_failed',
                    'detail': (failed.stderr or failed.stdout).strip()[-400:], 'hostConfigurationChanged': None}
        done = _run(host, [part.format(path=staged) for part in spec['install']])
        if done.returncode != 0:
            return {'host': host, 'status': 'error', 'reason': f'{host}_plugin_install_failed',
                    'detail': (done.stderr or done.stdout).strip()[-400:], 'hostConfigurationChanged': None}
        result = status(host, root, home)
        result.update({'hostConfigurationChanged': True, 'installedVersion': version})
        return result
    except (Conflict, OSError, ValueError, subprocess.SubprocessError) as exc:
        return _error(host, exc)


def remove(host: str, root, home) -> dict:
    try:
        _spec(host)
        root, home, _ = _identity(root, home, 'claude', 'core')
        if not _installed(host):
            return {'host': host, 'status': 'missing', 'hostConfigurationChanged': False}
        failed = _uninstall_all(host)
        if failed is not None:
            return {'host': host, 'status': 'error', 'reason': f'{host}_plugin_uninstall_failed',
                    'detail': (failed.stderr or failed.stdout).strip()[-400:]}
        return {**status(host, root, home), 'hostConfigurationChanged': True}
    except (Conflict, OSError, ValueError, subprocess.SubprocessError) as exc:
        return _error(host, exc)
