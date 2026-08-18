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
import os
import sqlite3
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .model_allocation import (
    EFFORT_TOKEN_RE,
    INVOCATION_STAGE_PHASES,
    canonical_phase_for_stage,
    model_role_for_stage,
    resolve_model_allocation,
)
from .workforce.contracts import (
    WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256,
    WORKFORCE_ONTOLOGY_VERSION,
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
from .workforce.provenance import (
    WORKFORCE_FEDERATED_PREPARATION_SCHEMA,
    WORKFORCE_FEDERATED_SELECTION_SCHEMA,
)

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "hephaestus-network", "version": "1.2.12"}

# Roots this process has already seeded, so only the first tool call in a
# session pays the bootstrap cost.
_FIRST_CONTACT_ROOTS: set[str] = set()


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
MODEL_ALLOCATION_POLICY_ENV = "AGENTLAS_MODEL_ALLOCATION_POLICY_JSON"
_HOST_MODEL_POLICY_FIELDS = frozenset({
    "pinnedModelId",
    "pinnedProvider",
    "maxTier",
    "maxEffort",
    "requiredCapabilities",
    "orchestrator",
    "worker",
})
_HOST_MODEL_ROLE_POLICY_FIELDS = frozenset({
    "pinnedModelId",
    "pinnedProvider",
    "maxTier",
    "maxEffort",
    "requiredCapabilities",
    "inherit",
})
WORKFORCE_PROTOCOL_VERSION = "2026-08-13.2"


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
        "codeMapSchemaVersion": "agentlas.code-map.v2",
        "contextSliceSchemaVersion": "agentlas.context-slice.v1",
        "contextImpactReceiptSchemaVersion": "agentlas.context-impact-receipt.v2",
        "contextVerificationReceiptSchemaVersion": "agentlas.context-verification-receipt.v2",
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
    third time only spends the host's context. Measured on the live surface:
    the workOrder schema alone is 8,144 bytes and appeared three times.

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
    Hand-copying a 48-hex ID is a measured error surface (2026-07-28: 1 of 12
    qwen attempts truncated the ID).
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


_MENU_AUDIT_FIELDS = ("qualificationEvidence", "packageHash", "contentDigest")

# Heavyweight fields inside semanticSnapshot. This is where a card stuffs a
# whole sentence slugified into an artifact ID, so a single candidate can
# carry dozens of them — and since candidates never overlap, comparing them is
# not even possible in the first place (measured live, 1 slot with 10
# candidates: 0% of 365 unique `produces` values shared by 2+ candidates, 0 of
# 149 for `consumes`). The same content is already in the summaries as one
# sentence, and actual matching is done by Core against the session store's
# original data. So the menu keeps only the count.
_MENU_SNAPSHOT_HEAVY_FIELDS = ("produces", "consumes")


def _menu_projection(result: dict[str, Any]) -> dict[str, Any]:
    """Projects a search response into a decision-ready summary menu — a
    drop-list approach.

    Instead of enumerating what to keep, it drops only the audit-weight
    fields: if an agent attribute (card schema) is added or renamed, the new
    field passes through automatically. Core's session store holds the full
    original text, and validation/preparation pin-matching is performed
    against that original data, so no control is lost.
    Measured (1 slot, 10 candidates): 41,216B -> about 22KB, zero loss of
    decision-relevant information.

    This projection is MCP-surface only. The Terminal runner asserts the
    semanticSnapshot key set at exactly 9 keys
    (agentlas-workforce.cjs assertExactKeys), so applying the same folding on
    Core's shared path would make that side die with candidate_set_invalid.
    """
    projected = {key: value for key, value in result.items() if key != "candidateProvenance"}
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
                        if isinstance(value, list):
                            snapshot.pop(field)
                            snapshot[f"{field}Count"] = len(value)
                    candidate["semanticSnapshot"] = snapshot
                candidates.append(candidate)
            slot["candidates"] = candidates
            slots.append(slot)
        candidate_set["slots"] = slots
        candidate_set["projection"] = "menu.v1"
        projected["candidateSet"] = candidate_set
    return projected


def _resolve_ordinal_assignments(
    selection: Mapping[str, Any],
    candidate_set: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolves each assignment's candidateOrdinal against the stored menu into an exact release ID.

    Returns: (selection normalized to canonical shape, None) or (None, a
    refusal code). If both an ordinal and a release ID were given and they
    disagree, this refuses rather than silently picking one.
    """
    slots_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for slot in candidate_set.get("slots", []) or []:
        if isinstance(slot, Mapping):
            slots_by_id[str(slot.get("slotId"))] = list(slot.get("candidates", []) or [])
    resolved = dict(selection)
    assignments = []
    for assignment in selection.get("assignments", []) or []:
        if not isinstance(assignment, Mapping):
            return None, "selection_assignment_invalid"
        assignment = dict(assignment)
        ordinal = assignment.pop("candidateOrdinal", None)
        if ordinal is not None:
            candidates = slots_by_id.get(str(assignment.get("slotId")))
            if candidates is None:
                return None, "ordinal_slot_not_in_menu"
            if not isinstance(ordinal, int) or not 1 <= ordinal <= len(candidates):
                return None, "ordinal_out_of_range"
            release_id = (candidates[ordinal - 1] or {}).get("agentReleaseId")
            if not isinstance(release_id, str) or not release_id:
                return None, "ordinal_candidate_unresolvable"
            existing = assignment.get("agentReleaseId")
            if isinstance(existing, str) and existing and existing != release_id:
                return None, "ordinal_release_conflict"
            assignment["agentReleaseId"] = release_id
        assignments.append(assignment)
    resolved["assignments"] = assignments
    return resolved, None


def _host_model_allocation_policy() -> dict[str, Any]:
    """Read operator cost guardrails from the MCP process boundary.

    Tool arguments are untrusted workload input. They may carry a parent-AI
    allocation decision, but they must never raise the host's model/effort
    ceiling or forge a user pin. Operators configure this JSON in the MCP
    server launch environment instead.
    """

    raw = os.environ.get(MODEL_ALLOCATION_POLICY_ENV, "").strip()
    if not raw:
        # Fall back to the file `agentlas-one orch` writes. The env var is the
        # operator override and still wins; without this file the policy was
        # empty on every host because nobody hand-writes JSON into a launch
        # environment, so every worker silently inherited the orchestrator's
        # frontier model — the opposite of why the allocator exists.
        policy_file = Path(
            os.environ.get("AGENTLAS_ONE_DIR") or (Path.home() / ".agentlas" / "one")
        ) / "model-policy.json"
        try:
            raw = policy_file.read_text(encoding="utf-8").strip()
        except OSError:
            return {}
        if not raw:
            return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        # Keep the decoder's line/column so a trailing comma is locatable. The
        # decoder message carries a position, never the policy value itself.
        raise ValueError(f"invalid host model allocation policy JSON: {exc}") from None
    if not isinstance(parsed, Mapping):
        raise ValueError("host model allocation policy must be an object")
    unknown = sorted(set(parsed) - _HOST_MODEL_POLICY_FIELDS)
    if unknown:
        raise ValueError(f"host model allocation policy has unknown fields: {','.join(unknown)}")
    policy = {key: parsed[key] for key in _HOST_MODEL_POLICY_FIELDS if key in parsed}

    def validate_scope(value: Mapping[str, Any], label: str, *, allow_inherit: bool) -> dict[str, Any]:
        unknown = sorted(set(value) - _HOST_MODEL_ROLE_POLICY_FIELDS)
        if unknown:
            raise ValueError(f"host {label} model policy has unknown fields: {','.join(unknown)}")
        scoped = dict(value)
        if "inherit" in scoped:
            if not allow_inherit or not isinstance(scoped["inherit"], bool):
                raise ValueError(f"host {label} inherit flag is invalid")
            if scoped["inherit"] and set(scoped) != {"inherit"}:
                raise ValueError(f"host {label} inherit policy cannot also pin or clamp a model")
        pinned_model_id = scoped.get("pinnedModelId")
        if pinned_model_id is not None and (
            not isinstance(pinned_model_id, str)
            or not pinned_model_id.strip()
            or len(pinned_model_id) > 255
        ):
            raise ValueError(f"host {label} pinnedModelId is invalid")
        pinned_provider = scoped.get("pinnedProvider")
        if pinned_provider is not None and (
            not isinstance(pinned_provider, str)
            or not pinned_provider.strip()
            or len(pinned_provider) > 80
        ):
            raise ValueError(f"host {label} pinnedProvider is invalid")
        if scoped.get("maxTier") not in {None, "economy", "balanced", "frontier"}:
            raise ValueError(f"host {label} maxTier is invalid")
        scoped_max_effort = scoped.get("maxEffort")
        if scoped_max_effort is not None and (
            not isinstance(scoped_max_effort, str) or not EFFORT_TOKEN_RE.fullmatch(scoped_max_effort)
        ):
            raise ValueError(f"host {label} maxEffort is invalid")
        capabilities = scoped.get("requiredCapabilities")
        if capabilities is not None and (
            not isinstance(capabilities, list)
            or len(capabilities) > 32
            or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in capabilities)
        ):
            raise ValueError(f"host {label} requiredCapabilities is invalid")
        return scoped

    for role in ("orchestrator", "worker"):
        scoped = policy.get(role)
        if scoped is None:
            continue
        if not isinstance(scoped, Mapping):
            raise ValueError(f"host {role} model policy must be an object")
        policy[role] = validate_scope(scoped, role, allow_inherit=role == "worker")

    if "pinnedModelId" in policy and (
        not isinstance(policy["pinnedModelId"], str)
        or not policy["pinnedModelId"].strip()
        or len(policy["pinnedModelId"]) > 255
    ):
        raise ValueError("host pinnedModelId is invalid")
    if "pinnedProvider" in policy and (
        not isinstance(policy["pinnedProvider"], str)
        or not policy["pinnedProvider"].strip()
        or len(policy["pinnedProvider"]) > 80
    ):
        raise ValueError("host pinnedProvider is invalid")
    if policy.get("maxTier") not in {None, "economy", "balanced", "frontier"}:
        raise ValueError("host maxTier is invalid")
    top_level_max_effort = policy.get("maxEffort")
    if top_level_max_effort is not None and (
        not isinstance(top_level_max_effort, str) or not EFFORT_TOKEN_RE.fullmatch(top_level_max_effort)
    ):
        raise ValueError("host maxEffort is invalid")
    capabilities = policy.get("requiredCapabilities")
    if capabilities is not None and (
        not isinstance(capabilities, list)
        or len(capabilities) > 32
        or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in capabilities)
    ):
        raise ValueError("host requiredCapabilities is invalid")
    return policy

TOOLS: list[dict[str, Any]] = [
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
                            "tier": {"enum": ["economy", "balanced", "frontier"]},
                            "supported_efforts": {
                                "type": "array",
                                "items": {
                                    "enum": [
                                        "none",
                                        "minimal",
                                        "low",
                                        "medium",
                                        "high",
                                        "xhigh",
                                        "max",
                                    ]
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
            "for Claude Code, Codex, Gemini, and other Hephaestus Hub calls."
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
        "name": "workforce.search_candidates",
        "description": (
            "Search the Agent Workforce Ontology with a redacted structured work order. "
            "sourceScope=network federates Local, owner Cloud, and public Hub menus; exact "
            "local/cloud/hub values restrict discovery to that source. It never selects a team. "
            "The calling top-level LLM must author the work order and make the staffing decision."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workOrder": _contract_property(
                    "workOrder",
                    "Complete agentlas.workforce-work-order.v1; use the exact schema and graph version declared in x-agentlas-contract. Semantic role/community/skill/knowledge IDs are open-world English concepts; catalog values are seed examples, not an allowlist.",
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
            "required": ["workOrder", "sourceScope"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.validate_selection",
        "description": (
            "Validate a team selected by the calling host LLM against an exact candidate set. "
            "Core holds the federated session it issued, so send only selection.selectionSessionId "
            "and it loads the pinned menu itself — echoing a wide candidate set back does not fit "
            "in one call. It never sends the merged menu to a remote source or "
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
                "selection": _selection_property_with_ordinal(
                    "Complete agentlas.workforce-selection.v1 authored by the host LLM; use the exact canonical schema declared in x-agentlas-contract. Each assignment may name the candidate by candidateOrdinal from the menu instead of copying the 48-hex agentReleaseId — Core resolves the ordinal against its pinned menu.",
                ),
            },
            "required": ["workOrder", "selection"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.prepare_execution",
        "description": (
            "Fetch BYOM runtime bundles only for an already accepted exact roster. "
            "Pins agentReleaseId, packageHash, and contentDigest and fails closed on drift; "
            "it never chooses replacements. A successful preparation is atomically bound "
            "to durable work continuity; callers cannot opt out by omitting an explicit goal mode."
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
                "selection": _contract_echo_property(
                    "selection",
                    "The exact Selection already accepted by workforce.validate_selection. Send it back unchanged — Core revalidates it and fails closed on any drift from the accepted roster.",
                ),
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
                    "description": "Exact accepted result returned by federated workforce.validate_selection.",
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
            },
            "required": [
                "workOrder", "selection",
                "federatedSelection", "projectDir",
            ],
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
            "The binding survives turns, sessions, host restarts, and Hub lease expiry; "
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
            "roster plus local skills is sufficient or an additive recruitment is needed."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectDir": {"type": "string", "minLength": 1, "maxLength": 4096},
                "goalId": {"type": "string", "minLength": 1, "maxLength": 256},
                "includeTerminal": {"type": "boolean"},
            },
            "required": ["projectDir"],
        },
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.goal_runtime",
        "description": (
            "Load the exact locally cached prepared plans for an active account/project "
            "goal. Returns directives only while the recorded remote lease is still active; "
            "otherwise returns lease-refresh-required and no remote directive content."
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
            "This does not execute a model and does not create a Hub charge."
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
            "completion or cancellation. A model turn ending or a 24-hour lease expiring "
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
                    "default": False,
                    "description": "Explicitly rebuild project-local indexes. Passive reads never write and return context_map_stale instead of stale results.",
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
                    "default": False,
                    "description": "Explicitly rebuild project-local indexes. Passive reads never write and return context_map_stale instead of stale results.",
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
                    "default": False,
                    "description": "Explicitly rebuild project-local indexes. Passive reads never write and return context_map_stale instead of stale results.",
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
                    "default": False,
                    "description": "Explicitly rebuild project-local indexes. Passive reads never write and return context_map_stale instead of stale results.",
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
                    "default": False,
                    "description": "Explicitly rebuild project-local indexes. Omit for a passive, read-only lookup.",
                },
            },
            "required": ["projectDir", "changed"],
        },
    },
]


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


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
        return validate_execution_receipt(
            arguments["receipt"],
            execution_plan=arguments["executionPlan"],
            tool_inventory=arguments["toolInventory"],
            benchmark_mode=arguments.get("benchmarkMode") is True,
        )

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
            if isinstance(item, Mapping) and item.get("active") is True
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
                    or active[0].get("id")
                    or ""
                ).strip()
                if current_model_id:
                    host_model_policy.setdefault("currentModelId", current_model_id)
        raw_decision = arguments.get("decision")
        receipt = resolve_model_allocation(
            raw_decision,
            inventory,
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
        if len(active) > 1 and not response["executionAllowed"]:
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

    # Any Agentlas tool touching a folder is first contact with that project, so
    # the project map is seeded there regardless of which tool arrived first.
    # Bootstrapping is per-process/per-root: the first call pays for it, the rest
    # of the session skips it.
    bootstrap: dict[str, Any] | None = None
    _bootstrap_target = str(arguments.get("project_dir") or ".")
    if _claim_first_contact(_bootstrap_target):
        from .project_bootstrap import auto_bootstrap_enabled, maybe_ensure_project

        bootstrap = maybe_ensure_project(
            _bootstrap_target,
            reason=f"mcp:{name}",
            enabled=auto_bootstrap_enabled(mcp=True),
            allow_unmarked_current_root=True,
        )

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
            context_slice,
            impact,
            locate,
            references,
            render_context_slice,
            verify_impact,
        )
        from .project_bootstrap import ensure_project, project_status

        project_dir = arguments.get("projectDir")
        if not isinstance(project_dir, str) or not project_dir.strip():
            return {"action": name, "status": "error", "error": "context_project_invalid"}
        try:
            project_root = Path(project_dir).expanduser().resolve(strict=True)
            if not project_root.is_dir() or project_root.is_symlink():
                return {"action": name, "status": "error", "error": "context_project_invalid"}
            if name != "context.refresh" and not (project_root / ".agentlas").is_dir():
                return {
                    "action": name,
                    "status": "error",
                    "error": "project_not_initialized",
                    "hint": (
                        "Run `hephaestus project ensure --project <folder>` first. "
                        "Read-only context tools never create project state."
                    ),
                }
            # Reading context is passive by default.  Only an explicit
            # refresh=true authorizes rebuilding project-local indexes.
            refresh = name == "context.refresh" or arguments.get("refresh") is True
            if refresh:
                project_receipt = ensure_project(
                    project_root,
                    reason=f"mcp:{name}",
                    force_code_map=name == "context.refresh" and arguments.get("force") is True,
                )
            else:
                project_receipt = {
                    **project_status(project_root),
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
                        "project_bootstrap": compact_project_receipt(project_receipt),
                    }
                return {
                    "action": name,
                    "status": "blocked",
                    "error": "project_bootstrap_incomplete",
                    "project_bootstrap": compact_project_receipt(project_receipt),
                }
            if name == "context.refresh":
                result = {
                    "action": name,
                    "status": "ok",
                    "refresh": project_receipt.get("codeMap") or {},
                }
            elif name == "context.locate":
                # Deliberately NOT allow_stale: a tool call is an explicit ask,
                # and the passive contract is to report context_map_stale with
                # retryArguments so the caller can decide. That differs from the
                # recall hook, where the user is waiting and a labelled stale
                # map beats nothing.
                result = locate(project_dir, str(arguments.get("query") or ""), refresh=refresh)
            elif name == "context.refs":
                result = references(project_dir, str(arguments.get("symbol") or ""), refresh=refresh)
            elif name == "context.slice":
                result = context_slice(
                    project_dir,
                    str(arguments.get("task") or ""),
                    targets=arguments.get("targets") or [],
                    refresh=refresh,
                )
                if arguments.get("render") is True:
                    result["rendered"] = render_context_slice(result)
            elif name == "context.impact":
                result = impact(project_dir, arguments.get("changed") or [], refresh=refresh)
            else:
                result = verify_impact(
                    project_dir,
                    arguments.get("changed") or [],
                    arguments.get("reviewed") or [],
                    verified=arguments.get("verified") or [],
                    waived=arguments.get("waived") or [],
                    refresh=refresh,
                )
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
            return {"action": name, "status": "error", "error": exc.code}
        except (OSError, TimeoutError, ValueError):
            return {"action": name, "status": "error", "error": "context_operation_failed"}

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
                return store.context(
                    project_dir=project_dir,
                    goal_id=str(goal_id) if isinstance(goal_id, str) else None,
                    include_terminal=arguments.get("includeTerminal") is True,
                )
            if name == "workforce.goal_runtime":
                goal_id = arguments.get("goalId")
                return store.runtime_context(
                    project_dir=project_dir,
                    goal_id=str(goal_id) if isinstance(goal_id, str) else None,
                )
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
            return {
                "action": name,
                "status": "error",
                "error": getattr(exc, "code", "workforce_goal_binding_failed"),
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
            implicit_goal_id,
        )

        # Agentlas OS is the canonical Workforce entrypoint. Core owns source
        # federation plus deterministic governance/provenance validation; the
        # active host LLM alone authors the staffing decision. Privacy checks
        # are local, non-mutating, and complete before the first outbound byte.
        # Normalize at extraction (absent slot list fields -> []) so every
        # downstream digest, validation and match sees one canonical form —
        # an author that omits an empty field and one that spells [] are
        # byte-identical from here on.
        work_order = normalize_work_order(arguments.get("workOrder"))
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
            return {
                "action": name,
                "status": "rejected",
                "error": "work_order_hub_boundary_rejected",
                "repairable": True,
                "hubCalls": 0,
                "boundary": boundary,
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
                prepare_goal_id = implicit_goal_id(
                    work_order=work_order,
                    requested_goal_id=(
                        str(arguments["goalId"])
                        if isinstance(arguments.get("goalId"), str)
                        else None
                    ),
                )
            except WorkforceGoalBindingError as exc:
                return {
                    "action": name,
                    "status": "rejected",
                    "error": exc.code,
                    "repairable": True,
                    "hubCalls": 0,
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
            # Default is the decision-ready summary menu (projection). The
            # session store holds the full original text, so validation/
            # preparation pin-matching loses nothing. Only a caller that needs
            # the legacy full-echo flow gets the original shape via fullDossier=true.
            if arguments.get("fullDossier") is True:
                return search_result
            return _menu_projection(search_result)
        if name != "workforce.search_candidates":
            candidate_set = arguments.get("candidateSet")
            selection = arguments.get("selection")
            federation_result = arguments.get("federationResult")
            federated_selection = arguments.get("federatedSelection")
            # This process issued the federation result and still holds it, keyed
            # by the selectionSessionId printed on the menu. Requiring the caller
            # to echo the whole thing back made the contract unusable at the size
            # a good menu actually is: a live 80-candidate set is ~461KB, past
            # what one tool call can carry, and the digest is over the exact
            # bytes so it cannot be trimmed. The caller was left choosing between
            # a menu wide enough to contain the right agent and a menu small
            # enough to send back — measured on 2026-07-28, the intended pick
            # ranked 4th, so a 3-candidate menu would have cut the answer out.
            # Resolve it here instead; the store re-validates digest and expiry,
            # so nothing about the pin is weakened. The Hub already accepts a
            # session id this way (mcp/workforce.ts); Core simply had not.
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
                resolved_selection, ordinal_error = _resolve_ordinal_assignments(selection, candidate_set)
                if ordinal_error is not None:
                    return {
                        "action": name,
                        "status": "rejected",
                        "error": ordinal_error,
                        "repairable": True,
                        "hubCalls": 0,
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
                        "contract": workforce_contract_metadata("selection"),
                        "status": "rejected",
                        "repairable": True,
                        "mutation": "none",
                        "selectionDigest": None,
                        "issues": shape_issues,
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
                    "boundary": selection_boundary,
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
                        return validate_federated_host_selection(
                            selection,
                            federation_result=federation_result,
                            work_order=work_order,
                            session_store=store,
                        )
                    if not isinstance(federated_selection, Mapping):
                        return {
                            "action": name,
                            "status": "rejected",
                            "error": "federated_selection_required",
                            "repairable": True,
                            "hubCalls": 0,
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
                        from .context_map import context_slice

                        prepared_result = {
                            **prepared_result,
                            "localContextSlice": context_slice(
                                str(prepare_project_dir),
                                str(work_order.get("taskBrief") or ""),
                                refresh=True,
                            ),
                            "localContextBoundary": {
                                "networkTransfer": "denied",
                                "scope": "project-local",
                                "inheritance": "all-selected-workers",
                            },
                        }
                    except Exception:
                        prepared_result = {
                            **prepared_result,
                            "localContextSliceStatus": "unavailable",
                        }
                    if not _workforce_preparation_ready(prepared_result):
                        return _workforce_preparation_refusal(name, prepared_result)
                    try:
                        goal_binding = WorkforceGoalStore().bind(
                            goal_id=str(prepare_goal_id),
                            project_dir=str(prepare_project_dir),
                            preparation=prepared_result,
                            goal_label="automatic Workforce continuity",
                        )
                    except (OSError, sqlite3.Error, WorkforceGoalBindingError, ValueError) as exc:
                        return {
                            "action": name,
                            "status": "error",
                            "error": getattr(exc, "code", "workforce_goal_binding_failed"),
                            "executionAllowed": False,
                            "preparedButUnbound": True,
                        }
                    return {**prepared_result, "goalBinding": goal_binding}
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
            from .context_map import context_slice

            remote_result = {
                **remote_result,
                "localContextSlice": context_slice(
                    str(prepare_project_dir),
                    str(work_order.get("taskBrief") or ""),
                    refresh=True,
                ),
                "localContextBoundary": {
                    "networkTransfer": "denied",
                    "scope": "project-local",
                    "inheritance": "all-selected-workers",
                },
            }
        except Exception:
            remote_result = {**remote_result, "localContextSliceStatus": "unavailable"}
        if not _workforce_preparation_ready(remote_result):
            return _workforce_preparation_refusal(name, remote_result)
        try:
            goal_binding = WorkforceGoalStore().bind(
                goal_id=str(prepare_goal_id),
                project_dir=str(prepare_project_dir),
                preparation=remote_result,
                goal_label="automatic Workforce continuity",
            )
        except (OSError, sqlite3.Error, WorkforceGoalBindingError, ValueError) as exc:
            return {
                "action": name,
                "status": "error",
                "error": getattr(exc, "code", "workforce_goal_binding_failed"),
                "executionAllowed": False,
                "preparedButUnbound": True,
            }
        return {**remote_result, "goalBinding": goal_binding}
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
        invocation = invoke_hub_agent(
            arguments["request"],
            slug=exact_slug or None,
            hub_decision=decision,
            project_dir=arguments.get("project_dir", "."),
            memory_root=arguments.get("memory_root"),
            version=str(arguments.get("version") or "latest"),
            local_inventory=arguments.get("local_inventory") or [],
        )
        if invocation.get("status") == "selection_required":
            invocation["routing_decision"] = decision
        if brief_warning:
            invocation["work_brief_warning"] = brief_warning
        return with_bootstrap(invocation)
    if name == "hephaestus_network_status":
        return network_status()
    if name == "agentlas_auth_status":
        from .auth import auth_status

        return auth_status(arguments.get("base_url"))
    if name == "agentlas_authenticate":
        from .auth import AgentlasAuthError, ensure_access_token, token_path

        base_url = arguments.get("base_url")
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


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method", "")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if msg_id is None:
        return None  # notification (e.g. notifications/initialized) — no response

    if method == "initialize":
        return _result(
            msg_id,
            {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Agentlas Workforce continuity is mandatory, not an optional goal mode. "
                    "At the start of every nontrivial project turn call workforce.goal_context "
                    "for the current project. Reuse an active exact roster plus local skills "
                    "when sufficient; recruit only a real gap. workforce.prepare_execution "
                    "requires projectDir and automatically binds every successful preparation, "
                    "even when the user never said goal. Keep the roster until explicit whole-goal "
                    "completion/cancellation through workforce.complete_goal. Lease expiry affects "
                    "only the next server charge and never ends the binding. Once a concrete project "
                    "task is resolved, call context.slice; before mutating a path call context.impact; "
                    "before declaring completion call context.verify and account for every affected "
                    "file. Context Map source paths and contents stay project-local and must never be "
                    "sent in Network or Cloud discovery requests. "
                    # 도구 접근 고지 — Desktop shared/tool-access-notice.ts, 터미널
                    # engine/tools/access-notice.cjs와 **같은 규칙**이다. 이 세 표면이 다른
                    # 말을 하면 사용자는 어느 쪽이 맞는지 알 수 없다. 문구를 여기서만
                    # 바꾸지 말 것 — 세 벌을 함께 옮긴다.
                    "Before telling the user a capability is unavailable, call "
                    "agentlas_resolve_plugins with the capability you need: the Agentlas Hub "
                    "catalog covers integrations that are not installed on this machine yet, "
                    "and a tool missing from this session is not the same as a tool that does "
                    "not exist. Never install or enable a tool on your own — show the slug, "
                    "what it will be allowed to do, and whether it needs credentials, then let "
                    "the user decide. If nothing covers the need, say so plainly; do not "
                    "describe a tool call you did not make."
                ),
            },
        )
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            payload = _call_tool(name, arguments)
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
                    "content": [
                        {
                            "type": "text",
                            "text": f"hephaestus tool {name} failed: {type(exc).__name__}: {exc}",
                        }
                    ],
                    "isError": True,
                },
            )
        tool_result = {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, sort_keys=True)}]
        }
        if isinstance(payload, Mapping) and payload.get("status") in {
            "error",
            "rejected",
            "blocked",
            "failed",
        }:
            # Keep the finite JSON payload intact while also honoring MCP's
            # application-error signal. Hosts can persist the exact code instead
            # of replacing it with a later generic schema failure.
            tool_result["isError"] = True
        return _result(msg_id, tool_result)
    return _error(msg_id, -32601, f"method not found: {method}")


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> int:
    # Starting the local Agentlas MCP server is the host's explicit plugin
    # boundary. Default its project bootstrap gate on while preserving an
    # operator's explicit 0/false override. maybe_ensure_project still confines
    # writes to the MCP process workspace and refuses unsafe home/root targets.
    from .project_bootstrap import MCP_AUTO_BOOTSTRAP_ENV

    os.environ.setdefault(MCP_AUTO_BOOTSTRAP_ENV, "1")
    # Wire the resident judge to the host's connected model when the host opted
    # in via AGENTLAS_JUDGE_RUNTIME; otherwise judged sites stay honestly
    # unavailable rather than keyword-deciding.
    from .judgment_bootstrap import install_judgment_from_env

    install_judgment_from_env()
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: dict[str, Any] | None = _error(None, -32700, "parse error")
        else:
            response = _handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
