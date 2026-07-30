"""Deterministic, non-mutating host boundary for Hub workforce contracts."""

from __future__ import annotations

from typing import Any, Mapping

from ..experience_privacy import personal_identifier_kinds, secret_like_kinds
from .contracts import (
    WORKFORCE_SELECTION_REASON_CODES,
    canonical_digest,
    iter_workforce_contract_strings,
    normalize_work_order,
    validate_work_order_semantics,
    validate_workforce_json_schema,
    workforce_contract_metadata,
)


WORKFORCE_HUB_BOUNDARY_SCHEMA = "agentlas.workforce-hub-boundary.v1"
WORKFORCE_SELECTION_HUB_BOUNDARY_SCHEMA = "agentlas.workforce-selection-hub-boundary.v1"

class WorkOrderHubBoundaryError(ValueError):
    """Raised before transport when Hub-bound free text is not public-safe."""

    def __init__(self, validation: Mapping[str, Any]):
        self.validation = dict(validation)
        suffix = ""
        if any(issue.get("code") == "ontology_version_mismatch" for issue in validation.get("issues") or []):
            suffix = ": ontology version mismatch"
        super().__init__("work_order_hub_boundary_rejected" + suffix)


class SelectionHubBoundaryError(ValueError):
    """Raised before transport when a Selection is invalid or not public-safe."""

    def __init__(self, validation: Mapping[str, Any]):
        self.validation = dict(validation)
        super().__init__("selection_hub_boundary_rejected")


def _add_unique(issues: list[dict[str, str]], path: str, code: str) -> None:
    issue = {"path": path, "code": code}
    if issue not in issues:
        issues.append(issue)


# SELF-PROVING FORMS ONLY — must stay identical to the Hub's
# `agentlas/AgentsAtlas/app/src/lib/workforce/privacy.ts` pattern set.
#
# A work order is task text the user wrote about the work they want done, and this
# boundary is non-repairing: it returns mutation "none" and never names the phrase to
# change.  So every class that GUESSES from natural-language shape killed real requests
# that the Hub itself accepts — "token: optional in the retry header" read as
# credential_assignment, "user id: required on every request" as labeled_identifier, an
# on-call number as phone, a web route as local_path.  Because index.py runs this as the
# first operation at the search boundary, such a run dies before a byte leaves the host,
# with nothing to tell the caller the Hub would have taken it.
#
# What stays is what can only be one thing: an issuer-prefixed provider token, a PEM
# header, a Bearer/JWT blob, credentials embedded in a URL, an email address.  Those hold
# with no model connected and cannot collide with a sentence about retry contracts.
# Deliberately gone (single-sourced regexes still live in experience_privacy for the
# accrual boundary, which has a judge): local-path, labeled-identifier, UUID, IP and phone
# shape inference, and keyword-adjacency credential matching.
_SELF_PROVING_IDENTIFIER_KINDS = frozenset({"email"})
_SELF_PROVING_SECRET_KINDS = frozenset(
    {"provider_token", "private_key", "bearer_token", "jwt", "credential_url"}
)


def _scan_contract_strings(value: Any, kind: str, issues: list[dict[str, str]]) -> None:
    for path, text in iter_workforce_contract_strings(value, kind):
        for private_kind in personal_identifier_kinds(text):
            if private_kind in _SELF_PROVING_IDENTIFIER_KINDS:
                _add_unique(issues, path, f"hub_private_{private_kind}")
        for secret_kind in secret_like_kinds(text):
            if secret_kind in _SELF_PROVING_SECRET_KINDS:
                _add_unique(issues, path, f"hub_secret_{secret_kind}")


def validate_hub_work_order_boundary(work_order: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete typed WorkOrder before the first outbound byte.

    The boundary applies the canonical JSON Schema, versioned graph semantics,
    bounded wire IDs, and privacy scanning to every schema-declared string.
    Semantic role/community/skill/knowledge IDs remain open-world. It never
    mutates or reflects a rejected value.
    """

    # Absent slot list fields mean [] — normalize before validation and before
    # the digest below, so omitted-form and full-form work orders produce the
    # same canonical bytes. Full forms pass through untouched.
    work_order = normalize_work_order(work_order)
    issues = validate_workforce_json_schema(work_order, "workOrder")
    semantic_issues = validate_work_order_semantics(work_order)
    if any(issue["code"] == "ontology_version_mismatch" for issue in semantic_issues):
        issues = [
            issue
            for issue in issues
            if not (issue["path"] == "ontologyVersion" and issue["code"] == "schema_const")
        ]
    issues.extend(issue for issue in semantic_issues if issue not in issues)
    if "redacted" in work_order and work_order.get("redacted") is not True:
        _add_unique(issues, "redacted", "hub_redacted_flag_required")
    _scan_contract_strings(work_order, "workOrder", issues)

    return {
        "schemaVersion": WORKFORCE_HUB_BOUNDARY_SCHEMA,
        "contract": workforce_contract_metadata("workOrder"),
        "status": "rejected" if issues else "accepted",
        "repairable": bool(issues),
        "mutation": "none",
        "workOrderDigest": None if issues else canonical_digest(work_order),
        "issues": issues,
    }


def validate_hub_selection_boundary(
    selection: Mapping[str, Any],
    *,
    work_order: Mapping[str, Any],
    candidate_set: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a host Selection and every context-finite identifier."""

    issues = validate_workforce_json_schema(selection, "selection")
    _scan_contract_strings(selection, "selection", issues)

    slot_ids = {
        str(slot.get("slotId"))
        for slot in work_order.get("roleSlots") or []
        if isinstance(slot, Mapping) and isinstance(slot.get("slotId"), str)
    }
    candidates_by_slot: dict[str, dict[str, Mapping[str, Any]]] = {}
    all_release_ids: set[str] = set()
    candidate_slots = candidate_set.get("slots")
    if isinstance(candidate_slots, list):
        for slot in candidate_slots:
            if not isinstance(slot, Mapping) or not isinstance(slot.get("slotId"), str):
                continue
            releases: dict[str, Mapping[str, Any]] = {}
            for candidate in slot.get("candidates") or []:
                if not isinstance(candidate, Mapping) or not isinstance(candidate.get("agentReleaseId"), str):
                    continue
                release_id = str(candidate["agentReleaseId"])
                releases[release_id] = candidate
                all_release_ids.add(release_id)
            candidates_by_slot[str(slot["slotId"])] = releases

    if candidate_set.get("ontologyVersion") != work_order.get("ontologyVersion"):
        _add_unique(issues, "candidateSet", "candidate_set_ontology_mismatch")
    if candidate_set.get("workOrderId") != work_order.get("workOrderId"):
        _add_unique(issues, "candidateSet", "candidate_set_work_order_mismatch")
    if selection.get("selectionSessionId") != candidate_set.get("selectionSessionId"):
        _add_unique(issues, "selectionSessionId", "selection_session_mismatch")
    if selection.get("candidateSetDigest") != candidate_set.get("candidateSetDigest"):
        _add_unique(issues, "candidateSetDigest", "candidate_set_digest_mismatch")

    artifact_ids: set[str] = set()
    for slot in work_order.get("roleSlots") or []:
        if isinstance(slot, Mapping):
            artifact_ids.update(str(item) for item in slot.get("consumes") or [] if isinstance(item, str))
            artifact_ids.update(str(item) for item in slot.get("produces") or [] if isinstance(item, str))
    for edge in work_order.get("edges") or []:
        if isinstance(edge, Mapping):
            artifact_ids.update(str(item) for item in edge.get("artifactKinds") or [] if isinstance(item, str))

    assignments = selection.get("assignments")
    if isinstance(assignments, list):
        for index, assignment in enumerate(assignments):
            if not isinstance(assignment, Mapping):
                continue
            slot_id = assignment.get("slotId")
            release_id = assignment.get("agentReleaseId")
            if isinstance(slot_id, str) and slot_id not in slot_ids:
                _add_unique(issues, f"assignments[{index}].slotId", "unknown_slot_id")
            candidate = candidates_by_slot.get(str(slot_id), {}).get(str(release_id))
            if isinstance(release_id, str) and candidate is None:
                _add_unique(issues, f"assignments[{index}].agentReleaseId", "release_outside_candidate_set")
            allowed_reasons = set(WORKFORCE_SELECTION_REASON_CODES)
            if isinstance(slot_id, str):
                allowed_reasons.add(f"fit:{slot_id}")
            if isinstance(candidate, Mapping):
                for field in ("fitEvidence", "qualificationEvidence", "optionalGaps"):
                    allowed_reasons.update(
                        str(item) for item in candidate.get(field) or [] if isinstance(item, str)
                    )
            reason_codes = assignment.get("reasonCodes")
            if isinstance(reason_codes, list):
                for reason_index, reason_code in enumerate(reason_codes):
                    if isinstance(reason_code, str) and reason_code not in allowed_reasons:
                        _add_unique(
                            issues,
                            f"assignments[{index}].reasonCodes[{reason_index}]",
                            "selection_reason_code_not_public_finite",
                        )

    edges = selection.get("edges")
    if isinstance(edges, list):
        for index, edge in enumerate(edges):
            if not isinstance(edge, Mapping):
                continue
            for field in ("fromSlot", "toSlot"):
                if isinstance(edge.get(field), str) and edge[field] not in slot_ids:
                    _add_unique(issues, f"edges[{index}].{field}", "unknown_slot_id")
            kinds = edge.get("artifactKinds")
            if isinstance(kinds, list):
                for kind_index, artifact_kind in enumerate(kinds):
                    if isinstance(artifact_kind, str) and artifact_kind not in artifact_ids:
                        _add_unique(
                            issues,
                            f"edges[{index}].artifactKinds[{kind_index}]",
                            "artifact_outside_work_order",
                        )

    alternatives = selection.get("alternativesConsidered")
    if isinstance(alternatives, list):
        for index, release_id in enumerate(alternatives):
            if isinstance(release_id, str) and release_id not in all_release_ids:
                _add_unique(issues, f"alternativesConsidered[{index}]", "release_outside_candidate_set")
    expansion = selection.get("requestExpansionForSlots")
    if isinstance(expansion, list):
        for index, slot_id in enumerate(expansion):
            if isinstance(slot_id, str) and slot_id not in slot_ids:
                _add_unique(issues, f"requestExpansionForSlots[{index}]", "unknown_slot_id")

    return {
        "schemaVersion": WORKFORCE_SELECTION_HUB_BOUNDARY_SCHEMA,
        "contract": workforce_contract_metadata("selection"),
        "status": "rejected" if issues else "accepted",
        "repairable": bool(issues),
        "mutation": "none",
        "selectionDigest": None if issues else canonical_digest(selection),
        "issues": issues,
    }


def assert_hub_work_order_boundary(work_order: Mapping[str, Any]) -> dict[str, Any]:
    validation = validate_hub_work_order_boundary(work_order)
    if validation["status"] != "accepted":
        raise WorkOrderHubBoundaryError(validation)
    return validation


def assert_hub_selection_boundary(
    selection: Mapping[str, Any],
    *,
    work_order: Mapping[str, Any],
    candidate_set: Mapping[str, Any],
) -> dict[str, Any]:
    validation = validate_hub_selection_boundary(
        selection,
        work_order=work_order,
        candidate_set=candidate_set,
    )
    if validation["status"] != "accepted":
        raise SelectionHubBoundaryError(validation)
    return validation


__all__ = [
    "WORKFORCE_HUB_BOUNDARY_SCHEMA",
    "WORKFORCE_SELECTION_HUB_BOUNDARY_SCHEMA",
    "WORKFORCE_SELECTION_REASON_CODES",
    "SelectionHubBoundaryError",
    "WorkOrderHubBoundaryError",
    "assert_hub_selection_boundary",
    "assert_hub_work_order_boundary",
    "validate_hub_selection_boundary",
    "validate_hub_work_order_boundary",
]
