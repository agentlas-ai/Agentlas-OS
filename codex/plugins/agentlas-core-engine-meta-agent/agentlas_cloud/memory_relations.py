"""Relation edges between two memory lines (``memory_relation_edges``): the allowed kinds, one writer and the readers.

The table is the desktop's and has always allowed three kinds in its CHECK: ``similar_to`` (written by the desktop when a line is stored),
``supersedes`` (the desktop, when a line replaces another) and ``contradicts`` (allowed, written by nobody until now). The engine did not write edges.
This module is the engine's one door to them: ``write_edge`` (validated, idempotent, writes nothing outside ``memory_relation_edges``) and the readers.
**No caller in the engine uses ``write_edge`` yet** (and the merge write them), so changes no behaviour.

The owner scope key is the desktop's (``electron/memory/graph.ts memoryOwnerScopeKey``): ``user:local`` | ``team:local`` | ``agent:<id>`` |
``project:<id>`` | ``project-path:<sha256(path)[:24]>``; an edge joins two lines of the same key.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from typing import Any, Iterable

RELATION_TYPES = ("similar_to", "supersedes", "contradicts")
"""The closed set of ``relation_type`` (the table's CHECK). ``similar_to`` is stored once per pair (smaller id first); the other two are directed: from the newer line to
the older one (``supersedes``) / from the line that was written to the one it disagrees with (``contradicts``)."""
UNDIRECTED = frozenset({"similar_to"})


class RelationError(ValueError):
    """A machine code in ``args[0]`` (``relation_type_invalid``, ``relation_same_line``, ``relation_score_invalid``, ``relation_owner_scope_missing``,
    ``relation_line_missing``)."""


def owner_scope_key(scope: str | None, agent_id: str | None = None, project_id: str | None = None, project_path: str | None = None) -> str | None:
    """The same key the desktop gives a line (``memoryOwnerScopeKey``); None for a line that has no owner scope (the desktop writes no edge for it)."""
    if scope == "user_identity":
        return "user:local"
    if scope in ("team_memory", "agent_team"):
        return "team:local"
    if scope == "agent_repo" and agent_id:
        return f"agent:{agent_id}"
    if scope == "project":
        if project_id:
            return f"project:{project_id}"
        if project_path:
            return "project-path:" + hashlib.sha256(project_path.encode("utf-8")).hexdigest()[:24]
    return None


def write_edge(db: sqlite3.Connection, from_id: str, to_id: str, relation_type: str, *, owner_scope_key: str | None,
               score: float | None = None, embedding: tuple[str | None, str | None, str | None] = (None, None, None),
               now: str | None = None) -> bool:
    """Write one edge; True when a row was added, False when that edge already existed (``INSERT OR IGNORE`` on the pair and kind: it can run again).

    Does not commit (the caller's transaction). Raises ``RelationError`` for a kind outside ``RELATION_TYPES``, an edge from a line to itself, a score outside
    -1..1, no owner scope key, or a line id that is not in this file's ``memory_entries`` (the table's foreign keys would refuse it only when they are on).
    ``similar_to`` is written once per pair, the smaller id first, as the desktop writes it."""
    if relation_type not in RELATION_TYPES:
        raise RelationError("relation_type_invalid")
    if not from_id or not to_id or from_id == to_id:
        raise RelationError("relation_same_line")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not -1.0 <= float(score) <= 1.0):
        raise RelationError("relation_score_invalid")
    if not owner_scope_key:
        raise RelationError("relation_owner_scope_missing")
    if relation_type in UNDIRECTED:
        from_id, to_id = sorted((from_id, to_id))
    for ident in (from_id, to_id):
        if db.execute("SELECT 1 FROM memory_entries WHERE id=?", (ident,)).fetchone() is None:
            raise RelationError("relation_line_missing")
    model, adapter, sha = embedding
    stamp = now or time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"
    return db.execute(
        "INSERT OR IGNORE INTO memory_relation_edges(relation_id,from_memory_id,to_memory_id,relation_type,score,owner_scope_key,"
        "embedding_model,embedding_adapter,embedding_model_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("mre_" + str(uuid.uuid4()), from_id, to_id, relation_type, score, owner_scope_key, model, adapter, sha, stamp)).rowcount > 0


def edges_of(db: sqlite3.Connection, line_id: str, relation_type: str | None = None) -> list[dict[str, Any]]:
    """Every edge that touches a line (either end), newest first: ``{relationId, from, to, type, score, ownerScopeKey, createdAt}``. Reads only; a file without the table answers ``[]``."""
    if relation_type is not None and relation_type not in RELATION_TYPES:
        raise RelationError("relation_type_invalid")
    try:
        rows = db.execute(
            "SELECT relation_id,from_memory_id,to_memory_id,relation_type,score,owner_scope_key,created_at FROM memory_relation_edges "
            "WHERE (from_memory_id=? OR to_memory_id=?)" + (" AND relation_type=?" if relation_type else "") + " ORDER BY created_at DESC,relation_id DESC",
            (line_id, line_id, *((relation_type,) if relation_type else ()))).fetchall()
    except sqlite3.Error:
        return []
    return [{"relationId": r[0], "from": r[1], "to": r[2], "type": r[3], "score": r[4], "ownerScopeKey": r[5], "createdAt": r[6]} for r in rows]


def contradictions_of(db: sqlite3.Connection, line_ids: Iterable[str]) -> dict[str, list[str]]:
    """``{line id: [the lines it contradicts or is contradicted by]}`` for the live lines among ``line_ids`` (a line that was superseded or forgotten is not a counterpart).
    Reads only; the read that recall's "which of two sides to prefer" will use."""
    ids = list(dict.fromkeys(line_ids))
    found: dict[str, list[str]] = {}
    for start in range(0, len(ids), 300):
        chunk = ids[start:start + 300]
        marks = ",".join("?" * len(chunk))
        try:
            rows = db.execute(
                f"SELECT e.from_memory_id,e.to_memory_id FROM memory_relation_edges e "
                f"JOIN memory_entries a ON a.id=e.from_memory_id AND a.superseded_at IS NULL AND a.content<>'' "
                f"JOIN memory_entries b ON b.id=e.to_memory_id AND b.superseded_at IS NULL AND b.content<>'' "
                f"WHERE e.relation_type='contradicts' AND (e.from_memory_id IN ({marks}) OR e.to_memory_id IN ({marks}))", [*chunk, *chunk]).fetchall()
        except sqlite3.Error:
            return found
        wanted = set(ids)
        for a, b in rows:
            for mine, other in ((a, b), (b, a)):
                if mine in wanted and other not in found.get(mine, []):
                    found.setdefault(mine, []).append(other)
    return found
