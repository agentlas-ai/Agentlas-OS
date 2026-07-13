"""Load and normalize Agent Ontology (AO) materials.

Loads canonical AO JSONL and returns a normalized in-memory shape consumed by
query/validator/CLI tooling.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

AGENT_ONTOLOGY_DIR = "agent-ontology"


DEFAULT_GRAMMAR: dict[str, Any] = {
    "schemaVersion": "0.1",
    "node_types": {
        "agent": [
            "Orchestrator",
            "HRDirector",
            "PMSoul",
            "MemoryCurator",
            "PolicyGate",
            "Specialist",
            "EvalJudge",
            "QAGate",
            "RuntimeArchitect",
            "SitemapRouter",
            "ExternalAgent",
        ],
        "artifact": ["Artifact"],
        "capability": ["Capability"],
        "scope": ["MemoryScope"],
    },
    "relation_rules": [
        {
            "relation": "member_of",
            "from": ["Specialist", "PMSoul", "MemoryCurator", "QAGate", "EvalJudge", "SitemapRouter", "RuntimeArchitect", "HRDirector", "Orchestrator"],
            "to": ["HRDirector", "Orchestrator"],
        },
        {
            "relation": "supervises",
            "from": ["Orchestrator", "HRDirector"],
            "to": ["Specialist", "PMSoul", "MemoryCurator", "PolicyGate", "EvalJudge", "QAGate", "RuntimeArchitect", "SitemapRouter"],
        },
        {
            "relation": "routes_to",
            "from": ["Orchestrator", "HRDirector", "PMSoul"],
            "to": ["Specialist", "SitemapRouter", "ExternalAgent"],
        },
        {
            "relation": "delegates_to",
            "from": ["Orchestrator", "HRDirector", "PMSoul"],
            "to": ["Specialist", "SitemapRouter", "PMSoul"],
        },
        {
            "relation": "can_invoke",
            "from": ["Orchestrator", "HRDirector", "Specialist", "RuntimeArchitect", "ExternalAgent"],
            "to": ["ExternalAgent"],
        },
        {"relation": "hands_off_to", "from": ["Orchestrator", "HRDirector", "PMSoul", "Specialist"], "to": ["Specialist", "PMSoul"]},
        {
            "relation": "produces",
            "from": ["Specialist", "PMSoul", "Orchestrator", "HRDirector", "RuntimeArchitect", "MemoryCurator", "PolicyGate", "EvalJudge", "QAGate", "SitemapRouter"],
            "to": ["Artifact"],
        },
        {
            "relation": "consumes",
            "from": ["Specialist", "PMSoul", "Orchestrator", "HRDirector", "RuntimeArchitect", "MemoryCurator", "PolicyGate", "EvalJudge", "QAGate", "SitemapRouter"],
            "to": ["Artifact"],
        },
        {
            "relation": "has_capability",
            "from": ["Specialist", "PMSoul", "Orchestrator", "HRDirector", "RuntimeArchitect", "MemoryCurator", "PolicyGate", "EvalJudge", "QAGate", "SitemapRouter"],
            "to": ["Capability"],
        },
        {
            "relation": "gated_by",
            "from": ["Specialist", "PMSoul", "Orchestrator", "HRDirector", "EvalJudge", "QAGate", "RuntimeArchitect"],
            "to": ["PolicyGate"],
        },
        {
            "relation": "requires_approval_from",
            "from": ["Specialist", "PMSoul", "Orchestrator", "HRDirector", "EvalJudge", "QAGate", "RuntimeArchitect"],
            "to": ["PolicyGate"],
        },
        {
            "relation": "blocked_from",
            "from": ["Orchestrator", "HRDirector", "Specialist", "PMSoul"],
            "to": ["Specialist", "PMSoul", "Orchestrator", "HRDirector"],
        },
        {"relation": "trusts", "from": ["ExternalAgent"], "to": ["ExternalAgent"]},
        {"relation": "aligned_with", "from": ["ExternalAgent"], "to": ["Capability"]},
        {"relation": "exposes_card", "from": ["Orchestrator", "HRDirector", "PMSoul", "Specialist", "RuntimeArchitect"], "to": ["ExternalAgent"]},
        {"relation": "owns_scope", "from": ["Orchestrator", "HRDirector", "PMSoul", "Specialist"], "to": ["MemoryScope"]},
    ],
    "deny": [
        {
            "from": "Specialist",
            "relation": "routes_to",
            "to": "Specialist",
            "reason": "Policy Office: specialist↔specialist direct routing is blocked",
        },
        {
            "from": "PMSoul",
            "relation": "routes_to",
            "to": "PMSoul",
            "reason": "Policy Office: peer PMSoul direct routing is blocked",
        },
        {
            "from": "HRDirector",
            "relation": "delegates_to",
            "to": "Specialist",
            "when": "to.member_of != from.member_of",
            "reason": "Policy Office: out-of-dept specialist delegation is blocked",
        },
    ],
    "require": [
        {"if": "edge.kind == \"shared_memory_write\"", "then": "requires_approval_from(PolicyGate)"},
        {"if": "to.type == \"ExternalAgent\" and relation == \"can_invoke\"", "then": "exists aligned_with(to)"},
    ],
    "capabilities": [
        "create_single_agent",
        "build_agent_team",
        "package_existing_agent",
        "repair_agent_repo",
        "generate_routing_cards",
        "open_ontology_gui",
        "run_regression_tests",
        "run_demo_tasks",
        "implement_web_apps",
    ],
}


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _read_jsonl(path: Path, default: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if default is None:
        default = []
    if not path.exists():
        return list(default), [{"source": str(path), "error": "missing-file"}]

    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({"source": str(path), "line": line_no, "error": str(exc)})
            continue
        if isinstance(payload, dict):
            items.append(payload)
        else:
            errors.append({"source": str(path), "line": line_no, "error": "payload not object"})
    return items, errors


def load_grammar(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = root / ".agentlas" / AGENT_ONTOLOGY_DIR / "grammar.json"
    payload = _read_json(path, default=None)
    if isinstance(payload, dict):
        return payload
    return DEFAULT_GRAMMAR


def _artifact_id(kind: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", (kind or "").lower()).strip("-")
    return f"artifact:{slug or 'unknown'}"


def load_graph(project_root: str | Path = ".") -> dict[str, Any]:
    """Load the AO graph without requiring a generated view on disk.

    A materialized ``.agentlas/agent-ontology`` remains authoritative when it
    exists. Clean checkouts derive the same graph in memory from the tracked
    project contracts, so read-only inspection never has to create ignored
    runtime state first.
    """

    root = Path(project_root).resolve()
    path = root / ".agentlas" / AGENT_ONTOLOGY_DIR
    graph: dict[str, Any] = {
        "agents": [],
        "artifacts": [],
        "capabilities": [],
        "scopes": [],
        "edges": [],
    }
    report: dict[str, Any] = {
        "project": str(root),
        "path": str(path),
        "graph": graph,
        "warnings": [],
        "errors": [],
        "unmapped": {},
        "status": "ok",
    }

    report["grammar"] = load_grammar(root)
    if not path.exists():
        report["warnings"].append("materialized AO view is absent; using read-only derived graph")
        try:
            from .migrate import migrate_ontology

            derived = migrate_ontology(root, write=False, overwrite=True)
        except (OSError, TypeError, ValueError) as exc:
            report["status"] = "degraded"
            report["errors"].append(f"derived-graph-failed:{type(exc).__name__}")
        else:
            source_graph = derived.get("graph") if isinstance(derived, dict) else None
            if isinstance(source_graph, dict) and derived.get("status") == "ok":
                graph["agents"] = [_normalize_agent_node(item) for item in source_graph.get("agents", [])]
                graph["artifacts"] = [_normalize_artifact_node(item) for item in source_graph.get("artifacts", [])]
                graph["capabilities"] = [
                    str(item) for item in source_graph.get("capabilities", []) if str(item).strip()
                ]
                graph["scopes"] = [_normalize_scope_node(item) for item in source_graph.get("scopes", [])]
                graph["edges"] = [_normalize_edge(item) for item in source_graph.get("edges", [])]
                report["unmapped"] = derived.get("unmapped", {})
                report["derived"] = True
            else:
                report["status"] = "degraded"
                report["errors"].append("derived-graph-unavailable")
    else:
        agents, errors = _read_jsonl(path / "agents.jsonl")
        report["errors"].extend(errors)
        graph["agents"] = [_normalize_agent_node(agent) for agent in agents]

        artifacts, errors = _read_jsonl(path / "artifacts.jsonl")
        report["errors"].extend(errors)
        graph["artifacts"] = [_normalize_artifact_node(artifact) for artifact in artifacts]

        caps_payload = _read_json(path / "capabilities.json", default=None)
        if isinstance(caps_payload, dict):
            capabilities = caps_payload.get("capabilities")
            if isinstance(capabilities, list):
                graph["capabilities"] = [str(item) for item in capabilities if str(item).strip()]
            else:
                report["warnings"].append("capabilities.json is malformed; expected {'capabilities': [...]} JSON object")
        elif caps_payload is not None:
            report["warnings"].append("capabilities.json is malformed; expected {'capabilities': [...]} JSON object")

        # scopes.jsonl is optional (Phase 0 memory ownership); a missing file is benign.
        if (path / "scopes.jsonl").exists():
            scopes, errors = _read_jsonl(path / "scopes.jsonl")
            report["errors"].extend(errors)
            graph["scopes"] = [_normalize_scope_node(s) for s in scopes]

        edges, errors = _read_jsonl(path / "edges.jsonl")
        report["errors"].extend(errors)
        graph["edges"] = [_normalize_edge(edge) for edge in edges]

        if (path / "migrate-report.json").exists():
            report["migrate_report"] = _read_json(path / "migrate-report.json", default=None)

    node_index = {_as_node_id(node): node for node in graph["agents"] + graph["artifacts"] + graph["scopes"] if _as_node_id(node)}
    for cap in graph.get("capabilities", []):
        if not str(cap).strip():
            continue
        node_id = f"capability:{cap}"
        node_index[node_id] = {"id": node_id, "type": "Capability", "name": cap}
    report["node_index"] = node_index
    report["counts"] = {
        "agents": len(graph["agents"]),
        "artifacts": len(graph["artifacts"]),
        "capabilities": len(graph["capabilities"]),
        "scopes": len(graph["scopes"]),
        "edges": len(graph["edges"]),
    }

    return report


def _as_node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or "").strip()


def _normalize_node_type(node: dict[str, Any], fallback: str) -> str:
    node_type = str(node.get("type") or node.get("node_type") or fallback).strip()
    return node_type or fallback


def _normalize_agent_node(node: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(node)
    normalized["id"] = str(node.get("id") or "").strip()
    normalized["type"] = _normalize_node_type(node, fallback="Specialist")
    normalized["capabilities"] = [str(cap) for cap in (node.get("capabilities") or []) if str(cap).strip()]
    normalized["produces"] = [str(p) for p in (node.get("produces") or []) if str(p).strip()]
    normalized["consumes"] = [str(p) for p in (node.get("consumes") or []) if str(p).strip()]
    return normalized


def _normalize_artifact_node(node: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(node)
    if not normalized.get("id"):
        kind = str(normalized.get("kind") or normalized.get("name") or "artifact")
        normalized["id"] = _artifact_id(kind)
    if not normalized.get("kind"):
        normalized["kind"] = str(normalized["id"]).removeprefix("artifact:")
    normalized["type"] = "Artifact"
    return normalized


def _normalize_scope_node(node: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(node)
    normalized["id"] = str(node.get("id") or "").strip()
    if not normalized["id"]:
        scope = str(node.get("scope") or node.get("name") or "scope")
        normalized["id"] = f"scope:{scope}"
    if not normalized.get("scope"):
        normalized["scope"] = str(normalized["id"]).removeprefix("scope:")
    normalized["type"] = "MemoryScope"
    return normalized


def _normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(edge)
    normalized["from"] = str(edge.get("from") or "").strip()
    normalized["to"] = str(edge.get("to") or "").strip()
    normalized["relation"] = str(edge.get("relation") or edge.get("kind") or "").strip()
    if normalized.get("relation") and not normalized.get("kind"):
        normalized["kind"] = normalized["relation"]
    if not normalized["from"] or not normalized["to"] or not normalized["relation"]:
        normalized["invalid"] = True
    return normalized
