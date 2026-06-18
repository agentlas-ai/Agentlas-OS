"""Validation for AO graph + grammar + rule evaluation."""

from __future__ import annotations

from collections import defaultdict
import re
from pathlib import Path
from typing import Any

from .loader import load_graph, load_grammar


def validate_graph(project_root: str | Path | None = None) -> dict[str, Any]:
    context = load_graph(project_root or ".")
    graph = context["graph"]
    grammar = context.get("grammar") or load_grammar(project_root or ".")

    errors: list[str] = []
    warnings: list[str] = []
    blocked_edges: list[dict[str, Any]] = []

    node_index: dict[str, dict[str, Any]] = {
        str(node.get("id")): node
        for node in graph.get("agents", []) + graph.get("artifacts", []) + graph.get("scopes", [])
        if str(node.get("id") or "").strip()
    }
    for capability in graph.get("capabilities", []):
        capability_id = str(capability).strip()
        if capability_id:
            node_index[f"capability:{capability_id}"] = {"id": f"capability:{capability_id}", "type": "Capability", "name": capability_id}

    agent_type_lookup: dict[str, str] = {}
    for node_id, node in node_index.items():
        node_id = str(node_id or "")
        if not node_id:
            continue
        node_type = str(node.get("type") or "")
        if node_type:
            agent_type_lookup[node_id] = node_type
            continue
        if node.get("id", "").startswith("artifact:") or str(node_id).startswith("capability:"):
            agent_type_lookup[node_id] = str(node.get("type") or "Artifact")
        else:
            agent_type_lookup[node_id] = "Unknown"

    for node in graph.get("agents", []):
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            errors.append("agent node missing id")
            continue
        node_type = str(node.get("type") or "")
        allowed_agent_types = set(grammar.get("node_types", {}).get("agent", []))
        if node_type not in allowed_agent_types:
            errors.append(f"agent {node_id}: unknown type {node_type}")

    for artifact in graph.get("artifacts", []):
        artifact_type = str(artifact.get("type") or "Artifact")
        if artifact_type != "Artifact":
            warnings.append(f"artifact {artifact.get('id')}: type coerced to Artifact")
            artifact["type"] = "Artifact"

    allowed_types = {str(rule.get("relation")): (tuple(rule.get("from", [])), tuple(rule.get("to", []))) for rule in grammar.get("relation_rules", []) if rule.get("relation")}

    for edge in graph.get("edges", []):
        from_id = str(edge.get("from") or "")
        to_id = str(edge.get("to") or "")
        relation = str(edge.get("relation") or edge.get("kind") or "")

        if edge.get("invalid"):
            errors.append(f"invalid edge record: {edge}")
            continue
        if from_id not in node_index:
            errors.append(f"edge {relation}: unknown from id {from_id}")
            continue
        if to_id not in node_index:
            errors.append(f"edge {relation}: unknown to id {to_id}")
            continue

        from_type = str(node_index.get(from_id, {}).get("type") or "")
        to_type = str(node_index.get(to_id, {}).get("type") or "")

        if relation not in allowed_types:
            warnings.append(f"edge relation '{relation}' has no grammar rule; skipped strict validation")
            continue
        allowed_from, allowed_to = allowed_types[relation]
        if allowed_from and from_type not in allowed_from and "*" not in allowed_from:
            errors.append(f"edge {relation}: from-type {from_type} not allowed -> {from_id}")
        if allowed_to and to_type not in allowed_to and "*" not in allowed_to:
            errors.append(f"edge {relation}: to-type {to_type} not allowed -> {to_id}")

        if edge_is_blocked(edge=edge, node_index=node_index, grammar=grammar):
            blocked_edges.append(edge)

    # Deny-violating edges and unmet require-rules are hard errors: `ao lint`
    # must fail and a commit must be blocked (plan §2.3). They remain listed in
    # blocked_edges / require_violations for machine inspection.
    for blocked in blocked_edges:
        errors.append(
            "deny-violating edge: "
            f"{blocked.get('from')} -[{blocked.get('relation') or blocked.get('kind')}]-> {blocked.get('to')}"
        )

    require_violations = list(_check_requirements(graph.get("edges", []), node_index, grammar))
    for violation in require_violations:
        errors.append(violation["message"])

    registered_capabilities = set(grammar.get("capabilities", []))
    for cap in graph.get("capabilities", []):
        if not isinstance(cap, str) or not cap.strip():
            errors.append(f"capability malformed: {cap}")
            continue
        if cap not in registered_capabilities and cap not in {"capability", "capabilities"}:
            warnings.append(f"unregistered capability: {cap}")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "blocked_edges": blocked_edges,
        "require_violations": require_violations,
        "counts": context.get("counts", {
            "agents": len(graph.get("agents", [])),
            "artifacts": len(graph.get("artifacts", [])),
            "capabilities": len(graph.get("capabilities", [])),
            "edges": len(graph.get("edges", [])),
        }),
        "node_index": node_index,
        "grammar": grammar,
    }


def _check_requirements(
    edges: list[dict[str, Any]],
    node_index: dict[str, dict[str, Any]],
    grammar: dict[str, Any],
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    outgoing = defaultdict(list)
    for edge in edges:
        outgoing[str(edge.get("from") or "")].append(edge)

    for edge in edges:
        edge_context = _with_node_context(edge, node_index)
        for rule in grammar.get("require", []):
            if _evaluate_condition(rule.get("if"), edge_context):
                requirement = str(rule.get("then", "")).strip()
                if not requirement:
                    continue
                if requirement.startswith("requires_approval_from("):
                    target = _inside_parens(requirement)
                    from_edges = outgoing.get(str(edge.get("from") or ""), [])
                    has_target = any(
                        (from_edge.get("relation") == "requires_approval_from")
                        and _node_type(from_edge.get("to"), node_index) == target
                        for from_edge in from_edges
                    )
                    if not has_target:
                        violations.append(
                            {"edge": edge, "message": f"requirement not met: {edge} -> {requirement}"}
                        )
                elif requirement.startswith("exists "):
                    inside = requirement[len("exists ") :].strip()
                    relation = inside.split("(")[0].strip()
                    # `exists rel(to)` anchors on the edge's TARGET node's outgoing
                    # edges; `exists rel` (or `(from)`) anchors on the source.
                    anchor = str(edge.get("to") or "") if "(to)" in inside else str(edge.get("from") or "")
                    has_relation = any(
                        other.get("relation") == relation for other in outgoing.get(anchor, [])
                    )
                    if not has_relation:
                        violations.append(
                            {"edge": edge, "message": f"requirement not met: {edge} -> {requirement}"}
                        )
    return violations


def _node_type(node_id: str, node_index: dict[str, dict[str, Any]]) -> str:
    return str(node_index.get(str(node_id), {}).get("type") or "")


def _inside_parens(text: str) -> str:
    match = re.search(r"\((.*)\)", text or "")
    if not match:
        return ""
    return match.group(1).strip().strip("\"'")


def _evaluate_condition(condition: str | None, edge_context: dict[str, Any]) -> bool:
    """Evaluate a grammar condition.

    Supports a small, deterministic boolean subset: clauses joined by ``and``
    (all must hold) or ``or`` (any must hold), where each clause is a single
    ``==`` / ``!=`` comparison (or the ``edge.kind == "shared_memory_write"``
    special form). No arbitrary code execution.
    """
    if not condition:
        return False

    expression = condition.strip()
    # `and` binds tighter than `or` (standard precedence): split on `or` first.
    if " or " in expression:
        return any(_evaluate_condition(part, edge_context) for part in expression.split(" or "))
    if " and " in expression:
        return all(_evaluate_clause(part, edge_context) for part in expression.split(" and "))
    return _evaluate_clause(expression, edge_context)


def _evaluate_clause(clause: str, edge_context: dict[str, Any]) -> bool:
    expression = (clause or "").strip()
    # Tolerate wrapping parentheses around a single clause.
    while expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    if not expression:
        return False
    if expression == "edge.kind == \"shared_memory_write\"":
        return str(edge_context.get("edge_kind") or edge_context.get("relation") or "").strip() == "shared_memory_write"

    match = re.match(r"(.+?)\s*(==|!=)\s*(.+)", expression)
    if not match:
        return False

    left_text, op, right_text = match.groups()
    left = _value_for_path(left_text.strip(), context=edge_context)
    right = _value_for_path(right_text.strip(), context=edge_context)
    if left is None or right is None:
        return False
    return left == right if op == "==" else left != right


def _value_for_path(expr: str, context: dict[str, Any]) -> Any:
    if expr == "relation":
        return context.get("relation")
    if expr in {"edge", "edge.relation"}:
        return context.get("relation")
    if expr == "edge.kind":
        return context.get("edge_kind")
    if expr == "from":
        return str(context.get("from") or "")
    if expr == "to":
        return str(context.get("to") or "")
    if expr == "from.type":
        return _node_type(context.get("from"), context.get("node_index", {}))
    if expr == "to.type":
        return _node_type(context.get("to"), context.get("node_index", {}))
    if expr == "from.member_of":
        return str(context.get("from_node", {}).get("member_of", "") or "")
    if expr == "to.member_of":
        return str(context.get("to_node", {}).get("member_of", "") or "")
    if expr in {"True", "true", "False", "false"}:
        return expr.lower() == "true"
    quoted = expr.strip()
    if (quoted.startswith("\"") and quoted.endswith("\"")) or (quoted.startswith("'") and quoted.endswith("'")):
        return quoted[1:-1]
    return quoted


def _with_node_context(edge: dict[str, Any], node_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    from_node_id = str(edge.get("from") or "")
    to_node_id = str(edge.get("to") or "")
    return {
        "from": from_node_id,
        "to": to_node_id,
        "relation": str(edge.get("relation") or edge.get("kind") or ""),
        "edge_kind": str(edge.get("kind") or edge.get("relation") or ""),
        "node_index": node_index,
        "from_node": node_index.get(from_node_id, {}),
        "to_node": node_index.get(to_node_id, {}),
    }


def evaluate_requirements(
    edge: dict[str, Any],
    node_index: dict[str, dict[str, Any]] | None = None,
    grammar: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return unmet ``require``-grammar violations for a single graph edge."""

    if grammar is None:
        grammar = load_grammar(".")
    if node_index is None:
        data = load_graph(".")
        merged_nodes = data.get("graph", {}).get("agents", []) + data.get("graph", {}).get("artifacts", [])
        node_index = {str(node.get("id") or ""): node for node in merged_nodes if node.get("id") is not None}
        for cap in data.get("graph", {}).get("capabilities", []):
            if str(cap).strip():
                node_index[f"capability:{cap}"] = {"id": f"capability:{cap}", "type": "Capability"}

    return list(_check_requirements([edge], node_index, grammar))


def explain_edge_gate(
    edge: dict[str, Any],
    node_index: dict[str, dict[str, Any]] | None = None,
    grammar: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect AO gate checks in a single payload for routing evidence."""

    blocked_by: list[str] = []
    if edge_is_blocked(edge=edge, node_index=node_index, grammar=grammar):
        resolved_index = node_index or _node_index_for_edge(edge)
        context = _with_node_context(edge, resolved_index)
        blocked_by.append(
            "deny rule matched: "
            + " -> ".join([
                str(context.get("from")),
                str(context.get("relation")),
                str(context.get("to")),
            ])
        )
    unmet = evaluate_requirements(edge=edge, node_index=node_index, grammar=grammar)
    return {"blocked_by": blocked_by, "requirement_violations": unmet}


def edge_is_blocked(
    edge: dict[str, Any],
    node_index: dict[str, dict[str, Any]] | None = None,
    grammar: dict[str, Any] | None = None,
) -> bool:
    if grammar is None:
        grammar = load_grammar(".")
    if node_index is None:
        data = load_graph(".")
        merged_nodes = data.get("graph", {}).get("agents", []) + data.get("graph", {}).get("artifacts", [])
        node_index = {str(node.get("id") or ""): node for node in merged_nodes if node.get("id") is not None}
        for cap in data.get("graph", {}).get("capabilities", []):
            if str(cap).strip():
                node_index[f"capability:{cap}"] = {"id": f"capability:{cap}", "type": "Capability"}

    context = _with_node_context(edge, node_index)
    from_type = _node_type(context["from"], node_index)
    to_type = _node_type(context["to"], node_index)

    for rule in grammar.get("deny", []):
        if str(rule.get("from") or "") != from_type:
            continue
        if str(rule.get("relation") or "") != str(context["relation"]):
            continue
        if str(rule.get("to") or "") != to_type:
            continue
        if not rule.get("when"):
            return True
        if _evaluate_condition(str(rule["when"]), context):
            return True
    return False


def _node_index_for_edge(edge: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = load_graph(".")
    merged_nodes = data.get("graph", {}).get("agents", []) + data.get("graph", {}).get("artifacts", [])
    node_index = {str(node.get("id") or ""): node for node in merged_nodes if node.get("id") is not None}
    for cap in data.get("graph", {}).get("capabilities", []):
        if str(cap).strip():
            node_index[f"capability:{cap}"] = {"id": f"capability:{cap}", "type": "Capability"}
    if not (str(edge.get("from") or "") in node_index):
        node_index[str(edge.get("from") or "")] = {"id": str(edge.get("from") or ""), "type": "Unknown"}
    if not (str(edge.get("to") or "") in node_index):
        node_index[str(edge.get("to") or "")] = {"id": str(edge.get("to") or ""), "type": "Unknown"}
    return node_index
