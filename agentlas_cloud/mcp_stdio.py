"""Local stdio MCP server for Hephaestus Workforce and legacy routing tools.

The canonical Network path federates registered Local, owner Cloud, and public
Hub candidate menus.  The active host LLM authors the exact-release selection;
Core validates and prepares that pinned roster without scoring, reranking, or
silently widening an explicit source scope.  Deterministic card-router tools
remain available only behind the explicit legacy/debug opt-in.

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout (MCP stdio). No
third-party dependencies.
"""

from __future__ import annotations

import json
from .public_prompt_composition import tool_schema_description
import os
import re
import sqlite3
import sys
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .model_allocation import (
    EFFORT_RANK,
    INVOCATION_STAGE_PHASES,
    canonical_phase_for_stage,
    model_role_for_stage,
    normalize_effort,
    _policy_for_role,
    resolve_model_allocation,
)
from .workforce.contracts import (
    WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256,
    WORKFORCE_ONTOLOGY_VERSION,
    WORKFORCE_SELECTION_REASON_CODES,
    canonical_digest,
    load_workforce_contract_schema,
    normalize_work_order,
    workforce_contract_metadata,
)
from .workforce.execution import (
    WORKFORCE_EXECUTION_PLAN_SCHEMA,
    WORKFORCE_EXECUTION_RECEIPT_SCHEMA,
)
from .workforce.federation import WORKFORCE_FEDERATION_RESULT_SCHEMA
from .workforce.goal_binding import (
    workforce_preparation_ready,
    workforce_preparation_refusal,
)
from .workforce.host_execution_contract import (
    goal_runtime_execution_contract,
    host_execution_contract,
)
from .workforce.provenance import (
    WORKFORCE_FEDERATED_PREPARATION_SCHEMA,
    WORKFORCE_FEDERATED_SELECTION_SCHEMA,
)
from .networking.lease_tools import LEASE_TOOLS, PURCHASE as LEASE_PURCHASE, QUOTE as LEASE_QUOTE, call_agent_lease_tool
from .networking.takedown_tools import TAKEDOWN, TAKEDOWN_TOOLS, call_agent_takedown_tool

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "hephaestus-network", "version": "1.2.95"}

# Roots this process has already seeded, so only the first tool call in a
# session pays the bootstrap cost.
_FIRST_CONTACT_ROOTS: set[str] = set()

# Only these legacy project-grounded tools read the caller's working tree or
# Work Brief at the common MCP boundary.  Typed Workforce tools keep their
# exact WorkOrder/candidate state in private Core stores. Context tools own
# their explicit projectDir lifecycle and must not bootstrap a second time here.
_COMMON_PROJECT_BOOTSTRAP_TOOLS = frozenset(
    {
        "hephaestus_route",
        "hephaestus_cloud_search",
        "hephaestus_search",
        "hephaestus_call",
        "hephaestus_hub_invoke",
    }
)


# Preparation serves the project's existing Context Map read-only; it never
# builds one. Building belongs to context.slice / `agentlas context refresh`.
# A stale or missing map is reported with localContextSliceCode, never built here.
# The freshness bound is the read-only recall contract memory_hook already
# uses (context_map.RECALL_FRESHNESS_BUDGET_SECONDS), passed at the call site.
PREPARE_CONTEXT_SLICE_READ: dict[str, Any] = {
    "refresh": False,
    "allow_stale": True,
}


def _claim_first_contact(project_dir: str) -> bool:
    """True once per resolved root per process."""

    try:
        key = str(Path(project_dir).expanduser().resolve())
    except (OSError, ValueError):
        key = project_dir
    if key in _FIRST_CONTACT_ROOTS:
        return False
    _FIRST_CONTACT_ROOTS.add(key)
    return True
from .model_policy import MODEL_ALLOCATION_POLICY_ENV, _host_model_allocation_policy
WORKFORCE_PROTOCOL_VERSION = "2026-08-21.1"


def workforce_protocol_metadata() -> dict[str, Any]:
    metadata = {
        "schemaVersion": "agentlas.workforce-protocol-metadata.v1",
        "protocolVersion": WORKFORCE_PROTOCOL_VERSION,
        "ontologyVersion": WORKFORCE_ONTOLOGY_VERSION,
        "ontologySnapshotSha256": WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256,
        "candidateSetSchemaVersion": "agentlas.workforce-candidate-set.v1",
        "federationResultSchemaVersion": WORKFORCE_FEDERATION_RESULT_SCHEMA,
        "federatedSelectionSchemaVersion": WORKFORCE_FEDERATED_SELECTION_SCHEMA,
        "federatedPreparationSchemaVersion": WORKFORCE_FEDERATED_PREPARATION_SCHEMA,
        "executionPlanSchemaVersion": WORKFORCE_EXECUTION_PLAN_SCHEMA,
        "executionReceiptSchemaVersion": WORKFORCE_EXECUTION_RECEIPT_SCHEMA,
        "sourceScopeRequired": True,
        "prepareAttemptSchemaVersion": "agentlas.workforce-prepare-attempt.v1",
        "sourceFetchIdempotencySchemaVersion": "agentlas.workforce-source-fetch-idempotency.v1",
        "sourceBundleReceiptSchemaVersion": "agentlas.workforce-source-bundle-verification.v1",
        "prepareIdempotencyRequired": True,
        "goalBindingSchemaVersion": "agentlas.workforce-goal-binding.v1",
        "goalContextSchemaVersion": "agentlas.workforce-goal-context.v1",
        "goalTurnSchemaVersion": "agentlas.workforce-goal-turn.v1",
        "goalRosterLifetime": "until-explicit-completion",
        "workOrderPreflightSchemaVersion": "agentlas.workforce-work-order-preflight.v1",
        "workOrderPreflightLifetime": "one-hour-local-reference",
        "codeMapSchemaVersion": "agentlas.code-map.v2",
        "contextSliceSchemaVersion": "agentlas.context-slice.v1",
        "contextImpactReceiptSchemaVersion": "agentlas.context-impact-receipt.v2",
        "contextVerificationReceiptSchemaVersion": "agentlas.context-verification-receipt.v2",
        "contextRefreshDefault": "change-driven-auto-on-next-context-call",
        "localContextNetworkTransfer": "denied",
    }
    metadata["protocolDigest"] = canonical_digest(metadata)
    return metadata


def workforce_tool_meta() -> dict[str, Any]:
    """MCP clients preserve tool metadata only inside the standard `_meta` bag."""

    return {"agentlas/workforce-protocol": workforce_protocol_metadata()}


def _contract_property(kind: str, description: str) -> dict[str, Any]:
    metadata = workforce_contract_metadata(kind)
    schema = deepcopy(load_workforce_contract_schema(kind))
    schema["description"] = description
    schema["x-agentlas-contract"] = metadata
    return schema


def _contract_echo_property(kind: str, description: str) -> dict[str, Any]:
    """A value the host received from an earlier Workforce call and returns unchanged.

    Inlining the full contract schema here advertises a shape the host is not
    allowed to author: the value must be echoed byte-for-byte or the pinned
    candidate set stops matching. The schema is still enforced — the handler
    revalidates against the canonical contract — so publishing it a second and
    third time only spends the host's context.

    Only the value the host actually authors (the first call's workOrder, and
    the selection it writes) keeps its full schema via _contract_property.

    The contract metadata is dropped here for the same reason as the schema:
    it tells the host which shape to author, and an echoed value is not
    authored. `kind` stays in the signature so the call site still names the
    contract this argument carries.
    """
    del kind
    return {
        "type": "object",
        "description": description,
    }


def _selection_property_with_ordinal(description: str) -> dict[str, Any]:
    """Selection schema for verification tools only — allows specifying an
    ordinal (candidateOrdinal) instead of a release ID.

    Does not touch the canonical schemas/workforce-selection.schema.json (the
    Hub/Terminal contract). This relaxation is valid only for MCP tool input;
    the handler resolves the ordinal against the stored menu into the exact
    agentReleaseId, then passes the canonical shape on to deep validation.
    Ordinals avoid requiring the caller to transcribe opaque release IDs.
    """
    schema = _contract_property("selection", description)
    try:
        items = schema["properties"]["assignments"]["items"]
        items["required"] = ["slotId", "reasonCodes"]
        items["properties"]["candidateOrdinal"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "description": "The candidate's ordinal in the menu. May be given instead of agentReleaseId — the server resolves it to the exact release from the stored session menu.",
        }
    except (KeyError, TypeError):
        pass
    return schema


def _prepare_selection_property() -> dict[str, Any]:
    """Distinguish an exact Selection from a pinned accepted reference."""

    session = {"type": "string", "minLength": 1, "maxLength": 256}
    digest = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    return {
        "description": (
            "Prefer {selectionSessionId} plus top-level federatedSelectionDigest from the "
            "accepted validation result. Core restores only that exact pinned Selection. "
            "The unchanged accepted validation wrapper or original exact Selection is also accepted."
        ),
        "anyOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["selectionSessionId"],
                "properties": {
                    "selectionSessionId": session,
                    "federatedSelectionDigest": digest,
                },
            },
            {
                "type": "object",
                "required": ["schemaVersion", "selectionSessionId", "assignments"],
                "properties": {
                    "schemaVersion": {"const": "agentlas.workforce-selection.v1"},
                    "selectionSessionId": session,
                    "assignments": {"type": "array", "minItems": 1},
                },
            },
            {
                "type": "object",
                "required": ["schemaVersion", "status", "selectionSessionId", "federatedSelectionDigest"],
                "properties": {
                    "schemaVersion": {"const": WORKFORCE_FEDERATED_SELECTION_SCHEMA},
                    "status": {"const": "accepted"},
                    "selectionSessionId": session,
                    "federatedSelectionDigest": digest,
                },
            },
        ],
    }


def _work_order_draft_schema() -> dict[str, Any]:
    """Small authoring contract compiled into the strict public WorkOrder.

    The exact wire schema remains available to legacy callers, but the normal
    host path should never guess finite IDs or repeat empty slot arrays.
    """

    catalog = workforce_contract_metadata("workOrder")["publicIdCatalog"]
    concept_list = {
        "type": "array",
        "maxItems": 256,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 2, "maxLength": 256},
    }
    finite_lists = {
        "requiredAuthorities": catalog["authorityIds"],
        "forbiddenAuthorities": catalog["authorityIds"],
        "runtimes": catalog["runtimeIds"],
        "languages": catalog["languageIds"],
        "modalities": catalog["modalityIds"],
    }
    role_properties: dict[str, Any] = {
        "title": {"type": "string", "minLength": 1, "maxLength": 160},
        "task": {"type": "string", "minLength": 1, "maxLength": 32000},
        "cardinality": {"type": "integer", "minimum": 1, "maximum": 16, "default": 1},
        "criticality": {"type": "string", "enum": ["required", "optional"], "default": "required"},
        "allowedEntityKinds": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "enum": ["agent", "team"]},
            "default": ["agent", "team"],
        },
        "minimumEvidenceLevel": {
            "type": "string",
            "enum": ["declared", "checked", "demonstrated", "attested"],
        },
    }
    for field in (
        "requiredCommunities",
        "optionalCommunities",
        "excludedCommunities",
        "requiredRoles",
        "requiredSkills",
        "optionalSkills",
        "requiredKnowledge",
        "requiredToolCapabilities",
    ):
        role_properties[field] = deepcopy(concept_list)
    for field, values in finite_lists.items():
        role_properties[field] = {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "enum": values},
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "taskBrief": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64000,
                "description": "Public-safe redacted task brief; never include local paths, secrets, account identifiers, or raw memory.",
            },
            "roles": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": role_properties,
                    "required": ["title", "task"],
                },
            },
            "edges": {
                "type": "array",
                "maxItems": 128,
                "description": "Use 1-based role ordinals. Core creates and binds exact slot/artifact IDs.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "fromRole": {"type": "integer", "minimum": 1, "maximum": 32},
                        "toRole": {"type": "integer", "minimum": 1, "maximum": 32},
                        "relation": {
                            "type": "string",
                            "enum": ["reportsTo", "handsOffTo", "reviews", "coordinatesWith"],
                            "default": "handsOffTo",
                        },
                        "artifactKinds": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string", "enum": catalog["artifactIds"]},
                            "default": ["artifact:worker-result"],
                        },
                    },
                    "required": ["fromRole", "toRole"],
                },
            },
            "forbiddenCommunities": deepcopy(concept_list),
            "selectionPolicy": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "minimumCandidatesPerSlot": {"type": "integer", "minimum": 2, "maximum": 30, "default": 2},
                    "maximumCandidatesPerSlot": {"type": "integer", "minimum": 2, "maximum": 100, "default": 30},
                },
            },
        },
        "required": ["taskBrief", "roles"],
    }


_MENU_AUDIT_FIELDS = ("qualificationEvidence", "packageHash", "contentDigest")

# The summary menu keeps artifact counts; matching uses the original data
# retained in the Core session store, and expansion returns full artifacts.
_MENU_SNAPSHOT_HEAVY_FIELDS = ("produces", "consumes")

# fit:text:term:<단어> 노이즈 컷용 영어 불용어 — bio-research 전수(2026-08-19)에서
# 실제로 관측된 것들 + 같은 급의 최소 확장. 도메인어(binding, molecular …)는 남긴다.
_FIT_TERM_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "between", "by", "can", "each",
    "for", "from", "in", "into", "is", "it", "its", "of", "on", "one", "or",
    "that", "the", "then", "this", "to", "with",
})


def _shortlist_projection(result: dict[str, Any]) -> dict[str, Any]:
    """menu.v3 — 훑기용 요약 카드. 결정은 여전히 풀카드로 내린다.

    세션 저장소는 원본을 보존한다. 호스트는 후보를 좁힌 뒤
    `workforce.expand_candidates`로 풀카드를 받아 최종 판단한다.

    무엇을 남기는가는 "이 후보를 더 볼지 말지"를 가르는 최소 재료로 정했다:
    서수(참조), 이름, 종류, 소속, 소개 1벌, 지금 부를 수 있는지, 결격.
    """

    projected = dict(result)
    candidate_set = projected.get("candidateSet")
    if not isinstance(candidate_set, dict):
        return projected
    candidate_set = dict(candidate_set)
    slots = []
    for slot in candidate_set.get("slots", []):
        slot = dict(slot)
        cards = []
        for ordinal, candidate in enumerate(slot.get("candidates", []), start=1):
            snapshot = candidate.get("semanticSnapshot")
            snapshot = snapshot if isinstance(snapshot, Mapping) else {}
            summaries = snapshot.get("summaries")
            operational = candidate.get("operational")
            operational = operational if isinstance(operational, Mapping) else {}
            card = {
                "candidateOrdinal": candidate.get("candidateOrdinal") or ordinal,
                "name": candidate.get("name") or (snapshot.get("names") or [None])[0],
                "entityKind": candidate.get("entityKind"),
                "communities": candidate.get("communities"),
                "summary": summaries[0] if isinstance(summaries, list) and summaries else None,
                "callable": operational.get("callable"),
            }
            missing = candidate.get("missingMandatory")
            if missing:
                card["missingMandatory"] = missing
            # 발행자 문장으로 구조석에 앉은 후보는 요약에서도 그 사실이 보여야 한다.
            if "fit:publisher-trigger" in (candidate.get("fitEvidence") or []):
                card["publisherTriggerMatch"] = True
            cards.append(card)
        slot["candidates"] = cards
        slots.append(slot)
    candidate_set["slots"] = slots
    candidate_set["projection"] = "menu.v3-shortlist"
    projected["candidateSet"] = candidate_set
    projected["expand"] = (
        "These are summary cards. Narrow to the candidates worth a closer look, then call "
        "workforce.expand_candidates with the selectionSessionId and their slotId/candidateOrdinal "
        "pairs to read the full cards before deciding. Nothing is lost: the session store holds "
        "the complete menu."
    )
    return projected


def _expand_candidates(
    result: Mapping[str, Any],
    requested: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the full (menu.v2) cards for the shortlisted ordinals only."""

    candidate_set = result.get("candidateSet")
    if not isinstance(candidate_set, Mapping):
        return {"status": "rejected", "error": "federation_candidate_set_unavailable"}
    wanted: dict[str, set[int]] = {}
    for item in requested:
        if not isinstance(item, Mapping):
            continue
        slot_id = str(item.get("slotId") or "")
        ordinal = item.get("candidateOrdinal")
        if not slot_id or not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
            continue
        wanted.setdefault(slot_id, set()).add(ordinal)
    if not wanted:
        return {
            "status": "rejected",
            "error": "workforce_expand_selection_invalid",
            "hint": "Send candidates as [{slotId, candidateOrdinal}] — ordinals restart at 1 within each slot.",
        }
    # ★expand 는 "좁힌 뒤 정확히 보는" 단계다 — 여기서까지 produces/consumes 를
    # 카운트로 치환하면 호스트는 어떤 표면에서도 엣지 호환을 판단할 재료가 없다.

    projected = _menu_projection({"candidateSet": dict(candidate_set)}, keep_artifacts=True)
    expanded_slots = []
    missing: list[str] = []
    for slot in (projected.get("candidateSet") or {}).get("slots", []):
        slot_id = str(slot.get("slotId") or "")
        ordinals = wanted.get(slot_id)
        if not ordinals:
            continue
        cards = slot.get("candidates") or []
        by_ordinal = {int(card.get("candidateOrdinal") or 0): card for card in cards}
        picked = []
        for ordinal in sorted(ordinals):
            card = by_ordinal.get(ordinal)
            if card is None:
                missing.append(f"{slot_id}:{ordinal}")
                continue
            picked.append(card)
        expanded_slots.append({"slotId": slot_id, "candidates": picked})
    unknown_slots = sorted(set(wanted) - {str(s.get("slotId")) for s in expanded_slots})
    return {
        "status": "expanded",
        "selectionSessionId": candidate_set.get("selectionSessionId"),
        "candidateSetDigest": candidate_set.get("candidateSetDigest"),
        "slots": expanded_slots,
        **({"unresolvedOrdinals": missing} if missing else {}),
        **({"unknownSlots": unknown_slots} if unknown_slots else {}),
    }


# Fields a per-turn continuity read does not need. The host decides
# reuse/recruit from labels, slots, sources and state; the exact release
# identity is resolved by Core from its own store at preparation time and is
# never retyped by the model.
_GOAL_ROSTER_AUDIT_FIELDS = (
    "agentDefinitionId",
    "agentReleaseId",
    "releaseVersion",
    "addedAt",
    "addedRevision",
)


def _selection_decision_schema() -> dict[str, Any]:
    """The three things a staffing decision actually contains.

    Which post, which candidate ordinal from the pinned menu, and why. Core
    fills schemaVersion, the candidate-set digest it already pinned, and the
    arrays that are empty in almost every real decision.
    """

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["selectionSessionId", "decisionAuthor", "assignments"],
        "properties": {
            "selectionSessionId": {"type": "string", "minLength": 1, "maxLength": 256},
            "decisionAuthor": {
                "type": "object",
                "additionalProperties": False,
                "required": ["modelId"],
                "properties": {
                    "modelId": {"type": "string", "minLength": 1, "maxLength": 255},
                    "runtimeId": {"type": "string", "maxLength": 255},
                },
            },
            "assignments": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["slotId"],
                    "properties": {
                        "slotId": {"type": "string", "minLength": 1, "maxLength": 256},
                        "candidateOrdinal": {"type": "integer", "minimum": 1, "maximum": 100},
                        "agentReleaseId": {"type": "string", "maxLength": 255},
                        "reasonCodes": {
                            "type": "array",
                            "maxItems": 16,
                            "items": {"type": "string", "minLength": 2, "maxLength": 255},
                            "description": (
                                "Use public codes: " + ", ".join(sorted(WORKFORCE_SELECTION_REASON_CODES))
                                + "; or exact reason codes in the selected candidate's pinned evidence. "
                                "Omission uses reason:host-semantic-judgment."
                            ),
                        },
                    },
                },
            },
            "edges": {
                "type": "array",
                "maxItems": 128,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["fromSlot", "toSlot"],
                    "properties": {
                        "fromSlot": {"type": "string", "maxLength": 256},
                        "toSlot": {"type": "string", "maxLength": 256},
                        "relation": {
                            "type": "string",
                            "enum": ["reportsTo", "handsOffTo", "reviews", "coordinatesWith"],
                        },
                        "artifactKinds": {"type": "array", "items": {"type": "string", "maxLength": 255}},
                    },
                },
            },
            "alternativesConsidered": {"type": "array", "items": {"type": "string", "maxLength": 255}},
            "requestExpansionForSlots": {"type": "array", "items": {"type": "string", "maxLength": 255}},
        },
    }


def _roster_labels_from_session(selection: Any) -> dict[str, str]:
    """Map agentReleaseId -> the candidate's human name for the bound roster.

    Automatic binding never passed labels, so `display_label` fell back to the
    release id and every continuity read (and every user-facing roster line)
    showed a hash where a name belongs. The names are already pinned in the
    session store, so no new input is needed from the host.
    """

    from .workforce.federation_store import FederationSessionError, FederationSessionStore

    session_id = ""
    if isinstance(selection, Mapping):
        session_id = str(selection.get("selectionSessionId") or "").strip()
    if not session_id:
        return {}
    try:
        stored = FederationSessionStore().get(session_id)
    except (FederationSessionError, OSError, sqlite3.Error, ValueError):
        return {}
    candidate_set = stored.get("candidateSet") if isinstance(stored, Mapping) else None
    if not isinstance(candidate_set, Mapping):
        return {}
    labels: dict[str, str] = {}
    for slot in candidate_set.get("slots") or []:
        if not isinstance(slot, Mapping):
            continue
        for candidate in slot.get("candidates") or []:
            if not isinstance(candidate, Mapping):
                continue
            release_id = str(candidate.get("agentReleaseId") or "")
            name = str(candidate.get("name") or "").strip()
            if release_id and name:
                labels.setdefault(release_id, name[:160])
    return labels


def _goal_context_projection(
    context: Mapping[str, Any],
    *,
    known_revisions: Any = None,
) -> dict[str, Any]:
    """Project a goal context into the bounded per-turn continuity view.

    Also answers the question the old shape could not: which bound releases
    were prepared and never actually run. A roster row whose `lastUsedAt` is
    null has no execution claim at all, so "prepared, not executed" is a fact
    here rather than something the model has to confess.
    """

    known: dict[str, int] = {}
    if isinstance(known_revisions, Mapping):
        for key, value in known_revisions.items():
            if isinstance(value, int) and not isinstance(value, bool):
                known[str(key)] = value
    goals: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    unchanged = 0
    for goal in context.get("goals") or []:
        if not isinstance(goal, Mapping):
            continue
        goal_id = str(goal.get("goalId") or "")
        revision = goal.get("rosterRevision")
        roster = [row for row in goal.get("roster") or [] if isinstance(row, Mapping)]
        never_used = [row for row in roster if not row.get("lastUsedAt")]
        if never_used:
            pending.append(
                {
                    "goalId": goal_id,
                    "preparedNotExecuted": len(never_used),
                    "rosterSize": len(roster),
                    "agents": [str(row.get("label") or "") for row in never_used][:16],
                }
            )
        if known.get(goal_id) == revision and isinstance(revision, int):
            unchanged += 1
            goals.append({"goalId": goal_id, "rosterRevision": revision, "state": "unchanged"})
            continue
        goals.append(
            {
                **{
                    key: value
                    for key, value in goal.items()
                    if key not in {"roster", "bindingId"}
                },
                "roster": [
                    {
                        key: value
                        for key, value in row.items()
                        if key not in _GOAL_ROSTER_AUDIT_FIELDS
                    }
                    for row in roster
                ],
            }
        )
    projected = {
        **{key: value for key, value in context.items() if key != "goals"},
        "projection": "goal-context.v2",
        "goals": goals,
    }
    if unchanged:
        projected["unchangedGoals"] = unchanged
    if pending:
        projected["pendingExecution"] = pending
        projected["pendingExecutionNotice"] = (
            "These bound releases were prepared and never recorded as executed. "
            "Preparation is not delivery: either run them for this turn's work and record it with "
            "workforce.record_goal_turn, or tell the user plainly that the roster is prepared but not executed."
        )
    return projected


def _with_unmet_requirement_notice(wrapper: Any) -> Any:
    """Lift an accepted receipt's unmet-requirement count to the MCP surface.

    The federated wrapper has an exact key set that other products assert, so
    the count stays inside `selectionValidation` there. What must not happen is
    an `accepted` that reads as "everything checks out" while the receipt says
    a chosen release does not meet a requirement the author actually wrote.
    """

    if not isinstance(wrapper, dict):
        return wrapper
    validation = wrapper.get("selectionValidation")
    if not isinstance(validation, Mapping):
        return wrapper
    count = validation.get("unmetRequirementCount")
    if not isinstance(count, int) or count <= 0:
        return wrapper
    return {
        **wrapper,
        "unmetRequirementCount": count,
        "notice": (
            f"{count} assigned release(s) do not meet a requirement this WorkOrder asked for. "
            "The selection is valid and Core does not choose for you — read "
            "selectionValidation.unmetRequirements and either accept the gap deliberately or reselect."
        ),
    }


# Context and preparation responses share one compactor at the output boundary.
def compact_context_result(tool_name: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Bound relationship receipts at the host-visible MCP boundary.

    Core keeps the complete graph for deterministic verification. Codex and
    other chat hosts need a readable working set plus explicit omission
    counts, not tens of kilobytes of duplicated graph internals.
    """

    payload = dict(result)
    omissions: dict[str, int] = {}

    def trim_list(
        container: dict[str, Any],
        field: str,
        limit: int,
        *,
        label: str | None = None,
        transform=None,
    ) -> None:
        value = container.get(field)
        if not isinstance(value, list):
            return
        items = value[:limit]
        if transform is not None:
            items = [transform(item) for item in items]
        container[field] = items
        omitted = max(0, len(value) - limit)
        if omitted:
            omissions[label or field] = omitted

    def compact_path(item: Any) -> Any:
        if not isinstance(item, Mapping):
            return item
        affected = item.get("affectedFiles")
        affected_files = affected[:8] if isinstance(affected, list) else []
        compact = {
            "changedSymbol": item.get("changedSymbol"),
            "definitions": (item.get("definitions") or [])[:3],
            "affectedFiles": affected_files,
        }
        if isinstance(affected, list) and len(affected) > len(affected_files):
            compact["affectedFilesOmitted"] = len(affected) - len(affected_files)
        return compact

    def compact_symbol(item: Any) -> Any:
        if not isinstance(item, Mapping):
            return item
        referenced = item.get("referencedBy")
        referenced_by = referenced[:4] if isinstance(referenced, list) else []
        compact = {
            "symbol": item.get("symbol"),
            "definitions": (item.get("definitions") or [])[:3],
            "referenceCount": item.get("referenceCount"),
            "referencedBy": referenced_by,
        }
        if isinstance(referenced, list) and len(referenced) > len(referenced_by):
            compact["referencedByOmitted"] = len(referenced) - len(referenced_by)
        return compact

    def compact_context_node(item: Any) -> Any:
        if not isinstance(item, Mapping):
            return item
        compact: dict[str, Any] = {}
        for key in ("id", "nodeId", "type", "kind", "status", "title", "name", "path"):
            value = item.get(key)
            if isinstance(value, str) and value:
                compact[key] = value[:512]
        return compact

    if tool_name == "context.impact":
        trim_list(payload, "impactedFiles", 16)
        trim_list(payload, "paths", 6, transform=compact_path)
        trim_list(payload, "verificationTargets", 12)
        receipt = dict(payload.get("receipt") or {})
        full_receipt_digest = receipt.pop("receiptDigest", None)
        trim_list(receipt, "changedSymbols", 16, label="receipt.changedSymbols")
        trim_list(receipt, "impactedFiles", 16, label="receipt.impactedFiles")
        trim_list(receipt, "verificationTargets", 8, label="receipt.verificationTargets")
        if full_receipt_digest:
            receipt["fullReceiptDigest"] = full_receipt_digest
        receipt["projectionDigest"] = canonical_digest(receipt)
        payload["receipt"] = receipt
    elif tool_name == "context.slice":
        payload.setdefault("action", tool_name)
        payload.setdefault("status", "ok")
        trim_list(payload, "contextEdges", 10)
        trim_list(payload, "files", 16)
        trim_list(payload, "moduleEdges", 10)
        trim_list(payload, "goalsAndConstraints", 6, transform=compact_context_node)
        trim_list(payload, "relatedContextNodes", 6, transform=compact_context_node)
        trim_list(payload, "symbols", 5, transform=compact_symbol)
        receipt = dict(payload.get("receipt") or {})
        trim_list(receipt, "selectedContextNodeIds", 12, label="receipt.selectedContextNodeIds")
        trim_list(receipt, "selectedFiles", 16, label="receipt.selectedFiles")
        trim_list(receipt, "selectedSymbols", 12, label="receipt.selectedSymbols")
        full_receipt_digest = receipt.pop("receiptDigest", None)
        if full_receipt_digest:
            receipt["fullReceiptDigest"] = full_receipt_digest
        receipt["projectionDigest"] = canonical_digest(receipt)
        payload["receipt"] = receipt
        verification = dict(payload.get("verification") or {})
        trim_list(verification, "edges", 6, label="verification.edges")
        trim_list(verification, "nodes", 5, label="verification.nodes")
        trim_list(verification, "issues", 16, label="verification.issues")
        payload["verification"] = verification
    elif tool_name == "context.verify":
        receipt = dict(payload.get("receipt") or {})
        full_receipt_digest = receipt.pop("receiptDigest", None)
        trim_list(receipt, "unresolvedFiles", 20, label="receipt.unresolvedFiles")
        trim_list(receipt, "verificationTargets", 16, label="receipt.verificationTargets")
        trim_list(receipt, "verificationIssues", 20, label="receipt.verificationIssues")
        if full_receipt_digest:
            receipt["fullReceiptDigest"] = full_receipt_digest
        receipt["projectionDigest"] = canonical_digest(receipt)
        payload["receipt"] = receipt

    if omissions:
        payload["omissions"] = omissions

    if tool_name == "context.slice":
        # The host-visible result has a hard 16 KiB budget, including the
        # goals list that duplicates selected context nodes. Trim optional
        # relationship rows deterministically until the complete JSON
        # projection fits; every removed row remains accounted for.
        byte_limit = 16 * 1024
        shrinkable = [
            (payload, "goalsAndConstraints", "goalsAndConstraints"),
            (payload, "relatedContextNodes", "relatedContextNodes"),
            (payload, "contextEdges", "contextEdges"),
            (payload, "moduleEdges", "moduleEdges"),
            (payload, "modules", "modules"),
            (payload, "symbols", "symbols"),
            (payload, "files", "files"),
            (verification, "issues", "verification.issues"),
            (verification, "edges", "verification.edges"),
            (verification, "nodes", "verification.nodes"),
            (receipt, "selectedContextNodeIds", "receipt.selectedContextNodeIds"),
            (receipt, "selectedFiles", "receipt.selectedFiles"),
            (receipt, "selectedSymbols", "receipt.selectedSymbols"),
        ]

        def projected_size() -> int:
            return len(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )

        while projected_size() > byte_limit:
            candidate = max(
                (
                    (len(value), container, field, label)
                    for container, field, label in shrinkable
                    if isinstance((value := container.get(field)), list) and value
                ),
                default=None,
                key=lambda row: row[0],
            )
            if candidate is None:
                rendered = payload.get("rendered")
                if isinstance(rendered, str) and rendered:
                    removed = min(1024, len(rendered))
                    payload["rendered"] = rendered[:-removed]
                    omissions["renderedChars"] = omissions.get("renderedChars", 0) + removed
                    payload["omissions"] = omissions
                    continue
                break
            _length, container, field, label = candidate
            container[field].pop()
            omissions[label] = omissions.get(label, 0) + 1
            payload["omissions"] = omissions
            receipt.pop("projectionDigest", None)
            receipt["projectionDigest"] = canonical_digest(receipt)
    return payload



def _compact_boundary(boundary: Mapping[str, Any]) -> dict[str, Any]:
    """Strip the already-declared contract catalog from a boundary refusal.

    Selection and WorkOrder refusals preserve repair details without repeating
    the contract catalog already exposed by the tool schema.
    """

    compact = {
        key: boundary.get(key)
        for key in (
            "schemaVersion",
            "status",
            "repairable",
            "mutation",
            "workOrderDigest",
            "selectionDigest",
            "issues",
        )
        if key in boundary
    }
    compact["issueCount"] = len(boundary.get("issues") or [])
    return compact


def _menu_projection(result: dict[str, Any], *, keep_artifacts: bool = False) -> dict[str, Any]:
    """Projects a search response into a decision-ready summary menu — a
    drop-list approach.

    Instead of enumerating what to keep, it drops only the audit-weight
    fields: if an agent attribute (card schema) is added or renamed, the new
    field passes through automatically. Core's session store holds the full
    original text, and validation/preparation pin-matching is performed
    against that original data, so no control is lost.


    This projection is MCP-surface only. The Terminal runner asserts the
    semanticSnapshot key set at exactly 9 keys
    (agentlas-workforce.cjs assertExactKeys), so applying the same folding on
    Core's shared path would make that side die with candidate_set_invalid.
    """
    projected = {key: value for key, value in result.items() if key != "candidateProvenance"}
    # A failed source receipt is digest-sealed to an exact key set, so the way
    # out cannot ride inside it — and until now it rode nowhere: the menu said
    # `cloud: failed source_unauthorized` and left the host to guess the move
    # (audit round 7, common rule 3). Decorate the projection instead: hints
    # live beside the receipts, not in them, so seals and consumers are
    # untouched.
    receipt_rows = projected.get("sourceReceipts")
    if isinstance(receipt_rows, list):
        failure_hints = {
            "source_unauthorized": "sign in with `hephaestus auth login`, then retry",
            "source_timeout": "the source did not answer in time — retry shortly",
            "source_circuit_open": "recent failures paused this source — retry after a short wait",
            "source_rate_limited": "rate limited — retry after a short wait",
            "source_not_configured": "this source is not configured on this machine",
            "source_unavailable": "the source could not be reached — check the network, then retry",
        }
        hints = {
            str(row.get("source")): failure_hints[str(row.get("failureCode"))]
            for row in receipt_rows
            if isinstance(row, dict)
            and row.get("status") == "failed"
            and str(row.get("failureCode")) in failure_hints
        }
        if hints:
            projected["sourceFailureHints"] = hints
    candidate_set = projected.get("candidateSet")
    if isinstance(candidate_set, dict):
        candidate_set = dict(candidate_set)
        slots = []
        for slot in candidate_set.get("slots", []):
            slot = dict(slot)
            candidates = []
            for ordinal, candidate in enumerate(slot.get("candidates", []), start=1):
                candidate = {
                    key: value
                    for key, value in candidate.items()
                    if key not in _MENU_AUDIT_FIELDS
                }
                candidate["candidateOrdinal"] = ordinal
                evidence = (slot.get("candidates", [])[ordinal - 1] or {}).get("qualificationEvidence")
                if isinstance(evidence, list):
                    candidate["qualificationEvidenceCount"] = len(evidence)
                snapshot = candidate.get("semanticSnapshot")
                if isinstance(snapshot, dict):
                    snapshot = dict(snapshot)
                    for field in _MENU_SNAPSHOT_HEAVY_FIELDS:
                        value = snapshot.get(field)
                        if isinstance(value, list) and not keep_artifacts:
                            snapshot.pop(field)
                            snapshot[f"{field}Count"] = len(value)
                    # Declared skills carry their concept strings. Elevated levels
                    # travel separately; matching uses the complete stored profile.
                    skills = snapshot.get("skills")
                    if isinstance(skills, list):
                        concepts: list[str] = []
                        elevated: dict[str, str] = {}
                        for item in skills:
                            if isinstance(item, Mapping) and isinstance(item.get("concept"), str):
                                concepts.append(item["concept"])
                                level = item.get("level")
                                if isinstance(level, str) and level != "declared":
                                    elevated[item["concept"]] = level
                            elif isinstance(item, str):
                                concepts.append(item)
                        snapshot["skills"] = concepts
                        if elevated:
                            snapshot["skillLevels"] = elevated
                    # Keep the first summary and one in another language when
                    # available; report the total and retain originals in the store.
                    summaries = snapshot.get("summaries")
                    if isinstance(summaries, list) and len(summaries) > 2:
                        def _is_hangul(text: Any) -> bool:
                            return isinstance(text, str) and any("가" <= ch <= "힣" for ch in text)
                        first = summaries[0]
                        other = next(
                            (item for item in summaries[1:] if _is_hangul(item) != _is_hangul(first)),
                            summaries[1],
                        )
                        snapshot["summaries"] = [first, other]
                        snapshot["summariesCount"] = len(summaries)
                    candidate["semanticSnapshot"] = snapshot
                # ★fitEvidence 노이즈 컷. 두 종류를 걷는다(허용 이유코드 집합은 저장
                # 원본에서 계산되므로 메뉴에서 걷어도 reasonCodes 검증은 불변):
                #  · fit-retrieval:* — "Core 가 어떤 검색기로 찾았나"이지 "왜 맞나"가
                #    아니다. 전 후보 동일 부착 = 정보 0.
                #  · fit:text:term:<불용어> — 일반 불용어를 제거하고 도메인어를 남긴다.
                fit = candidate.get("fitEvidence")
                if isinstance(fit, list):
                    kept = []
                    for item in fit:
                        if not isinstance(item, str):
                            kept.append(item)
                            continue
                        if item.startswith("fit-retrieval:"):
                            continue
                        if item.startswith("fit:text:term:") and item.rsplit(":", 1)[-1].lower() in _FIT_TERM_STOPWORDS:
                            continue
                        kept.append(item)
                    if len(kept) != len(fit):
                        candidate["fitEvidence"] = kept
                candidates.append(candidate)
            slot["candidates"] = candidates
            slots.append(slot)
        candidate_set["slots"] = slots
        candidate_set["projection"] = "menu.v2"
        projected["candidateSet"] = candidate_set
    return projected


def _preparation_projection(result: dict[str, Any]) -> dict[str, Any]:
    """Projects a prepared execution response for the MCP surface.

    Shared directive bundles and execution graphs are emitted once per
    contentDigest in bundleContents; roster rows carry identifiers and digests.

    menu.v2 와 같은 규율이다: 이 투영은 MCP 표면 전용이고, goal binding 은
    투영 **이전의** 원본을 저장하며, bundleDigest 는 저장 원본에 대해 계산된
    값이라 여기서 행을 줄여도 권위는 불변이다. search 와 달리 기본값은
    원형이고 투영은 ``fullDossier=false`` 명시 옵트인이다 — 행 전체로
    bundleDigest 를 재계산하는 데스크탑 검증자가 이 런타임과 **독립적으로**
    업데이트되므로(런타임 홈은 설치기·업데이터 소유), 기본값을 바꾸면
    신 런타임 + 구 데스크탑 스큐에서 편성이 죽는다. 터미널은 cloud HTTP
    MCP 를 쓰므로 이 경로를 지나지 않는다.
    """
    plan = result.get("executionPlan")
    if not isinstance(plan, dict):
        return result
    roster = plan.get("executionRoster")
    if not isinstance(roster, list) or not roster:
        return result
    bundle_contents: dict[str, dict[str, Any]] = {}
    projected_rows: list[dict[str, Any]] = []
    for row in roster:
        if not isinstance(row, Mapping):
            projected_rows.append(row)
            continue
        digest = str(row.get("contentDigest") or "")
        heavy = {
            key: row[key]
            for key in ("directiveBundle", "executionGraph")
            if key in row and row[key] is not None
        }
        if not digest or not heavy:
            projected_rows.append(dict(row))
            continue
        bundle_contents.setdefault(digest, heavy)
        projected_rows.append(
            {key: value for key, value in row.items() if key not in heavy}
        )
    projected_plan = dict(plan, executionRoster=projected_rows)
    return {
        **result,
        "executionPlan": projected_plan,
        "bundleContents": bundle_contents,
        "projection": "prepare.v2",
        "hostExecutionContract": host_execution_contract(plan, projected=True),
        "projectionNote": (
            "executionRoster rows reference their directiveBundle/executionGraph "
            "by contentDigest in bundleContents (one copy per digest). The bound "
            "preparation stores the unprojected original; pass fullDossier=true "
            "for the legacy self-contained rows."
        ),
    }


def _resolve_ordinal_assignments(
    selection: Mapping[str, Any],
    candidate_set: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    """Resolves each assignment's candidateOrdinal against the stored menu into an exact release ID.

    Returns: (selection normalized to canonical shape, None, None) or
    (None, a refusal code, a detail object naming what was wrong). If both an
    ordinal and a release ID were given and they disagree, this refuses rather
    than silently picking one.

    Ordinals restart at 1 inside each slot. Boundary details identify the
    invalid selection and valid bounds so callers can repair it.
    """
    slots_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for slot in candidate_set.get("slots", []) or []:
        if isinstance(slot, Mapping):
            slots_by_id[str(slot.get("slotId"))] = list(slot.get("candidates", []) or [])
    resolved = dict(selection)
    assignments = []
    for index, assignment in enumerate(selection.get("assignments", []) or []):
        if not isinstance(assignment, Mapping):
            return None, "selection_assignment_invalid", {"path": f"assignments[{index}]"}
        assignment = dict(assignment)
        ordinal = assignment.pop("candidateOrdinal", None)
        if ordinal is not None:
            slot_id = str(assignment.get("slotId"))
            candidates = slots_by_id.get(slot_id)
            if candidates is None:
                return None, "ordinal_slot_not_in_menu", {
                    "path": f"assignments[{index}].slotId",
                    "slotId": slot_id,
                    "slotsInMenu": sorted(slots_by_id),
                }
            if not isinstance(ordinal, int) or not 1 <= ordinal <= len(candidates):
                return None, "ordinal_out_of_range", {
                    "path": f"assignments[{index}].candidateOrdinal",
                    "slotId": slot_id,
                    "given": ordinal,
                    "validRange": [1, len(candidates)] if candidates else [],
                    "candidatesInSlot": len(candidates),
                    "hint": (
                        "candidateOrdinal restarts at 1 within each slot — it is not a running "
                        "number across the whole menu. Count this candidate's position inside "
                        f"candidateSet.slots[slotId={slot_id}].candidates, or send its "
                        "agentReleaseId instead."
                    ),
                }
            release_id = (candidates[ordinal - 1] or {}).get("agentReleaseId")
            if not isinstance(release_id, str) or not release_id:
                return None, "ordinal_candidate_unresolvable", {
                    "path": f"assignments[{index}].candidateOrdinal",
                    "slotId": slot_id,
                    "given": ordinal,
                }
            existing = assignment.get("agentReleaseId")
            if isinstance(existing, str) and existing and existing != release_id:
                return None, "ordinal_release_conflict", {
                    "path": f"assignments[{index}]",
                    "slotId": slot_id,
                    "ordinalResolvesTo": release_id,
                    "agentReleaseIdGiven": existing,
                }
            assignment["agentReleaseId"] = release_id
        assignments.append(assignment)
    resolved["assignments"] = assignments
    return resolved, None, None



def _goal_context_model_policy(context: dict[str, Any]) -> dict[str, Any]:
    """Expose this server's effective policy posture without policy values."""
    try:
        policy = _host_model_allocation_policy()
    except ValueError:
        posture = {"status": "invalid", "roles": {}}
    else:
        roles = {}
        for role in ("orchestrator", "worker"):
            effective, _ = _policy_for_role(policy, role)
            constrained = any(
                effective.get(key) not in (None, "", [])
                for key in ("pinnedModelId", "pinnedProvider", "maxTier", "maxEffort", "requiredCapabilities")
            )
            roles[role] = "allocation_required" if constrained else "inherit_host"
        posture = {"status": "ok", "roles": roles}
    return {**context, "hostModelPolicy": posture}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "agentlas.read_agent_file",
        "description": "Read an original UTF-8 file below a local agent package using its existing agentlas.json allowRead/denyRead policy. Rejects traversal and links; optional source metadata never grants authority or calls a model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "minLength": 1, "description": "Local package root containing agentlas.json."},
                "path": {"type": "string", "minLength": 1, "description": "Portable package-relative path declared in allowRead."},
            },
            "required": ["root", "path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "agentlas_resolve_plugins",
        "description": (
            "Resolve a short, redacted missing capability against installed Agentlas plugins and the "
            "Agentlas Hub catalog before claiming that no suitable integration exists. Returns exact "
            "local matches, installable Hub entries, or unresolved=true. This tool never installs or "
            "enables a plugin; the user must decide after reviewing permissions and credential requirements."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["need"],
            "properties": {
                "need": {
                    "type": "string",
                    "description": "A short, redacted description of the missing capability; do not include private text.",
                },
                "project_dir": {"type": "string", "description": "Project directory to scan (default: cwd)."},
                "use_hub": {"type": "boolean", "description": "Search Agentlas Hub as well as installed plugins (default: true)."},
            },
        },
    },
    {
        "name": "agentlas_tool_search",
        "description": (
            "Find the TOOL for a concrete action, not the plugin for a topic. Pass `need` as one "
            "plain sentence describing the action ('show what changed in the repository since the "
            "last commit'). Searches servers first, then only the winners' tools, and answers with a "
            "short list: server, tool, one line, and effect hints (readOnly/destructive). Input "
            "schemas are NOT returned — load the chosen tool's schema from its server at call time. "
            "Use forbid_destructive when the task must not delete or overwrite anything."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["need"],
            "properties": {
                "need": {"type": "string", "description": "One sentence describing the action to perform."},
                "project_dir": {"type": "string", "description": "Project directory to scan (default: cwd)."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 8, "description": "Candidates to return (default 4)."},
                "forbid_destructive": {"type": "boolean", "description": "Exclude tools that delete or overwrite."},
            },
        },
    },
    {
        "name": "hephaestus_route",
        "description": (
            "Legacy compatibility/debug card router. Disabled unless the operator "
            "sets HEPHAESTUS_LEGACY_ROUTER=1; it is not the typed Local+Cloud+Hub "
            "Workforce staffing surface and must not be reported as hep-network."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "The natural-language request to route."},
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
                "approve_hub": {
                    "type": "boolean",
                    "description": "Backward-compatible no-op; Hub lookup already sends redacted keywords only.",
                },
                "hub_only": {
                    "type": "boolean",
                    "description": "Skip local routing cards and search Agentlas Hub only. This is the default unless allow_local_routing is true.",
                },
                "allow_local_routing": {
                    "type": "boolean",
                    "description": "Operator/debug escape hatch. When false or omitted, local private/plugin cards are ignored.",
                },
                "caller_id": {
                    "type": "string",
                    "description": "Optional caller agent id for Agent Ontology deny/require gating.",
                },
                "caller": {
                    "type": "string",
                    "description": "Alias for caller_id, matching the CLI --caller option.",
                },
                "session_inventory": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "session_id": {"type": "string"},
                                    "provider": {"type": "string"},
                                    "model": {"type": "string"},
                                    "trust": {"type": "string"},
                                    "capabilities": {"type": "array", "items": {"type": "string"}},
                                    "max_parallel": {"type": "integer"},
                                    "tier": {"type": "string"},
                                    "supported_efforts": {"type": "array", "items": {"type": "string"}},
                                    "context_window": {"type": "integer"},
                                    "supports_tools": {"type": "boolean"},
                                    "supports_multimodal": {"type": "boolean"},
                                    "capability_descriptor": {
                                        "type": "object",
                                        "description": (
                                            "Optional strict agentlas.runtime-fabric-capability-descriptor.v1; "
                                            "unknown or invalid declarations never block native execution."
                                        ),
                                    },
                                },
                                "additionalProperties": True,
                            },
                        ]
                    },
                    "description": "Optional host-advertised active sessions (Codex, Claude, GLM, DeepSeek, local models) for Stormbreaker pipeline scheduling.",
                },
                "model_allocation_decisions": {
                    "type": "object",
                    "additionalProperties": {"type": "object"},
                    "description": "Parent/leader AI decisions keyed by packet id, phase, or stage order. Raw task text must not be included.",
                },
            },
            "required": ["request"],
        },
    },
    {
        "name": "model.resolve_allocation",
        "description": (
            "Resolve one host-owned invocation stage to an orchestrator or worker "
            "model using the operator's provider-neutral role policy. This tool "
            "does not call a model and never accepts pins or cost ceilings from "
            "tool arguments."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": sorted(INVOCATION_STAGE_PHASES),
                    "description": (
                        "Host-owned execution stage. Planning, synthesis, routing, "
                        "clarification, and verification resolve to orchestrator; "
                        "build/execute/worker/delegate/task resolve to worker."
                    ),
                },
                "session_inventory": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "session_id": {"type": "string"},
                            "provider": {"type": "string"},
                            "model": {"type": "string"},
                            "active": {"type": "boolean"},
                            "available": {"type": "boolean"},
                            "tier": {"enum": ["economy", "balanced", "frontier"]},
                            "supported_efforts": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "pattern": "^[A-Za-z][A-Za-z0-9-]{0,23}$",
                                },
                            },
                            "context_window": {"type": "integer", "minimum": 0},
                            "supports_tools": {"type": "boolean"},
                            "supports_multimodal": {"type": "boolean"},
                            "capability_descriptor": {
                                "type": "object",
                                "description": (
                                    "Optional strict agentlas.runtime-fabric-capability-descriptor.v1; "
                                    "unknown or invalid declarations never block native execution."
                                ),
                            },
                            "capabilities": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                    "description": (
                        "Live host sessions. Model identifiers are opaque inventory "
                        "values; Core has no vendor model-name table."
                    ),
                },
                "decision": {
                    "type": "object",
                    "description": (
                        "Optional parent/leader agentlas.model-allocation-decision.v1. "
                        "Its phase must match the canonical phase for stage."
                    ),
                },
                "escalation": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["fromRole", "failureCount", "attempt"],
                    "properties": {
                        "fromRole": {"const": "worker"},
                        "failureCount": {"const": 2},
                        "attempt": {"const": 1},
                    },
                    "description": (
                        "Host-owned bounded escalation: the worker role failed the "
                        "same task exactly twice and this is the single allowed "
                        "orchestrator retry. Any other shape is recorded and ignored."
                    ),
                },
            },
            "required": ["stage", "session_inventory"],
        },
    },
    {
        "name": "hephaestus_cloud_search",
        "description": (
            "Legacy compatibility/debug owner-cargo router. Disabled unless the "
            "operator sets HEPHAESTUS_LEGACY_ROUTER=1. Use typed Workforce scope "
            "cloud for exact receipts, refusals, validation, and preparation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "The natural-language request to match against the owner's own cloud packages."},
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
            },
            "required": ["request"],
        },
    },
    {
        "name": "hephaestus_search",
        "description": (
            "Power-user search: return top Agentlas Cloud (owner packages) and "
            "public Hub candidates side by side without invoking any agent. Use "
            "when the user asks to find agents and compare choices."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Search request, for example: find an agent that can write a market report."},
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
                "limit": {"type": "integer", "description": "Candidates per section. Default 10."},
            },
            "required": ["request"],
        },
    },
    {
        "name": "hephaestus_call",
        "description": (
            "Prepare explicitly named Agentlas Hub/cloud agents. This fetches BYOM "
            "runtime bundles and writes receipts; the caller runtime still runs "
            "the actual LLM/tool work."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agents": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Comma list or array of slugs. Prefix with cloud: for owner packages or hub: for public Hub.",
                },
                "context": {"type": "string", "description": "Task context passed to each named agent."},
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
                "version": {"type": "string", "description": "Hub package hash or latest."},
                "local_inventory": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Installed plugin slugs/names to pass to agentlas.resolve_plugins. Use [] to avoid local plugin matches.",
                },
            },
            "required": ["agents", "context"],
        },
    },
    {
        "name": "hephaestus_network_status",
        "description": "Report Hephaestus Network state: card counts, benchmark state, auto-routing gate.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agentlas_authenticate",
        "description": (
            "Open the user's browser for a one-time Agentlas Google/sign-in flow, "
            "store the local signed-in state under ~/.agentlas/auth, and reuse it "
            "for Claude Code, Codex, Antigravity, and other Hephaestus Hub calls."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "description": "Agentlas Hub base URL. Defaults to https://agentlas.cloud."},
                "open_browser": {
                    "type": "boolean",
                    "description": "Open the default browser automatically. Defaults to true.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Seconds to wait for browser sign-in. Defaults to 180.",
                },
            },
        },
    },
    {
        "name": "agentlas_auth_status",
        "description": "Report whether this machine already has a reusable Agentlas sign-in for Hephaestus Hub calls.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "description": "Agentlas Hub base URL. Defaults to https://agentlas.cloud."}
            },
        },
    },
    {
        "name": "hephaestus_hub_invoke",
        "description": (
            "Prepare an exact Agentlas Hub public agent through the Hephaestus Network "
            "surface. An exact slug is required before bundle preparation. Without one, "
            "the tool returns Hub candidates with status=selection_required and never "
            "requests a runtime bundle. With an exact slug, it requests the BYOM runtime "
            "bundle, resolves Hub plugins, touches Agentlas memory when memory_root is "
            "provided, and writes an execution receipt. The Hub does not run an LLM."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Prompt/task for the Hub agent."},
                "slug": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Exact Hub agent slug selected by the host. If omitted or blank, "
                        "the tool returns candidates with status=selection_required and "
                        "does not request a runtime bundle."
                    ),
                },
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
                "memory_root": {"type": "string", "description": "Optional Agentlas memory root to bootstrap/update missing-only."},
                "approve_hub": {
                    "type": "boolean",
                    "description": "Backward-compatible no-op; host runtimes gate actual execution.",
                },
                "version": {"type": "string", "description": "Hub package hash or latest."},
                "local_inventory": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Installed plugin slugs/names to pass to agentlas.resolve_plugins. Use [] to avoid local plugin matches.",
                },
            },
            "required": ["request"],
        },
    },
    {
        "name": "workforce.preflight_work_order",
        "description": (
            "Compile a compact semantic staffing draft into an exact, privacy-checked "
            "agentlas.workforce-work-order.v1 and pin it locally behind a one-hour workOrderRef. "
            "Core generates finite transaction IDs, empty arrays, artifact flow, ontology/version "
            "fields and digest deterministically. It performs no discovery and makes zero Hub calls. "
            "Use the returned workOrderRef with workforce.search_candidates instead of authoring or "
            "echoing the strict wire WorkOrder by hand."
        ),
        "inputSchema": _work_order_draft_schema(),
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.search_candidates",
        "description": (
            "Search the Agent Workforce Ontology with a locally preflighted WorkOrder reference. "
            "sourceScope=network federates Local, owner Cloud, and public Hub menus; exact "
            "local/cloud/hub values restrict discovery to that source. It never selects a team. "
            "The calling top-level LLM authors the semantic draft and makes the staffing decision."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workOrderRef": {
                    "type": "string",
                    "pattern": "^work-order-ref:[0-9a-f]{64}$",
                    "description": "One-hour local handle returned by workforce.preflight_work_order. Preferred; the exact WorkOrder never needs to be echoed.",
                },
                "workOrder": _contract_echo_property(
                    "workOrder",
                    "Legacy exact agentlas.workforce-work-order.v1 input. Prefer workOrderRef from workforce.preflight_work_order; Core still validates this object without mutation before any source call.",
                ),
                "expandSlotIds": {"type": "array", "items": {"type": "string"}},
                "sourceScope": {
                    "type": "string",
                    "enum": ["network", "local", "cloud", "hub"],
                    "description": (
                        "Required typed source scope. network=Local+Cloud+Hub; exact scopes never widen and there is no implicit fallback."
                    ),
                },
                "fullDossier": {
                    "type": "boolean",
                    "description": (
                        "Default false: the response is a decision menu — audit-weight fields "
                        "(qualificationEvidence, packageHash, contentDigest, candidateProvenance) stay in "
                        "Core's session store and each candidate carries a candidateOrdinal for "
                        "ordinal selection. semanticSnapshot.produces/consumes collapse to "
                        "producesCount/consumesCount: those entries do not repeat across candidates, so "
                        "they cannot rank one against another, and Core still matches on the stored "
                        "originals — read summaries, skills, communities and fitEvidence instead. "
                        "Set true only for a legacy full-echo flow."
                    ),
                },
                "shortlist": {
                    "type": "boolean",
                    "description": (
                        tool_schema_description('shortlist')
                    ),
                    "default": True,
                },
                "turnId": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "description": (
                        "Optional local turn/session identity used only to short-circuit repeated dead remote calls; "
                        "it is hashed locally and never sent to Cloud or Hub."
                    ),
                },
            },
            "required": ["sourceScope"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.expand_candidates",
        "description": (
            "Return the full candidate cards for a shortlist, after a shortlist=true search. "
            "Core resolves them from the pinned session, so send only the selectionSessionId and "
            "the slotId/candidateOrdinal pairs worth a closer look. This is a read: it does not "
            "select, rank, or change the pinned menu, and the ordinals stay the ones you select with."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "selectionSessionId": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "description": "The selectionSessionId printed on the shortlist menu.",
                },
                "candidates": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "slotId": {"type": "string", "minLength": 1, "maxLength": 256},
                            "candidateOrdinal": {"type": "integer", "minimum": 1},
                        },
                        "required": ["slotId", "candidateOrdinal"],
                    },
                    "description": "Ordinals restart at 1 within each slot — pair every ordinal with its slotId.",
                },
            },
            "required": ["selectionSessionId", "candidates"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.validate_selection",
        "description": (
            "Validate a team selected by the calling host LLM against an exact candidate set. "
            "Core holds the federated session it issued, so send only selection.selectionSessionId "
            "and it loads the pinned menu AND the pinned workOrder itself — echoing either back "
            "adds bytes but no information (Core only ever byte-compares them to its own store). It never sends the merged menu to a remote source or "
            "selects/reranks/substitutes agents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workOrder": _contract_echo_property(
                    "workOrder",
                    "The exact WorkOrder already accepted by workforce.search_candidates. Send it back unchanged — Core revalidates it against the full contract, and any edit invalidates the pinned candidate set.",
                ),
                "candidateSet": {
                    "type": "object",
                    "description": (
                        "Optional. Omit it: Core resolves the exact pinned set from "
                        "selection.selectionSessionId and re-verifies its digest and expiry. Send it "
                        "only to validate a set this process did not issue."
                    ),
                },
                "federationResult": {
                    "type": "object",
                    "description": (
                        "Optional. Omit it: Core loads the locally pinned federation result for "
                        "selection.selectionSessionId. A live menu wide enough to contain the right "
                        "agent does not fit in one tool call, and its digest covers the exact bytes "
                        "so it cannot be trimmed — narrowing the menu to fit is how the intended "
                        "pick gets cut. Core never sends the merged menu to a remote source."
                    ),
                },
                "decision": _selection_decision_schema(),
                "selection": {
                    "type": "object",
                    "description": (
                        "Legacy exact agentlas.workforce-selection.v1. Prefer `decision`: it carries the "
                        "same choice without the empty arrays and the copied candidate-set digest, and "
                        "Core compiles it into this exact object. Either form is validated against the "
                        "canonical schema server-side, so publishing that schema here a second time "
                        "would spend context without adding enforcement."
                    ),
                },
            },
            # workOrder 는 더 이상 필수가 아니다 — 세션에 핀된 저장본이 항상
            # 권위이고(assert_work_order_binding 이 바이트 동일을 요구), 생략 시
            # Core 가 selectionSessionId 로 복원한다. 판별식: 안 보내도 복원
            # 가능하면 그 필드는 인자가 아니라 의례다(2026-08-19).
            #
            # 결정 자체는 여전히 반드시 온다 — 컴팩트 `decision` 이든 레거시
            # 정확 `selection` 이든 하나는 있어야 한다. "둘 중 하나"를 코드가
            # 아니라 스키마가 말하게 둔다.
            "required": [],
            "anyOf": [{"required": ["decision"]}, {"required": ["selection"]}],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.prepare_execution",
        "description": (
            "Fetch BYOM runtime bundles only for an already accepted exact roster. "
            "Pins agentReleaseId, packageHash, and contentDigest and fails closed on drift; "
            "it never chooses replacements. A successful preparation is atomically bound "
            "to durable work continuity; callers cannot opt out by omitting an explicit goal mode. "
            "Preparation does not run workers: execute the bound goal through native host "
            "invocations or `hephaestus workforce execute` with an explicit host adapter."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workOrder": _contract_echo_property(
                    "workOrder",
                    "The exact WorkOrder already accepted by workforce.search_candidates. Send it back unchanged — Core revalidates it against the full contract, and any edit invalidates the pinned candidate set.",
                ),
                "candidateSet": {
                    "type": "object",
                    "description": (
                        "Optional. Omit it: Core resolves the exact pinned set from "
                        "selection.selectionSessionId and re-verifies its digest and expiry. Send it "
                        "only to prepare a set this process did not issue."
                    ),
                },
                "decision": _selection_decision_schema(),
                "selection": _prepare_selection_property(),
                "validationReceipt": {"type": "object"},
                "federationResult": {
                    "type": "object",
                    "description": (
                        "Optional. Omit it: Core loads the locally pinned federation result for "
                        "selection.selectionSessionId. The default search answer is a decision menu "
                        "with candidateProvenance dropped, so echoing that back is rejected outright "
                        "— resolve by session instead of re-fetching the full dossier to have "
                        "something to echo."
                    ),
                },
                "federatedSelection": {
                    "type": "object",
                    "description": "Exact accepted result returned by federated workforce.validate_selection. Prefer sending only federatedSelectionDigest instead — Core holds the accepted wrapper it issued and loads it by digest, so echoing the whole object back adds bytes but no information.",
                },
                "federatedSelectionDigest": {
                    "type": "string",
                    "description": "The federatedSelectionDigest from the accepted validate_selection result. Core resolves the pinned wrapper from its own session store — send this instead of the full federatedSelection object.",
                },
                "prepareAttempt": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": (
                        "Optional caller-authored agentlas.workforce-prepare-attempt.v1. Its digest binds the "
                        "logical occurrence, exact WorkOrder/Selection, federated selection, and every source pin. "
                        "Omit it: the idempotencyKey is a canonical sha256 no host LLM can hand-compute, so Core "
                        "derives the attempt from the accepted federatedSelection (occurrenceId from its "
                        "selectionSessionId, so a same-session retry stays idempotent). Send it only from callers "
                        "that compute digests programmatically."
                    ),
                    "properties": {
                        "schemaVersion": {"const": "agentlas.workforce-prepare-attempt.v1"},
                        "occurrenceId": {"type": "string", "minLength": 1, "maxLength": 512},
                        "workOrderDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                        "selectionDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                        "federatedSelectionDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                        "selectedSourcePinDigests": {
                            "type": "array", "minItems": 1, "maxItems": 128,
                            "uniqueItems": True,
                            "items": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                        },
                        "idempotencyKey": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                    },
                    "required": [
                        "schemaVersion", "occurrenceId", "workOrderDigest", "selectionDigest",
                        "federatedSelectionDigest", "selectedSourcePinDigests", "idempotencyKey",
                    ],
                },
                "projectDir": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4096,
                    "description": "Current local project/workspace used for automatic durable binding.",
                },
                "goalId": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "description": (
                        "Optional host Task/conversation id. When absent Core derives a stable "
                        "content-free id from the WorkOrder id; the user need not say goal."
                    ),
                },
                "turnId": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "description": (
                        "Optional local turn/session identity used only to short-circuit repeated dead remote calls; "
                        "it is hashed locally and never sent to Cloud or Hub."
                    ),
                },
                "fullDossier": {
                    "type": "boolean",
                    "description": (
                        tool_schema_description('prepare-projection')
                    ),
                },
            },
            # workOrder 와 federatedSelection 은 더 이상 필수가 아니다 — 둘 다
            # 세션 저장본이 권위라 생략 시 Core 가 복원한다: workOrder 는
            # selectionSessionId 로, federatedSelection 은 federatedSelectionDigest 로.
            # projectDir 는 진짜 인자다(호스트만 아는 값), selection 도 그렇다.
            # 결정은 컴팩트 decision 이나 레거시 exact selection 중 하나로 온다.
            # projectDir 은 언제나 필수다 — 연속성은 선택이 아니다.
            "required": ["projectDir"],
            "anyOf": [{"required": ["decision"]}, {"required": ["selection"]}],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.validate_execution_receipt",
        "description": (
            "Read-only validation of one host-produced execution receipt against "
            "the exact prepared plan and a private local tool-inventory snapshot. "
            "This tool does not execute workers, create a receipt, or call Hub."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "receipt": {"type": "object"},
                "executionPlan": {"type": "object"},
                "toolInventory": {"type": "object"},
                "benchmarkMode": {"type": "boolean", "default": False},
            },
            "required": ["receipt", "executionPlan", "toolInventory"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.bind_goal",
        "description": (
            "Bind an already prepared exact Workforce roster to one durable host goal. "
            "The binding survives turns, sessions, and host restarts; "
            "repeated calls append only newly prepared exact releases."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "goalId": {"type": "string", "minLength": 1, "maxLength": 256},
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "preparation": {"type": "object"},
                "goalLabel": {"type": "string", "maxLength": 240},
                "rosterLabels": {
                    "type": "object",
                    "additionalProperties": {"type": "string", "maxLength": 160},
                },
            },
            "required": ["goalId", "projectDir", "preparation"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.goal_context",
        "description": (
            "Read the current account- and project-scoped durable Workforce roster. "
            "Call this at the start of a goal turn before deciding whether the existing "
            "roster plus local skills is sufficient or an additive recruitment is needed. "
            "Returns the bounded goal-context.v2 view; pass knownRevisions to get only what changed, "
            "and read pendingExecution — those releases were prepared and never executed."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "goalId": {"type": "string", "minLength": 1, "maxLength": 256},
                "includeTerminal": {"type": "boolean"},
                "knownRevisions": {
                    "type": "object",
                    "additionalProperties": {"type": "integer", "minimum": 0},
                    "description": "goalId -> rosterRevision already in this conversation. Matching goals come back as state=unchanged instead of a full roster.",
                },
                "fullDossier": {
                    "type": "boolean",
                    "description": "Legacy uncompacted context including exact release identity. Preparation resolves exact releases from Core's own store, so a turn decision never needs this.",
                },
            },
            "required": ["projectDir"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.goal_runtime",
        "description": (
            "Load the exact locally cached prepared plans for an active account/project "
            "goal. Free Hub and owned plans remain available without a lease. "
            "Legacy leased plans return lease-refresh-required with no directives after expiry."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "goalId": {"type": "string", "minLength": 1, "maxLength": 256},
            },
            "required": ["projectDir"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.record_goal_turn",
        "description": (
            "Record the host LLM's content-free per-turn choice: reuse the bound roster, "
            "use local skills only, recruit a real gap, remain on standby, or block. "
            "This records a decision without executing a model or calling a Hub agent."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "goalId": {"type": "string", "minLength": 1, "maxLength": 256},
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "turnId": {"type": "string", "minLength": 1, "maxLength": 256},
                "decision": {
                    "type": "string",
                    "enum": ["reuse", "recruit", "local-only", "blocked", "standby"],
                },
                "usedRosterKeys": {
                    "type": "array",
                    "maxItems": 128,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                },
                "localSkillIds": {
                    "type": "array",
                    "maxItems": 128,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 160},
                },
                "gapCodes": {
                    "type": "array",
                    "maxItems": 128,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 160},
                },
                "hostRuntime": {"type": "string", "maxLength": 80},
            },
            "required": ["goalId", "projectDir", "turnId", "decision"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.complete_goal",
        "description": (
            "Release a durable Workforce binding only after an explicit host/user goal "
            "completion or cancellation. A model turn ending or a legacy lease expiring "
            "is never sufficient."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "goalId": {"type": "string", "minLength": 1, "maxLength": 256},
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "explicitCompletion": {"const": True},
                "status": {"type": "string", "enum": ["completed", "cancelled"]},
                "reason": {"type": "string", "maxLength": 160},
            },
            "required": ["goalId", "projectDir", "explicitCompletion"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "goal.strategy",
        "description": (
            "Plan tree and KPI check for a long, measurable goal (adds to the host /goal; the host still decides when "
            "the work is done). Start with action=schema. Changes only the goal's own files, never permissions or payments."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": ["schema", "start", "plan_op", "kpi_define", "kpi_sample", "review", "owner_answer", "status", "refresh", "context"]},
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "goalId": {"type": "string", "maxLength": 64},
                "goalText": {"type": "string", "maxLength": 4000, "description": "start only: the owner's exact goal text"},
                "payload": {"type": "object", "description": "start: plan draft; plan_op / kpi_define / kpi_sample: the object from action=schema; review: an optional shift; owner_answer: {answer, note}"},
                "key": {"type": "string", "maxLength": 80, "description": "idempotency key; a retry with the same key returns the first receipt"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "context.refresh",
        "description": "Explicitly build one complete content-addressed project Context Map snapshot.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "force": {"type": "boolean", "default": False}
            },
            "required": ["projectDir"]
        }
    },
    {
        "name": "context.locate",
        "description": (
            "Locate exact project symbols, definitions, and reverse references in the "
            "local dependency map. Project files and query results never leave the host."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "query": {"type": "string", "minLength": 1, "maxLength": 12_000},
                "refresh": {
                    "type": "boolean",
                    "description": "Omit to auto-refresh once when the map is stale; true forces a rebuild; false is a strict passive no-write read that may return context_map_stale.",
                },
            },
            "required": ["projectDir", "query"],
        },
    },
    {
        "name": "context.refs",
        "description": (
            "Return every bounded local backlink for one exact symbol. Use this before "
            "editing a function, type, route, field, or public contract."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "symbol": {"type": "string", "minLength": 1, "maxLength": 256},
                "refresh": {
                    "type": "boolean",
                    "description": "Omit to auto-refresh once when the map is stale; true forces a rebuild; false is a strict passive no-write read that may return context_map_stale.",
                },
            },
            "required": ["projectDir", "symbol"],
        },
    },
    {
        "name": "context.slice",
        "description": (
            "Build the minimal dependency-selected Context Slice for a resolved task. "
            "Selection follows definitions, backlinks, module edges, declared inheritance, "
            "and interfaces rather than embedding similarity."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "task": {"type": "string", "maxLength": 12_000},
                "targets": {
                    "type": "array",
                    "maxItems": 128,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 4096},
                },
                "refresh": {
                    "type": "boolean",
                    "description": "Omit to auto-refresh once when the map is stale; true forces a rebuild; false is a strict passive no-write read that may return context_map_stale.",
                },
                "render": {"type": "boolean"},
            },
            "required": ["projectDir", "task"],
        },
    },
    {
        "name": "context.impact",
        "description": (
            "Trace changed files or symbols through reverse references and module "
            "dependencies. Returns a local, content-free impact receipt."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "changed": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 256,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 4096},
                },
                "refresh": {
                    "type": "boolean",
                    "description": "Omit to auto-refresh once when the map is stale; true forces a rebuild; false is a strict passive no-write read that may return context_map_stale.",
                },
            },
            "required": ["projectDir", "changed"],
        },
    },
    {
        "name": "context.verify",
        "description": (
            "Completion gate: fail closed while any impacted file is neither changed, "
            "reviewed, nor explicitly waived. Returns a deterministic verification receipt."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "changed": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 256,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 4096},
                },
                "reviewed": {
                    "type": "array",
                    "maxItems": 512,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 4096},
                },
                "verified": {
                    "type": "array",
                    "maxItems": 512,
                    "uniqueItems": True,
                    "description": "Exact test or CI paths with successful execution evidence; review alone never satisfies a verification channel.",
                    "items": {"type": "string", "maxLength": 4096},
                },
                "waived": {
                    "type": "array",
                    "maxItems": 512,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 4096},
                },
                "refresh": {
                    "type": "boolean",
                    "description": "Omit to auto-refresh once when the map is stale; true forces a rebuild; false is a strict passive no-write verification that may return context_map_stale.",
                },
            },
            "required": ["projectDir", "changed"],
        },
    },
]


TOOLS.extend(LEASE_TOOLS)
TOOLS.extend(TAKEDOWN_TOOLS)

# These tools retain Web's authenticated package/session authority. Core only
# forwards declared requests and consumes automatic curation in its trusted
# background adapter; complete_memory_curation is deliberately not a model tool.
_REMOTE_MEMORY_TOOLS = [
    {
        "name": "agentlas.record_agent_memory",
        "description": "Record a compact package turn summary for automatic memory consolidation. Never send raw transcripts or credentials. The host processes curation in the background; no manual memory approval or foreground judgment is required.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["slug", "summary"],
                        "properties": {
                            "slug": {"type": "string"}, "summary": {"type": "string"},
                            "sourceRef": {"type": "string", "description": "Stable turn or Ticket reference; omit memoryType for summary-only extraction."},
                            "sessionId": {"type": "string", "description": "Server-minted package memory session ID."},
                            "sessionToken": {"type": "string", "description": "Owner-bound capability from memory_session_open."},
                            "outcome": {"type": "string", "enum": ["completed", "failed", "cancelled", "unknown"]},
                            "memoryType": {"type": "string", "enum": ["preference", "fact", "failure_recovery", "project_context", "decision", "warning"]},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "evidence": {"type": "string"}, "salience": {"type": "number"},
                            "visibility": {"type": "string", "enum": ["workspace", "user_private", "project", "global", "team"]},
                            "supersedesId": {"type": "string"}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
    {
        "name": "agentlas.decide_agent_learning",
        "description": "Process an existing package memory or playbook candidate. Memory promotion queues automatic model consolidation; it is not a human approval requirement for ordinary turn memory.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["slug", "kind", "id", "decision"],
                        "properties": {"slug": {"type": "string"}, "kind": {"type": "string", "enum": ["memory", "playbook"]},
                                       "id": {"type": "string"}, "decision": {"type": "string", "enum": ["promote", "reject"]}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
    {
        "name": "agentlas.memory_curation_request",
        "description": "Resume a server-owned automatic memory job using the host's configured no-tools background adapter. Does not select a new model or expose private curation input to the foreground model.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["jobId"],
                        "properties": {"jobId": {"type": "string"}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
    {
        "name": "agentlas.memory_session_open",
        "description": "Bind package turn summaries and continuation to an authenticated logical host session. The server mints the session capability; it grants no model or tool execution permission.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["slug", "hostSessionKey"],
                        "properties": {"slug": {"type": "string"}, "hostSessionKey": {"type": "string"},
                                       "goal": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}},
                                       "originTaskId": {"type": "string"}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "agentlas.memory_session_recap",
        "description": "Read the source-bound package checkpoint and memory context using the owner session capability. Recap is the existing continuation projection, without a second model summary.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["slug", "sessionId", "sessionToken"],
                        "properties": {"slug": {"type": "string"}, "sessionId": {"type": "string"}, "sessionToken": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
]
TOOLS.extend(_REMOTE_MEMORY_TOOLS)
_REMOTE_MEMORY_TOOL_NAMES = frozenset(tool["name"] for tool in _REMOTE_MEMORY_TOOLS)
_SCOPE_ARG = {"type": "string", "enum": ["default", "owner_all"],
              "description": "default: this project, the owner and this agent. owner_all: every project on this machine."}
_PROJECT_ARG = {"type": "string", "maxLength": 4096, "description": "Project folder; defaults to the current working directory."}
_TIME_ARG = {"type": "string", "maxLength": 40, "description": "ISO 8601 time, e.g. 2026-08-30T05:00:00Z."}
_LOCAL_MEMORY_TOOLS = [
    {
        "name": "memory.search",
        "description": ("Search this machine's Agentlas memory (curated memories and dated turn summaries from every runtime) "
                        "by meaning and keywords. Each result carries its date, source and match strength."),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 2000,
                      "description": "Keywords or a short phrase in any language work best."},
            "since": _TIME_ARG, "until": _TIME_ARG,
            "types": {"type": "array", "items": {"type": "string", "enum": ["memory", "episode"]}, "uniqueItems": True},
            "kinds": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 40}},
            "scope": _SCOPE_ARG, "projectDir": _PROJECT_ARG,
            "include_confidential": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, "required": ["query"]},
    },
    {
        "name": "memory.timeline",
        "description": "List what happened on this machine in a time range, oldest first, from Agentlas memory and turn summaries.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "since": _TIME_ARG, "until": _TIME_ARG,
            "types": {"type": "array", "items": {"type": "string", "enum": ["memory", "episode"]}, "uniqueItems": True},
            "scope": _SCOPE_ARG, "projectDir": _PROJECT_ARG,
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "cursor": {"type": "integer", "minimum": 0}}, "required": ["since"]},
    },
    {
        "name": "memory.get",
        "description": "Show one Agentlas memory or turn summary with its origin turn, replacements and similar memories.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "id": {"type": "string", "minLength": 3, "maxLength": 520},
            "scope": _SCOPE_ARG, "projectDir": _PROJECT_ARG}, "required": ["id"]},
    },
    {
        "name": "memory.crosscheck",
        "description": ("Find Agentlas memories related to statements from your own runtime memory, with dates, "
                        "so you can judge agreement or conflict. Returns candidates only, no verdict."),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "claims": {"type": "array", "minItems": 1, "maxItems": 10, "items": {"type": "string", "minLength": 1, "maxLength": 500}},
            "scope": _SCOPE_ARG, "projectDir": _PROJECT_ARG}, "required": ["claims"]},
    },
    {
        "name": "memory.record",
        "description": ("Record a one-sentence summary of this turn's work, and optional observations, into Agentlas memory. "
                        "Never include secrets, credentials or transcripts."),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "turn_summary": {"type": "string", "minLength": 1, "maxLength": 300},
            "observations": {"type": "array", "maxItems": 8, "items": {"type": "object", "additionalProperties": False, "properties": {
                "content": {"type": "string", "minLength": 1, "maxLength": 500},
                "kind": {"type": "string", "enum": ["fact", "decision", "preference", "risk", "procedure"]},
                "scope": {"type": "string", "enum": ["project", "agent_repo", "user_identity"]},
                "evidence": {"type": "string", "maxLength": 300},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]}}, "required": ["content", "kind"]}},
            "projectDir": _PROJECT_ARG}, "required": ["turn_summary"]},
    },
]
TOOLS.extend(_LOCAL_MEMORY_TOOLS)
_LOCAL_MEMORY_TOOL_NAMES = frozenset(tool["name"] for tool in _LOCAL_MEMORY_TOOLS)
_MEMORY_GATED_TOOL_NAMES = _REMOTE_MEMORY_TOOL_NAMES | _LOCAL_MEMORY_TOOL_NAMES
_CLIENT_NAME: list[str] = [""]
_CONTEXT_MAP_TOOL_NAMES = frozenset({"context.refresh", "context.locate", "context.refs", "context.slice", "context.impact", "context.verify"})


def _feature_on(name: str) -> bool:
    try:
        from .feature_preferences import feature_enabled
        return feature_enabled(name, mcp=True)
    except Exception:
        return False


def _inventory_state() -> tuple[bool, bool]:
    return (_feature_on("context-map"), _feature_on("memory-hooks"))


def _available_tools() -> list[dict[str, Any]]:
    context_on, memory_on = _inventory_state()
    return [tool for tool in TOOLS if (context_on or tool["name"] not in _CONTEXT_MAP_TOOL_NAMES)
            and (memory_on or tool["name"] not in _MEMORY_GATED_TOOL_NAMES)]


# MCP tool annotations (spec 2025-03-26, "Tool annotations"): every tool states
# what it does to its environment. Hosts decide approval from these hints —
# codex exec runs unattended/write turns with approval_policy "never" and
# refuses, before the server sees it, every MCP call without readOnlyHint
# ("MCP tool call requires approval, but approval policy is never"; desktop
# Threads automation 2026-09-24, hephaestus_network_status). None of these
# tools declared annotations, so pure reads were refused in automations and
# prompted in One write mode.
#
# readOnlyHint follows HTTP "safe" semantics (RFC 9110 §9.2.1): the caller does
# not request a state change. A derived cache the read itself maintains (the
# Context Map auto-refresh of an already-initialized project, a one-hour pinned
# WorkOrder/candidate session) is not a requested change. Anything that
# creates project state (first-contact bootstrap), writes receipts or bindings,
# signs in, or fetches runtime bundles is not read-only — say so truthfully.
_READ = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
_WRITE = {"readOnlyHint": False, "destructiveHint": False}
_TOOL_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "agentlas.read_agent_file": {**_READ, "openWorldHint": False},
    "agentlas_resolve_plugins": {**_READ, "openWorldHint": True},
    "agentlas_tool_search": {**_READ, "openWorldHint": False},
    "model.resolve_allocation": {**_READ, "openWorldHint": False},
    "hephaestus_network_status": {**_READ, "openWorldHint": False},
    "agentlas_auth_status": {**_READ, "openWorldHint": False},
    "workforce.preflight_work_order": {**_READ, "idempotentHint": False, "openWorldHint": False},
    "workforce.search_candidates": {**_READ, "idempotentHint": False, "openWorldHint": True},
    "workforce.expand_candidates": {**_READ, "openWorldHint": False},
    "workforce.validate_selection": {**_READ, "openWorldHint": False},
    "workforce.validate_execution_receipt": {**_READ, "openWorldHint": False},
    "workforce.goal_context": {**_READ, "openWorldHint": False},
    "workforce.goal_runtime": {**_READ, "openWorldHint": False},
    "context.locate": {**_READ, "openWorldHint": False},
    "context.refs": {**_READ, "openWorldHint": False},
    "context.slice": {**_READ, "openWorldHint": False},
    "context.impact": {**_READ, "openWorldHint": False},
    "context.verify": {**_READ, "openWorldHint": False},
    "memory.search": {**_READ, "openWorldHint": False},
    "memory.timeline": {**_READ, "openWorldHint": False},
    "memory.get": {**_READ, "openWorldHint": False},
    "memory.crosscheck": {**_READ, "openWorldHint": False},
    # Queues one ticket per call through the existing owner memory queue.
    "memory.record": {**_WRITE, "idempotentHint": False, "openWorldHint": False},
    # First contact bootstraps .agentlas into the caller's project.
    "hephaestus_route": {**_WRITE, "openWorldHint": True},
    "hephaestus_cloud_search": {**_WRITE, "openWorldHint": True},
    "hephaestus_search": {**_WRITE, "openWorldHint": True},
    # Fetch runtime bundles and write execution receipts.
    "hephaestus_call": {**_WRITE, "openWorldHint": True},
    "hephaestus_hub_invoke": {**_WRITE, "openWorldHint": True},
    "workforce.prepare_execution": {**_WRITE, "openWorldHint": True},
    "agentlas_authenticate": {**_WRITE, "idempotentHint": True, "openWorldHint": True},
    "workforce.bind_goal": {**_WRITE, "idempotentHint": True, "openWorldHint": False},
    "workforce.record_goal_turn": {**_WRITE, "openWorldHint": False},
    # Releases a durable binding; not undoable by calling again.
    "workforce.complete_goal": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
    "context.refresh": {**_WRITE, "idempotentHint": True, "openWorldHint": False},
    "goal.strategy": {**_WRITE, "idempotentHint": True, "openWorldHint": False},
}
for _tool in TOOLS:
    _declared = _tool.get("annotations")
    _mapped = _TOOL_ANNOTATIONS.get(str(_tool["name"]))
    if _declared is None and _mapped is None:
        # A new tool must say what it does before it ships; failing at import
        # keeps an unannotated tool from silently becoming "needs approval".
        raise RuntimeError(f"MCP tool {_tool['name']} declares no annotations")
    if _declared is None:
        _tool["annotations"] = dict(_mapped)
del _tool, _declared, _mapped


class UnknownToolError(LookupError):
    """Raised only when this server implements no tool with the given name.

    The unknown-tool signal used to be a bare ``KeyError(name)``, and the
    dispatcher caught bare ``KeyError``. Every other KeyError in the call —
    a missing required argument (``arguments["request"]``) or any KeyError
    raised deep inside route_request/search/hub_invoke, where the workforce
    layers use KeyError as an internal error code — was therefore reported to
    the host as "unknown tool: <name>". A host LLM told a tool does not exist
    stops calling it instead of repairing the call, so a one-argument mistake
    or a real internal failure permanently removed a working tool. A dedicated
    exception keeps "this tool does not exist" distinguishable from "this call
    failed".
    """


_DECLARED_TOOL_REQUIRED_ARGUMENTS: dict[str, tuple[str, ...]] = {
    str(tool["name"]): tuple(
        str(field)
        for field in (tool.get("inputSchema") or {}).get("required") or []
    )
    for tool in TOOLS
}


def _missing_required_arguments(name: str, arguments: Mapping[str, Any]) -> list[str]:
    """Required arguments the caller omitted, per this server's own tools/list.

    The contract is read back from TOOLS instead of being restated per handler,
    so a tool cannot advertise a required argument in tools/list and then fail
    on it with an unrelated error.
    """

    return [
        field
        for field in _DECLARED_TOOL_REQUIRED_ARGUMENTS.get(name, ())
        if arguments.get(field) is None
    ]


def _workforce_preparation_ready(result: Any) -> bool:
    """Whether a preparation actually pinned an executable roster.

    A rejected preparation (for example team_execution_graph_missing) carries an
    empty executionRoster. Binding it produces a goal-binding error whose code
    hides the real cause, so readiness must gate the bind call.
    """

    return workforce_preparation_ready(result)


def _workforce_preparation_refusal(name: str, result: Any) -> dict[str, Any]:
    """Return the preparation's own refusal, never a binding error in its place."""

    return workforce_preparation_refusal(name, result)


def _project_work_brief(project_dir: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Discover a project's Work Brief for an MCP route. Returns (brief, warning).

    Discovery only, so a project with no brief is the normal case and never
    blocks the call. A brief that IS there but fails validation is a different
    thing: the host asked for a routed plan and would get one shaped by nothing
    it wrote, so the exact `work_brief_problem` reason rides back on the result.
    Same warning shape the CLI emits, so a host does not have to learn two.
    """
    from .interview import resolve_work_brief

    resolved = resolve_work_brief(project_dir or ".")
    if resolved.problem:
        return None, {
            "path": str(resolved.path),
            "problem": resolved.problem,
            "effect": "this route ran without the Work Brief",
        }
    return resolved.brief, None


def _workforce_circuit_key(arguments: Mapping[str, Any], work_order: Mapping[str, Any]) -> str:
    """Hash host turn context for the local remote circuit only."""

    # An explicit turn/session is the unit of continuity. Do not append the
    # WorkOrder digest in that case: search -> validate -> prepare may carry
    # different tool payloads while still belonging to the same host turn and
    # must fail fast after the first dead remote source. Direct callers without
    # host continuity still get a safe exact-work-order key in source_service.
    context = arguments.get("turnId") or arguments.get("sessionId")
    material: dict[str, Any] = {
        "schemaVersion": "agentlas.workforce-remote-circuit-context.v1",
        "hostContext": str(context) if context else None,
    }
    if not context:
        material["workOrderDigest"] = canonical_digest(work_order)
    return canonical_digest(
        material
    )


def _restore_prepared_selection_reference(arguments: dict[str, Any]) -> dict[str, Any]:
    """Restore an accepted choice without inferring or reauthoring its pins."""

    from .workforce.federation_store import FederationSessionError, FederationSessionStore

    reference = arguments.get("selection")
    if not isinstance(reference, Mapping):
        return arguments
    is_wrapper = reference.get("schemaVersion") == WORKFORCE_FEDERATED_SELECTION_SCHEMA
    is_reference = bool(reference) and set(reference) <= {
        "selectionSessionId", "federatedSelectionDigest"
    }
    if not is_wrapper and not is_reference:
        return arguments
    session = reference.get("selectionSessionId")
    if not isinstance(session, str) or not session.strip():
        raise FederationSessionError("selection_reference_session_required")
    nested_digest = reference.get("federatedSelectionDigest")
    digest = arguments.get("federatedSelectionDigest") or nested_digest
    if not isinstance(digest, str) or not digest.strip():
        raise FederationSessionError("selection_reference_digest_required")
    if nested_digest is not None and nested_digest != digest:
        raise FederationSessionError("selection_reference_digest_conflict")
    pinned = FederationSessionStore().get_federated_selection(session.strip(), digest.strip())
    supplied_wrapper = arguments.get("federatedSelection")
    for supplied in ([reference] if is_wrapper else []) + (
        [supplied_wrapper] if supplied_wrapper is not None else []
    ):
        try:
            matches = isinstance(supplied, Mapping) and canonical_digest(supplied) == canonical_digest(pinned)
        except (TypeError, ValueError, RecursionError):
            matches = False
        if not matches:
            raise FederationSessionError("selection_reference_wrapper_mismatch")
    validation = pinned.get("selectionValidation")
    receipt = validation.get("receipt") if isinstance(validation, Mapping) else None
    try:
        if not isinstance(receipt, Mapping):
            raise ValueError("missing_receipt")
        selection = {
            "schemaVersion": "agentlas.workforce-selection.v1",
            **{
                key: receipt[key]
                for key in (
                    "selectionSessionId", "candidateSetDigest", "decisionAuthor", "edges",
                    "alternativesConsidered", "requestExpansionForSlots",
                )
            },
            "assignments": [
                {key: row[key] for key in ("slotId", "agentReleaseId", "reasonCodes")}
                for row in receipt["assignments"]
            ],
        }
        if canonical_digest(selection) != pinned.get("selectionDigest"):
            raise ValueError("exact_selection_unrecoverable")
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        # Older receipts normalize lists. Never treat that normalized choice as
        # the exact original unless its digest proves they are identical.
        raise FederationSessionError("selection_reference_exact_echo_required") from exc
    return {
        **arguments,
        "selection": selection,
        "federatedSelection": pinned,
        "federatedSelectionDigest": pinned["federatedSelectionDigest"],
    }


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name in _CONTEXT_MAP_TOOL_NAMES and not _feature_on("context-map"):
        return {"action": name, "status": "rejected", "error": "feature_disabled", "feature": "context-map", "writeAttempted": False}
    if name in _MEMORY_GATED_TOOL_NAMES and not _feature_on("memory-hooks"):
        return {"action": name, "status": "rejected", "error": "feature_disabled", "feature": "memory-hooks", "writeAttempted": False}
    from .networking import init_networking, network_status, route_request
    from .networking.bootstrap import networking_home

    missing_arguments = _missing_required_arguments(name, arguments)
    if missing_arguments:
        # Refuse the call in words the caller can act on, before any handler
        # indexes the argument. Naming the omitted arguments is the whole
        # repair: the host adds them and retries the same tool.
        return {
            "action": name,
            "status": "rejected",
            "error": "missing_required_argument",
            "missingArguments": missing_arguments,
            "detail": (
                f"{name} was called without required argument(s): "
                f"{', '.join(missing_arguments)}. Call {name} again with "
                "those argument(s) set."
            ),
            "repairable": True,
        }

    if name in _LOCAL_MEMORY_TOOL_NAMES:
        from . import memory_recall
        try:
            if name == "memory.record":
                return {"action": name, **memory_recall.record(arguments, host=_CLIENT_NAME[0])}
            handler = {"memory.search": memory_recall.search, "memory.timeline": memory_recall.timeline,
                       "memory.get": memory_recall.get, "memory.crosscheck": memory_recall.crosscheck}[name]
            return {"action": name, **handler(arguments)}
        except memory_recall.RecallError as error:
            return {"action": name, "status": "rejected", "error": error.code, "writeAttempted": False}
        except ValueError as error:
            code = str(error) if re.fullmatch(r"memory_[a-z_]+", str(error)) else "memory_unavailable"
            return {"action": name, "status": "rejected", "error": code, "writeAttempted": name == "memory.record"}

    if name == "agentlas.read_agent_file":
        from .runtime import read_agent_file

        if any(not isinstance(arguments.get(key), str) or not arguments[key].strip() for key in ("root", "path")):
            return {"action": name, "status": "rejected", "error": "package_read_argument_invalid"}
        return read_agent_file(arguments["root"], arguments["path"])

    if name in {LEASE_QUOTE, LEASE_PURCHASE}:
        return call_agent_lease_tool(name, arguments)

    if name == TAKEDOWN:
        return call_agent_takedown_tool(name, arguments)

    if name in {"hephaestus_route", "hephaestus_cloud_search"} and os.environ.get(
        "HEPHAESTUS_LEGACY_ROUTER"
    ) != "1":
        return {
            "action": name,
            "status": "rejected",
            "error": "legacy_router_disabled",
            "repairable": True,
            "detail": (
                "Use typed workforce.search_candidates, workforce.validate_selection, "
                "and workforce.prepare_execution. Set HEPHAESTUS_LEGACY_ROUTER=1 "
                "only for explicit compatibility/debug routing."
            ),
        }

    if name in _REMOTE_MEMORY_TOOL_NAMES:
        from .networking.hub_client import call_hub_tool
        return call_hub_tool(name, arguments)

    if name == "workforce.validate_execution_receipt":
        from .workforce.execution import validate_execution_receipt

        values = (
            ("receipt", arguments.get("receipt"), 16 * 1024 * 1024),
            ("executionPlan", arguments.get("executionPlan"), 64 * 1024 * 1024),
            ("toolInventory", arguments.get("toolInventory"), 16 * 1024 * 1024),
        )
        for label, value, maximum in values:
            if not isinstance(value, Mapping):
                return {"action": name, "status": "rejected", "error": f"{label}_invalid"}
            try:
                size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            except (TypeError, ValueError):
                return {"action": name, "status": "rejected", "error": f"{label}_invalid"}
            if size > maximum:
                return {"action": name, "status": "rejected", "error": f"{label}_too_large"}
        result = validate_execution_receipt(
            arguments["receipt"],
            execution_plan=arguments["executionPlan"],
            tool_inventory=arguments["toolInventory"],
            benchmark_mode=arguments.get("benchmarkMode") is True,
        )
        if isinstance(result, dict) and result.get("status") == "rejected":
            # A raised stop must carry its way out (2026-09-05). The v2 receipt is a
            # runtime-produced artifact (invocation evidence, sandbox enforcement,
            # domain-separated binding digests); a host LLM cannot hand-author it, and
            # until now the rejection listed issue codes with no pointer to the
            # contract or to the executors that emit valid receipts. Measured: a
            # prepared Hub roster stayed "prepared, not executed" because this was
            # the only answer the host ever got.
            result = {
                **result,
                "hostExecutionBlocked": False,
                "hostExecutionBlockScope": "receipt-validation-only",
                "hostAuthorizationRequired": True,
                "evidenceStatus": "unvalidated",
                "hostExecutionContract": host_execution_contract(arguments["executionPlan"], wrapped=False),
                "receiptContract": {
                    "schemaVersion": "agentlas.workforce-execution-receipt.v2",
                    "schemaRef": "schemas/workforce-execution-receipt.schema.json",
                    "producedBy": [
                        "Current host native executor (when runtime receipt telemetry is available)",
                        "hephaestus workforce execute --project <project> --goal-id <goal> --adapter-argv-json '[\"<host-adapter>\"]' (external host adapter)",
                        "agentlas workforce \"<request>\" (Agentlas Terminal executor)",
                        "Agentlas Desktop Work (borrowed task force executor)",
                    ],
                    "adapterContractRef": "agentlas_cloud/workforce/host_executor.py",
                    # prompt-module: {"id":"tool.workforce.receipt-recovery","revision":2,"stability":"fixed-policy","changeTriggers":["release"],"order":0}
                    "hostGuidance": (
                        "Use the current host's native delegation with the exact prepared "
                        "directives, identities, dependencies, and artifact handoffs when "
                        "available and authorized. Missing receipt telemetry alone does not "
                        "block host execution. Preserve every host and explicit row restriction. "
                        "Use an external adapter only when native delegation is unavailable; "
                        "do not switch hosts automatically. Do not hand-author telemetry or "
                        "claim validated execution from this rejected receipt. Retain actual "
                        "invocations, artifacts, and unvalidated evidence separately, and "
                        "record per-turn roster use with workforce.record_goal_turn."
                    ),
                },
            }
        return result

    if name in {"hephaestus_route", "hephaestus_cloud_search", "hephaestus_hub_invoke"}:
        from .networking.memory import unsafe_route_refusal

        unsafe = unsafe_route_refusal(str(arguments.get("request") or ""))
        if unsafe is not None:
            return unsafe

    host_model_policy: dict[str, Any] = {}
    if name in {"hephaestus_route", "model.resolve_allocation"}:
        try:
            host_model_policy = _host_model_allocation_policy()
        except ValueError as exc:
            # The validator already knows which field is wrong; discarding that
            # diagnosis makes a one-character policy typo indistinguishable from
            # any other, so the operator has to guess a field and restart the
            # host per guess. Every message raised by
            # _host_model_allocation_policy names only policy key names, never
            # their values, so it is safe to return. Collapse whitespace and cap
            # the length because unknown-field names come from operator JSON.
            reason = " ".join(str(exc).split())[:200] or "host model allocation policy is invalid"
            return {
                "action": "refuse" if name == "hephaestus_route" else name,
                "status": "invalid_host_model_allocation_policy",
                "reason": reason,
                "detail": (
                    f"{reason}. Fix {MODEL_ALLOCATION_POLICY_ENV} in the MCP "
                    "server launch environment."
                ),
            }

    if name == "model.resolve_allocation":
        stage = str(arguments.get("stage") or "").strip().lower()
        phase = canonical_phase_for_stage(stage)
        if phase is None:
            return {
                "action": name,
                "status": "invalid_invocation_stage",
                "executionAllowed": False,
            }
        inventory = arguments.get("session_inventory")
        if not isinstance(inventory, list):
            return {
                "action": name,
                "status": "invalid_session_inventory",
                "executionAllowed": False,
            }
        active = [
            item
            for item in inventory
            if isinstance(item, Mapping) and item.get("active") is True and item.get("available") is not False
        ]
        # MCP documents model and session_id separately. The legacy pure
        # allocator also accepts an ambiguous `id` shorthand; at this boundary
        # an id-only row must not become a fabricated model identifier.
        allocation_inventory = [
            {key: value for key, value in item.items() if key != "id"}
            if isinstance(item, Mapping) and not (item.get("model") or item.get("model_id"))
            else item
            for item in inventory
        ]
        active_session_ids = [
            str(
                item.get("session_id")
                or item.get("id")
                or item.get("model")
                or item.get("model_id")
                or "unknown-session"
            ).strip()[:160]
            for item in active[:20]
        ]
        if active:
            # One active row is a safe current-session fallback. Multiple active
            # rows are normal in hosts that keep orchestrator and worker sessions
            # live together, but they are not authority to guess which model the
            # operator intended. Let an exact role policy/parent decision resolve
            # first; only return ambiguity if the resolver still has no model.
            if len(active) == 1:
                current_model_id = str(
                    active[0].get("model")
                    or active[0].get("model_id")
                    or ""
                ).strip()
                if current_model_id:
                    host_model_policy.setdefault("currentModelId", current_model_id)
        raw_decision = arguments.get("decision")
        receipt = resolve_model_allocation(
            raw_decision,
            allocation_inventory,
            policy=host_model_policy,
            role=model_role_for_stage(stage),
            expected_phase=phase,
            escalation=arguments.get("escalation"),
        )
        response = {
            "action": name,
            "status": receipt["status"],
            "stage": stage,
            "phase": phase,
            "role": receipt["role"],
            "allocationReceipt": receipt,
            "usageStatus": "not-observed-before-invocation",
            "executionAllowed": bool(receipt["resolved"].get("modelId")),
        }
        effective_policy, _ = _policy_for_role(host_model_policy, receipt["role"])
        ceiling = normalize_effort(effective_policy.get("maxEffort"))
        if response["executionAllowed"] and ceiling is not None:
            resolved = receipt["resolved"]
            effort = normalize_effort(resolved.get("effort"))
            matching = [
                item for item in allocation_inventory
                if isinstance(item, Mapping)
                and item.get("available") is not False
                and str(item.get("session_id") or item.get("id") or item.get("model") or item.get("model_id") or "").strip() == resolved.get("sessionId")
                and str(item.get("model") or item.get("model_id") or item.get("id") or "").strip() == resolved.get("modelId")
            ]
            advertised = matching[0].get("supported_efforts") if len(matching) == 1 else None
            supported = isinstance(advertised, list) and effort is not None and any(
                normalize_effort(value) == effort for value in advertised
            )
            within_ceiling = effort == ceiling or (
                effort in EFFORT_RANK and ceiling in EFFORT_RANK
                and EFFORT_RANK[effort] <= EFFORT_RANK[ceiling]
            )
            if not supported or not within_ceiling:
                response["executionAllowed"] = False
                response["status"] = "effort_policy_unverified"
                response["policyVerification"] = "effort_unverified"
        # Provider aliases inferred from a session id, family, or a default
        # label are not proof of an operator's explicit provider pin.  This
        # check applies only to that pin; unpinned host inheritance is unchanged.
        pinned_provider = effective_policy.get("pinnedProvider")
        if isinstance(pinned_provider, str) and pinned_provider.strip() and receipt["resolved"].get("modelId"):
            resolved = receipt["resolved"]
            matching = [
                item for item in allocation_inventory
                if isinstance(item, Mapping)
                and item.get("available") is not False
                and str(item.get("session_id") or item.get("id") or item.get("model") or item.get("model_id") or "").strip() == resolved.get("sessionId")
                and str(item.get("model") or item.get("model_id") or item.get("id") or "").strip() == resolved.get("modelId")
            ]
            advertised = matching[0].get("provider") if len(matching) == 1 else None
            observed = advertised.strip().lower() if isinstance(advertised, str) and advertised.strip() else None
            if observed != pinned_provider.strip().lower():
                resolved["provider"] = observed
                response["executionAllowed"] = False
                response["providerPolicyVerification"] = "unverified"
                if response["status"] != "effort_policy_unverified":
                    response["status"] = "provider_policy_unverified"
        ambiguous_reason = any("ambiguous" in code for code in receipt.get("reasonCodes", []))
        missing_choice = raw_decision is None and not effective_policy.get("pinnedModelId")
        if len(active) > 1 and not receipt["resolved"].get("modelId") and (ambiguous_reason or missing_choice):
            response.update(
                {
                    "status": "ambiguous_active_session",
                    "activeSessionIds": active_session_ids,
                    "repairable": True,
                    "detail": (
                        "Multiple host sessions are marked active and no exact role policy "
                        "or parent allocation decision selected one. Mark exactly one session "
                        f"active, or configure orchestrator/worker pinnedModelId in {MODEL_ALLOCATION_POLICY_ENV}, "
                        "then retry the same stage."
                    ),
                }
            )
        return response

    # Project-grounded legacy tools seed their working tree on first contact.
    # Workforce protocol calls, auth/status calls, and Context calls are not on
    # this path: the first two are project-content independent and Context owns
    # its explicit projectDir lifecycle in its handler below.
    bootstrap: dict[str, Any] | None = None
    _bootstrap_target = (
        str(arguments.get("project_dir") or ".")
        if name in _COMMON_PROJECT_BOOTSTRAP_TOOLS
        else None
    )
    if _bootstrap_target is not None:
        from .project_bootstrap import auto_bootstrap_enabled, maybe_ensure_project

        # A disabled optional bootstrap must leave the core tool usable, and it
        # must not consume this process's first-contact slot. If the owner turns
        # it on later, the next tool call can still perform the one-time seed.
        from .project_bootstrap import bootstrap_feature_dependencies

        bootstrap_enabled = auto_bootstrap_enabled(mcp=True)
        missing = bootstrap_feature_dependencies(mcp=True) if bootstrap_enabled else []
        if bootstrap_enabled and not missing and _claim_first_contact(_bootstrap_target):
            bootstrap = maybe_ensure_project(
                _bootstrap_target,
                reason=f"mcp:{name}",
                enabled=True,
                allow_unmarked_current_root=True,
                enforce_feature_preferences=True,
                mcp=True,
            )
            if bootstrap.get("error") == "feature_dependencies_disabled":
                # Preferences can change after preflight; retry on a later call.
                try:
                    key = str(Path(_bootstrap_target).expanduser().resolve())
                except (OSError, ValueError):
                    key = _bootstrap_target
                _FIRST_CONTACT_ROOTS.discard(key)
                bootstrap = None

    if bootstrap is not None:
        status = bootstrap.get("status")
        safe_warning = (
            status == "privacy_warning"
            and bootstrap.get("privacyBlockInstalled") is True
            and bootstrap.get("privateModeCompliant") is True
            and int(bootstrap.get("missingCount") or 0) == 0
            and int(bootstrap.get("permissionIssueCount") or 0) == 0
        )
        if status != "active" and not safe_warning:
            detail = bootstrap.get("detail") or "project_bootstrap_incomplete"
            return {
                "action": "project_bootstrap",
                "status": "blocked",
                "detail": detail,
                "project_bootstrap": bootstrap,
            }

    def with_bootstrap(result: dict[str, Any]) -> dict[str, Any]:
        result = compact_routing_result(result)
        if bootstrap is not None:
            result["project_bootstrap"] = compact_project_receipt(bootstrap)
        return result

    def compact_project_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Keep MCP context results actionable without echoing local diagnostics."""

        code_map = receipt.get("codeMap") if isinstance(receipt.get("codeMap"), Mapping) else {}
        functional = (
            code_map.get("functionalSitemap")
            if isinstance(code_map.get("functionalSitemap"), Mapping)
            else {}
        )
        return {
            "action": "project_bootstrap",
            "status": receipt.get("status"),
            "privateModeCompliant": receipt.get("privateModeCompliant"),
            "privacyBlockInstalled": receipt.get("privacyBlockInstalled"),
            "missingCount": int(receipt.get("missingCount") or len(receipt.get("missing") or [])),
            "permissionIssueCount": int(
                receipt.get("permissionIssueCount") or len(receipt.get("permissionIssues") or [])
            ),
            "warningCount": len(receipt.get("warnings") or []),
            "trackedSensitivePathCount": int(
                receipt.get("trackedSensitivePathCount")
                or len(receipt.get("trackedSensitivePaths") or [])
            ),
            "codeMap": {
                "coverageComplete": code_map.get("coverageComplete"),
                "refresh": code_map.get("refresh"),
                "mapFingerprint": functional.get("mapFingerprint"),
            },
        }

    def compact_routing_result(result: Mapping[str, Any]) -> dict[str, Any]:
        """Keep discovery menus bounded while preserving exact candidate rows."""

        payload = dict(result)
        omissions = dict(payload.get("omissions") or {})

        def trim(container: dict[str, Any], field: str, limit: int, label: str) -> None:
            value = container.get(field)
            if not isinstance(value, list):
                return
            container[field] = value[:limit]
            if len(value) > limit:
                omissions[label] = len(value) - limit

        trim(payload, "candidates", 10, "candidates")
        trim(payload, "suggestions", 10, "suggestions")
        hub = payload.get("hub")
        if isinstance(hub, Mapping):
            compact_hub = dict(hub)
            trim(compact_hub, "results", 10, "hub.results")
            payload["hub"] = compact_hub
        if omissions:
            payload["omissions"] = omissions
        return payload

    if name == "goal.strategy":
        from .goal_strategy import service as goal_service

        action = arguments.get("action")
        payload = arguments.get("payload") if isinstance(arguments.get("payload"), dict) else {}
        project = arguments.get("projectDir") if isinstance(arguments.get("projectDir"), str) else ""
        goal_id = arguments.get("goalId") if isinstance(arguments.get("goalId"), str) else ""
        key = arguments.get("key") if isinstance(arguments.get("key"), str) else None
        try:
            if action == "schema":
                return {"action": name, **goal_service.contracts()}
            if not project.strip():
                return {"action": name, "status": "error", "error": "project_required"}
            if action == "start":
                return {"action": name, **goal_service.start(project, str(arguments.get("goalText") or ""), payload, key=key)}
            if not goal_id:
                return {"action": name, "status": "error", "error": "goal_id_required"}
            routes = {
                "plan_op": lambda: goal_service.plan_op(project, goal_id, payload, key=key),
                "kpi_define": lambda: goal_service.kpi_define(project, goal_id, payload, key=key),
                "kpi_sample": lambda: goal_service.kpi_sample(project, goal_id, payload, key=key),
                "review": lambda: goal_service.review(project, goal_id, payload or None, key=key),
                "owner_answer": lambda: goal_service.owner_answer(project, goal_id, str(payload.get("answer") or ""), str(payload.get("note") or ""), key=key),
                "status": lambda: goal_service.status(project, goal_id),
                "refresh": lambda: goal_service.refresh(project, goal_id),
                "context": lambda: {"goal_id": goal_id, "mode": goal_service.mode(), "context": goal_service.context(project, goal_id)},
            }
            if action not in routes:
                return {"action": name, "status": "error", "error": "action_invalid"}
            return {"action": name, **routes[str(action)]()}
        except (goal_service.GoalError, ValueError, OSError) as exc:
            return {"action": name, "status": "error", "error": getattr(exc, "code", type(exc).__name__), "detail": str(exc)[:400]}

    if name in {
        "context.refresh",
        "context.locate",
        "context.refs",
        "context.slice",
        "context.impact",
        "context.verify",
    }:
        from .context_map import (
            ContextMapError,
            context_error_remedy,
            context_slice,
            impact,
            locate,
            references,
            render_context_slice,
            verify_impact,
        )
        from .project_bootstrap import ensure_context_map, context_project_status
        from .feature_preferences import feature_enabled

        project_dir = arguments.get("projectDir")
        if not isinstance(project_dir, str) or not project_dir.strip():
            return {"action": name, "status": "error", "error": "context_project_invalid"}
        try:
            project_root = Path(project_dir).expanduser().resolve(strict=True)
            if not project_root.is_dir() or project_root.is_symlink():
                return {"action": name, "status": "error", "error": "context_project_invalid"}
            context_map_enabled = feature_enabled("context-map")
            automatic_refresh_requested = name != "context.refresh" and "refresh" not in arguments
            explicit_refresh_requested = name == "context.refresh" or arguments.get("refresh") is True
            if not context_map_enabled and (explicit_refresh_requested or (automatic_refresh_requested and not (project_root / ".agentlas").is_dir())):
                return {
                    "action": name,
                    "status": "disabled",
                    "error": "feature_disabled",
                    "feature": "context-map",
                    "writeAttempted": False,
                }
            # context.refresh creates project state, so a model-named folder is
            # bootstrapped only inside the host-approved roots (the same
            # boundary as first-contact bootstrap) or when already initialized.
            if name == "context.refresh" and not (project_root / ".agentlas").is_dir():
                from .project_bootstrap import _within_auto_boundary

                if not _within_auto_boundary(project_root):
                    return {"action": name, "status": "refused", "reason": "context_refresh_outside_boundary"}
            if name != "context.refresh" and not (project_root / ".agentlas").is_dir():
                return {
                    "action": name,
                    "status": "error",
                    "error": "project_not_initialized",
                    "hint": (
                        "This folder has no project map yet, and read-only context tools never create project state. "
                        "Call context.refresh once for this projectDir (it creates the map inside the host-approved folders), then repeat this call; "
                        "if context.refresh refuses the folder, carry on without the Context Map."
                    ),
                    "repairable": True,
                }
            # Omitted refresh means "automatic once if stale" at the MCP
            # adapter. Explicit false preserves the strict passive/no-write
            # contract used by audits and hooks; explicit true forces refresh.
            # Omitted refresh normally allows one automatic rebuild on stale
            # state. Standalone hosts keep that path passive unless the user or
            # host explicitly enables Context Map generation.
            auto_refresh = automatic_refresh_requested and context_map_enabled
            refresh = name == "context.refresh" or arguments.get("refresh") is True
            if refresh:
                project_receipt = ensure_context_map(project_root, force=name == "context.refresh" and arguments.get("force") is True, mcp=True)
                if project_receipt.get("status") == "disabled":
                    return {**project_receipt, "action": name}
            else:
                project_receipt = {
                    **context_project_status(project_root),
                    "action": "project_status",
                    "reason": f"mcp:{name}",
                    "writeAttempted": False,
                }
            if project_receipt.get("status") not in {"active", "privacy_warning"}:
                code_map_receipt = (
                    project_receipt.get("codeMap")
                    if isinstance(project_receipt.get("codeMap"), dict)
                    else {}
                )
                if code_map_receipt.get("coverageComplete") is False:
                    return {
                        "action": name,
                        "status": "error",
                        "error": "context_refresh_incomplete",
                        # Reached before the ContextMapError handler, so the
                        # remedy is attached here too.
                        "detail": context_error_remedy("context_refresh_incomplete"),
                        "project_bootstrap": compact_project_receipt(project_receipt),
                    }
                return {
                    "action": name,
                    "status": "blocked",
                    "error": "project_bootstrap_incomplete",
                    "project_bootstrap": compact_project_receipt(project_receipt),
                }
            def run_context_operation(refresh_value: bool) -> dict[str, Any]:
                if name == "context.locate":
                    return locate(
                        project_dir,
                        str(arguments.get("query") or ""),
                        refresh=refresh_value,
                    )
                if name == "context.refs":
                    return references(
                        project_dir,
                        str(arguments.get("symbol") or ""),
                        refresh=refresh_value,
                    )
                if name == "context.slice":
                    value = context_slice(
                        project_dir,
                        str(arguments.get("task") or ""),
                        targets=arguments.get("targets") or [],
                        refresh=refresh_value,
                    )
                    if arguments.get("render") is True:
                        value["rendered"] = render_context_slice(value)
                    return value
                if name == "context.impact":
                    return impact(
                        project_dir,
                        arguments.get("changed") or [],
                        refresh=refresh_value,
                    )
                return verify_impact(
                    project_dir,
                    arguments.get("changed") or [],
                    arguments.get("reviewed") or [],
                    verified=arguments.get("verified") or [],
                    waived=arguments.get("waived") or [],
                    refresh=refresh_value,
                )

            if name == "context.refresh":
                result = {
                    "action": name,
                    "status": "ok",
                    "refresh": project_receipt.get("codeMap") or {},
                }
            else:
                try:
                    result = run_context_operation(False)
                    if auto_refresh:
                        result["autoRefreshed"] = False
                except ContextMapError as exc:
                    if (
                        automatic_refresh_requested
                        and not context_map_enabled
                        and exc.code in {
                            "context_map_stale",
                            "context_freshness_incomplete",
                            "context_verification_refresh_required",
                        }
                    ):
                        return {
                            "action": name,
                            "status": "disabled",
                            "error": "feature_disabled",
                            "feature": "context-map",
                            "writeAttempted": False,
                        }
                    if not auto_refresh or exc.code not in {
                        "context_map_stale",
                        "context_freshness_incomplete",
                        "context_verification_refresh_required",
                    }:
                        raise
                    project_receipt = ensure_context_map(project_root, mcp=True)
                    if project_receipt.get("status") not in {"active", "privacy_warning"}:
                        return {**project_receipt, "action": name}
                    result = run_context_operation(False)
                    result["autoRefreshed"] = True
            result["project_bootstrap"] = compact_project_receipt(project_receipt)
            return compact_context_result(name, result)
        except ContextMapError as exc:
            if exc.code == "context_verification_refresh_required":
                return {
                    "action": name,
                    "status": "error",
                    "error": exc.code,
                    "detail": (
                        "context.verify requires a fresh dependency map. "
                        "Call context.verify again with refresh=true."
                    ),
                    "repairable": True,
                    "retryArguments": {"refresh": True},
                }
            if exc.code in {"context_map_stale", "context_freshness_incomplete"}:
                return {
                    "action": name,
                    "status": "error",
                    "error": exc.code,
                    "detail": (
                        "Passive context reads refuse stale or unverified indexes. "
                        "Call the same tool again with refresh=true."
                    ),
                    "repairable": True,
                    "retryArguments": {"refresh": True},
                }
            if exc.code == "context_changed_target_excluded_by_policy":
                return {
                    "action": name,
                    "status": "error",
                    "error": exc.code,
                    "detail": (
                        "The target exists but agentlas-context-map.json excludes its root. "
                        "Remove that narrow exclusion when the file must participate in impact verification; "
                        "the next default Context Map call will auto-refresh it."
                    ),
                    "repairable": True,
                }
            # Every remaining code reaches the caller through here. Without the
            # remedy this returned a bare `{"error": "<code>"}`, which is where
            # `context.slice` dead-ended for a caller that had no CLI to fall
            # back to.
            payload = {"action": name, "status": "error", "error": exc.code}
            remedy = context_error_remedy(exc.code)
            if remedy:
                payload["detail"] = remedy
            return payload
        except (OSError, TimeoutError, ValueError):
            return {"action": name, "status": "error", "error": "context_operation_failed"}

    # A standalone read of an uninitialized roster must not create auth,
    # networking directories, or a SQLite store. Desktop keeps its existing
    # initialization behavior. The status is explicit because another process
    # may initialize the store after this observation.
    if name in {"workforce.goal_context", "workforce.goal_runtime"}:
        from .feature_preferences import _DESKTOP_HOSTS
        host = str(os.environ.get("AGENTLAS_HOST_RUNTIME") or "").strip().lower()
        if host not in _DESKTOP_HOSTS:
            from .workforce.goal_binding import (
                WORKFORCE_GOAL_CONTEXT_SCHEMA, WorkforceGoalBindingError,
                _assert_goal_id, _project_identity, default_goal_store_path,
            )
            store_path = default_goal_store_path()
            try:
                store_path.lstat()
            except FileNotFoundError:
                try:
                    project_dir = arguments.get("projectDir")
                    if not isinstance(project_dir, str):
                        raise WorkforceGoalBindingError("workforce_goal_project_unavailable")
                    project_key, _ = _project_identity(project_dir)
                    goal_id = arguments.get("goalId")
                    if isinstance(goal_id, str):
                        _assert_goal_id(goal_id)
                except (OSError, ValueError, WorkforceGoalBindingError) as exc:
                    return {"action": name, "status": "error",
                            "error": getattr(exc, "code", "workforce_goal_binding_failed")}
                if name == "workforce.goal_runtime":
                    return {"schemaVersion": "agentlas.workforce-goal-runtime-context.v1",
                            "status": "not-bound", "storageState": "not_initialized", "goals": []}
                context = {
                    "schemaVersion": WORKFORCE_GOAL_CONTEXT_SCHEMA,
                    "accountPartition": None,
                    "projectKey": project_key,
                    "status": "not_initialized",
                    "goals": [],
                    "continuityPolicy": {
                        "terminalOnlyOnExplicitCompletion": True,
                        "leaseExpiryDoesNotCompleteGoal": True,
                        "reuseRosterBeforeRecruitment": True,
                        "recruitmentIsAdditive": True,
                        "standbyMeansBoundNotContinuouslyExecuting": True,
                    },
                }
                projected = context if arguments.get("fullDossier") is True else _goal_context_projection(
                    context, known_revisions=arguments.get("knownRevisions"))
                return _goal_context_model_policy(projected)
            except OSError:
                return {"action": name, "status": "error", "error": "workforce_goal_store_unavailable"}
            if store_path.is_symlink():
                return {"action": name, "status": "error", "error": "workforce_goal_store_unsafe"}

    init_networking(networking_home())
    if name in {
        "workforce.bind_goal",
        "workforce.goal_context",
        "workforce.goal_runtime",
        "workforce.record_goal_turn",
        "workforce.complete_goal",
    }:
        from .workforce.goal_binding import WorkforceGoalBindingError, WorkforceGoalStore

        try:
            store = WorkforceGoalStore()
            project_dir = arguments.get("projectDir")
            if not isinstance(project_dir, str):
                raise WorkforceGoalBindingError("workforce_goal_project_unavailable")
            if name == "workforce.bind_goal":
                preparation = arguments.get("preparation")
                if not isinstance(preparation, Mapping):
                    raise WorkforceGoalBindingError("workforce_goal_preparation_not_ready")
                labels = arguments.get("rosterLabels")
                return store.bind(
                    goal_id=str(arguments.get("goalId") or ""),
                    project_dir=project_dir,
                    preparation=preparation,
                    goal_label=(
                        str(arguments["goalLabel"])
                        if isinstance(arguments.get("goalLabel"), str)
                        else None
                    ),
                    roster_labels=labels if isinstance(labels, Mapping) else None,
                )
            if name == "workforce.goal_context":
                goal_id = arguments.get("goalId")
                context = store.context(
                    project_dir=project_dir,
                    goal_id=str(goal_id) if isinstance(goal_id, str) else None,
                    include_terminal=arguments.get("includeTerminal") is True,
                )
                if arguments.get("fullDossier") is True:
                    return _goal_context_model_policy(context)
                return _goal_context_model_policy(_goal_context_projection(
                    context,
                    known_revisions=arguments.get("knownRevisions"),
                ))
            if name == "workforce.goal_runtime":
                goal_id = arguments.get("goalId")
                return goal_runtime_execution_contract(store.runtime_context(
                    project_dir=project_dir,
                    goal_id=str(goal_id) if isinstance(goal_id, str) else None,
                ))
            if name == "workforce.record_goal_turn":
                return store.record_turn(
                    goal_id=str(arguments.get("goalId") or ""),
                    project_dir=project_dir,
                    turn_id=str(arguments.get("turnId") or ""),
                    decision=str(arguments.get("decision") or ""),
                    used_roster_keys=arguments.get("usedRosterKeys") or [],
                    local_skill_ids=arguments.get("localSkillIds") or [],
                    gap_codes=arguments.get("gapCodes") or [],
                    host_runtime=(
                        str(arguments["hostRuntime"])
                        if isinstance(arguments.get("hostRuntime"), str)
                        else None
                    ),
                )
            return store.complete(
                goal_id=str(arguments.get("goalId") or ""),
                project_dir=project_dir,
                explicit_completion=arguments.get("explicitCompletion") is True,
                status=str(arguments.get("status") or "completed"),
                reason=str(arguments.get("reason") or "explicit-host-goal-terminal"),
            )
        except (OSError, sqlite3.Error, WorkforceGoalBindingError, ValueError) as exc:
            from .workforce.package_adapter import refusal_fields

            code = getattr(exc, "code", "workforce_goal_binding_failed")
            if name == "workforce.record_goal_turn" and code == "workforce_goal_active_binding_not_found":
                # Recording a turn needs a roster bound to the goal in this project. With none there is nothing to record and nothing went
                # wrong: say so calmly instead of an error the model reads as a failure of the turn.
                return {
                    "action": name,
                    "status": "skipped",
                    "reason": code,
                    "detail": (
                        "No roster is bound to this goal in this project, so there is nothing to record. Carry on; "
                        "workforce.prepare_execution binds a roster when one is needed."
                    ),
                }
            return {
                "action": name,
                "status": "error",
                "error": code,
                **refusal_fields(exc),
            }
    if name == "workforce.expand_candidates":
        # 읽기 전용 — 핀된 메뉴에서 shortlist 서수의 풀카드를 되돌려준다.
        # 선택·랭킹·변형 없음이라 경계 검사 대상이 아니고, 세션 해석 실패는
        # 그 사유(만료·없음)를 그대로 말한다.
        from .workforce.federation_store import FederationSessionError, FederationSessionStore

        session_id = str(arguments.get("selectionSessionId") or "").strip()
        try:
            stored = FederationSessionStore().get(session_id)
        except FederationSessionError as exc:
            return {
                "action": name,
                "status": "rejected",
                "error": str(getattr(exc, "args", ["federation_session_unavailable"])[0]),
                "repairable": True,
                "hint": "Run workforce.search_candidates again — a candidate set expires one hour after it is issued.",
                "hubCalls": 0,
            }
        expanded = _expand_candidates(stored, arguments.get("candidates") or [])
        return {"action": name, **expanded}
    if name == "workforce.preflight_work_order":
        from .workforce.federation_store import FederationSessionError, FederationSessionStore
        from .workforce.work_order_adapter import (
            WORKFORCE_WORK_ORDER_PREFLIGHT_SCHEMA,
            WorkOrderDraftError,
            compile_work_order_draft_with_report,
        )

        normalized_concepts: list[dict[str, str]] = []
        try:
            work_order, normalized_concepts = compile_work_order_draft_with_report(arguments)
            pin = FederationSessionStore().save_work_order_preflight(work_order)
        except WorkOrderDraftError as exc:
            return {
                "action": name,
                "schemaVersion": WORKFORCE_WORK_ORDER_PREFLIGHT_SCHEMA,
                "status": "rejected",
                "error": exc.code,
                "repairable": True,
                "mutation": "none",
                "workOrderDigest": None,
                "issueCount": len(exc.issues),
                "issues": exc.issues,
                "hubCalls": 0,
            }
        except FederationSessionError as exc:
            return {
                "action": name,
                "schemaVersion": WORKFORCE_WORK_ORDER_PREFLIGHT_SCHEMA,
                "status": "error",
                "error": exc.code,
                "repairable": True,
                "hubCalls": 0,
            }
        return {
            "action": name,
            "schemaVersion": WORKFORCE_WORK_ORDER_PREFLIGHT_SCHEMA,
            **{key: value for key, value in pin.items() if key != "status"},
            "status": "accepted",
            "pinStatus": pin.get("status"),
            **(
                {
                    "normalizedConcepts": normalized_concepts,
                    "normalizedConceptNote": (
                        "Core rewrote these authored phrases into schema-valid concept ids. "
                        "Discovery matched on the rewritten values."
                    ),
                }
                if normalized_concepts
                else {}
            ),
            "slotBindings": [
                {
                    "roleOrdinal": index,
                    "slotId": slot.get("slotId"),
                    "title": slot.get("title"),
                }
                for index, slot in enumerate(work_order.get("roleSlots") or [], start=1)
                if isinstance(slot, Mapping)
            ],
            "hubCalls": 0,
        }
    if name in {
        "workforce.search_candidates",
        "workforce.validate_selection",
        "workforce.prepare_execution",
    }:
        from .workforce import validate_hub_selection_boundary, validate_hub_work_order_boundary
        from .networking.hub_client import call_hub_tool
        from .workforce.federation_store import FederationSessionError, FederationSessionStore
        from .workforce.provenance import (
            FederatedProvenanceError,
            prepare_federated_execution_plan,
            validate_federated_host_selection,
        )
        from .workforce.source_service import WorkforceSourceError, WorkforceSourceService
        from .workforce.goal_binding import (
            WorkforceGoalBindingError,
            WorkforceGoalStore,
            resolve_continuity_goal_id,
        )

        if name == "workforce.prepare_execution":
            try:
                arguments = _restore_prepared_selection_reference(arguments)
            except FederationSessionError as exc:
                return {
                    "action": name,
                    "status": "rejected",
                    "error": exc.code,
                    "repairable": True,
                    "hubCalls": 0,
                    "hint": (
                        "Pass selection={selectionSessionId} and federatedSelectionDigest from the same "
                        "accepted validate_selection result. If its exact choice cannot be restored, "
                        "resend the original decision or exact Selection; expired sessions require a new search."
                    ),
                }

        # Agentlas OS is the canonical Workforce entrypoint. Core owns source
        # federation plus deterministic governance/provenance validation; the
        # active host LLM alone authors the staffing decision. Privacy checks
        # are local, non-mutating, and complete before the first outbound byte.
        # Normalize at extraction (absent slot list fields -> []) so every
        # downstream digest, validation and match sees one canonical form —
        # an author that omits an empty field and one that spells [] are
        # byte-identical from here on.
        work_order = normalize_work_order(arguments.get("workOrder"))
        if name == "workforce.search_candidates":
            work_order_ref = arguments.get("workOrderRef")
            if isinstance(work_order_ref, str) and work_order_ref.strip():
                try:
                    pinned_work_order = normalize_work_order(
                        FederationSessionStore().preflight_work_order(work_order_ref.strip())
                    )
                except FederationSessionError as exc:
                    return {
                        "action": name,
                        "status": "rejected",
                        "error": exc.code,
                        "repairable": True,
                        "hubCalls": 0,
                        "hint": "Run workforce.preflight_work_order again; WorkOrder references expire after one hour.",
                    }
                if isinstance(work_order, Mapping) and canonical_digest(work_order) != canonical_digest(pinned_work_order):
                    return {
                        "action": name,
                        "status": "rejected",
                        "error": "work_order_reference_conflict",
                        "repairable": True,
                        "hubCalls": 0,
                    }
                work_order = pinned_work_order
        if not isinstance(work_order, Mapping) and name != "workforce.search_candidates":
            """★workOrder 에코도 의례였다 — 저장본이 항상 권위다.

            validate/prepare 는 받은 workOrder 를 신뢰하지 않는다:
            assert_work_order_binding 이 세션에 핀된 저장본을 꺼내 **바이트 동일**을
            요구한다(federation_store.py:439). 즉 호스트가 보낼 수 있는 유일하게
            유효한 값은 저장본과 같은 바이트뿐이고, 그렇다면 안 보내도 된다.
            search 가 핀해 둔 workOrder 를 세션 id 로 해석한다 — federatedSelection
            digest 참조·candidateSet resolve-by-session 과 같은 결이다. search 는
            제외한다: 그때는 아직 핀할 저장본이 없다.
            """
            selection_argument = arguments.get("selection")
            decision_argument = arguments.get("decision")
            pinned_session = (
                (
                    selection_argument.get("selectionSessionId")
                    if isinstance(selection_argument, Mapping)
                    else None
                )
                or (
                    decision_argument.get("selectionSessionId")
                    if isinstance(decision_argument, Mapping)
                    else None
                )
                or arguments.get("selectionSessionId")
            )
            if isinstance(pinned_session, str) and pinned_session.strip():
                try:
                    work_order = normalize_work_order(
                        FederationSessionStore().work_order(pinned_session.strip())
                    )
                except FederationSessionError as exc:
                    # 진짜 사유를 삼키지 않는다 — "워크오더가 이상함"이 아니라
                    # "그 세션이 없음/만료됨"이 호스트가 고칠 수 있는 사실이다.
                    return {
                        "action": name,
                        "status": "rejected",
                        "error": str(getattr(exc, "args", ["federation_session_unavailable"])[0]),
                        "repairable": True,
                        "hubCalls": 0,
                        "detail": {
                            "hint": (
                                "the session-pinned workOrder could not be resolved — start a fresh "
                                "search_candidates, or send the workOrder explicitly"
                            ),
                        },
                    }
        if not isinstance(work_order, Mapping):
            return {
                "action": name,
                "status": "rejected",
                "error": "work_order_hub_boundary_rejected",
                "repairable": True,
                "hubCalls": 0,
                "boundary": {
                    "schemaVersion": "agentlas.workforce-hub-boundary.v1",
                    "status": "rejected",
                    "repairable": True,
                    "mutation": "none",
                    "workOrderDigest": None,
                    "issues": [{"path": "workOrder", "code": "hub_work_order_invalid"}],
                },
            }
        boundary = validate_hub_work_order_boundary(work_order)
        if boundary["status"] != "accepted":
            compact_boundary = _compact_boundary(boundary)
            return {
                "action": name,
                "status": "rejected",
                "error": "work_order_hub_boundary_rejected",
                "repairable": True,
                "hubCalls": 0,
                # The full public catalog is already declared once in the tool
                # contract. Echoing it on every refusal added no repair signal.
                "boundary": compact_boundary,
            }
        prepare_project_dir: str | None = None
        prepare_goal_id: str | None = None
        if name == "workforce.prepare_execution":
            project_dir_value = arguments.get("projectDir")
            if not isinstance(project_dir_value, str) or not project_dir_value.strip():
                return {
                    "action": name,
                    "status": "rejected",
                    "error": "workforce_goal_project_required",
                    "repairable": True,
                    "hubCalls": 0,
                }
            prepare_project_dir = project_dir_value
            try:
                prepare_goal_id = resolve_continuity_goal_id(
                    project_dir=prepare_project_dir,
                    work_order=work_order,
                    requested_goal_id=(
                        str(arguments["goalId"])
                        if isinstance(arguments.get("goalId"), str)
                        else None
                    ),
                )
            except WorkforceGoalBindingError as exc:
                from .workforce.package_adapter import refusal_fields

                return {
                    "action": name,
                    "status": "rejected",
                    "error": exc.code,
                    "repairable": True,
                    "hubCalls": 0,
                    **refusal_fields(exc),
                }
        source_scope = arguments.get("sourceScope")
        expand_slot_ids: list[str] = []
        if name == "workforce.search_candidates":
            if source_scope is None:
                return {
                    "action": name,
                    "status": "rejected",
                    "error": "workforce_source_scope_required",
                    "repairable": True,
                    "hubCalls": 0,
                }
            if source_scope is not None and source_scope not in {"network", "local", "cloud", "hub"}:
                return {
                    "action": name,
                    "status": "rejected",
                    "error": "workforce_source_scope_invalid",
                    "repairable": True,
                    "hubCalls": 0,
                }
            raw_expand_slot_ids = arguments.get("expandSlotIds", [])
            work_order_slots = {
                str(slot.get("slotId"))
                for slot in work_order.get("roleSlots") or []
                if isinstance(slot, Mapping) and isinstance(slot.get("slotId"), str)
            }
            if (
                not isinstance(raw_expand_slot_ids, list)
                or len(raw_expand_slot_ids) > 32
                or any(not isinstance(item, str) or item not in work_order_slots for item in raw_expand_slot_ids)
                or len(raw_expand_slot_ids) != len(set(raw_expand_slot_ids))
            ):
                return {
                    "action": name,
                    "status": "rejected",
                    "error": "workforce_expand_slots_invalid",
                    "repairable": True,
                    "hubCalls": 0,
                }
            expand_slot_ids = list(raw_expand_slot_ids)
        if name == "workforce.search_candidates":
            try:
                search_result = WorkforceSourceService(
                    circuit_key=_workforce_circuit_key(arguments, work_order)
                ).search(
                    work_order,
                    source_scope=str(source_scope),
                    expand_slot_ids=list(expand_slot_ids),
                )
            except (WorkforceSourceError, ValueError) as exc:
                return {
                    "action": name,
                    "status": "error",
                    "error": getattr(exc, "code", "workforce_source_search_failed"),
                }
            # Default is the bounded shortlist menu. The
            # session store holds the full original text, so validation/
            # preparation pin-matching loses nothing. A legacy caller can ask
            # for menu.v2 with shortlist=false or the original full dossier.
            if arguments.get("fullDossier") is True:
                return search_result
            if arguments.get("shortlist") is not False:
                return _shortlist_projection(_menu_projection(search_result))
            return _menu_projection(search_result)
        if name != "workforce.search_candidates":
            candidate_set = arguments.get("candidateSet")
            selection = arguments.get("selection")
            decision_draft = arguments.get("decision")
            if selection is None and isinstance(decision_draft, Mapping):
                from .workforce.work_order_adapter import (
                    WorkOrderDraftError,
                    compile_selection_draft,
                )

                pinned_digest = ""
                session_hint = str(decision_draft.get("selectionSessionId") or "").strip()
                if session_hint:
                    try:
                        pinned = FederationSessionStore().get(session_hint)
                        pinned_set = pinned.get("candidateSet") if isinstance(pinned, Mapping) else None
                        if isinstance(pinned_set, Mapping):
                            pinned_digest = str(pinned_set.get("candidateSetDigest") or "")
                    except (FederationSessionError, OSError, sqlite3.Error, ValueError):
                        pinned_digest = ""
                if not pinned_digest:
                    return {
                        "action": name,
                        "status": "rejected",
                        "error": "federation_session_unavailable",
                        "repairable": True,
                        "hubCalls": 0,
                        "hint": "Run workforce.search_candidates again — a candidate set expires one hour after it is issued.",
                    }
                try:
                    selection = compile_selection_draft(
                        decision_draft, candidate_set_digest=pinned_digest
                    )
                except WorkOrderDraftError as exc:
                    return {
                        "action": name,
                        "status": "rejected",
                        "error": exc.code,
                        "repairable": True,
                        "hubCalls": 0,
                        "issueCount": len(exc.issues),
                        "issues": exc.issues,
                    }
            federation_result = arguments.get("federationResult")
            federated_selection = arguments.get("federatedSelection")
            # Resolve the federation result from its selectionSessionId. The
            # store revalidates digest and expiry without requiring full echo.
            if not isinstance(federation_result, Mapping):
                pinned_session = (
                    selection.get("selectionSessionId")
                    if isinstance(selection, Mapping)
                    else None
                ) or arguments.get("selectionSessionId")
                if isinstance(pinned_session, str) and pinned_session.strip():
                    try:
                        # Build the store here rather than reading the enclosing
                        # `store` name. `_call_tool` binds `store` twice — a
                        # WorkforceGoalStore on the goal branch above, and the
                        # FederationSessionStore further down — which makes it a
                        # function-local that is UNBOUND on this path, so every
                        # resolve-by-session attempt raised UnboundLocalError.
                        # That is not a FederationSessionError, so the except
                        # below never caught it and the whole call crashed: this
                        # entire branch has never once succeeded. It is the only
                        # escape from echoing a ~461KB candidate set back, so the
                        # size problem it was written to solve stayed unsolved.
                        federation_result = FederationSessionStore().get(pinned_session.strip())
                    except FederationSessionError as exc:
                        return {
                            "action": name,
                            "status": "rejected",
                            "error": str(getattr(exc, "args", ["federation_session_unavailable"])[0]),
                            "repairable": True,
                            "hubCalls": 0,
                        }
            if not isinstance(candidate_set, Mapping) and isinstance(federation_result, Mapping):
                stored_set = federation_result.get("candidateSet")
                if isinstance(stored_set, Mapping):
                    candidate_set = stored_set
            # Ordinal resolution — lets a candidate be specified by its menu
            # ordinal instead of hand-copying a 48-hex ID. Resolves it against
            # the stored (or submitted) menu into the exact release ID, into
            # canonical shape, and only then passes it on to deep validation.
            # A resolution failure is refused, with no silent substitute.
            #
            # This is applied to prepare too. While it was validate-only, a
            # caller who got an "accepted" verdict by ordinal, then passed the
            # same selection to prepare, was refused with a missing
            # assignments[0].agentReleaseId plus a candidateOrdinal
            # additionalProperties error (measured). validate does not return
            # the canonical shape, so the caller had no way to recover.
            if (
                name in ("workforce.validate_selection", "workforce.prepare_execution")
                and isinstance(selection, Mapping)
                and isinstance(candidate_set, Mapping)
                and any(
                    isinstance(row, Mapping) and "candidateOrdinal" in row
                    for row in selection.get("assignments", []) or []
                )
            ):
                resolved_selection, ordinal_error, ordinal_detail = _resolve_ordinal_assignments(
                    selection, candidate_set
                )
                if ordinal_error is not None:
                    return {
                        "action": name,
                        "status": "rejected",
                        "error": ordinal_error,
                        "repairable": True,
                        "hubCalls": 0,
                        # Say which assignment, what was given, and what would be
                        # accepted. Without this the caller only learns that it was
                        # wrong, which is exactly what it already knew.
                        **({"detail": ordinal_detail} if ordinal_detail else {}),
                    }
                selection = resolved_selection
            # Name the argument that is actually wrong. This check covers two
            # unrelated mistakes and used to report both as `selection` /
            # `schema_type`: a caller who omitted the candidate set — or the
            # `federationResult` it is derived from — was told its selection had
            # the wrong type, so it rewrote a correct selection over and over.
            # Measured 2026-07-28: two different host models each burned several
            # attempts on this, one of them abandoning the network path entirely.
            shape_issues: list[dict[str, str]] = []
            if not isinstance(candidate_set, Mapping):
                shape_issues.append({
                    "path": "candidateSet",
                    "code": "missing_or_not_object",
                    "detail": (
                        "pass the candidateSet from the search response, or pass federationResult "
                        "and Core will take the candidate set from it; alternatively pass only "
                        "selection.selectionSessionId and Core resolves the set it already holds"
                    ),
                })
            if not isinstance(selection, Mapping):
                shape_issues.append({
                    "path": "selection",
                    "code": "missing_or_not_object",
                    "detail": "selection must be the agentlas.workforce-selection.v1 object itself",
                })
            if shape_issues:
                return {
                    "action": name,
                    "status": "rejected",
                    "error": "selection_hub_boundary_rejected",
                    "repairable": True,
                    "hubCalls": 0,
                    "boundary": {
                        "schemaVersion": "agentlas.workforce-selection-hub-boundary.v1",
                        "status": "rejected",
                        "repairable": True,
                        "mutation": "none",
                        "selectionDigest": None,
                        "issues": shape_issues,
                        "issueCount": len(shape_issues),
                    },
                }
            federated_candidate_set = (
                federation_result.get("candidateSet")
                if isinstance(federation_result, Mapping)
                and isinstance(federation_result.get("candidateSet"), Mapping)
                else None
            )
            boundary_candidate_set = federated_candidate_set or candidate_set
            selection_boundary = validate_hub_selection_boundary(
                selection,
                work_order=work_order,
                candidate_set=boundary_candidate_set,
            )
            if selection_boundary["status"] != "accepted":
                return {
                    "action": name,
                    "status": "rejected",
                    "error": "selection_hub_boundary_rejected",
                    "repairable": True,
                    "hubCalls": 0,
                    "boundary": _compact_boundary(selection_boundary),
                }
            if not isinstance(federation_result, Mapping):
                return {
                    "action": name,
                    "status": "rejected",
                    "error": "federation_result_required",
                    "repairable": True,
                    "hubCalls": 0,
                }
            if federation_result is not None or federated_selection is not None:
                if (
                    not isinstance(federated_candidate_set, Mapping)
                    or any(
                        candidate_set.get(field) != federated_candidate_set.get(field)
                        for field in (
                            "schemaVersion", "selectionSessionId", "candidateSetDigest",
                            "workOrderId", "ontologyVersion",
                        )
                    )
                ):
                    return {
                        "action": name,
                        "status": "rejected",
                        "error": "federated_candidate_set_mismatch",
                        "repairable": True,
                        "hubCalls": 0,
                    }
                store = FederationSessionStore()
                try:
                    if name == "workforce.validate_selection":
                        if federated_selection is not None:
                            return {
                                "action": name,
                                "status": "rejected",
                                "error": "federated_selection_not_allowed_during_validation",
                                "repairable": True,
                                "hubCalls": 0,
                            }
                        wrapper = validate_federated_host_selection(
                            selection,
                            federation_result=federation_result,
                            work_order=work_order,
                            session_store=store,
                        )
                        return _with_unmet_requirement_notice(wrapper)
                    if not isinstance(federated_selection, Mapping):
                        """★참조 해석 — wrapper 에코는 정보 0의 왕복세다.

                        prepare 는 오랫동안 accepted wrapper **전체**를 되돌려 받기를
                        요구했는데, Core 는 받자마자 자기 저장소의 같은 wrapper 를
                        digest 로 꺼내 바이트 대조만 한다(provenance.py:303,
                        source_service.py:867). 즉 에코된 본문은 한 번도 신뢰된 적이
                        없다 — 저장본이 항상 권위다. 그렇다면 호스트가 증명해야 할
                        것은 "어느 accepted 결정을 실행하려는가" 하나이고, 그것은
                        digest 로 충분하다. validate 의 resolve-by-session 과 같은
                        결이며, 결합 검증은 저장소 get_federated_selection 이
                        그대로 수행한다(디이제스트 불일치는 여전히 거절).
                        """
                        supplied_digest = arguments.get("federatedSelectionDigest")
                        pinned_session = (
                            selection.get("selectionSessionId")
                            if isinstance(selection, Mapping)
                            else None
                        ) or (
                            candidate_set.get("selectionSessionId")
                            if isinstance(candidate_set, Mapping)
                            else None
                        )
                        if (
                            isinstance(supplied_digest, str)
                            and supplied_digest.strip()
                            and isinstance(pinned_session, str)
                            and pinned_session.strip()
                        ):
                            try:
                                federated_selection = store.get_federated_selection(
                                    pinned_session.strip(),
                                    supplied_digest.strip(),
                                )
                            except FederationSessionError as exc:
                                return {
                                    "action": name,
                                    "status": "rejected",
                                    "error": str(
                                        getattr(exc, "args", ["federated_selection_not_pinned"])[0]
                                    ),
                                    "repairable": True,
                                    "hubCalls": 0,
                                }
                    if not isinstance(federated_selection, Mapping):
                        return {
                            "action": name,
                            "status": "rejected",
                            "error": "federated_selection_required",
                            "repairable": True,
                            "hubCalls": 0,
                            "detail": {
                                "hint": (
                                    "send federatedSelectionDigest from the accepted validate_selection "
                                    "result — Core resolves the pinned wrapper from its session store; "
                                    "echoing the full federatedSelection object is also accepted"
                                ),
                            },
                        }
                    # prepareAttempt's idempotencyKey is the canonical sha256
                    # of the entire payload — a value a host LLM cannot
                    # compute by hand (the Terminal runner computes it in
                    # code). On the MCP host path, when it's not supplied,
                    # Core derives it from the same material — the exact
                    # WorkOrder / resolved Selection's canonical digest, plus
                    # federatedSelection's received digest and source pins.
                    # occurrenceId is derived from selectionSessionId, so a
                    # retry within the same session lands on the same key and
                    # idempotency is preserved. A supplied prepareAttempt is
                    # matched and validated as-is (no weakening).
                    prepare_attempt = arguments.get("prepareAttempt")
                    if prepare_attempt is None:
                        from .workforce.prepare_cache import prepare_attempt_payload

                        pinned_rows = federated_selection.get("selectedSourcePins")
                        session_ref = federated_selection.get("selectionSessionId")
                        if isinstance(pinned_rows, list) and isinstance(session_ref, str):
                            try:
                                prepare_attempt = prepare_attempt_payload(
                                    f"occurrence:{session_ref.strip()}",
                                    work_order_digest=canonical_digest(work_order),
                                    selection_digest=canonical_digest(selection),
                                    federated_selection_digest=str(
                                        federated_selection.get("federatedSelectionDigest") or ""
                                    ),
                                    selected_source_pin_digests=[
                                        str(row.get("sourcePinDigest") or "")
                                        if isinstance(row, Mapping)
                                        else ""
                                        for row in pinned_rows
                                    ],
                                )
                            except Exception:
                                # A derivation failure is left for the
                                # existing required-argument validation path
                                # to refuse honestly, with no silent substitute.
                                prepare_attempt = None
                    service = WorkforceSourceService(
                        session_store=store,
                        circuit_key=_workforce_circuit_key(arguments, work_order),
                    )
                    source_bundles = service.fetch_selected_runtime_bundles(
                        federated_selection,
                        work_order=work_order,
                        selection=selection,
                        prepare_attempt=prepare_attempt,
                    )
                    prepared_result = prepare_federated_execution_plan(
                        work_order=work_order,
                        selection=selection,
                        federated_selection=federated_selection,
                        federation_result=federation_result,
                        source_runtime_bundles=source_bundles,
                        session_store=store,
                    )
                    # Project grounding is attached only after every remote
                    # source call and exact bundle verification has completed.
                    # It is never included in Hub/Cloud search, selection, or
                    # bundle-fetch payloads.
                    try:
                        from .context_map import RECALL_FRESHNESS_BUDGET_SECONDS, context_slice

                        prepared_result = {
                            **prepared_result,
                            "localContextSlice": compact_context_result(
                                "context.slice",
                                context_slice(
                                    str(prepare_project_dir),
                                    str(work_order.get("taskBrief") or ""),
                                    **PREPARE_CONTEXT_SLICE_READ,
                                    freshness_budget_seconds=RECALL_FRESHNESS_BUDGET_SECONDS,
                                ),
                            ),
                            "localContextBoundary": {
                                "networkTransfer": "denied",
                                "scope": "project-local",
                                "inheritance": "all-selected-workers",
                            },
                        }
                    except Exception as exc:
                        prepared_result = {
                            **prepared_result,
                            "localContextSliceStatus": "unavailable",
                            "localContextSliceCode": str(getattr(exc, "code", "") or type(exc).__name__),
                        }
                    # Core's local grounding is part of the artifact cached by
                    # bind. Seal the verified producer result after enrichment;
                    # never reseal a cached preparation when reading it.
                    prepared_result["federatedPreparationDigest"] = canonical_digest({
                        key: value for key, value in prepared_result.items()
                        if key != "federatedPreparationDigest"
                    })
                    if not _workforce_preparation_ready(prepared_result):
                        return _workforce_preparation_refusal(name, prepared_result)
                    try:
                        goal_binding = WorkforceGoalStore().bind(
                            goal_id=str(prepare_goal_id),
                            project_dir=str(prepare_project_dir),
                            preparation=prepared_result,
                            goal_label="automatic Workforce continuity",
                            roster_labels=_roster_labels_from_session(selection),
                        )
                    except (OSError, sqlite3.Error, WorkforceGoalBindingError, ValueError) as exc:
                        # This catch — not the goal-command handlers — is where a
                        # tombstoned implicit goal actually fires (audit round 6:
                        # the remediation added at the raise site never reached
                        # the wire because this dict is assembled by hand).
                        from .workforce.package_adapter import refusal_fields

                        return {
                            "action": name,
                            "status": "error",
                            "error": getattr(exc, "code", "workforce_goal_binding_failed"),
                            "executionAllowed": False,
                            "preparedButUnbound": True,
                            **refusal_fields(exc),
                        }
                    final_result = {**prepared_result, "goalBinding": goal_binding}
                    # 투영은 명시 옵트인(fullDossier=False)이다. search 와 달리
                    # prepare 소비자에는 행 전체로 bundleDigest 를 재계산하는 구
                    # 데스크탑 검증자가 있고, 런타임(~/.agentlas)과 데스크탑은
                    # 서로 독립적으로 업데이트되므로 기본값을 바꾸면 "신 런타임 +
                    # 구 데스크탑" 스큐에서 편성이 죽는다. 정본 명령이 호스트에게
                    # fullDossier:false 를 가르치므로 호스트는 다이어트를 받는다.
                    if arguments.get("fullDossier") is False:
                        return _preparation_projection(final_result)
                    return final_result
                except (FederatedProvenanceError, WorkforceSourceError, ValueError) as exc:
                    # Third route to the same code-only refusal, this one on the
                    # borrow side: `local_registry.runtime_bundle` re-hashes the
                    # staged package, so a `PackageAdaptationError` reaches this
                    # generic `ValueError` arm and the host was handed a bare
                    # `source_missing`/`source_secret_material_forbidden` token
                    # with the sentence explaining it discarded. Wire codes still
                    # answer as codes; only errors that wrote extra words add any.
                    from .workforce.package_adapter import refusal_fields

                    failure = {
                        "action": name,
                        "status": "error",
                        "error": getattr(exc, "code", "federated_workforce_invalid"),
                        **refusal_fields(exc),
                    }
                    retry_after_ms = getattr(exc, "retry_after_ms", None)
                    receipt_expires_at = getattr(exc, "receipt_expires_at", None)
                    if isinstance(retry_after_ms, int) and not isinstance(retry_after_ms, bool):
                        failure["retryAfterMs"] = max(100, min(10_000, retry_after_ms))
                    if isinstance(receipt_expires_at, str) and receipt_expires_at:
                        failure["receiptExpiresAt"] = receipt_expires_at
                    return failure
        remote_result = call_hub_tool(name, arguments)
        if name != "workforce.prepare_execution":
            return remote_result
        try:
            from .context_map import RECALL_FRESHNESS_BUDGET_SECONDS, context_slice

            remote_result = {
                **remote_result,
                "localContextSlice": compact_context_result(
                    "context.slice",
                    context_slice(
                        str(prepare_project_dir),
                        str(work_order.get("taskBrief") or ""),
                        **PREPARE_CONTEXT_SLICE_READ,
                        freshness_budget_seconds=RECALL_FRESHNESS_BUDGET_SECONDS,
                    ),
                ),
                "localContextBoundary": {
                    "networkTransfer": "denied",
                    "scope": "project-local",
                    "inheritance": "all-selected-workers",
                },
            }
        except Exception as exc:
            remote_result = {
                **remote_result,
                "localContextSliceStatus": "unavailable",
                "localContextSliceCode": str(getattr(exc, "code", "") or type(exc).__name__),
            }
        if remote_result.get("schemaVersion") == WORKFORCE_FEDERATED_PREPARATION_SCHEMA:
            remote_result["federatedPreparationDigest"] = canonical_digest({
                key: value for key, value in remote_result.items()
                if key != "federatedPreparationDigest"
            })
        if not _workforce_preparation_ready(remote_result):
            return _workforce_preparation_refusal(name, remote_result)
        try:
            goal_binding = WorkforceGoalStore().bind(
                goal_id=str(prepare_goal_id),
                project_dir=str(prepare_project_dir),
                preparation=remote_result,
                goal_label="automatic Workforce continuity",
                roster_labels=_roster_labels_from_session(selection),
            )
        except (OSError, sqlite3.Error, WorkforceGoalBindingError, ValueError) as exc:
            # Same firing path as the local branch above, remote leg.
            from .workforce.package_adapter import refusal_fields

            return {
                "action": name,
                "status": "error",
                "error": getattr(exc, "code", "workforce_goal_binding_failed"),
                "executionAllowed": False,
                "preparedButUnbound": True,
                **refusal_fields(exc),
            }
        final_remote = {**remote_result, "goalBinding": goal_binding}
        # 위 로컬 경로와 같은 이유로 명시 옵트인.
        if arguments.get("fullDossier") is False:
            return _preparation_projection(final_remote)
        return final_remote
    if name == "hephaestus_route":
        allow_local_routing = bool(arguments.get("allow_local_routing", False))
        hub_only = True if not allow_local_routing else bool(arguments.get("hub_only", False))
        if hub_only:
            from .networking.gui_shortcut import open_local_gui_shortcut

            shortcut = open_local_gui_shortcut(
                arguments["request"],
                no_open=os.environ.get("HEPHAESTUS_NETWORK_GUI_NO_OPEN") == "1",
            )
            if shortcut.get("action") != "no_local_gui_shortcut":
                return with_bootstrap(shortcut)
        # `route --project X` reads X/.agentlas/work-brief.json; this tool takes
        # the same project_dir and used to ignore it, so the identical project
        # routed brief-shaped on the CLI and brief-less over MCP, with nothing
        # in either result saying which one the host got. One router, one
        # contract: discover the brief here too, and when the file exists but
        # cannot be used, ride the reason back instead of dropping it.
        work_brief, brief_warning = _project_work_brief(arguments.get("project_dir", "."))
        decision = route_request(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            use_hub=True,
            hub_approved=bool(arguments.get("approve_hub", False)),
            hub_only=hub_only,
            caller_id=arguments.get("caller_id") or arguments.get("caller"),
            session_inventory=arguments.get("session_inventory") or None,
            model_allocation_decisions=arguments.get("model_allocation_decisions") or None,
            # Cost ceilings and pins are host policy, never caller-controlled
            # MCP arguments. Unknown legacy arguments are intentionally ignored.
            model_allocation_policy=host_model_policy or None,
            work_brief=work_brief,
        )
        if brief_warning:
            decision["work_brief_warning"] = brief_warning
        return with_bootstrap(decision)
    if name == "hephaestus_cloud_search":
        # Owner-scoped: scope="cloud" implies hub_only inside route_request and
        # queries only the signed-in user's OWN cloud packages.
        # This routes, so it owes the same Work Brief contract as
        # hephaestus_route / `route --scope cloud`: same project_dir, same
        # brief, same reason on the way back when the brief cannot be used.
        work_brief, brief_warning = _project_work_brief(arguments.get("project_dir", "."))
        decision = route_request(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            use_hub=True,
            hub_approved=False,
            scope="cloud",
            work_brief=work_brief,
        )
        if brief_warning:
            decision["work_brief_warning"] = brief_warning
        return with_bootstrap(decision)
    if name == "hephaestus_search":
        from .networking import search_agents

        return with_bootstrap(search_agents(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            limit=int(arguments.get("limit") or 10),
        ))
    if name == "hephaestus_call":
        from .networking import call_agents

        return with_bootstrap(call_agents(
            arguments.get("agents") or [],
            str(arguments.get("context") or ""),
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            version=str(arguments.get("version") or "latest"),
            local_inventory=arguments.get("local_inventory") or [],
        ))
    if name == "hephaestus_hub_invoke":
        from .networking.hub_invocation import invoke_hub_agent

        # Hub invocation picks its agent from a real route, so the brief that
        # shapes hephaestus_route must shape this one too — otherwise the same
        # project yields brief-shaped candidates through one tool and
        # brief-less candidates through the other, and the agent that actually
        # runs is the one chosen without the user's anti_scope.
        work_brief, brief_warning = _project_work_brief(arguments.get("project_dir", "."))
        decision = route_request(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            use_hub=True,
            hub_approved=bool(arguments.get("approve_hub", False)),
            hub_only=True,
            work_brief=work_brief,
        )
        requested_slug = arguments.get("slug")
        exact_slug = requested_slug.strip() if isinstance(requested_slug, str) else ""
        # A borrowed agent's memory files and soul appends stay under the
        # host's hub-agents drawer; a model-supplied path elsewhere is ignored
        # in favour of the per-agent default.
        requested_memory_root = arguments.get("memory_root")
        memory_root = None
        if requested_memory_root:
            from .networking.bootstrap import hub_agents_dir

            try:
                inside = (
                    Path(str(requested_memory_root)).expanduser().resolve()
                    .is_relative_to(hub_agents_dir().expanduser().resolve())
                )
            except (OSError, RuntimeError, ValueError):
                inside = False
            memory_root = requested_memory_root if inside else None
        invocation = invoke_hub_agent(
            arguments["request"],
            slug=exact_slug or None,
            hub_decision=decision,
            project_dir=arguments.get("project_dir", "."),
            memory_root=memory_root,
            version=str(arguments.get("version") or "latest"),
            local_inventory=arguments.get("local_inventory") or [],
        )
        if invocation.get("status") == "selection_required":
            invocation["routing_decision"] = decision
        if brief_warning:
            invocation["work_brief_warning"] = brief_warning
        if requested_memory_root and memory_root is None:
            invocation["memory_root_ignored"] = True
        return with_bootstrap(invocation)
    if name == "agentlas_resolve_plugins":
        from .plugin_discovery import resolve_plugins

        need = str(arguments.get("need") or "").strip()
        if not need:
            return {"error": "missing_need", "message": "need is required — one sentence describing the missing capability."}
        return resolve_plugins(
            need,
            arguments.get("project_dir") or ".",
            use_hub=arguments.get("use_hub") is not False,
        )
    if name == "agentlas_tool_search":
        from .plugin_discovery import tool_search

        need = str(arguments.get("need") or "").strip()
        if not need:
            return {"error": "missing_need", "message": "need is required — one sentence describing the action."}
        return tool_search(
            need,
            arguments.get("project_dir") or ".",
            limit=int(arguments.get("limit") or 4),
            forbid_destructive=arguments.get("forbid_destructive") is True,
        )
    if name == "hephaestus_network_status":
        return network_status()
    if name == "agentlas_auth_status":
        from .auth import AgentlasAuthError, auth_status, normalize_base_url
        from .networking.hub_client import hub_url

        base_url = arguments.get("base_url")
        # Renew an aged-out access token from the saved grant before answering,
        # so a saved sign-in does not read as signed out after an idle hour or
        # an update. Only for the configured hub: a model-supplied base_url
        # stays a pure local read, like agentlas_authenticate refuses it.
        renew = True
        if base_url:
            try:
                renew = normalize_base_url(str(base_url)) == normalize_base_url(hub_url())
            except AgentlasAuthError:
                renew = False
        return auth_status(base_url, refresh=renew)
    if name == "agentlas_authenticate":
        from .auth import AgentlasAuthError, ensure_access_token, normalize_base_url, token_path
        from .networking.hub_client import hub_url

        base_url = arguments.get("base_url")
        # The host configuration decides which origin a sign-in may open, never
        # the tool payload: a model-supplied base_url would make Core fetch that
        # host's OAuth metadata and open whatever authorization_endpoint it names.
        if base_url:
            try:
                foreign = normalize_base_url(str(base_url)) != normalize_base_url(hub_url())
            except AgentlasAuthError:
                foreign = True
            if foreign:
                return {
                    "action": "agentlas_authenticate",
                    "status": "error",
                    "error": "auth_base_url_not_configured",
                }
        try:
            token = ensure_access_token(
                str(base_url) if base_url else None,
                interactive=True,
                open_browser=arguments.get("open_browser", True) is not False,
                timeout_seconds=int(arguments.get("timeout_seconds") or 180),
            )
        except AgentlasAuthError as exc:
            return {
                "action": "agentlas_authenticate",
                "status": "error",
                "error": str(exc),
                "token_path": str(token_path(str(base_url) if base_url else None)),
            }
        return {
            "action": "agentlas_authenticate",
            "status": "authenticated" if token else "signed_out",
            "token_path": str(token_path(str(base_url) if base_url else None)),
        }
    raise UnknownToolError(name)


from .prompt_composition import mcp_initialize_instructions_for_runtime


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method", "")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if msg_id is None:
        return None  # notification (e.g. notifications/initialized) — no response

    if method == "initialize":
        client = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
        _CLIENT_NAME[0] = str(client.get("name") or "")[:60]
        return _result(
            msg_id,
            {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": SERVER_INFO,
                "instructions": mcp_initialize_instructions_for_runtime(),
            },
        )
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": _available_tools()})
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            payload = _call_tool(name, arguments)
            # Serialized inside the error boundary: a value JSON cannot encode
            # becomes this tool's error, never an exception that ends the server.
            payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except UnknownToolError:
            return _error(msg_id, -32602, f"unknown tool: {name}")
        except Exception as exc:  # surfaced as a tool error, not a protocol error
            # Name the exception type: a KeyError stringifies to the bare key
            # ("'request'"), which reads like nothing at all and used to be
            # mislabeled as an unknown tool. The tool exists and the call
            # failed — say that.
            return _result(
                msg_id,
                {
                    "content": [{"type": "text", "text": _tool_failure_text(name, exc)}],
                    "isError": True,
                },
            )
        tool_result = {"content": [{"type": "text", "text": payload_text}]}
        if isinstance(payload, Mapping) and payload.get("status") in {
            "error",
            "rejected",
            "blocked",
            "failed",
            "effort_policy_unverified",
        }:
            # Keep the finite JSON payload intact while also honoring MCP's
            # application-error signal. Hosts can persist the exact code instead
            # of replacing it with a later generic schema failure.
            tool_result["isError"] = True
        return _result(msg_id, tool_result)
    return _error(msg_id, -32601, f"method not found: {method}")


def _tool_failure_text(name: str, exc: BaseException) -> str:
    """Compose failure facts from this host's effective configuration.

    Feature ON is not an updater receipt; no scheduling/completion is inferred.
    """
    from .feature_preferences import feature_enabled
    from .prompt_composition import tool_failure_text

    return tool_failure_text(name=name, exc=exc,
                             auto_update_enabled=feature_enabled("auto-update"))


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> int:
    # Wire the resident judge to the host's connected model when the host opted
    # in via AGENTLAS_JUDGE_RUNTIME; otherwise judged sites stay honestly
    # unavailable rather than keyword-deciding.
    from .judgment_bootstrap import install_judgment_from_env

    install_judgment_from_env()
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    output_lock = threading.Lock()
    stopped = threading.Event()
    initialized = threading.Event()

    def send(message: dict[str, Any]) -> None:
        with output_lock:
            stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
            stdout.flush()

    # Track the last advertised inventory, not merely the last poll. A quick
    # ON/list/OFF between polls must still invalidate that advertised list.
    advertised = [_inventory_state()]

    def watch_inventory() -> None:
        while not stopped.wait(0.5):
            current = _inventory_state()
            with output_lock:
                if initialized.is_set() and current != advertised[0]:
                    advertised[0] = current
                    try:
                        stdout.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}) + "\n")
                        stdout.flush()
                    except (OSError, ValueError):
                        return

    watcher = threading.Thread(target=watch_inventory, name="feature-inventory", daemon=True)
    watcher.start()
    try:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            message = None
            try:
                message = json.loads(line)
            except ValueError:
                response: dict[str, Any] | None = _error(None, -32700, "parse error")
            else:
                # One malformed line must not end the server: every hephaestus tool
                # would be gone for the rest of the host session.
                if isinstance(message, list):
                    response = _error(None, -32600, "batch requests are not supported")
                elif not isinstance(message, dict):
                    response = _error(None, -32600, "invalid request")
                else:
                    try:
                        response = _handle(message)
                    except Exception as exc:
                        print(f"hephaestus mcp: internal error: {type(exc).__name__}", file=sys.stderr, flush=True)
                        response = _error(message["id"], -32603, "internal error") if message.get("id") is not None else None
            if response is not None:
                if isinstance(message, dict) and message.get("method") == "tools/list" and isinstance(response.get("result"), dict):
                    names = {tool.get("name") for tool in response["result"].get("tools", [])}
                    with output_lock:
                        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                        stdout.flush()
                        advertised[0] = (bool(names & _CONTEXT_MAP_TOOL_NAMES), bool(names & _MEMORY_GATED_TOOL_NAMES))
                else:
                    send(response)
            if isinstance(message, dict) and message.get("method") == "notifications/initialized":
                initialized.set()
    finally:
        stopped.set()
        watcher.join(timeout=1)
    return 0
