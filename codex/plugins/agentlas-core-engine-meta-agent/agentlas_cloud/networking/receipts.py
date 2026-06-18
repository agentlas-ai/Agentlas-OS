"""Routing receipts: every routing decision leaves an auditable trace.

Receipts intentionally store normalized, redacted tokens and a hash of the
normalized query — never the raw prompt.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from .bootstrap import append_jsonl, networking_home, utc_now
from .memory import redact_tokens


def write_receipt(
    *,
    action: str,
    query_tokens: list[str],
    candidates: list[dict[str, Any]],
    selected: str | None,
    reasons: list[str],
    locale: str,
    runtime: str | None = None,
    hop_count: int = 0,
    router_chain: list[str] | None = None,
    match_reason: str | None = None,
    graph_path: list[dict[str, Any]] | None = None,
    allowed_by: list[str] | None = None,
    blocked_by_axiom: list[str] | None = None,
    fallback_scope: str | None = None,
    task_force: dict[str, Any] | None = None,
    policy_decision: dict[str, Any] | None = None,
    memory_playbook: dict[str, Any] | None = None,
    home: Path | str | None = None,
) -> str:
    base = Path(home) if home else networking_home()
    receipt_id = uuid.uuid4().hex[:16]
    tokens = redact_tokens(query_tokens)
    record = {
        "ts": utc_now(),
        "receipt_id": receipt_id,
        "runtime": runtime or "terminal",
        "locale": locale,
        "query_tokens": tokens,
        "query_hash": hashlib.sha256(" ".join(sorted(tokens)).encode("utf-8")).hexdigest()[:24],
        "action": action,
        "selected": selected,
        "candidates": [{"id": item.get("id"), "score": item.get("score")} for item in candidates[:5]],
        "reasons": reasons,
        "hop_count": hop_count,
        "router_chain": router_chain or ["hephaestus-network"],
        "match_reason": match_reason,
        "graph_path": graph_path or [],
        "allowed_by": allowed_by or [],
        "blocked_by_axiom": blocked_by_axiom or [],
        "fallback_scope": fallback_scope,
        "task_force": task_force or {},
        "policy_decision": policy_decision or {},
        "memory_playbook": memory_playbook or {},
    }
    append_jsonl(base / "ledgers" / "routing-decisions.jsonl", record)
    return receipt_id


def record_execution(
    receipt_id: str,
    card_id: str,
    status: str,
    home: Path | str | None = None,
    detail: str | None = None,
    *,
    pipeline_id: str | None = None,
    packet_id: str | None = None,
    stage_order: int | None = None,
    session_id: str | None = None,
    parallel_group: str | None = None,
    parent_receipt_id: str | None = None,
) -> None:
    base = Path(home) if home else networking_home()
    record = {"ts": utc_now(), "receipt_id": receipt_id, "card_id": card_id, "status": status, "detail": detail}
    optional = {
        "pipeline_id": pipeline_id,
        "packet_id": packet_id,
        "stage_order": stage_order,
        "session_id": session_id,
        "parallel_group": parallel_group,
        "parent_receipt_id": parent_receipt_id,
    }
    record.update({key: value for key, value in optional.items() if value is not None})
    append_jsonl(
        base / "ledgers" / "executions.jsonl",
        record,
    )
