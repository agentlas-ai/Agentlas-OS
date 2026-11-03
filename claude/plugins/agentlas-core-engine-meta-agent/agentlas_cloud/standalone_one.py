"""Standalone One preference without legacy host wiring or implicit memory."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from typing import Any

from .feature_preferences import _settings_lock, _write_config, feature_enabled

OWNER = "agentlas.os-one-owner.v1"
SCHEMA = "agentlas.os-one-state.v1"


def _plain(path: Path) -> None:
    if any(component.is_symlink() for component in (path, *path.parents)):
        raise ValueError("standalone_one_symlink_refused")


def _read(path: Path) -> dict[str, Any]:
    _plain(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 65536:
            raise ValueError("standalone_one_file_invalid")
        raw = os.read(fd, 65537)
        after = path.lstat()
        if (before.st_ino, before.st_dev) != (after.st_ino, after.st_dev):
            raise ValueError("standalone_one_file_changed")
    finally:
        os.close(fd)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("standalone_one_state_invalid")
    return value


def _root() -> Path:
    # AGENTLAS_ONE_DIR belongs to the legacy/Desktop workspace. Never use it
    # to broaden this standalone preference's ownership boundary.
    root = Path.home() / ".agentlas" / "os-one"
    _plain(root)
    return root


def _snapshot(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"schemaVersion": SCHEMA, "on": False, "name": "One"}
    if _read(root / "owner.json") != {"schemaVersion": OWNER}:
        raise ValueError("standalone_one_ownership_unverified")
    state = _read(root / "state.json")
    if state.get("schemaVersion") != SCHEMA or type(state.get("on")) is not bool or not isinstance(state.get("name"), str):
        raise ValueError("standalone_one_state_invalid")
    return state


def _result(state: dict[str, Any], *, write: bool = False) -> dict[str, Any]:
    enabled = state["on"]
    return {"schemaVersion": SCHEMA, "scope": "standalone_os", "status": "partial" if enabled else "disabled",
            "configured": enabled, "name": state["name"], "writeAttempted": write,
            "activation": {"status": "unverified" if enabled else "disabled",
                           "reason": "standalone_session_activation_not_connected" if enabled else "one_disabled",
                           "hostSettingsModified": False, "legacyStateModified": False, "modelSessionObserved": False,
                           "newSessionRequired": True},
            "memory": {"enabled": feature_enabled("memory-hooks"), "changed": False}}


def update(*, enabled: bool | None = None, name: str | None = None) -> dict[str, Any]:
    if name is not None and (not name.strip() or len(name) > 128 or any(ord(c) < 32 for c in name)):
        raise ValueError("standalone_one_name_invalid")
    root = _root()
    # Reuse the cross-process preference lock; read/merge/write is one critical
    # section, so a concurrent rename and switch cannot discard each other.
    with _settings_lock(None):
        state = _snapshot(root)
        if not root.exists():
            root.mkdir(mode=0o700)
            with (root / "owner.json").open("x", encoding="utf-8") as marker:
                json.dump({"schemaVersion": OWNER}, marker)
        updated = dict(state)
        if enabled is not None:
            updated["on"] = enabled
        if name is not None:
            updated["name"] = name.strip()
        _write_config(root / "state.json", updated)
        observed = _snapshot(root)
        if observed != updated:
            raise ValueError("standalone_one_write_unverified")
    return _result(observed, write=True)


def session_context(host: str, event: str) -> dict[str, Any]:
    """Read-only session injection of the existing registered One composition."""
    if host not in {"claude", "codex"} or event not in {"SessionStart", "UserPromptSubmit"}:
        return {}
    state = _snapshot(_root())
    if state["on"] is not True:
        return {}
    from .prompt_composition import one_directive_for_runtime
    directive = one_directive_for_runtime(name=state["name"])
    # Avoid emitting a stale ON snapshot after a concurrent OFF or rename.
    if _snapshot(_root()) != state:
        return {}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": directive}}


def _host_session(result: dict[str, Any], *, prepare: bool = False) -> dict[str, Any]:
    """Prepare or inspect a session command without starting the host process."""
    if not shutil.which("claude"):
        result["session"] = {"status": "partial", "reason": "claude_session_host_unavailable",
                             "modelSessionObserved": False, "hostConfigurationChanged": False}
        return result
    from . import host_core
    root, home = Path(__file__).resolve().parent.parent, Path.home()
    if prepare:
        prepared = host_core.install(root, home, "claude", plugin_kind="one")
        session = prepared.get("session", prepared)
    else:
        session = host_core.session_plan(root, home, "claude")
    result["session"] = session
    if "sessionCommand" in session:
        result["sessionCommand"] = session["sessionCommand"]
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args.pop(0) if args else "status"
    # A leftover legacy hook must be inert before it consults any state.
    if command in {"stop-hook", "statusline"}:
        print("{}" if command == "stop-hook" else "", end="\n")
        return 0
    if command == "hook":
        parser = argparse.ArgumentParser()
        parser.add_argument("--host", choices=("claude", "codex"), required=True)
        parser.add_argument("--event", choices=("SessionStart", "UserPromptSubmit"), required=True)
        parsed = parser.parse_args(args)
        try:
            result = session_context(parsed.host, parsed.event)
        except (OSError, ValueError, RecursionError):
            result = {}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    try:
        if command == "on":
            result = update(enabled=True, name=" ".join(args) if args else None)
        elif command == "off":
            result = update(enabled=False)
        elif command == "name":
            result = update(name=" ".join(args))
        elif command == "status" and not args:
            result = _result(_snapshot(_root()))
        elif command == "memory":
            result = {"status": "enabled" if feature_enabled("memory-hooks") else "disabled", "feature": "memory-hooks", "writeAttempted": False}
        else:
            result = {"status": "partial", "reason": "standalone_operation_not_connected", "operation": command,
                      "writeAttempted": False, "hostSettingsModified": False}
        if command in {"on", "off", "name"} or (command == "status" and not args):
            result = _host_session(result, prepare=command == "on")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1 if result["status"] == "partial" else 0
    except (OSError, ValueError, RecursionError) as exc:
        # A post-replace fsync failure is not proof of an unchanged preference.
        print(json.dumps({"status": "error", "reason": "standalone_one_preference_failed",
                          "errorType": type(exc).__name__, "stateMayHaveChanged": command in {"on", "off", "name"},
                          "hostSettingsModified": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
