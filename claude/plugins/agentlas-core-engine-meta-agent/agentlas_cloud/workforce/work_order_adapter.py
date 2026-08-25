"""Compact semantic draft adapter for canonical Workforce WorkOrders.

The public WorkOrder is deliberately strict because it crosses a privacy and
federation boundary.  It is a poor authoring surface, though: a host model had
to invent finite transaction IDs, repeat fifteen empty arrays per slot, and
keep edge/artifact identifiers byte-consistent.  This adapter keeps that wire
contract strict while moving the mechanical work into deterministic Core code.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .contracts import (
    WORKFORCE_ONTOLOGY_VERSION,
    WORKFORCE_V1_PUBLIC_ARTIFACT_IDS,
    WORKFORCE_V1_PUBLIC_AUTHORITY_IDS,
    WORKFORCE_V1_PUBLIC_LANGUAGE_IDS,
    WORKFORCE_V1_PUBLIC_MODALITY_IDS,
    WORKFORCE_V1_PUBLIC_RUNTIME_IDS,
    canonical_digest,
    normalize_work_order,
)
from .privacy import validate_hub_work_order_boundary


WORKFORCE_WORK_ORDER_PREFLIGHT_SCHEMA = "agentlas.workforce-work-order-preflight.v1"

_SEMANTIC_SLOT_LIST_FIELDS = (
    "requiredCommunities",
    "optionalCommunities",
    "excludedCommunities",
    "requiredRoles",
    "requiredSkills",
    "optionalSkills",
    "requiredKnowledge",
    "requiredToolCapabilities",
)
_FINITE_SLOT_LIST_FIELDS = (
    "requiredAuthorities",
    "forbiddenAuthorities",
    "runtimes",
    "languages",
    "modalities",
)
_ALLOWED_ROLE_FIELDS = frozenset({
    "title",
    "task",
    # Several phrasings of the same slot, joined into `task`. Ranking uses the
    # slot's title plus task as its query text, and one request rarely matches a
    # card in only one wording — "our webhook double-charges", "duplicate effects
    # under retry", and "design an idempotency key" reach different cards even
    # though they describe one job. Authors kept cramming these into one
    # sentence; letting them list the phrasings is the whole of what a v2 work
    # order was going to add, without a second wire schema to keep alive.
    "queries",
    "cardinality",
    "criticality",
    "allowedEntityKinds",
    "minimumEvidenceLevel",
    *_SEMANTIC_SLOT_LIST_FIELDS,
    *_FINITE_SLOT_LIST_FIELDS,
})
_ALLOWED_DRAFT_FIELDS = frozenset({
    "taskBrief",
    "roles",
    "edges",
    "forbiddenCommunities",
    "selectionPolicy",
})
_ALLOWED_EDGE_FIELDS = frozenset({
    "fromRole",
    "toRole",
    "relation",
    "artifactKinds",
})


class WorkOrderDraftError(ValueError):
    """A compact, non-reflecting authoring refusal."""

    def __init__(self, code: str, issues: list[dict[str, str]]):
        self.code = code
        self.issues = issues
        super().__init__(code)


# The public schema accepts `^[A-Za-z0-9][A-Za-z0-9._:/@-]{1,255}$` for every
# semantic concept id.  A host model writes what a human would ("network
# efficiency research"), and the old adapter passed that straight through to a
# boundary refusal whose only word was `schema_pattern`.  Turning a phrase into
# the concept id it obviously means is mechanical, so Core does it — the same
# reason the adapter exists at all.  What cannot be reduced to an ASCII concept
# (a pure Korean phrase, say) is refused with a code that says what to do.
_CONCEPT_UNSAFE_RE = re.compile(r"[^a-z0-9._:/@-]+")
_CONCEPT_DASHES_RE = re.compile(r"-{2,}")


def _normalize_concept(value: str) -> str | None:
    text = str(value).strip().lower().replace("_", "-")
    # A non-ASCII letter or digit IS the concept; the ASCII-only substitution
    # below can only delete it.  `role:성능-조사자` used to survive that as the
    # bare namespace `role` — accepted, pinned as a mandatory requirement, and
    # then matched against nothing, so every candidate came back
    # `missing-role:role`.  Only a concept with no ASCII at all reached the
    # refusal; one carrying an ASCII prefix slipped past it.  Refuse whenever
    # normalization would drop meaning, not just when it would drop everything.
    if any(ch.isalnum() and not ch.isascii() for ch in text):
        return None
    text = _CONCEPT_UNSAFE_RE.sub("-", text)
    text = _CONCEPT_DASHES_RE.sub("-", text).strip("-.:/@")
    if not 2 <= len(text) <= 256 or not text[0].isalnum():
        return None
    return text


def _add(issues: list[dict[str, str]], path: str, code: str) -> None:
    issue = {"path": path, "code": code}
    if issue not in issues:
        issues.append(issue)


def _validate_string_list(
    value: Any,
    path: str,
    issues: list[dict[str, str]],
    *,
    allowed: frozenset[str] | None = None,
    normalized: list[dict[str, str]] | None = None,
) -> list[str]:
    """Validate one draft list.

    Finite lists (``allowed`` given) are exact enums and are never rewritten.
    Open-world concept lists are normalized into schema-valid concept ids, and
    every rewrite is reported back to the author instead of applied silently.
    """

    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 256:
        _add(issues, path, "draft_string_list_invalid")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, str) or not item.strip():
            _add(issues, item_path, "draft_id_invalid")
            continue
        if allowed is not None:
            if item not in allowed:
                _add(issues, item_path, "draft_finite_id_invalid")
                continue
            concept = item
        else:
            concept = _normalize_concept(item) or ""
            if not concept:
                _add(issues, item_path, "draft_concept_not_normalizable")
                continue
            if concept != item and normalized is not None:
                entry = {"path": item_path, "from": item, "to": concept}
                if entry not in normalized:
                    normalized.append(entry)
        if concept in result:
            _add(issues, item_path, "draft_id_duplicate")
            continue
        result.append(concept)
    return result


def compile_work_order_draft(
    draft: Mapping[str, Any],
    *,
    _normalized_out: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Compile a small semantic draft into the exact public v1 WorkOrder.

    Slot and WorkOrder IDs are deterministic opaque/ordinal identifiers.

    ★Edges are a declaration of flow, never a qualification requirement.
    Compiling them into each slot's consumes/produces looked like a consistency
    win and was measured to be a discovery killer: `artifact:worker-result` is
    the default edge artifact and 0 of 849 local workforce profiles declare it
    (produces is declared by 5.9%, consumes by 2.9%), so every candidate of every
    slot came back with a mandatory gap. A requirement axis that almost nobody
    populates is not a filter, it is an extinction event. Requirements are now
    exactly what the author asked for; the handoff stays in `edges`.
    """

    if not isinstance(draft, Mapping):
        raise WorkOrderDraftError(
            "work_order_draft_invalid",
            [{"path": "draft", "code": "draft_object_required"}],
        )
    issues: list[dict[str, str]] = []
    normalized: list[dict[str, str]] = [] if _normalized_out is None else _normalized_out
    for field in sorted(set(draft) - _ALLOWED_DRAFT_FIELDS):
        _add(issues, str(field), "draft_additional_property")

    task_brief = draft.get("taskBrief")
    if not isinstance(task_brief, str) or not task_brief.strip() or len(task_brief) > 64_000:
        _add(issues, "taskBrief", "draft_task_brief_invalid")

    raw_roles = draft.get("roles")
    if not isinstance(raw_roles, list) or not 1 <= len(raw_roles) <= 32:
        _add(issues, "roles", "draft_roles_invalid")
        raw_roles = []

    roles: list[dict[str, Any]] = []
    finite_catalogs = {
        "requiredAuthorities": WORKFORCE_V1_PUBLIC_AUTHORITY_IDS,
        "forbiddenAuthorities": WORKFORCE_V1_PUBLIC_AUTHORITY_IDS,
        "runtimes": WORKFORCE_V1_PUBLIC_RUNTIME_IDS,
        "languages": WORKFORCE_V1_PUBLIC_LANGUAGE_IDS,
        "modalities": WORKFORCE_V1_PUBLIC_MODALITY_IDS,
    }
    for index, raw_role in enumerate(raw_roles):
        base = f"roles[{index}]"
        if not isinstance(raw_role, Mapping):
            _add(issues, base, "draft_role_object_required")
            continue
        for field in sorted(set(raw_role) - _ALLOWED_ROLE_FIELDS):
            _add(issues, f"{base}.{field}", "draft_additional_property")
        title = raw_role.get("title")
        task = raw_role.get("task")
        raw_queries = raw_role.get("queries")
        if raw_queries is not None:
            if (
                not isinstance(raw_queries, list)
                or not raw_queries
                or len(raw_queries) > 8
                or any(not isinstance(q, str) or not q.strip() for q in raw_queries)
            ):
                _add(issues, f"{base}.queries", "draft_role_queries_invalid")
            elif task is None:
                task = "\n".join(q.strip() for q in raw_queries)
            else:
                # Both given: the author's own sentence leads, the phrasings follow.
                task = "\n".join([task.strip(), *(q.strip() for q in raw_queries)])
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            _add(issues, f"{base}.title", "draft_role_title_invalid")
        if not isinstance(task, str) or not task.strip() or len(task) > 32_000:
            _add(issues, f"{base}.task", "draft_role_task_invalid")
        cardinality = raw_role.get("cardinality", 1)
        if (
            not isinstance(cardinality, int)
            or isinstance(cardinality, bool)
            or not 1 <= cardinality <= 16
        ):
            _add(issues, f"{base}.cardinality", "draft_cardinality_invalid")
            cardinality = 1
        criticality = raw_role.get("criticality", "required")
        if criticality not in {"required", "optional"}:
            _add(issues, f"{base}.criticality", "draft_criticality_invalid")
            criticality = "required"
        entity_kinds = raw_role.get("allowedEntityKinds", ["agent", "team"])
        if (
            not isinstance(entity_kinds, list)
            or not entity_kinds
            or any(not isinstance(item, str) or item not in {"agent", "team"} for item in entity_kinds)
            or len(entity_kinds) != len(set(entity_kinds))
        ):
            _add(issues, f"{base}.allowedEntityKinds", "draft_entity_kinds_invalid")
            entity_kinds = ["agent", "team"]
        minimum_evidence = raw_role.get("minimumEvidenceLevel")
        if minimum_evidence is not None and minimum_evidence not in {
            "declared",
            "checked",
            "demonstrated",
            "attested",
        }:
            _add(issues, f"{base}.minimumEvidenceLevel", "draft_evidence_level_invalid")

        role: dict[str, Any] = {
            "slotId": f"slot:ordinal-{index + 1}",
            "title": title,
            "task": task,
            "cardinality": cardinality,
            "criticality": criticality,
            "allowedEntityKinds": list(entity_kinds),
        }
        for field in _SEMANTIC_SLOT_LIST_FIELDS:
            role[field] = _validate_string_list(
                raw_role.get(field), f"{base}.{field}", issues, normalized=normalized
            )
        for field in _FINITE_SLOT_LIST_FIELDS:
            role[field] = _validate_string_list(
                raw_role.get(field),
                f"{base}.{field}",
                issues,
                allowed=finite_catalogs[field],
            )
        role["consumes"] = []
        role["produces"] = []
        if minimum_evidence is not None:
            role["minimumEvidenceLevel"] = minimum_evidence
        roles.append(role)

    edges: list[dict[str, Any]] = []
    raw_edges = draft.get("edges", [])
    if not isinstance(raw_edges, list) or len(raw_edges) > 128:
        _add(issues, "edges", "draft_edges_invalid")
        raw_edges = []
    for index, raw_edge in enumerate(raw_edges):
        base = f"edges[{index}]"
        if not isinstance(raw_edge, Mapping):
            _add(issues, base, "draft_edge_object_required")
            continue
        for field in sorted(set(raw_edge) - _ALLOWED_EDGE_FIELDS):
            _add(issues, f"{base}.{field}", "draft_additional_property")
        from_role = raw_edge.get("fromRole")
        to_role = raw_edge.get("toRole")
        if (
            not isinstance(from_role, int)
            or isinstance(from_role, bool)
            or not 1 <= from_role <= len(roles)
        ):
            _add(issues, f"{base}.fromRole", "draft_role_ordinal_invalid")
        if (
            not isinstance(to_role, int)
            or isinstance(to_role, bool)
            or not 1 <= to_role <= len(roles)
        ):
            _add(issues, f"{base}.toRole", "draft_role_ordinal_invalid")
        relation = raw_edge.get("relation", "handsOffTo")
        if relation not in {"reportsTo", "handsOffTo", "reviews", "coordinatesWith"}:
            _add(issues, f"{base}.relation", "draft_relation_invalid")
        artifact_kinds = _validate_string_list(
            raw_edge.get("artifactKinds", ["artifact:worker-result"]),
            f"{base}.artifactKinds",
            issues,
            allowed=WORKFORCE_V1_PUBLIC_ARTIFACT_IDS,
        )
        if not artifact_kinds:
            artifact_kinds = ["artifact:worker-result"]
        if (
            isinstance(from_role, int)
            and not isinstance(from_role, bool)
            and 1 <= from_role <= len(roles)
            and isinstance(to_role, int)
            and not isinstance(to_role, bool)
            and 1 <= to_role <= len(roles)
        ):
            # Deliberately no write into roles[*]["produces"/"consumes"] — see
            # the compile docstring. The edge itself carries the handoff.
            edges.append({
                "from": roles[from_role - 1]["slotId"],
                "to": roles[to_role - 1]["slotId"],
                "relation": relation,
                "artifactKinds": artifact_kinds,
            })

    forbidden = _validate_string_list(
        draft.get("forbiddenCommunities"),
        "forbiddenCommunities",
        issues,
        normalized=normalized,
    )
    raw_policy = draft.get("selectionPolicy", {})
    if not isinstance(raw_policy, Mapping):
        _add(issues, "selectionPolicy", "draft_selection_policy_invalid")
        raw_policy = {}
    for field in sorted(set(raw_policy) - {"minimumCandidatesPerSlot", "maximumCandidatesPerSlot"}):
        _add(issues, f"selectionPolicy.{field}", "draft_additional_property")
    minimum = raw_policy.get("minimumCandidatesPerSlot", 2)
    # 4, not 8. Measured on the 116 routing-eligible profiles in this repo with
    # 389 English queries (leave-one-out): the correct agent is inside the top 4
    # for 97.4% of them and inside the top 3 for 97.2%, so slots 5-8 buy 0.2
    # points while doubling what the host LLM reads. A candidate card averages
    # 368 characters, so the default drops a one-slot menu from ~2,900 to ~950.
    # A caller that wants a wider menu still asks for one.
    maximum = raw_policy.get("maximumCandidatesPerSlot", 4)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or not 2 <= minimum <= 30:
        _add(issues, "selectionPolicy.minimumCandidatesPerSlot", "draft_candidate_minimum_invalid")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 2 <= maximum <= 100:
        _add(issues, "selectionPolicy.maximumCandidatesPerSlot", "draft_candidate_maximum_invalid")
    if isinstance(minimum, int) and isinstance(maximum, int) and minimum > maximum:
        _add(issues, "selectionPolicy", "draft_candidate_range_invalid")

    if issues:
        raise WorkOrderDraftError("work_order_draft_invalid", issues)

    # The ID is content-derived and contains no user text. It stays stable across
    # retries while satisfying the public finite-ID policy.
    order_digest = canonical_digest({
        "taskBrief": task_brief,
        "roles": roles,
        "edges": edges,
        "forbiddenCommunities": forbidden,
        "selectionPolicy": {
            "minimumCandidatesPerSlot": minimum,
            "maximumCandidatesPerSlot": maximum,
        },
    })
    work_order = normalize_work_order({
        "schemaVersion": "agentlas.workforce-work-order.v1",
        "workOrderId": f"work-order:opaque-{order_digest.removeprefix('sha256:')}",
        "taskBrief": task_brief,
        "redacted": True,
        "ontologyVersion": WORKFORCE_ONTOLOGY_VERSION,
        "roleSlots": roles,
        "edges": edges,
        "forbiddenCommunities": forbidden,
        "selectionPolicy": {
            "minimumCandidatesPerSlot": minimum,
            "maximumCandidatesPerSlot": maximum,
            "allowHistoryEvidence": False,
        },
    })
    boundary = validate_hub_work_order_boundary(work_order)
    if boundary.get("status") != "accepted":
        raise WorkOrderDraftError(
            "work_order_draft_boundary_rejected",
            [
                {"path": str(issue.get("path") or "workOrder"), "code": str(issue.get("code") or "invalid")}
                for issue in boundary.get("issues") or []
                if isinstance(issue, Mapping)
            ],
        )
    return work_order


def compile_work_order_draft_with_report(
    draft: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Compile a draft and report every concept id Core rewrote for the author."""

    report: list[dict[str, str]] = []
    work_order = compile_work_order_draft(draft, _normalized_out=report)
    return work_order, report


WORKFORCE_SELECTION_DRAFT_SCHEMA = "agentlas.workforce-selection-draft.v1"

_ALLOWED_DECISION_FIELDS = frozenset({
    "selectionSessionId",
    "decisionAuthor",
    "assignments",
    "edges",
    "alternativesConsidered",
    "requestExpansionForSlots",
})
_ALLOWED_ASSIGNMENT_FIELDS = frozenset({
    "slotId",
    "candidateOrdinal",
    "agentReleaseId",
    "reasonCodes",
})
_ALLOWED_DECISION_EDGE_FIELDS = frozenset({
    "fromSlot",
    "toSlot",
    "relation",
    "artifactKinds",
})


def compile_selection_draft(
    decision: Mapping[str, Any],
    *,
    candidate_set_digest: str,
) -> dict[str, Any]:
    """Compile a compact staffing decision into the exact public v1 Selection.

    ★WorkOrder 에서 없앤 의례가 Selection 에 그대로 남아 있었다 — 실측
    2026-08-20: `alternativesConsidered` 와 `requestExpansionForSlots` 를
    빠뜨리면 `schema_required` 로 거절되는데, 둘 다 거의 항상 빈 배열이다.
    후보 서수는 이미 메뉴가 주고 candidateSetDigest 는 Core 가 핀해 두고 있다.
    저자가 실제로 정하는 것은 "어느 자리에 몇 번 후보를, 왜" 세 가지뿐이다.
    """

    if not isinstance(decision, Mapping):
        raise WorkOrderDraftError(
            "selection_draft_invalid",
            [{"path": "decision", "code": "draft_object_required"}],
        )
    issues: list[dict[str, str]] = []
    for field in sorted(set(decision) - _ALLOWED_DECISION_FIELDS):
        _add(issues, str(field), "draft_additional_property")

    session_id = decision.get("selectionSessionId")
    if not isinstance(session_id, str) or not session_id.strip():
        _add(issues, "selectionSessionId", "draft_selection_session_required")

    author = decision.get("decisionAuthor")
    model_id = author.get("modelId") if isinstance(author, Mapping) else None
    if not isinstance(model_id, str) or not model_id.strip():
        _add(issues, "decisionAuthor.modelId", "draft_decision_author_required")
    runtime_id = author.get("runtimeId") if isinstance(author, Mapping) else None

    raw_assignments = decision.get("assignments")
    if not isinstance(raw_assignments, list) or not 1 <= len(raw_assignments) <= 64:
        _add(issues, "assignments", "draft_assignments_invalid")
        raw_assignments = []
    assignments: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_assignments):
        base = f"assignments[{index}]"
        if not isinstance(raw, Mapping):
            _add(issues, base, "draft_assignment_object_required")
            continue
        for field in sorted(set(raw) - _ALLOWED_ASSIGNMENT_FIELDS):
            _add(issues, f"{base}.{field}", "draft_additional_property")
        slot_id = raw.get("slotId")
        if not isinstance(slot_id, str) or not slot_id.strip():
            _add(issues, f"{base}.slotId", "draft_slot_id_required")
            continue
        ordinal = raw.get("candidateOrdinal")
        release_id = raw.get("agentReleaseId")
        has_ordinal = isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal >= 1
        has_release = isinstance(release_id, str) and bool(release_id.strip())
        if not has_ordinal and not has_release:
            _add(issues, base, "draft_candidate_reference_required")
            continue
        reasons = raw.get("reasonCodes")
        if reasons is None:
            reasons = ["reason:host-semantic-judgment"]
        reasons = _validate_string_list(reasons, f"{base}.reasonCodes", issues)
        if not reasons:
            reasons = ["reason:host-semantic-judgment"]
        row: dict[str, Any] = {"slotId": slot_id, "reasonCodes": reasons}
        if has_ordinal:
            row["candidateOrdinal"] = ordinal
        if has_release:
            row["agentReleaseId"] = release_id
        assignments.append(row)

    edges: list[dict[str, Any]] = []
    raw_edges = decision.get("edges", [])
    if not isinstance(raw_edges, list) or len(raw_edges) > 128:
        _add(issues, "edges", "draft_edges_invalid")
        raw_edges = []
    for index, raw in enumerate(raw_edges):
        base = f"edges[{index}]"
        if not isinstance(raw, Mapping):
            _add(issues, base, "draft_edge_object_required")
            continue
        for field in sorted(set(raw) - _ALLOWED_DECISION_EDGE_FIELDS):
            _add(issues, f"{base}.{field}", "draft_additional_property")
        from_slot = raw.get("fromSlot")
        to_slot = raw.get("toSlot")
        if not isinstance(from_slot, str) or not isinstance(to_slot, str):
            _add(issues, base, "draft_edge_slot_required")
            continue
        relation = raw.get("relation", "handsOffTo")
        if relation not in {"reportsTo", "handsOffTo", "reviews", "coordinatesWith"}:
            _add(issues, f"{base}.relation", "draft_relation_invalid")
            relation = "handsOffTo"
        artifacts = _validate_string_list(
            raw.get("artifactKinds", ["artifact:worker-result"]),
            f"{base}.artifactKinds",
            issues,
            allowed=WORKFORCE_V1_PUBLIC_ARTIFACT_IDS,
        ) or ["artifact:worker-result"]
        edges.append({
            "fromSlot": from_slot,
            "toSlot": to_slot,
            "relation": relation,
            "artifactKinds": artifacts,
        })

    alternatives = _validate_string_list(
        decision.get("alternativesConsidered"), "alternativesConsidered", issues
    )
    expansion = _validate_string_list(
        decision.get("requestExpansionForSlots"), "requestExpansionForSlots", issues
    )
    if issues:
        raise WorkOrderDraftError("selection_draft_invalid", issues)
    return {
        "schemaVersion": "agentlas.workforce-selection.v1",
        "selectionSessionId": str(session_id),
        "candidateSetDigest": candidate_set_digest,
        "decisionAuthor": {
            "kind": "host_llm",
            "modelId": str(model_id),
            "runtimeId": str(runtime_id) if isinstance(runtime_id, str) and runtime_id.strip() else None,
        },
        "assignments": assignments,
        "edges": edges,
        "alternativesConsidered": alternatives,
        "requestExpansionForSlots": expansion,
    }
