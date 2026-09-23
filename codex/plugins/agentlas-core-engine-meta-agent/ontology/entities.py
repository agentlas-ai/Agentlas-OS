"""Deterministic, code-aware entity layer for the project document ontology.

Why this replaced the Title-Case extractor (2026-09-23 measurement, private
bench ``docs/benchmark/ontology-entities``): project documents are written in
Korean or English prose, but the *names* in them — functions, files, commands,
environment variables, tool keys, error codes — are ASCII code spans in either
language (94% of Agentlas-OS chunks carry a backtick span, 50% a file path).
The old extractor only knew "Capitalised English phrase" and "A depends on B"
sentences; after orphan pruning it left 5 relations for the whole project, two
of them from a test fixture. Sentence verb patterns measured 4/15 precise
(table cells read as sentences, negation, reversed direction) and are gone.

What this module does, with no model call:

* ``extract_mentions`` — typed mentions in a chunk: ``file`` (resolved against
  the Context Map), ``path`` (path-shaped but not a file of this project),
  ``symbol`` (a Context Map definition), ``command``, ``env_var``, ``key``
  (dotted tool/schema keys), ``code_id`` (code-shaped names without a
  definition: error codes, fields), ``package``, ``version``.
* ``entity_keys`` — lookup keys for question linking: exact lower-case name,
  file basename and stem, and the word-split form (``graph_spread.py`` ->
  "graph spread") so a plain English question still reaches a code name.
* ``cooccurrence_edges`` — NPMI co-occurrence over chunks with the hub and
  enumeration filters that took precision from 6/15 to 12/15.
* ``question_tokens`` / ``question_word_ngrams`` — the query-side linker.

Structural facts (definitions, imports, co-edits) come from the Context Map and
contact ledger through ``graph_spread``'s cached loader, the same one
experience recall uses, so both surfaces read the code map one way.
"""

from __future__ import annotations

import math
import re
from collections import Counter, OrderedDict
from typing import Any, Iterable, Mapping

# Bump when extraction output changes; the runtime re-extracts every chunk once.
EXTRACTOR_VERSION = "code-aware.v1"

# Relation bases. ``code_map``/``ledger`` edges carry no evidence chunk (their
# evidence is the code map snapshot or the ledger), so they are the only rows
# allowed a NULL evidence_chunk_id.
BASIS_CODE_MAP = "code_map"
BASIS_LEDGER = "ledger"
BASIS_CORRELATION = "correlation"
BASIS_DECLARED = "declared"
BASIS_ASSERTED = "asserted"
# Environment variables a code file reads, scanned from the files the Context
# Map lists (the code map indexes identifiers, not string literals).
BASIS_CODE_SCAN = "code_scan"
STRUCTURAL_BASES = (BASIS_CODE_MAP, BASIS_LEDGER, BASIS_CODE_SCAN)
# Bases the extractor owns and rewrites on a re-extraction. ``asserted`` is what
# pre-code-aware rows default to (Title-Case sentence patterns): dropped.
EXTRACTED_BASES = (BASIS_CORRELATION, BASIS_DECLARED, BASIS_ASSERTED)

# Relation-line order and hop weights (measured in the prototype; defined_in
# and imported_by are exact code-map facts, co_occurs is correlation).
LINE_PRIORITY = {
    "defined_in": 0,
    "imported_by": 1,
    "read_by": 1,
    "depends_on": 2,
    "owns": 2,
    "co_edited": 3,
    "co_occurs": 4,
    "mentions": 5,
}
HOP_WEIGHT = {
    "defined_in": 1.0,
    "imported_by": 0.8,
    "read_by": 0.8,
    "depends_on": 0.7,
    "owns": 0.7,
    "co_edited": 0.6,
    "co_occurs": 0.5,
}

CODE_SPAN = re.compile(r"(?<!`)`([^`\n]{2,120})`(?!`)")
_PATH_EXT = "py|pyi|ts|tsx|js|jsx|cjs|mjs|json|jsonl|md|sh|sql|yaml|yml|toml|rs|go|css|html|txt"
# Boundaries are ASCII on purpose: Korean attaches particles directly to a name
# ("circuit.py가", "NODE_ENV는"), and Unicode \b / \w treat Hangul as a word
# character, which silently dropped every such mention.
PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_/.\-])((?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_\-][A-Za-z0-9_.\-]*\.(?:" + _PATH_EXT + r"))(?::\d+)?(?![A-Za-z0-9_/])"
)
ENV_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,})(?![A-Za-z0-9_])")
SLASH_CMD_RE = re.compile(r"(?<![A-Za-z0-9_/])(/(?:hep|agentlas)-[a-z][a-z\-]*)(?![A-Za-z0-9_\-])")
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
SPAN_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.\-/@])[A-Za-z_][A-Za-z0-9_]*(?:[.\-][A-Za-z0-9_]+)*")
VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-.][\w.]+)?$")
SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}$")
CAMEL_RE = re.compile(r"^[a-z]+(?:[A-Z][a-z0-9]+)+$|^(?:[A-Z][a-z0-9]+){2,}$")
DOTTED_RE = re.compile(r"^[a-z_][\w\-]*(?:\.[a-z_][\w\-]*)+$")
PACKAGE_RE = re.compile(r"^@[a-z0-9\-]+/[a-z0-9\-.]+$")
CODE_FILE_RE = re.compile(r"\.(py|pyi|ts|tsx|js|jsx|cjs|mjs|sh)$")
CLI_HEADS = {"agentlas", "npm", "npx", "node", "python3", "python", "git", "bash", "pnpm", "gh", "codex", "claude", "hep"}
NOT_FILES = {"node.js", "next.js", "vue.js", "react.js", "three.js", "d3.js", "chart.js", "express.js"}
ENV_STOP = {"README", "TODO", "NOTE", "HTTP", "JSON", "UTF_8", "API_KEY"}
STEM_STOP = {"skill", "readme", "index", "agents", "__init__", "claude", "changelog", "config", "utils", "types"}

MAX_ENTITIES_PER_CHUNK = 64
COOC_NPMI_MIN = 0.25
COOC_HUB_FRACTION = 0.05
COOC_MAX_PER_CHUNK = 30
COOC_ENUM_MIN = 5
DEFINITION_MAX_FILES = 3
CO_EDIT_MIN_UNITS = 2
MAX_LINK_SEEDS = 12


class CodeIndex:
    """The Context Map facts extraction needs, from graph_spread's loader."""

    def __init__(self, code_map: Mapping[str, Any] | None):
        code_map = code_map or {}
        self.snapshot_id: str = str(code_map.get("snapshotId") or "")
        self.mapped: set[str] = set(code_map.get("mappedFiles") or ())
        self.definitions: Mapping[str, list[str]] = code_map.get("definitionsAll") or {}
        self.symbol_case: Mapping[str, str] = code_map.get("symbolCase") or {}
        self.edges: list[tuple[str, str, str]] = list(code_map.get("dependencyEdges") or ())
        by_basename: dict[str, list[str]] = {}
        suffixes: dict[str, str | None] = {}
        for path in self.mapped:
            by_basename.setdefault(path.rsplit("/", 1)[-1].lower(), []).append(path)
            parts = path.split("/")
            for index in range(1, len(parts)):
                suffix = "/".join(parts[index:])
                suffixes[suffix] = None if suffix in suffixes and suffixes[suffix] != path else path
        self.by_basename = by_basename
        self.suffixes = {key: value for key, value in suffixes.items() if value is not None}

    @property
    def available(self) -> bool:
        return bool(self.mapped or self.definitions)

    def resolve_path(self, raw: str) -> str | None:
        raw = raw.strip()
        while raw.startswith("./"):
            raw = raw[2:]
        if not raw or raw.lower() in NOT_FILES or ".." in raw.split("/"):
            return None
        if raw in self.mapped:
            return raw
        if "/" in raw:
            return self.suffixes.get(raw)
        hits = self.by_basename.get(raw.lower(), [])
        return hits[0] if len(hits) == 1 else None

    def symbol_name(self, bare: str) -> str | None:
        low = bare.lower()
        if low not in self.definitions:
            return None
        return self.symbol_case.get(low, bare)


def code_shaped_name(name: str) -> bool:
    return len(name) >= 5 and not name.startswith("__") and ("_" in name.strip("_") or bool(CAMEL_RE.match(name)))


def classify_span(span: str, code: CodeIndex) -> tuple[str, str] | None:
    s = span.strip().strip("()`'\"")
    if not s or len(s) < 3:
        return None
    first = s.split()[0]
    if s.startswith("/") and re.match(r"^/[a-z][a-z\-]+$", first):
        return ("command", first)
    if first in CLI_HEADS and len(s.split()) >= 2:
        tokens = s.split()
        canon = " ".join(t for t in tokens[:3] if not t.startswith("-") and not t.startswith("<"))
        return ("command", canon) if " " in canon else None
    if " " in s:
        return None  # multi-word spans: see span_identifiers
    match = PATH_RE.fullmatch(s) or PATH_RE.fullmatch(s.split(":")[0])
    if match:
        resolved = code.resolve_path(match.group(1))
        if resolved:
            return ("file", resolved)
        raw = match.group(1)
        return None if raw.lower() in NOT_FILES else ("path", raw)
    if PACKAGE_RE.match(s):
        return ("package", s)
    if VERSION_RE.match(s):
        return ("version", s)
    if ENV_RE.fullmatch(s) and s not in ENV_STOP:
        return ("env_var", s)
    bare = s.rstrip("()")
    if ("_" in bare or CAMEL_RE.match(bare)) and len(bare) >= 5:
        symbol = code.symbol_name(bare)
        if symbol:
            return ("symbol", symbol)
    if DOTTED_RE.match(s) and not re.search(r"\.(md|py|json)$", s):
        return ("key", s)
    if SNAKE_RE.match(bare) and len(bare) >= 8:
        return ("code_id", bare)
    if CAMEL_RE.match(bare) and len(bare) >= 8:
        return ("code_id", bare)
    # Backticked kebab names are identifiers too: MCP servers, skills, packages.
    if KEBAB_RE.match(bare) and len(bare) >= 8:
        return ("code_id", bare)
    return None


def span_identifiers(span: str, code: "CodeIndex") -> list[tuple[str, str]]:
    """Code names inside a multi-word code span (`sourceScope: "cloud"`,
    `retry_charge(order_id)`), each classified like a span of its own."""

    found: list[tuple[str, str]] = []
    for match in SPAN_TOKEN_RE.finditer(span):
        typed = classify_span(match.group(0), code)
        if typed and typed[0] not in ("version", "path"):
            found.append(typed)
    return found


FENCE_RE = re.compile(r"```")


def fenced_ranges(text: str) -> list[tuple[int, int]]:
    """Character ranges inside ``` fences (an unclosed fence runs to the end:
    chunk windows can cut a block in half)."""

    marks = [match.start() for match in FENCE_RE.finditer(text or "")]
    ranges = []
    for index in range(0, len(marks), 2):
        start = marks[index]
        end = marks[index + 1] + 3 if index + 1 < len(marks) else len(text)
        ranges.append((start, end))
    return ranges


def extract_mentions(text: str, code: CodeIndex) -> list[tuple[str, str]]:
    """Typed mentions ``[(entity_type, canonical_name)]`` in text order, unique."""

    return [(kind, name) for kind, name, _in_code in extract_mentions_with_context(text, code)]


def extract_mentions_with_context(text: str, code: CodeIndex) -> list[tuple[str, str, bool]]:
    """``[(entity_type, canonical_name, only_inside_code_blocks)]``.

    A name that appears only inside fenced code (the shell runner snippet many
    command documents repeat) is still a mention for linking, but it is not
    prose that relates it to its neighbours, so co-occurrence skips it.
    """

    found: list[tuple[str, str, int]] = []
    covered: list[tuple[int, int]] = []
    for match in CODE_SPAN.finditer(text or ""):
        covered.append((match.start(), match.end()))
        typed = classify_span(match.group(1), code)
        if typed:
            found.append((typed[0], typed[1], match.start()))
        else:
            for kind, name in span_identifiers(match.group(1), code):
                found.append((kind, name, match.start()))

    def free(start: int, end: int) -> bool:
        return not any(a <= start < b or a < end <= b for a, b in covered)

    for match in PATH_RE.finditer(text or ""):
        if free(match.start(), match.end()):
            resolved = code.resolve_path(match.group(1))
            if resolved:
                found.append(("file", resolved, match.start()))
    for match in SLASH_CMD_RE.finditer(text or ""):
        if free(match.start(), match.end()):
            found.append(("command", match.group(1), match.start()))
    for match in ENV_RE.finditer(text or ""):
        name = match.group(1)
        if free(match.start(), match.end()) and name not in ENV_STOP and len(name) >= 6:
            found.append(("env_var", name, match.start()))
    found.sort(key=lambda item: item[2])
    fences = fenced_ranges(text or "")
    unique: "OrderedDict[tuple[str, str], bool]" = OrderedDict()
    for etype, name, position in found:
        in_code = any(start <= position < end for start, end in fences)
        key = (etype, name)
        if key in unique:
            unique[key] = unique[key] and in_code
        elif len(unique) < MAX_ENTITIES_PER_CHUNK:
            unique[key] = in_code
    return [(etype, name, in_code) for (etype, name), in_code in unique.items()]


def document_path(raw_text: str, display_name: str) -> str:
    """Original relative path of a project-document snapshot, else its name."""

    head = (raw_text or "")[:600]
    match = re.match(r"Project document: ([^\n]+)\n", head)
    if match:
        return match.group(1).strip()
    return display_name


def split_words(name: str) -> str | None:
    """``graph_spread.py`` -> "graph spread"; ``queryExperience`` -> "query experience"."""

    base = name.rsplit("/", 1)[-1]
    base = re.sub(r"\.(py|pyi|ts|tsx|js|jsx|cjs|mjs|md|json|sh)$", "", base)
    base = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", base)
    words = [word for word in re.split(r"[_\-\s./]+", base.lower()) if word]
    if len(words) < 2:
        return None
    joined = " ".join(words)
    return joined if len(joined) >= 8 else None


def entity_keys(entity_type: str, name: str) -> list[tuple[str, str]]:
    keys = {(name.lower(), "exact")}
    if entity_type in ("file", "doc", "path"):
        base = name.rsplit("/", 1)[-1]
        keys.add((base.lower(), "basename"))
        stem = re.sub(r"\.\w+$", "", base).lower()
        if len(stem) >= 5 and stem not in STEM_STOP:
            keys.add((stem, "stem"))
    if entity_type in ("file", "symbol", "code_id", "env_var", "key"):
        words = split_words(name)
        if words:
            keys.add((words, "words"))
    return sorted(keys)


# --- environment reads (code scan) ---------------------------------------

_ENV_READ_PATTERNS = (
    # Python: os.environ.get("X"), os.environ["X"], os.getenv("X"), environ.setdefault("X")
    re.compile(r"""(?:environ(?:\.get|\.setdefault|\.pop)?\s*[\(\[]|getenv\s*\()\s*['"]([A-Z][A-Z0-9_]{3,})['"]"""),
    # JS/TS: process.env.X, process.env["X"], env.X after destructuring is not tracked
    re.compile(r"""process\.env(?:\.([A-Z][A-Z0-9_]{3,})|\[\s*['"]([A-Z][A-Z0-9_]{3,})['"]\s*\])"""),
    # A constant that names the variable: MODEL_POLICY_ENV = "AGENTLAS_X"
    re.compile(r"""\b(?:[A-Z][A-Z0-9_]*)?ENV[A-Z0-9_]*\s*(?::\s*[A-Za-z\[\]]+\s*)?=\s*['"]([A-Z][A-Z0-9_]{3,})['"]"""),
    # Shell: ${X} / ${X:-default} / "$X"
    re.compile(r"""\$\{([A-Z][A-Z0-9_]{3,})(?:[:}\-=?+])"""),
)
ENV_SCAN_SUFFIXES = (".py", ".sh", ".bash", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx")
ENV_SCAN_MAX_BYTES = 512 * 1024
ENV_SCAN_MAX_FILES = 20_000
ENV_SCAN_SKIP_PARTS = {"node_modules", "_vendor", "vendor", "dist", "build", "__pycache__"}
_ENV_SCAN_CACHE: dict[str, tuple[tuple[int, int], frozenset[str]]] = {}


def env_reads_in_text(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in _ENV_READ_PATTERNS:
        for match in pattern.finditer(text):
            name = next((group for group in match.groups() if group), None)
            if name and "_" in name and len(name) >= 6 and name not in ENV_STOP:
                found.add(name)
    return found


def scan_env_reads(root: Any, files: Iterable[str]) -> dict[str, set[str]]:
    """``{ENV_NAME: {relative code file, ...}}`` for string-literal env reads.

    Bounded (size, count, vendored trees skipped) and cached per file version,
    so a refresh after a small code change rereads only the changed files.
    """

    from pathlib import Path

    base = Path(root)
    reads: dict[str, set[str]] = {}
    scanned = 0
    for relative in sorted(files):
        if not relative.endswith(ENV_SCAN_SUFFIXES) or ENV_SCAN_SKIP_PARTS & set(relative.split("/")):
            continue
        if scanned >= ENV_SCAN_MAX_FILES:
            break
        path = base / relative
        try:
            if path.is_symlink() or not path.is_file():
                continue
            info = path.stat()
        except OSError:
            continue
        if info.st_size > ENV_SCAN_MAX_BYTES:
            continue
        scanned += 1
        version = (int(info.st_mtime_ns), int(info.st_size))
        cached = _ENV_SCAN_CACHE.get(str(path))
        if cached is not None and cached[0] == version:
            names = cached[1]
        else:
            try:
                names = frozenset(env_reads_in_text(path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
            _ENV_SCAN_CACHE[str(path)] = (version, names)
        for name in names:
            reads.setdefault(name, set()).add(relative)
    return reads


# --- question side ---------------------------------------------------------

_QUESTION_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-./@])[/@]?[A-Za-z_][A-Za-z0-9_\-./]*[A-Za-z0-9_]")


def question_tokens(question: str) -> list[str]:
    """Code-shaped ASCII tokens in a question, in any surrounding language."""

    tokens: list[str] = []
    for token in _QUESTION_TOKEN.findall(question or ""):
        code_shaped = (
            any(ch in token for ch in "_./")
            or re.search(r"[a-z][A-Z]", token) is not None
            or (token.isupper() and len(token) >= 4)
            or token.startswith("/")
            or (KEBAB_RE.match(token) is not None and len(token) >= 8)
        )
        if code_shaped and token not in tokens:
            tokens.append(token)
    return tokens


def question_word_ngrams(question: str, low: int = 2, high: int = 5) -> list[str]:
    words = re.findall(r"[a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", question or "").lower())
    grams: list[str] = []
    for size in range(high, low - 1, -1):
        for index in range(0, len(words) - size + 1):
            gram = " ".join(words[index : index + size])
            if len(gram) >= 8:
                grams.append(gram)
    return list(dict.fromkeys(grams))


# --- co-occurrence ---------------------------------------------------------


def cooccurrence_edges(
    chunk_entities: Mapping[str, Iterable[str]],
    entity_type: Mapping[str, str],
    *,
    npmi_min: float = COOC_NPMI_MIN,
    hub_fraction: float = COOC_HUB_FRACTION,
    total_chunks: int | None = None,
) -> list[tuple[str, str, float, str]]:
    """``[(entity_a, entity_b, npmi, evidence_chunk_id)]`` with a < b.

    A pair counts once per chunk, needs >= 2 chunks, and must clear NPMI.
    Hubs (entities in more than ``hub_fraction`` of chunks) and versions are
    left out; a chunk that lists >= COOC_ENUM_MIN entities of one type (a
    command table, "writes a, b, c, d") says they are siblings, not related,
    so same-type pairs from it are not counted.
    """

    n_chunks = max(len(chunk_entities), int(total_chunks or 0))
    if n_chunks < 2:
        return []
    frequency: Counter[str] = Counter()
    for ids in chunk_entities.values():
        frequency.update(set(ids))
    hub_cut = max(3, int(hub_fraction * n_chunks))
    pair_count: Counter[tuple[str, str]] = Counter()
    pair_chunk: dict[tuple[str, str], str] = {}
    for chunk_id in sorted(chunk_entities):
        keep = sorted(
            {entity for entity in chunk_entities[chunk_id] if frequency[entity] <= hub_cut and entity_type.get(entity) != "version"}
        )
        if len(keep) > COOC_MAX_PER_CHUNK or len(keep) < 2:
            continue
        type_count = Counter(entity_type.get(entity) for entity in keep)
        for x in range(len(keep)):
            tx = entity_type.get(keep[x])
            for y in range(x + 1, len(keep)):
                if tx == entity_type.get(keep[y]) and type_count[tx] >= COOC_ENUM_MIN:
                    continue
                pair = (keep[x], keep[y])
                pair_count[pair] += 1
                pair_chunk.setdefault(pair, chunk_id)
    edges: list[tuple[str, str, float, str]] = []
    for (a, b), count in pair_count.items():
        if count < 2:
            continue
        p_ab = count / n_chunks
        if p_ab >= 1.0:
            continue
        p_a, p_b = frequency[a] / n_chunks, frequency[b] / n_chunks
        npmi = math.log(p_ab / (p_a * p_b)) / -math.log(p_ab)
        if npmi >= npmi_min:
            edges.append((a, b, round(npmi, 3), pair_chunk[(a, b)]))
    edges.sort()
    return edges


def co_edit_pairs(units: Iterable[frozenset[str]], max_unit: int) -> Counter[tuple[str, str]]:
    pairs: Counter[tuple[str, str]] = Counter()
    for unit in units:
        files = sorted(unit)
        if len(files) < 2 or len(files) > max_unit:
            continue
        for index, left in enumerate(files):
            for right in files[index + 1 :]:
                pairs[(left, right)] += 1
    return pairs


def round_robin(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Diverse relation lines: types in priority order, one per type per round.

    A big file's forty ``defined_in`` edges must not fill every context line
    the desktop shows (it renders the first six).
    """

    by_type: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
    for row in sorted(rows, key=lambda r: (LINE_PRIORITY.get(r["relation_type"], 9), r.get("_rank", 0))):
        by_type.setdefault(row["relation_type"], []).append(row)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    depth = 0
    while len(out) < limit and any(len(items) > depth for items in by_type.values()):
        for items in by_type.values():
            if len(items) > depth:
                row = items[depth]
                if row["relation_id"] not in seen:
                    seen.add(row["relation_id"])
                    out.append(row)
                if len(out) >= limit:
                    break
        depth += 1
    return out
