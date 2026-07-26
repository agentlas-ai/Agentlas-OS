"""Dependency-aware, project-local context slices for every Agentlas host.

The code map is an index, not prompt material.  This module turns that index
plus optional declared project context into a bounded task slice and issues
content-free receipts for later impact verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .project_bootstrap import generate_code_map


CODE_MAP_SCHEMA = "agentlas.code-map.v2"
CONTEXT_SLICE_SCHEMA = "agentlas.context-slice.v1"
CONTEXT_QUERY_RECEIPT_SCHEMA = "agentlas.context-query-receipt.v1"
CONTEXT_IMPACT_RECEIPT_SCHEMA = "agentlas.context-impact-receipt.v1"
CONTEXT_VERIFICATION_RECEIPT_SCHEMA = "agentlas.context-verification-receipt.v1"

MAX_MAP_BYTES = 24 * 1024 * 1024
MAX_TASK_CHARS = 12_000
MAX_QUERY_TERMS = 96
MAX_SELECTED_SYMBOLS = 12
MAX_SELECTED_FILES = 64
MAX_IMPACT_FILES = 256
MAX_CONTEXT_NODES = 48
MAX_CONTEXT_EDGES = 128
MAX_RENDER_CHARS = 9_000

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_PATH_HINT_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:[A-Za-z0-9_.()@+-]+/)+[A-Za-z0-9_.()@+-]+)"
)
_ACTIVE_STATES = frozenset({"active", "tentative", "validated", "proposed", "unknown", ""})
_INHERITED_NODE_TYPES = frozenset(
    {"project", "goal", "subgoal", "requirement", "constraint", "decision", "assumption", "metric", "deadline"}
)
_STOP_TERMS = frozenset(
    {
        "and", "are", "but", "can", "class", "const", "data", "def", "file", "for", "from",
        "function", "get", "has", "import", "into", "let", "main", "new", "node", "not",
        "project", "return", "set", "that", "the", "this", "type", "use", "using", "value",
        "what", "when", "where", "which", "with",
    }
)


class ContextMapError(ValueError):
    """Stable, secret-free error surfaced by CLI and MCP adapters."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _project_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ContextMapError("context_project_invalid")
    return root


def _regular_json(path: Path, *, max_bytes: int) -> dict[str, Any]:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ContextMapError("context_map_missing") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_size <= 0
        or metadata.st_size > max_bytes
    ):
        raise ContextMapError("context_map_unreadable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextMapError("context_map_unreadable") from exc
    if not isinstance(payload, dict):
        raise ContextMapError("context_map_unreadable")
    return payload


def _normalize_file(root: Path, value: str) -> str | None:
    raw = value.strip().replace("\\", "/").lstrip("./")
    if not raw or raw.startswith("/") or "\x00" in raw:
        return None
    try:
        candidate = (root / raw).resolve(strict=False)
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate.relative_to(root).as_posix()


def _bounded_strings(values: Iterable[str], limit: int) -> list[str]:
    return sorted({value for value in values if value})[:limit]


def _query_terms(task: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(task[:MAX_TASK_CHARS]):
        raw = match.group(0)
        normalized = raw.lower()
        if normalized in _STOP_TERMS or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
        if len(terms) >= MAX_QUERY_TERMS:
            break
    return terms


def _symbol_terms(task: str) -> list[str]:
    """Return symbol-shaped terms, not generic prose words.

    This is intentionally stricter than declared-context matching. A task that
    merely says "fix the context" must not select every function named
    ``context``; exact camelCase, snake_case, or long identifiers are eligible.
    """

    terms: list[str] = []
    for match in _TOKEN_RE.finditer(task[:MAX_TASK_CHARS]):
        raw = match.group(0)
        if "_" not in raw and not re.search(r"[a-z][A-Z]", raw) and len(raw) < 12:
            continue
        normalized = raw.lower()
        if normalized not in terms:
            terms.append(normalized)
        if len(terms) >= MAX_QUERY_TERMS:
            break
    return terms


def _task_path_hints(root: Path, task: str, targets: Sequence[str]) -> list[str]:
    paths: list[str] = []
    for raw in [*targets, *(match.group(1) for match in _PATH_HINT_RE.finditer(task[:MAX_TASK_CHARS]))]:
        normalized = _normalize_file(root, raw)
        if normalized:
            paths.append(normalized)
    return _bounded_strings(paths, MAX_SELECTED_FILES)


def load_code_map(
    project: str | Path,
    *,
    refresh: bool = True,
    force_refresh: bool = False,
) -> tuple[Path, dict[str, Any], dict[str, Any] | None]:
    """Load the canonical map, optionally refreshing its fingerprint first."""

    root = _project_root(project)
    refresh_receipt: dict[str, Any] | None = None
    if refresh:
        refresh_receipt = generate_code_map(root, force=force_refresh)
    payload = _regular_json(root / ".agentlas" / "code-map" / "project-map.json", max_bytes=MAX_MAP_BYTES)
    schema = str(payload.get("schemaVersion") or "")
    if schema not in {CODE_MAP_SCHEMA, "5.0"}:
        raise ContextMapError("context_map_upgrade_required")
    if not isinstance(payload.get("defIndex"), dict) or not isinstance(payload.get("refIndex"), dict):
        raise ContextMapError("context_map_upgrade_required")
    return root, payload, refresh_receipt


def _node_id(node: Mapping[str, Any]) -> str:
    return str(node.get("id") or node.get("nodeId") or node.get("path") or "")


def _node_type(node: Mapping[str, Any]) -> str:
    return str(node.get("type") or node.get("kind") or "").lower()


def _node_status(node: Mapping[str, Any]) -> str:
    return str(node.get("status") or "").lower()


def _load_declared_graph(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge explicit Context Map declarations with annotated sitemap nodes.

    Generated file/directory-only sitemap rows are deliberately ignored here:
    the code map already represents those paths.  Only typed functional/project
    nodes and explicit edges are eligible for inheritance.
    """

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for relative in (".agentlas/context-map.json", ".agentlas/sitemap.json"):
        path = root / relative
        if not path.exists():
            continue
        try:
            payload = _regular_json(path, max_bytes=16 * 1024 * 1024)
        except ContextMapError:
            continue
        raw_nodes = payload.get("nodes")
        raw_edges = payload.get("edges") or payload.get("relationships")
        if isinstance(raw_nodes, list):
            for candidate in raw_nodes:
                if not isinstance(candidate, dict):
                    continue
                kind = _node_type(candidate)
                if relative.endswith("sitemap.json") and kind in {"file", "directory"}:
                    continue
                if _node_id(candidate) and _node_status(candidate) in _ACTIVE_STATES:
                    nodes.append(dict(candidate))
        if isinstance(raw_edges, list):
            edges.extend(dict(candidate) for candidate in raw_edges if isinstance(candidate, dict))
    return nodes[:2_000], edges[:8_000]


def _edge_parts(edge: Mapping[str, Any]) -> tuple[str, str, str]:
    source = str(edge.get("from") or edge.get("source") or edge.get("fromId") or "")
    target = str(edge.get("to") or edge.get("target") or edge.get("toId") or "")
    relation = str(edge.get("type") or edge.get("relation") or edge.get("kind") or "depends_on")
    return source, target, relation


def _select_declared_context(
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
    *,
    terms: Sequence[str],
    selected_files: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {_node_id(node): node for node in nodes if _node_id(node)}
    selected: set[str] = {
        node_id
        for node_id, node in by_id.items()
        if _node_type(node) in _INHERITED_NODE_TYPES
        and _node_status(node) in {"active", "validated", "tentative", ""}
    }
    needles = set(terms)
    needles.update(part.lower() for path in selected_files for part in Path(path).parts)
    for node_id, node in by_id.items():
        searchable = " ".join(
            str(node.get(field) or "")
            for field in ("id", "title", "name", "description", "path", "scope")
        ).lower()
        if any(term in searchable for term in needles):
            selected.add(node_id)

    # Structural closure: carry parents, constraints, decisions, dependencies,
    # interfaces, and validation nodes one hop in either direction.
    selected_edges: list[dict[str, Any]] = []
    for _ in range(2):
        changed = False
        for edge in edges:
            source, target, _relation = _edge_parts(edge)
            if not source or not target:
                continue
            if source in selected or target in selected:
                if source in by_id and source not in selected:
                    selected.add(source)
                    changed = True
                if target in by_id and target not in selected:
                    selected.add(target)
                    changed = True
                selected_edges.append(edge)
        if not changed:
            break
    selected_nodes = [by_id[node_id] for node_id in sorted(selected) if node_id in by_id][
        :MAX_CONTEXT_NODES
    ]
    allowed_ids = {_node_id(node) for node in selected_nodes}
    selected_edges = [
        edge
        for edge in selected_edges
        if _edge_parts(edge)[0] in allowed_ids and _edge_parts(edge)[1] in allowed_ids
    ][:MAX_CONTEXT_EDGES]
    return selected_nodes, selected_edges


def _module_of(path: str) -> str:
    parts = Path(path).parts
    return parts[0] if len(parts) > 1 else "."


def _selected_symbols(
    code_map: Mapping[str, Any],
    *,
    terms: Sequence[str],
    files: Sequence[str],
) -> list[str]:
    definitions = code_map.get("defIndex")
    file_symbols = code_map.get("fileSymbols")
    if not isinstance(definitions, dict):
        return []
    exact = list(dict.fromkeys(term for term in terms if term in definitions))
    selected: list[str] = list(exact)
    if isinstance(file_symbols, dict):
        for file_path in files:
            symbols = file_symbols.get(file_path)
            if not isinstance(symbols, list):
                continue
            for item in symbols:
                if isinstance(item, dict):
                    key = str(item.get("n") or "").lower()
                    if key and key in definitions:
                        selected.append(key)
    ref_count = code_map.get("refCount") if isinstance(code_map.get("refCount"), dict) else {}
    ranked = sorted(
        set(selected) - set(exact),
        key=lambda key: (-int(ref_count.get(key) or 0), key),
    )
    return [*exact, *ranked][:MAX_SELECTED_SYMBOLS]


def context_slice(
    project: str | Path,
    task: str,
    *,
    targets: Sequence[str] = (),
    refresh: bool = True,
) -> dict[str, Any]:
    root, code_map, refresh_receipt = load_code_map(project, refresh=refresh)
    terms = _query_terms(task)
    selected_files = _task_path_hints(root, task, targets)
    symbols = _selected_symbols(code_map, terms=_symbol_terms(task), files=selected_files)
    definitions = code_map.get("defIndex", {})
    references = code_map.get("refIndex", {})

    related_files: list[str] = list(selected_files)
    symbol_rows: list[dict[str, Any]] = []
    for key in symbols:
        defs = definitions.get(key) if isinstance(definitions, dict) else None
        refs = references.get(key) if isinstance(references, dict) else None
        definition_rows = [item for item in (defs or []) if isinstance(item, dict)][:8]
        reference_files = [str(item) for item in (refs or []) if isinstance(item, str)][:64]
        related_files.extend(str(item.get("f") or "") for item in definition_rows)
        related_files.extend(reference_files)
        symbol_rows.append(
            {
                "symbol": key,
                "definitions": definition_rows,
                "referencedBy": reference_files,
                "referenceCount": int((code_map.get("refCount") or {}).get(key) or len(reference_files)),
            }
        )
    selected_files = _bounded_strings(related_files, MAX_SELECTED_FILES)
    selected_modules = _bounded_strings((_module_of(value) for value in selected_files), 24)

    module_edges = []
    for edge in code_map.get("moduleEdges", []):
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        legacy = str(edge.get("edge") or "")
        if legacy and " → " in legacy:
            source, target = legacy.split(" → ", 1)
        if source in selected_modules or target in selected_modules:
            module_edges.append(
                {
                    "from": source,
                    "to": target,
                    "weight": int(edge.get("weight") or 0),
                    "relation": "depends_on",
                }
            )
        if len(module_edges) >= 48:
            break

    declared_nodes, declared_edges = _load_declared_graph(root)
    selected_nodes, selected_edges = _select_declared_context(
        declared_nodes,
        declared_edges,
        terms=terms,
        selected_files=selected_files,
    )
    task_digest = _canonical_digest({"task": task[:MAX_TASK_CHARS], "targets": list(targets)})
    map_fingerprint = str(code_map.get("fingerprintHash") or "")
    receipt_base = {
        "schemaVersion": CONTEXT_QUERY_RECEIPT_SCHEMA,
        "taskDigest": task_digest,
        "mapSchemaVersion": str(code_map.get("schemaVersion") or ""),
        "mapFingerprint": map_fingerprint,
        "mapGeneratedAt": str(code_map.get("generatedAt") or ""),
        "selectionBasis": [
            "exact_symbol",
            "definition_backlink",
            "file_scope",
            "module_dependency",
            "declared_context_inheritance",
        ],
        "selectedSymbols": symbols,
        "selectedFiles": selected_files,
        "selectedContextNodeIds": [_node_id(node) for node in selected_nodes],
        "refreshStatus": str((refresh_receipt or {}).get("status") or "not_requested"),
        "issuedAt": _utc_now(),
    }
    receipt_base["receiptDigest"] = _canonical_digest(receipt_base)
    return {
        "schemaVersion": CONTEXT_SLICE_SCHEMA,
        "project": str(code_map.get("project") or root.name),
        "taskDigest": task_digest,
        "goalsAndConstraints": [
            node for node in selected_nodes if _node_type(node) in _INHERITED_NODE_TYPES
        ],
        "relatedContextNodes": selected_nodes,
        "contextEdges": selected_edges,
        "symbols": symbol_rows,
        "files": selected_files,
        "modules": selected_modules,
        "moduleEdges": module_edges,
        "completionContract": {
            "beforeMutation": "Run context impact for every changed file or symbol and review all returned backlinks.",
            "beforeCompletion": "Verify every impacted file is changed, reviewed, or explicitly waived with a reason.",
            "localOnly": True,
        },
        "receipt": receipt_base,
    }


def locate(
    project: str | Path,
    query: str,
    *,
    refresh: bool = True,
) -> dict[str, Any]:
    root, code_map, refresh_receipt = load_code_map(project, refresh=refresh)
    terms = _query_terms(query)
    definitions = code_map.get("defIndex", {})
    references = code_map.get("refIndex", {})
    matches: list[dict[str, Any]] = []
    for term in terms:
        if term not in definitions:
            continue
        matches.append(
            {
                "symbol": term,
                "definitions": definitions.get(term, [])[:12],
                "referencedBy": references.get(term, [])[:64],
                "referenceCount": int((code_map.get("refCount") or {}).get(term) or 0),
            }
        )
        if len(matches) >= MAX_SELECTED_SYMBOLS:
            break
    return {
        "action": "context.locate",
        "status": "ok",
        "project": root.name,
        "mapFingerprint": code_map.get("fingerprintHash"),
        "refreshStatus": str((refresh_receipt or {}).get("status") or "not_requested"),
        "matches": matches,
    }


def references(
    project: str | Path,
    symbol: str,
    *,
    refresh: bool = True,
) -> dict[str, Any]:
    root, code_map, refresh_receipt = load_code_map(project, refresh=refresh)
    key = symbol.strip().lower()
    definitions = code_map.get("defIndex", {})
    ref_index = code_map.get("refIndex", {})
    found = key in definitions
    return {
        "action": "context.refs",
        "status": "ok" if found else "not_found",
        "project": root.name,
        "symbol": key,
        "definitions": definitions.get(key, [])[:32] if found else [],
        "referencedBy": ref_index.get(key, [])[:MAX_IMPACT_FILES] if found else [],
        "referenceCount": int((code_map.get("refCount") or {}).get(key) or 0),
        "mapFingerprint": code_map.get("fingerprintHash"),
        "refreshStatus": str((refresh_receipt or {}).get("status") or "not_requested"),
    }


def impact(
    project: str | Path,
    changed: Sequence[str],
    *,
    refresh: bool = True,
) -> dict[str, Any]:
    root, code_map, refresh_receipt = load_code_map(project, refresh=refresh)
    definitions = code_map.get("defIndex", {})
    references_index = code_map.get("refIndex", {})
    file_symbols = code_map.get("fileSymbols", {})
    changed_files: list[str] = []
    changed_symbols: list[str] = []
    for raw in changed:
        normalized = _normalize_file(root, raw)
        if normalized and (
            normalized in file_symbols
            or (root / normalized).exists()
            or "/" in raw
            or "." in Path(raw).name
        ):
            changed_files.append(normalized)
            for item in file_symbols.get(normalized, []) if isinstance(file_symbols, dict) else []:
                if isinstance(item, dict):
                    display = str(item.get("n") or "")
                    key = display.lower()
                    if key and (
                        "_" in display
                        or re.search(r"[a-z][A-Z]", display)
                        or len(display) >= 12
                    ):
                        changed_symbols.append(key)
        else:
            key = raw.strip().lower()
            if key and key in definitions:
                changed_symbols.append(key)

    impacted: set[str] = set(changed_files)
    paths: list[dict[str, Any]] = []
    for symbol in sorted(set(changed_symbols)):
        refs = [
            str(value)
            for value in references_index.get(symbol, [])
            if isinstance(value, str)
        ][:MAX_IMPACT_FILES]
        impacted.update(refs)
        paths.append(
            {
                "changedSymbol": symbol,
                "definitions": definitions.get(symbol, [])[:16],
                "affectedFiles": refs,
            }
        )
    impacted_files = sorted(impacted)[:MAX_IMPACT_FILES]
    receipt = {
        "schemaVersion": CONTEXT_IMPACT_RECEIPT_SCHEMA,
        "mapFingerprint": str(code_map.get("fingerprintHash") or ""),
        "changedFiles": sorted(set(changed_files)),
        "changedSymbols": sorted(set(changed_symbols)),
        "impactedFiles": impacted_files,
        "truncated": len(impacted) > MAX_IMPACT_FILES,
        "refreshStatus": str((refresh_receipt or {}).get("status") or "not_requested"),
        "issuedAt": _utc_now(),
    }
    receipt["receiptDigest"] = _canonical_digest(receipt)
    return {
        "action": "context.impact",
        "status": "ok",
        "project": root.name,
        "paths": paths,
        "impactedFiles": impacted_files,
        "impactedModules": _bounded_strings((_module_of(value) for value in impacted_files), 48),
        "receipt": receipt,
    }


def verify_impact(
    project: str | Path,
    changed: Sequence[str],
    reviewed: Sequence[str],
    *,
    waived: Sequence[str] = (),
    refresh: bool = True,
) -> dict[str, Any]:
    impact_result = impact(project, changed, refresh=refresh)
    root = _project_root(project)
    reviewed_files = {
        value for raw in reviewed if (value := _normalize_file(root, raw))
    }
    waived_files = {
        value for raw in waived if (value := _normalize_file(root, raw))
    }
    changed_files = set(impact_result["receipt"]["changedFiles"])
    required = set(impact_result["impactedFiles"])
    unresolved = sorted(required - changed_files - reviewed_files - waived_files)
    receipt = {
        "schemaVersion": CONTEXT_VERIFICATION_RECEIPT_SCHEMA,
        "impactReceiptDigest": impact_result["receipt"]["receiptDigest"],
        "mapFingerprint": impact_result["receipt"]["mapFingerprint"],
        "changedFiles": sorted(changed_files),
        "reviewedFiles": sorted(reviewed_files),
        "waivedFiles": sorted(waived_files),
        "unresolvedFiles": unresolved,
        "status": "passed" if not unresolved else "blocked",
        "issuedAt": _utc_now(),
    }
    receipt["receiptDigest"] = _canonical_digest(receipt)
    return {
        "action": "context.verify",
        "status": receipt["status"],
        "project": impact_result["project"],
        "receipt": receipt,
    }


def render_context_slice(value: Mapping[str, Any], *, max_chars: int = MAX_RENDER_CHARS) -> str:
    """Compact prompt representation; source paths only, never source contents."""

    lines = [
        "## Agentlas Context Slice (dependency-selected, project-local)",
        f"Receipt: {value.get('receipt', {}).get('receiptDigest', 'missing')}",
    ]
    goals = value.get("goalsAndConstraints")
    if isinstance(goals, list) and goals:
        lines.append("Inherited goals, constraints, decisions:")
        for node in goals[:20]:
            if not isinstance(node, Mapping):
                continue
            label = str(node.get("title") or node.get("name") or _node_id(node))
            lines.append(f"- [{_node_type(node) or 'context'}:{_node_status(node) or 'active'}] {label[:240]}")
    symbols = value.get("symbols")
    if isinstance(symbols, list) and symbols:
        lines.append("Definitions and backlinks:")
        for item in symbols[:20]:
            if not isinstance(item, Mapping):
                continue
            definitions = ", ".join(
                f"{row.get('f')}:{row.get('l')}"
                for row in item.get("definitions", [])[:4]
                if isinstance(row, Mapping)
            )
            refs = ", ".join(str(path) for path in item.get("referencedBy", [])[:12])
            lines.append(f"- {item.get('symbol')}: defs={definitions or '-'}; refs={refs or '-'}")
    files = value.get("files")
    if isinstance(files, list) and files:
        lines.append("Structurally related files:")
        lines.extend(f"- {path}" for path in files[:40])
    module_edges = value.get("moduleEdges")
    if isinstance(module_edges, list) and module_edges:
        lines.append("Module dependencies:")
        lines.extend(
            f"- {edge.get('from')} -> {edge.get('to')} (weight {edge.get('weight', 0)})"
            for edge in module_edges[:20]
            if isinstance(edge, Mapping)
        )
    lines.extend(
        [
            "Before mutation: run context impact for each changed file/symbol and inspect every backlink.",
            "Before completion: produce a passing context verification receipt or explicitly report unresolved impact.",
        ]
    )
    return "\n".join(lines)[:max_chars].rstrip()
