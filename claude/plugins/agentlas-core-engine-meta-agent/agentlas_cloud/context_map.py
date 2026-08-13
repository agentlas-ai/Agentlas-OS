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
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .project_bootstrap import (
    CODE_EXTENSIONS,
    CODE_MAP_CACHE_SCHEMA,
    CODE_MAP_MANIFEST_SCHEMA,
    CODE_MAP_POLICY_VERSION,
    MAX_CODE_FILES,
    MAX_CODE_SCAN_SECONDS,
    _fingerprint_hash,
    _content_snapshot,
    _context_index_policy,
    _file_role,
    _git_file_list,
    _is_ci_workflow_path,
    _is_test_path,
    _is_version_contract_path,
    _safe_file,
    _policy_allows,
    _walk_file_list,
    _walk_local_test_files,
    generate_code_map,
)


CODE_MAP_SCHEMA = "agentlas.code-map.v2"
CONTEXT_SLICE_SCHEMA = "agentlas.context-slice.v1"
CONTEXT_QUERY_RECEIPT_SCHEMA = "agentlas.context-query-receipt.v1"
CONTEXT_IMPACT_RECEIPT_SCHEMA = "agentlas.context-impact-receipt.v2"
CONTEXT_VERIFICATION_RECEIPT_SCHEMA = "agentlas.context-verification-receipt.v2"
VERIFICATION_MAP_SCHEMA = "agentlas.verification-map.v2"

MAX_MAP_BYTES = 24 * 1024 * 1024
MAX_TASK_CHARS = 12_000
MAX_QUERY_TERMS = 96
MAX_SELECTED_SYMBOLS = 12
MAX_SELECTED_FILES = 64
MAX_IMPACT_FILES = 2_048
MAX_CONTEXT_NODES = 48
MAX_CONTEXT_EDGES = 128
MAX_DECLARED_NODES = 2_000
MAX_DECLARED_EDGES = 8_000
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
    raw = value.strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or raw.startswith("/") or "\x00" in raw:
        return None
    if any(part == ".." for part in raw.split("/")):
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


def _symbol_terms(task: str, code_map: Mapping[str, Any] | None = None) -> list[str]:
    """Return symbol-shaped terms, not generic prose words.

    This is intentionally stricter than declared-context matching. A task that
    merely says "fix the context" must not select every function named
    ``context``; exact camelCase, snake_case, or long identifiers are eligible.

    The shape rule alone had a hole worth naming: a symbol whose name is a short
    lowercase word could never be selected, however exactly the user typed it.
    Measured on a fresh project whose only symbol was ``charge``: the map knew
    it, ``defIndex`` listed it, and "make the charge path safe to retry" came
    back with zero files and zero symbols. The user names the thing correctly and
    the slice answers with nothing.

    Rarity separates the two cases better than length does. A prose token that
    matches exactly one definition site is naming that thing; a token that
    matches many is the generic word the shape rule was defending against.
    """

    terms: list[str] = []
    definitions = (code_map or {}).get("defIndex")
    definitions = definitions if isinstance(definitions, Mapping) else {}
    for match in _TOKEN_RE.finditer(task[:MAX_TASK_CHARS]):
        raw = match.group(0)
        normalized = raw.lower()
        shaped = "_" in raw or re.search(r"[a-z][A-Z]", raw) or len(raw) >= 12
        if not shaped:
            sites = definitions.get(raw) or definitions.get(normalized)
            if not isinstance(sites, list) or not 0 < len(sites) <= _RARE_SYMBOL_SITES:
                continue
        if normalized not in terms:
            terms.append(normalized)
        if len(terms) >= MAX_QUERY_TERMS:
            break
    return terms


# A name that is defined in one or two places is naming something; a name
# defined everywhere is a word.
_RARE_SYMBOL_SITES = 2


def _task_path_hints(root: Path, task: str, targets: Sequence[str]) -> list[str]:
    paths: list[str] = []
    for raw in [*targets, *(match.group(1) for match in _PATH_HINT_RE.finditer(task[:MAX_TASK_CHARS]))]:
        normalized = _normalize_file(root, raw)
        if normalized:
            paths.append(normalized)
    return _bounded_strings(paths, MAX_SELECTED_FILES)


def _passive_code_map_fingerprint(root: Path) -> tuple[str, str, int, int, str]:
    """Recompute only the bounded freshness receipt without writing a map."""

    deadline = time.monotonic() + MAX_CODE_SCAN_SECONDS
    all_files, list_stop, _ = _git_file_list(root, deadline)
    source = "git" if all_files is not None else "filesystem"
    if all_files is None:
        all_files, list_stop, _ = _walk_file_list(root, deadline)
    if list_stop is not None:
        raise ContextMapError("context_freshness_incomplete")

    policy = _context_index_policy(root)
    listed_relative_files = {
        path.relative_to(root).as_posix()
        for path in all_files
        if _safe_file(root, path)
        and _policy_allows(path.relative_to(root).as_posix(), policy)
    }
    local_test_files, local_test_stop, _ = _walk_local_test_files(root, deadline, policy)
    if local_test_stop is not None:
        raise ContextMapError("context_freshness_incomplete")
    local_test_relative_files = {
        path.relative_to(root).as_posix()
        for path in local_test_files
        if _safe_file(root, path)
    }
    local_test_code_files = {
        relative
        for relative in local_test_relative_files
        if Path(relative).suffix.lower() in CODE_EXTENSIONS
    }
    relative_files = sorted(listed_relative_files | local_test_relative_files)
    source_code_candidates = [
        relative
        for relative in relative_files
        if Path(relative).suffix.lower() in CODE_EXTENSIONS
        and not _is_test_path(relative)
        and relative not in local_test_code_files
    ]
    if len(source_code_candidates) > MAX_CODE_FILES:
        raise ContextMapError("context_freshness_incomplete")
    code_files = source_code_candidates[:MAX_CODE_FILES]
    verification_files = [
        relative
        for relative in relative_files
        if (
            _is_ci_workflow_path(relative)
            or _is_version_contract_path(relative)
            or relative in local_test_relative_files
        )
    ]
    fingerprint_files = relative_files
    fingerprints: dict[str, dict[str, int]] = {}
    for relative in fingerprint_files:
        try:
            metadata = os.stat(root / relative, follow_symlinks=False)
        except OSError as exc:
            raise ContextMapError("context_freshness_incomplete") from exc
        fingerprints[relative] = {
            "mtimeNs": metadata.st_mtime_ns,
            "ctimeNs": metadata.st_ctime_ns,
            "size": metadata.st_size,
        }
    try:
        snapshot_id, _hashes, _read_bytes = _content_snapshot(root, relative_files, policy)
    except OSError as exc:
        raise ContextMapError("context_freshness_incomplete") from exc
    return _fingerprint_hash(fingerprints), snapshot_id, len(code_files), len(fingerprints), source


def _require_passive_freshness(
    root: Path,
    payload: Mapping[str, Any],
    cache: Mapping[str, Any],
) -> None:
    _fingerprint, snapshot_id, code_files, mapped_files, source = _passive_code_map_fingerprint(root)
    if (
        snapshot_id != str(payload.get("snapshotId") or "")
        or int(cache.get("candidateCodeFiles", -1)) != code_files
        or int(cache.get("candidateMappedFiles", -1)) != mapped_files
        or cache.get("completeListing") is not True
        or str(cache.get("listingSource") or "") != source
    ):
        raise ContextMapError("context_map_stale")


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
        refresh_stats = (
            refresh_receipt.get("stats")
            if isinstance(refresh_receipt.get("stats"), dict)
            else {}
        )
        if (
            str(refresh_receipt.get("refresh") or "") == "deferred"
            or refresh_receipt.get("coverageComplete") is False
            or refresh_stats.get("coverageComplete") is False
            or refresh_stats.get("budgetStop")
            or refresh_stats.get("outputTruncated") is True
        ):
            raise ContextMapError("context_refresh_incomplete")
    payload = _regular_json(root / ".agentlas" / "code-map" / "project-map.json", max_bytes=MAX_MAP_BYTES)
    schema = str(payload.get("schemaVersion") or "")
    if schema not in {CODE_MAP_SCHEMA, "5.0"}:
        raise ContextMapError("context_map_upgrade_required")
    if (
        not isinstance(payload.get("defIndex"), dict)
        or not isinstance(payload.get("refIndex"), dict)
        or not isinstance(payload.get("refCount"), dict)
        or not isinstance(payload.get("fileSymbols"), dict)
        or not isinstance(payload.get("indexedFiles"), list)
        or not isinstance(payload.get("mappedFiles"), list)
        or not isinstance(payload.get("fileRoles"), dict)
        or not isinstance(payload.get("dependencyEdges"), list)
        or not isinstance(payload.get("tombstones"), dict)
    ):
        raise ContextMapError("context_map_upgrade_required")
    verification_graph = payload.get("verificationGraph")
    if (
        not isinstance(verification_graph, dict)
        or verification_graph.get("schemaVersion") != VERIFICATION_MAP_SCHEMA
        or not isinstance(verification_graph.get("nodes"), list)
        or not isinstance(verification_graph.get("edges"), list)
        or not isinstance(verification_graph.get("issues"), list)
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(verification_graph.get("graphDigest") or ""),
        )
    ):
        raise ContextMapError("context_map_upgrade_required")
    cache = _regular_json(
        root / ".agentlas" / "code-map" / ".cache.json",
        max_bytes=1024 * 1024,
    )
    try:
        manifest = _regular_json(
            root / ".agentlas" / "code-map" / "manifest.json",
            max_bytes=1024 * 1024,
        )
    except ContextMapError as exc:
        raise ContextMapError("context_map_integrity_failed") from exc
    expected_root_hash = "sha256:" + hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    fingerprint = str(payload.get("fingerprintHash") or "")
    snapshot_id = str(payload.get("snapshotId") or "")
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    reference_index = payload["refIndex"]
    reference_count = payload["refCount"]
    coherent_references = all(
        isinstance(reference_index.get(key), list)
        and len(reference_index[key]) == int(count)
        for key, count in reference_count.items()
        if isinstance(count, int) and count >= 0
    ) and all(isinstance(count, int) and count >= 0 for count in reference_count.values())
    compatibility_map = (
        manifest.get("compatibilityMap")
        if isinstance(manifest.get("compatibilityMap"), dict)
        else {}
    )
    payload_digest = _canonical_digest(payload)
    if (
        not re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot_id)
        or payload.get("projectRootHash") != expected_root_hash
        or cache.get("schemaVersion") != CODE_MAP_CACHE_SCHEMA
        or cache.get("policyVersion") != CODE_MAP_POLICY_VERSION
        or cache.get("projectRootHash") != expected_root_hash
        or cache.get("fingerprintHash") != fingerprint
        or cache.get("snapshotId") != snapshot_id
        or cache.get("policyDigest") != payload.get("policyDigest")
        or cache.get("mapPayloadDigest") != payload_digest
        or manifest.get("schemaVersion") != CODE_MAP_MANIFEST_SCHEMA
        or manifest.get("projectRootHash") != expected_root_hash
        or manifest.get("snapshotId") != snapshot_id
        or manifest.get("policyDigest") != payload.get("policyDigest")
        or manifest.get("complete") is not True
        or compatibility_map.get("path") != "project-map.json"
        or compatibility_map.get("schemaVersion") != schema
        or compatibility_map.get("digest") != payload_digest
        or int(cache.get("candidateMappedFiles") or -1)
        != int(stats.get("candidateMappedFiles") or -2)
        or (
            not coherent_references
            and stats.get("outputTruncated") is not True
        )
    ):
        raise ContextMapError("context_map_integrity_failed")
    if (
        cache.get("completeMap") is not True
        or stats.get("coverageComplete") is not True
        or stats.get("incompleteReasons") != []
        or stats.get("scanComplete") is not True
        or stats.get("budgetStop")
        or stats.get("outputTruncated") is not False
        or int(stats.get("candidateCodeFiles") or 0) != int(stats.get("codeFiles") or 0)
    ):
        raise ContextMapError("context_map_incomplete")
    if not refresh:
        _require_passive_freshness(root, payload, cache)
    return root, payload, refresh_receipt


def _refresh_status(receipt: Mapping[str, Any] | None) -> str:
    if not receipt:
        return "not_requested"
    return str(receipt.get("refresh") or receipt.get("status") or "unknown")


def _node_id(node: Mapping[str, Any]) -> str:
    return str(node.get("id") or node.get("nodeId") or node.get("path") or "")


def _node_type(node: Mapping[str, Any]) -> str:
    return str(node.get("type") or node.get("kind") or "").lower()


def _node_status(node: Mapping[str, Any]) -> str:
    return str(node.get("status") or "").lower()


def _load_declared_graph(
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Merge explicit Context Map declarations with annotated sitemap nodes.

    Generated file/directory-only sitemap rows are deliberately ignored here:
    the code map already represents those paths.  Only typed functional/project
    nodes and explicit edges are eligible for inheritance.
    """

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    source_nodes = 0
    source_edges = 0
    loaded_sources: list[str] = []
    for relative in (".agentlas/context-map.json", ".agentlas/sitemap.json"):
        path = root / relative
        if not path.exists():
            continue
        try:
            payload = _regular_json(path, max_bytes=16 * 1024 * 1024)
        except ContextMapError as exc:
            raise ContextMapError("context_declared_map_invalid") from exc
        loaded_sources.append(relative)
        raw_nodes = payload.get("nodes")
        raw_edges = payload.get("edges") or payload.get("relationships")
        if raw_nodes is not None and not isinstance(raw_nodes, list):
            raise ContextMapError("context_declared_map_invalid")
        if raw_edges is not None and not isinstance(raw_edges, list):
            raise ContextMapError("context_declared_map_invalid")
        if isinstance(raw_nodes, list):
            source_nodes += len(raw_nodes)
            for candidate in raw_nodes:
                if not isinstance(candidate, dict):
                    raise ContextMapError("context_declared_map_invalid")
                kind = _node_type(candidate)
                if relative.endswith("sitemap.json") and kind in {"file", "directory"}:
                    continue
                if not _node_id(candidate):
                    raise ContextMapError("context_declared_map_invalid")
                if _node_status(candidate) in _ACTIVE_STATES:
                    nodes.append(dict(candidate))
        if isinstance(raw_edges, list):
            source_edges += len(raw_edges)
            for candidate in raw_edges:
                if not isinstance(candidate, dict):
                    raise ContextMapError("context_declared_map_invalid")
                source, target, _ = _edge_parts(candidate)
                if not source or not target:
                    raise ContextMapError("context_declared_map_invalid")
                edges.append(dict(candidate))
    loaded_nodes = nodes[:MAX_DECLARED_NODES]
    loaded_edges = edges[:MAX_DECLARED_EDGES]
    report = {
        "sources": loaded_sources,
        "sourceNodeCount": source_nodes,
        "sourceEdgeCount": source_edges,
        "eligibleNodeCount": len(nodes),
        "eligibleEdgeCount": len(edges),
        "loadedNodeCount": len(loaded_nodes),
        "loadedEdgeCount": len(loaded_edges),
        "omittedNodeCount": max(0, len(nodes) - len(loaded_nodes)),
        "omittedEdgeCount": max(0, len(edges) - len(loaded_edges)),
    }
    report["partial"] = bool(report["omittedNodeCount"] or report["omittedEdgeCount"])
    return loaded_nodes, loaded_edges, report


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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
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
    selected_edge_keys: set[tuple[str, str, str]] = set()
    for _ in range(2):
        changed = False
        for edge in edges:
            source, target, relation = _edge_parts(edge)
            if not source or not target:
                continue
            if source in selected or target in selected:
                if source in by_id and source not in selected:
                    selected.add(source)
                    changed = True
                if target in by_id and target not in selected:
                    selected.add(target)
                    changed = True
                edge_key = (source, target, relation)
                if edge_key not in selected_edge_keys:
                    selected_edge_keys.add(edge_key)
                    selected_edges.append(edge)
        if not changed:
            break
    eligible_nodes = [by_id[node_id] for node_id in sorted(selected) if node_id in by_id]
    eligible_edge_count = len(selected_edges)
    selected_nodes = eligible_nodes[:MAX_CONTEXT_NODES]
    allowed_ids = {_node_id(node) for node in selected_nodes}
    selected_edges = [
        edge
        for edge in selected_edges
        if _edge_parts(edge)[0] in allowed_ids and _edge_parts(edge)[1] in allowed_ids
    ][:MAX_CONTEXT_EDGES]
    report = {
        "eligibleNodeCount": len(eligible_nodes),
        "eligibleEdgeCount": eligible_edge_count,
        "selectedNodeCount": len(selected_nodes),
        "selectedEdgeCount": len(selected_edges),
        "omittedNodeCount": max(0, len(eligible_nodes) - len(selected_nodes)),
        "omittedEdgeCount": max(0, eligible_edge_count - len(selected_edges)),
    }
    report["partial"] = bool(report["omittedNodeCount"] or report["omittedEdgeCount"])
    return selected_nodes, selected_edges, report


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
    symbols = _selected_symbols(code_map, terms=_symbol_terms(task, code_map), files=selected_files)
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
    verification_graph = (
        code_map.get("verificationGraph")
        if isinstance(code_map.get("verificationGraph"), dict)
        else {}
    )
    verification_nodes = {
        str(node.get("id") or ""): node
        for node in verification_graph.get("nodes", [])
        if isinstance(node, dict) and str(node.get("id") or "")
    }
    verification_entities = set(selected_files)
    verification_entities.update(
        node_id
        for node_id, node in verification_nodes.items()
        if str(node.get("path") or "") in selected_files
    )
    selected_verification_edges: list[dict[str, Any]] = []
    selected_verification_ids: set[str] = set()
    for _ in range(4):
        next_entities: set[str] = set()
        for edge in verification_graph.get("edges", []):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("from") or "")
            target = str(edge.get("to") or "")
            if source not in verification_entities or not target:
                continue
            selected_verification_edges.append(dict(edge))
            if target in verification_nodes:
                selected_verification_ids.add(target)
            next_entities.add(target)
        if not next_entities - verification_entities:
            break
        verification_entities.update(next_entities)
    selected_verification_nodes = [
        verification_nodes[node_id]
        for node_id in sorted(selected_verification_ids)
    ][:128]
    selected_verification_edges = selected_verification_edges[:256]

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

    # Slice construction is a reader. Explicit project bootstrap/refresh owns
    # declared-context materialization; a query must never rewrite project state.
    declared_nodes, declared_edges, declared_load = _load_declared_graph(root)
    selected_nodes, selected_edges, declared_selection = _select_declared_context(
        declared_nodes,
        declared_edges,
        terms=terms,
        selected_files=selected_files,
    )
    task_digest = _canonical_digest({"task": task[:MAX_TASK_CHARS], "targets": list(targets)})
    map_fingerprint = str(code_map.get("fingerprintHash") or "")
    declared_context_receipt = {
        **declared_load,
        "selectedNodeCount": declared_selection["selectedNodeCount"],
        "selectedEdgeCount": declared_selection["selectedEdgeCount"],
        "selectionEligibleNodeCount": declared_selection["eligibleNodeCount"],
        "selectionEligibleEdgeCount": declared_selection["eligibleEdgeCount"],
        "omittedNodeCount": declared_load["omittedNodeCount"]
        + declared_selection["omittedNodeCount"],
        "omittedEdgeCount": declared_load["omittedEdgeCount"]
        + declared_selection["omittedEdgeCount"],
        "partial": bool(declared_load["partial"] or declared_selection["partial"]),
    }
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
            "verification_dependency",
        ],
        "selectedSymbols": symbols,
        "selectedFiles": selected_files,
        "selectedContextNodeIds": [_node_id(node) for node in selected_nodes],
        "partial": declared_context_receipt["partial"],
        "declaredContext": declared_context_receipt,
        "refreshStatus": _refresh_status(refresh_receipt),
        "issuedAt": _utc_now(),
    }
    receipt_base["receiptDigest"] = _canonical_digest(receipt_base)
    return {
        "schemaVersion": CONTEXT_SLICE_SCHEMA,
        "status": "partial" if declared_context_receipt["partial"] else "ok",
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
        "verification": {
            "schemaVersion": VERIFICATION_MAP_SCHEMA,
            "graphDigest": str(verification_graph.get("graphDigest") or ""),
            "nodes": selected_verification_nodes,
            "edges": selected_verification_edges,
            "issues": [
                issue
                for issue in verification_graph.get("issues", [])
                if isinstance(issue, dict)
            ][:64],
        },
        "completionContract": {
            "beforeMutation": "Run context impact for every changed file or symbol and review all returned backlinks.",
            "beforeCompletion": "Verify impacted source dependents, then satisfy one linked execution channel: local tests/test commands or CI workflows. Version contracts remain a separate release responsibility.",
            "verificationChannelPolicy": "any-valid-channel",
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
        "refreshStatus": _refresh_status(refresh_receipt),
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
        "refreshStatus": _refresh_status(refresh_receipt),
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
    dependency_edges = [
        edge for edge in code_map.get("dependencyEdges", []) if isinstance(edge, Mapping)
    ]
    file_roles = code_map.get("fileRoles") if isinstance(code_map.get("fileRoles"), dict) else {}
    tombstones = code_map.get("tombstones") if isinstance(code_map.get("tombstones"), dict) else {}
    indexed_files = {
        str(value)
        for value in code_map.get("mappedFiles", code_map.get("indexedFiles", []))
        if isinstance(value, str)
    }
    changed_files: list[str] = []
    changed_symbols: list[str] = []
    change_kinds: list[dict[str, str]] = []
    for raw in changed:
        normalized = _normalize_file(root, raw)
        if normalized and normalized in indexed_files:
            changed_files.append(normalized)
            change_kinds.append(
                {
                    "path": normalized,
                    "status": "modified",
                    "role": str(file_roles.get(normalized) or "unknown"),
                    "resolution": "current",
                }
            )
            for item in file_symbols.get(normalized, []) if isinstance(file_symbols, dict) else []:
                if isinstance(item, dict):
                    display = str(item.get("n") or "")
                    key = display.lower()
                    if key:
                        changed_symbols.append(key)
        elif (
            normalized
            and _policy_allows(normalized, _context_index_policy(root))
            and _safe_file(root, root / normalized)
        ):
            changed_files.append(normalized)
            change_kinds.append(
                {
                    "path": normalized,
                    "status": "modified",
                    "role": _file_role(normalized),
                    "resolution": "opaque-current",
                }
            )
        elif normalized and normalized in tombstones:
            changed_files.append(normalized)
            tombstone = tombstones.get(normalized)
            tombstone = tombstone if isinstance(tombstone, Mapping) else {}
            change_kinds.append(
                {
                    "path": normalized,
                    "status": "deleted",
                    "role": str(tombstone.get("role") or "unknown"),
                    "resolution": "tombstone",
                }
            )
        else:
            if normalized is None:
                raise ContextMapError("context_changed_target_invalid")
            key = raw.strip().lower()
            if key and key in definitions:
                changed_symbols.append(key)
            else:
                raise ContextMapError("context_changed_target_unknown")
    if not changed_files and not changed_symbols:
        raise ContextMapError("context_changed_target_required")

    impacted: set[str] = set(changed_files)
    paths: list[dict[str, Any]] = []
    dependency_frontier = set(changed_files)
    while dependency_frontier:
        next_frontier: set[str] = set()
        for edge in dependency_edges:
            source = str(edge.get("from") or "")
            target = str(edge.get("to") or "")
            if (
                source in dependency_frontier
                and target
                and str(file_roles.get(target) or "") != "test"
                and target not in impacted
            ):
                impacted.add(target)
                next_frontier.add(target)
                if len(impacted) > MAX_IMPACT_FILES:
                    break
        if len(impacted) > MAX_IMPACT_FILES:
            break
        if not next_frontier:
            break
        dependency_frontier = next_frontier
    for symbol in sorted(set(changed_symbols)):
        # Lexical references remain useful for locate/refs, but are advisory
        # for file changes. Only an explicitly supplied symbol may expand by
        # text mention; changed files use exact dependency edges above.
        refs = []
        if not changed_files:
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
    verification_graph = (
        code_map.get("verificationGraph")
        if isinstance(code_map.get("verificationGraph"), dict)
        else {}
    )
    verification_nodes = {
        str(node.get("id") or ""): {
            "id": str(node.get("id") or ""),
            "path": str(node.get("path") or ""),
            "kind": str(node.get("kind") or "verification"),
        }
        for node in verification_graph.get("nodes", [])
        if isinstance(node, dict) and str(node.get("id") or "")
    }
    verification_nodes_by_path = {
        node["path"]: node
        for node in verification_nodes.values()
        if node["path"]
    }
    verification_edges = [
        edge
        for edge in verification_graph.get("edges", [])
        if isinstance(edge, dict)
    ]
    verification_issues: list[dict[str, str]] = []
    for issue in verification_graph.get("issues", []):
        if not isinstance(issue, dict):
            continue
        source = str(issue.get("source") or "")
        source_node = verification_nodes.get(source) or verification_nodes_by_path.get(source) or {}
        source_id = str(source_node.get("id") or source)
        source_path = str(source_node.get("path") or source)
        source_kind = str(source_node.get("kind") or "")
        issue_channel = (
            "ci"
            if source_kind == "ci_workflow"
            else "local"
            if source_kind in {"test", "test_command"}
            else ""
        )
        missing_path = str(issue.get("missingPath") or "")
        if source_path and missing_path:
            verification_issues.append(
                {
                    "code": str(issue.get("code") or "verification_graph_issue"),
                    "sourceId": source_id,
                    "source": source_path,
                    "channel": issue_channel,
                    "missingPath": missing_path,
                }
            )
    frontier = set(impacted)
    frontier.update(
        node_id
        for node_id, node in verification_nodes.items()
        if node["path"] in impacted
    )
    seen_entities = set(frontier)
    verification_targets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for _ in range(4):
        next_frontier: set[str] = set()
        for edge in verification_edges:
            source = str(edge.get("from") or "")
            target = str(edge.get("to") or "")
            relation = str(edge.get("relation") or "verifies")
            if (
                source not in frontier
                or not target
                or relation.startswith("advisory_")
                or relation == "released_by"
            ):
                continue
            node = verification_nodes.get(target)
            if node and node["path"]:
                target_key = (node["id"], node["kind"], relation)
                verification_targets[target_key] = {
                    "id": node["id"],
                    "path": node["path"],
                    "kind": node["kind"],
                    "relation": relation,
                    "from": source,
                }
            if target not in seen_entities:
                seen_entities.add(target)
                next_frontier.add(target)
        if not next_frontier:
            break
        frontier = next_frontier
    for node_id, node in verification_nodes.items():
        if not node["path"] or node["path"] not in changed_files:
            continue
        target_key = (node["id"], node["kind"], "structural_impact")
        verification_targets.setdefault(
            target_key,
            {
                "id": node["id"],
                "path": node["path"],
                "kind": node["kind"],
                "relation": "structural_impact",
                "from": node_id,
            },
        )
    verification_issues = [
        issue
        for issue in verification_issues
        if str(issue.get("sourceId") or "") in seen_entities
        or str(issue.get("source") or "") in impacted
    ]
    target_rows = [
        verification_targets[key]
        for key in sorted(verification_targets)
    ]
    local_commands = sorted(
        {
            str(target.get("id") or "")
            for target in target_rows
            if str(target.get("kind") or "") == "test_command"
            and str(target.get("id") or "")
        }
    )
    local_tests = sorted(
        {
            str(target.get("path") or "")
            for target in target_rows
            if str(target.get("kind") or "") == "test"
            and str(target.get("path") or "")
        }
    )
    verification_channels = {
        # Test paths and exact package-command IDs are independent execution
        # receipts. Keep their union: discovering a test file must not make a
        # valid command receipt unrecognizable.
        "local": sorted(set(local_tests) | set(local_commands)),
        "ci": sorted(
            {
                str(target.get("id") or "")
                for target in target_rows
                if str(target.get("kind") or "") == "ci_workflow"
                and str(target.get("id") or "")
            }
        ),
    }
    if len(impacted) > MAX_IMPACT_FILES:
        # A partial impact set cannot be honest completion evidence. Require
        # the caller to narrow or decompose the change instead of returning a
        # clipped list as status=ok.
        raise ContextMapError("context_impact_incomplete")
    impacted_files = sorted(impacted)
    map_stats = code_map.get("stats") if isinstance(code_map.get("stats"), dict) else {}
    map_budget_stop = str(map_stats.get("budgetStop") or "")
    map_output_truncated = map_stats.get("outputTruncated") is True
    map_complete = (
        bool(map_stats)
        and map_stats.get("coverageComplete") is True
        and map_stats.get("incompleteReasons") == []
        and map_stats.get("scanComplete") is True
        and not map_budget_stop
        and not map_output_truncated
    )
    canonical_changes = sorted(
        {
            (change["path"], change["status"], change["role"], change["resolution"]): change
            for change in change_kinds
        }.values(),
        key=lambda change: (
            change["path"],
            change["status"],
            change["role"],
            change["resolution"],
        ),
    )
    receipt = {
        "schemaVersion": CONTEXT_IMPACT_RECEIPT_SCHEMA,
        "mapFingerprint": str(code_map.get("fingerprintHash") or ""),
        "snapshotId": str(code_map.get("snapshotId") or ""),
        "changeSetDigest": _canonical_digest(canonical_changes),
        "mapComplete": map_complete,
        "mapBudgetStop": map_budget_stop or None,
        "mapOutputTruncated": map_output_truncated,
        "mapIncompleteReasons": list(map_stats.get("incompleteReasons") or []),
        "changedFiles": sorted(set(changed_files)),
        "changes": canonical_changes,
        "changedSymbols": sorted(set(changed_symbols)),
        "impactedFiles": impacted_files,
        "verificationTargets": target_rows,
        "verificationChannelPolicy": "one-executed-valid-channel",
        "verificationChannels": verification_channels,
        "releaseObligations": sorted(
            {
                str(target.get("path") or "")
                for target in target_rows
                if str(target.get("kind") or "") == "version_contract"
                and str(target.get("path") or "")
            }
        ),
        "verificationGraphDigest": str(verification_graph.get("graphDigest") or ""),
        "verificationIssues": verification_issues,
        "truncated": False,
        "refreshStatus": _refresh_status(refresh_receipt),
    }
    receipt["receiptDigest"] = _canonical_digest(receipt)
    receipt["issuedAt"] = _utc_now()
    return {
        "action": "context.impact",
        "status": "ok",
        "project": root.name,
        "paths": paths,
        "impactedFiles": impacted_files,
        "verificationTargets": receipt["verificationTargets"],
        "impactedModules": _bounded_strings((_module_of(value) for value in impacted_files), 48),
        "receipt": receipt,
    }


def verify_impact(
    project: str | Path,
    changed: Sequence[str],
    reviewed: Sequence[str],
    *,
    verified: Sequence[str] = (),
    waived: Sequence[str] = (),
    refresh: bool = True,
) -> dict[str, Any]:
    impact_result = impact(project, changed, refresh=refresh)
    impact_receipt = impact_result["receipt"]
    if impact_receipt.get("mapComplete") is not True or impact_receipt.get("truncated") is True:
        raise ContextMapError("context_verification_map_incomplete")
    root = _project_root(project)
    if any(_normalize_file(root, raw) is None for raw in [*reviewed, *verified, *waived]):
        raise ContextMapError("context_verification_evidence_invalid")
    reviewed_files = {
        value for raw in reviewed if (value := _normalize_file(root, raw))
    }
    reviewed_scopes = {
        value.rstrip("/") + "/"
        for raw in reviewed
        if raw.strip().replace("\\", "/").endswith("/")
        and (value := _normalize_file(root, raw.strip().rstrip("/")))
    }
    verified_files = {
        value for raw in verified if (value := _normalize_file(root, raw))
    }
    waived_files = {
        value for raw in waived if (value := _normalize_file(root, raw))
    }
    changed_files = set(impact_receipt["changedFiles"])
    required = set(impact_result["impactedFiles"])
    reviewed_by_scope = {
        path for path in required if any(path.startswith(scope) for scope in reviewed_scopes)
    }
    channel_rows = impact_receipt.get("verificationChannels")
    verification_channels = (
        {
            str(name): {
                str(path)
                for path in paths
                if isinstance(path, str) and path
            }
            for name, paths in channel_rows.items()
            if isinstance(name, str) and isinstance(paths, list)
        }
        if isinstance(channel_rows, Mapping)
        else {}
    )
    eligible_channels = sorted(
        name for name, paths in verification_channels.items() if paths
    )
    satisfied_channels = sorted(
        name
        for name, paths in verification_channels.items()
        if paths and bool(paths & verified_files)
    )
    selected_channel = satisfied_channels[0] if satisfied_channels else None
    unresolved = sorted(
        required - changed_files - reviewed_files - reviewed_by_scope - waived_files
    )
    verification_evidence_missing = bool(eligible_channels) and not selected_channel
    unresolved_verification_issues = [
        issue
        for issue in impact_receipt.get("verificationIssues", [])
        if isinstance(issue, Mapping)
        and str(issue.get("source") or "") not in waived_files
        and (
            not selected_channel
            or str(issue.get("channel") or "") in {"", selected_channel}
        )
    ]
    valid_verification_evidence = set().union(*verification_channels.values()) if verification_channels else set()
    issue_sources = {
        str(issue.get("source") or "")
        for issue in impact_receipt.get("verificationIssues", [])
        if isinstance(issue, Mapping)
    }
    unrecognized_evidence = {
        "reviewed": sorted(
            path
            for path in reviewed_files
            if path not in required and not any(item.startswith(path.rstrip("/") + "/") for item in required)
        ),
        "verified": sorted(verified_files - valid_verification_evidence),
        "waived": sorted(waived_files - required - issue_sources),
    }
    has_unrecognized_evidence = any(unrecognized_evidence.values())
    receipt = {
        "schemaVersion": CONTEXT_VERIFICATION_RECEIPT_SCHEMA,
        "impactReceiptDigest": impact_receipt["receiptDigest"],
        "mapFingerprint": impact_receipt["mapFingerprint"],
        "snapshotId": impact_receipt.get("snapshotId"),
        "changeSetDigest": impact_receipt.get("changeSetDigest"),
        "verificationGraphDigest": impact_receipt.get("verificationGraphDigest"),
        "verificationTargets": impact_receipt.get("verificationTargets", []),
        "verificationChannelPolicy": "one-executed-valid-channel",
        "verificationChannels": {
            name: sorted(paths)
            for name, paths in sorted(verification_channels.items())
        },
        "eligibleVerificationChannels": eligible_channels,
        "satisfiedVerificationChannels": satisfied_channels,
        "selectedVerificationChannel": selected_channel,
        "verificationEvidenceMissing": verification_evidence_missing,
        "releaseObligations": impact_receipt.get("releaseObligations", []),
        "verificationIssues": unresolved_verification_issues,
        "unrecognizedEvidence": unrecognized_evidence,
        "changedFiles": sorted(changed_files),
        "reviewedFiles": sorted(reviewed_files),
        "reviewedScopes": sorted(reviewed_scopes),
        "verifiedFiles": sorted(verified_files),
        "waivedFiles": sorted(waived_files),
        "unresolvedFiles": unresolved,
        "unresolvedCount": len(unresolved),
        "unresolvedModuleCounts": dict(
            sorted(Counter(_module_of(path) for path in unresolved).items())
        ),
        "status": (
            "passed"
            if not unresolved
            and not unresolved_verification_issues
            and not verification_evidence_missing
            and not has_unrecognized_evidence
            else "blocked"
        ),
    }
    receipt["receiptDigest"] = _canonical_digest(receipt)
    receipt["issuedAt"] = _utc_now()
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
    verification = value.get("verification")
    if isinstance(verification, Mapping) and verification.get("nodes"):
        lines.append("Verification responsibilities:")
        for node in list(verification.get("nodes") or [])[:30]:
            if isinstance(node, Mapping):
                lines.append(
                    f"- {node.get('kind', 'verification')}: {node.get('path', '-')}"
                )
    if isinstance(verification, Mapping) and verification.get("issues"):
        lines.append("Verification graph issues:")
        for issue in list(verification.get("issues") or [])[:20]:
            if isinstance(issue, Mapping):
                lines.append(
                    f"- {issue.get('code', 'issue')}: {issue.get('source', '-')} -> {issue.get('missingPath', '-')}"
                )
    lines.extend(
        [
            "Before mutation: run context impact for each changed file/symbol and inspect every backlink.",
            "Before completion: account for impacted source dependents and satisfy one linked execution channel (local tests/test commands or CI workflows). Version contracts remain a separate release responsibility.",
        ]
    )
    return "\n".join(lines)[:max_chars].rstrip()
