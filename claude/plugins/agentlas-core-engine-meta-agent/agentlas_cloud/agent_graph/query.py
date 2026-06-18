"""Query helpers for Agent Ontology (AO) graphs."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from .loader import AGENT_ONTOLOGY_DIR, _artifact_id, load_graph
from .validator import edge_is_blocked


def _as_graph(project_root: str | Path | dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if isinstance(project_root, dict):
        graph_data = project_root
    else:
        graph_data = load_graph(project_root)
    graph = graph_data.get("graph", graph_data)
    agents = list(graph.get("agents", []))
    artifacts = list(graph.get("artifacts", []))
    scopes = list(graph.get("scopes", []))
    edges = list(graph.get("edges", []))
    node_index: dict[str, dict[str, Any]] = {
        str(node.get("id")): node
        for node in agents + artifacts + scopes
        if node.get("id")
    }
    for cap in graph_data.get("capabilities", graph.get("capabilities", [])):
        if str(cap).strip():
            node_id = f"capability:{cap}"
            node_index[node_id] = {"id": node_id, "type": "Capability", "name": cap}
    return graph, node_index, edges


def describe_graph(project_root: str | Path = ".") -> dict[str, Any]:
    """Return compact graph counts and metadata.

    This helper is intentionally light and CLI-friendly.
    """

    graph_data = load_graph(project_root)
    graph = graph_data.get("graph", graph_data)
    relation_counts: dict[str, int] = {}
    for edge in graph.get("edges", []):
        relation = str(edge.get("relation") or edge.get("kind") or "unknown")
        relation_counts[relation] = relation_counts.get(relation, 0) + 1
    artifact_kinds = sorted({str(artifact.get("kind") or artifact.get("id") or "").removeprefix("artifact:") for artifact in graph.get("artifacts", [])})
    return {
        "path": str(Path(project_root) / ".agentlas" / AGENT_ONTOLOGY_DIR),
        "warnings": graph_data.get("warnings", []),
        "errors": graph_data.get("errors", []),
        "counts": {
            "agents": len(graph.get("agents", [])),
            "artifacts": len(graph.get("artifacts", [])),
            "capabilities": len(graph.get("capabilities", [])),
            "scopes": len(graph.get("scopes", [])),
            "edges": len(graph.get("edges", [])),
        },
        "relation_counts": relation_counts,
        "artifact_kinds": artifact_kinds,
    }


def _artifact_lookup(graph: dict[str, Any], artifact: str) -> str:
    artifact_id = (artifact or "").strip()
    if not artifact_id:
        return ""
    if artifact_id.startswith("artifact:"):
        return artifact_id
    if any(item.get("id") == artifact_id for item in graph.get("artifacts", [])):
        return artifact_id
    return _artifact_id(artifact_id)


def who_produces(
    project_root: str | Path | dict[str, Any],
    artifact: str,
) -> list[dict[str, str]]:
    """Return agents that have a ``produces`` edge to an artifact."""

    graph, _, edges = _as_graph(project_root)
    target = _artifact_lookup(graph, artifact)
    results = []
    for edge in edges:
        if str(edge.get("relation") or edge.get("kind")) != "produces":
            continue
        if str(edge.get("to")) != target:
            continue
        source = str(edge.get("from") or "")
        if source:
            results.append({"agent": source, "artifact": target, "edge": edge.get("kind") or edge.get("relation") or "produces"})
    return results


def who_consumes(
    project_root: str | Path | dict[str, Any],
    artifact: str,
) -> list[dict[str, str]]:
    """Return agents that have a ``consumes`` edge to an artifact."""

    graph, _, edges = _as_graph(project_root)
    target = _artifact_lookup(graph, artifact)
    results = []
    for edge in edges:
        if str(edge.get("relation") or edge.get("kind")) != "consumes":
            continue
        if str(edge.get("to")) != target:
            continue
        source = str(edge.get("from") or "")
        if source:
            results.append({"agent": source, "artifact": target, "edge": edge.get("kind") or edge.get("relation") or "consumes"})
    return results


def is_blocked(edge: dict[str, Any], project_root: str | Path | None = None) -> bool:
    """Check whether an edge violates any deny rule."""

    node_index = None
    grammar = None
    if project_root is not None:
        graph_data = load_graph(project_root)
        graph = graph_data.get("graph", graph_data)
        node_index = {str(node.get("id")): node for node in graph.get("agents", []) + graph.get("artifacts", [])}
        for capability in graph_data.get("capabilities", graph.get("capabilities", [])):
            if str(capability).strip():
                node_index[f"capability:{capability}"] = {"id": f"capability:{capability}", "type": "Capability"}
        grammar = graph_data.get("grammar")
    return edge_is_blocked(edge=edge, node_index=node_index, grammar=grammar)


def reachable(
    project_root: str | Path | dict[str, Any],
    start: str,
    target: str,
    max_depth: int = 6,
    relation: str | None = None,
    allow_blocked: bool = False,
) -> list[dict[str, Any]]:
    """Return one shortest path from start to target as edge objects."""

    if max_depth < 1:
        return []
    graph, _, edges = _as_graph(project_root)
    start = str(start or "")
    target = str(target or "")
    if not start or not target:
        return []
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        rel = str(edge.get("relation") or edge.get("kind") or "")
        if relation is not None and rel != relation:
            continue
        from_id = str(edge.get("from") or "")
        to_id = str(edge.get("to") or "")
        if not from_id or not to_id:
            continue
        if not allow_blocked and is_blocked(edge=edge, project_root=project_root):
            continue
        adjacency.setdefault(from_id, []).append({"to": to_id, "edge": edge})
    queue = deque([(start, [])])
    visited = {start}
    while queue:
        node_id, path = queue.popleft()
        if len(path) >= max_depth:
            continue
        for item in adjacency.get(node_id, []):
            edge = item["edge"]
            next_node = item["to"]
            next_path = path + [edge]
            if next_node == target:
                return next_path
            if next_node not in visited:
                visited.add(next_node)
                queue.append((next_node, next_path))
    return []


def _query_matches(graph: dict[str, Any], condition: str, node_ids: set[str], project_root: str | Path | dict[str, Any]) -> set[str]:
    token = condition.strip()
    if not token:
        return set(node_ids)
    negated = token.lower().startswith("not ")
    if negated:
        token = token[4:].strip()
    if not token:
        return set(node_ids)

    result: set[str] = set()
    if ":" in token:
        field, value = token.split(":", 1)
        field = field.strip().lower()
        value = value.strip()
        target = value.lower()

        if field == "type":
            for node_id in node_ids:
                if str(graph.get("node_index", {}).get(node_id, {}).get("type", "")).lower() == target:
                    result.add(node_id)
        elif field == "produces":
            for hit in who_produces(graph, value):
                result.add(hit["agent"])
        elif field == "consumes":
            for hit in who_consumes(graph, value):
                result.add(hit["agent"])
        elif field == "id":
            target = value.lower()
            for node_id in node_ids:
                if node_id.lower() == target:
                    result.add(node_id)
        elif field == "blocked_from":
            candidate: set[str] = set()
            _, _, edges = _as_graph(graph)
            blocked_by = f"{value}"
            for edge in edges:
                if str(edge.get("relation") or edge.get("kind")) != "blocked_from":
                    continue
                if str(edge.get("to")).lower() == blocked_by.lower():
                    candidate.add(str(edge.get("from") or ""))
            for node_id in node_ids:
                if node_id in candidate:
                    result.add(node_id)
        else:
            # Unsupported conditions apply only when explicitly declared, otherwise
            # they are considered non-matching.
            result = set()
    else:
        token_l = token.lower()
        for node_id in node_ids:
            node = graph.get("node_index", {}).get(node_id, {})
            if token_l in str(node.get("name", "")).lower() or token_l in str(node.get("type", "")).lower():
                result.add(node_id)

    return set(node_ids) - result if negated else result


def execute_query(query: str, project_root: str | Path | dict[str, Any] = ".") -> dict[str, Any]:
    """Execute a tiny AO query language.

    Supported syntax: ``field:value`` filters chained with ``and``, each
    optionally negated with a leading ``not``. ``or`` and parentheses are NOT
    supported; if present they are reported as a warning rather than silently
    treated as a match.

    Supported examples:
    - ``produces:plan``
    - ``consumes:prd and not blocked_from:caller``
    - ``type:Specialist and produces:codebase_change``
    """

    query_text = (query or "").strip()
    if not query_text:
        return {"query": "", "matches": [], "count": 0}

    graph, node_index, _ = _as_graph(project_root)
    graph["node_index"] = node_index

    # We only support chainable filters with "and".
    conditions = [part.strip() for part in query_text.split(" and ")]
    candidates = set(node_index.keys())
    warnings: list[str] = []
    if " or " in f" {query_text} " or "(" in query_text or ")" in query_text:
        warnings.append(
            "unsupported syntax: only 'and'/'not' filters are supported; 'or' and parentheses are ignored"
        )

    for condition in conditions:
        if not condition:
            continue
        matched = _query_matches(graph, condition, candidates if candidates else set(node_index.keys()), graph)
        candidates = matched
        if not candidates:
            break

    results = []
    for node_id in sorted(candidates):
        node = node_index.get(node_id, {})
        if not isinstance(node, dict):
            continue
        results.append(
            {
                "id": node_id,
                "type": node.get("type"),
                "name": node.get("name") or node_id.split("/")[-1],
                "matched_on": query_text,
                "member_of": node.get("member_of"),
            }
        )
    if not candidates:
        warnings.append("query empty")
    return {
        "query": query_text,
        "count": len(results),
        "matches": results,
        "warnings": warnings,
        "unmatched_fields": [],
    }


def plan_path(
    project_root: str | Path | dict[str, Any],
    start: str,
    target: str,
    max_depth: int = 5,
    relation: str | None = None,
    allow_blocked: bool = False,
) -> dict[str, Any]:
    """Return AO path metadata from start to target."""

    path_edges = reachable(project_root, start, target, max_depth=max_depth, relation=relation, allow_blocked=allow_blocked)
    if not path_edges:
        return {
            "start": str(start),
            "target": str(target),
            "found": False,
            "length": 0,
            "edges": [],
        }
    return {
        "start": str(start),
        "target": str(target),
        "found": True,
        "length": len(path_edges),
        "edges": [
            {
                "from": str(edge.get("from")),
                "to": str(edge.get("to")),
                "relation": str(edge.get("relation") or edge.get("kind") or ""),
            }
            for edge in path_edges
        ],
    }


def plan_pipeline_ao(
    project_root: str | Path | dict[str, Any],
    target_artifact: str,
    max_stages: int = 12,
) -> dict[str, Any]:
    """Plan a multi-stage pipeline by traversing produces/consumes edges (Phase 0).

    Given a goal artifact, walk backward: the agent that *produces* it, then the
    agents that produce what *that* agent *consumes*, and so on — yielding an
    upstream-first ordered chain of stages. This replaces hard-coded stage
    intent with real AO graph reasoning.
    """

    graph, _, edges = _as_graph(project_root)
    target = _artifact_lookup(graph, target_artifact)

    def producers(artifact_id: str) -> list[str]:
        return [
            str(e.get("from"))
            for e in edges
            if str(e.get("relation") or e.get("kind")) == "produces" and str(e.get("to")) == artifact_id
        ]

    def consumes_of(agent_id: str) -> list[str]:
        return [
            str(e.get("to"))
            for e in edges
            if str(e.get("relation") or e.get("kind")) == "consumes" and str(e.get("from")) == agent_id
        ]

    stages: list[dict[str, Any]] = []
    visited: set[str] = set()
    queue: list[str] = [target]
    while queue and len(stages) < max_stages:
        artifact = queue.pop(0)
        for agent in producers(artifact):
            if agent in visited:
                continue
            visited.add(agent)
            consumed = consumes_of(agent)
            stages.append({"agent": agent, "produces": artifact, "consumes": consumed})
            queue.extend(consumed)

    stages.reverse()  # upstream-first execution order
    return {
        "target": target,
        "found": bool(stages),
        "length": len(stages),
        "stages": stages,
    }
