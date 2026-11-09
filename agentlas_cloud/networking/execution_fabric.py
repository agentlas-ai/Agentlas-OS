"""Stormbreaker execution fabric for routed pipeline plans.

The router still returns a plan only. This module turns that plan into a
machine-readable execution contract that a host runtime can use to split work
across active model sessions while keeping Stormbreaker's final gate honest.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ..model_allocation import (
    EFFORT_RANK,
    _as_capabilities,
    _capability_observation,
    _context_window,
    _policy_for_role,
    canonical_phase_for_stage,
    model_role_for_stage,
    normalize_effort,
    resolve_model_allocation,
    validate_allocation_decision,
)
from .stormbreaker_harness import goal_ultracode_harness, harness_reference
from .runtime_capabilities import descriptor_from_session, scrub_identity_features


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


# Access path is the ONLY thing the runtime x model matrix (PLAN 2026-08-14 §1.3)
# is allowed to answer: does this (runtime, model) pair need runtime-specific
# code (a subscription CLI) or the generic API/local path? Anything finer
# (context window, price, tools) belongs to live discovery, never to this field.
ACCESS_PATHS = ("subscription-cli", "api", "local", "unknown")


def _provider_from_session(raw: Any, family: str) -> str:
    """Opaque provider label for the inventory channel; never a capability."""

    if isinstance(raw, Mapping):
        advertised = str(raw.get("provider") or "").strip().lower()
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", advertised):
            return advertised
    return family


def _raw_session_matches(raw_sessions: list[Any] | None, session_id: str) -> list[Any]:
    """Find all available raw rows for a normalized session identity."""
    matches: list[Any] = []
    for idx, raw in enumerate(raw_sessions or []):
        if isinstance(raw, Mapping):
            if raw.get("available") is False:
                continue
            candidate = str(raw.get("session_id") or raw.get("id") or raw.get("name") or raw.get("provider") or f"session:{idx + 1}").strip()
        elif isinstance(raw, str):
            candidate = raw.strip() or f"session:{idx + 1}"
        else:
            continue
        if candidate == session_id:
            matches.append(raw)
    return matches


def _advertised_provider_for_session(raw_sessions: list[Any] | None, session_id: str) -> str | None:
    """Return only a unique session's explicit provider, never an inferred family."""
    matches = _raw_session_matches(raw_sessions, session_id)
    if len(matches) != 1 or not isinstance(matches[0], Mapping):
        return None
    provider = matches[0].get("provider")
    return provider.strip().lower() if isinstance(provider, str) and provider.strip() else None


def _access_path_from_session(raw: Any) -> str:
    if isinstance(raw, Mapping):
        advertised = str(raw.get("access_path") or raw.get("accessPath") or "").strip().lower()
        if advertised in ACCESS_PATHS:
            return advertised
        if raw.get("local") is True:
            return "local"
    return "unknown"


def _normalize_session_inventory(
    raw_sessions: list[Any] | None, *, preserve_unknown_efforts: bool
) -> list[dict[str, Any]]:
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
                "provider": "host",
                "model": None,
                "access_path": "unknown",
                "trust": "host",
                "capabilities": ["route_selected_execution"],
                "max_parallel": 1,
                "capability_descriptor": descriptor_from_session(None, "host:primary"),
            }
        ]

    sessions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, raw in enumerate(raw_sessions):
        if isinstance(raw, str):
            session_id = raw.strip() or f"session:{idx + 1}"
            # A bare string identifies the session, not its model. Only an
            # explicit model field on an inventory object establishes one.
            model = None
            capabilities: list[str] = []
            trust = "approved_external"
        elif isinstance(raw, Mapping):
            if raw.get("available") is False:
                continue
            session_id = str(
                raw.get("session_id")
                or raw.get("id")
                or raw.get("name")
                or raw.get("provider")
                or f"session:{idx + 1}"
            )
            advertised_model = raw.get("model") or raw.get("model_id")
            model = (str(advertised_model).strip() or None) if advertised_model else None
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
        provider = _provider_from_session(raw, family)
        capability_descriptor = scrub_identity_features(
            descriptor_from_session(raw, session_id), [model, provider, family]
        )
        sessions.append(
            {
                "session_id": session_id,
                "family": family,
                # Separate inventory channel for provider/model identity — the
                # capability descriptor below must never learn these values.
                "provider": provider,
                "model": model,
                **({"active": raw["active"]} if isinstance(raw, Mapping) and isinstance(raw.get("active"), bool) else {}),
                **({"available": raw["available"]} if isinstance(raw, Mapping) and isinstance(raw.get("available"), bool) else {}),
                "access_path": _access_path_from_session(raw),
                "trust": trust if trust in {"host", "local", "approved_external", "untrusted"} else "approved_external",
                "capabilities": capabilities,
                "max_parallel": max(1, max_parallel),
                "tier": str(raw.get("tier")).lower() if isinstance(raw, Mapping) and raw.get("tier") else None,
                "supported_efforts": (
                    list(raw["supported_efforts"])
                    if isinstance(raw, Mapping) and isinstance(raw.get("supported_efforts"), list)
                    else None if preserve_unknown_efforts else []
                ),
                "context_window": _context_window(raw),
                "supports_tools": _capability_observation(raw, "supports_tools", "supportsTools"),
                "supports_multimodal": _capability_observation(raw, "supports_multimodal", "supportsMultimodal"),
                "capability_descriptor": capability_descriptor,
            }
        )

    return sessions


def normalize_session_inventory(raw_sessions: list[Any] | None) -> list[dict[str, Any]]:
    """Normalize sessions using the established public array-shaped contract."""
    return _normalize_session_inventory(raw_sessions, preserve_unknown_efforts=False)


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

    sessions = _normalize_session_inventory(session_inventory, preserve_unknown_efforts=True)
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
        chosen_session = _choose_session(sessions, stage_name, session_loads) if sessions else None
        decisions = model_allocation_decisions or {}
        raw_decision = (
            decisions.get(packet_id)
            or decisions.get(stage_name)
            or decisions.get(str(order))
        )
        allocation_policy = dict(model_allocation_policy or {})
        if chosen_session and chosen_session.get("model"):
            allocation_policy.setdefault("currentModelId", chosen_session["model"])
        host_phase = canonical_phase_for_stage(stage_name)
        model_role = model_role_for_stage(stage_name)
        allocation_receipt = resolve_model_allocation(
            raw_decision,
            sessions,
            policy=allocation_policy,
            role=model_role,
            expected_phase=host_phase,
        )
        resolved_session_id = allocation_receipt["resolved"].get("sessionId")
        if resolved_session_id:
            # The allocator canonicalizes surrounding whitespace when comparing
            # identifiers.  Map back only a unique canonical match, retaining
            # the host's original opaque identifier for the executor.
            matching_sessions = [
                session for session in sessions
                if session["session_id"].strip() == resolved_session_id
            ]
            if len(matching_sessions) == 1:
                chosen_session = matching_sessions[0]
            elif len(matching_sessions) > 1:
                # A canonical collision cannot identify an exact native session.
                # Without a pin the host may still choose its advisory session;
                # with a pin the policy validation below remains fail-closed.
                allocation_receipt["status"] = "unresolved"
                allocation_receipt["resolved"] = {key: None for key in allocation_receipt["resolved"]}
                allocation_receipt["reasonCodes"].append("session_identity_ambiguous")
                resolved_session_id = None
        effective_policy, _ = _policy_for_role(allocation_policy, model_role)
        constrained = any(effective_policy.get(key) for key in (
            "pinnedModelId", "pinnedProvider", "maxTier", "maxEffort", "requiredCapabilities"
        ))
        decision_selection = raw_decision.get("selection") if isinstance(raw_decision, Mapping) else None
        normalized_decision, decision_issues = validate_allocation_decision(raw_decision)
        valid_parent_decision = bool(
            normalized_decision is not None
            and not decision_issues
            and (host_phase is None or normalized_decision.get("phase") == host_phase)
        )
        # A rejected decision cannot impose a model choice on an unambiguous
        # host session. Keep its issues in the receipt; host policy and known
        # task requirements must still hold. The trust field is only a host
        # declaration and does not grant execution authority.
        features = raw_decision.get("features") if isinstance(raw_decision, Mapping) else None
        # No feature claims is equivalent to the existing no-decision host
        # path; partial or malformed claims are not proof of requirements.
        features_absent = isinstance(raw_decision, Mapping) and "features" not in raw_decision
        feature_shape_known = (
            isinstance(features, Mapping)
            and isinstance(features.get("toolRequired"), bool)
            and isinstance(features.get("multimodalRequired"), bool)
            and all(
                isinstance(features.get(key), int)
                and not isinstance(features.get(key), bool)
                and features[key] >= 0
                for key in ("inputTokens", "expectedOutputTokens")
            )
        )
        known_requirement_conflict = bool(
            feature_shape_known
            and chosen_session
            and (
                (features["toolRequired"] and chosen_session.get("supports_tools") is False)
                or (features["multimodalRequired"] and chosen_session.get("supports_multimodal") is False)
                or (
                    chosen_session.get("context_window") is not None
                    and features["inputTokens"] + features["expectedOutputTokens"] > chosen_session["context_window"]
                )
            )
        )
        safe_host_fallback = (
            not constrained
            and len(sessions) == 1
            and (not session_inventory or len(session_inventory) == 1)
            and chosen_session is not None
            and chosen_session.get("active") is not False
            and chosen_session.get("trust") in {"host", "local", "approved_external"}
            and (features_absent or feature_shape_known)
            and not known_requirement_conflict
        )
        exact_requested = (
            bool(normalized_decision["selection"]["exactModelId"])
            if valid_parent_decision and normalized_decision is not None
            else (
                isinstance(decision_selection, Mapping)
                and bool(decision_selection.get("exactModelId"))
                and not safe_host_fallback
            )
        )
        policy_unresolved = bool((constrained or exact_requested) and not resolved_session_id)
        if (constrained or exact_requested) and resolved_session_id and (
            len(_raw_session_matches(session_inventory, str(resolved_session_id))) != 1
            or not chosen_session or str(chosen_session.get("session_id") or "").strip() != resolved_session_id
        ):
            allocation_receipt["status"] = "unresolved"
            allocation_receipt["resolved"] = {key: None for key in allocation_receipt["resolved"]}
            allocation_receipt["reasonCodes"].append("session_identity_ambiguous")
            policy_unresolved = True
            resolved_session_id = None
            chosen_session = None
        pinned_provider = effective_policy.get("pinnedProvider")
        requested_provider = decision_selection.get("provider") if exact_requested and not effective_policy.get("pinnedModelId") else None
        required_provider = pinned_provider or requested_provider
        if isinstance(required_provider, str) and required_provider.strip() and resolved_session_id:
            advertised_provider = _advertised_provider_for_session(session_inventory, str(resolved_session_id))
            if advertised_provider != required_provider.strip().lower():
                allocation_receipt["status"] = "unresolved"
                allocation_receipt["resolved"] = {key: None for key in allocation_receipt["resolved"]}
                allocation_receipt["reasonCodes"].append("provider_policy_unverified")
                policy_unresolved = True
                resolved_session_id = None
                chosen_session = None
        if exact_requested:
            resolved = allocation_receipt["resolved"]
            requested_model = str(decision_selection["exactModelId"]).strip()
            requested_provider = str(decision_selection.get("provider") or "").strip().lower()
            policy_unresolved = policy_unresolved or bool(allocation_receipt.get("validationIssues"))
            if not effective_policy.get("pinnedModelId"):
                policy_unresolved = policy_unresolved or resolved.get("modelId") != requested_model
                if requested_provider:
                    policy_unresolved = policy_unresolved or str(resolved.get("provider") or "").lower() != requested_provider
        ceiling = normalize_effort(effective_policy.get("maxEffort"))
        if ceiling and resolved_session_id:
            effort = normalize_effort(allocation_receipt["resolved"].get("effort"))
            efforts = chosen_session.get("supported_efforts") if chosen_session else None
            supported = isinstance(efforts, list) and effort is not None and any(normalize_effort(item) == effort for item in efforts)
            within = effort == ceiling or (effort in EFFORT_RANK and ceiling in EFFORT_RANK and EFFORT_RANK[effort] <= EFFORT_RANK[ceiling])
            policy_unresolved = policy_unresolved or not (supported and within)
        if policy_unresolved:
            allocation_receipt["status"] = "unresolved"
            allocation_receipt["resolved"] = {key: None for key in allocation_receipt["resolved"]}
            resolved_session_id = None
            chosen_session = None
        elif resolved_session_id and chosen_session and str(chosen_session.get("session_id") or "").strip() != resolved_session_id:
            # Preserve the native host's identifier, but do not claim the
            # allocator resolved a different, normalized identity.
            allocation_receipt["status"] = "unresolved"
            allocation_receipt["resolved"] = {key: None for key in allocation_receipt["resolved"]}
            allocation_receipt["reasonCodes"].append("session_identity_unverified")
            resolved_session_id = None
        elif resolved_session_id and chosen_session:
            # Report and dispatch the same identifier the host advertised.
            allocation_receipt["resolved"]["sessionId"] = chosen_session["session_id"]
        if chosen_session:
            chosen_id = str(chosen_session["session_id"])
            session_loads[chosen_id] = session_loads.get(chosen_id, 0) + 1
        depends_on = _packet_dependencies(stage, produced_by_kind)
        packet = {
                "packet_id": packet_id,
                "stage_order": order,
                "stage": stage_name,
                "card": stage.get("card"),
                "canonical_command": stage.get("canonical_command"),
                "depends_on": depends_on,
                "produces": produced,
                "write_scope": f"{handoff_dir}{order}-{primary_output}/",
                "session_hint": {
                    "session_id": chosen_session["session_id"] if chosen_session else None,
                    "family": chosen_session["family"] if chosen_session else None,
                    "model": chosen_session["model"] if chosen_session else None,
                    "trust": chosen_session["trust"] if chosen_session else None,
                    "effort": allocation_receipt["resolved"].get("effort"),
                    "capability_descriptor": chosen_session["capability_descriptor"] if chosen_session else None,
                    "selection_status": (
                        "no_available_session" if not chosen_session and session_inventory and all(
                            isinstance(row, Mapping) and row.get("available") is False for row in session_inventory
                        ) else "policy_unresolved" if policy_unresolved
                        else "resolved" if resolved_session_id else "advisory"
                    ),
                    **({"inventory_status": "invalid"} if not sessions and session_inventory and not all(
                        isinstance(row, Mapping) and row.get("available") is False for row in session_inventory
                    ) else {}),
                },
                "model_allocation": allocation_receipt,
                "model_allocation_contract": {
                    "decision_schema": "agentlas.model-allocation-decision.v1",
                    "decision_owner": "parent_or_leader_ai",
                    "phase": host_phase,
                    "role": allocation_receipt["role"],
                    "status": (
                        allocation_receipt["status"]
                        if raw_decision
                        else "awaiting-parent-ai"
                    ),
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
        # Hub-routed Stormbreaker stages carry the prepared BYOM instructions
        # into packet.json so any host executor (including a local Ollama/Qwen
        # adapter) can execute the selected specialist without another routing
        # or network lookup.
        for key in ("hub_runtime_bundle", "hub_grounding", "hub_invocation"):
            if stage.get(key) is not None:
                packet[key] = stage[key]
        packets.append(packet)
        for kind in produced:
            produced_by_kind[kind] = packet_id

    groups = _group_packets(packets)
    return {
        "fabric_version": "stormbreaker.execution_fabric.v3",
        "mode": "stormbreaker-goal-ultracode",
        "execution_harness": execution_harness,
        "pipeline_id": pipeline_id,
        # Keep the established array shape for existing fabric consumers.
        # The resolver above still receives None for unobserved capabilities.
        "sessions": [
            {**session, "supported_efforts": session["supported_efforts"] or []}
            if "supported_efforts" in session else session
            for session in sessions
        ],
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
    unverified: list[str] = []
    missing: list[str] = []
    fabric_errors: list[str] = []
    if not required:
        # ``all([])``-style/vacuous success is never a valid execution proof.
        # A malformed or empty routed fabric must fail closed even when the
        # caller supplies an equally empty packet-status map.
        fabric_errors.append("empty_required_packet_set")
    for packet_id in required:
        status = packet_statuses.get(packet_id)
        if status == "passing":
            passing.append(packet_id)
        elif status == "blocked":
            blocked.append(packet_id)
        elif status == "executed_unverified":
            unverified.append(packet_id)
        else:
            missing.append(packet_id)
    can_report_success = bool(required) and not fabric_errors and not missing and not blocked and not unverified
    return {
        "can_report_success": can_report_success,
        "can_report_blocked": bool(fabric_errors or blocked or unverified),
        "passing": passing,
        "blocked": blocked,
        "unverified": unverified,
        "missing_or_incomplete": missing,
        "fabric_errors": fabric_errors,
        "final_gate": "success" if can_report_success else "blocked",
    }
