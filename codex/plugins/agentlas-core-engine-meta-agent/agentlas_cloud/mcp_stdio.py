"""Local stdio MCP server for the Hephaestus Network router.

Exposes the Hub-first Hephaestus Network router as MCP tools so any MCP-capable
harness (OpenCode, Goose, Crush, Hermes Agent, Cursor, Codex, Gemini CLI, and
Ollama-launched harnesses running local models such as Gemma or DeepSeek) can
call routing without a runtime-specific command surface.

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout (MCP stdio). No
third-party dependencies. Public Network calls skip local private cards by
default; local routing requires the explicit `allow_local_routing` debug flag.
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from typing import Any, Mapping

from .workforce.contracts import (
    WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256,
    WORKFORCE_ONTOLOGY_VERSION,
    canonical_digest,
    load_workforce_contract_schema,
    workforce_contract_metadata,
)
from .workforce.execution import WORKFORCE_EXECUTION_PLAN_SCHEMA
from .workforce.federation import WORKFORCE_FEDERATION_RESULT_SCHEMA
from .workforce.provenance import (
    WORKFORCE_FEDERATED_PREPARATION_SCHEMA,
    WORKFORCE_FEDERATED_SELECTION_SCHEMA,
)

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "hephaestus-network", "version": "1.1.60"}
MODEL_ALLOCATION_POLICY_ENV = "AGENTLAS_MODEL_ALLOCATION_POLICY_JSON"
_HOST_MODEL_POLICY_FIELDS = frozenset({
    "pinnedModelId",
    "maxTier",
    "maxEffort",
    "requiredCapabilities",
})
WORKFORCE_PROTOCOL_VERSION = "2026-07-17.2"


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
        "sourceScopeRequired": True,
        "prepareAttemptSchemaVersion": "agentlas.workforce-prepare-attempt.v1",
        "sourceFetchIdempotencySchemaVersion": "agentlas.workforce-source-fetch-idempotency.v1",
        "sourceBundleReceiptSchemaVersion": "agentlas.workforce-source-bundle-verification.v1",
        "prepareIdempotencyRequired": True,
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


def _workforce_tool_contracts(*kinds: str) -> dict[str, dict[str, Any]]:
    return {kind: workforce_contract_metadata(kind) for kind in kinds}


def _host_model_allocation_policy() -> dict[str, Any]:
    """Read operator cost guardrails from the MCP process boundary.

    Tool arguments are untrusted workload input. They may carry a parent-AI
    allocation decision, but they must never raise the host's model/effort
    ceiling or forge a user pin. Operators configure this JSON in the MCP
    server launch environment instead.
    """

    raw = os.environ.get(MODEL_ALLOCATION_POLICY_ENV, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("invalid host model allocation policy JSON") from None
    if not isinstance(parsed, Mapping):
        raise ValueError("host model allocation policy must be an object")
    policy = {key: parsed[key] for key in _HOST_MODEL_POLICY_FIELDS if key in parsed}
    if "pinnedModelId" in policy and (
        not isinstance(policy["pinnedModelId"], str)
        or not policy["pinnedModelId"].strip()
        or len(policy["pinnedModelId"]) > 255
    ):
        raise ValueError("host pinnedModelId is invalid")
    if policy.get("maxTier") not in {None, "economy", "balanced", "frontier"}:
        raise ValueError("host maxTier is invalid")
    if policy.get("maxEffort") not in {None, "none", "minimal", "low", "medium", "high", "xhigh", "max"}:
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
            "Route a natural-language request through the Hephaestus Network "
            "Hub-first router. Returns a JSON decision (route, clarify, "
            "pipeline, hub_fallback, propose_new, or refuse) with a receipt_id. "
            "The router does not execute tools; the caller runtime owns execution safety."
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
        "name": "hephaestus_cloud_search",
        "description": (
            "Search ONLY the signed-in user's OWN Agentlas cloud packages (보관함) "
            "and return a JSON decision with a receipt_id. This is the owner-scoped "
            "leg of the three-scope model: it skips local cards and the public "
            "marketplace, querying the Hub with the owner filter (cargo.*). The "
            "user's own cloud packages are restorable/owned by them and call-priced "
            "at a flat 1 credit. The router does not execute tools; the caller "
            "runtime owns execution safety."
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
                "request": {"type": "string", "description": "Search request, for example: 시장 리포트 쓸 에이전트 찾아줘."},
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
            "Invoke an Agentlas Hub public agent through the Hephaestus Network surface. "
            "This skips local routing, calls Hub MCP marketplace.search_agents and "
            "agentlas.get_runtime_bundle, resolves Hub plugins, touches Agentlas memory "
            "when memory_root is provided, and writes an execution receipt. Agentlas "
            "public agents are BYOM: the Hub returns a runtime bundle; it does not run an LLM."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Prompt/task for the Hub agent."},
                "slug": {"type": "string", "description": "Optional exact Hub agent slug. If omitted, first callable Hub result is used."},
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
                    "Complete agentlas.workforce-work-order.v1; use the exact canonical schema and pinned ontology declared in x-agentlas-contract.",
                ),
                "expandSlotIds": {"type": "array", "items": {"type": "string"}},
                "sourceScope": {
                    "type": "string",
                    "enum": ["network", "local", "cloud", "hub"],
                    "description": (
                        "Required typed source scope. network=Local+Cloud+Hub; exact scopes never widen and there is no implicit fallback."
                    ),
                },
            },
            "required": ["workOrder", "sourceScope"],
        },
        "x-agentlas-contracts": _workforce_tool_contracts("workOrder"),
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.validate_selection",
        "description": (
            "Validate a team selected by the calling host LLM against an exact candidate set. "
            "With federationResult, Agentlas Core validates its locally pinned federated session; "
            "it never sends the merged menu to a remote source or selects/reranks/substitutes agents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workOrder": _contract_property(
                    "workOrder",
                    "The exact complete WorkOrder used to create candidateSet.",
                ),
                "candidateSet": {"type": "object"},
                "federationResult": {
                    "type": "object",
                    "description": (
                        "Exact locally pinned federation result from a source-scoped search. "
                        "When present, Core validates locally and never sends the merged menu to a remote source."
                    ),
                },
                "selection": _contract_property(
                    "selection",
                    "Complete agentlas.workforce-selection.v1 authored by the host LLM; use the exact canonical schema declared in x-agentlas-contract.",
                ),
            },
            "required": ["workOrder", "candidateSet", "selection", "federationResult"],
        },
        "x-agentlas-contracts": _workforce_tool_contracts("workOrder", "selection"),
        "_meta": workforce_tool_meta(),
    },
    {
        "name": "workforce.prepare_execution",
        "description": (
            "Fetch BYOM runtime bundles only for an already accepted exact roster. "
            "Pins agentReleaseId, packageHash, and contentDigest and fails closed on drift; "
            "it never chooses replacements."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workOrder": _contract_property(
                    "workOrder",
                    "The exact complete WorkOrder used to create candidateSet.",
                ),
                "candidateSet": {"type": "object"},
                "selection": _contract_property(
                    "selection",
                    "The exact complete host-LLM Selection accepted by validationReceipt or federatedSelection.",
                ),
                "validationReceipt": {"type": "object"},
                "federationResult": {"type": "object"},
                "federatedSelection": {
                    "type": "object",
                    "description": "Exact accepted result returned by federated workforce.validate_selection.",
                },
                "prepareAttempt": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": (
                        "Caller-authored agentlas.workforce-prepare-attempt.v1. Its digest binds the "
                        "logical occurrence, exact WorkOrder/Selection, federated selection, and every source pin."
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
            },
            "required": [
                "workOrder", "candidateSet", "selection",
                "federationResult", "federatedSelection", "prepareAttempt",
            ],
        },
        "x-agentlas-contracts": _workforce_tool_contracts("workOrder", "selection"),
        "_meta": workforce_tool_meta(),
    },
]


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from .networking import init_networking, network_status, route_request
    from .networking.bootstrap import networking_home

    host_model_policy: dict[str, Any] = {}
    if name == "hephaestus_route":
        try:
            host_model_policy = _host_model_allocation_policy()
        except ValueError:
            return {
                "action": "refuse",
                "status": "invalid_host_model_allocation_policy",
                "detail": f"Fix {MODEL_ALLOCATION_POLICY_ENV} in the MCP server launch environment.",
            }

    bootstrap: dict[str, Any] | None = None
    if name in {
        "hephaestus_route",
        "hephaestus_cloud_search",
        "hephaestus_search",
        "hephaestus_call",
        "hephaestus_hub_invoke",
    }:
        from .project_bootstrap import auto_bootstrap_enabled, maybe_ensure_project

        bootstrap = maybe_ensure_project(
            arguments.get("project_dir", "."),
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
        if bootstrap is not None:
            result["project_bootstrap"] = bootstrap
        return result

    init_networking(networking_home())
    if name in {
        "workforce.search_candidates",
        "workforce.validate_selection",
        "workforce.prepare_execution",
    }:
        from .workforce import validate_hub_selection_boundary, validate_hub_work_order_boundary
        from .networking.hub_client import call_hub_tool
        from .workforce.federation_store import FederationSessionStore
        from .workforce.provenance import (
            FederatedProvenanceError,
            prepare_federated_execution_plan,
            validate_federated_host_selection,
        )
        from .workforce.source_service import WorkforceSourceError, WorkforceSourceService

        # Agentlas OS is the canonical Workforce entrypoint. Core owns source
        # federation plus deterministic governance/provenance validation; the
        # active host LLM alone authors the staffing decision. Privacy checks
        # are local, non-mutating, and complete before the first outbound byte.
        work_order = arguments.get("workOrder")
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
                return WorkforceSourceService().search(
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
        if name != "workforce.search_candidates":
            candidate_set = arguments.get("candidateSet")
            selection = arguments.get("selection")
            federation_result = arguments.get("federationResult")
            federated_selection = arguments.get("federatedSelection")
            if not isinstance(candidate_set, Mapping) or not isinstance(selection, Mapping):
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
                        "issues": [{"path": "selection", "code": "schema_type"}],
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
                    service = WorkforceSourceService(session_store=store)
                    source_bundles = service.fetch_selected_runtime_bundles(
                        federated_selection,
                        work_order=work_order,
                        selection=selection,
                        prepare_attempt=arguments.get("prepareAttempt"),
                    )
                    return prepare_federated_execution_plan(
                        work_order=work_order,
                        selection=selection,
                        federated_selection=federated_selection,
                        federation_result=federation_result,
                        source_runtime_bundles=source_bundles,
                        session_store=store,
                    )
                except (FederatedProvenanceError, WorkforceSourceError, ValueError) as exc:
                    failure = {
                        "action": name,
                        "status": "error",
                        "error": getattr(exc, "code", "federated_workforce_invalid"),
                    }
                    retry_after_ms = getattr(exc, "retry_after_ms", None)
                    receipt_expires_at = getattr(exc, "receipt_expires_at", None)
                    if isinstance(retry_after_ms, int) and not isinstance(retry_after_ms, bool):
                        failure["retryAfterMs"] = max(100, min(10_000, retry_after_ms))
                    if isinstance(receipt_expires_at, str) and receipt_expires_at:
                        failure["receiptExpiresAt"] = receipt_expires_at
                    return failure
        return call_hub_tool(name, arguments)
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
        return with_bootstrap(route_request(
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
        ))
    if name == "hephaestus_cloud_search":
        # Owner-scoped: scope="cloud" implies hub_only inside route_request and
        # queries only the signed-in user's OWN cloud packages (보관함).
        return with_bootstrap(route_request(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            use_hub=True,
            hub_approved=False,
            scope="cloud",
        ))
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

        decision = route_request(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            use_hub=True,
            hub_approved=bool(arguments.get("approve_hub", False)),
            hub_only=True,
        )
        if decision.get("action") != "hub_candidates" and not arguments.get("slug"):
            return with_bootstrap({
                "action": "hub_invoke",
                "status": "routing_not_ready",
                "routing_decision": decision,
                "detail": "Hub invocation requires a Hub-approved hub_only route that returns hub_candidates.",
            })
        return with_bootstrap(invoke_hub_agent(
            arguments["request"],
            slug=arguments.get("slug"),
            hub_decision=decision,
            project_dir=arguments.get("project_dir", "."),
            memory_root=arguments.get("memory_root"),
            version=str(arguments.get("version") or "latest"),
            local_inventory=arguments.get("local_inventory") or [],
        ))
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
    raise KeyError(name)


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
        except KeyError:
            return _error(msg_id, -32602, f"unknown tool: {name}")
        except Exception as exc:  # surfaced as a tool error, not a protocol error
            return _result(
                msg_id,
                {"content": [{"type": "text", "text": f"hephaestus tool failed: {exc}"}], "isError": True},
            )
        tool_result = {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, sort_keys=True)}]
        }
        if isinstance(payload, Mapping) and payload.get("status") in {"error", "rejected", "blocked"}:
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
