"""Fail-open, capture-time-redacted observations for runtime subagent hooks.

The host runtime owns spawning, scheduling, cancellation, and the visible
answer. This module only records bounded metadata when a host provides a
SubagentStart/SubagentStop hook. A malformed payload, unavailable project
directory, or write failure always returns an empty hook response so native
runtime behavior is never gated by Agentlas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping


SCHEMA_VERSION = "agentlas.subagent-observation.v1"
OBSERVATION_DIR = "observations"
OBSERVATION_FILE = "subagents.jsonl"
MAX_STDIN_BYTES = 256_000
MAX_RECORD_BYTES = 8 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 1_200
EVENTS = frozenset({"SubagentStart", "SubagentStop"})

_SECRET_PATTERNS = (
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"\b(?:sk|rk|pk)-(?:ant|proj|live|test)?-?[A-Za-z0-9_-]{16,}\b", re.I),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b", re.I),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(
        r"\b(?:authorization\s*:\s*bearer|password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)\s*[:=]?\s*[^\s,;]+",
        re.I,
    ),
    re.compile(r"(?<![\w.@])[^\s]+@[^\s]+\.[^\s]+"),
    re.compile(r"(?:/Users/|/home/|/private/var/|[A-Za-z]:[\\/])[^\s\"']+"),
)


def _redact(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[:limit]


def _safe_identifier(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = _redact(value, 256)
    if not text or text == "[REDACTED]" or "/" in text or "\\" in text:
        return None
    return text


def _read_payload() -> dict[str, Any]:
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
        if not raw or len(raw) > MAX_STDIN_BYTES:
            return {}
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _payload_value(payload: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = payload.get(name)
        if value not in (None, ""):
            return value
    return None


def _project_root(payload: Mapping[str, Any]) -> Path | None:
    raw = _payload_value(
        payload,
        "cwd",
        "workspaceRoot",
        "workspace_root",
        "projectDir",
        "project_dir",
        "directory",
    )
    if not isinstance(raw, str) or not raw.strip():
        raw = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("PWD") or os.getcwd()
    try:
        current = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if current.is_file():
        current = current.parent
    if not current.is_dir():
        return None
    for root in (current, *current.parents):
        agentlas_dir = root / ".agentlas"
        try:
            if agentlas_dir.is_dir() and not agentlas_dir.is_symlink():
                return root
        except OSError:
            return None
    return None


def _event_value(payload: Mapping[str, Any], event: str | None) -> str:
    candidate = event or _payload_value(payload, "hook_event_name", "hookEventName", "event")
    return candidate if isinstance(candidate, str) and candidate in EVENTS else ""


def _record_path(root: Path) -> Path | None:
    agentlas_dir = root / ".agentlas"
    observations = agentlas_dir / OBSERVATION_DIR
    try:
        if agentlas_dir.is_symlink() or observations.exists() and observations.is_symlink():
            return None
        observations.mkdir(mode=0o700, exist_ok=True)
        if not observations.is_dir():
            return None
        path = observations / OBSERVATION_FILE
        if path.exists() and (path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES):
            return None
        return path
    except OSError:
        return None


def _append(path: Path, record: Mapping[str, Any]) -> bool:
    try:
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        if len(line) > MAX_RECORD_BYTES:
            return False
        with path.open("ab") as handle:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            handle.write(line)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


def observe(
    payload: Mapping[str, Any],
    *,
    event: str | None = None,
    host: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Record one bounded observation and return a passive host-hook response."""

    event_name = _event_value(payload, event)
    if not event_name:
        return {}
    root = _project_root(payload)
    if root is None:
        return {}
    path = _record_path(root)
    if path is None:
        return {}
    message = _payload_value(
        payload,
        "last_assistant_message",
        "lastAssistantMessage",
        "message",
        "output",
        "result",
    )
    redacted_message = _redact(message)
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "event": event_name,
        "host": _safe_identifier(host or _payload_value(payload, "host")) or "unknown",
        "observedAt": observed_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agentId": _safe_identifier(_payload_value(payload, "agent_id", "agentId")),
        "agentType": _safe_identifier(_payload_value(payload, "agent_type", "agentType")),
        "stopHookActive": payload.get("stop_hook_active") is True
        or payload.get("stopHookActive") is True,
        "hasMessage": bool(redacted_message),
        "messagePreview": redacted_message,
        "messageDigest": "sha256:" + hashlib.sha256(redacted_message.encode("utf-8")).hexdigest(),
        "source": "host-hook",
    }
    record = {key: value for key, value in record.items() if value is not None}
    _append(path, record)
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default=None)
    parser.add_argument("--host", default=None)
    args = parser.parse_args(argv)
    try:
        observe(_read_payload(), event=args.event, host=args.host)
    except Exception:
        # Observation is supplemental. Never turn a hook exception into a host
        # runtime failure or a blocked native subagent.
        pass
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
