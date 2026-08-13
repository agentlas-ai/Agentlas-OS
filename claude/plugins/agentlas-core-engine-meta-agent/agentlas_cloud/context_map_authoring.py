"""Derive the declared context graph from what the project already records.

`.agentlas/context-map.json` was created empty by project bootstrap and never
written again: the only two things that touched it were the bootstrap that made
it and `context_map._load_declared_graph` that read it. Its note asked a human
to "add explicit goals, requirements, decisions" but no surface offered that
action, so on every machine it stayed at nodes=[] edges=[] — measured 0 nodes in
both projects on a host that had been running for months.

What the reader does with it is narrow and worth stating, because it bounds what
this module must get right: `_load_declared_graph` merges this file with
`.agentlas/sitemap.json`, and the result becomes `context.slice`'s
`goalsAndConstraints`, `relatedContextNodes` and `contextEdges`. With this file
empty, 100% of that came from the sitemap, whose only declarable entries are the
four canned seed sentences bootstrap writes. Every agent asking for the
project's goals got the same boilerplate.

The honest source is the ledger the project already keeps. `.agentlas/pm/`
`learnings/*.md` is the durable learnings layer, written after substantial work
with `## Decision — …` / `## Fact — …` section headers and evidence in the body.
`curator-decisions.jsonl` and `work-brief.json` carry the same material in
machine form. This module reads those and emits nodes.

Authored nodes carry `origin: "derived"` and are the only ones a refresh
replaces. The file declares `mergeOnly: true`, so anything a human or another
tool wrote survives untouched — a derivation that could delete someone's own
statement would make the file unsafe to write to, which is how it ended up with
no writer in the first place.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

CONTEXT_MAP_RELATIVE = ".agentlas/context-map.json"
CONTEXT_MAP_SCHEMA = "agentlas.context-map.v1"
DERIVED_ORIGIN = "derived"

# Section headers used by the learnings ledger, mapped onto the node types the
# reader already understands. `_INHERITED_NODE_TYPES` in context_map.py decides
# which of these reach `goalsAndConstraints`; the rest still travel as
# `relatedContextNodes`, which is where a fact or a procedure belongs.
_SECTION_TYPES = {
    "decision": "decision",
    "decisions": "decision",
    "fact": "fact",
    "facts": "fact",
    "procedure": "procedure",
    "procedures": "procedure",
    "hypothesis": "assumption",
    "assumption": "assumption",
    "constraint": "constraint",
    "constraints": "constraint",
    "requirement": "requirement",
    "requirements": "requirement",
    "goal": "goal",
    "goals": "goal",
    "metric": "metric",
    "risk": "assumption",
}

_SECTION_HEADER = re.compile(r"^##\s+([A-Za-z가-힣]+)\s*(?:[—–-]\s*(.*))?$")
_TITLE_HEADER = re.compile(r"^#\s+(.+)$")

# Every bound below is measured against a real heavily-used project (this repo,
# 2026-08-07: 28 learning files, largest 14.7KB, median 4.3KB, 145 section headers,
# longest title 80 chars). They exist to stop a pathological file from stalling
# project activation, not to shape output - so each is set well clear of observed
# use, and anything they DO drop is reported in the receipt rather than vanishing.
# A cap that silently truncates reads downstream as "that is all there was".
MAX_DERIVED_NODES = 2_000        # observed 40 derived from 145 sections
MAX_TITLE_CHARS = 200            # observed longest 80
MAX_SUMMARY_CHARS = 600          # display clip only; the source file stays authoritative
MAX_LEARNING_FILES = 2_000       # observed 28
MAX_LEARNING_BYTES = 4 * 1024 * 1024  # observed largest 14.7KB


def _clip(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# What the bounds above actually dropped on the last derive. Reported in the receipt so
# a capped run never reads as a complete one.
_SKIPPED: dict[str, int] = {}


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "node"


def _read_text(path: Path) -> str | None:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return None
    if path.is_symlink() or not info.st_size or info.st_size > MAX_LEARNING_BYTES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _learning_nodes(root: Path) -> list[dict[str, Any]]:
    """One node per `## <Kind> — <claim>` section of the learnings ledger."""

    folder = root / ".agentlas" / "pm" / "learnings"
    if not folder.is_dir():
        return []
    nodes: list[dict[str, Any]] = []
    every = sorted(p for p in folder.glob("*.md") if p.is_file())
    files = every[:MAX_LEARNING_FILES]
    _SKIPPED["learning_files_over_cap"] = len(every) - len(files)
    _SKIPPED["learning_files_unreadable"] = 0
    for path in files:
        text = _read_text(path)
        if text is None:
            _SKIPPED["learning_files_unreadable"] += 1
        if text is None:
            continue
        relative = str(path.relative_to(root))
        document_title = ""
        current: dict[str, Any] | None = None
        body: list[str] = []

        def flush() -> None:
            nonlocal current, body
            if current is not None:
                summary = _clip(" ".join(line for line in body if line.strip()), MAX_SUMMARY_CHARS)
                if summary:
                    current["summary"] = summary
                nodes.append(current)
            current = None
            body = []

        for line in text.splitlines():
            title_match = _TITLE_HEADER.match(line)
            if title_match and not document_title:
                document_title = _clip(title_match.group(1), MAX_TITLE_CHARS)
                continue
            header = _SECTION_HEADER.match(line)
            if header:
                flush()
                node_type = _SECTION_TYPES.get(header.group(1).strip().lower())
                if node_type is None:
                    continue
                claim = _clip(header.group(2) or document_title or path.stem, MAX_TITLE_CHARS)
                current = {
                    "id": f"learning:{_slug(path.stem)}:{_slug(claim)[:60]}",
                    "type": node_type,
                    "title": claim,
                    "status": "active",
                    "origin": DERIVED_ORIGIN,
                    "evidence": relative,
                    "document": document_title or path.stem,
                }
                continue
            if current is not None:
                body.append(line)
        flush()
    return nodes


def _curator_decision_nodes(root: Path) -> list[dict[str, Any]]:
    path = root / ".agentlas" / "curator-decisions.jsonl"
    text = _read_text(path)
    if not text:
        return []
    nodes: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, Mapping):
            continue
        claim = _clip(
            str(row.get("decision") or row.get("summary") or row.get("title") or ""),
            MAX_TITLE_CHARS,
        )
        if not claim:
            continue
        nodes.append(
            {
                "id": f"curator:{index}:{_slug(claim)[:60]}",
                "type": "decision",
                "title": claim,
                "status": str(row.get("status") or "active").lower(),
                "origin": DERIVED_ORIGIN,
                "evidence": ".agentlas/curator-decisions.jsonl",
            }
        )
    return nodes


def _work_brief_nodes(root: Path) -> list[dict[str, Any]]:
    """Goals, requirements and anti-scope the builder interview already confirmed.

    These are the only nodes here the user stated in their own words, so they are
    emitted verbatim rather than summarised.
    """

    path = root / ".agentlas" / "work-brief.json"
    text = _read_text(path)
    if not text:
        return []
    try:
        brief = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(brief, Mapping):
        return []

    def collect(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
            out: list[str] = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    out.append(item)
                elif isinstance(item, Mapping):
                    text_value = item.get("text") or item.get("statement") or item.get("description")
                    if isinstance(text_value, str) and text_value.strip():
                        out.append(text_value)
            return out
        return []

    fields = (
        ("goal", ("goal", "goals", "objective")),
        ("requirement", ("requirements", "acceptance", "acceptance_criteria")),
        ("constraint", ("constraints", "anti_scope", "antiScope", "out_of_scope")),
        ("metric", ("done_signal", "doneSignal", "stop_criterion", "stopCriterion")),
    )
    nodes: list[dict[str, Any]] = []
    for node_type, keys in fields:
        for key in keys:
            for statement in collect(brief.get(key)):
                claim = _clip(statement, MAX_TITLE_CHARS)
                nodes.append(
                    {
                        "id": f"brief:{node_type}:{_slug(claim)[:60]}",
                        "type": node_type,
                        "title": claim,
                        "status": "active",
                        "origin": DERIVED_ORIGIN,
                        "evidence": ".agentlas/work-brief.json",
                    }
                )
    return nodes


def derive_context_nodes(root: Path) -> list[dict[str, Any]]:
    """Every derived node, newest evidence first, de-duplicated by id."""

    _SKIPPED.clear()
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    candidates = _work_brief_nodes(root) + _curator_decision_nodes(root) + _learning_nodes(root)
    for index, node in enumerate(candidates):
        node_id = str(node.get("id") or "")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        ordered.append(node)
        if len(ordered) >= MAX_DERIVED_NODES:
            _SKIPPED["nodes_over_cap"] = len(candidates) - index - 1
            break
    return ordered


def last_derive_skipped() -> dict[str, int]:
    """Non-zero counts of what the bounds dropped on the last derive."""

    return {key: value for key, value in _SKIPPED.items() if value}


def refresh_declared_context(project: str | Path) -> dict[str, Any]:
    """Rewrite only the derived half of `.agentlas/context-map.json`.

    Returns a receipt rather than raising because explicit project bootstrap
    owns this materialization and must report unreadable ledgers without
    partially rewriting declared context.
    """

    root = Path(project).expanduser().resolve()
    path = root / CONTEXT_MAP_RELATIVE
    receipt: dict[str, Any] = {
        "action": "refresh_declared_context",
        "path": CONTEXT_MAP_RELATIVE,
        "derived": 0,
        "preserved": 0,
        "written": False,
    }
    if not (root / ".agentlas").is_dir():
        receipt["status"] = "no_project_state"
        return receipt

    existing: dict[str, Any] = {}
    if path.exists():
        text = _read_text(path)
        if text:
            try:
                loaded = json.loads(text)
                if isinstance(loaded, Mapping):
                    existing = dict(loaded)
            except json.JSONDecodeError:
                receipt["status"] = "unreadable"
                return receipt

    preserved = [
        node
        for node in (existing.get("nodes") or [])
        if isinstance(node, Mapping) and node.get("origin") != DERIVED_ORIGIN
    ]
    preserved_edges = [
        edge
        for edge in (existing.get("edges") or [])
        if isinstance(edge, Mapping) and edge.get("origin") != DERIVED_ORIGIN
    ]
    derived = derive_context_nodes(root)

    payload = dict(existing)
    payload.setdefault("schemaVersion", CONTEXT_MAP_SCHEMA)
    payload.setdefault("projectId", existing.get("projectId") or root.name)
    payload.setdefault(
        "statuses",
        ["active", "deprecated", "superseded", "tentative", "validated", "rejected"],
    )
    payload["mergeOnly"] = True
    payload["nodes"] = [*preserved, *derived]
    payload["edges"] = preserved_edges
    payload["note"] = (
        "Nodes with origin=derived are regenerated from .agentlas/work-brief.json, "
        "curator-decisions.jsonl and pm/learnings/*.md. Anything without that flag "
        "is yours and is never rewritten. Generated code dependencies stay in "
        "code-map/project-map.json."
    )

    receipt["derived"] = len(derived)
    skipped = last_derive_skipped()
    if skipped:
        receipt["skipped"] = skipped
    receipt["preserved"] = len(preserved)

    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8", errors="replace") == serialized:
        receipt["status"] = "unchanged"
        return receipt
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    except OSError as exc:
        receipt["status"] = "write_failed"
        receipt["detail"] = str(exc)
        return receipt
    receipt["status"] = "written"
    receipt["written"] = True
    return receipt
