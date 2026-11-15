"""The text checks a memory line gets before it is stored or moved: secret shapes, host-absolute paths. A module of its own with no import of the engine's other packages, so the memory commands
(``one_pack``'s check, import and export, the hook) can ask it without loading the routing and ontology code (about 0.6 s and 320 MB). ``networking.memory`` re-exports every name."""
from __future__ import annotations

import re

SECRET_PATTERNS = [
    re.compile(r"sk-[a-z0-9]{8,}", re.IGNORECASE),
    re.compile(r"akia[0-9a-z]{12,}", re.IGNORECASE),
    re.compile(r"ghp_[a-z0-9_-]{20,}", re.IGNORECASE),
    re.compile(r"xox[baprs]-[a-z0-9-]{8,}", re.IGNORECASE),
    re.compile(r"-----begin", re.IGNORECASE),
    re.compile(r"(api[_-]?key|password|passwd|secret|token)\s*[:=]", re.IGNORECASE),
    re.compile(
        r"\b(api[_-]?key|password|passwd|secret|token|credential)\b"
        r"\s+(?!budget\b|limit\b|usage\b)\S{8,}",
        re.IGNORECASE,
    ),
]
PRIVATE_PATH_PATTERNS = [
    re.compile(r"(?<![a-z0-9])/(?:Users|home|private|Volumes|var|tmp|etc|opt)/[^\s]+", re.IGNORECASE),
    re.compile(r"(?<![a-z0-9])~/(?:[^\s]+)", re.IGNORECASE),
    re.compile(r"\bfile://[^\s]+", re.IGNORECASE),
    re.compile(r"\b[a-z]:\\(?:[^\\\s]+\\)*[^\\\s]+", re.IGNORECASE),
]


def contains_secret(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in SECRET_PATTERNS)


def route_input_issues(text: str) -> list[str]:
    """Classify unsafe route input without retaining or returning its value."""
    issues: list[str] = []
    if contains_secret(text):
        issues.append("route_secret_like_input")
    if any(pattern.search(text or "") for pattern in PRIVATE_PATH_PATTERNS):
        issues.append("route_private_path")
    return issues
