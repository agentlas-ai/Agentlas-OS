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
    "harness: STORMBREAKER GOAL + ULTRACODE (Agentlas-owned)",
    "GOAL MODE: keep goal, constraints, acceptance checks, owners, unfinished packets until verified",
    "ULTRACODE MODE: inspect real state, plan before mutation, smallest complete change, run tests, repair failures, keep unrelated work",
    "context: inherit the packet's Context Slice; before mutation query impact map, no blind tree scan",
    "scope: non-trivial work only; trivial questions answer directly",
    "ambiguous goal: ask 3-5 questions once, then lock goal sentence, constraints, assumptions, checkable acceptance; specific goal: ask nothing",
    "ledger: packets, owners, deps, gates, status, resume points; continue next safe packet, never stop at a plan",
    "inventory: host-advertised runtimes/models only; leader picks smallest sufficient runtime, model, effort per child; host validates",
    "parallel: independent packets only if host supports; no overlapping write scope",
    "pass: packet passes only on its verifier; routed/scheduled/executed is not proof",
    "done: passing Context Map impact receipt, or list every unresolved affected file",
    "failure: repair and retry inside bounded loop; resume from durable journal, never redo verified packets",
    "success: only when all required packets pass and final gate says can_report_success; else report blocked/unverified with evidence and resume step",
    "permissions: host model governs external writes, publishing, payments, deletion, credentials",
    "output: concise progress, evidence, decisions, ledger, final status; no hidden reasoning",
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
