"""Contracts for the Agentlas Research Engine.

These dataclasses are deliberately dependency-free so browser, platform, and
hosted search modules can be loaded only when policy selects them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


DEFAULT_MAX_COST = {"tokens": 20000, "requests": 20, "seconds": 120}


def _stable_hash(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8", "ignore")).hexdigest()[:length]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(value)]
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def _int_between(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))


@dataclass
class ResearchModuleManifest:
    module_id: str
    capabilities: list[str]
    weight: str = "light"
    slot: str = "reader"
    activation: str = "auto"
    requires: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    default_state: str = "available"
    privacy: str = "no_raw_token_to_model"
    failure_modes: list[str] = field(default_factory=list)
    install_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.module_id,
            "capabilities": list(self.capabilities),
            "weight": self.weight,
            "slot": self.slot,
            "activation": self.activation,
            "requires": list(self.requires),
            "permissions": list(self.permissions),
            "default_state": self.default_state,
            "privacy": self.privacy,
            "failure_modes": list(self.failure_modes),
            "install_hint": self.install_hint,
        }


@dataclass
class ResearchRequest:
    query: str
    intent: str = "read"
    source_hints: list[str] = field(default_factory=list)
    loadout: str = "auto"
    freshness: str = "live"
    depth: str = "quick"
    follow_results: int = 0
    query_variants: list[str] = field(default_factory=list)
    allowed_modules: list[str] = field(default_factory=list)
    forbidden_modules: list[str] = field(default_factory=list)
    privacy_scope: str = "public"
    max_weight: str = ""
    max_cost: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_MAX_COST))

    @classmethod
    def from_value(cls, value: "ResearchRequest | dict[str, Any] | str") -> "ResearchRequest":
        if isinstance(value, ResearchRequest):
            return value
        if isinstance(value, str):
            return cls(query=value)
        if isinstance(value, dict):
            payload = dict(value)
            payload.setdefault("query", "")
            return cls(
                query=str(payload.get("query") or ""),
                intent=str(payload.get("intent") or "read"),
                source_hints=_string_list(payload.get("source_hints")),
                loadout=str(payload.get("loadout") or "auto"),
                freshness=str(payload.get("freshness") or "live"),
                depth=str(payload.get("depth") or "quick"),
                follow_results=_int_between(payload.get("follow_results"), minimum=0, maximum=10),
                query_variants=_string_list(payload.get("query_variants")),
                allowed_modules=_string_list(payload.get("allowed_modules")),
                forbidden_modules=_string_list(payload.get("forbidden_modules")),
                privacy_scope=str(payload.get("privacy_scope") or "public"),
                max_weight=str(payload.get("max_weight") or ""),
                max_cost=dict(payload.get("max_cost") or DEFAULT_MAX_COST),
            )
        raise TypeError(f"unsupported research request value: {type(value).__name__}")

    @property
    def request_hash(self) -> str:
        parts = [
            self.query,
            self.intent,
            self.loadout,
            self.freshness,
            self.depth,
            str(self.follow_results),
            "\n".join(sorted(self.query_variants)),
            self.privacy_scope,
            self.max_weight,
            json.dumps(self.max_cost, sort_keys=True, separators=(",", ":")),
            "\n".join(sorted(self.source_hints)),
            "\n".join(sorted(self.allowed_modules)),
            "\n".join(sorted(self.forbidden_modules)),
        ]
        return _stable_hash("\n".join(parts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "intent": self.intent,
            "source_hints": list(self.source_hints),
            "loadout": self.loadout,
            "freshness": self.freshness,
            "depth": self.depth,
            "follow_results": self.follow_results,
            "query_variants": list(self.query_variants),
            "allowed_modules": list(self.allowed_modules),
            "forbidden_modules": list(self.forbidden_modules),
            "privacy_scope": self.privacy_scope,
            "max_weight": self.max_weight,
            "max_cost": dict(self.max_cost),
            "request_hash": self.request_hash,
        }


@dataclass
class ResearchAttempt:
    module: str
    status: str
    reason: str = ""
    url: str = ""
    next_allowed: list[str] = field(default_factory=list)
    weight: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "status": self.status,
            "reason": self.reason,
            "url": self.url,
            "next_allowed": list(self.next_allowed),
            "weight": self.weight,
        }


@dataclass
class ResearchResult:
    source_id: str
    url: str
    title: str = ""
    platform: str = "web"
    content_markdown: str = ""
    extracted_at: str = ""
    freshness: str = "live"
    confidence: str = "weak"
    limits: list[str] = field(default_factory=list)
    citations: list[dict[str, str]] = field(default_factory=list)
    receipt_id: str = ""

    @classmethod
    def blocked(cls, url: str, *, reason: str, receipt_id: str = "") -> "ResearchResult":
        return cls(
            source_id=_stable_hash(url),
            url=url,
            title="",
            platform="web",
            content_markdown="",
            confidence="blocked",
            limits=[reason],
            citations=[{"label": url, "url": url}] if url else [],
            receipt_id=receipt_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "url": self.url,
            "title": self.title,
            "platform": self.platform,
            "content_markdown": self.content_markdown,
            "extracted_at": self.extracted_at,
            "freshness": self.freshness,
            "confidence": self.confidence,
            "limits": list(self.limits),
            "citations": list(self.citations),
            "receipt_id": self.receipt_id,
        }


@dataclass
class ResearchReceipt:
    receipt_id: str
    request_hash: str
    module_chain: list[str] = field(default_factory=list)
    attempts: list[ResearchAttempt] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "request_hash": self.request_hash,
            "module_chain": list(self.module_chain),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "policy": dict(self.policy),
        }
