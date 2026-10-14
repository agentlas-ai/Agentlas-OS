"""Portable parity adapter for the canonical prompt-order.ts ordering contract."""
from __future__ import annotations
import json

PROMPT_ORDER_REVISION = 1
CANONICAL_SOURCE_SHA256 = "ab0dd8ca8d6bad93a380850548a1bbe6e0118c20229f13ddbab55a71ae9f8428"
STABILITY_ORDER = ("fixed-policy", "versioned-content", "configuration", "task-context", "turn-context", "final-boundary")
_DECLARED: dict[str, dict] = {}


def compose_prompt(parts: list[dict], separator: str = "\n") -> str:
    for part in parts:
        if not str(part.get("id", "")).strip() or not part.get("changeTriggers"):
            raise ValueError("prompt-module-declaration-required")
        if part["stability"] not in STABILITY_ORDER:
            raise ValueError("prompt-stability-invalid")
        declaration = {key: part[key] for key in ("id", "stability", "changeTriggers")}
        declaration.update(revision=part.get("revision", 1), order=part.get("order", 0))
        _DECLARED.setdefault(json.dumps(declaration, sort_keys=True), declaration)
    ordered = sorted(enumerate(parts), key=lambda row: (STABILITY_ORDER.index(row[1]["stability"]), row[1].get("order", 0), row[0]))
    return separator.join(part["text"] for _, part in ordered if part.get("text", "").strip())


def declared_modules() -> list[dict]:
    return [{**part, "changeTriggers": list(part["changeTriggers"])} for part in _DECLARED.values()]
