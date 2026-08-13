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
import shutil
import stat
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .a2a import _PRIVATE_FIELDS
from .loader import load_graph

FORMAT = "okf-v0.1"
OKF_BUNDLE_MARKER = ".agentlas-okf-bundle"
MAX_IMPORT_ENTRIES = 8_192
MAX_IMPORT_FILES = 4_096
MAX_IMPORT_FILE_BYTES = 2 * 1024 * 1024
MAX_IMPORT_TOTAL_BYTES = 64 * 1024 * 1024
MAX_IMPORT_DEPTH = 12
MAX_IMPORT_NODES = 10_000
MAX_IMPORT_EDGES = 50_000

_KIND_DIR = {"Artifact": "artifacts", "Capability": "capabilities", "MemoryScope": "scopes"}


def _dir_for(node_type: str) -> str:
    return _KIND_DIR.get(str(node_type), "agents")


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", str(name).lower()).strip("-") or "node"


def _replaceable_output_directory(path: Path) -> bool:
    """Return whether an existing output directory is empty or ours."""

    try:
        entries = list(path.iterdir())
    except OSError:
        return False
    if not entries:
        return True
    marker = path / OKF_BUNDLE_MARKER
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        return marker.read_text(encoding="utf-8") == f"{FORMAT}\n"
    except (OSError, UnicodeDecodeError):
        return False


def _okf_paths(nodes: list[dict[str, Any]]) -> dict[str, str]:
    id_to_path: dict[str, str] = {}
    path_to_id: dict[str, str] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        if node_id in id_to_path:
            raise ValueError(f"duplicate OKF node id: {node_id}")
        relative = f"{_dir_for(node.get('type'))}/{_safe(node_id)}.md"
        prior = path_to_id.get(relative)
        if prior is not None and prior != node_id:
            raise ValueError(
                f"OKF node path collision: {prior!r} and {node_id!r} map to {relative!r}"
            )
        id_to_path[node_id] = relative
        path_to_id[relative] = node_id
    return id_to_path


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

    graph_context = load_graph(project_root)
    if graph_context.get("status") != "ok":
        raise ValueError("refusing to export a stale or invalid AO graph")
    graph = graph_context.get("graph", {})
    requested_out = Path(out_dir) if out_dir else (Path(project_root) / ".agentlas" / "okf-export")
    requested_out = requested_out.expanduser()
    out = Path(os.path.abspath(requested_out))
    if out.is_symlink():
        raise ValueError("refusing to replace a symlink OKF output directory")
    if out.exists() and not out.is_dir():
        raise ValueError("OKF output target must be a directory")
    if out.exists() and not _replaceable_output_directory(out):
        raise ValueError(
            "refusing to replace a non-empty directory without an Agentlas OKF bundle marker"
        )
    nodes = _collect_nodes(graph)
    id_to_path = _okf_paths(nodes)
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.tmp-", dir=out.parent))

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
        path = staging / id_to_path[nid]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        written += 1

    index = ["---", "type: Index", f"format: {FORMAT}", "---", "", "# OKF Bundle Index", ""]
    for node in nodes:
        nid = str(node.get("id") or "")
        if nid in id_to_path:
            index.append(f"- [{nid}]({id_to_path[nid]}) ({node.get('type')})")
    try:
        (staging / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
        (staging / OKF_BUNDLE_MARKER).write_text(f"{FORMAT}\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    backup: Path | None = None
    published = False
    try:
        if out.exists():
            if not _replaceable_output_directory(out):
                raise ValueError(
                    "OKF output directory changed and is no longer safely replaceable"
                )
            backup = Path(tempfile.mkdtemp(prefix=f".{out.name}.old-", dir=out.parent))
            backup.rmdir()
            out.rename(backup)
        staging.rename(out)
        published = True
    except Exception:
        if backup is not None and backup.exists() and not out.exists():
            backup.rename(out)
            backup = None
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if published and backup is not None and backup.exists():
            shutil.rmtree(backup)

    return {
        "format": FORMAT,
        "out_dir": str(out),
        "files": written + 2,
        "nodes": len(nodes),
        "redacted_fields": sorted(_PRIVATE_FIELDS),
    }


def from_okf_bundle(in_dir: str | Path) -> dict[str, Any]:
    """Parse an external OKF bundle into nodes + edges (for kernel-gated import).

    The returned graph is a *proposal* — callers route it through Memory
    Candidate admission; it is never written directly to the canonical AO.
    """

    requested_base = Path(in_dir).expanduser()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    if not requested_base.exists():
        return {"status": "error", "format": FORMAT, "nodes": [], "edges": [], "counts": {"nodes": 0, "edges": 0}, "error": "okf_bundle_missing"}
    if requested_base.is_symlink() or not requested_base.is_dir():
        raise ValueError("OKF import requires a real bundle directory")
    base = requested_base.resolve(strict=True)

    markdown_files: list[Path] = []
    entries = 0
    total_bytes = 0
    for current, dirnames, filenames in os.walk(base, topdown=True, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(base)
        depth = 0 if relative == Path(".") else len(relative.parts)
        if depth > MAX_IMPORT_DEPTH:
            raise ValueError(f"OKF import exceeds depth limit {MAX_IMPORT_DEPTH}")
        entries += len(dirnames) + len(filenames)
        if entries > MAX_IMPORT_ENTRIES:
            raise ValueError(f"OKF import exceeds entry limit {MAX_IMPORT_ENTRIES}")
        for name in dirnames:
            candidate = current_path / name
            if candidate.is_symlink():
                raise ValueError("OKF import refuses symlink entries")
        for name in filenames:
            candidate = current_path / name
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("OKF import refuses symlink entries")
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("OKF import requires regular files")
            candidate.resolve(strict=True).relative_to(base)
            if candidate.suffix.lower() != ".md":
                continue
            if metadata.st_size > MAX_IMPORT_FILE_BYTES:
                raise ValueError(f"OKF import file exceeds {MAX_IMPORT_FILE_BYTES} bytes")
            total_bytes += metadata.st_size
            if total_bytes > MAX_IMPORT_TOTAL_BYTES:
                raise ValueError(f"OKF import exceeds {MAX_IMPORT_TOTAL_BYTES} total bytes")
            markdown_files.append(candidate)
            if len(markdown_files) > MAX_IMPORT_FILES:
                raise ValueError(f"OKF import exceeds file limit {MAX_IMPORT_FILES}")

    link_re = re.compile(r"- \[([^\]]+)\]\(([^)]+)\)")
    for path in sorted(markdown_files):
        if path.name == "index.md":
            continue
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        nid = str(meta.get("id") or "").strip()
        if not nid:
            continue
        if len(nodes) >= MAX_IMPORT_NODES:
            raise ValueError(f"OKF import exceeds node limit {MAX_IMPORT_NODES}")
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
                    if len(edges) >= MAX_IMPORT_EDGES:
                        raise ValueError(f"OKF import exceeds edge limit {MAX_IMPORT_EDGES}")
                    edges.append(
                        {"from": nid, "to": match.group(1), "relation": current_rel, "kind": "okf-import"}
                    )
    return {
        "status": "ok",
        "format": FORMAT,
        "nodes": nodes,
        "edges": edges,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
        "scan": {
            "files": len(markdown_files),
            "bytes": total_bytes,
            "file_limit": MAX_IMPORT_FILES,
            "byte_limit": MAX_IMPORT_TOTAL_BYTES,
        },
    }
