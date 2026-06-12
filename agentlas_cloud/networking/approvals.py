"""User approval gates for high-risk capabilities.

The router never executes anything itself; it returns structured
``approval_request`` payloads that the calling runtime must surface to the
user. Grants are recorded in ledgers/capability-grants.jsonl with an explicit
scope and optional TTL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bootstrap import (
    HIGH_RISK_CAPABILITIES,
    append_jsonl,
    networking_home,
    read_json,
    read_jsonl,
    utc_now,
)


def build_approval_request(capabilities: list[str], target: str, reason: str, payload_preview: str | None = None) -> dict[str, Any]:
    return {
        "capabilities": sorted(set(capabilities)),
        "target": target,
        "reason": reason,
        "payload_preview": payload_preview,
        "how_to_grant": f"hephaestus network grant <capability> --target {target} [--scope per_call|session|project|global]",
    }


def required_approvals(card: dict[str, Any]) -> list[str]:
    declared = list(card.get("approval_requirements") or [])
    risk_caps = list(((card.get("risk_profile") or {}).get("capabilities_at_risk")) or [])
    return sorted({cap for cap in declared + risk_caps if cap in HIGH_RISK_CAPABILITIES})


def missing_grants(capabilities: list[str], target: str, home: Path | str | None = None) -> list[str]:
    return sorted({cap for cap in capabilities if cap in HIGH_RISK_CAPABILITIES and not has_grant(cap, target, home)})


def consume_per_call_grants(capabilities: list[str], target: str, home: Path | str | None = None) -> list[str]:
    base = Path(home) if home else networking_home()
    consumed: list[str] = []
    for capability in sorted(set(capabilities)):
        grant = _active_grant(capability, target, base)
        if not grant or grant.get("scope", "per_call") != "per_call":
            continue
        append_jsonl(
            base / "ledgers" / "capability-grants.jsonl",
            {
                "ts": utc_now(),
                "capability": capability,
                "target": target,
                "scope": "per_call",
                "status": "consumed",
            },
        )
        consumed.append(capability)
    return consumed


def record_grant(
    capability: str,
    target: str,
    scope: str = "per_call",
    ttl_seconds: int | None = None,
    home: Path | str | None = None,
) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    policy = read_json(base / "policies" / "approval-policy.json", default={})
    allowed_scopes = policy.get("grant_scopes") or ["per_call", "session", "project", "global"]
    if scope not in allowed_scopes:
        return {"status": "rejected", "reason": f"invalid scope {scope}; allowed: {allowed_scopes}"}
    record = {
        "ts": utc_now(),
        "capability": capability,
        "target": target,
        "scope": scope,
        "ttl_seconds": ttl_seconds,
    }
    append_jsonl(base / "ledgers" / "capability-grants.jsonl", record)
    return {"status": "granted", **record}


def _active_grant(capability: str, target: str, home: Path | str | None = None) -> dict[str, Any] | None:
    base = Path(home) if home else networking_home()
    grants = read_jsonl(base / "ledgers" / "capability-grants.jsonl")
    now = datetime.now(timezone.utc)
    for grant in reversed(grants):
        if grant.get("capability") != capability or grant.get("target") != target:
            continue
        if grant.get("status") == "consumed":
            return None
        scope = grant.get("scope", "per_call")
        ttl = grant.get("ttl_seconds")
        if ttl:
            try:
                granted_at = datetime.fromisoformat(str(grant.get("ts")))
            except ValueError:
                continue
            if (now - granted_at).total_seconds() > float(ttl):
                continue
        return grant
    return None


def has_grant(capability: str, target: str, home: Path | str | None = None) -> bool:
    return _active_grant(capability, target, home) is not None
