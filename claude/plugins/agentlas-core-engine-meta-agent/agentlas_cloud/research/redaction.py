"""Redaction helpers for research receipts and diagnostic summaries."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterable


_SENSITIVE_ENV_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "AUTH", "BEARER", "CREDENTIAL")
_COMMAND_ENV_VARS = {
    "AGENTLAS_AGENT_BROWSER_BIN",
    "AGENTLAS_BROWSER_USE_SNAPSHOT_CMD",
    "AGENTLAS_HYPERAGENT_SNAPSHOT_CMD",
    "AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD",
    "AGENTLAS_STAGEHAND_SNAPSHOT_CMD",
    "AGENTLAS_STEEL_SNAPSHOT_CMD",
}
_SECRET_FLAGS = {
    "--api-key",
    "--apikey",
    "--auth",
    "--authorization",
    "--bearer-token",
    "--credential",
    "--credentials",
    "--password",
    "--secret",
    "--token",
    "--access-token",
    "--refresh-token",
}

_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)([^\s,;]+)")
_FLAG_RE = re.compile(
    r"(?i)(--(?:api[-_]?key|auth(?:orization)?|bearer[-_]?token|credential|credentials|password|secret|token|access[-_]?token|refresh[-_]?token)(?:=|\s+))([^\s,;]+)"
)
_ASSIGNMENT_RE = re.compile(
    r"(?i)\b((?:api[-_]?key|auth(?:orization)?|bearer[-_]?token|credential|credentials|password|secret|token|access[-_]?token|refresh[-_]?token)\s*[:=]\s*)([^\s,;]+)"
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_COMMON_SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{12,}|[A-Za-z0-9_./+-]{40,})\b"
)


def redact_secret_values(value: str, extra_values: Iterable[str] | None = None) -> str:
    """Return *value* with known secret-looking substrings replaced."""

    text = str(value or "")
    for secret in _secret_values(extra_values):
        text = text.replace(secret, "[redacted]")
    text = _BEARER_RE.sub(r"\1[redacted]", text)
    text = _FLAG_RE.sub(r"\1[redacted]", text)
    text = _ASSIGNMENT_RE.sub(r"\1[redacted]", text)
    text = _JWT_RE.sub("[redacted]", text)
    return _COMMON_SECRET_RE.sub("[redacted]", text)


def redacted_exception_reason(exc: BaseException, *, max_length: int = 180, prefix: str = "") -> str:
    """Return a bounded exception reason safe for receipts."""

    reason = redact_secret_values(f"{type(exc).__name__}:{str(exc)}")
    if prefix:
        reason = f"{prefix}{reason}"
    return reason[:max_length]


def _secret_values(extra_values: Iterable[str] | None) -> list[str]:
    values: set[str] = set()
    for item in extra_values or ():
        if _is_redactable_value(item):
            values.add(str(item))
    for name, raw in os.environ.items():
        if not raw:
            continue
        if _looks_sensitive_env(name):
            if _is_redactable_value(raw):
                values.add(raw)
        if name in _COMMAND_ENV_VARS:
            values.update(_secrets_from_command(raw))
    return sorted(values, key=len, reverse=True)


def _looks_sensitive_env(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in _SENSITIVE_ENV_MARKERS)


def _secrets_from_command(raw: str) -> set[str]:
    try:
        argv = shlex.split(raw)
    except ValueError:
        argv = raw.split()
    values: set[str] = set()
    for index, arg in enumerate(argv):
        flag, sep, inline_value = arg.partition("=")
        if sep and flag.lower() in _SECRET_FLAGS and _is_redactable_value(inline_value):
            values.add(inline_value)
            continue
        if arg.lower() in _SECRET_FLAGS and index + 1 < len(argv) and _is_redactable_value(argv[index + 1]):
            values.add(argv[index + 1])
    return values


def _is_redactable_value(value: object) -> bool:
    text = str(value or "")
    return len(text) >= 4 and text not in {"true", "false", "none", "null"}
