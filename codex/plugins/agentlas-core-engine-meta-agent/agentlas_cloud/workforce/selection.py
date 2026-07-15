"""Validate, but never create, a host-LLM workforce decision."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import canonical_digest, normalized_strings


def _candidate_maps(candidate_set: Mapping[str, Any]) -> tuple[dict[str, dict[str, dict[str, Any]]], set[str]]:
    by_slot: dict[str, dict[str, dict[str, Any]]] = {}
    all_releases: set[str] = set()
    for slot in candidate_set.get("slots") or []:
        if not isinstance(slot, Mapping) or not slot.get("slotId"):
            continue
        slot_id = str(slot["slotId"])
        releases: dict[str, dict[str, Any]] = {}
        for candidate in slot.get("candidates") or []:
            if not isinstance(candidate, Mapping) or not candidate.get("agentReleaseId"):
                continue
            release_id = str(candidate["agentReleaseId"])
            releases[release_id] = dict(candidate)
            all_releases.add(release_id)
        by_slot[slot_id] = releases
    return by_slot, all_releases


def _slot_specs(work_order: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(slot["slotId"]): dict(slot)
        for slot in work_order.get("roleSlots") or []
        if isinstance(slot, Mapping) and slot.get("slotId")
    }


def _has_cycle(edges: list[Mapping[str, Any]], slot_ids: set[str]) -> bool:
    graph: dict[str, set[str]] = {slot_id: set() for slot_id in slot_ids}
    for edge in edges:
        source = str(edge.get("fromSlot") or "")
        target = str(edge.get("toSlot") or "")
        if source in graph and target in graph and source != target:
            graph[source].add(target)
        elif source == target and source:
            return True
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def validate_host_selection(
    selection: Mapping[str, Any],
    *,
    candidate_set: Mapping[str, Any],
    work_order: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return an accepted or rejected task-force validation receipt.

    There is intentionally no fallback picker in this module.  A rejected
    decision goes back to the host LLM for expansion or a new decision.
    """

    issues: list[str] = []
    if selection.get("schemaVersion") != "agentlas.workforce-selection.v1":
        issues.append("unsupported_selection_schema")
    if selection.get("selectionSessionId") != candidate_set.get("selectionSessionId"):
        issues.append("selection_session_mismatch")
    if selection.get("candidateSetDigest") != candidate_set.get("candidateSetDigest"):
        issues.append("candidate_set_digest_mismatch")
    try:
        expires_at = datetime.fromisoformat(str(candidate_set.get("expiresAt") or "").replace("Z", "+00:00"))
        clock = now or datetime.now(timezone.utc)
        if expires_at <= clock:
            issues.append("candidate_set_expired")
    except ValueError:
        issues.append("candidate_set_expiry_invalid")
    decision_author = selection.get("decisionAuthor") if isinstance(selection.get("decisionAuthor"), Mapping) else {}
    if decision_author.get("kind") != "host_llm" or not decision_author.get("modelId"):
        issues.append("decision_author_must_be_host_llm")

    candidates_by_slot, all_candidates = _candidate_maps(candidate_set)
    specs = _slot_specs(work_order)
    assignments = selection.get("assignments") if isinstance(selection.get("assignments"), list) else []
    counts: dict[str, int] = defaultdict(int)
    ideal_team: list[dict[str, Any]] = []
    executable_team: list[dict[str, Any]] = []
    unfilled_posts: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for assignment in assignments:
        if not isinstance(assignment, Mapping):
            issues.append("invalid_assignment")
            continue
        slot_id = str(assignment.get("slotId") or "")
        release_id = str(assignment.get("agentReleaseId") or "")
        pair = (slot_id, release_id)
        if slot_id not in specs:
            issues.append("unknown_slot")
            continue
        if release_id not in candidates_by_slot.get(slot_id, {}):
            issues.append(f"release_outside_candidate_set:{slot_id}:{release_id}")
            continue
        if pair in seen_pairs:
            issues.append(f"duplicate_assignment:{slot_id}:{release_id}")
            continue
        seen_pairs.add(pair)
        if not normalized_strings(assignment.get("reasonCodes")):
            issues.append(f"missing_assignment_reason:{slot_id}:{release_id}")
        counts[slot_id] += 1
        candidate = candidates_by_slot[slot_id][release_id]
        row = {
            "slotId": slot_id,
            "agentDefinitionId": candidate.get("agentDefinitionId"),
            "agentReleaseId": release_id,
            "releaseVersion": candidate.get("releaseVersion"),
            "packageHash": candidate.get("packageHash"),
            "contentDigest": candidate.get("contentDigest"),
            "entityKind": candidate.get("entityKind"),
            "reasonCodes": normalized_strings(assignment.get("reasonCodes")),
        }
        ideal_team.append(row)
        operational = candidate.get("operational") if isinstance(candidate.get("operational"), Mapping) else {}
        if operational.get("callable") is True:
            executable_team.append(row)
        else:
            unfilled_posts.append(
                {
                    "slotId": slot_id,
                    "agentReleaseId": release_id,
                    "reason": "selected_ideal_release_not_callable_now",
                    "installable": bool(operational.get("installable")),
                    "unavailableReasons": normalized_strings(operational.get("unavailableReasons")),
                }
            )

    for slot_id, spec in specs.items():
        cardinality = max(1, int(spec.get("cardinality") or 1))
        criticality = str(spec.get("criticality") or "required")
        if criticality == "required" and counts[slot_id] != cardinality:
            issues.append(f"required_slot_cardinality:{slot_id}:{counts[slot_id]}:{cardinality}")
        elif criticality != "required" and counts[slot_id] > cardinality:
            issues.append(f"optional_slot_overfilled:{slot_id}:{counts[slot_id]}:{cardinality}")

    edges = [dict(edge) for edge in selection.get("edges") or [] if isinstance(edge, Mapping)]
    for edge in edges:
        if str(edge.get("fromSlot") or "") not in specs or str(edge.get("toSlot") or "") not in specs:
            issues.append("edge_references_unknown_slot")
    if _has_cycle(edges, set(specs)):
        issues.append("task_force_cycle")

    alternatives = normalized_strings(selection.get("alternativesConsidered"))
    for release_id in alternatives:
        if release_id not in all_candidates:
            issues.append(f"alternative_outside_candidate_set:{release_id}")

    receipt_payload = {
        "selectionSessionId": candidate_set.get("selectionSessionId"),
        "candidateSetDigest": candidate_set.get("candidateSetDigest"),
        "ontologyVersion": candidate_set.get("ontologyVersion"),
        "workOrderId": work_order.get("workOrderId"),
        "decisionAuthor": {
            "kind": decision_author.get("kind"),
            "modelId": decision_author.get("modelId"),
            "runtimeId": decision_author.get("runtimeId"),
        },
        "assignments": ideal_team,
        "edges": edges,
        "alternativesConsidered": alternatives,
    }
    return {
        "schemaVersion": "agentlas.workforce-selection-validation.v1",
        "status": "rejected" if issues else "accepted",
        "issues": sorted(set(issues)),
        "selectionReceiptId": "workforce-selection:" + canonical_digest(receipt_payload).split(":", 1)[1][:32],
        "decisionOwner": "host_llm",
        "historyInfluence": "none",
        "ontologyVersion": candidate_set.get("ontologyVersion"),
        "candidateSetDigest": candidate_set.get("candidateSetDigest"),
        "idealTeam": ideal_team,
        "executableTeam": executable_team,
        "unfilledPosts": unfilled_posts,
        "substitutions": [],
        "edges": edges,
        "receipt": receipt_payload,
    }


__all__ = ["validate_host_selection"]
