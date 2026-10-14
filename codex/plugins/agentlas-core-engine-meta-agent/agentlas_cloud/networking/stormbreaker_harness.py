"""Canonical, host-neutral Stormbreaker Goal + UltraCode harness.

This module is the single source of truth for the execution protocol used by
Agentlas Desktop, Agentlas Terminal, Codex, Claude Code, and every other host.
Hosts may choose different tools or expose different live model inventories,
but they must apply ``system_prompt`` verbatim and may not redefine Goal mode or
UltraCode mode locally.
"""

from __future__ import annotations

import hashlib
from typing import Any


HARNESS_SCHEMA_VERSION = "agentlas.stormbreaker.goal-ultracode-harness.v1"
HARNESS_ID = "agentlas-core/stormbreaker-goal-ultracode"
HARNESS_MODE = "stormbreaker-goal-ultracode"

HARNESS_PROTOCOL_LINES = (
    "harness: Stormbreaker Goal+UltraCode; substantial work only, trivial direct",
    "GOAL MODE: lock goal/constraints/checks/owners; unclear ask 3-5 once, specific none",
    "ULTRACODE MODE: inspect real state, inherit Context Slice, query impact before edits; minimal complete fix, tests/repair, keep unrelated work",
    "ledger: packets/owners/deps/gates/status/resume; continue safe unfinished work beyond planning",
    "children: host inventory only; smallest sufficient model/effort; host validates; parallel only supported independent nonoverlapping writes",
    "proof: verifier per packet; routed/prepared/executed \u2260 passed; Context Map impact receipt or every unresolved affected file",
    "recovery: bounded evidence loop, durable journal, never redo verified packets; grants/current personal always-allow govern effects/payment; reconcile uncertain effects first",
    "final: all packets pass + final_gate.can_report_success; else blocked/unverified + evidence/resume; brief progress/decisions/ledger, no hidden reasoning",
)

from ..prompt_order import compose_prompt

HARNESS_SYSTEM_PROMPT = compose_prompt([{
    "id": "purpose.stormbreaker.harness.policy", "revision": 2, "stability": "fixed-policy",
    "changeTriggers": ["release"], "text": "\n".join(HARNESS_PROTOCOL_LINES),
}])
HARNESS_PROMPT_SHA256 = hashlib.sha256(HARNESS_SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def goal_ultracode_harness() -> dict[str, Any]:
    """Return a fresh portable harness contract for a host or work packet."""

    return {
        "schema_version": HARNESS_SCHEMA_VERSION,
        "harness_id": HARNESS_ID,
        "owner": "Agentlas Core",
        "mode": HARNESS_MODE,
        "system_prompt": HARNESS_SYSTEM_PROMPT,
        "prompt_sha256": HARNESS_PROMPT_SHA256,
        "host_rule": "apply system_prompt verbatim; do not redefine Goal mode or UltraCode mode in an adapter",
        "inventory_rule": "pass live sessions with --session-inventory when available; otherwise use the explicit host:primary fallback",
        "completion_rule": "success requires result.final_gate.can_report_success",
    }


def harness_reference() -> dict[str, str]:
    """Return the compact identity embedded in every packet."""

    return {
        "schema_version": HARNESS_SCHEMA_VERSION,
        "harness_id": HARNESS_ID,
        "mode": HARNESS_MODE,
        "prompt_sha256": HARNESS_PROMPT_SHA256,
        "source": "execution_fabric.execution_harness",
    }
