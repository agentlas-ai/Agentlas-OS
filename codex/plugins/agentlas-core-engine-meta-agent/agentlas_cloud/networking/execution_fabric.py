"""Stormbreaker execution fabric for routed pipeline plans.

The router still returns a plan only. This module turns that plan into a
machine-readable execution contract that a host runtime can use to split work
across active model sessions while keeping Stormbreaker's final gate honest.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ..model_allocation import infer_inventory_tier, resolve_model_allocation
from .stormbreaker_harness import goal_ultracode_harness, harness_reference


STAGE_CAPABILITY_HINTS: dict[str, tuple[str, ...]] = {
    "plan": ("planning", "requirements", "research", "architecture"),
    "build": ("coding", "implementation", "code", "patch"),
    "verify": ("qa", "test", "verification", "review"),
}


def _family_from_session(raw: Any, session_id: str) -> str:
    """Preserve host-advertised provider identity without a model allowlist."""

    if isinstance(raw, Mapping):
        advertised = str(raw.get("family") or raw.get("provider") or "").strip().lower()
        if re.fullmatch(r"[a-z0-9][a-z0-9._]{0,63}", advertised):
            return advertised
    prefix = re.split(r"[:/@-]", session_id.strip().lower(), maxsplit=1)[0]
    return prefix if re.fullmatch(r"[a-z0-9][a-z0-9._]{0,63}", prefix) else "host"


def _as_capabilities(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.lower()]
    if not isinstance(value, list):
        return []
    capabilities: list[str] = []
    for item in value:
        if isinstance(item, str):
            capabilities.append(item.lower())
    return capabilities


def normalize_session_inventory(raw_sessions: list[Any] | None) -> list[dict[str, Any]]:
    """Normalize host-advertised model sessions for scheduling.

    A host can pass strings ("codex", "claude") or dictionaries. The inventory
    is intentionally descriptive: Hephaestus does not call third-party sessions
    from the router; the host runtime owns actual execution.
    """

    if not raw_sessions:
        return [
            {
                "session_id": "host:primary",
                "family": "host",
                "model": "host-runtime",
                "trust": "host",
                "capabilities": ["route_selected_execution"],
                "max_parallel": 1,
            }
        ]

    sessions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, raw in enumerate(raw_sessions):
        if isinstance(raw, str):
            session_id = raw.strip() or f"session:{idx + 1}"
            model = session_id
            capabilities: list[str] = []
            trust = "approved_external"
        elif isinstance(raw, Mapping):
            session_id = str(
                raw.get("session_id")
                or raw.get("id")
                or raw.get("name")
                or raw.get("provider")
                or f"session:{idx + 1}"
            )
            model = str(raw.get("model") or raw.get("model_family") or raw.get("provider") or session_id)
            capabilities = _as_capabilities(raw.get("capabilities"))
            trust = str(raw.get("trust") or ("host" if raw.get("local") else "approved_external")).lower()
        else:
            continue

        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        try:
            max_parallel = int(raw.get("max_parallel", 1)) if isinstance(raw, Mapping) else 1
        except (TypeError, ValueError):
            max_parallel = 1
        family = _family_from_session(raw, session_id)
        sessions.append(
            {
                "session_id": session_id,
                "family": family,
                "model": model,
                "trust": trust if trust in {"host", "local", "approved_external", "untrusted"} else "approved_external",
                "capabilities": capabilities,
                "max_parallel": max(1, max_parallel),
                "tier": (
                    str(raw.get("tier")).lower()
                    if isinstance(raw, Mapping) and raw.get("tier")
                    else infer_inventory_tier(model)
                ),
                "supported_efforts": (
                    list(raw.get("supported_efforts") or [])
                    if isinstance(raw, Mapping)
                    else []
                ),
                "context_window": (
                    int(raw.get("context_window") or 0)
                    if isinstance(raw, Mapping) and str(raw.get("context_window") or "0").isdigit()
                    else 0
                ),
                "supports_tools": bool(raw.get("supports_tools", True)) if isinstance(raw, Mapping) else True,
                "supports_multimodal": bool(raw.get("supports_multimodal", False)) if isinstance(raw, Mapping) else False,
            }
        )

    return sessions or normalize_session_inventory(None)


def _session_score(session: dict[str, Any], stage: str) -> int:
    """Score declared capabilities and trust only, never provider/model names."""

    capabilities = set(session.get("capabilities") or [])
    hints = set(STAGE_CAPABILITY_HINTS.get(stage, ()))
    score = len(capabilities & hints) * 4
    if session.get("trust") in {"host", "local"}:
        score += 1
    return score


def _choose_session(
    sessions: list[dict[str, Any]],
    stage: str,
    session_loads: dict[str, int],
) -> dict[str, Any]:
    eligible = [
        session
        for session in sessions
        if not (session.get("trust") == "untrusted" and stage == "build")
    ] or sessions
    eligible.sort(
        key=lambda session: (
            -_session_score(session, stage),
            session_loads.get(str(session["session_id"]), 0) / max(1, int(session.get("max_parallel") or 1)),
            str(session["session_id"]),
        )
    )
    chosen = eligible[0]
    session_loads[str(chosen["session_id"])] = session_loads.get(str(chosen["session_id"]), 0) + 1
    return chosen


def _packet_dependencies(stage: dict[str, Any], produced_by_kind: dict[str, str]) -> list[str]:
    deps: list[str] = []
    for consumed in stage.get("consumes") or []:
        dep = produced_by_kind.get(str(consumed))
        if dep:
            deps.append(dep)
    return deps


def _group_packets(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    done: set[str] = set()
    remaining = list(packets)
    while remaining:
        ready = [packet for packet in remaining if set(packet.get("depends_on") or []).issubset(done)]
        if not ready:
            ready = [remaining[0]]
        group_id = f"group:{len(groups) + 1}"
        for packet in ready:
            packet["parallel_group"] = group_id
        groups.append(
            {
                "group_id": group_id,
                "depends_on": sorted({dep for packet in ready for dep in packet.get("depends_on", [])}),
                "packet_ids": [packet["packet_id"] for packet in ready],
                "join_policy": "all_packets_pass_before_dependents_start",
            }
        )
        for packet in ready:
            done.add(packet["packet_id"])
            remaining.remove(packet)
    return groups


def build_execution_fabric(
    stages: list[dict[str, Any]],
    *,
    pipeline_id: str,
    handoff_dir: str,
    session_inventory: list[Any] | None = None,
    model_allocation_decisions: Mapping[str, Mapping[str, Any]] | None = None,
    model_allocation_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a Stormbreaker work-packet contract for a routed pipeline."""

    sessions = normalize_session_inventory(session_inventory)
    execution_harness = goal_ultracode_harness()
    session_loads: dict[str, int] = {}
    packets: list[dict[str, Any]] = []
    produced_by_kind: dict[str, str] = {}

    for stage in stages:
        stage_name = str(stage.get("stage") or "stage")
        order = int(stage.get("order") or len(packets) + 1)
        produced = [str(item) for item in (stage.get("produces") or [])]
        primary_output = produced[0] if produced else "artifact"
        packet_id = f"{pipeline_id}:{order}:{stage_name}"
        chosen_session = _choose_session(sessions, stage_name, session_loads)
        decisions = model_allocation_decisions or {}
        raw_decision = (
            decisions.get(packet_id)
            or decisions.get(stage_name)
            or decisions.get(str(order))
        )
        allocation_policy = dict(model_allocation_policy or {})
        allocation_policy.setdefault("currentModelId", chosen_session["model"])
        allocation_receipt = resolve_model_allocation(raw_decision, sessions, policy=allocation_policy)
        resolved_session_id = allocation_receipt["resolved"].get("sessionId")
        if resolved_session_id:
            chosen_session = next(
                (session for session in sessions if session["session_id"] == resolved_session_id),
                chosen_session,
            )
        depends_on = _packet_dependencies(stage, produced_by_kind)
        packets.append(
            {
                "packet_id": packet_id,
                "stage_order": order,
                "stage": stage_name,
                "card": stage.get("card"),
                "canonical_command": stage.get("canonical_command"),
                "depends_on": depends_on,
                "produces": produced,
                "write_scope": f"{handoff_dir}{order}-{primary_output}/",
                "session_hint": {
                    "session_id": chosen_session["session_id"],
                    "family": chosen_session["family"],
                    "model": chosen_session["model"],
                    "trust": chosen_session["trust"],
                    "effort": allocation_receipt["resolved"].get("effort"),
                },
                "model_allocation": allocation_receipt,
                "model_allocation_contract": {
                    "decision_schema": "agentlas.model-allocation-decision.v1",
                    "decision_owner": "parent_or_leader_ai",
                    "status": "resolved" if raw_decision else "awaiting-parent-ai",
                    "rule": "AI judges workload; host validates inventory, pins, capability, context and cost policy",
                    "raw_prompt_allowed_in_receipt": False,
                },
                "data_policy": [
                    "local operator mode: execute locally by default and label boundaries instead of asking on every step",
                    "pass stage contract, artifact paths, public playbooks, and redacted receipt metadata only",
                    "do not pass raw local memory or private prompts to external sessions",
                    "host runtime gates real publish/delete/payment/submit actions at execution time",
                ],
                "execution_harness": harness_reference(),
                "required_for_final_gate": True,
            }
        )
        for kind in produced:
            produced_by_kind[kind] = packet_id

    groups = _group_packets(packets)
    return {
        "fabric_version": "stormbreaker.execution_fabric.v3",
        "mode": "stormbreaker-goal-ultracode",
        "execution_harness": execution_harness,
        "pipeline_id": pipeline_id,
        "sessions": sessions,
        "packets": packets,
        "parallel_groups": groups,
        "required_packet_ids": [packet["packet_id"] for packet in packets],
        "join_policy": "success_requires_all_required_packets_passing",
        "resume_policy": {
            "journal": f"{handoff_dir}stormbreaker-execution-ledger.jsonl",
            "resume_from": "first_non_passing_required_packet",
            "final_gate": "block_success_until_all_required_packets_pass",
        },
    }


def evaluate_final_gate(fabric: dict[str, Any], packet_statuses: dict[str, str]) -> dict[str, Any]:
    """Classify whether a host runtime may report success for a fabric."""

    required = [str(packet_id) for packet_id in fabric.get("required_packet_ids") or []]
    passing: list[str] = []
    blocked: list[str] = []
    missing: list[str] = []
    for packet_id in required:
        status = packet_statuses.get(packet_id)
        if status == "passing":
            passing.append(packet_id)
        elif status == "blocked":
            blocked.append(packet_id)
        else:
            missing.append(packet_id)
    return {
        "can_report_success": not missing and not blocked,
        "can_report_blocked": not missing and bool(blocked),
        "passing": passing,
        "blocked": blocked,
        "missing_or_incomplete": missing,
        "final_gate": "success" if not missing and not blocked else "blocked",
    }
