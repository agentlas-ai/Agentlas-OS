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
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

PLUGIN_ID = "hephaestus@agentlas-core-engine"
MARKETPLACE_ID = "agentlas-core-engine"
COMMAND_TIMEOUT_SECONDS = 90
HOST_ACTIVATION_MARKER = "host-plugin-activation.json"
_PROCESS_SNAPSHOT_UNSET = object()


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
    exact_target = _exact_cache_current(
        cache,
        target,
        Path(".claude-plugin") / "plugin.json",
    )
    try:
        expected_path = expected_path.resolve()
    except OSError:
        pass
    first: dict[str, Any] | None = None
    if isinstance(plugins, dict):
        for plugin_id, entries in plugins.items():
            if str(plugin_id) != PLUGIN_ID:
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
                if exact_target and recorded == target and candidate == expected_path and manifest_version == target:
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
    if not _exact_cache_current(
        cache,
        target,
        Path(".claude-plugin") / "plugin.json",
    ):
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
    for plugin_id, entries in plugins.items():
        if str(plugin_id) != PLUGIN_ID:
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


def _elapsed_seconds(value: str) -> float | None:
    """Parse portable ps etime values such as 12:03 or 2-01:02:03."""

    try:
        days = 0
        clock = value.strip()
        if "-" in clock:
            day_text, clock = clock.split("-", 1)
            days = int(day_text)
        fields = [int(item) for item in clock.split(":")]
        if len(fields) == 2:
            hours, minutes, seconds = 0, fields[0], fields[1]
        elif len(fields) == 3:
            hours, minutes, seconds = fields
        else:
            return None
        return float(days * 86400 + hours * 3600 + minutes * 60 + seconds)
    except (TypeError, ValueError):
        return None


def _environment_value(text: str, key: str) -> str | None:
    """Read one selected value from ``ps eww`` output without retaining env."""

    pattern = re.compile(
        rf"(?:^|\s){re.escape(key)}=(.*?)(?=\s[A-Za-z_][A-Za-z0-9_]*=|$)"
    )
    matches = list(pattern.finditer(text))
    return matches[-1].group(1) if matches else None


def _selected_process_environments(pids: list[int]) -> dict[int, dict[str, str] | None] | None:
    """Read only host-scope variables for a bounded set of processes.

    A process name alone is not enough on a shared machine: another account or
    an isolated HOME can run Codex/Claude at the same time. Never retain the
    rest of the process environment because it can contain credentials. On
    macOS every matching PID is queried in one ``ps`` call, so host count cannot
    multiply the five-second timeout inside the 30-second one-hop bridge.
    """

    if not pids:
        return {}
    keys = ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR")
    proc_root = Path("/proc")
    if proc_root.is_dir():
        result: dict[int, dict[str, str] | None] = {}
        for pid in pids:
            try:
                entries = (proc_root / str(pid) / "environ").read_bytes().split(b"\0")
            except OSError:
                result[pid] = None
                continue
            selected: dict[str, str] = {}
            for entry in entries:
                key_bytes, separator, value = entry.partition(b"=")
                if not separator:
                    continue
                key = key_bytes.decode("utf-8", errors="ignore")
                if key in keys:
                    selected[key] = value.decode("utf-8", errors="ignore")
            result[pid] = selected
        return result
    try:
        result = subprocess.run(
            ["ps", "eww", "-p", ",".join(str(pid) for pid in sorted(set(pids))), "-o", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    selected_by_pid: dict[int, dict[str, str] | None] = {pid: None for pid in pids}
    for line in (result.stdout or "").splitlines():
        try:
            pid_text, raw = line.strip().split(None, 1)
            pid = int(pid_text)
        except (ValueError, IndexError):
            continue
        selected_by_pid[pid] = {
            key: value
            for key in keys
            if (value := _environment_value(raw, key)) is not None
        }
    return selected_by_pid


def _process_snapshot() -> list[dict[str, Any]] | None:
    """Read one process table for the whole host reconciliation.

    Cache count must never multiply process-table probes. Windows remains
    explicitly unknown until a command-line/start-time provider is available;
    callers fail closed instead of reporting a loaded release they cannot see.
    """

    if os.name == "nt":
        return None
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,uid=,etime=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    observed_at = time.time()
    rows: list[dict[str, Any]] = []
    for line in (result.stdout or "").splitlines():
        try:
            pid_text, uid_text, elapsed_text, command = line.strip().split(None, 3)
            pid = int(pid_text)
            uid = int(uid_text)
        except (ValueError, IndexError):
            continue
        elapsed = _elapsed_seconds(elapsed_text)
        row: dict[str, Any] = {
            "pid": pid,
            "uid": uid,
            "startedEpoch": observed_at - elapsed if elapsed is not None else None,
            "command": command,
        }
        rows.append(row)
    current_uid = os.getuid() if hasattr(os, "getuid") else None
    host_rows = [
        row
        for row in rows
        if row.get("uid") == current_uid
        and any(
            _host_command_matches(host, str(row.get("command") or ""))
            for host in ("codex", "claude")
        )
    ]
    selected_by_pid = _selected_process_environments(
        [int(row["pid"]) for row in host_rows]
    )
    for row in host_rows:
        selected = selected_by_pid.get(int(row["pid"])) if selected_by_pid is not None else None
        if selected is not None:
            row["environmentKnown"] = True
            row["home"] = selected.get("HOME")
            row["codexHome"] = selected.get("CODEX_HOME")
            row["claudeConfigDir"] = selected.get("CLAUDE_CONFIG_DIR")
        else:
            row["environmentKnown"] = False
    return rows


def _plugin_process_state(
    path: Path,
    process_snapshot: list[dict[str, Any]] | None | object = _PROCESS_SNAPSHOT_UNSET,
) -> str:
    """Return ``active``, ``inactive``, or ``unknown`` for a cache path."""

    snapshot = _process_snapshot() if process_snapshot is _PROCESS_SNAPSHOT_UNSET else process_snapshot
    if snapshot is None:
        return "unknown"
    try:
        needle = str(path.expanduser().resolve())
    except OSError:
        needle = str(path.expanduser())
    for row in snapshot:
        if row.get("pid") == os.getpid():
            continue
        command = str(row.get("command") or "")
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
        manifest_path = child / manifest
        value = (
            _json_version(manifest_path)
            if manifest_path.is_file() and not manifest_path.is_symlink()
            else None
        )
        # A version-named cache is immutable.  Old updaters briefly rewrote an
        # existing directory with newer bytes, so a manifest alone cannot make
        # `cache/1.2.26` prove that an exact `cache/1.2.34` target exists.
        if value and value == _normal_version(child.name):
            versions.append(value)
    return sorted(set(versions))


def _exact_cache_current(root: Path, target: str, manifest: Path) -> bool:
    """Verify one immutable target-named cache without following links."""

    target_path = root / target
    manifest_path = target_path / manifest
    return bool(
        target_path.is_dir()
        and not target_path.is_symlink()
        and manifest_path.is_file()
        and not manifest_path.is_symlink()
        and _json_version(manifest_path) == target
    )


def _active_cache_paths(
    root: Path,
    process_snapshot: list[dict[str, Any]] | None,
) -> tuple[list[str], bool]:
    """Return live versioned cache paths and whether inspection was incomplete.

    Host ledgers describe what the *next* process will load.  A process that is
    already running can keep an older cache path open after that ledger moves,
    so checking only the ledger target loses the reload boundary on the second
    reconciliation pass.
    """

    active: list[str] = []
    inspection_unknown = False
    if not root.is_dir():
        return active, inspection_unknown
    try:
        children = list(root.iterdir())
    except OSError:
        return active, True
    for child in children:
        if not child.is_dir() or child.is_symlink():
            continue
        state = _plugin_process_state(child, process_snapshot)
        if state == "active":
            active.append(str(child))
        elif state == "unknown":
            inspection_unknown = True
    return active, inspection_unknown


def _host_command_matches(host: str, command: str) -> bool:
    """Recognize processes that can retain one host's loaded plugin state."""

    lowered = command.strip().lower()
    # macOS launch wrappers use ``wrapper -- /path/to/real-host ...``. Only the
    # executable before that delimiter owns this process; matching a later
    # argument would count both wrapper and child as plugin hosts.
    executable_segment = lowered.split(" -- ", 1)[0]
    if host == "codex":
        if any(
            marker in lowered
            for marker in (
                "crashpad_handler",
                " --type=",
                "/frameworks/",
                "codex computer use.app",
                "cua_node",
            )
        ):
            return False
        return bool(re.match(r"^(?:.*[/\\])?codex(?:\.exe)?(?:\s|$)", executable_segment))
    if host == "claude":
        if any(marker in lowered for marker in ("crashpad_handler", " --type=", "/frameworks/")):
            return False
        # The consumer Claude desktop shell launches separate Claude Code host
        # children. Its shell itself does not load the Code plugin cache.
        desktop_shell = "/applications/claude.app/contents/macos/claude"
        if executable_segment == desktop_shell or executable_segment.startswith(desktop_shell + " "):
            return False
        return bool(re.match(r"^(?:.*[/\\])?claude(?:\.exe)?(?:\s|$)", executable_segment))
    return False


def _host_process_scope(host: str, row: dict[str, Any], home: Path) -> str:
    """Return ``match``, ``mismatch``, or ``unknown`` for one host process."""

    current_uid = os.getuid() if hasattr(os, "getuid") else None
    row_uid = row.get("uid")
    if isinstance(row_uid, int) and current_uid is not None and row_uid != current_uid:
        return "mismatch"
    if row.get("environmentKnown") is not True:
        return "unknown"

    process_home = Path(str(row["home"])) if row.get("home") else None
    if host == "codex":
        expected = Path(os.environ.get("CODEX_HOME") or home / ".codex")
        actual = Path(str(row["codexHome"])) if row.get("codexHome") else (
            process_home / ".codex" if process_home is not None else None
        )
        if actual is not None:
            return "match" if _canonical_path(actual) == _canonical_path(expected) else "mismatch"
    if host == "claude":
        expected = home / ".claude"
        actual = Path(str(row["claudeConfigDir"])) if row.get("claudeConfigDir") else (
            process_home / ".claude" if process_home is not None else None
        )
        if actual is not None:
            return "match" if _canonical_path(actual) == _canonical_path(expected) else "mismatch"
    return "unknown"


def _host_process_evidence(
    host: str,
    process_snapshot: list[dict[str, Any]] | None,
    activation_epoch: float | None,
    home: Path,
) -> dict[str, Any]:
    """Measure host sessions that predate the exact-cache activation."""

    if process_snapshot is None:
        return {"state": "unknown", "pids": [], "stalePids": []}
    candidates = [
        row
        for row in process_snapshot
        if row.get("pid") != os.getpid()
        and _host_command_matches(host, str(row.get("command") or ""))
    ]
    rows = [row for row in candidates if _host_process_scope(host, row, home) == "match"]
    scope_unknown = [
        row for row in candidates if _host_process_scope(host, row, home) == "unknown"
    ]
    if not rows and not scope_unknown:
        return {"state": "inactive", "pids": [], "stalePids": []}
    pids = sorted(int(row["pid"]) for row in [*rows, *scope_unknown])
    unknown_pids = sorted(int(row["pid"]) for row in scope_unknown)
    if (
        scope_unknown
        or activation_epoch is None
        or any(not isinstance(row.get("startedEpoch"), (int, float)) for row in rows)
    ):
        return {
            "state": "unknown",
            "pids": pids,
            "stalePids": [],
            "scopeUnknownPids": unknown_pids,
        }
    # ``ps etime`` has whole-second precision and therefore overestimates a
    # process start by up to one second. Fail closed: only a process measured
    # more than one second after activation is provably a fresh host session.
    stale = sorted(
        int(row["pid"])
        for row in rows
        if float(row["startedEpoch"]) <= activation_epoch + 1.0
    )
    return {
        "state": "active",
        "pids": pids,
        "stalePids": stale,
        "scopeUnknownPids": unknown_pids,
    }


def _activation_marker_path(home: Path) -> Path:
    runtime_base = Path(
        os.environ.get("HEPHAESTUS_RUNTIME_BASE")
        or home / ".agentlas" / "runtime"
    )
    return runtime_base / HOST_ACTIVATION_MARKER


def _read_activation_marker(home: Path) -> dict[str, Any]:
    try:
        payload = json.loads(_activation_marker_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _manifest_mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _activation_epoch(home: Path, host: str, target: str, manifest: Path) -> float | None:
    marker = _read_activation_marker(home)
    hosts = marker.get("hosts") if isinstance(marker, dict) else None
    row = hosts.get(host) if isinstance(hosts, dict) else None
    manifest_mtime_ns = _manifest_mtime_ns(manifest)
    manifest_epoch = manifest_mtime_ns / 1_000_000_000 if manifest_mtime_ns is not None else None
    activated_epoch = row.get("activatedEpoch") if isinstance(row, dict) else None
    if (
        isinstance(row, dict)
        and _normal_version(row.get("release")) == target
        and row.get("cacheManifestMtimeNs") == manifest_mtime_ns
        and isinstance(activated_epoch, (int, float))
        and manifest_epoch is not None
        and float(activated_epoch) >= manifest_epoch - 1.0
        and float(activated_epoch) <= time.time() + 60.0
    ):
        return float(activated_epoch)
    # An archive manifest can predate the moment this host activated it. Using
    # that artifact timestamp would let a process started after packaging but
    # before installation look current on the first reconciliation pass.
    return None


def _record_activation_markers(home: Path, target: str, hosts: list[dict[str, Any]]) -> None:
    """Persist a transition cutoff once persistent next-load state is current."""

    path = _activation_marker_path(home)
    if not path.parent.is_dir():
        return
    previous = _read_activation_marker(home)
    previous_hosts = previous.get("hosts") if isinstance(previous.get("hosts"), dict) else {}
    next_hosts = dict(previous_hosts)
    changed = False
    for row in hosts:
        host = str(row.get("host") or "")
        if host not in {"codex", "claude"} or not row.get("nextLoadCurrent"):
            continue
        suffix = ".codex-plugin" if host == "codex" else ".claude-plugin"
        manifest = (
            (Path(os.environ.get("CODEX_HOME") or home / ".codex") if host == "codex" else home / ".claude")
            / "plugins"
            / "cache"
            / MARKETPLACE_ID
            / "hephaestus"
            / target
            / suffix
            / "plugin.json"
        )
        mtime_ns = _manifest_mtime_ns(manifest)
        prior = next_hosts.get(host)
        if (
            isinstance(prior, dict)
            and _normal_version(prior.get("release")) == target
            and prior.get("cacheManifestMtimeNs") == mtime_ns
        ):
            continue
        next_hosts[host] = {
            "release": f"v{target}",
            "activatedEpoch": time.time(),
            "cacheManifestMtimeNs": mtime_ns,
        }
        changed = True
    if not changed:
        return
    payload = {
        "schemaVersion": "agentlas.host-plugin-activation.v1",
        "hosts": next_hosts,
    }
    try:
        _write_json_atomic(path, payload)
    except OSError:
        # A denied feedback-marker write must not roll back an activated
        # runtime, but process feedback remains fail-closed until it can be
        # measured against a real host activation timestamp.
        return


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


def _codex_status(
    home: Path,
    source: Path,
    target: str,
    process_snapshot: list[dict[str, Any]] | None | object = _PROCESS_SNAPSHOT_UNSET,
) -> dict[str, Any]:
    snapshot = _process_snapshot() if process_snapshot is _PROCESS_SNAPSHOT_UNSET else process_snapshot
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    cache = codex_home / "plugins" / "cache" / MARKETPLACE_ID / "hephaestus"
    versions = _cache_versions(cache, Path(".codex-plugin") / "plugin.json")
    config = codex_home / "config.toml"
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        text = ""
    source_bound = _source_bound(text, source) and f'[plugins."{PLUGIN_ID}"]' in text
    manifest = cache / target / ".codex-plugin" / "plugin.json"
    exact_cache_current = _exact_cache_current(
        cache,
        target,
        Path(".codex-plugin") / "plugin.json",
    )
    persisted_current = exact_cache_current and source_bound
    active_paths, cache_process_unknown = _active_cache_paths(cache, snapshot)
    target_path = cache / target
    stale_active_paths = [path for path in active_paths if _canonical_path(Path(path)) != _canonical_path(target_path)]
    activation_epoch = _activation_epoch(home, "codex", target, manifest)
    host_process = _host_process_evidence("codex", snapshot, activation_epoch, home)
    process_state_unknown = cache_process_unknown or host_process["state"] == "unknown"
    active_process = (
        "active"
        if active_paths or host_process["state"] == "active"
        else "unknown"
        if process_state_unknown
        else "inactive"
    )
    stale_session = bool(stale_active_paths or host_process["stalePids"])
    installed_state = cache.is_dir() or PLUGIN_ID in text
    cli_available = shutil.which("codex") is not None
    return {
        "host": "codex",
        "detected": installed_state,
        "cliAvailable": cli_available,
        "versions": versions,
        "targetVersion": target,
        "sourceBound": source_bound,
        "exactCacheCurrent": exact_cache_current,
        "nextLoadCurrent": persisted_current,
        "activeProcess": active_process,
        "activeInstallPaths": active_paths,
        "staleActiveInstallPaths": stale_active_paths,
        "hostProcessPids": host_process["pids"],
        "staleHostPids": host_process["stalePids"],
        "scopeUnknownHostPids": host_process.get("scopeUnknownPids", []),
        "activationEpoch": activation_epoch,
        "loadedReleaseVerified": active_process == "active" and not stale_session and not process_state_unknown,
        "current": persisted_current and not stale_session and not process_state_unknown,
        "codexHome": str(codex_home),
    }


def _claude_status(
    home: Path,
    source: Path,
    target: str,
    process_snapshot: list[dict[str, Any]] | None | object = _PROCESS_SNAPSHOT_UNSET,
) -> dict[str, Any]:
    snapshot = _process_snapshot() if process_snapshot is _PROCESS_SNAPSHOT_UNSET else process_snapshot
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
    active_paths, cache_process_unknown = _active_cache_paths(cache, snapshot)
    target_path = cache / target
    stale_active_paths = [
        path
        for path in active_paths
        if _canonical_path(Path(path)) != _canonical_path(target_path)
    ]
    manifest = cache / target / ".claude-plugin" / "plugin.json"
    exact_cache_current = _exact_cache_current(
        cache,
        target,
        Path(".claude-plugin") / "plugin.json",
    )
    next_load_current = exact_cache_current and source_bound and bool(ledger["current"])
    activation_epoch = _activation_epoch(home, "claude", target, manifest)
    host_process = _host_process_evidence("claude", snapshot, activation_epoch, home)
    process_state_unknown = cache_process_unknown or host_process["state"] == "unknown"
    active_process = (
        "active"
        if active_paths or host_process["state"] == "active"
        else "unknown"
        if process_state_unknown
        else "inactive"
    )
    stale_session = bool(stale_active_paths or host_process["stalePids"])
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
        "activeInstallPaths": active_paths,
        "staleActiveInstallPaths": stale_active_paths,
        "hostProcessPids": host_process["pids"],
        "staleHostPids": host_process["stalePids"],
        "scopeUnknownHostPids": host_process.get("scopeUnknownPids", []),
        "activationEpoch": activation_epoch,
        "exactCacheCurrent": exact_cache_current,
        "nextLoadCurrent": next_load_current,
        "loadedReleaseVerified": active_process == "active" and not stale_session and not process_state_unknown,
        "current": next_load_current and not stale_session and not process_state_unknown,
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
    process_snapshot = _process_snapshot()
    return {
        "schemaVersion": "agentlas.host-plugin-status.v1",
        "release": f"v{target}",
        "hosts": [
            _codex_status(home_dir, source_root, target, process_snapshot),
            _claude_status(home_dir, source_root, target, process_snapshot),
            _gemini_status(home_dir, source_root, target),
        ],
    }


def _reconcile_codex(
    home: Path,
    source: Path,
    target: str,
    execute: bool,
    process_snapshot: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    status = _codex_status(home, source, target, process_snapshot)
    if not status["detected"]:
        return {
            **status,
            "status": "not_installed",
            "reloadRequired": False,
        }
    if status["nextLoadCurrent"] and (
        status.get("staleActiveInstallPaths") or status.get("staleHostPids")
    ):
        return {
            **status,
            "status": "pending_reload",
            "reason": "active_plugin_process",
            "reloadRequired": True,
        }
    if status["nextLoadCurrent"] and status.get("activeProcess") == "unknown":
        return {
            **status,
            "status": "pending_restart",
            "reason": "plugin_process_state_unknown",
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
    verified = _codex_status(home, source, target, process_snapshot)
    return {
        **verified,
        "status": "pending_reload" if verified["current"] else "pending_restart",
        "reloadRequired": True,
        "reason": "host_process_not_reloaded" if verified["current"] else "host_restart_required",
        "steps": steps,
    }


def _reconcile_claude(
    home: Path,
    source: Path,
    target: str,
    execute: bool,
    process_snapshot: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    status = _claude_status(home, source, target, process_snapshot)
    if not status["detected"]:
        return {
            **status,
            "status": "not_installed",
            "reloadRequired": False,
        }
    if status["nextLoadCurrent"] and (
        status.get("staleActiveInstallPaths") or status.get("staleHostPids")
    ):
        return {
            **status,
            "status": "pending_reload",
            "reason": "active_plugin_process",
            "reloadRequired": True,
        }
    if status["nextLoadCurrent"] and status.get("activeProcess") == "unknown":
        return {
            **status,
            "status": "pending_restart",
            "reason": "plugin_process_state_unknown",
            "reloadRequired": True,
        }
    if status["current"]:
        return {**status, "status": "current", "reloadRequired": False}
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
        verified = _claude_status(home, source, target, process_snapshot)
        if previous_process_state != "inactive":
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
    if status.get("activeProcess") != "inactive":
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
    verified = _claude_status(home, source, target, process_snapshot)
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
    codex_exact = _exact_cache_current(
        codex_cache,
        target,
        Path(".codex-plugin") / "plugin.json",
    )
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
    claude_exact = _exact_cache_current(
        claude_cache,
        target,
        Path(".claude-plugin") / "plugin.json",
    )
    claude_source_bound = _source_bound(marketplace_text, source_root, "claude")
    ledger_before = _claude_ledger_state(installed, claude_cache, target)
    ledger_migration: dict[str, Any] = {
        "ok": not claude_detected,
        "changed": False,
        "reason": "host_not_installed" if not claude_detected else "exact_target_cache_missing",
    }
    if claude_detected and claude_exact:
        ledger_migration = _migrate_claude_ledger(installed, claude_cache, target)
    # The bridge has just materialized/migrated persistent next-load state.
    # Record that host-local activation before comparing already-running host
    # sessions, otherwise an old archive mtime can yield a false first pass.
    marker_seed = [
        _codex_status(home_dir, source_root, target, []),
        _claude_status(home_dir, source_root, target, []),
    ]
    _record_activation_markers(home_dir, target, marker_seed)
    process_snapshot = _process_snapshot()

    def transition_row(row: dict[str, Any]) -> dict[str, Any]:
        if not row.get("detected"):
            return {**row, "status": "not_installed", "current": True, "reloadRequired": False}
        if not row.get("nextLoadCurrent"):
            return {**row, "status": "blocked", "current": False, "reloadRequired": False}
        pending = bool(
            row.get("staleActiveInstallPaths")
            or row.get("staleHostPids")
            or row.get("activeProcess") == "unknown"
        )
        return {
            **row,
            "status": "pending_reload" if pending else "current",
            "current": not pending,
            "reloadRequired": pending,
            **({"reason": "host_process_not_reloaded"} if pending else {}),
        }

    codex_row = transition_row(_codex_status(home_dir, source_root, target, process_snapshot))
    claude_row = transition_row(_claude_status(home_dir, source_root, target, process_snapshot))
    claude_row.update({"ledgerBefore": ledger_before, "ledgerMigration": ledger_migration})
    hosts = [codex_row, claude_row]
    _record_activation_markers(home_dir, target, hosts)
    blockers = [
        {"host": host["host"], "reason": "persistent_state_not_current"}
        for host in hosts
        if host["status"] == "blocked"
    ]
    unsafe_paths = sorted({path for paths in legacy.values() for path in paths})
    pending_hosts = sorted(
        str(host["host"])
        for host in hosts
        if host.get("reloadRequired")
    )
    status = "blocked" if blockers else "pending_reload" if pending_hosts else "pass"
    return {
        "schemaVersion": "agentlas.host-plugin-transition.v1",
        "status": status,
        "release": f"v{target}",
        "bounded": True,
        "vendorCliInvoked": False,
        "reloadRequired": bool(pending_hosts),
        "pendingHosts": pending_hosts,
        "unsafeLegacyInPlace": bool(unsafe_paths),
        "unsafeLegacyPaths": unsafe_paths,
        "reason": (
            "legacy_updater_replaced_cache_in_place"
            if unsafe_paths and pending_hosts
            else "host_process_not_reloaded"
            if pending_hosts
            else None
        ),
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
    # The runtime updater can materialize exact persistent state immediately
    # before this call. Seed its host-local cutoff before evaluating processes
    # that may still retain the previous release.
    marker_seed = [
        _codex_status(home_dir, source_root, target, []),
        _claude_status(home_dir, source_root, target, []),
    ]
    _record_activation_markers(home_dir, target, marker_seed)
    process_snapshot = _process_snapshot()
    hosts = [
        _reconcile_codex(home_dir, source_root, target, execute, process_snapshot),
        _reconcile_claude(home_dir, source_root, target, execute, process_snapshot),
        _reconcile_gemini(home_dir, source_root, target, execute),
    ]
    _record_activation_markers(home_dir, target, hosts)
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
