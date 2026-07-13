"""OKF (Open Knowledge Format) adapter for the Agent Ontology (AO).

Round-trippable serialization of the AO graph to/from a Google Cloud OKF v0.1
bundle: a directory of Markdown files, one concept per file, with YAML
frontmatter (``type`` mandatory) and a Markdown body whose links encode
relations. Path = identity, directory = node kind, Markdown links = edges,
``index.md`` lists the bundle.

OKF is intentionally not a formal typed ontology, so this is a *lossy
interchange* projection: AO stays the canonical typed source; OKF is the
portable wire format that any OKF-aware agent (Gemini/ADK, Knowledge Catalog)
can consume. Export is redaction-safe — private fields are never serialized,
mirroring the A2A export whitelist.

No third-party dependency: a minimal frontmatter reader/writer is used.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .a2a import _PRIVATE_FIELDS
from .loader import load_graph

FORMAT = "okf-v0.1"

_KIND_DIR = {"Artifact": "artifacts", "Capability": "capabilities", "MemoryScope": "scopes"}


def _dir_for(node_type: str) -> str:
    return _KIND_DIR.get(str(node_type), "agents")


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", str(name).lower()).strip("-") or "node"


def _write_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    raw, body = parts[1], parts[2]
    meta: dict[str, Any] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key:
            if not isinstance(meta.get(current_key), list):
                meta[current_key] = []
            meta[current_key].append(line[4:].strip())
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            current_key = key
            meta[key] = value if value else []
    return meta, body.lstrip("\n")


def _collect_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for node in graph.get("agents", []):
        nodes.append(dict(node))
    for node in graph.get("artifacts", []):
        nodes.append({**node, "type": "Artifact"})
    for node in graph.get("scopes", []):
        nodes.append({**node, "type": "MemoryScope"})
    for cap in graph.get("capabilities", []):
        cap = str(cap).strip()
        if cap:
            nodes.append({"id": f"capability:{cap}", "type": "Capability", "name": cap})
    return nodes


def to_okf_bundle(project_root: str | Path = ".", out_dir: str | Path | None = None) -> dict[str, Any]:
    """Serialize the AO graph to an OKF bundle directory. Redaction-safe."""

    graph = load_graph(project_root).get("graph", {})
    out = Path(out_dir) if out_dir else (Path(project_root) / ".agentlas" / "okf-export")
    out.mkdir(parents=True, exist_ok=True)
    nodes = _collect_nodes(graph)

    id_to_path: dict[str, str] = {}
    for node in nodes:
        nid = str(node.get("id") or "")
        if nid:
            id_to_path[nid] = f"{_dir_for(node.get('type'))}/{_safe(nid)}.md"

    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        outgoing[str(edge.get("from") or "")].append(edge)

    written = 0
    for node in nodes:
        nid = str(node.get("id") or "")
        if not nid:
            continue
        ntype = str(node.get("type") or "")
        # Redaction: only a safe field whitelist is emitted.
        tags = [str(c) for c in (node.get("capabilities") or []) if str(c).strip()]
        meta = {
            "type": ntype,
            "id": nid,
            "title": node.get("name") or nid,
            "tags": tags,
            "format": FORMAT,
        }
        body = [f"# {node.get('name') or nid}", ""]
        rels: dict[str, list[str]] = defaultdict(list)
        for edge in outgoing.get(nid, []):
            to_id = str(edge.get("to") or "")
            relation = str(edge.get("relation") or edge.get("kind") or "")
            if to_id in id_to_path and relation:
                rels[relation].append(to_id)
        for relation in sorted(rels):
            body.append(f"## {relation}")
            for to_id in rels[relation]:
                rel_link = os.path.relpath(id_to_path[to_id], os.path.dirname(id_to_path[nid]))
                body.append(f"- [{to_id}]({rel_link})")
            body.append("")
        content = _write_frontmatter(meta) + "\n\n" + "\n".join(body) + "\n"
        path = out / id_to_path[nid]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written += 1

    index = ["---", "type: Index", f"format: {FORMAT}", "---", "", "# OKF Bundle Index", ""]
    for node in nodes:
        nid = str(node.get("id") or "")
        if nid in id_to_path:
            index.append(f"- [{nid}]({id_to_path[nid]}) ({node.get('type')})")
    (out / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")

    return {
        "format": FORMAT,
        "out_dir": str(out),
        "files": written + 1,
        "nodes": len(nodes),
        "redacted_fields": sorted(_PRIVATE_FIELDS),
    }


def from_okf_bundle(in_dir: str | Path) -> dict[str, Any]:
    """Parse an external OKF bundle into nodes + edges (for kernel-gated import).

    The returned graph is a *proposal* — callers route it through Memory
    Candidate admission; it is never written directly to the canonical AO.
    """

    base = Path(in_dir)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    if not base.exists():
        return {"format": FORMAT, "nodes": [], "edges": [], "counts": {"nodes": 0, "edges": 0}, "error": "missing bundle"}

    link_re = re.compile(r"- \[([^\]]+)\]\(([^)]+)\)")
    for path in sorted(base.rglob("*.md")):
        if path.name == "index.md":
            continue
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        nid = str(meta.get("id") or "").strip()
        if not nid:
            continue
        nodes.append(
            {
                "id": nid,
                "type": meta.get("type"),
                "name": meta.get("title") or nid,
                "tags": meta.get("tags") or [],
                "source": "okf-import",
            }
        )
        current_rel: str | None = None
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                current_rel = stripped[3:].strip()
            elif stripped.startswith("- [") and current_rel:
                match = link_re.match(stripped)
                if match:
                    edges.append(
                        {"from": nid, "to": match.group(1), "relation": current_rel, "kind": "okf-import"}
                    )
    return {
        "format": FORMAT,
        "nodes": nodes,
        "edges": edges,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }
