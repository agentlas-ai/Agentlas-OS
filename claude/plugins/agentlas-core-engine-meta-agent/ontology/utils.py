from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: str | bytes, length: int = 24) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:length]


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_loads(value: str | None, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def estimate_tokens(text: str) -> int:
    return max(1, int(len(re.findall(r"\S+", text)) * 1.3))


def normalize_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip(" \t\r\n.:-_"))
    return value


def normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))
