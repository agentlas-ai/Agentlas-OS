"""Research receipt persistence."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from agentlas_cloud.networking.bootstrap import append_jsonl, networking_home, utc_now

from .contracts import ResearchAttempt, ResearchReceipt, ResearchRequest


def new_receipt_id() -> str:
    return f"research_{uuid.uuid4().hex[:16]}"


def write_research_receipt(
    request: ResearchRequest,
    *,
    attempts: list[ResearchAttempt],
    module_chain: list[str],
    policy: dict[str, Any],
    home: Path | str | None = None,
) -> ResearchReceipt:
    receipt = ResearchReceipt(
        receipt_id=new_receipt_id(),
        request_hash=request.request_hash,
        module_chain=module_chain,
        attempts=attempts,
        policy=policy,
    )
    base = Path(home) if home else networking_home()
    record = {"ts": utc_now(), **receipt.to_dict()}
    append_jsonl(base / "ledgers" / "research-receipts.jsonl", record)
    return receipt

