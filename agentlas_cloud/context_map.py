"""Dependency-aware, project-local context slices for every Agentlas host.

The code map is an index, not prompt material.  This module turns that index
plus optional declared project context into a bounded task slice and issues
content-free receipts for later impact verification.
"""

from __future__ import annotations

import hashlib
import itertools
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
    unpack_sitemap_edges,
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

# Local-only maps: read from the project's own .agentlas/, never uploaded.
MAX_MAP_BYTES = None
MAX_TASK_CHARS = 12_000
MAX_QUERY_TERMS = 96
MAX_SELECTED_SYMBOLS = 12
MAX_SELECTED_FILES = 64
MAX_IMPACT_FILES = 2_048
MAX_CONTEXT_NODES = 48
MAX_CONTEXT_EDGES = 128
MAX_DECLARED_NODES = 2_000
# Default recall budget. Chosen against the tightest shipped hook contract
# (PreToolUse 10s) minus what the rest of the capsule costs (measured 2.2s for
# ontology + One + workforce), and against Desktop's 4s slice kill. Small
# projects finish the real check well inside it and stay fully verified; only
# large ones fall back to the labelled path.
MAX_RENDERED_CONTEXT_EDGES = 12
RECALL_FRESHNESS_BUDGET_SECONDS = 1.5
# Recall runs inside a host hook whose contract is measured in seconds: the
# tightest shipped budget is PreToolUse at 10s (host_adapters/hooks/*/hooks.json),
# and Desktop kills its slice subprocess at 4s. The passive freshness receipt
# walks the whole repository, so on a large project it cannot fit — measured on
# the pilot: 29.6s before the _safe_file repair, 11.0s after. Recall therefore
# asks for freshness under a budget and, when the budget runs out, serves the
# last complete map labelled `unverified` instead of returning nothing. An
# unverified map with an honest label beats an empty capsule; the same trade
# already exists for `stale_served`.
MAX_DECLARED_EDGES = 8_000
# Per-node edge budget for closure. Keeps one hub node from filling the slice.
MAX_EDGES_PER_NODE = 64
# Tier for inherited project context that the task never reached. Higher than
# any traversal hop so it only fills budget the task left unused.
_INHERITED_TIER = 9
# What the project IS, as opposed to what it has accumulated. Bounded in
# practice, so these seed traversal instead of waiting for leftover budget.
_DEFINING_NODE_TYPES = frozenset({"project", "goal", "subgoal", "requirement", "constraint"})
# Which declared types carry the most for a reader. Used only to break ties
# inside a tier, never to exclude anything.
_NODE_TYPE_RANK = {
    "goal": 0, "subgoal": 1, "requirement": 2, "constraint": 3,
    "decision": 4, "metric": 5, "deadline": 6, "project": 7,
    "fact": 8, "procedure": 9, "assumption": 10,
}
_DEFAULT_TYPE_RANK = 11
MAX_RENDER_CHARS = 9_000

# ASCII identifiers (3+) OR any run of non-ASCII letters (2+). The ASCII-only
# form silently discarded every Korean/Japanese/Chinese word: measured on four
# real projects, "API 라우트 추가" tokenised to ['api'] alone and the slice
# returned files 0 / symbols 0 while the English "add API route" found 13/5.
# Non-ASCII terms cannot match code symbols, but they DO match declared titles
# in sitemap/context-map, which is where a non-English author's intent lives.
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|[^\W\d_]{2,}", re.UNICODE)
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


def _regular_json(path: Path, *, max_bytes: int | None = None) -> dict[str, Any]:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ContextMapError("context_map_missing") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_size <= 0
        or (max_bytes is not None and metadata.st_size > max_bytes)
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
            # Rarity does not rescue a function word. "from published sources"
            # matched a helper literally named `from` (one definition site, so
            # the rarity gate passed) and dragged its 3,998 references into the
            # slice — measured 2026-08-19. A prose stopword names nothing,
            # however rarely someone defined it; shaped identifiers
            # (`from_wire`) remain eligible above.
            if normalized in _STOP_TERMS:
                continue
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


def _passive_code_map_fingerprint(
    root: Path,
    *,
    budget_seconds: float | None = None,
) -> tuple[str, str, int, int, str]:
    """Recompute only the bounded freshness receipt without writing a map.

    ``budget_seconds`` caps the wall clock a caller is willing to spend. Running
    out raises ``context_freshness_budget_exceeded``, which is deliberately a
    different code from ``context_freshness_incomplete``: the first means "we
    stopped asking", the second means "the answer itself is unusable". Callers
    that can serve a labelled map treat only the first as recoverable.
    """

    started = time.monotonic()
    scan_deadline = started + MAX_CODE_SCAN_SECONDS
    budget_deadline = started + budget_seconds if budget_seconds is not None else None
    deadline = min(scan_deadline, budget_deadline) if budget_deadline is not None else scan_deadline

    def _check_budget() -> None:
        if budget_deadline is not None and time.monotonic() >= budget_deadline:
            raise ContextMapError("context_freshness_budget_exceeded")

    all_files, list_stop, _ = _git_file_list(root, deadline)
    source = "git" if all_files is not None else "filesystem"
    if all_files is None:
        all_files, list_stop, _ = _walk_file_list(root, deadline)
    if list_stop is not None:
        # A stop under a budget is the budget, not a broken scan.
        _check_budget()
        raise ContextMapError("context_freshness_incomplete")
    _check_budget()

    policy = _context_index_policy(root)
    listed_relative_files = {
        path.relative_to(root).as_posix()
        for path in all_files
        if _safe_file(root, path)
        and _policy_allows(path.relative_to(root).as_posix(), policy)
    }
    _check_budget()
    local_test_files, local_test_stop, _ = _walk_local_test_files(root, deadline, policy)
    if local_test_stop is not None:
        _check_budget()
        raise ContextMapError("context_freshness_incomplete")
    _check_budget()
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
    for index, relative in enumerate(fingerprint_files):
        if budget_deadline is not None and index % 1024 == 0:
            _check_budget()
        try:
            metadata = os.stat(root / relative, follow_symlinks=False)
        except OSError as exc:
            raise ContextMapError("context_freshness_incomplete") from exc
        fingerprints[relative] = {
            "mtimeNs": metadata.st_mtime_ns,
            "ctimeNs": metadata.st_ctime_ns,
            "size": metadata.st_size,
        }
    _check_budget()
    try:
        snapshot_id, _hashes, _read_bytes = _content_snapshot(root, relative_files, policy)
    except OSError as exc:
        raise ContextMapError("context_freshness_incomplete") from exc
    return _fingerprint_hash(fingerprints), snapshot_id, len(code_files), len(fingerprints), source


def _require_passive_freshness(
    root: Path,
    payload: Mapping[str, Any],
    cache: Mapping[str, Any],
    *,
    budget_seconds: float | None = None,
) -> None:
    _fingerprint, snapshot_id, code_files, mapped_files, source = _passive_code_map_fingerprint(
        root, budget_seconds=budget_seconds
    )
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
    allow_stale: bool = False,
    freshness_budget_seconds: float | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any] | None]:
    """Load the canonical map, optionally refreshing its fingerprint first.

    ``allow_stale`` serves the last complete map even when the passive
    freshness check would reject it, and reports that in the receipt. Read-only
    callers that cannot refresh (the recall hook) otherwise return nothing on
    any actively-edited project — measured: the pilot workspace was always
    stale because another session was writing, so the hook never delivered a
    slice to the very sessions doing the work. A stale map with a stale flag
    beats no map.

    ``freshness_budget_seconds`` caps that passive check. Exhausting it is not
    an error for a caller that already accepts stale data: the map is served
    with ``refresh: "unverified_served"``, which says "this map may be current,
    we did not have time to prove it" — distinct from ``stale_served``, which
    says "we proved it is behind". Measured on the pilot repository the check
    costs 11.0s against a 10s PreToolUse contract and a 4s Desktop kill, so
    without a budget every recall on a large project silently produced nothing.
    """

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
    cache = _regular_json(root / ".agentlas" / "code-map" / ".cache.json")
    try:
        manifest = _regular_json(root / ".agentlas" / "code-map" / "manifest.json")
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
        # Oversized/unreadable files are skipped by policy, not by budget
        # failure, so they count as covered here (see project_bootstrap).
        or int(stats.get("candidateCodeFiles") or 0)
        != int(stats.get("codeFiles") or 0)
        + int(stats.get("skippedLarge") or 0)
        + int(stats.get("skippedUnreadable") or 0)
    ):
        raise ContextMapError("context_map_incomplete")
    if not refresh:
        try:
            _require_passive_freshness(
                root, payload, cache, budget_seconds=freshness_budget_seconds
            )
        except ContextMapError as exc:
            code = getattr(exc, "code", "")
            if not allow_stale or code not in {
                "context_map_stale",
                "context_freshness_budget_exceeded",
            }:
                raise
            if code == "context_freshness_budget_exceeded":
                refresh_receipt = {
                    **(refresh_receipt or {}),
                    "refresh": "unverified_served",
                    "freshnessVerified": False,
                    "freshnessBudgetSeconds": freshness_budget_seconds,
                }
            else:
                refresh_receipt = {**(refresh_receipt or {}), "refresh": "stale_served", "stale": True}
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
    *,
    include_inactive: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Merge explicit Context Map declarations with annotated sitemap nodes.

    Generated file/directory-only sitemap rows are deliberately ignored here:
    the code map already represents those paths.  Only typed functional/project
    nodes and explicit edges are eligible for inheritance.

    ``include_inactive`` keeps deprecated/superseded nodes. A slice must not
    inherit dead context, but drift detection exists precisely to find a node
    declared dead whose implementation is still live — dropping those here made
    that check structurally unable to fire.
    """

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    source_nodes = 0
    source_edges = 0
    loaded_sources: list[str] = []
    # One declared file being unreadable must not close the whole library. Each
    # file is loaded independently; a failure is recorded, never raised, so the
    # slice degrades to whatever remains and the receipt says what was skipped.
    # Measured: a single malformed sitemap.json turned every context_slice(),
    # coverage() and drift() call into ContextMapError.
    skipped_sources: dict[str, str] = {}
    for relative in (".agentlas/context-map.json", ".agentlas/sitemap.json"):
        path = root / relative
        if not path.exists():
            continue
        try:
            payload = _regular_json(path)
        except ContextMapError as exc:
            skipped_sources[relative] = str(getattr(exc, "code", exc))
            continue
        raw_nodes = payload.get("nodes")
        raw_edges = payload.get("edges") or payload.get("relationships")
        if raw_nodes is not None and not isinstance(raw_nodes, list):
            skipped_sources[relative] = "nodes_not_a_list"
            continue
        if raw_edges is not None and not isinstance(raw_edges, list):
            skipped_sources[relative] = "edges_not_a_list"
            continue
        packed_edge_count = 0
        packed_edge_iter: Iterable[Mapping[str, Any]] = ()
        if relative.endswith("sitemap.json") and isinstance(payload.get("edgesPacked"), Mapping):
            # v2 sitemaps keep machine-generated edges in a packed column store
            # (see project_bootstrap._pack_sitemap_edges); decode lazily and
            # let the same per-node cap below bound what is kept.
            total, combined = unpack_sitemap_edges(payload)
            plain_count = len(raw_edges) if isinstance(raw_edges, list) else 0
            packed_edge_count = total - plain_count
            packed_edge_iter = (edge for index, edge in enumerate(combined) if index >= plain_count)
        loaded_sources.append(relative)
        if isinstance(raw_nodes, list):
            source_nodes += len(raw_nodes)
            for candidate in raw_nodes:
                if not isinstance(candidate, dict):
                    continue  # skip the row, keep the file
                kind = _node_type(candidate)
                if relative.endswith("sitemap.json") and kind in {"file", "directory"}:
                    continue
                if not _node_id(candidate):
                    continue
                if include_inactive or _node_status(candidate) in _ACTIVE_STATES:
                    nodes.append(dict(candidate))
        if isinstance(raw_edges, list) or packed_edge_count:
            source_edges += (len(raw_edges) if isinstance(raw_edges, list) else 0) + packed_edge_count
            per_node: dict[str, int] = {}
            candidates: Iterable[Any] = raw_edges if isinstance(raw_edges, list) else ()
            for candidate in itertools.chain(candidates, packed_edge_iter):
                if not isinstance(candidate, dict):
                    continue
                source, target, _ = _edge_parts(candidate)
                if not source or not target:
                    continue
                if (
                    per_node.get(source, 0) >= MAX_EDGES_PER_NODE
                    or per_node.get(target, 0) >= MAX_EDGES_PER_NODE
                ):
                    continue
                per_node[source] = per_node.get(source, 0) + 1
                per_node[target] = per_node.get(target, 0) + 1
                edges.append(dict(candidate))
    # Truncation happens AFTER selection, not here. Cutting the list before the
    # task is known meant a relevant edge sitting past the cap could never be
    # reached: measured on a workspace with 683,729 declared edges, exactly one
    # survived into the slice. `_select_declared_context` applies the real
    # budgets to what the task actually selected.
    report = {
        "sources": loaded_sources,
        "skippedSources": skipped_sources,
        "sourceNodeCount": source_nodes,
        "sourceEdgeCount": source_edges,
        "eligibleNodeCount": len(nodes),
        "eligibleEdgeCount": len(edges),
        "loadedNodeCount": len(nodes),
        "loadedEdgeCount": len(edges),
        "omittedNodeCount": 0,
        "omittedEdgeCount": 0,
    }
    report["partial"] = False
    return nodes, edges, report


def _edge_parts(edge: Mapping[str, Any]) -> tuple[str, str, str]:
    source = str(edge.get("from") or edge.get("source") or edge.get("fromId") or "")
    target = str(edge.get("to") or edge.get("target") or edge.get("toId") or "")
    relation = str(edge.get("type") or edge.get("relation") or edge.get("kind") or "depends_on")
    return source, target, relation


# Authority tiers, from the PRD. A reader must be able to tell an observed fact
# from a declared intent from a co-edit correlation, or the tiers are decoration.
#   A0 observed             AST / filesystem / contact ledger
#   A1 declared             a human or generator wrote it in sitemap/context-map
#   A2 structurally-derived path or unique-symbol match
#   A3 semantically-derived lexical / substring
_AUTHORITY_BY_SOURCE = {"contact-ledger": "A0", "code-map": "A0", "sitemap": "A1", "context-map": "A1"}


def _with_authority(edge: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Return the edge with `authority` and `origin` attached, never mutating input.

    Origin comes from the endpoint nodes' declared source when the edge itself
    does not say. A human-written edge (no `origin=derived` on its endpoints) is
    A1-declared; a generator-derived one is still A1 but flagged so a reader
    can weigh it. Nothing here is inferred — an edge with no known origin says so.
    """

    if "authority" in edge:
        return dict(edge)
    source, target, _ = _edge_parts(edge)
    endpoints = [by_id.get(source), by_id.get(target)]
    derived = any(isinstance(n, Mapping) and n.get("origin") == "derived" for n in endpoints)
    known = any(isinstance(n, Mapping) for n in endpoints)
    out = dict(edge)
    out["authority"] = "A1" if known else "unknown"
    out["origin"] = "derived" if derived else ("declared" if known else "unknown")
    return out


def _select_declared_context(
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
    *,
    terms: Sequence[str],
    selected_files: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    by_id = {_node_id(node): node for node in nodes if _node_id(node)}
    # Two kinds of inherited context, and they must not share a rank.
    #
    #   * What the project IS — project/goal/requirement/constraint. Always few,
    #     always worth carrying, and they seed traversal so a task that matches
    #     nothing still reaches the graph.
    #   * What the project HAS LEARNED — decision/fact/procedure/assumption.
    #     These grow without bound; a project with 3,000 assumptions filled the
    #     whole node budget before one task-matched node was considered.
    #
    # The first group seeds. The second waits for leftover budget.
    inherited: set[str] = set()
    selected: set[str] = set()
    for node_id, node in by_id.items():
        if (
            _node_type(node) in _INHERITED_NODE_TYPES
            and _node_status(node) in {"active", "validated", "tentative", ""}
        ):
            if _node_type(node) in _DEFINING_NODE_TYPES:
                selected.add(node_id)
            else:
                inherited.add(node_id)
    needles = set(terms)
    needles.update(part.lower() for path in selected_files for part in Path(path).parts)
    for node_id, node in by_id.items():
        searchable = " ".join(
            str(node.get(field) or "")
            for field in ("id", "title", "name", "description", "path", "scope")
        ).lower()
        if any(term in searchable for term in needles):
            selected.add(node_id)

    # Adjacency index instead of rescanning every edge per hop. A single hub
    # node must not be able to dominate the slice, so each node contributes a
    # bounded number of edges (measured: one `invoked_by` hub held 672,357).
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source, target, _relation = _edge_parts(edge)
        if not source or not target:
            continue
        for endpoint in (source, target):
            bucket = adjacency.setdefault(endpoint, [])
            if len(bucket) < MAX_EDGES_PER_NODE:
                bucket.append(edge)

    # Breadth-first closure that remembers distance, because distance is the
    # relevance signal used below. The previous code selected by node id order,
    # so a task-relevant node could be pushed past the budget by an unrelated
    # one that merely sorted earlier.
    distance: dict[str, int] = {node_id: 0 for node_id in selected}
    frontier = set(distance)
    selected_edges: list[dict[str, Any]] = []
    selected_edge_keys: set[tuple[str, str, str]] = set()
    for hop in (1, 2):
        next_frontier: set[str] = set()
        for node_id in sorted(frontier):
            for edge in adjacency.get(node_id, ()):
                source, target, relation = _edge_parts(edge)
                edge_key = (source, target, relation)
                if edge_key not in selected_edge_keys:
                    selected_edge_keys.add(edge_key)
                    selected_edges.append(edge)
                for endpoint in (source, target):
                    if endpoint in by_id and endpoint not in distance:
                        distance[endpoint] = hop
                        next_frontier.add(endpoint)
        frontier = next_frontier
        if not frontier:
            break

    # Inherited project context sits below anything the task reached, so it
    # fills leftover budget instead of consuming it first.
    for node_id in inherited:
        distance.setdefault(node_id, _INHERITED_TIER)

    # Rank by closeness to the task, then by how much the node type carries
    # (a goal outranks an assumption), then by id for determinism.
    ordered_ids = sorted(
        distance,
        key=lambda node_id: (
            distance[node_id],
            _NODE_TYPE_RANK.get(_node_type(by_id[node_id]), _DEFAULT_TYPE_RANK)
            if node_id in by_id else _DEFAULT_TYPE_RANK,
            node_id,
        ),
    )
    eligible_nodes = [by_id[node_id] for node_id in ordered_ids if node_id in by_id]
    eligible_edge_count = len(selected_edges)
    selected_nodes = eligible_nodes[:MAX_CONTEXT_NODES]
    allowed_ids = {_node_id(node) for node in selected_nodes}
    selected_edges = [
        _with_authority(edge, by_id)
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


CONTACT_LEDGER_RELATIVE = ".agentlas/contact-ledger.jsonl"
MAX_LEDGER_BYTES = 32 * 1024 * 1024
MAX_CO_EDITED_FILES = 8
# One work unit that touches half the repo says nothing about any single pair.
MAX_SESSION_FILES = 24
# A "work unit" is a session AND a time window, not a session alone. Two things
# broke the session-only model on measurement: hosts that send no session_id
# hashed to one shared key (every edit in the project became one unit), and a
# day-long IDE session exceeded MAX_SESSION_FILES so its whole day was dropped.
CO_EDIT_WINDOW_SECONDS = 30 * 60


def _ledger_epoch(record: Mapping[str, Any]) -> int:
    raw = str(record.get("at") or "")
    try:
        return int(datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return 0


MAX_LAYOUT_DIRECTORIES = 14
MAX_LAYOUT_NAMES_PER_DIRECTORY = 14


def _project_layout(code_map: Mapping[str, Any]) -> list[str]:
    """Where things live, by directory, most load-bearing first.

    A request usually names a domain, not an identifier: "무역 로직 고쳐줘",
    "이 페이지 디자인 바꿔줘". Neither opens a symbol door, and no amount of
    string or vector matching over one-to-three word identifiers closes that
    gap — both were measured and reverted. But the answer is already written in
    the tree: this project keeps combat.js, economy.js, contracts.js and
    save-manager.js side by side, and any reader who sees those names knows
    which one "무역" means. The map simply never showed them.

    So the slice states the shape of the project and lets the agent choose.
    Directories are ranked by how much of the codebase depends on what they
    define, so the load-bearing ones survive the budget. Measured on a 629-file
    game project: 11 code directories in 1,007 characters.
    """

    files = [value for value in code_map.get("mappedFiles") or [] if isinstance(value, str)]
    if not files:
        return []
    reference_count = code_map.get("refCount") if isinstance(code_map.get("refCount"), Mapping) else {}
    definitions = code_map.get("defIndex") if isinstance(code_map.get("defIndex"), Mapping) else {}
    weight: Counter[str] = Counter()
    for symbol, sites in definitions.items():
        incoming = int(reference_count.get(symbol) or 0)
        if not incoming:
            continue
        for site in sites or []:
            if isinstance(site, Mapping) and site.get("f"):
                weight[str(Path(str(site["f"])).parent)] += incoming
    grouped: dict[str, set[str]] = {}
    for relative in files:
        path = Path(relative)
        if path.suffix.lower() not in CODE_EXTENSIONS:
            continue
        grouped.setdefault(str(path.parent), set()).add(path.stem)
    if not grouped:
        return []
    ordered = sorted(
        grouped.items(),
        key=lambda row: (-weight.get(row[0], 0), -len(row[1]), row[0]),
    )[:MAX_LAYOUT_DIRECTORIES]
    lines: list[str] = []
    for directory, names in ordered:
        listed = sorted(names)
        shown = listed[:MAX_LAYOUT_NAMES_PER_DIRECTORY]
        suffix = f" +{len(listed) - len(shown)}" if len(listed) > len(shown) else ""
        lines.append(f"{directory}/ ({len(listed)}): " + ", ".join(shown) + suffix)
    return lines


def _recently_touched_files(root: Path, limit: int) -> list[str]:
    """Files this project actually worked on, most recent session first.

    The slice had exactly two doors into the graph and both were textual: a
    path written in the task, or a symbol name written in the task. A question
    that describes rather than names — which every non-English question does by
    construction — opened neither, and the fallback offered the project's
    conventional entry points. Measured on a real game project, asking "전투
    계산 로직 어디 있어" returned sim/package.json: a correct answer to a
    question nobody asked.

    This is the third door, and it needs no language at all. The contact ledger
    records which files the tools actually edited; those files are where the
    work is, and once the traversal has them the dependency, co-edit and
    verification graphs expand from there exactly as they do for a named
    symbol. Observed events only — no parsing, no model.
    """

    path = root / CONTACT_LEDGER_RELATIVE
    try:
        if not path.is_file() or path.is_symlink():
            return []
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    ranked: dict[str, int] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, Mapping):
            continue
        epoch = _ledger_epoch(record)
        for value in record.get("paths") or []:
            if not isinstance(value, str):
                continue
            normalized = _normalize_file(root, value)
            if normalized and epoch >= ranked.get(normalized, -1):
                ranked[normalized] = epoch
    return [
        name
        for name, _epoch in sorted(ranked.items(), key=lambda row: (-row[1], row[0]))
    ][:limit]


def _co_edited_files(root: Path, selected: Sequence[str]) -> list[dict[str, Any]]:
    """Files historically edited alongside `selected`, ranked by how often.

    This is the one relation the static map cannot derive. Copies of the same
    file across plugin mirrors import nothing from each other, so the dependency
    graph rates them unrelated — yet changing one without the others is the most
    repeated defect in this repo. Measured over 489 commits: 95.4% of frequently
    co-edited code pairs had no AST edge, and co-edit history predicted the next
    change 94.5% of the time against 13.4% for the dependency graph.

    Observed history only: no inference, no model. Returns `[]` when the ledger
    is absent, which is the normal state of a project on its first day.
    """

    if not selected:
        return []
    path = root / CONTACT_LEDGER_RELATIVE
    try:
        if not path.is_file():
            return []
        size = path.stat().st_size
        if size <= MAX_LEDGER_BYTES:
            raw = path.read_text(encoding="utf-8")
        else:
            # Append-only and chronological, so the tail is the recent history —
            # the part that predicts the next edit. Reading only the tail keeps
            # a years-old ledger from silently disabling co-edit forever
            # (measured: a 115 MB ledger returned [] with no explanation).
            with path.open("rb") as handle:
                handle.seek(size - MAX_LEDGER_BYTES)
                chunk = handle.read()
            # Drop the first partial line.
            newline = chunk.find(b"\n")
            raw = chunk[newline + 1:].decode("utf-8", errors="replace") if newline >= 0 else ""
    except OSError:
        return []

    # Group by (session, time-window). Records are appended chronologically, so
    # a window closes when the gap to the previous record exceeds the threshold.
    units: dict[tuple[str, int], set[str]] = {}
    last_seen: dict[str, tuple[int, int]] = {}   # session -> (window_id, last_epoch)
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        session = str(record.get("session") or "")
        paths = record.get("paths")
        # Intent lines share the file (Phase A.2) but carry no paths.
        if not session or not isinstance(paths, list):
            continue
        epoch = _ledger_epoch(record)
        window_id, last_epoch = last_seen.get(session, (0, epoch))
        if epoch - last_epoch > CO_EDIT_WINDOW_SECONDS:
            window_id += 1
        last_seen[session] = (window_id, epoch)
        bucket = units.setdefault((session, window_id), set())
        for value in paths:
            if isinstance(value, str) and value:
                bucket.add(value)

    wanted = set(selected)
    counts: Counter[str] = Counter()
    for files in units.values():
        if not (files & wanted):
            continue
        # A wide work unit says less about any single pair than a narrow one,
        # but dropping it outright discarded whole days of real signal (measured:
        # 30 files over 3 hours in one IDE session → 0 co-edit results). Weight
        # by breadth instead: a 2-file unit counts 1.0, a 40-file unit ~0.6.
        weight = 1.0 if len(files) <= MAX_SESSION_FILES else MAX_SESSION_FILES / len(files)
        for other in files - wanted:
            counts[other] += weight
    # A path that no longer exists is history, not guidance. Ledger lines are
    # never rewritten, so the filter has to happen at read time.
    return [
        {"file": name, "sessions": round(hits, 2), "authority": "A0", "relation": "co_edited"}
        for name, hits in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if (root / name).exists()
    ][:MAX_CO_EDITED_FILES]


def _module_of(path: str) -> str:
    parts = Path(path).parts
    return parts[0] if len(parts) > 1 else "."


# Shorter tokens ("api", "db", "id") match hundreds of unrelated definitions.
_MIN_FALLBACK_TERM = 4
# A short term is admitted when it selects at most this many symbols, or at
# most 1/N of the whole index — whichever is larger. Selectivity, not length.
_SHORT_TERM_MAX_HITS = 24
_SHORT_TERM_SELECTIVITY = 40


def _fallback_symbols(
    definitions: Mapping[str, Any],
    ref_count: Mapping[str, Any],
    fallback_terms: Sequence[str],
) -> list[str]:
    """Find symbols by substring when no exact name was typed.

    ``defIndex`` is keyed by exact symbol name, so prose like "runtime adapter
    버그 고치기" matched nothing even though ``runtime_adapters`` was indexed.
    Ranked by existing refCount — no embedding, no new index.
    """

    # Non-ASCII terms (Korean etc.) never match code symbols; only ASCII terms
    # participate here. Short ASCII terms are admitted when they are selective:
    # "api" hitting 9 of 1,578 symbols is a real query, "get" hitting 400 is
    # noise. Length was the wrong proxy — it discarded "api", "db", "ui".
    ascii_terms = [term for term in fallback_terms if term.isascii()]
    long_terms = [term for term in ascii_terms if len(term) >= _MIN_FALLBACK_TERM]
    short_terms = [term for term in ascii_terms if 0 < len(term) < _MIN_FALLBACK_TERM]
    needles = list(long_terms)
    if short_terms:
        total = max(1, len(definitions))
        for term in short_terms:
            matched = sum(1 for key in definitions if term in key)
            if 0 < matched <= max(_SHORT_TERM_MAX_HITS, total // _SHORT_TERM_SELECTIVITY):
                needles.append(term)
    if not needles:
        return []
    hits = [key for key in definitions if any(needle in key for needle in needles)]
    hits.sort(key=lambda key: (-int(ref_count.get(key) or 0), key))
    return hits


def _selected_symbols(
    code_map: Mapping[str, Any],
    *,
    terms: Sequence[str],
    files: Sequence[str],
    fallback_terms: Sequence[str] = (),
) -> tuple[list[str], str]:
    """Return ``(symbols, match_mode)``.

    ``match_mode`` travels with the slice so a reader can tell an exactly-named
    symbol from one recovered by substring. Silent mixing would make the weaker
    evidence indistinguishable from the stronger.
    """

    definitions = code_map.get("defIndex")
    file_symbols = code_map.get("fileSymbols")
    if not isinstance(definitions, dict):
        return [], "none"
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
    resolved = [*exact, *ranked][:MAX_SELECTED_SYMBOLS]
    if resolved:
        return resolved, ("exact" if exact else "file")
    fallback = _fallback_symbols(definitions, ref_count, fallback_terms)
    if fallback:
        return fallback[:MAX_SELECTED_SYMBOLS], "substring"
    return [], "none"


def context_slice(
    project: str | Path,
    task: str,
    *,
    targets: Sequence[str] = (),
    refresh: bool = True,
    allow_stale: bool = False,
    freshness_budget_seconds: float | None = None,
) -> dict[str, Any]:
    root, code_map, refresh_receipt = load_code_map(
        project,
        refresh=refresh,
        allow_stale=allow_stale,
        freshness_budget_seconds=freshness_budget_seconds,
    )
    terms = _query_terms(task)
    selected_files = _task_path_hints(root, task, targets)
    # `selected_files` is reassigned below to the dependency-expanded set. Co-edit
    # history must anchor on what the task actually named, not on the expansion,
    # or every co-edit partner is already inside the set and nothing is reported.
    task_named_files = list(selected_files)
    symbols, symbol_match = _selected_symbols(
        code_map,
        terms=_symbol_terms(task, code_map),
        files=selected_files,
        fallback_terms=terms,
    )
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
    # A task phrased in a language the symbol table cannot contain (Korean over
    # an English codebase — three of four measured projects) matched nothing.
    # The library must still open a door: the project's conventional entry
    # points are what any newcomer reads first, and the map already knows them.
    file_match = "matched"
    if not selected_files:
        # Third door: what this project was actually being worked on. Tried
        # before the conventional entry points, because "where the work is"
        # beats "where a newcomer starts reading" for every task that is not
        # the first one.
        recent = _recently_touched_files(root, 12)
        if recent:
            selected_files = _bounded_strings(recent, MAX_SELECTED_FILES)
            file_match = "recent_work"
    if not selected_files:
        entry_points = [
            str(item.get("path") or "")
            for item in (code_map.get("entryPoints") or [])
            if isinstance(item, dict) and item.get("path")
        ]
        if entry_points:
            selected_files = _bounded_strings(entry_points, MAX_SELECTED_FILES)
            file_match = "entry_points"
        else:
            # No conventional entry point either (library, script bundle). The
            # most-referenced definition sites are the next best door: they are
            # what the rest of the code depends on.
            ref_count = code_map.get("refCount") if isinstance(code_map.get("refCount"), dict) else {}
            definitions = code_map.get("defIndex") if isinstance(code_map.get("defIndex"), dict) else {}
            hub_files: list[str] = []
            for key, _count in sorted(ref_count.items(), key=lambda kv: (-int(kv[1] or 0), kv[0])):
                for site in definitions.get(key) or []:
                    if isinstance(site, dict) and site.get("f"):
                        hub_files.append(str(site["f"]))
                if len(set(hub_files)) >= 8:
                    break
            if hub_files:
                selected_files = _bounded_strings(hub_files, 8)
                file_match = "most_referenced"
    # Expansion used to run through symbols only: a file-seeded slice (a task
    # that named a path, or the recent-work door below) stopped at its seed
    # while `impact` on the very same file reached its dependents. Measured on
    # a real game project: seed sim/web/app.js -> slice showed 1 file, impact
    # showed sim/harness/web-runtime.mjs as well. Whatever door was used, the
    # graph is the point — walk one dependency hop from every seeded file.
    if selected_files:
        seeds = set(selected_files)
        neighbours: list[str] = []
        for edge in code_map.get("dependencyEdges") or []:
            if not isinstance(edge, Mapping):
                continue
            source = str(edge.get("from") or "")
            target = str(edge.get("to") or "")
            if source in seeds and target:
                neighbours.append(target)
            elif target in seeds and source:
                neighbours.append(source)
        file_symbols_index = code_map.get("fileSymbols")
        if isinstance(file_symbols_index, Mapping):
            for name in list(seeds):
                for item in file_symbols_index.get(name) or []:
                    if not isinstance(item, Mapping):
                        continue
                    key = str(item.get("n") or "").lower()
                    for value in (references.get(key) or []) if isinstance(references, Mapping) else []:
                        if isinstance(value, str):
                            neighbours.append(value)
        if neighbours:
            selected_files = _bounded_strings([*selected_files, *neighbours], MAX_SELECTED_FILES)
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
        "symbolMatch": symbol_match,
        # "matched" = task named or reached these files; "entry_points" = nothing
        # matched and these are the project's conventional starting files.
        "fileMatch": file_match,
        # Exact/file matches are structural (A2); substring recovery is lexical
        # (A3) and a reader should weigh it accordingly.
        "symbolAuthority": {"exact": "A2", "file": "A2", "substring": "A3"}.get(symbol_match, "unknown"),
        # Observed co-edit history. Carries the relations the dependency graph
        # structurally cannot see (mirrored copies, code↔install script, …).
        "projectLayout": _project_layout(code_map),
        "coEditedFiles": _co_edited_files(root, task_named_files),
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
    allow_stale: bool = False,
    freshness_budget_seconds: float | None = None,
) -> dict[str, Any]:
    root, code_map, refresh_receipt = load_code_map(
        project,
        refresh=refresh,
        allow_stale=allow_stale,
        freshness_budget_seconds=freshness_budget_seconds,
    )
    terms = _query_terms(query)
    definitions = code_map.get("defIndex", {})
    references = code_map.get("refIndex", {})
    matches: list[dict[str, Any]] = []
    # An agent asking this tool has already read the request and decided what to
    # look for; the answer it needs is a place, and a place is as often a file
    # as a function. Symbols-only made the tool useless for exactly the terms an
    # agent derives from a domain request — measured on a game project, the
    # queries "economy", "contracts" and "goods" each returned 0 matches while
    # sim/src/economy.js, contracts.js and goods.js sat in the map. Files are
    # matched on their stem so a caller need not know the extension or path.
    files = [value for value in code_map.get("mappedFiles") or [] if isinstance(value, str)]
    lowered_terms = [term for term in terms if term]
    file_hits: list[dict[str, Any]] = []
    for relative in files:
        stem = Path(relative).stem.lower()
        if any(term == stem or term in stem for term in lowered_terms):
            file_hits.append({"file": relative, "stem": Path(relative).stem})
        if len(file_hits) >= MAX_SELECTED_FILES:
            break
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
        "files": file_hits,
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


COVERAGE_SCHEMA = "agentlas.context-coverage.v1"
DRIFT_SCHEMA = "agentlas.context-drift.v1"
MAX_FINDINGS_PER_KIND = 25
# Relations that count as "this declared thing is realized somewhere".
_REALIZATION_RELATIONS = frozenset({
    "realized_by", "implemented_by", "satisfied_by", "contributes_to",
    "depends_on", "contains", "produces", "exposed_by", "configured_by",
})
_VERIFICATION_RELATIONS = frozenset({
    "verified_by", "tested_by", "checked_by", "benchmarked_by",
    "verifies", "verified_by_import", "verified_by_command",
})
_DEAD_STATES = frozenset({"deprecated", "superseded", "retired", "removed", "rejected"})


def _node_scan_path(node: Mapping[str, Any]) -> str:
    """Best project-relative path this declared node stands for, if any."""

    path = str(node.get("path") or "").strip()
    if path:
        # lstrip("./") strips a character set, which would turn ".playwright-cli"
        # into "playwright-cli" and break every dotfile-rooted comparison.
        normalized = path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized or path
    node_id = str(node.get("id") or "")
    for prefix in ("surface:module:", "code:file:", "file:", "module:"):
        if node_id.startswith(prefix):
            return node_id[len(prefix):]
    return ""


def _excluded_by_policy(node: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    """True when the current scan policy would not index this node's path.

    The sitemap is merge-only, so nodes created before an `excludeRoots` entry
    was added survive indefinitely. Diagnostics must answer for the project as
    it is configured now, or they report backup folders and worktrees as
    untested features — noise that gets the whole check switched off.
    """

    path = _node_scan_path(node)
    if not path or path == ".":
        return False
    return not _policy_allows(path, policy)


def _declared_degree(edges: Sequence[Mapping[str, Any]]) -> tuple[Counter[str], Counter[str]]:
    """Outgoing counts split by what the relation means, not just that it exists."""

    realization: Counter[str] = Counter()
    verification: Counter[str] = Counter()
    for edge in edges:
        source, target, relation = _edge_parts(edge)
        if not source or not target:
            continue
        if relation in _VERIFICATION_RELATIONS:
            verification[source] += 1
            verification[target] += 1
        elif relation in _REALIZATION_RELATIONS:
            realization[source] += 1
    return realization, verification


def coverage(project: str | Path, *, refresh: bool = True) -> dict[str, Any]:
    """What the project declared but never carried through.

    Open-world by construction: an empty declared layer means "not known", not
    "nothing is missing". Reporting absence as a finding would fill a fresh
    project's first run with thousands of false alarms and get the whole
    diagnostic switched off, which is the failure mode this guards against.
    """

    root, code_map, _receipt = load_code_map(project, refresh=refresh)
    nodes, edges, load_report = _load_declared_graph(root)
    policy = _context_index_policy(root)
    by_id = {
        _node_id(node): node
        for node in nodes
        if _node_id(node) and not _excluded_by_policy(node, policy)
    }

    if not by_id:
        return {
            "schemaVersion": COVERAGE_SCHEMA,
            "status": "unknown",
            "reason": "no_declared_nodes",
            "detail": "선언 층이 비어 있어 판정할 수 없다. 없음이 아니라 모름이다.",
            "findings": {},
            "declared": load_report,
        }

    realization, verification = _declared_degree(edges)
    findings: dict[str, list[dict[str, Any]]] = {}

    unrealized = [
        {"id": node_id, "title": str(node.get("title") or node.get("name") or "")[:120],
         "type": _node_type(node)}
        for node_id, node in sorted(by_id.items())
        if _node_type(node) in {"requirement", "goal", "subgoal"}
        and _node_status(node) not in _DEAD_STATES
        and realization[node_id] == 0
    ]
    if edges:
        findings["unrealizedRequirements"] = unrealized[:MAX_FINDINGS_PER_KIND]

    untested = [
        {"id": node_id, "title": str(node.get("title") or node.get("name") or "")[:120],
         "type": _node_type(node)}
        for node_id, node in sorted(by_id.items())
        if _node_type(node) in {"surface", "feature", "workflow", "capability"}
        and _node_status(node) not in _DEAD_STATES
        and verification[node_id] == 0
    ]
    verification_graph = code_map.get("verificationGraph")
    if isinstance(verification_graph, dict) and verification_graph.get("edges"):
        findings["untestedFeatures"] = untested[:MAX_FINDINGS_PER_KIND]

    counted = {kind: len(values) for kind, values in findings.items()}
    return {
        "schemaVersion": COVERAGE_SCHEMA,
        "status": "partial" if load_report.get("partial") else "complete",
        "findings": findings,
        "counts": counted,
        "declared": load_report,
        # Which checks could not run, and why. Never silently reported as clean.
        "skipped": {
            **({} if edges else {"unrealizedRequirements": "no_declared_edges"}),
            **({} if isinstance(verification_graph, dict) and verification_graph.get("edges")
               else {"untestedFeatures": "no_verification_graph"}),
        },
    }


def drift(project: str | Path, *, refresh: bool = True) -> dict[str, Any]:
    """Where the declared project and the real one disagree.

    Only reports disagreements it can point at with both sides present: a node
    marked dead whose implementation is still indexed and still referenced. A
    guess here costs more than a miss, because a diagnostic that cries wolf is
    turned off and then catches nothing at all.
    """

    root, code_map, _receipt = load_code_map(project, refresh=refresh)
    # Dead nodes are the subject of this check, so they must survive the load.
    nodes, edges, load_report = _load_declared_graph(root, include_inactive=True)
    policy = _context_index_policy(root)
    by_id = {
        _node_id(node): node
        for node in nodes
        if _node_id(node) and not _excluded_by_policy(node, policy)
    }

    if not by_id:
        return {
            "schemaVersion": DRIFT_SCHEMA,
            "status": "unknown",
            "reason": "no_declared_nodes",
            "findings": {},
            "declared": load_report,
        }

    indexed = {
        str(value)
        for value in code_map.get("mappedFiles", code_map.get("indexedFiles", []))
        if isinstance(value, str)
    }
    reference_index = code_map.get("refIndex") if isinstance(code_map.get("refIndex"), dict) else {}
    referenced_files: set[str] = set()
    for files in reference_index.values():
        if isinstance(files, list):
            referenced_files.update(str(item) for item in files if isinstance(item, str))

    dead_but_live: list[dict[str, Any]] = []
    for node_id, node in sorted(by_id.items()):
        if _node_status(node) not in _DEAD_STATES:
            continue
        path = str(node.get("path") or "")
        if not path or path not in indexed:
            continue
        dead_but_live.append({
            "id": node_id,
            "status": _node_status(node),
            "path": path,
            "stillReferenced": path in referenced_files,
            "title": str(node.get("title") or node.get("name") or "")[:120],
        })

    findings = {"deadButImplemented": dead_but_live[:MAX_FINDINGS_PER_KIND]}
    return {
        "schemaVersion": DRIFT_SCHEMA,
        "status": "partial" if load_report.get("partial") else "complete",
        "findings": findings,
        "counts": {kind: len(values) for kind, values in findings.items()},
        "declared": load_report,
        "skipped": {} if indexed else {"deadButImplemented": "no_indexed_files"},
    }


def impact(
    project: str | Path,
    changed: Sequence[str],
    *,
    refresh: bool = True,
    allow_stale: bool = False,
    freshness_budget_seconds: float | None = None,
) -> dict[str, Any]:
    root, code_map, refresh_receipt = load_code_map(
        project,
        refresh=refresh,
        allow_stale=allow_stale,
        freshness_budget_seconds=freshness_budget_seconds,
    )
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
    # An advisory edge is a name-based match ("context_map.py" <-> the test
    # called test_context_map.py) rather than a proven import or command. It was
    # dropped outright, and on this repository that meant dropping the answer:
    # 1,497 of the code->test links are advisory against 403 proven imports, so
    # asking "what breaks if I change context_map.py" returned an empty list
    # while the graph plainly held `context_map.py --advisory_by_name-->
    # test:tests/test_context_map.py`. Advisory targets are now reported with
    # their confidence attached instead of silently discarded — a labelled
    # maybe is what the reader can act on; an empty list reads as "nothing to
    # check". They still do NOT extend the frontier: a guess must not propagate
    # into further hops and inflate the blast radius.
    for _ in range(4):
        next_frontier: set[str] = set()
        for edge in verification_edges:
            source = str(edge.get("from") or "")
            target = str(edge.get("to") or "")
            relation = str(edge.get("relation") or "verifies")
            if source not in frontier or not target or relation == "released_by":
                continue
            advisory = relation.startswith("advisory_")
            node = verification_nodes.get(target)
            if node and node["path"]:
                target_key = (node["id"], node["kind"], relation)
                verification_targets[target_key] = {
                    "id": node["id"],
                    "path": node["path"],
                    "kind": node["kind"],
                    "relation": relation,
                    "confidence": "advisory" if advisory else "exact",
                    "from": source,
                }
            if advisory:
                continue
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
                "confidence": "exact",
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


def _rendered_edge_endpoints(value: Mapping[str, Any]) -> set[str]:
    """Node ids that a rendered edge line already names."""

    edges = value.get("contextEdges")
    if not isinstance(edges, list):
        return set()
    endpoints: set[str] = set()
    for edge in edges[:MAX_RENDERED_CONTEXT_EDGES]:
        if not isinstance(edge, Mapping):
            continue
        source, target, _relation = _edge_parts(edge)
        if source and target:
            endpoints.add(source)
            endpoints.add(target)
    return endpoints


def render_context_slice(value: Mapping[str, Any], *, max_chars: int = MAX_RENDER_CHARS) -> str:
    """Compact prompt representation; source paths only, never source contents."""

    lines = [
        "## Agentlas Context Slice (dependency-selected, project-local)",
        f"Receipt: {value.get('receipt', {}).get('receiptDigest', 'missing')}",
    ]
    # A stale map is still served (see load_code_map allow_stale), but the
    # reader must know the index predates recent edits.
    refresh_status = str((value.get("receipt") or {}).get("refreshStatus") or "")
    if refresh_status == "stale_served":
        lines.append("Note: map predates recent edits (served stale rather than empty); re-verify paths before acting.")
    elif refresh_status == "unverified_served":
        lines.append("Note: map freshness was not verified within the recall budget; it may predate recent edits — re-verify paths before acting.")
    # Order is a budget decision, not a style one. The capsule layer gives this
    # slice ~1,200 chars; measured on a real "fix context_slice" turn the
    # sections cost: edges 852, goals 1,036, definitions 737, related files 649.
    # Background-first spent the whole budget before saying WHERE anything is,
    # so three different coding questions produced byte-identical slices with
    # zero file paths — the map knew `context_slice` was at context_map.py:1012
    # and had 13 backlinks, and the reader never saw it. What the agent needs to
    # start working (where the symbol lives, what calls it, what moves with it)
    # goes first; the project's standing goals and their edges follow and take
    # what is left. Both still render in full when no budget is applied.
    symbols = value.get("symbols")
    if isinstance(symbols, list) and symbols:
        # Say how these were found. An exact match and a substring guess must not
        # read the same to the agent that acts on them.
        match_mode = str(value.get("symbolMatch") or "")
        authority = str(value.get("symbolAuthority") or "")
        suffix = f" ({match_mode} match, authority {authority})" if match_mode and authority else ""
        lines.append(f"Definitions and backlinks{suffix}:")
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
        file_match = str(value.get("fileMatch") or "matched")
        heading = {
            "entry_points": "Nothing in the task matched the symbol table; conventional entry points:",
            "most_referenced": "Nothing matched; the most-referenced definition sites:",
        }.get(file_match, "Structurally related files:")
        lines.append(heading)
        lines.extend(f"- {path}" for path in files[:40])
    co_edited = value.get("coEditedFiles")
    if isinstance(co_edited, list) and co_edited:
        # Observed history, not inference: files repeatedly changed together
        # with the ones the task named. This is the relation the dependency
        # graph structurally cannot see (mirrors, code↔install script).
        lines.append("Historically edited together with the named files (observed, authority A0):")
        for item in co_edited[:8]:
            if isinstance(item, Mapping) and item.get("file"):
                lines.append(f"- {item['file']} ({item.get('sessions', '?')} work units)")
    layout = value.get("projectLayout")
    if isinstance(layout, list) and layout:
        lines.append("Where things live (directories by how much depends on them):")
        lines.extend(f"- {item}" for item in layout)
    # An edge line names both of its endpoints, so a node that appears in one is
    # already stated — listing it again as a bare bullet spends the capsule
    # budget twice on the same fact. Measured: at the 1,200-char context_slice
    # layer budget the bullet list consumed everything and zero edges survived,
    # which is how a 680,119-edge graph reached the model as a flat list. Edges
    # are rendered first and their endpoints are dropped from the list below.
    edge_endpoint_ids = _rendered_edge_endpoints(value)
    # The selection stage walks two hops out from the task and returns both the
    # nodes it reached and the edges it walked — and until now the renderer
    # printed neither, so the whole traversal ended in a field nobody read.
    # Measured on the pilot: 680,119 declared edges in the sitemap, 32,048
    # loaded, up to 128 selected for a task, and 0 rendered. The edges are the
    # only part that says HOW two pieces of context relate; goals alone read as
    # an unordered list. Kept compact and placed after the defining nodes, so a
    # tight capsule budget still spends its first characters on what the
    # project IS.
    related = value.get("relatedContextNodes")
    context_edges = value.get("contextEdges")
    if isinstance(context_edges, list) and context_edges:
        by_id = {
            _node_id(node): node
            for node in (related if isinstance(related, list) else [])
            if isinstance(node, Mapping) and _node_id(node)
        }

        def _label(node_id: str) -> str:
            node = by_id.get(node_id)
            if isinstance(node, Mapping):
                title = str(node.get("title") or node.get("name") or "").strip()
                if title:
                    return title[:60]
            return node_id[:60]

        rendered_edges: list[str] = []
        for edge in context_edges[:MAX_RENDERED_CONTEXT_EDGES]:
            if not isinstance(edge, Mapping):
                continue
            source, target, relation = _edge_parts(edge)
            if not source or not target:
                continue
            # A plain `->` is HTML-escaped into `-&gt;` by the capsule builder,
            # which is what the reader would actually receive. Use the arrow
            # character so the relation stays legible in the prompt.
            rendered_edges.append(f"{_label(source)} —{relation or 'relates_to'}→ {_label(target)}")
        if rendered_edges:
            lines.append("How that context connects (observed edges, 2-hop):")
            lines.extend(f"- {item}" for item in rendered_edges)
    goals = value.get("goalsAndConstraints")
    if isinstance(goals, list) and goals:
        lines.append("Inherited goals, constraints, decisions:")
        for node in goals[:20]:
            if not isinstance(node, Mapping):
                continue
            if _node_id(node) in edge_endpoint_ids:
                continue
            label = str(node.get("title") or node.get("name") or _node_id(node))
            lines.append(f"- [{_node_type(node) or 'context'}:{_node_status(node) or 'active'}] {label[:240]}")
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
