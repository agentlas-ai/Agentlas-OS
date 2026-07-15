"""Pinned BYOM preparation and truthful workforce execution validation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from .contracts import canonical_digest
from .privacy import WorkOrderHubBoundaryError, assert_hub_work_order_boundary


WORKFORCE_RUNTIME_BUNDLE_DIGEST_SCHEMA = "agentlas.workforce-runtime-bundle-digest.v4"
WORKFORCE_EXECUTION_PLAN_SCHEMA = "agentlas.workforce-execution-plan.v5"
WORKFORCE_EXECUTION_RECEIPT_SCHEMA = "agentlas.workforce-execution-receipt.v2"
WORKFORCE_PERMISSION_POLICY_SCHEMA = "agentlas.workforce-permission-policy.v1"
WORKFORCE_PERMISSION_POLICY_DIGEST_SCHEMA = "agentlas.workforce-permission-policy-digest.v1"
WORKFORCE_EXECUTION_GRAPH_SCHEMA = "1.0"
WORKFORCE_EXECUTION_GRAPH_DIGEST_SCHEMA = "agentlas.workforce-execution-graph-digest.v1"
WORKFORCE_EXECUTION_CONTEXT_SCHEMA = "agentlas.workforce-execution-context.v1"
WORKFORCE_EXECUTION_CONTEXT_DIGEST_SCHEMA = "agentlas.workforce-execution-context-digest.v1"
WORKFORCE_CAPABILITY_BINDING_PLAN_SCHEMA = "agentlas.workforce-capability-binding-plan.v1"
WORKFORCE_CAPABILITY_BINDING_PLAN_DIGEST_SCHEMA = "agentlas.workforce-capability-binding-plan-digest.v1"
WORKFORCE_TOOL_INVENTORY_SCHEMA = "agentlas.workforce-tool-inventory.v1"
WORKFORCE_TOOL_INVENTORY_DIGEST_SCHEMA = "agentlas.workforce-tool-inventory-digest.v1"

_INTEROPERABLE_OBJECT_KEY_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_.$:/@+~-]*$")
_RESERVED_OBJECT_KEYS = frozenset({"__proto__", "prototype", "constructor"})
_UNICODE_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{1,255}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROOT_RELATIVE_GLOB_RE = re.compile(r"^[A-Za-z0-9._@+~*?/-]{1,240}$")
_MCP_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.$:/@+~-]{0,127}$")
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_DIGEST_VALUE_DEPTH = 32
_MAX_DIGEST_VALUE_NODES = 10_000
_EFFORTS = {None, "none", "low", "medium", "high", "xhigh", "max"}
_EFFORT_EVIDENCE = {"runner-reported", "runtime-fixed", "not-observable"}


def validate_workforce_digest_value(value: Any) -> None:
    """Accept only JSON values with identical Python/ECMAScript encoding."""

    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_DIGEST_VALUE_NODES:
            raise ValueError("runtime_bundle_digest_value_too_large")
        if depth > _MAX_DIGEST_VALUE_DEPTH:
            raise ValueError("runtime_bundle_digest_value_too_deep")
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, str):
            if _UNICODE_SURROGATE_RE.search(item):
                raise ValueError("runtime_bundle_digest_lone_surrogate")
            return
        if isinstance(item, (int, float)):
            raise ValueError("runtime_bundle_digest_number_forbidden")
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if (
                    not isinstance(key, str)
                    or not _INTEROPERABLE_OBJECT_KEY_RE.fullmatch(key)
                    or key in _RESERVED_OBJECT_KEYS
                ):
                    raise ValueError("runtime_bundle_digest_object_key_invalid")
                visit(child, depth + 1)
            return
        raise ValueError("runtime_bundle_digest_non_json_value")

    visit(value, 0)


def _portable_canonical_json(value: Any) -> str:
    validate_workforce_digest_value(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _portable_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_portable_canonical_json(value).encode("utf-8")).hexdigest()


def _exact_keys(value: Mapping[str, Any], keys: set[str], code: str) -> None:
    if set(value) != keys:
        raise ValueError(code)


def _string_list(
    value: Any,
    *,
    code: str,
    max_items: int,
    max_length: int,
    pattern: re.Pattern[str] | None = None,
) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise ValueError(code)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > max_length:
            raise ValueError(code)
        if _UNICODE_SURROGATE_RE.search(item) or (pattern is not None and not pattern.fullmatch(item)):
            raise ValueError(code)
        if item in result:
            raise ValueError(code)
        result.append(item)
    return result


def _root_relative_patterns(value: Any, code: str) -> list[str]:
    patterns = _string_list(
        value,
        code=code,
        max_items=128,
        max_length=240,
        pattern=_ROOT_RELATIVE_GLOB_RE,
    )
    for pattern in patterns:
        if pattern.startswith("/") or "\\" in pattern or ".." in pattern.split("/"):
            raise ValueError(code)
    return patterns


def deny_all_permission_policy() -> dict[str, Any]:
    """Return the only safe projection for a bundle with no declaration."""

    return {
        "schemaVersion": WORKFORCE_PERMISSION_POLICY_SCHEMA,
        "network": "deny",
        "shell": "deny",
        "fileRead": {"mode": "deny", "allowPatterns": [], "denyPatterns": []},
        "mcp": {"mode": "deny", "allowedTools": []},
        "unknownTools": "deny",
    }


def validate_permission_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and detach the first-class execution permission upper bound."""

    _exact_keys(
        policy,
        {"schemaVersion", "network", "shell", "fileRead", "mcp", "unknownTools"},
        "permission_policy_keys_invalid",
    )
    if policy.get("schemaVersion") != WORKFORCE_PERMISSION_POLICY_SCHEMA:
        raise ValueError("permission_policy_schema_invalid")
    if policy.get("network") not in {"allow", "ask", "deny"}:
        raise ValueError("permission_policy_network_invalid")
    if policy.get("shell") not in {"allow", "ask", "deny"}:
        raise ValueError("permission_policy_shell_invalid")
    if policy.get("unknownTools") != "deny":
        raise ValueError("permission_policy_unknown_tools_must_deny")

    file_read = policy.get("fileRead")
    if not isinstance(file_read, Mapping):
        raise ValueError("permission_policy_file_read_invalid")
    _exact_keys(file_read, {"mode", "allowPatterns", "denyPatterns"}, "permission_policy_file_read_keys_invalid")
    file_mode = file_read.get("mode")
    if file_mode not in {"deny", "manifest-allowlist"}:
        raise ValueError("permission_policy_file_read_mode_invalid")
    allow_patterns = _root_relative_patterns(file_read.get("allowPatterns"), "permission_policy_allow_pattern_invalid")
    deny_patterns = _root_relative_patterns(file_read.get("denyPatterns"), "permission_policy_deny_pattern_invalid")
    if file_mode == "deny" and (allow_patterns or deny_patterns):
        raise ValueError("permission_policy_denied_file_lists_must_be_empty")
    if file_mode == "manifest-allowlist" and (not allow_patterns or not deny_patterns):
        raise ValueError("permission_policy_file_allowlist_incomplete")

    mcp = policy.get("mcp")
    if not isinstance(mcp, Mapping):
        raise ValueError("permission_policy_mcp_invalid")
    _exact_keys(mcp, {"mode", "allowedTools"}, "permission_policy_mcp_keys_invalid")
    mcp_mode = mcp.get("mode")
    if mcp_mode not in {"deny", "allowlist"}:
        raise ValueError("permission_policy_mcp_mode_invalid")
    allowed_tools = _string_list(
        mcp.get("allowedTools"),
        code="permission_policy_mcp_tool_invalid",
        max_items=128,
        max_length=128,
        pattern=_MCP_TOOL_NAME_RE,
    )
    if mcp_mode == "deny" and allowed_tools:
        raise ValueError("permission_policy_denied_mcp_list_must_be_empty")
    if mcp_mode == "allowlist" and not allowed_tools:
        raise ValueError("permission_policy_mcp_allowlist_empty")

    canonical = {
        "schemaVersion": WORKFORCE_PERMISSION_POLICY_SCHEMA,
        "network": policy.get("network"),
        "shell": policy.get("shell"),
        "fileRead": {
            "mode": file_mode,
            "allowPatterns": allow_patterns,
            "denyPatterns": deny_patterns,
        },
        "mcp": {"mode": mcp_mode, "allowedTools": allowed_tools},
        "unknownTools": "deny",
    }
    validate_workforce_digest_value(canonical)
    return canonical


def _one_source(bundle: Mapping[str, Any], *names: str) -> Any:
    values = [bundle[name] for name in names if name in bundle]
    if not values:
        return None
    first = values[0]
    if any(value != first for value in values[1:]):
        raise ValueError("permission_policy_source_conflict")
    return first


def _runtime_bundle_sources(runtime_bundle: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return every supported source layer without silently preferring one."""

    sources: list[Mapping[str, Any]] = [runtime_bundle]
    directive = runtime_bundle.get("directiveBundle")
    if directive is not None:
        if not isinstance(directive, Mapping):
            raise ValueError("runtime_bundle_directive_invalid")
        sources.append(directive)
    for source in list(sources):
        nested = _one_source(source, "runtimeBundle", "runtime_bundle")
        if nested is not None:
            if not isinstance(nested, Mapping):
                raise ValueError("runtime_bundle_nested_invalid")
            sources.append(nested)
    return sources


def project_permission_policy(runtime_bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Project legacy Hub declarations or a canonical policy, always fail-safe.

    The projection happens at the preparation authority and is included in the
    returned v5 row.  Hosts never invent a missing field.  An entirely absent
    declaration becomes an explicit deny-all row; an incomplete claimed
    allowlist is rejected rather than weakened or widened.
    """

    sources = _runtime_bundle_sources(runtime_bundle)
    canonical_values = [
        value
        for source in sources
        for value in [_one_source(source, "permissionPolicy", "permission_policy")]
        if value is not None
    ]
    if canonical_values:
        canonical = canonical_values[0]
        if any(value != canonical for value in canonical_values[1:]):
            raise ValueError("permission_policy_source_conflict")
        if not isinstance(canonical, Mapping):
            raise ValueError("permission_policy_invalid")
        return validate_permission_policy(canonical)

    def merged(*names: str) -> Any:
        values: list[Any] = []
        for source in sources:
            value = _one_source(source, *names)
            if value is not None:
                values.append(value)
        if not values:
            return None
        first = values[0]
        if any(value != first for value in values[1:]):
            raise ValueError("permission_policy_source_conflict")
        return first

    permissions = merged("toolPermissions", "tool_permissions")
    allow_read = merged("allowRead", "allow_read")
    deny_read = merged("denyRead", "deny_read")
    allowed_tools = merged("mcpAllowedTools", "mcp_allowed_tools")
    if permissions is None and allow_read is None and deny_read is None and allowed_tools is None:
        return deny_all_permission_policy()
    if permissions is None:
        permissions = {}
    if not isinstance(permissions, Mapping) or set(permissions) - {"network", "shell", "fileRead"}:
        raise ValueError("permission_policy_tool_permissions_invalid")

    network = permissions.get("network", "deny")
    shell = permissions.get("shell", "deny")
    file_decision = permissions.get("fileRead", "deny")
    if file_decision == "manifest-allowlist":
        file_read = {
            "mode": "manifest-allowlist",
            "allowPatterns": allow_read,
            "denyPatterns": deny_read,
        }
    elif file_decision == "deny":
        if allow_read not in (None, []) or deny_read not in (None, []):
            raise ValueError("permission_policy_denied_file_source_conflict")
        file_read = {"mode": "deny", "allowPatterns": [], "denyPatterns": []}
    else:
        raise ValueError("permission_policy_file_read_mode_invalid")

    if allowed_tools is None or allowed_tools == []:
        mcp = {"mode": "deny", "allowedTools": []}
    else:
        mcp = {"mode": "allowlist", "allowedTools": allowed_tools}
    return validate_permission_policy(
        {
            "schemaVersion": WORKFORCE_PERMISSION_POLICY_SCHEMA,
            "network": network,
            "shell": shell,
            "fileRead": file_read,
            "mcp": mcp,
            "unknownTools": "deny",
        }
    )


def workforce_permission_policy_canonical_json(policy: Mapping[str, Any]) -> str:
    canonical = validate_permission_policy(policy)
    return _portable_canonical_json(
        {"schemaVersion": WORKFORCE_PERMISSION_POLICY_DIGEST_SCHEMA, "permissionPolicy": canonical}
    )


def workforce_permission_policy_digest(policy: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(workforce_permission_policy_canonical_json(policy).encode("utf-8")).hexdigest()


def _package_path(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise ValueError(code)
    if not _ROOT_RELATIVE_GLOB_RE.fullmatch(value) or value.startswith("/") or "\\" in value:
        raise ValueError(code)
    if ".." in value.split("/") or "*" in value or "?" in value:
        raise ValueError(code)
    return value


def validate_execution_graph(graph: Mapping[str, Any], *, entity_kind: str) -> dict[str, Any]:
    if entity_kind != "team":
        raise ValueError("execution_graph_entity_kind_invalid")
    _exact_keys(graph, {"schemaVersion", "manager", "workers"}, "execution_graph_keys_invalid")
    if graph.get("schemaVersion") != WORKFORCE_EXECUTION_GRAPH_SCHEMA:
        raise ValueError("execution_graph_schema_invalid")
    manager = graph.get("manager")
    if not isinstance(manager, Mapping):
        raise ValueError("execution_graph_manager_invalid")
    _exact_keys(manager, {"path", "content"}, "execution_graph_manager_keys_invalid")
    manager_path = _package_path(manager.get("path"), "execution_graph_manager_path_invalid")
    manager_content = manager.get("content")
    if not isinstance(manager_content, str) or not manager_content.strip() or len(manager_content) > 200_000:
        raise ValueError("execution_graph_manager_content_invalid")

    raw_workers = graph.get("workers")
    if not isinstance(raw_workers, list) or not (1 <= len(raw_workers) <= 32):
        raise ValueError("execution_graph_workers_invalid")
    workers: list[dict[str, str]] = []
    ids: set[str] = set()
    paths = {manager_path}
    for raw in raw_workers:
        if not isinstance(raw, Mapping):
            raise ValueError("execution_graph_worker_invalid")
        _exact_keys(raw, {"id", "path", "content"}, "execution_graph_worker_keys_invalid")
        worker_id = raw.get("id")
        if not isinstance(worker_id, str) or not _ID_RE.fullmatch(worker_id) or worker_id in ids:
            raise ValueError("execution_graph_worker_id_invalid")
        path = _package_path(raw.get("path"), "execution_graph_worker_path_invalid")
        if path in paths:
            raise ValueError("execution_graph_worker_path_duplicate")
        content = raw.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > 200_000:
            raise ValueError("execution_graph_worker_content_invalid")
        ids.add(worker_id)
        paths.add(path)
        workers.append({"id": worker_id, "path": path, "content": content})

    canonical = {
        "schemaVersion": WORKFORCE_EXECUTION_GRAPH_SCHEMA,
        "manager": {"path": manager_path, "content": manager_content},
        "workers": workers,
    }
    validate_workforce_digest_value(canonical)
    return canonical


def project_execution_graph(runtime_bundle: Mapping[str, Any], *, entity_kind: str) -> dict[str, Any] | None:
    if entity_kind == "group":
        raise ValueError("group_entity_not_executable")
    sources = _runtime_bundle_sources(runtime_bundle)
    graphs: list[Any] = []
    for source in sources:
        graph = _one_source(source, "executionGraph", "execution_graph")
        if graph is not None:
            graphs.append(graph)
    if graphs and any(graph != graphs[0] for graph in graphs[1:]):
        raise ValueError("execution_graph_source_conflict")
    if not graphs:
        if entity_kind == "team":
            raise ValueError("team_execution_graph_missing")
        return None
    if entity_kind == "agent":
        raise ValueError("agent_execution_graph_forbidden")
    if not isinstance(graphs[0], Mapping):
        raise ValueError("execution_graph_invalid")
    return validate_execution_graph(graphs[0], entity_kind=entity_kind)


def workforce_execution_graph_canonical_json(graph: Mapping[str, Any]) -> str:
    canonical = validate_execution_graph(graph, entity_kind="team")
    return _portable_canonical_json(
        {"schemaVersion": WORKFORCE_EXECUTION_GRAPH_DIGEST_SCHEMA, "executionGraph": canonical}
    )


def workforce_execution_graph_digest(graph: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(workforce_execution_graph_canonical_json(graph).encode("utf-8")).hexdigest()


def workforce_runtime_bundle_canonical_json(roster_row: Mapping[str, Any]) -> str:
    """Return the language-neutral canonical bytes contract for digest v4."""

    directive_bundle = roster_row.get("directiveBundle")
    if not isinstance(directive_bundle, Mapping) or not any(
        isinstance(directive_bundle.get(key), str) and directive_bundle.get(key).strip()
        for key in ("systemPrompt", "instructions", "agentMd")
    ):
        raise ValueError("runtime_bundle_directive_missing")
    permission_policy = roster_row.get("permissionPolicy")
    if not isinstance(permission_policy, Mapping):
        raise ValueError("permission_policy_missing")
    permission_policy = validate_permission_policy(permission_policy)
    entity_kind = roster_row.get("entityKind")
    if entity_kind not in {"agent", "team"}:
        raise ValueError("runtime_bundle_entity_kind_invalid")
    execution_graph = roster_row.get("executionGraph")
    if entity_kind == "agent":
        if execution_graph is not None:
            raise ValueError("agent_execution_graph_forbidden")
    else:
        if not isinstance(execution_graph, Mapping):
            raise ValueError("team_execution_graph_missing")
        execution_graph = validate_execution_graph(execution_graph, entity_kind="team")
    payload = {
        "schemaVersion": WORKFORCE_RUNTIME_BUNDLE_DIGEST_SCHEMA,
        "slotId": roster_row.get("slotId"),
        "agentDefinitionId": roster_row.get("agentDefinitionId"),
        "agentReleaseId": roster_row.get("agentReleaseId"),
        "releaseVersion": roster_row.get("releaseVersion"),
        "packageHash": roster_row.get("packageHash"),
        "contentDigest": roster_row.get("contentDigest"),
        "entityKind": entity_kind,
        "directiveBundle": dict(directive_bundle),
        "permissionPolicy": permission_policy,
        "executionGraph": execution_graph,
    }
    return _portable_canonical_json(payload)


def workforce_runtime_bundle_digest(roster_row: Mapping[str, Any]) -> str:
    canonical = workforce_runtime_bundle_canonical_json(roster_row)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _context_strings(value: Any, code: str, *, maximum: int = 256) -> list[str]:
    return _string_list(
        value,
        code=code,
        max_items=maximum,
        max_length=255,
        pattern=_ID_RE,
    )


def project_execution_context(
    *,
    work_order: Mapping[str, Any],
    selection: Mapping[str, Any],
    validation_receipt: Mapping[str, Any],
    candidate_set: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the closed, content-only organization contract for execution."""

    assert_hub_work_order_boundary(work_order)
    if work_order.get("schemaVersion") != "agentlas.workforce-work-order.v1":
        raise ValueError("execution_context_work_order_schema_invalid")
    if selection.get("schemaVersion") != "agentlas.workforce-selection.v1":
        raise ValueError("execution_context_selection_schema_invalid")
    if work_order.get("workOrderId") != candidate_set.get("workOrderId"):
        raise ValueError("execution_context_work_order_id_mismatch")
    if selection.get("candidateSetDigest") != candidate_set.get("candidateSetDigest"):
        raise ValueError("execution_context_candidate_digest_mismatch")
    if selection.get("selectionSessionId") != candidate_set.get("selectionSessionId"):
        raise ValueError("execution_context_selection_session_mismatch")

    task_brief = work_order.get("taskBrief")
    if not isinstance(task_brief, str) or not task_brief.strip() or len(task_brief) > 4000:
        raise ValueError("execution_context_task_brief_invalid")
    raw_slots = work_order.get("roleSlots")
    if not isinstance(raw_slots, list) or not (1 <= len(raw_slots) <= 32):
        raise ValueError("execution_context_slots_invalid")
    slots: list[dict[str, Any]] = []
    slot_ids: set[str] = set()
    for raw in raw_slots:
        if not isinstance(raw, Mapping):
            raise ValueError("execution_context_slot_invalid")
        slot_id = raw.get("slotId")
        title = raw.get("title")
        task = raw.get("task")
        cardinality = raw.get("cardinality")
        criticality = raw.get("criticality")
        if not isinstance(slot_id, str) or not _ID_RE.fullmatch(slot_id) or slot_id in slot_ids:
            raise ValueError("execution_context_slot_id_invalid")
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise ValueError("execution_context_slot_title_invalid")
        if not isinstance(task, str) or not task.strip() or len(task) > 2000:
            raise ValueError("execution_context_slot_task_invalid")
        if isinstance(cardinality, bool) or not isinstance(cardinality, int) or not (1 <= cardinality <= 16):
            raise ValueError("execution_context_slot_cardinality_invalid")
        if criticality not in {"required", "optional"}:
            raise ValueError("execution_context_slot_criticality_invalid")
        minimum_evidence = raw.get("minimumEvidenceLevel")
        if minimum_evidence not in {None, "declared", "checked", "demonstrated", "attested"}:
            raise ValueError("execution_context_minimum_evidence_invalid")
        constraints: dict[str, list[str]] = {}
        for field in (
            "requiredCommunities",
            "optionalCommunities",
            "excludedCommunities",
            "requiredRoles",
            "requiredSkills",
            "optionalSkills",
            "requiredKnowledge",
            "requiredToolCapabilities",
            "consumes",
            "produces",
            "requiredAuthorities",
            "forbiddenAuthorities",
            "runtimes",
            "languages",
            "modalities",
            "allowedEntityKinds",
        ):
            constraints[field] = _context_strings(
                raw.get(field), f"execution_context_slot_{field}_invalid"
            )
        if not constraints["allowedEntityKinds"] or any(
            item not in {"agent", "team"} for item in constraints["allowedEntityKinds"]
        ):
            raise ValueError("execution_context_slot_allowed_entity_kinds_invalid")
        slot_ids.add(slot_id)
        slots.append(
            {
                "slotId": slot_id,
                "title": title,
                "task": task,
                # Intentional portable projection from the schema-validated
                # small integer.  It is not a model/adapter rewrite.
                "cardinality": str(cardinality),
                "criticality": criticality,
                **constraints,
                "minimumEvidenceLevel": minimum_evidence,
            }
        )

    def project_edges(value: Any, *, work_order_edges: bool) -> list[dict[str, Any]]:
        if not isinstance(value, list) or len(value) > 128:
            raise ValueError("execution_context_edges_invalid")
        result: list[dict[str, Any]] = []
        source_key, target_key = ("from", "to") if work_order_edges else ("fromSlot", "toSlot")
        for raw in value:
            if not isinstance(raw, Mapping):
                raise ValueError("execution_context_edge_invalid")
            source = raw.get(source_key)
            target = raw.get(target_key)
            relation = raw.get("relation")
            if source not in slot_ids or target not in slot_ids:
                raise ValueError("execution_context_edge_slot_invalid")
            if relation not in {"reportsTo", "handsOffTo", "reviews", "coordinatesWith"}:
                raise ValueError("execution_context_edge_relation_invalid")
            result.append(
                {
                    source_key: source,
                    target_key: target,
                    "relation": relation,
                    "artifactKinds": _context_strings(
                        raw.get("artifactKinds"), "execution_context_edge_artifacts_invalid"
                    ),
                }
            )
        return result

    work_order_edges = project_edges(work_order.get("edges"), work_order_edges=True)
    selection_edges = project_edges(selection.get("edges"), work_order_edges=False)
    raw_assignments = selection.get("assignments")
    if not isinstance(raw_assignments, list) or not (1 <= len(raw_assignments) <= 64):
        raise ValueError("execution_context_assignments_invalid")
    assignments: list[dict[str, Any]] = []
    pairs: set[tuple[str, str]] = set()
    for raw in raw_assignments:
        if not isinstance(raw, Mapping):
            raise ValueError("execution_context_assignment_invalid")
        slot_id = raw.get("slotId")
        release_id = raw.get("agentReleaseId")
        if slot_id not in slot_ids or not isinstance(release_id, str) or not _ID_RE.fullmatch(release_id):
            raise ValueError("execution_context_assignment_identity_invalid")
        pair = (slot_id, release_id)
        if pair in pairs:
            raise ValueError("execution_context_assignment_duplicate")
        reason_codes = _context_strings(raw.get("reasonCodes"), "execution_context_reason_codes_invalid")
        if not reason_codes:
            raise ValueError("execution_context_reason_codes_invalid")
        pairs.add(pair)
        assignments.append({"slotId": slot_id, "agentReleaseId": release_id, "reasonCodes": reason_codes})

    receipt = validation_receipt.get("receipt")
    if not isinstance(receipt, Mapping):
        raise ValueError("execution_context_validation_receipt_missing")
    receipt_assignments = [
        {
            "slotId": row.get("slotId"),
            "agentReleaseId": row.get("agentReleaseId"),
            "reasonCodes": row.get("reasonCodes"),
        }
        for row in receipt.get("assignments") or []
        if isinstance(row, Mapping)
    ]
    if receipt_assignments != assignments or receipt.get("edges") != selection_edges:
        raise ValueError("execution_context_validation_receipt_mismatch")
    if receipt.get("workOrderId") != work_order.get("workOrderId"):
        raise ValueError("execution_context_validation_work_order_mismatch")

    context = {
        "schemaVersion": WORKFORCE_EXECUTION_CONTEXT_SCHEMA,
        "workOrderId": work_order.get("workOrderId"),
        "taskBrief": task_brief,
        "forbiddenCommunities": _context_strings(
            work_order.get("forbiddenCommunities"),
            "execution_context_forbidden_communities_invalid",
        ),
        "slots": slots,
        "workOrderEdges": work_order_edges,
        "assignments": assignments,
        "selectionEdges": selection_edges,
    }
    validate_workforce_digest_value(context)
    return context


def workforce_execution_context_canonical_json(context: Mapping[str, Any]) -> str:
    return _portable_canonical_json(
        {"schemaVersion": WORKFORCE_EXECUTION_CONTEXT_DIGEST_SCHEMA, "executionContext": dict(context)}
    )


def workforce_execution_context_digest(context: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(workforce_execution_context_canonical_json(context).encode("utf-8")).hexdigest()


def validate_tool_inventory(tool_inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one local, private, policy-filtered JIT tool snapshot."""

    if not isinstance(tool_inventory, Mapping):
        raise ValueError("tool_inventory_missing")
    _exact_keys(
        tool_inventory,
        {"schemaVersion", "executionContextDigest", "observedAt", "entries"},
        "tool_inventory_keys_invalid",
    )
    if tool_inventory.get("schemaVersion") != WORKFORCE_TOOL_INVENTORY_SCHEMA:
        raise ValueError("tool_inventory_schema_invalid")
    execution_context_digest = tool_inventory.get("executionContextDigest")
    observed_at = tool_inventory.get("observedAt")
    if not isinstance(execution_context_digest, str) or not _SHA256_RE.fullmatch(execution_context_digest):
        raise ValueError("tool_inventory_execution_context_digest_invalid")
    if not isinstance(observed_at, str) or not _UTC_TIMESTAMP_RE.fullmatch(observed_at):
        raise ValueError("tool_inventory_observed_at_invalid")
    raw_entries = tool_inventory.get("entries")
    if not isinstance(raw_entries, list) or len(raw_entries) > 1024:
        raise ValueError("tool_inventory_entries_invalid")
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    entry_keys = {
        "slotId", "agentReleaseId", "permissionPolicyDigest", "provider", "toolId",
        "serverId", "description", "inputSchemaDigest", "runtimeIds",
        "selectiveEnforcement", "capabilityIds", "status",
    }
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise ValueError("tool_inventory_entry_invalid")
        _exact_keys(raw, entry_keys, "tool_inventory_entry_keys_invalid")
        slot_id = raw.get("slotId")
        release_id = raw.get("agentReleaseId")
        policy_digest = raw.get("permissionPolicyDigest")
        provider = raw.get("provider")
        tool_id = raw.get("toolId")
        if any(
            not isinstance(item, str) or not _ID_RE.fullmatch(item)
            for item in (slot_id, release_id)
        ) or not isinstance(policy_digest, str) or not _SHA256_RE.fullmatch(policy_digest):
            raise ValueError("tool_inventory_entry_scope_invalid")
        if provider not in {"builtin", "mcp"} or not isinstance(tool_id, str):
            raise ValueError("tool_inventory_entry_tool_invalid")
        if provider == "mcp" and not _MCP_TOOL_NAME_RE.fullmatch(tool_id):
            raise ValueError("tool_inventory_entry_tool_invalid")
        if provider == "builtin" and not _ID_RE.fullmatch(tool_id):
            raise ValueError("tool_inventory_entry_tool_invalid")
        server_id = raw.get("serverId")
        input_schema_digest = raw.get("inputSchemaDigest")
        if provider == "mcp":
            if not isinstance(server_id, str) or not _ID_RE.fullmatch(server_id):
                raise ValueError("tool_inventory_entry_server_invalid")
            if not isinstance(input_schema_digest, str) or not _SHA256_RE.fullmatch(input_schema_digest):
                raise ValueError("tool_inventory_entry_input_schema_invalid")
        else:
            if server_id is not None:
                raise ValueError("tool_inventory_builtin_server_forbidden")
            if input_schema_digest is not None and (
                not isinstance(input_schema_digest, str) or not _SHA256_RE.fullmatch(input_schema_digest)
            ):
                raise ValueError("tool_inventory_entry_input_schema_invalid")
        description = raw.get("description")
        if (
            not isinstance(description, str)
            or len(description) > 500
            or _UNICODE_SURROGATE_RE.search(description)
        ):
            raise ValueError("tool_inventory_entry_description_invalid")
        runtime_ids = _context_strings(
            raw.get("runtimeIds"), "tool_inventory_entry_runtimes_invalid", maximum=32
        )
        capability_ids = _context_strings(
            raw.get("capabilityIds"), "tool_inventory_entry_capabilities_invalid"
        )
        if not runtime_ids or not capability_ids:
            raise ValueError("tool_inventory_entry_coverage_empty")
        if raw.get("selectiveEnforcement") != "exact-tool-allowlist":
            raise ValueError("tool_inventory_entry_enforcement_invalid")
        if raw.get("status") != "ready":
            raise ValueError("tool_inventory_entry_not_ready")
        identity = (slot_id, release_id, provider, tool_id)
        if identity in seen:
            raise ValueError("tool_inventory_entry_duplicate")
        seen.add(identity)
        entries.append({
            "slotId": slot_id,
            "agentReleaseId": release_id,
            "permissionPolicyDigest": policy_digest,
            "provider": provider,
            "toolId": tool_id,
            "serverId": server_id,
            "description": description,
            "inputSchemaDigest": input_schema_digest,
            "runtimeIds": runtime_ids,
            "selectiveEnforcement": "exact-tool-allowlist",
            "capabilityIds": capability_ids,
            "status": "ready",
        })
    result = {
        "schemaVersion": WORKFORCE_TOOL_INVENTORY_SCHEMA,
        "executionContextDigest": execution_context_digest,
        "observedAt": observed_at,
        "entries": entries,
    }
    validate_workforce_digest_value(result)
    return result


def workforce_tool_inventory_digest(tool_inventory: Mapping[str, Any]) -> str:
    normalized = validate_tool_inventory(tool_inventory)
    return _portable_digest({
        "schemaVersion": WORKFORCE_TOOL_INVENTORY_DIGEST_SCHEMA,
        "toolInventory": normalized,
    })


def _validate_bound_inventory(inventory: Any) -> list[dict[str, Any]]:
    if not isinstance(inventory, list) or len(inventory) > 256:
        raise ValueError("capability_binding_plan_inventory_invalid")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    keys = {
        "slotId", "agentReleaseId", "permissionPolicyDigest", "toolId", "provider",
        "capabilityIds", "status",
    }
    for raw in inventory:
        if not isinstance(raw, Mapping):
            raise ValueError("capability_binding_plan_inventory_row_invalid")
        _exact_keys(raw, keys, "capability_binding_plan_inventory_row_keys_invalid")
        slot_id = raw.get("slotId")
        release_id = raw.get("agentReleaseId")
        policy_digest = raw.get("permissionPolicyDigest")
        provider = raw.get("provider")
        tool_id = raw.get("toolId")
        if any(
            not isinstance(item, str) or not _ID_RE.fullmatch(item)
            for item in (slot_id, release_id)
        ) or not isinstance(policy_digest, str) or not _SHA256_RE.fullmatch(policy_digest):
            raise ValueError("capability_binding_plan_inventory_scope_invalid")
        if provider not in {"builtin", "mcp"} or not isinstance(tool_id, str):
            raise ValueError("capability_binding_plan_inventory_tool_invalid")
        if provider == "mcp" and not _MCP_TOOL_NAME_RE.fullmatch(tool_id):
            raise ValueError("capability_binding_plan_inventory_tool_invalid")
        if provider == "builtin" and not _ID_RE.fullmatch(tool_id):
            raise ValueError("capability_binding_plan_inventory_tool_invalid")
        capability_ids = _context_strings(
            raw.get("capabilityIds"), "capability_binding_plan_inventory_capabilities_invalid"
        )
        if not capability_ids or raw.get("status") != "bound":
            raise ValueError("capability_binding_plan_inventory_unbound")
        identity = (slot_id, release_id, provider, tool_id)
        if identity in seen:
            raise ValueError("capability_binding_plan_inventory_duplicate")
        seen.add(identity)
        result.append({
            "slotId": slot_id,
            "agentReleaseId": release_id,
            "permissionPolicyDigest": policy_digest,
            "toolId": tool_id,
            "provider": provider,
            "capabilityIds": capability_ids,
            "status": "bound",
        })
    return result


def _normalize_capability_binding_plan_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise ValueError("capability_binding_plan_invalid")
    base_keys = {
        "schemaVersion", "decisionOwner", "plannerInvocationId", "inventory",
        "executionContextDigest", "toolInventoryDigest",
    }
    if frozenset(plan) not in {frozenset(base_keys), frozenset(base_keys | {"bindingPlanDigest"})}:
        raise ValueError("capability_binding_plan_keys_invalid")
    if plan.get("schemaVersion") != WORKFORCE_CAPABILITY_BINDING_PLAN_SCHEMA:
        raise ValueError("capability_binding_plan_schema_invalid")
    if plan.get("decisionOwner") != "host_llm":
        raise ValueError("capability_binding_plan_owner_invalid")
    planner_invocation_id = plan.get("plannerInvocationId")
    if not isinstance(planner_invocation_id, str) or not _ID_RE.fullmatch(planner_invocation_id):
        raise ValueError("capability_binding_plan_planner_invalid")
    execution_context_digest = plan.get("executionContextDigest")
    tool_inventory_digest = plan.get("toolInventoryDigest")
    if not isinstance(execution_context_digest, str) or not _SHA256_RE.fullmatch(execution_context_digest):
        raise ValueError("capability_binding_plan_execution_context_digest_invalid")
    if not isinstance(tool_inventory_digest, str) or not _SHA256_RE.fullmatch(tool_inventory_digest):
        raise ValueError("capability_binding_plan_tool_inventory_digest_invalid")
    inventory = _validate_bound_inventory(plan.get("inventory"))
    return {
        "schemaVersion": WORKFORCE_CAPABILITY_BINDING_PLAN_SCHEMA,
        "decisionOwner": "host_llm",
        "plannerInvocationId": planner_invocation_id,
        "executionContextDigest": execution_context_digest,
        "toolInventoryDigest": tool_inventory_digest,
        "inventory": inventory,
    }


def workforce_capability_binding_plan_digest(plan: Mapping[str, Any]) -> str:
    normalized = _normalize_capability_binding_plan_payload(plan)
    return _portable_digest({
        "schemaVersion": WORKFORCE_CAPABILITY_BINDING_PLAN_DIGEST_SCHEMA,
        "capabilityBindingPlan": normalized,
    })


def validate_capability_binding_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping) or "bindingPlanDigest" not in plan:
        raise ValueError("capability_binding_plan_keys_invalid")
    normalized = _normalize_capability_binding_plan_payload(plan)
    expected_digest = workforce_capability_binding_plan_digest(normalized)
    if plan.get("bindingPlanDigest") != expected_digest:
        raise ValueError("capability_binding_plan_digest_mismatch")
    return {**normalized, "bindingPlanDigest": expected_digest}


def _capability_assignment_policy_issue(
    assignment: Mapping[str, Any],
    permission_policy: Mapping[str, Any],
) -> str | None:
    provider = assignment.get("provider")
    tool_id = assignment.get("toolId")
    if provider == "mcp":
        mcp_policy = permission_policy.get("mcp")
        if (
            not isinstance(mcp_policy, Mapping)
            or mcp_policy.get("mode") != "allowlist"
            or tool_id not in (mcp_policy.get("allowedTools") or [])
        ):
            return "outside_mcp_policy"
        return None
    if provider == "builtin":
        file_policy = permission_policy.get("fileRead")
        allowed_builtin = {
            "builtin:network": permission_policy.get("network") in {"allow", "ask"},
            "builtin:shell": permission_policy.get("shell") in {"allow", "ask"},
            "builtin:file-read": (
                isinstance(file_policy, Mapping)
                and file_policy.get("mode") == "manifest-allowlist"
            ),
        }
        if allowed_builtin.get(tool_id) is not True:
            return "outside_builtin_policy"
        return None
    return "provider_invalid"


def _candidate_lookup(candidate_set: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for slot in candidate_set.get("slots") or []:
        if not isinstance(slot, Mapping):
            continue
        slot_id = str(slot.get("slotId") or "")
        for candidate in slot.get("candidates") or []:
            if isinstance(candidate, Mapping) and candidate.get("agentReleaseId"):
                result[(slot_id, str(candidate["agentReleaseId"]))] = dict(candidate)
    return result


def prepare_execution_plan(
    *,
    work_order: Mapping[str, Any],
    selection: Mapping[str, Any],
    validation_receipt: Mapping[str, Any],
    candidate_set: Mapping[str, Any],
    runtime_bundles: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Pin the exact selected organization, releases, policies, and graphs."""

    issues: list[str] = []
    if validation_receipt.get("status") != "accepted":
        issues.append("selection_not_accepted")
    if validation_receipt.get("candidateSetDigest") != candidate_set.get("candidateSetDigest"):
        issues.append("candidate_set_digest_mismatch")
    if validation_receipt.get("unfilledPosts"):
        issues.append("selected_team_not_executable")

    context: dict[str, Any] | None = None
    context_digest: str | None = None
    try:
        context = project_execution_context(
            work_order=work_order,
            selection=selection,
            validation_receipt=validation_receipt,
            candidate_set=candidate_set,
        )
        context_digest = workforce_execution_context_digest(context)
    except WorkOrderHubBoundaryError:
        issues.append("work_order_hub_boundary_rejected")
    except ValueError as exc:
        issues.append(str(exc))

    candidates = _candidate_lookup(candidate_set)
    bundles: dict[str, dict[str, Any]] = {}
    for bundle in runtime_bundles:
        if not isinstance(bundle, Mapping) or not bundle.get("agentReleaseId"):
            issues.append("runtime_bundle_identity_invalid")
            continue
        release_id = str(bundle.get("agentReleaseId"))
        if release_id in bundles:
            issues.append(f"runtime_bundle_duplicate:{release_id}")
            continue
        bundles[release_id] = dict(bundle)

    roster: list[dict[str, Any]] = []
    selected_release_ids: set[str] = set()
    for assignment in validation_receipt.get("executableTeam") or []:
        if not isinstance(assignment, Mapping):
            issues.append("invalid_executable_assignment")
            continue
        slot_id = str(assignment.get("slotId") or "")
        release_id = str(assignment.get("agentReleaseId") or "")
        selected_release_ids.add(release_id)
        candidate = candidates.get((slot_id, release_id))
        bundle = bundles.get(release_id)
        if candidate is None:
            issues.append(f"selected_release_missing_from_candidate_set:{slot_id}:{release_id}")
            continue
        if bundle is None:
            issues.append(f"runtime_bundle_missing:{release_id}")
            continue
        for field in ("packageHash", "contentDigest"):
            if bundle.get(field) != candidate.get(field):
                issues.append(f"runtime_bundle_{field}_mismatch:{release_id}")
        directive_bundle = bundle.get("directiveBundle") if isinstance(bundle.get("directiveBundle"), Mapping) else {}
        if not directive_bundle:
            directive_bundle = {
                key: bundle.get(key)
                for key in ("systemPrompt", "instructions", "agentMd")
                if isinstance(bundle.get(key), str) and str(bundle.get(key)).strip()
            }
        if not any(
            isinstance(directive_bundle.get(key), str) and str(directive_bundle[key]).strip()
            for key in ("systemPrompt", "instructions", "agentMd")
        ):
            issues.append(f"runtime_bundle_directive_missing:{release_id}")
            continue
        if bundle.get("status") not in {None, "prepared", "ready"}:
            issues.append(f"runtime_bundle_not_ready:{release_id}")
        try:
            permission_policy = project_permission_policy(bundle)
            permission_digest = workforce_permission_policy_digest(permission_policy)
            execution_graph = project_execution_graph(bundle, entity_kind=str(candidate.get("entityKind") or ""))
            graph_digest = workforce_execution_graph_digest(execution_graph) if execution_graph is not None else None
        except ValueError as exc:
            issues.append(f"{exc}:{release_id}")
            continue
        roster_row = {
            "slotId": slot_id,
            "agentDefinitionId": candidate.get("agentDefinitionId"),
            "agentReleaseId": release_id,
            "releaseVersion": candidate.get("releaseVersion"),
            "packageHash": candidate.get("packageHash"),
            "contentDigest": candidate.get("contentDigest"),
            "entityKind": candidate.get("entityKind"),
            "directiveBundle": dict(directive_bundle),
            "permissionPolicy": permission_policy,
            "permissionPolicyDigest": permission_digest,
            "executionGraph": execution_graph,
            "executionGraphDigest": graph_digest,
        }
        try:
            roster_row["bundleDigest"] = workforce_runtime_bundle_digest(roster_row)
        except ValueError:
            issues.append(f"runtime_bundle_digest_domain_invalid:{release_id}")
            continue
        roster_row["bundleDigestSchema"] = WORKFORCE_RUNTIME_BUNDLE_DIGEST_SCHEMA
        roster.append(roster_row)

    extras = set(bundles) - selected_release_ids
    if extras:
        issues.extend(f"unselected_runtime_bundle:{release_id}" for release_id in sorted(extras))
    issues = sorted(set(issues))
    if issues:
        roster = []

    receipt_payload = {
        "selectionReceiptId": validation_receipt.get("selectionReceiptId"),
        "candidateSetDigest": candidate_set.get("candidateSetDigest"),
        "executionContextDigest": context_digest,
        "executionRoster": roster,
    }
    return {
        "schemaVersion": WORKFORCE_EXECUTION_PLAN_SCHEMA,
        "status": "rejected" if issues else "prepared",
        "issues": issues,
        "preparationReceiptId": "workforce-preparation:" + canonical_digest(receipt_payload).split(":", 1)[1][:32],
        "selectionReceiptId": validation_receipt.get("selectionReceiptId"),
        "candidateSetDigest": candidate_set.get("candidateSetDigest"),
        "decisionOwner": "host_llm",
        "substitutions": [],
        "executionContext": context,
        "executionContextDigest": context_digest,
        "executionRoster": roster,
    }


def _invocation(
    value: Any,
    *,
    label: str,
    issues: list[str],
    invocation_ids: set[str],
    permission_policy_digest: str | None = None,
    expected_tool_inventory_digest: str | None = None,
    expected_granted_tool_ids: list[str] | None = None,
    eligible_runtime_ids: set[str] | None = None,
) -> None:
    if not isinstance(value, Mapping):
        issues.append(f"{label}_invocation_invalid")
        return
    for field in ("invocationId", "modelId", "runtimeId", "provider"):
        if not isinstance(value.get(field), str) or not value.get(field):
            issues.append(f"{label}_{field}_missing")
    invocation_id = str(value.get("invocationId") or "")
    runtime_id = str(value.get("runtimeId") or "")
    if invocation_id:
        if invocation_id in invocation_ids:
            issues.append("duplicate_invocation_id")
        invocation_ids.add(invocation_id)
    if eligible_runtime_ids is not None and runtime_id not in eligible_runtime_ids:
        issues.append(f"{label}_runtime_not_in_tool_inventory")
    if value.get("status") != "completed":
        issues.append(f"{label}_not_completed")
    requested = value.get("requestedEffort")
    applied = value.get("appliedEffort")
    evidence = value.get("effortEvidence")
    if requested not in _EFFORTS or applied not in _EFFORTS or evidence not in _EFFORT_EVIDENCE:
        issues.append(f"{label}_effort_invalid")
    elif evidence == "not-observable" and applied is not None:
        issues.append(f"{label}_unobservable_effort_claimed")
    elif evidence == "runner-reported":
        if applied is None or (requested is not None and requested != applied):
            issues.append(f"{label}_reported_effort_mismatch")
    elif evidence == "runtime-fixed":
        if applied is None or requested is not None:
            issues.append(f"{label}_fixed_effort_invalid")

    if permission_policy_digest is not None:
        enforcement = value.get("permissionEnforcement")
        if not isinstance(enforcement, Mapping):
            issues.append(f"{label}_permission_enforcement_missing")
            return
        if set(enforcement) != {
            "permissionPolicyDigest", "enforcementMode", "status", "approvalReceiptIds",
            "enforcementEvidence",
        }:
            issues.append(f"{label}_permission_enforcement_keys_invalid")
        if enforcement.get("permissionPolicyDigest") != permission_policy_digest:
            issues.append(f"{label}_permission_policy_digest_mismatch")
        if enforcement.get("enforcementMode") not in {
            "native-sandbox", "no-authority-sandbox", "zero-tools"
        }:
            issues.append(f"{label}_permission_mode_invalid")
        if enforcement.get("status") != "enforced":
            issues.append(f"{label}_permission_not_enforced")
        evidence = enforcement.get("enforcementEvidence")
        if not isinstance(evidence, Mapping):
            issues.append(f"{label}_permission_evidence_missing")
        else:
            evidence_keys = {
                "runtimeKind", "runtimeVersion", "sandboxMode", "toolInventory",
                "disabledCapabilities", "ephemeral", "ignoredUserConfig", "ignoredRules",
                "toolInventoryDigest", "grantedToolIds",
            }
            if set(evidence) != evidence_keys:
                issues.append(f"{label}_permission_evidence_keys_invalid")
            if not isinstance(evidence.get("runtimeKind"), str) or not evidence.get("runtimeKind"):
                issues.append(f"{label}_permission_runtime_kind_invalid")
            if evidence.get("runtimeVersion") is not None and (
                not isinstance(evidence.get("runtimeVersion"), str) or not evidence.get("runtimeVersion")
            ):
                issues.append(f"{label}_permission_runtime_version_invalid")
            if evidence.get("sandboxMode") not in {
                "read-only", "no-filesystem", "host-native", "not-applicable"
            }:
                issues.append(f"{label}_permission_sandbox_invalid")
            if evidence.get("toolInventory") not in {"empty", "non-authoritative", "policy-filtered"}:
                issues.append(f"{label}_permission_inventory_invalid")
            if evidence.get("toolInventoryDigest") != expected_tool_inventory_digest:
                issues.append(f"{label}_tool_inventory_digest_mismatch")
            granted_tool_ids = evidence.get("grantedToolIds")
            if (
                not isinstance(granted_tool_ids, list)
                or len(granted_tool_ids) > 128
                or any(
                    not isinstance(item, str) or not _MCP_TOOL_NAME_RE.fullmatch(item)
                    for item in granted_tool_ids
                )
                or len(set(granted_tool_ids)) != len(granted_tool_ids)
            ):
                issues.append(f"{label}_granted_tool_ids_invalid")
            elif (
                expected_granted_tool_ids is not None
                and granted_tool_ids != expected_granted_tool_ids
            ):
                issues.append(f"{label}_granted_tool_ids_mismatch")
            disabled = evidence.get("disabledCapabilities")
            if not isinstance(disabled, list) or len(disabled) > 128 or any(
                not isinstance(item, str) or not _ID_RE.fullmatch(item) for item in disabled
            ) or len(set(disabled)) != len(disabled):
                issues.append(f"{label}_permission_disabled_capabilities_invalid")
            mode = enforcement.get("enforcementMode")
            if mode == "zero-tools" and evidence.get("toolInventory") != "empty":
                issues.append(f"{label}_zero_tools_inventory_not_empty")
            if mode == "no-authority-sandbox" and (
                evidence.get("sandboxMode") not in {"read-only", "no-filesystem"}
                or evidence.get("toolInventory") not in {"empty", "non-authoritative"}
                or not disabled
            ):
                issues.append(f"{label}_no_authority_evidence_invalid")
            if mode in {"zero-tools", "no-authority-sandbox"} and (
                evidence.get("ephemeral") is not True
                or evidence.get("ignoredUserConfig") is not True
                or evidence.get("ignoredRules") is not True
            ):
                issues.append(f"{label}_isolated_runtime_evidence_invalid")
            if mode == "native-sandbox" and evidence.get("toolInventory") != "policy-filtered":
                issues.append(f"{label}_native_policy_filter_missing")
        approvals = enforcement.get("approvalReceiptIds")
        if not isinstance(approvals, list) or len(approvals) > 64 or any(
            not isinstance(item, str) or not _ID_RE.fullmatch(item) for item in approvals
        ) or len(set(approvals)) != len(approvals):
            issues.append(f"{label}_approval_receipts_invalid")
        if enforcement.get("enforcementMode") in {"no-authority-sandbox", "zero-tools"} and approvals:
            issues.append(f"{label}_no_authority_has_approvals")
        granted_tool_ids = evidence.get("grantedToolIds") if isinstance(evidence, Mapping) else None
        if enforcement.get("enforcementMode") in {"no-authority-sandbox", "zero-tools"} and granted_tool_ids:
            issues.append(f"{label}_no_authority_has_granted_tools")


def validate_execution_receipt(
    receipt: Mapping[str, Any],
    *,
    execution_plan: Mapping[str, Any] | None,
    tool_inventory: Mapping[str, Any] | None,
    benchmark_mode: bool = False,
) -> dict[str, Any]:
    """Validate actual direct/nested invocations against one prepared v5 plan."""

    issues: list[str] = []
    normalized_tool_inventory: dict[str, Any] | None = None
    tool_inventory_digest: str | None = None
    try:
        normalized_tool_inventory = validate_tool_inventory(tool_inventory)  # type: ignore[arg-type]
        tool_inventory_digest = workforce_tool_inventory_digest(normalized_tool_inventory)
    except ValueError as exc:
        issues.append(str(exc))
    if execution_plan is None:
        issues.append("missing_execution_plan")
        expected_roster: list[Any] = []
    elif execution_plan.get("schemaVersion") != WORKFORCE_EXECUTION_PLAN_SCHEMA:
        issues.append("unsupported_execution_plan")
        expected_roster = []
    elif execution_plan.get("status") != "prepared":
        issues.append("execution_plan_not_prepared")
        expected_roster = []
    else:
        expected_roster = execution_plan.get("executionRoster") if isinstance(execution_plan.get("executionRoster"), list) else []

    if receipt.get("schemaVersion") != WORKFORCE_EXECUTION_RECEIPT_SCHEMA:
        issues.append("unsupported_execution_receipt")
    if execution_plan is not None:
        if receipt.get("selectionReceiptId") != execution_plan.get("selectionReceiptId"):
            issues.append("selection_receipt_mismatch")
        if receipt.get("preparationReceiptId") != execution_plan.get("preparationReceiptId"):
            issues.append("preparation_receipt_mismatch")
        if receipt.get("executionContextDigest") != execution_plan.get("executionContextDigest"):
            issues.append("execution_context_digest_mismatch")
        context = execution_plan.get("executionContext")
        if not isinstance(context, Mapping) or receipt.get("workOrderId") != context.get("workOrderId"):
            issues.append("execution_context_work_order_mismatch")
        if (
            normalized_tool_inventory is not None
            and normalized_tool_inventory.get("executionContextDigest")
            != execution_plan.get("executionContextDigest")
        ):
            issues.append("tool_inventory_execution_context_digest_mismatch")

    invocation_ids: set[str] = set()
    _invocation(receipt.get("orchestrator"), label="orchestrator", issues=issues, invocation_ids=invocation_ids)
    planner = receipt.get("planner")
    _invocation(planner, label="planner", issues=issues, invocation_ids=invocation_ids)
    if not isinstance(planner, Mapping) or planner.get("parseSuccess") is not True:
        issues.append("planner_structured_output_failed")
    if isinstance(planner, Mapping) and planner.get("fallbackUsed") is True:
        issues.append("planner_fallback_used")

    roster_by_pair = {
        (str(row.get("slotId")), str(row.get("agentReleaseId"))): row
        for row in expected_roster
        if isinstance(row, Mapping)
    }
    execution_context = execution_plan.get("executionContext") if isinstance(execution_plan, Mapping) else {}
    context_slots = {
        str(slot.get("slotId")): slot
        for slot in (execution_context.get("slots") or [])
        if isinstance(slot, Mapping)
    } if isinstance(execution_context, Mapping) else {}

    binding_plan: dict[str, Any] | None = None
    binding_plan_digest: str | None = None
    raw_binding_plan = receipt.get("capabilityBindingPlan")
    if not isinstance(raw_binding_plan, Mapping):
        issues.append("capability_binding_plan_missing")
    else:
        try:
            binding_plan = validate_capability_binding_plan(raw_binding_plan)
            binding_plan_digest = binding_plan["bindingPlanDigest"]
        except ValueError as exc:
            issues.append(str(exc))
    if binding_plan is not None:
        if binding_plan.get("executionContextDigest") != receipt.get("executionContextDigest"):
            issues.append("capability_binding_plan_execution_context_digest_mismatch")
        if binding_plan.get("toolInventoryDigest") != tool_inventory_digest:
            issues.append("capability_binding_plan_tool_inventory_digest_mismatch")
        if not isinstance(planner, Mapping) or (
            binding_plan.get("plannerInvocationId") != planner.get("invocationId")
        ):
            issues.append("capability_binding_plan_planner_mismatch")
        if not isinstance(planner, Mapping) or (
            planner.get("capabilityBindingPlanDigest") != binding_plan_digest
        ):
            issues.append("planner_capability_binding_plan_digest_mismatch")
        if not isinstance(planner, Mapping) or (
            planner.get("toolInventoryDigest") != tool_inventory_digest
        ):
            issues.append("planner_tool_inventory_digest_mismatch")

    planned_bindings_by_pair: dict[tuple[str, str], list[dict[str, str]]] = {}
    eligible_runtime_ids_by_pair: dict[tuple[str, str], set[str] | None] = {}
    external_entries = {
        (
            entry["slotId"], entry["agentReleaseId"], entry["provider"], entry["toolId"],
        ): entry
        for entry in (normalized_tool_inventory or {}).get("entries", [])
    }
    if binding_plan is not None:
        cap_rows_by_pair: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        entry_rows_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for bound_row in binding_plan["inventory"]:
            pair = (bound_row["slotId"], bound_row["agentReleaseId"])
            if pair not in roster_by_pair:
                issues.append("capability_binding_plan_inventory_roster_mismatch")
                continue
            roster_row = roster_by_pair[pair]
            if bound_row["permissionPolicyDigest"] != roster_row.get("permissionPolicyDigest"):
                issues.append(f"capability_binding_plan_permission_scope_mismatch:{pair[0]}")
            external = external_entries.get((
                pair[0], pair[1], bound_row["provider"], bound_row["toolId"],
            ))
            if external is None:
                issues.append(f"capability_binding_plan_tool_absent_from_inventory:{pair[0]}")
            else:
                if external.get("permissionPolicyDigest") != bound_row["permissionPolicyDigest"]:
                    issues.append(f"capability_binding_plan_inventory_policy_mismatch:{pair[0]}")
                if any(
                    capability_id not in external.get("capabilityIds", [])
                    for capability_id in bound_row["capabilityIds"]
                ):
                    issues.append(f"capability_binding_plan_inventory_capability_mismatch:{pair[0]}")
                entry_rows_by_pair.setdefault(pair, []).append(external)
            permission_policy = (
                roster_row.get("permissionPolicy")
                if isinstance(roster_row.get("permissionPolicy"), Mapping)
                else {}
            )
            policy_issue = _capability_assignment_policy_issue(bound_row, permission_policy)
            if policy_issue:
                issues.append(f"capability_binding_plan_{policy_issue}:{pair[0]}:{bound_row['toolId']}")
            cap_map = cap_rows_by_pair.setdefault(pair, {})
            for capability_id in bound_row["capabilityIds"]:
                if capability_id in cap_map:
                    issues.append(f"capability_binding_plan_capability_duplicate:{pair[0]}:{capability_id}")
                else:
                    cap_map[capability_id] = bound_row
        for pair, row in roster_by_pair.items():
            slot_context = context_slots.get(pair[0], {})
            required_capabilities = (
                slot_context.get("requiredToolCapabilities")
                if isinstance(slot_context.get("requiredToolCapabilities"), list)
                else []
            )
            cap_map = cap_rows_by_pair.get(pair, {})
            if set(cap_map) != set(required_capabilities) or len(cap_map) != len(required_capabilities):
                issues.append(f"capability_binding_plan_required_coverage_mismatch:{pair[0]}")
            planned_bindings_by_pair[pair] = [
                {
                    "capabilityId": capability_id,
                    "provider": cap_map[capability_id]["provider"],
                    "toolId": cap_map[capability_id]["toolId"],
                    "source": "host_inventory",
                    "status": "bound",
                }
                for capability_id in required_capabilities
                if capability_id in cap_map
            ]
            selected_entries = entry_rows_by_pair.get(pair, [])
            if selected_entries:
                runtime_sets = [set(entry["runtimeIds"]) for entry in selected_entries]
                eligible = set.intersection(*runtime_sets)
                eligible_runtime_ids_by_pair[pair] = eligible
                if not eligible:
                    issues.append(f"capability_binding_plan_runtime_intersection_empty:{pair[0]}")
            else:
                eligible_runtime_ids_by_pair[pair] = None

    workers = receipt.get("workers") if isinstance(receipt.get("workers"), list) else []
    if len(workers) != len(roster_by_pair) or not workers:
        issues.append("roster_execution_count_mismatch")
    seen_pairs: set[tuple[str, str]] = set()
    nested_refs: dict[str, Mapping[str, Any]] = {}
    for index, worker in enumerate(workers):
        if not isinstance(worker, Mapping):
            issues.append("invalid_roster_execution")
            continue
        pair = (str(worker.get("slotId") or ""), str(worker.get("agentReleaseId") or ""))
        row = roster_by_pair.get(pair)
        if row is None or pair in seen_pairs:
            issues.append("roster_execution_identity_invalid")
            continue
        seen_pairs.add(pair)
        for field in (
            "entityKind", "packageHash", "contentDigest", "bundleDigest",
            "permissionPolicyDigest", "executionGraphDigest",
        ):
            if worker.get(field) != row.get(field):
                issues.append(f"roster_execution_{field}_mismatch")
        if worker.get("status") != "completed":
            issues.append(f"roster_execution_not_completed:{pair[0]}")
        if worker.get("capabilityBindingPlanDigest") != binding_plan_digest:
            issues.append(f"worker_capability_binding_plan_digest_mismatch:{pair[0]}")
        handoffs = worker.get("handoffArtifactRefs")
        if not isinstance(handoffs, list) or not handoffs or any(not isinstance(item, str) or not item for item in handoffs):
            issues.append(f"worker_handoff_missing:{pair[0]}")
        slot_context = context_slots.get(pair[0], {})
        required_capabilities = (
            slot_context.get("requiredToolCapabilities")
            if isinstance(slot_context.get("requiredToolCapabilities"), list)
            else []
        )
        bindings = worker.get("capabilityBindings")
        if not isinstance(bindings, list) or len(bindings) > 256:
            issues.append(f"capability_bindings_invalid:{pair[0]}")
            bindings = []
        if bindings != planned_bindings_by_pair.get(pair, []):
            issues.append(f"capability_binding_plan_worker_drift:{pair[0]}")
        bound_capabilities: list[str] = []
        policy = row.get("permissionPolicy") if isinstance(row.get("permissionPolicy"), Mapping) else {}
        mcp_policy = policy.get("mcp") if isinstance(policy.get("mcp"), Mapping) else {}
        file_policy = policy.get("fileRead") if isinstance(policy.get("fileRead"), Mapping) else {}
        for binding in bindings:
            if not isinstance(binding, Mapping) or set(binding) != {
                "capabilityId", "provider", "toolId", "source", "status"
            }:
                issues.append(f"capability_binding_shape_invalid:{pair[0]}")
                continue
            capability_id = binding.get("capabilityId")
            tool_id = binding.get("toolId")
            provider = binding.get("provider")
            if (
                not isinstance(capability_id, str)
                or not _ID_RE.fullmatch(capability_id)
                or capability_id in bound_capabilities
                or not isinstance(tool_id, str)
                or binding.get("source") != "host_inventory"
                or binding.get("status") != "bound"
            ):
                issues.append(f"capability_binding_value_invalid:{pair[0]}")
                continue
            bound_capabilities.append(capability_id)
            if provider == "mcp" and not _MCP_TOOL_NAME_RE.fullmatch(tool_id):
                issues.append(f"capability_binding_value_invalid:{pair[0]}")
                continue
            if provider == "builtin" and not _ID_RE.fullmatch(tool_id):
                issues.append(f"capability_binding_value_invalid:{pair[0]}")
                continue
            policy_issue = _capability_assignment_policy_issue(binding, policy)
            if policy_issue:
                issues.append(f"capability_binding_{policy_issue}:{pair[0]}:{capability_id}")
        if bound_capabilities != required_capabilities:
            issues.append(f"required_capability_binding_mismatch:{pair[0]}")
        granted_tool_ids = sorted(set(
            binding.get("toolId")
            for binding in planned_bindings_by_pair.get(pair, [])
            if isinstance(binding.get("toolId"), str)
        ))
        eligible_runtime_ids = eligible_runtime_ids_by_pair.get(pair)
        requires_tool_authority = bool(required_capabilities)
        if row.get("executionGraph") is None:
            if worker.get("executionMode") != "direct" or worker.get("nestedExecutionId") is not None:
                issues.append("direct_execution_mode_invalid")
            _invocation(
                worker.get("directInvocation"),
                label=f"direct_worker_{index}",
                issues=issues,
                invocation_ids=invocation_ids,
                permission_policy_digest=str(row.get("permissionPolicyDigest") or ""),
                expected_tool_inventory_digest=tool_inventory_digest,
                expected_granted_tool_ids=granted_tool_ids,
                eligible_runtime_ids=eligible_runtime_ids,
            )
            direct_invocation = worker.get("directInvocation")
            direct_enforcement = (
                direct_invocation.get("permissionEnforcement")
                if isinstance(direct_invocation, Mapping)
                and isinstance(direct_invocation.get("permissionEnforcement"), Mapping)
                else {}
            )
            if requires_tool_authority and direct_enforcement.get("enforcementMode") in {
                "no-authority-sandbox", "zero-tools"
            }:
                issues.append(f"required_capability_executed_without_authority:{pair[0]}")
        else:
            nested_id = worker.get("nestedExecutionId")
            if worker.get("executionMode") != "nested" or worker.get("directInvocation") is not None:
                issues.append("nested_execution_mode_invalid")
            if not isinstance(nested_id, str) or not _ID_RE.fullmatch(nested_id) or nested_id in nested_refs:
                issues.append("nested_execution_reference_invalid")
            else:
                nested_refs[nested_id] = {
                    **row,
                    "_requiresToolAuthority": requires_tool_authority,
                    "_toolInventoryDigest": tool_inventory_digest,
                    "_grantedToolIds": granted_tool_ids,
                    "_eligibleRuntimeIds": eligible_runtime_ids,
                }

    nested = receipt.get("nestedExecutions") if isinstance(receipt.get("nestedExecutions"), list) else []
    if len(nested) != len(nested_refs):
        issues.append("nested_execution_count_mismatch")
    seen_nested: set[str] = set()
    for nested_index, item in enumerate(nested):
        if not isinstance(item, Mapping):
            issues.append("nested_execution_invalid")
            continue
        nested_id = str(item.get("nestedExecutionId") or "")
        row = nested_refs.get(nested_id)
        if row is None or nested_id in seen_nested:
            issues.append("nested_execution_identity_invalid")
            continue
        seen_nested.add(nested_id)
        for field in ("slotId", "agentReleaseId", "bundleDigest", "permissionPolicyDigest", "executionGraphDigest"):
            if item.get(field) != row.get(field):
                issues.append(f"nested_execution_{field}_mismatch")
        if item.get("status") != "completed":
            issues.append("nested_execution_not_completed")
        permission_digest = str(row.get("permissionPolicyDigest") or "")
        graph = row.get("executionGraph") if isinstance(row.get("executionGraph"), Mapping) else {}
        expected_graph_workers = graph.get("workers") if isinstance(graph.get("workers"), list) else []
        expected_worker_ids = [
            worker.get("id") for worker in expected_graph_workers if isinstance(worker, Mapping)
        ]
        manager_plan = item.get("managerPlan")
        _invocation(
            manager_plan,
            label=f"nested_{nested_index}_manager_plan",
            issues=issues,
            invocation_ids=invocation_ids,
            permission_policy_digest=permission_digest,
            expected_tool_inventory_digest=row.get("_toolInventoryDigest"),
            expected_granted_tool_ids=row.get("_grantedToolIds"),
            eligible_runtime_ids=row.get("_eligibleRuntimeIds"),
        )
        if not isinstance(manager_plan, Mapping) or manager_plan.get("parseSuccess") is not True:
            issues.append("nested_manager_plan_structured_output_failed")
        if isinstance(manager_plan, Mapping) and manager_plan.get("fallbackUsed") is not False:
            issues.append("nested_manager_plan_fallback_used")
        if not isinstance(manager_plan, Mapping) or manager_plan.get("plannedWorkerIds") != expected_worker_ids:
            issues.append("nested_manager_plan_worker_order_mismatch")
        nested_actual_invocations: list[Mapping[str, Any]] = [
            manager_plan if isinstance(manager_plan, Mapping) else {}
        ]
        actual_graph_workers = item.get("workers") if isinstance(item.get("workers"), list) else []
        if [worker.get("id") for worker in actual_graph_workers if isinstance(worker, Mapping)] != expected_worker_ids:
            issues.append("nested_worker_order_or_identity_mismatch")
        if len(actual_graph_workers) != len(expected_graph_workers):
            issues.append("nested_worker_count_mismatch")
        for worker_index, graph_worker in enumerate(actual_graph_workers):
            if not isinstance(graph_worker, Mapping):
                issues.append("nested_worker_invalid")
                continue
            _invocation(
                graph_worker,
                label=f"nested_{nested_index}_worker_{worker_index}",
                issues=issues,
                invocation_ids=invocation_ids,
                permission_policy_digest=permission_digest,
                expected_tool_inventory_digest=row.get("_toolInventoryDigest"),
                expected_granted_tool_ids=row.get("_grantedToolIds"),
                eligible_runtime_ids=row.get("_eligibleRuntimeIds"),
            )
            nested_actual_invocations.append(graph_worker)
        manager_synthesis = item.get("managerSynthesis")
        _invocation(
            manager_synthesis,
            label=f"nested_{nested_index}_manager_synthesis",
            issues=issues,
            invocation_ids=invocation_ids,
            permission_policy_digest=permission_digest,
            expected_tool_inventory_digest=row.get("_toolInventoryDigest"),
            expected_granted_tool_ids=row.get("_grantedToolIds"),
            eligible_runtime_ids=row.get("_eligibleRuntimeIds"),
        )
        if isinstance(manager_synthesis, Mapping):
            nested_actual_invocations.append(manager_synthesis)
        if row.get("_requiresToolAuthority") is True and any(
            isinstance(invocation.get("permissionEnforcement"), Mapping)
            and invocation["permissionEnforcement"].get("enforcementMode")
            in {"no-authority-sandbox", "zero-tools"}
            for invocation in nested_actual_invocations
        ):
            issues.append(f"required_capability_executed_without_authority:{row.get('slotId')}")

    _invocation(receipt.get("synthesis"), label="synthesis", issues=issues, invocation_ids=invocation_ids)
    verifier = receipt.get("verifier")
    _invocation(verifier, label="verifier", issues=issues, invocation_ids=invocation_ids)
    if not isinstance(verifier, Mapping) or verifier.get("verdict") != "pass":
        issues.append("verifier_did_not_pass")
    if benchmark_mode and len(workers) < 2:
        issues.append("benchmark_requires_multiple_workers")
    if receipt.get("status") != "passed":
        issues.append("execution_not_passed")
    if receipt.get("status") == "passed" and issues:
        issues.append("false_pass_claim")
    return {
        "schemaVersion": "agentlas.workforce-execution-validation.v2",
        "status": "rejected" if issues else "accepted",
        "issues": sorted(set(issues)),
        "executionId": receipt.get("executionId"),
        "validatedDigest": canonical_digest(receipt),
    }


__all__ = [
    "WORKFORCE_CAPABILITY_BINDING_PLAN_DIGEST_SCHEMA",
    "WORKFORCE_CAPABILITY_BINDING_PLAN_SCHEMA",
    "WORKFORCE_EXECUTION_CONTEXT_DIGEST_SCHEMA",
    "WORKFORCE_EXECUTION_CONTEXT_SCHEMA",
    "WORKFORCE_EXECUTION_GRAPH_DIGEST_SCHEMA",
    "WORKFORCE_EXECUTION_GRAPH_SCHEMA",
    "WORKFORCE_EXECUTION_PLAN_SCHEMA",
    "WORKFORCE_EXECUTION_RECEIPT_SCHEMA",
    "WORKFORCE_PERMISSION_POLICY_DIGEST_SCHEMA",
    "WORKFORCE_PERMISSION_POLICY_SCHEMA",
    "WORKFORCE_RUNTIME_BUNDLE_DIGEST_SCHEMA",
    "WORKFORCE_TOOL_INVENTORY_DIGEST_SCHEMA",
    "WORKFORCE_TOOL_INVENTORY_SCHEMA",
    "deny_all_permission_policy",
    "prepare_execution_plan",
    "project_execution_context",
    "project_execution_graph",
    "project_permission_policy",
    "validate_execution_graph",
    "validate_execution_receipt",
    "validate_capability_binding_plan",
    "validate_tool_inventory",
    "validate_permission_policy",
    "validate_workforce_digest_value",
    "workforce_execution_context_canonical_json",
    "workforce_execution_context_digest",
    "workforce_capability_binding_plan_digest",
    "workforce_tool_inventory_digest",
    "workforce_execution_graph_canonical_json",
    "workforce_execution_graph_digest",
    "workforce_permission_policy_canonical_json",
    "workforce_permission_policy_digest",
    "workforce_runtime_bundle_canonical_json",
    "workforce_runtime_bundle_digest",
]
