"""Validate a caller's Build context assessment without inventing evidence.

The host owns source access, semantic judgment, user communication and any
interview witness.  A valid claim is not proof that any of those happened.
"""

from __future__ import annotations

import re
from typing import Any

SCHEMA_VERSION = "agentlas.build-context-assessment.v1"
RESULT_SCHEMA_VERSION = "agentlas.build-context-result.v1"
DIMENSIONS = frozenset({"goal", "constraints", "success", "context"})
SOURCE_KINDS = frozenset({"request", "conversation", "file", "existing_agent", "tool_result", "research", "memory"})
_STATES = frozenset({"supported", "assumed", "unknown", "conflict", "not_applicable"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ContextAssessmentError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _object(value: Any, allowed: frozenset[str], required: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContextAssessmentError(code)
    if set(value) - allowed or required - set(value):
        raise ContextAssessmentError(code)
    return value


def _id(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ContextAssessmentError(code)
    return value


def validate_context_assessment(value: Any) -> dict[str, Any]:
    """Validate and copy bounded claims; do not read, vouch for, or execute them.

    Source-reference IDs are only identifiers. Hosts must compare them against
    their own input inventory. No receipt or field supplied here proves a user
    answer, permission, host observation, or semantic model invocation.
    """
    obj = _object(
        value,
        frozenset({"schemaVersion", "status", "sourceCoverage", "evidenceRefs", "materialGaps", "reasonCode"}),
        frozenset({"schemaVersion", "status", "sourceCoverage", "evidenceRefs", "materialGaps"}),
        "invalid_assessment",
    )
    if obj["schemaVersion"] != SCHEMA_VERSION:
        raise ContextAssessmentError("unsupported_schema")
    status = obj["status"]
    if not isinstance(status, str) or status not in {"sufficient", "needs_input", "unverified"}:
        raise ContextAssessmentError("invalid_status")
    coverage, sources, gaps = obj["sourceCoverage"], obj["evidenceRefs"], obj["materialGaps"]
    if not isinstance(coverage, list) or len(coverage) > 4:
        raise ContextAssessmentError("invalid_source_coverage")
    if not isinstance(sources, list) or len(sources) > 64:
        raise ContextAssessmentError("invalid_evidence_refs")
    if not isinstance(gaps, list) or len(gaps) > 12:
        raise ContextAssessmentError("invalid_material_gaps")
    source_ids: set[str] = set()
    copied_sources = []
    for source in sources:
        source = _object(source, frozenset({"id", "kind"}), frozenset({"id", "kind"}), "invalid_evidence_ref")
        source_id = _id(source["id"], "invalid_evidence_ref_id")
        kind = source["kind"]
        if source_id in source_ids:
            raise ContextAssessmentError("duplicate_evidence_ref")
        if not isinstance(kind, str) or kind not in SOURCE_KINDS:
            raise ContextAssessmentError("invalid_evidence_kind")
        source_ids.add(source_id)
        copied_sources.append({"id": source_id, "kind": kind})

    copied_coverage = []
    seen_dimensions: set[str] = set()
    dimension_states: dict[str, str] = {}
    for row in coverage:
        row = _object(row, frozenset({"dimension", "state", "evidenceRefs", "note"}),
                      frozenset({"dimension", "state", "evidenceRefs"}), "invalid_coverage_row")
        dimension, state, refs = row["dimension"], row["state"], row["evidenceRefs"]
        if not isinstance(dimension, str) or dimension not in DIMENSIONS or dimension in seen_dimensions:
            raise ContextAssessmentError("invalid_coverage_dimension")
        if not isinstance(state, str) or state not in _STATES:
            raise ContextAssessmentError("invalid_coverage_state")
        if not isinstance(refs, list) or len(refs) > 16:
            raise ContextAssessmentError("invalid_coverage_refs")
        checked_refs = [_id(ref, "invalid_coverage_ref") for ref in refs]
        if len(set(checked_refs)) != len(checked_refs) or any(ref not in source_ids for ref in checked_refs):
            raise ContextAssessmentError("unknown_or_duplicate_coverage_ref")
        if state == "supported" and not checked_refs:
            raise ContextAssessmentError("supported_without_source")
        note = row.get("note")
        if "note" in row and (not isinstance(note, str) or not note.strip() or len(note) > 300):
            raise ContextAssessmentError("invalid_coverage_note")
        if state in {"assumed", "not_applicable"} and note is None:
            raise ContextAssessmentError("coverage_note_required")
        copied = {"dimension": dimension, "state": state, "evidenceRefs": checked_refs}
        if note is not None:
            copied["note"] = note
        copied_coverage.append(copied)
        seen_dimensions.add(dimension)
        dimension_states[dimension] = state

    copied_gaps = []
    gap_ids: set[str] = set()
    for gap in gaps:
        gap = _object(gap, frozenset({"id", "question"}), frozenset({"id", "question"}), "invalid_material_gap")
        gap_id = _id(gap["id"], "invalid_material_gap_id")
        question = gap["question"]
        if gap_id in gap_ids:
            raise ContextAssessmentError("duplicate_material_gap")
        if not isinstance(question, str) or not question.strip() or len(question) > 500:
            raise ContextAssessmentError("invalid_material_question")
        gap_ids.add(gap_id)
        copied_gaps.append({"id": gap_id, "question": question})

    reason = obj.get("reasonCode")
    if "reasonCode" in obj and (not isinstance(reason, str) or not _REASON.fullmatch(reason)):
        raise ContextAssessmentError("invalid_reason_code")
    if status == "needs_input" and not copied_gaps:
        raise ContextAssessmentError("material_question_required")
    if status == "unverified" and not reason:
        raise ContextAssessmentError("reason_code_required")
    if status == "sufficient":
        if copied_gaps or seen_dimensions != DIMENSIONS or not copied_sources:
            raise ContextAssessmentError("incomplete_sufficient_claim")
        if any(state in {"unknown", "conflict"} for state in dimension_states.values()):
            raise ContextAssessmentError("unresolved_sufficient_claim")
        if any(dimension_states.get(dim) != "supported" for dim in ("goal", "success")):
            raise ContextAssessmentError("goal_and_success_need_sources")

    result = {"schemaVersion": SCHEMA_VERSION, "status": status, "sourceCoverage": copied_coverage,
              "evidenceRefs": copied_sources, "materialGaps": copied_gaps}
    if reason is not None:
        result["reasonCode"] = reason
    return result


def assess_build_context(value: Any) -> dict[str, Any]:
    """Return the caller claim with explicit, non-authoritative provenance."""
    assessment = validate_context_assessment(value)
    return {
        "schemaVersion": RESULT_SCHEMA_VERSION,
        "status": assessment["status"],
        "assessment": assessment,
        "semanticProvenance": "caller_claim",
        "sourceVerification": "unverified",
        "hostWitness": "not_checked",
        "authorizationGranted": False,
        "modelInvoked": False,
    }
