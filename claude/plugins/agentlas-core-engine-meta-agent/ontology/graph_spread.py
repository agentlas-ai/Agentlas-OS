"""Graph spread for experience recall: Personalized PageRank over free edges.

Recall had two doors, both textual: a memory had to share words with the
question (lexical) or meaning with it (vector). A memory that shares neither —
"charge_retry.py must stay idempotent" when the question is "where do we handle
failed payments" — was unreachable even when the memory right next to it was a
direct hit. HippoRAG's answer is to spread from the direct hits over a graph;
this module does that with edges that already exist for free:

  similar_to      embedding cosine between memories (>= 0.55, 5 per node),
                  written at ingest from the scan that already runs there
  mentions_file   a memory names a file (text or source_refs)
  co_edited       files edited in the same work unit (contact ledger)
  references      file-level definition/reference edges (Context Map code map)

No model call and no new extraction: every edge is a byproduct of something the
runtime already records. ``co_edited`` is correlation, not causation, and is
typed as such (``RELATION_TYPES``) so no consumer reads it as "A causes B".

Pure-local python. Nodes are bounded by the eligible memory window plus the
files those memories name; power iteration converges in a few dozen steps.
Fail-open by construction: an empty graph yields an empty signal, and the
caller's fusion then reduces exactly to its original channels.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

# relation_type -> (default transition weight, causal?, basis). ``causal`` is
# False for every edge here on purpose: none of them is evidence that one
# memory explains another, only that they travel together.
RELATION_TYPES: dict[str, dict[str, Any]] = {
    "similar_to": {"weight": 1.0, "causal": False, "basis": "vector_cosine"},
    "mentions_file": {"weight": 1.0, "causal": False, "basis": "text_or_source_ref_path"},
    "co_edited": {"weight": 0.8, "causal": False, "basis": "contact_ledger_correlation"},
    "references": {"weight": 0.6, "causal": False, "basis": "code_map_definition_reference"},
}

# Desktop's memory_relation_edges contract (>= 0.55, 5 per node), mirrored so
# the two surfaces build the same neighborhood from the same kind of vector.
SIMILAR_EDGE_THRESHOLD = 0.55
SIMILAR_EDGE_PER_NODE = 5

DEFAULT_DAMPING = 0.85
DEFAULT_MAX_ITERATIONS = 40
DEFAULT_TOLERANCE = 1e-7

TICKET_PREFIX = "t:"
FILE_PREFIX = "f:"

CONTACT_LEDGER_RELATIVE = ".agentlas/contact-ledger.jsonl"
CODE_MAP_RELATIVE = ".agentlas/code-map/project-map.json"
# Same bounds and work-unit model as agentlas_cloud.context_map._co_edited_files
# (session x 30-minute window, breadth-weighted), so "co-edited" means the same
# thing in the Context Map slice and in memory recall.
MAX_LEDGER_BYTES = 32 * 1024 * 1024
MAX_CODE_MAP_BYTES = 64 * 1024 * 1024
MAX_SESSION_FILES = 24
CO_EDIT_WINDOW_SECONDS = 30 * 60

_PATH_EXTENSIONS = (
    "py|pyi|ts|tsx|js|jsx|cjs|mjs|json|jsonl|md|sh|sql|yaml|yml|toml|rs|go|java|kt|swift|"
    "css|scss|html|c|cc|cpp|h|hpp|rb|php|cs|vue|svelte|txt|ini|cfg"
)
_PATH_PATTERN = re.compile(
    r"(?<![\w/.\-])((?:[\w.\-]+/)*[\w\-][\w.\-]*\.(?:" + _PATH_EXTENSIONS + r"))(?::\d+)?(?![\w/])",
    re.IGNORECASE,
)
# Library names that look like files ("Node.js") are not files in this project.
_NOT_FILES = {
    "node.js", "next.js", "vue.js", "react.js", "three.js", "d3.js", "chart.js", "express.js",
    "nuxt.js", "deno.js", "ember.js", "backbone.js", "angular.js", "p5.js", "socket.io.js",
}
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{4,}")


def _normalize_path(value: str) -> str | None:
    raw = value.strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or "\x00" in raw or any(part == ".." for part in raw.split("/")):
        return None
    return raw


@lru_cache(maxsize=32_768)
def _text_file_mentions(text: str) -> frozenset[str]:
    found: set[str] = set()
    for match in _PATH_PATTERN.finditer(text or ""):
        value = match.group(1)
        if value.lower() in _NOT_FILES:
            continue
        normalized = _normalize_path(value)
        if normalized:
            found.add(normalized)
    return frozenset(found)


def extract_file_mentions(text: str, source_refs: Iterable[Any] | None = None) -> set[str]:
    """Paths a memory names, from its text and structured source refs."""

    found = set(_text_file_mentions(text or ""))
    for ref in source_refs or []:
        candidates: list[str] = []
        if isinstance(ref, str):
            candidates.append(ref)
        elif isinstance(ref, Mapping):
            for key in ("path", "file", "f", "source_path"):
                value = ref.get(key)
                if isinstance(value, str):
                    candidates.append(value)
        for value in candidates:
            value = value.split("#", 1)[0]
            value = re.sub(r":\d+(?::\d+)?$", "", value)
            if value.startswith("file://"):
                value = value[len("file://"):]
            normalized = _normalize_path(value)
            if normalized and "." in Path(normalized).name:
                found.add(normalized)
    return found


class FileResolver:
    """Map a mention ("context_map.py", "cloud/context_map.py", "/abs/root/x.py")
    onto one known path.

    Known paths come from the ledger and code map. Every path suffix that names
    exactly one known file resolves to it (O(1) per mention). An unknown or
    ambiguous mention keeps its own normalized text, so two memories naming the
    same unknown file still meet.
    """

    def __init__(self, root: Path | None, known: Iterable[str]):
        self.root = root
        self.known = set(known)
        suffixes: dict[str, str | None] = {}
        for path in self.known:
            parts = path.split("/")
            for index in range(1, len(parts)):
                suffix = "/".join(parts[index:])
                suffixes[suffix] = None if suffix in suffixes and suffixes[suffix] != path else path
        self.suffixes = {key: value for key, value in suffixes.items() if value is not None}
        self._root_text = str(root.resolve(strict=False)).rstrip("/") + "/" if root is not None else None

    def resolve(self, mention: str) -> str:
        value = mention
        if self._root_text and value.startswith(self._root_text):
            value = value[len(self._root_text):]
        if value in self.known:
            return value
        return self.suffixes.get(value, value)


# ---------------------------------------------------------------------------
# Project-level edges (contact ledger, code map), cached per file version.

_CACHE: dict[tuple[str, str], tuple[tuple[int, int], Any]] = {}


def _file_version(path: Path) -> tuple[int, int] | None:
    try:
        if not path.is_file() or path.is_symlink():
            return None
        stat = path.stat()
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _cached(kind: str, path: Path, loader) -> Any:
    version = _file_version(path)
    if version is None:
        return None
    key = (kind, str(path))
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == version:
        return hit[1]
    value = loader(path, version[1])
    _CACHE[key] = (version, value)
    return value


def _ledger_epoch(record: Mapping[str, Any]) -> int:
    try:
        return int(
            datetime.strptime(str(record.get("at") or ""), "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except ValueError:
        return 0


def _load_co_edit_units(path: Path, size: int) -> list[frozenset[str]]:
    with path.open("rb") as handle:
        if size > MAX_LEDGER_BYTES:
            handle.seek(size - MAX_LEDGER_BYTES)
            chunk = handle.read()
            newline = chunk.find(b"\n")
            chunk = chunk[newline + 1:] if newline >= 0 else b""
        else:
            chunk = handle.read()
    units: dict[tuple[str, int], set[str]] = {}
    last_seen: dict[str, tuple[int, int]] = {}
    for line in chunk.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        session = str(record.get("session") or "")
        paths = record.get("paths")
        if not session or not isinstance(paths, list):
            continue
        epoch = _ledger_epoch(record)
        window_id, last_epoch = last_seen.get(session, (0, epoch))
        if epoch - last_epoch > CO_EDIT_WINDOW_SECONDS:
            window_id += 1
        last_seen[session] = (window_id, epoch)
        bucket = units.setdefault((session, window_id), set())
        for value in paths:
            if isinstance(value, str):
                normalized = _normalize_path(value)
                if normalized:
                    bucket.add(normalized)
    return [frozenset(files) for files in units.values() if len(files) >= 2]


def co_edit_units(root: Path | None) -> list[frozenset[str]]:
    if root is None:
        return []
    try:
        return _cached("ledger", root / CONTACT_LEDGER_RELATIVE, _load_co_edit_units) or []
    except OSError:
        return []


def _load_code_map(path: Path, size: int) -> dict[str, Any]:
    if size > MAX_CODE_MAP_BYTES:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    dependencies: dict[str, set[str]] = {}
    for edge in payload.get("dependencyEdges") or []:
        if not isinstance(edge, Mapping):
            continue
        src, dst = edge.get("from"), edge.get("to")
        if isinstance(src, str) and isinstance(dst, str) and src != dst:
            dependencies.setdefault(src, set()).add(dst)
    definitions: dict[str, set[str]] = {}
    raw_defs = payload.get("defIndex") if isinstance(payload.get("defIndex"), Mapping) else {}
    raw_refs = payload.get("refIndex") if isinstance(payload.get("refIndex"), Mapping) else {}
    for symbol, sites in raw_defs.items():
        files = {
            str(site.get("f")) for site in (sites or []) if isinstance(site, Mapping) and site.get("f")
        }
        # A name defined in many places identifies none of them.
        if files and len(files) <= 3:
            definitions[str(symbol)] = files
    if not dependencies:
        # Older maps without dependencyEdges: derive file edges from def/ref.
        for symbol, refs in raw_refs.items():
            targets = definitions.get(str(symbol))
            if not targets:
                continue
            for ref in refs or []:
                if isinstance(ref, str):
                    for target in targets:
                        if ref != target:
                            dependencies.setdefault(ref, set()).add(target)
    files = set(dependencies)
    for targets in dependencies.values():
        files |= targets
    for targets in definitions.values():
        files |= targets
    return {"dependencies": dependencies, "definitions": definitions, "files": files}


def code_map_edges(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {}
    try:
        return _cached("code-map", root / CODE_MAP_RELATIVE, _load_code_map) or {}
    except OSError:
        return {}


def symbol_files(text: str, definitions: Mapping[str, set[str]]) -> set[str]:
    """Definition files for identifier-shaped names a memory mentions.

    Only names that look like code (snake_case, camelCase, dotted) count; a
    plain English word that happens to be a symbol name ("status") is noise.
    """

    if not definitions:
        return set()
    found: set[str] = set()
    for match in _IDENTIFIER_PATTERN.finditer(text or ""):
        token = match.group(0)
        if "_" not in token.strip("_") and not re.search(r"[a-z][A-Z]", token):
            continue
        files = definitions.get(token)
        if files:
            found |= files
    return found


def unit_vector(values: Iterable[float]) -> list[float] | None:
    """L2-normalized float copy, or None for empty/zero/non-finite vectors.

    Normalizing once lets the neighbor scan use a bare dot product instead of
    re-deriving both norms for every pair (the int8 store is scale-free).
    """

    floats = [float(value) for value in values]
    if not floats or not all(math.isfinite(value) for value in floats):
        return None
    norm = math.sqrt(sum(value * value for value in floats))
    if norm == 0:
        return None
    return [value / norm for value in floats]


def dot(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(map(float.__mul__, left, right))


# ---------------------------------------------------------------------------
# Graph + Personalized PageRank.


class TypedGraph:
    """Undirected weighted multigraph with per-relation-type edge accounting."""

    def __init__(self, relation_weights: Mapping[str, float] | None = None):
        self.relation_weights = {
            name: float(spec["weight"]) for name, spec in RELATION_TYPES.items()
        }
        if relation_weights:
            self.relation_weights.update({k: float(v) for k, v in relation_weights.items()})
        self.adjacency: dict[str, dict[str, float]] = {}
        self.edge_counts: dict[str, int] = {}
        self._seen: set[tuple[str, str, str]] = set()

    def add(self, left: str, right: str, relation_type: str, strength: float = 1.0) -> None:
        if left == right or strength <= 0:
            return
        base = self.relation_weights.get(relation_type, 0.0)
        if base <= 0:
            return
        a, b = (left, right) if left < right else (right, left)
        key = (a, b, relation_type)
        if key in self._seen:
            return
        self._seen.add(key)
        weight = base * float(strength)
        self.adjacency.setdefault(a, {})
        self.adjacency.setdefault(b, {})
        self.adjacency[a][b] = self.adjacency[a].get(b, 0.0) + weight
        self.adjacency[b][a] = self.adjacency[b].get(a, 0.0) + weight
        self.edge_counts[relation_type] = self.edge_counts.get(relation_type, 0) + 1

    @property
    def node_count(self) -> int:
        return len(self.adjacency)


def personalized_pagerank(
    adjacency: Mapping[str, Mapping[str, float]],
    personalization: Mapping[str, float],
    *,
    damping: float = DEFAULT_DAMPING,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, float]:
    """p = (1 - d) * s + d * W^T p, with W row-normalized and dangling mass
    returned to the seeds. ``damping`` is the probability of following an edge.

    Returns {} when there is no seed mass. Deterministic for identical inputs.
    """

    if not 0.0 <= damping < 1.0:
        raise ValueError("damping must be in [0, 1)")
    seeds = {node: float(value) for node, value in personalization.items() if value > 0 and math.isfinite(value)}
    total = sum(seeds.values())
    if total <= 0:
        return {}
    seeds = {node: value / total for node, value in seeds.items()}
    out_weight = {node: sum(neighbors.values()) for node, neighbors in adjacency.items()}
    rank = dict(seeds)
    for _ in range(max(1, max_iterations)):
        spread: dict[str, float] = {}
        dangling = 0.0
        for node, mass in rank.items():
            if mass <= 0:
                continue
            neighbors = adjacency.get(node)
            norm = out_weight.get(node, 0.0)
            if not neighbors or norm <= 0:
                dangling += mass
                continue
            scale = damping * mass / norm
            for neighbor, weight in neighbors.items():
                spread[neighbor] = spread.get(neighbor, 0.0) + scale * weight
        restart = (1.0 - damping) + damping * dangling
        for node, value in seeds.items():
            spread[node] = spread.get(node, 0.0) + restart * value
        delta = sum(abs(spread.get(node, 0.0) - rank.get(node, 0.0)) for node in set(spread) | set(rank))
        rank = spread
        if delta < tolerance:
            break
    return rank
