"""Migrate legacy `.agentlas` files into canonical AO JSONL."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from .loader import AGENT_ONTOLOGY_DIR, _read_json, load_grammar
from .loader import _artifact_id as canonical_artifact_id

# Canonical router ids that may be referenced by edges without an explicit
# node record. Materialized as Orchestrator nodes so edges do not dangle.
_ORCHESTRATOR_ALIASES = {"agents.md", "orchestrator", "hq", "team-soul"}

SOURCE_FILES = [
    "company-blueprint.json",
    "routing-card.json",
    "sitemap.json",
    "memory-map.json",
]


def migrate_ontology(project_root: str | Path = ".", write: bool = True, overwrite: bool = True) -> dict[str, Any]:
    root = Path(project_root).resolve()
    source_root = root / ".agentlas"
    target_root = source_root / AGENT_ONTOLOGY_DIR

    report: dict[str, Any] = {
        "project": str(root),
        "target": str(target_root),
        "written": [],
        "unmapped": {
            "company_blueprint": [],
            "routing_card": [],
            "sitemap": [],
            "memory_map": [],
        },
        "counts": {"agents": 0, "artifacts": 0, "capabilities": 0, "edges": 0},
        "errors": [],
        "status": "ok",
    }

    if not source_root.exists():
        report["status"] = "error"
        report["errors"].append("source root .agentlas does not exist")
        return report

    if write and not overwrite and target_root.exists() and any(target_root.iterdir() if target_root.exists() else []):
        report["status"] = "skipped"
        report["errors"].append("target already exists; pass --overwrite to rewrite")
        return report

    company_blueprint = _read_json(source_root / "company-blueprint.json", default={}) or {}
    routing_card = _read_json(source_root / "routing-card.json", default={}) or {}
    sitemap = _read_json(source_root / "sitemap.json", default={}) or {}
    memory_map = _read_json(source_root / "memory-map.json", default={}) or {}

    agents: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    capabilities: list[str] = []
    scopes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    unmapped = report["unmapped"]

    # --- company-blueprint: nodes & explicit handoff edges ---
    for node in _iter_records(company_blueprint.get("nodes"), default=()):
        node_id = str(node.get("id") or "").strip()
        role = str(node.get("role") or node.get("title") or node.get("name") or "").strip()
        if not node_id:
            unmapped["company_blueprint"].append({"type": "missing_node_id", "node": node})
            continue
        agent_type = _agent_type(role or node_id, node_id)
        agent = {
            "id": node_id,
            "type": agent_type,
            "name": role or node_id,
            "path": str(node.get("path") or ""),
            "member_of": node.get("member_of"),
            "role": role,
            "team": node.get("team"),
            "source": "company-blueprint",
        }
        if node.get("capabilities"):
            agent["capabilities"] = _normalize_capabilities(node.get("capabilities"), card_id=node_id)
        else:
            unmapped["company_blueprint"].append({"type": "agent_capabilities_missing", "id": node_id})
        agents.append(agent)
        node_ids.add(node_id)

        # Agent I/O contracts -> Artifact nodes + produces/consumes edges.
        for direction in ("produces", "consumes"):
            raw = node.get(direction)
            if not isinstance(raw, list):
                continue
            for item in raw:
                artifact_id = _artifact_ref(item, source="company-blueprint", unmapped=unmapped["company_blueprint"])
                if not artifact_id:
                    continue
                new_artifact = _upsert_artifact(artifacts, artifact_id)
                if new_artifact is not None:
                    artifacts.append(new_artifact)
                edges.append(
                    {
                        "from": node_id,
                        "to": artifact_id,
                        "relation": direction,
                        "kind": "derived",
                        "source": "company-blueprint",
                    }
                )

    for edge in _iter_records(company_blueprint.get("edges"), default=()):
        source = str(edge.get("from") or edge.get("source") or "").strip()
        target = str(edge.get("to") or edge.get("target") or "").strip()
        if not source or not target:
            continue
        relation = _infer_relation(str(edge.get("handoff") or edge.get("relation") or ""), edge.get("type"))
        edges.append(
            {
                "from": source,
                "to": target,
                "relation": relation,
                "kind": "derived",
                "source": "company-blueprint",
                "raw_handoff": edge.get("handoff"),
            }
        )

    # --- routing-card: capabilities / produce-consume contracts ---
    if routing_card:
        card_id = str(routing_card.get("id") or routing_card.get("canonical_id") or "local/hephaestus-meta-agent")
        if card_id not in node_ids:
            card_node = {
                "id": card_id,
                "type": _agent_type(str(routing_card.get("name") or "agent"), card_id),
                "name": str(routing_card.get("name") or card_id),
                "name_ko": routing_card.get("name_ko"),
                "path": str((routing_card.get("entrypoints") or {}).get("agent") or "."),
                "routing_status": routing_card.get("routing_status"),
                "source": "routing-card",
            }
            agents.append(card_node)
            node_ids.add(card_id)

        for cap in _normalize_capabilities(routing_card.get("capabilities"), card_id=card_id):
            if cap not in capabilities:
                capabilities.append(cap)
            edges.append(
                {
                    "from": card_id,
                    "to": f"capability:{cap}",
                    "relation": "has_capability",
                    "kind": "derived",
                    "source": "routing-card",
                }
            )

        for direction in ("produces", "consumes"):
            for item in _iter_records(routing_card.get(direction), default=()):
                artifact_id = _artifact_ref(item, source="routing-card", unmapped=unmapped["routing_card"])
                if not artifact_id:
                    continue
                artifact = _upsert_artifact(artifacts, artifact_id)
                if artifact is not None:
                    artifacts.append(artifact)
                edges.append(
                    {
                        "from": card_id,
                        "to": artifact_id,
                        "relation": direction,
                        "kind": "derived",
                        "source": "routing-card",
                    }
                )

    # --- sitemap: direct handoff graph shape ---
    for edge in _iter_records(sitemap.get("edges"), default=()):
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        if not source or not target:
            continue
        relation = _infer_relation(
            str(edge.get("kind") or edge.get("label") or edge.get("type") or ""),
            source_context=(source, target),
        )
        edges.append(
            {
                "from": source,
                "to": target,
                "relation": relation,
                "kind": "derived",
                "source": "sitemap",
            }
        )

    # Memory ownership -> MemoryScope nodes + owns_scope edges (Phase 0).
    # An owner string may name several agents ("a or b"); each yields an edge.
    if isinstance(memory_map.get("writeOwners"), dict):
        for scope_name, owner in memory_map["writeOwners"].items():
            scope_id = f"scope:{_snake(str(scope_name))}"
            if not any(s.get("id") == scope_id for s in scopes):
                scopes.append({"id": scope_id, "type": "MemoryScope", "scope": str(scope_name), "source": "memory-map"})
            if not isinstance(owner, str) or not owner.strip():
                continue
            for owner_id in [o.strip() for o in owner.split(" or ") if o.strip()]:
                edges.append(
                    {
                        "from": owner_id,
                        "to": scope_id,
                        "relation": "owns_scope",
                        "kind": "derived",
                        "source": "memory-map",
                    }
                )
    elif memory_map:
        unmapped["memory_map"].append({"type": "writeOwners_not_dict", "value": memory_map})

    # Reconcile edges against grammar: materialize referenced router nodes,
    # drop edges whose endpoints are not materialized nodes (reported in
    # `unmapped`, never silently lost), and downgrade relations that the
    # source-type cannot legally use (e.g. Specialist routes_to -> hands_off_to).
    grammar = load_grammar(root)
    _ensure_orchestrator_nodes(agents, edges, node_ids)
    edges = _reconcile_edges(agents, artifacts, capabilities, scopes, edges, grammar, unmapped)

    # Canonicalize duplicates.
    capabilities = _dedupe(capabilities)
    edges = _dedupe_edges(edges)
    artifacts = _dedupe_by_id(artifacts)
    agents = _dedupe_by_id(agents)
    scopes = _dedupe_by_id(scopes)

    # Normalize artifact nodes for on-disk JSONL.
    artifact_nodes = []
    for artifact in artifacts:
        if artifact.get("id") and artifact.get("kind"):
            artifact_nodes.append(
                {
                    "id": artifact["id"],
                    "type": "Artifact",
                    "kind": artifact["kind"],
                    "name": artifact.get("name") or artifact["kind"],
                    "source": artifact.get("source", "routing-card"),
                }
            )

    report["graph"] = {
        "agents": agents,
        "artifacts": artifact_nodes,
        "capabilities": capabilities,
        "scopes": scopes,
        "edges": edges,
    }

    report["counts"] = {
        "agents": len(agents),
        "artifacts": len(artifact_nodes),
        "capabilities": len(capabilities),
        "scopes": len(scopes),
        "edges": len(edges),
    }

    if write:
        target_root.mkdir(parents=True, exist_ok=True)
        _write_jsonl(target_root / "agents.jsonl", agents)
        _write_jsonl(target_root / "artifacts.jsonl", artifact_nodes)
        _write_jsonl(target_root / "scopes.jsonl", scopes)
        _write_jsonl(target_root / "edges.jsonl", edges)
        _write_jsonl(
            target_root / "capabilities.json",
            {"capabilities": capabilities},
            is_json=True,
        )
        # Materialize the grammar on disk so it is the editable, git-diffable
        # single source of truth (plan PR1). load_grammar() reads this file when
        # present, so re-running migrate is idempotent and never clobbers a
        # user-customized grammar.json.
        _write_jsonl(target_root / "grammar.json", grammar, is_json=True)
        _write_jsonl(
            target_root / "migrate-report.json",
            {
                "status": report["status"],
                "written_at": datetime.now(timezone.utc).isoformat(),
                "counts": report["counts"],
                "overwrite": overwrite,
                "unmapped": report["unmapped"],
            },
            is_json=True,
        )
        report["written"] = [
            str(target_root / "agents.jsonl"),
            str(target_root / "artifacts.jsonl"),
            str(target_root / "edges.jsonl"),
            str(target_root / "capabilities.json"),
        ]
    return report


def diff_ontology(project_root: str | Path = ".") -> dict[str, Any]:
    """Compute AO drift vs regenerated derivation from legacy JSON files."""

    generated = migrate_ontology(project_root, write=False, overwrite=True)
    if generated.get("status") not in ("ok", "skipped"):
        return generated

    current = load_from_disk(project_root)
    baseline = generated.get("graph", {})
    counts = generated.get("counts", {})
    if not baseline:
        return {
            "status": "error",
            "errors": ["missing generated graph in migration output"],
            "project": str(Path(project_root).resolve()),
        }

    def _index_lines(items: list[dict[str, Any]]) -> list[str]:
        return sorted(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items)

    current_graph = {
        "agents": current.get("agents", []),
        "artifacts": current.get("artifacts", []),
        "capabilities": current.get("capabilities", []),
        "scopes": current.get("scopes", []),
        "edges": current.get("edges", []),
    }

    drift: dict[str, Any] = {}
    same = True
    for key in ("agents", "artifacts", "capabilities", "scopes", "edges"):
        generated_lines = _index_lines(list(baseline.get(key, [])))
        current_lines = _index_lines(list(current_graph.get(key, [])))
        drift[key] = {
            "same": generated_lines == current_lines,
            "generated_count": len(generated_lines),
            "current_count": len(current_lines),
        }
        if not drift[key]["same"]:
            same = False
            gset = set(generated_lines)
            cset = set(current_lines)
            drift[key]["missing_in_current"] = sorted(list(gset - cset))
            drift[key]["extra_in_current"] = sorted(list(cset - gset))

    return {
        "status": "clean" if same else "drift",
        "project": str(Path(project_root).resolve()),
        "counts": counts,
        "diff": drift,
        "same": same,
    }


def load_from_disk(project_root: str | Path) -> dict[str, Any]:
    """Read `.agentlas/agent-ontology/*.jsonl` for manual inspection."""

    root = Path(project_root).resolve()
    base = root / ".agentlas" / AGENT_ONTOLOGY_DIR
    report = {"project": str(root), "agents": [], "artifacts": [], "capabilities": [], "scopes": [], "edges": []}
    if not base.exists():
        return report

    if (base / "agents.jsonl").exists():
        report["agents"] = _read_jsonl_lines(base / "agents.jsonl")
    if (base / "artifacts.jsonl").exists():
        report["artifacts"] = _read_jsonl_lines(base / "artifacts.jsonl")
    if (base / "scopes.jsonl").exists():
        report["scopes"] = _read_jsonl_lines(base / "scopes.jsonl")
    if (base / "edges.jsonl").exists():
        report["edges"] = _read_jsonl_lines(base / "edges.jsonl")
    if (base / "capabilities.json").exists():
        payload = _read_json(base / "capabilities.json", default={}) or {}
        capabilities = payload.get("capabilities") if isinstance(payload, dict) else None
        if isinstance(capabilities, list):
            report["capabilities"] = capabilities
        elif capabilities is not None:
            report["capabilities"] = []
    report["counts"] = {
        "agents": len(report["agents"]),
        "artifacts": len(report["artifacts"]),
        "capabilities": len(report["capabilities"]),
        "scopes": len(report["scopes"]),
        "edges": len(report["edges"]),
    }
    return report


def _iter_records(value: Any, *, default: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return list(default)
    return [entry for entry in value if isinstance(entry, dict)]


def _has_value(node: dict[str, Any], key: str) -> bool:
    raw = node.get(key)
    return bool(raw is not None and str(raw).strip())


def _has_node(items: list[dict[str, Any]], node_id: str) -> bool:
    return any(str(item.get("id")) == node_id for item in items)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _normalize_capabilities(raw: Any, card_id: str | None = None) -> list[str]:
    caps: list[str] = []
    if not raw:
        return caps
    values = raw if isinstance(raw, list) else [raw]
    for item in values:
        for piece in str(item).replace(",", " ").split():
            norm = _snake(piece)
            if not norm:
                continue
            if not norm.startswith(("run_", "create_", "build_", "open_", "package_", "repair_", "implement_", "generate_")):
                norm = f"run_{norm}"
            caps.append(norm)
    if not caps and card_id:
        caps.append(f"run_{_snake(card_id)}")
    return _dedupe(caps)


def _artifact_ref(raw: Any, source: str, unmapped: list[dict[str, Any]]) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        slug = _snake(raw)
        if not slug:
            return ""
        return canonical_artifact_id(slug)
    if isinstance(raw, dict):
        if raw.get("id") and str(raw.get("id")).strip():
            return canonical_artifact_id(_snake(str(raw.get("id"))))
        if raw.get("kind") and str(raw.get("kind")).strip():
            return canonical_artifact_id(_snake(str(raw.get("kind"))))
        if raw.get("name") and str(raw.get("name")).strip():
            return canonical_artifact_id(_snake(str(raw.get("name"))))
    unmapped.append({"source": source, "value": raw, "note": "unparseable-artifact"})
    return ""


def _upsert_artifact(bucket: list[dict[str, Any]], artifact_id: str) -> dict[str, Any] | None:
    artifact_id = str(artifact_id or "").strip()
    if artifact_id.startswith("artifact:"):
        artifact_id = artifact_id
    elif artifact_id.startswith("artifact-"):
        artifact_id = "artifact:" + artifact_id.removeprefix("artifact-")
    else:
        artifact_id = canonical_artifact_id(_snake(artifact_id))
    if not artifact_id:
        return None
    for item in bucket:
        if item.get("id") == artifact_id:
            return None
    # The caller appends the returned artifact; do not mutate the bucket here
    # (this removes the historical double-append that dedupe later had to hide).
    kind = artifact_id.removeprefix("artifact:")
    return {"id": artifact_id, "kind": kind, "name": kind}


def _dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        out.append(item)
    return out


def _dedupe_edges(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for item in items:
        key = (str(item.get("from") or ""), str(item.get("to") or ""), str(item.get("relation") or ""), str(item.get("kind") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _snake(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", (value or "").lower()).strip("-_")


def _infer_relation(handoff: str, edge_type: Any = None, source_context: tuple[str, str] | None = None) -> str:
    if edge_type and isinstance(edge_type, str):
        return str(edge_type)
    value = (handoff or "").lower()
    if "delegate" in value:
        return "delegates_to"
    if "handoff" in value:
        return "hands_off_to"
    if "route" in value:
        return "routes_to"
    if "produce" in value:
        return "produces"
    if "consume" in value:
        return "consumes"
    if "trust" in value:
        return "trusts"
    if "gated" in value:
        return "gated_by"
    if "invoke" in value:
        return "can_invoke"
    if "align" in value:
        return "aligned_with"
    if "own" in value and source_context:
        return "owns_scope"
    return "routes_to"


def _agent_type(role: str, node_id: str) -> str:
    key = (role or "").lower()
    if "orchestrator" in key or "hq" in key:
        return "Orchestrator"
    if "director" in key:
        return "HRDirector"
    if "pm soul" in key or "pmsoul" in key:
        return "PMSoul"
    if "team" in key or "builder" in key:
        return "Specialist"
    if "policy" in key:
        return "PolicyGate"
    if "curator" in key or "memory" in key:
        return "MemoryCurator"
    if "qag" in key or "qa" in key:
        return "QAGate"
    if "eval" in key:
        return "EvalJudge"
    if "runtime" in key:
        return "RuntimeArchitect"
    if "sitemap" in key:
        return "SitemapRouter"
    if node_id in {"AGENTS.md", "orchestrator", "team-soul"}:
        return "Orchestrator"
    return "Specialist"


def _ensure_orchestrator_nodes(
    agents: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_ids: set[str],
) -> None:
    """Materialize canonical router ids (e.g. AGENTS.md) referenced by edges.

    Edges in company-blueprint frequently originate from the canonical
    orchestrator entrypoint that has no explicit node record. Without a node
    those edges dangle and fail grammar validation, so we add an Orchestrator
    node for any referenced router alias that is otherwise unmapped.
    """

    referenced: set[str] = set()
    for edge in edges:
        for key in ("from", "to"):
            value = str(edge.get(key) or "").strip()
            if value and value not in node_ids and value.lower() in _ORCHESTRATOR_ALIASES:
                referenced.add(value)
    for router_id in sorted(referenced):
        agents.append(
            {
                "id": router_id,
                "type": "Orchestrator",
                "name": router_id,
                "source": "company-blueprint",
            }
        )
        node_ids.add(router_id)


def _reconcile_edges(
    agents: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    capabilities: list[str],
    scopes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    grammar: dict[str, Any],
    unmapped: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Keep only grammar-valid edges; report or repair the rest.

    - Unknown endpoint (not a materialized agent/artifact/capability node) ->
      reported under ``unmapped['edges_unresolved']`` and dropped.
    - Relation illegal for the source type (or denied) -> downgraded to
      ``hands_off_to`` when that is legal; otherwise reported under
      ``unmapped['edges_invalid_relation']`` and dropped.
    """

    node_type: dict[str, str] = {}
    for agent in agents:
        nid = str(agent.get("id") or "").strip()
        if nid:
            node_type[nid] = str(agent.get("type") or "Specialist")
    for artifact in artifacts:
        nid = str(artifact.get("id") or "").strip()
        if nid:
            node_type[nid] = "Artifact"
    for cap in capabilities:
        cap_id = str(cap).strip()
        if cap_id:
            node_type[f"capability:{cap_id}"] = "Capability"
    for scope in scopes:
        sid = str(scope.get("id") or "").strip()
        if sid:
            node_type[sid] = "MemoryScope"

    allowed_from: dict[str, set[str]] = {}
    allowed_to: dict[str, set[str]] = {}
    for rule in grammar.get("relation_rules", []):
        relation = str(rule.get("relation") or "")
        if not relation:
            continue
        allowed_from[relation] = set(rule.get("from", []))
        allowed_to[relation] = set(rule.get("to", []))

    deny_rules = grammar.get("deny", [])

    def _denied(from_type: str, relation: str, to_type: str) -> bool:
        for rule in deny_rules:
            if (
                str(rule.get("from") or "") == from_type
                and str(rule.get("relation") or "") == relation
                and str(rule.get("to") or "") == to_type
                and not rule.get("when")
            ):
                return True
        return False

    def _legal(from_type: str, relation: str, to_type: str) -> bool:
        if relation not in allowed_from:
            return False
        froms = allowed_from[relation]
        tos = allowed_to.get(relation, set())
        if froms and from_type not in froms and "*" not in froms:
            return False
        if tos and to_type not in tos and "*" not in tos:
            return False
        return not _denied(from_type, relation, to_type)

    reconciled: list[dict[str, Any]] = []
    for edge in edges:
        from_id = str(edge.get("from") or "").strip()
        to_id = str(edge.get("to") or "").strip()
        relation = str(edge.get("relation") or edge.get("kind") or "").strip()
        if from_id not in node_type or to_id not in node_type:
            unmapped.setdefault("edges_unresolved", []).append(
                {"from": from_id, "to": to_id, "relation": relation, "source": edge.get("source")}
            )
            continue
        from_type = node_type[from_id]
        to_type = node_type[to_id]
        if _legal(from_type, relation, to_type):
            reconciled.append(edge)
            continue
        # Downgrade an illegal routing relation to a peer handoff when legal.
        if relation != "hands_off_to" and _legal(from_type, "hands_off_to", to_type):
            reconciled.append({**edge, "relation": "hands_off_to", "downgraded_from": relation})
            continue
        unmapped.setdefault("edges_invalid_relation", []).append(
            {
                "from": from_id,
                "to": to_id,
                "relation": relation,
                "from_type": from_type,
                "to_type": to_type,
                "source": edge.get("source"),
            }
        )
    return reconciled


def _write_jsonl(path: Path, items: list[dict[str, Any]] | dict[str, Any], *, is_json: bool = False) -> None:
    if is_json:
        content = json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        path.write_text(content, encoding="utf-8")
        return

    if not items:
        path.write_text("", encoding="utf-8")
        return
    content = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items) + "\n"
    path.write_text(content, encoding="utf-8")


def _read_jsonl_lines(path: Path) -> list[dict[str, Any]]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            lines.append(payload)
    return lines
