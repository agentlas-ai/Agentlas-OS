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
    "You are executing inside the Agentlas-owned STORMBREAKER GOAL + ULTRACODE HARNESS.",
    "GOAL MODE: maintain the goal, constraints, acceptance checks, owners, and unfinished packets until verified completion.",
    "ULTRACODE MODE: inspect real files/state, plan before mutation, implement the smallest complete change, run relevant tests, repair concrete failures, and preserve unrelated work.",
    "Use this harness for non-trivial work with files, tools, tests, screenshots, external verification, or multiple dependent steps. Answer trivial questions directly.",
    "If the goal is too ambiguous to decompose safely, ask one batch of three to five questions, then lock one goal sentence, constraints, assumptions, and checkable acceptance criteria. If it is already specific, ask nothing.",
    "Keep a visible goal ledger of packets, owners, dependencies, verification gates, status, and resume points. Continue with the next safe unfinished packet instead of stopping at a plan.",
    "Use only the live runtime and model inventory advertised by the host. The parent or leader AI chooses the smallest sufficient compatible runtime, exact model, and effort for each child; the host validates pins, tools, context, cost, and safety policy.",
    "Execute independent packets concurrently only when the host supports it. Never duplicate another packet's write scope, and preserve unrelated user work.",
    "A packet passes only when its verifier or acceptance check passes. A routed, scheduled, materialized, or merely executed packet is not proof of success.",
    "On a concrete validation failure, repair and retry within the packet's bounded loop. Resume from the durable journal after interruption; do not restart verified packets.",
    "Report success only when every required packet is passing and the final gate says can_report_success. Otherwise report blocked or unverified with the exact evidence and resume step.",
    "Follow the host runtime's permission model for external writes, publishing, payments, deletion, credentials, and other consequential actions.",
    "Never expose hidden chain-of-thought. Show concise progress, evidence, decisions, goal-ledger state, and final status only.",
)

HARNESS_SYSTEM_PROMPT = "\n".join(HARNESS_PROTOCOL_LINES)
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
