"""Where agent folders live, and which of their files stay on this computer.

One place for the engine to answer "where is the agents root" so the desktop, the daemon and the engine
cannot disagree. The desktop reads the same rule in ``electron/agents/home.ts``:

  ``AGENTLAS_AGENT_HOME`` -> ``<agentlas home>/agents-root.json`` -> ``<agentlas home>/agents``

The shared table ``contracts/test-vectors/agent-home-root-vectors.json`` pins the answers; both sides' tests read it.
Only absolute paths count (no ``~``, no relative paths), so no input can make this module raise.

Everything here only READS. Nothing creates a folder, and a root that the owner configured but that is not
there right now (an unplugged drive) is never replaced by a freshly made default: reads fall back to the
default location, writes are told the root is unavailable (``agents_root_status``).

``safe_store_key`` (memory_scopes) never looks at the disk, so it cannot produce the desktop's collision suffix
(``<name>-<id6>``). The engine therefore never makes a folder from that name; it finds the folder that already
exists (``find_agent_folder``, by the ``owner.json`` the desktop writes) and leaves it alone when there is none.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .upload_limits_generated import AGENT_LOCAL_STATE_DIRECTORIES, AGENT_LOCAL_STATE_PATHS

AGENT_LOCAL_STATE_FOLDER: str = AGENT_LOCAL_STATE_DIRECTORIES[0]
AGENT_OWNER_FILE = "owner.json"
ROOT_SETTINGS_FILE = "agents-root.json"
LEGACY_HOME_NAME = "agentlas-agent"

_STATE_DIRECTORIES = frozenset(name.lower() for name in AGENT_LOCAL_STATE_DIRECTORIES)
_STATE_PATHS = tuple(tuple(part for part in entry.lower().split("/") if part) for entry in AGENT_LOCAL_STATE_PATHS)


def _segments(relative: str) -> list[str]:
    # Case-insensitive file systems treat `.Agentlas-Local` as the same folder, and Windows drops trailing dots and
    # spaces, so `.agentlas-local.` is the same folder too (same normalisation as the desktop's agent-local-state.ts).
    parts = str(relative).replace("\\", "/").lower().split("/")
    return [part.rstrip(". ") for part in parts if part.rstrip(". ") and part != "."]


def is_agent_local_state_name(name: str) -> bool:
    """One path segment: is it the folder that holds this computer's memory and ledgers for the agent?"""
    return any(part in _STATE_DIRECTORIES for part in _segments(name)[:1])


def is_agent_local_state_path(relative: str) -> bool:
    """A relative path (file or folder) inside, or equal to, the agent's local state. Depth does not matter."""
    parts = _segments(relative)
    if any(part in _STATE_DIRECTORIES for part in parts):
        return True
    for state in _STATE_PATHS:
        for start in range(0, len(parts) - len(state) + 1):
            if tuple(parts[start : start + len(state)]) == state:
                return True
    return False


def _absolute_env(name: str) -> Path | None:
    """An absolute path from the environment, else None. `~` and relative paths are NOT expanded: a relative path
    would mean a different folder for every working directory (same rule as the desktop's home.ts)."""
    raw = (os.environ.get(name) or "").strip()
    if not raw or not os.path.isabs(raw):
        return None
    return Path(os.path.abspath(raw))


def _user_home() -> Path:
    try:
        return Path.home()
    except (RuntimeError, KeyError, OSError):
        return Path(os.path.expanduser("~"))


def agentlas_home() -> Path:
    """`AGENTLAS_HOME` when it is an absolute path, else `~/.agentlas`."""
    return _absolute_env("AGENTLAS_HOME") or (_user_home() / ".agentlas")


def default_agents_root() -> Path:
    return agentlas_home() / "agents"


def legacy_agents_home() -> Path:
    """Where earlier engines built agents. Still read, never the default for new ones."""
    return agentlas_home() / LEGACY_HOME_NAME


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except (OSError, ValueError):
        return False


def _settings_root() -> tuple[str, Path | None]:
    """`agents-root.json`: ("none", None) no file; ("invalid", None) unreadable or malformed; ("set", path)."""
    try:
        raw = (agentlas_home() / ROOT_SETTINGS_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return "none", None
    except (OSError, ValueError):
        return "invalid", None
    try:
        parsed = json.loads(raw.lstrip("\ufeff"))
    except ValueError:
        return "invalid", None
    if not isinstance(parsed, dict) or parsed.get("v") != 1 or not isinstance(parsed.get("path"), str):
        return "invalid", None
    if not os.path.isabs(parsed["path"]):
        return "invalid", None
    return "set", Path(os.path.abspath(parsed["path"]))


def _configured_candidates() -> list[Path]:
    """Configured roots in priority order: the environment, then agents-root.json."""
    env = _absolute_env("AGENTLAS_AGENT_HOME")
    if env:
        # An explicit environment root is the only authority: if it is missing, a root from agents-root.json must not
        # quietly take over for writes while reads still use the environment's path (reads and writes would split).
        return [env]
    state, path = _settings_root()
    return [path] if state == "set" and path is not None else []


def explicit_env_root() -> Path | None:
    """The owner's `AGENTLAS_AGENT_HOME` when it is an absolute path. A build may create this folder; a root named only
    in agents-root.json (a drive that can come and go) is never created for it."""
    return _absolute_env("AGENTLAS_AGENT_HOME")


def agents_root() -> Path:
    """The agents root for READING. Never creates anything and never raises.

    An explicit `AGENTLAS_AGENT_HOME` is returned even if the folder is not there (it is the owner's statement);
    a root from agents-root.json that is not a folder right now falls back to the default location for reading only.
    """
    env = _absolute_env("AGENTLAS_AGENT_HOME")
    if env:
        return env
    state, path = _settings_root()
    if state == "set" and path is not None and _is_dir(path):
        return path
    return default_agents_root()


def agents_root_status() -> dict[str, Any]:
    """Write-side verdict, the same answer as the desktop's agentHomeRootStatus().

    `available` is False when a root is configured but is not a folder right now: do not fall back to the default, or
    the owner's memory ends up in two places once the drive comes back. Shape: configured, available, path, and
    `reason` ("missing" | "settings-invalid") when unavailable.
    """
    configured = _configured_candidates()
    for candidate in configured:
        if _is_dir(candidate):
            return {"configured": True, "available": True, "path": str(candidate)}
    if configured:
        return {"configured": True, "available": False, "path": str(configured[0]), "reason": "missing"}
    if _settings_root()[0] == "invalid":
        return {"configured": True, "available": False, "path": None, "reason": "settings-invalid"}
    return {"configured": False, "available": True, "path": str(default_agents_root())}


def agent_homes_to_read() -> list[Path]:
    """Folders that may hold agent packages, newest layout first: the agents root, then the legacy home. Existing only."""
    homes: list[Path] = []
    for candidate in (agents_root(), legacy_agents_home()):
        if _is_dir(candidate) and not any(_same_dir(candidate, seen) for seen in homes):
            homes.append(candidate)
    return homes


def _same_dir(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return left == right


def has_owner_marker(folder: Path) -> bool:
    """True when the desktop manages this folder (``.agentlas-local/owner.json`` is a readable object)."""
    return owner_agent_id(folder) is not None


def owner_agent_id(folder: Path) -> str | None:
    try:
        payload = json.loads((folder / AGENT_LOCAL_STATE_FOLDER / AGENT_OWNER_FILE).read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    agent_id = payload.get("agentId")
    return agent_id if isinstance(agent_id, str) and agent_id else ""


def find_agent_folder(agent_id: str, root: str | Path | None = None) -> Path | None:
    """The existing folder under the agents root that the desktop marked as this agent's, or None. Read-only.

    Kept without a caller yet on purpose: (the agent memory store) must find an agent's folder from the
    `owner.json` the desktop wrote, never from a name `safe_store_key` computes, and this is that lookup.
    """
    if not isinstance(agent_id, str) or not agent_id:
        return None
    base = Path(root).expanduser() if root else agents_root()
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return None
    for entry in entries:
        try:
            if entry.is_dir() and owner_agent_id(entry) == agent_id:
                return entry
        except OSError:
            continue
    return None
