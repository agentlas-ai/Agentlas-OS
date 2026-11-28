"""Moving memory rows into their own stores, and forgetting across all of them.

The root store (``memory.sqlite``) is where every row lived. Under the layout switch ``memory_layout = split-1`` new
agent and project rows are written to their own store (agent folder / project folder under the memory root, see
``memory_stores``) and this module moves the rows that are already in the root. Nothing here runs unless the switch
is ``split-1``; the desktop is the one that sets it, through ``start`` below, after it has checked its own
conditions. This module is the only implementation of the move: the desktop calls the command line.

The move
--------
A move is a MOVE, never a copy of the database. Rows go in batches of 200: the batch is read while holding the root's
write lock, written to the destination store and committed there, checked to be present there, and only then deleted
from the root and committed. At any instant a row exists in at least one place, and a crash anywhere leaves a state the
next call continues from: the copy overwrites the destination row with the root's (the root is the source of truth while
the move runs), so it is idempotent, and the delete runs only for rows whose id, text and ``superseded_at`` are the same
in the destination. Two callers at once (desktop Main, daemon, terminal) are safe for the same reason and are kept apart by a
lock file (not by a meta key); whoever finds it held answers ``busy``.

Disk: the root file does not shrink while rows leave it, so the peak is the root's size plus the moved bytes, reached at
the end of the move; no whole-database copy is ever made. Before it starts, ``start`` and ``step`` require free space of
``max(256 MB, 2 x the bytes to move)``. When the move is complete and the root holds a large share of free pages, one
``VACUUM`` (with ``auto_vacuum=INCREMENTAL`` so later deletes are reclaimed) shrinks it; it is skipped, never forced, when
the disk is short or the file is busy.

What is never moved: personal rows, ``host:*`` and other resident actors, Hub agents (``hub:``), rows whose agent has
no folder with an owner.json (the engine does not build agent folders), project rows with no folder key, ``legacy-shared``
rows, rows whose translation is still pending (the translator reads the root only) and ``session`` rows (checkpoints have
their own file). They stay in the root, which every reader still reads.

Progress is a JSON object (command line: one JSON line). The only meta keys this adds to the root are ``memory_layout``
and ``drain_swept_revision``.

Turning it off: ``revert`` sets the layout to ``split-paused`` (new rows go to the root again, reading stays a union,
nothing is moved); with ``merge_back`` it also moves every row back into the root and removes the key. An older engine
that opens the root afterwards sees the root's own schema and rows, nothing new.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, NamedTuple

from . import agent_home
from . import long_path
from . import memory_stores as ms
from .memory_actor_family import memory_actor_ids
from .memory_scopes import owner_scope_of

BATCH_ROWS = 200
PAUSE_SECONDS = 0.12           # longer than SQLite's longest retry interval (0.1 s): a writer that is waiting for the root's lock comes back inside this gap (defect 9: at 0.02 s it kept missing the gap and waited across several batches)
LOCK_TARGET_SECONDS = 0.12     # one transaction holds the root's write lock about this long at most; the next batch is sized from the hold just measured
FIRST_BATCH_ROWS = 100
MIN_BATCH_ROWS = 100           # below this the fixed cost of a transaction (commit, scans) dominates: smaller batches would only take longer overall
MIN_FREE_BYTES = 256 * 1024 * 1024
CURRENT_ENGINE_CAPABILITY = 4      # Agentlas 2.0 the ``memory_layout`` number of this engine (capabilities.json). It is NOT a gate: ``engine_inventory`` counts the copies below it (``belowCurrent``) so the desktop can tell the owner which plugin to update; nothing is held back by the count
MIN_ENGINE_LAYOUT_CAPABILITY = 2   # the capability an engine copy must declare before rows move: 1 was a development stage (no team-row rule, no forget repair) that was never published
# 3 = the engine reads a move-bundle stamp (memory_stores.ONE_PACK_STAMP_SOURCE) as Personal-only; one_pack.import_rows refuses while any copy is below 3. This number (2) is the one the layout move needs and every reader compares with >=.
PAUSED_LAYOUT = "split-paused"
SWEPT_KEY = "drain_swept_revision"
CANDIDATE_SCOPES = ("agent_repo", "project", "team_memory", "agent_team")

ROW_TABLES = (  # copied with the entry, in this order (the entry first: the others reference it)
    ("memory_entries", "id"),
    ("memory_identity_bindings", "memory_id"),
    ("memory_project_links", "memory_id"),
    ("memory_origin_links", "memory_id"),
    ("memory_entry_native", "entry_id"),
)


class BatchPacer:
    """Sizes the batches of a long job so that none holds the write lock much longer than ``LOCK_TARGET_SECONDS`` (the desktop's main thread
    waits on that lock). ``size`` is the next batch's row count, between ``MIN_BATCH_ROWS`` and ``cap``; ``took(held, rows)`` learns from how
    long the last batch held the lock: well under the target, grow by a quarter; over it, shrink by a quarter (by half when far over). A batch costs
    a fixed part (commit, scans) plus a part per row, so the size is steered by the hold itself, not by a per-row guess. Nothing is stored:
    every call of a job starts again from ``FIRST_BATCH_ROWS``; a slow disk settles on smaller batches, a fast one on the ``cap``."""

    def __init__(self, cap: int, *, first: int = FIRST_BATCH_ROWS):
        self.cap = max(1, int(cap))
        self.size = min(self.cap, max(1, first))

    def took(self, held_seconds: float, rows: int) -> None:
        if held_seconds > 1.5 * LOCK_TARGET_SECONDS:
            size = max(self.size, rows) // 2
        elif held_seconds > LOCK_TARGET_SECONDS:
            size = max(self.size, rows) * 3 // 4
        elif held_seconds < 0.8 * LOCK_TARGET_SECONDS and rows * 4 >= self.size * 3:  # a short last batch of a window says nothing about a full one
            size = self.size * 5 // 4 + 1
        else:
            size = self.size
        self.size = max(min(MIN_BATCH_ROWS, self.cap), min(self.cap, size))


def _hash(value: str) -> str:
    return ms._sha(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _chunks(items: list[Any], size: int = 400) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _marks(count: int) -> str:
    return ",".join("?" * count)


def _tables(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]


def _meta_get(db: sqlite3.Connection, key: str) -> str | None:
    try:
        row = db.execute("SELECT value FROM memory_store_meta WHERE key=?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _meta_set(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT INTO memory_store_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def _meta_delete(db: sqlite3.Connection, key: str) -> None:
    db.execute("DELETE FROM memory_store_meta WHERE key=?", (key,))


# --- root access ------------------------------------------------------------------------------------------------

def open_root(owner: str, timeout: float = 5.0):
    """The owner's root store with the engine's own connection rules (host binding, foreign keys). None = no store yet."""
    from .memory_runtime import MemoryRuntime, memory_path
    if not memory_path(owner).is_file():
        return None
    return MemoryRuntime(owner, timeout=timeout)


class SplitLock:
    """Public name (was ``_Lock``). Contract: ``with SplitLock(folder) as free`` is True when this process now holds
    ``<folder>/.split.lock`` (the one mover of this store) and False when another process holds it (answer ``busy``).

    One mover at a time on this machine. A held lock answers ``busy``; an unsupported platform just goes without
    (the move is safe when two run at once, the lock only saves the duplicate work)."""

    def __init__(self, directory: Path):
        self.path = directory / ".split.lock"
        self.handle = None

    def __enter__(self) -> bool:
        try:
            self.handle = open(self.path, "a+")
        except OSError:
            return True
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError):
            if self.handle is not None:
                self.handle.close()
            self.handle = None
            return False
        return True

    def __exit__(self, *_exc: Any) -> None:
        if self.handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                self.handle.close()
            except (OSError, ImportError):
                pass


_Lock = SplitLock  # the old name, the same class


# --- classification ---------------------------------------------------------------------------------------------

class Move(NamedTuple):
    row_id: str
    ref: ms.StoreRef


class Scan(NamedTuple):
    moves: list[Move]
    stuck: Counter
    candidates: int


def _stay_reason(row: Any, kind: str) -> str:
    agent = str(row["agent_id"] or "")
    if kind == ms.SESSION:
        return "session_rows"
    if agent.casefold().startswith("hub:"):
        return "hub_agent"
    if agent.casefold().startswith(("host:", "builtin-agentlas-")) or kind == ms.PERSONAL:
        return "personal"
    return "legacy_shared"


def scan(root_db: sqlite3.Connection, owner: str) -> Scan:
    """Which root rows have somewhere to go, and why the others stay. Reads six columns per candidate row, creates nothing."""
    moves: list[Move] = []
    stuck: Counter = Counter()
    homes: dict[str, Path | None] = {}
    keys: dict[str, str | None] = {}
    candidates = 0
    marks = _marks(len(CANDIDATE_SCOPES))
    #': no line is held back for a translation any more (the worker that read the queue is gone; a held line would wait for ever).
    agents_root = agent_home.agents_root()
    for row in root_db.execute(f"SELECT id,scope,agent_id,project_id,project_path,chat_id FROM memory_entries WHERE scope IN ({marks}) ORDER BY id", CANDIDATE_SCOPES).fetchall():
        candidates += 1
        owned = owner_scope_of(row)
        if owned is None:
            stuck["never_stored"] += 1
            continue
        if owned.kind == ms.AGENT and owned.owner_id:
            if owned.owner_id not in homes:
                found_home = ms.find_agent_home(owned.owner_id)
                # Only a folder under the current agents root is a move target (a stale path from another setup is not).
                homes[owned.owner_id] = found_home if found_home is not None and (found_home.parent == agents_root or found_home == ms._env_agent_home(owned.owner_id)) else None
            home = homes[owned.owner_id]
            if home is None:
                stuck["no_agent_home"] += 1
            else:
                moves.append(Move(row["id"], ms.agent_ref(owner, home, owned.owner_id)))
        elif owned.kind == ms.PROJECT:
            path = row["project_path"]
            if path not in keys:
                found = ms.project_keys(path if isinstance(path, str) and path else None)
                keys[path] = found[0] if found else None
            if keys[path] is None:
                stuck["no_project_key"] += 1
            else:
                moves.append(Move(row["id"], ms.project_ref(owner, keys[path])))
        else:
            stuck[_stay_reason(row, owned.kind)] += 1
    return Scan(moves, stuck, candidates)


def _movable_bytes(root_db: sqlite3.Connection) -> int:
    marks = _marks(len(CANDIDATE_SCOPES))
    row = root_db.execute(
        f"SELECT COALESCE(SUM(LENGTH(content)+COALESCE(LENGTH(embedding_json),0)+LENGTH(evidence_json)+LENGTH(context_json)+200),0) "
        f"FROM memory_entries WHERE scope IN ({marks})", CANDIDATE_SCOPES).fetchone()
    return int(row[0])


def free_bytes(path: Path) -> int:
    """Public name (was ``_free_bytes``). Bytes free on the volume that holds ``path`` (the nearest folder that exists)."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


_free_bytes = free_bytes


# --- copying rows between two stores ------------------------------------------------------------------------------

NATIVE_FORGET_TRIGGERS = ("memory_entry_native_forget", "memory_entry_native_delete")
"""The two triggers that belong to a sub-store's original-wording table (they sit ON ``memory_entries`` and clear a line's wording when the line is
forgotten or deleted). The only triggers a table copy carries: they reference nothing but tables every sub-store has."""


def _ensure_side_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> bool:
    """Make ``table`` and its indexes in ``dst`` from the way ``src`` defines it, so the columns other tools added to the root come along.
    False when ``src`` does not have it.

    Only the table and its indexes are copied. A root also carries objects other tools put on it for the ROOT (the desktop's recall-change
    journal and the triggers that write to it, a view): those are never copied, because they write to or read from tables a sub-store does not
    have (the move stalled on exactly that). The one exception is the pair of forget triggers named in ``NATIVE_FORGET_TRIGGERS``."""
    if table not in _tables(src):
        return False
    if table in _tables(dst):
        return True
    for kind in ("table", "index"):
        for name, sql in src.execute("SELECT name,sql FROM sqlite_master WHERE type=? AND tbl_name=? AND sql IS NOT NULL", (kind, table)):
            dst.execute(sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1) if kind == "table" else sql)
    if table == "memory_entry_native":  # its forget triggers are defined ON memory_entries
        for name, sql in src.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name IN (?,?) AND sql IS NOT NULL", NATIVE_FORGET_TRIGGERS):
            if not dst.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?", (name,)).fetchone():
                dst.execute(sql)
    return True


def copy_rows(src: sqlite3.Connection, dst: sqlite3.Connection, ids: list[str]) -> None:
    """Public name (was ``_copy_rows``). Contract: copy the entries ``ids`` and everything that hangs on them from ``src`` into
    ``dst`` without deleting anything from ``src``; it can run again. The caller commits ``dst``.

    Rows for ``ids`` and everything that hangs on them, into ``dst``, ``INSERT OR IGNORE`` (so it can run again)."""
    for table, key in ROW_TABLES:
        if table != "memory_entries" and not _ensure_side_table(src, dst, table):
            continue
        shared = [column for column in _columns(src, table) if column in set(_columns(dst, table))]
        names = ",".join(shared)
        if table == "memory_entries":
            # The source is the truth for the entry itself: same id in the destination (an earlier interrupted copy, or a
            # row written there) is overwritten, never kept over the source. Children below stay INSERT OR IGNORE.
            # Two things only go one way, so the copy never undoes them: a retired row stays retired (``superseded_at`` is the only
            # such column of this table; a copy that arrives with NULL keeps the destination's value), and a row the destination
            # already forgot (text emptied and retired by ``forget``) is not written over with the words it lost.
            updates = ",".join(f"{c}=COALESCE(excluded.{c},{table}.{c})" if c == "superseded_at" else f"{c}=excluded.{c}" for c in shared if c != key)
            verb = (f"INSERT INTO {table}({names}) VALUES({_marks(len(shared))}) ON CONFLICT({key}) DO UPDATE SET {updates} "
                    f"WHERE NOT ({table}.content='' AND {table}.superseded_at IS NOT NULL)")
        else:
            verb = f"INSERT OR IGNORE INTO {table}({names}) VALUES({_marks(len(shared))})"
        for chunk in _chunks(ids):
            rows = src.execute(f"SELECT {names} FROM {table} WHERE {key} IN ({_marks(len(chunk))})", chunk).fetchall()
            if rows:
                dst.executemany(verb, [tuple(r) for r in rows])
    # Translation jobs of these entries.
    if _ensure_side_table(src, dst, "memory_translation_jobs"):
        shared = [column for column in _columns(src, "memory_translation_jobs") if column in set(_columns(dst, "memory_translation_jobs"))]
        names = ",".join(shared)
        for chunk in _chunks(ids):
            rows = src.execute(f"SELECT {names} FROM memory_translation_jobs WHERE target_kind='memory_entry' AND target_id IN ({_marks(len(chunk))})", chunk).fetchall()
            if rows:
                dst.executemany(f"INSERT OR IGNORE INTO memory_translation_jobs({names}) VALUES({_marks(len(shared))})", [tuple(r) for r in rows])
    # Relation edges whose two ends are both in dst now. 'supersedes' to a row that stays elsewhere becomes an origin link on the
    # newer row; similar_to / contradicts across files are derived values and are not kept.
    if "memory_relation_edges" in _tables(src):
        present = lambda i: dst.execute("SELECT 1 FROM memory_entries WHERE id=?", (i,)).fetchone() is not None  # noqa: E731
        for chunk in _chunks(ids):
            edges = src.execute(f"SELECT * FROM memory_relation_edges WHERE from_memory_id IN ({_marks(len(chunk))}) OR to_memory_id IN ({_marks(len(chunk))})", [*chunk, *chunk]).fetchall()
            for edge in edges:
                if present(edge["from_memory_id"]) and present(edge["to_memory_id"]):
                    columns = [c for c in edge.keys() if c in set(_columns(dst, "memory_relation_edges"))]
                    dst.execute(f"INSERT OR IGNORE INTO memory_relation_edges({','.join(columns)}) VALUES({_marks(len(columns))})", [edge[c] for c in columns])
                elif edge["relation_type"] == "supersedes" and present(edge["from_memory_id"]):
                    dst.execute("INSERT OR IGNORE INTO memory_origin_links(memory_id,source_kind,source_id,source_revision,relation) VALUES(?,'memory',?,'','supersedes')",
                                (edge["from_memory_id"], edge["to_memory_id"]))
    # The ticket that decided each entry stays findable from the entry itself (the root decision's pointer is cleared when the row leaves).
    if "memory_decisions" in _tables(src):
        for chunk in _chunks(ids):
            for ticket, target in src.execute(f"SELECT ticket_id,target_memory_id FROM memory_decisions WHERE target_memory_id IN ({_marks(len(chunk))})", chunk).fetchall():
                dst.execute("INSERT OR IGNORE INTO memory_origin_links(memory_id,source_kind,source_id,source_revision) VALUES(?,'memory-ticket',?,'')", (target, ticket))


_copy_rows = copy_rows


def landed(src: sqlite3.Connection, dst: sqlite3.Connection, ids: list[str]) -> set[str]:
    """Public name (was ``_landed``). Contract: the subset of ``ids`` that may now be deleted from ``src`` because ``dst`` holds the
    same text. Ids whose row in ``dst`` has the same text as in ``src`` and is retired whenever ``src`` is (only those may be deleted
    from ``src``). A row retired only in ``dst`` is still landed (the retirement is kept there, the source copy goes);
    a row ``dst`` already forgot is landed too (the words must not come back). Anything else stays and is a conflict."""
    same: set[str] = set()
    for chunk in _chunks(ids):
        sql = f"SELECT id,content,superseded_at FROM memory_entries WHERE id IN ({_marks(len(chunk))})"
        want = {row[0]: (row[1], row[2]) for row in src.execute(sql, chunk)}
        for row in dst.execute(sql, chunk):
            wanted = want.get(row[0])
            if wanted is None:
                continue
            forgotten = row[1] == "" and row[2] is not None
            if forgotten or (wanted[0] == row[1] and (wanted[1] == row[2] or (wanted[1] is None and row[2] is not None))):
                same.add(row[0])
    return same


_landed = landed


def _keep_supersedes(db: sqlite3.Connection, moving: list[str], together: set[str]) -> None:
    """Rows are about to leave ``db``. A ``supersedes`` edge ends where its older row is deleted (foreign key cascade), so when
    the newer row stays behind in ``db`` it gets the same fact as an origin link (the form every store already reads)."""
    if "memory_relation_edges" not in _tables(db):
        return
    for chunk in _chunks(moving):
        for newer, older in db.execute(
                f"SELECT from_memory_id,to_memory_id FROM memory_relation_edges WHERE relation_type='supersedes' AND to_memory_id IN ({_marks(len(chunk))})", chunk).fetchall():
            if newer in together:
                continue
            db.execute("INSERT OR IGNORE INTO memory_origin_links(memory_id,source_kind,source_id,source_revision,relation) "
                       "SELECT ?,'memory',?,'','supersedes' WHERE EXISTS(SELECT 1 FROM memory_entries WHERE id=?)", (newer, older, newer))


def _with_partners(db: sqlite3.Connection, head: list[Move], by_id: dict[str, ms.StoreRef], cap: int = 2000) -> list[Move]:
    """Rows joined by a relation edge and bound for the same store leave in the same batch, so the edge can be copied
    (it needs both ends in the destination). Bounded; an edge to a row going elsewhere is handled by ``_keep_supersedes``."""
    if "memory_relation_edges" not in _tables(db):
        return head
    chosen = {move.row_id: move for move in head}
    frontier = list(chosen)
    while frontier and len(chosen) < cap:
        found: list[str] = []
        for chunk in _chunks(frontier, 300):
            marks = _marks(len(chunk))
            for a, b in db.execute(f"SELECT from_memory_id,to_memory_id FROM memory_relation_edges WHERE from_memory_id IN ({marks}) OR to_memory_id IN ({marks})", [*chunk, *chunk]):
                for other, mine in ((b, a), (a, b)):
                    ref = by_id.get(other)
                    if other not in chosen and ref is not None and mine in chosen and chosen[mine].ref.path == ref.path:
                        chosen[other] = Move(other, ref)
                        found.append(other)
        frontier = found
    return list(chosen.values())


def _delete_rows(db: sqlite3.Connection, ids: list[str]) -> None:
    tables = _tables(db)
    for chunk in _chunks(ids):
        marks = _marks(len(chunk))
        db.execute(f"DELETE FROM memory_entries WHERE id IN ({marks})", chunk)  # bindings, links, edges, native go with it
        if "memory_projection_outbox" in tables:
            db.execute(f"DELETE FROM memory_projection_outbox WHERE memory_id IN ({marks})", chunk)
        if "memory_translation_jobs" in tables:
            db.execute(f"DELETE FROM memory_translation_jobs WHERE target_kind='memory_entry' AND target_id IN ({marks})", chunk)


# --- one batch --------------------------------------------------------------------------------------------------

class BatchResult(NamedTuple):
    moved: int
    skipped: dict[str, int]       # code -> rows left in the root this time
    failed_ids: set[str]
    blocked: str | None           # disk_full: stop for now
    held: float = 0.0             # seconds the root's write lock was held (from the lock taken to the commit)
    missing: dict[str, int] = {}  # what a store lacked, as "table:<name>" / "column:<name>" -> rows left in the root for it (only for ``store_schema_error``)


def _is_disk_full(error: BaseException) -> bool:
    text = str(error).lower()
    return any(word in text for word in ("full", "i/o error", "enospc", "no space"))


# Why a row stayed in the root this time, and whether asking again can change that without anybody doing anything.
# ``retryable`` is true when at least one of the skip codes of a call is in this set. A code that is not listed is not promised to clear by itself.
RETRYABLE_SKIPS = frozenset({"store_locked", "forget_catchup_withheld", "store_unwritable", "store_unreadable", "agent_home_removed", "conflict", "changed"})

_LOCK_CODES = (5, 6)  # SQLITE_BUSY, SQLITE_LOCKED
_MISSING = re.compile(r"^(?:no such (table|column): (?:[A-Za-z_][A-Za-z0-9_]*\.)?|table [A-Za-z_][A-Za-z0-9_]* has no (column) named )([A-Za-z_][A-Za-z0-9_]{0,63})$")


def classify_store_error(error: BaseException) -> tuple[str, str | None]:
    """``(code, missing)`` for an error a destination store raised while rows were copied into it.

    ``store_locked``: SQLite reported busy or locked (the primary result code, or SQLite's own fixed wording where the Python build does not
    expose the code); asking again can succeed. ``store_schema_error``: the store lacks a table or a column the copy needs; ``missing`` is
    ``"table:<name>"`` or ``"column:<name>"`` (an identifier of at most 64 characters, never a path or a value); asking again cannot succeed.
    ``store_error``: anything else. SQLite gives no structured field for the missing name, so it is read from its fixed ``no such table:`` /
    ``no such column:`` message with a strict pattern; a message that does not match is ``store_error``, never guessed."""
    code = getattr(error, "sqlite_errorcode", None)
    text = str(error).strip()
    if isinstance(code, int) and (code & 0xFF) in _LOCK_CODES:
        return "store_locked", None
    lowered = text.lower()
    if lowered in ("database is locked", "database table is locked") or lowered.endswith("database is busy"):
        return "store_locked", None
    found = _MISSING.match(text)
    if found:
        return "store_schema_error", f"{found.group(1) or found.group(2)}:{found.group(3)}"
    return "store_error", None


def _move_batch(rt: Any, owner: str, moves: list[Move]) -> BatchResult:
    """Move up to one batch. The root's write lock is held from the read to the delete, so no writer changes a row
    between being copied and being removed, and no forget can slip in between."""
    root = rt.db
    # Reads go through a plain connection: the engine's guarded connection checks the host binding on every row it
    # returns, which costs more than the copy. The write lock held on ``root`` below keeps this reader's view exact.
    reader = sqlite3.connect(str(rt.path), timeout=5.0)
    reader.row_factory = sqlite3.Row
    skipped: Counter = Counter()
    missing: Counter = Counter()
    failed: set[str] = set()
    moved_ids: list[str] = []
    wanted = {move.row_id: move.ref for move in moves}
    held = 0.0
    try:
        root.execute("BEGIN IMMEDIATE")
        locked_at = time.monotonic()
        try:
            groups: dict[Path, tuple[ms.StoreRef, list[str]]] = {}
            for chunk in _chunks(list(wanted)):
                for row in reader.execute(f"SELECT id,scope,agent_id,project_id,project_path,chat_id FROM memory_entries WHERE id IN ({_marks(len(chunk))})", chunk).fetchall():
                    # Classified again under the lock: a row changed since the scan goes where it belongs now, or stays.
                    owned = owner_scope_of(row)
                    ref = wanted[row["id"]]
                    if owned is None or owned.kind not in (ms.AGENT, ms.PROJECT):
                        skipped["changed"] += 1
                        failed.add(row["id"])
                        continue
                    groups.setdefault(ref.path, (ref, []))[1].append(row["id"])
            for ref, ids in groups.values():
                existed = ref.path.is_file()  # a store this call creates and then abandons may be removed; an existing one never
                sdb, code = ms.open_store_for_write(ref, owner, root)
                if sdb is None:
                    skipped[code or "store_unwritable"] += len(ids)
                    failed.update(ids)
                    continue
                try:
                    sdb.execute("BEGIN IMMEDIATE")
                    copy_rows(reader, sdb, ids)
                    sdb.commit()
                    present = landed(reader, sdb, ids)
                except sqlite3.DatabaseError as error:  # one store's failure is that store's skip, whatever its kind (lock, schema, integrity)
                    sdb.rollback()
                    if _is_disk_full(error):
                        root.rollback()
                        return BatchResult(0, dict(skipped), failed, "disk_full")
                    code, lacks = classify_store_error(error)
                    skipped[code] += len(ids)
                    if lacks:
                        missing[lacks] += len(ids)
                    failed.update(ids)
                    continue
                finally:
                    sdb.close()
                if ref.kind == ms.AGENT and not (ms._local_folder_of(ref) / agent_home.AGENT_OWNER_FILE).is_file():
                    # The marker is not there right now (deleted, replaced by a sync tool). The store may hold rows from earlier
                    # batches that are no longer in the root, so it is never deleted here (if the folder is really gone, the
                    # folder's removal takes it); only a store this very call created, still empty of earlier work, may go.
                    if not existed:
                        for name in ("memory.sqlite", "memory.sqlite-journal"):
                            try:
                                (ref.path.parent / name).unlink()
                            except OSError:
                                pass
                    skipped["agent_home_removed"] += len(ids)
                    failed.update(ids)
                    continue
                landed_ids = [i for i in ids if i in present]
                failed.update(set(ids) - set(landed_ids))
                if len(landed_ids) != len(ids):
                    skipped["conflict"] += len(ids) - len(landed_ids)
                moved_ids.extend(landed_ids)
            if moved_ids:
                _keep_supersedes(root, moved_ids, set(moved_ids))
                _delete_rows(root, moved_ids)
            root.commit()
            held = time.monotonic() - locked_at
        except BaseException:
            root.rollback()
            raise
    except sqlite3.OperationalError as error:
        if _is_disk_full(error):
            return BatchResult(0, dict(skipped), failed, "disk_full")
        raise
    finally:
        reader.close()
    return BatchResult(len(moved_ids), dict(skipped), failed, None, held, dict(missing))


# --- start / step / status -------------------------------------------------------------------------------------------

def _layout_value(root_db: sqlite3.Connection) -> str | None:
    return _meta_get(root_db, ms.LAYOUT_KEY)


def status(owner: str) -> dict[str, Any]:
    rt = open_root(owner)
    if rt is None:
        return {"state": "no_store"}
    try:
        value = _layout_value(rt.db)
        layout = ms.layout_of(rt.db)
        result: dict[str, Any] = {"state": "ok", "layout": layout, "layoutValue": value}
        found = scan(rt.db, owner)
        by_store = Counter(move.ref.kind for move in found.moves)
        result.update(movable=len(found.moves), byStore=dict(by_store), stuck=dict(found.stuck), candidates=found.candidates,
                      swept=_meta_get(rt.db, SWEPT_KEY) == str(ms.store_revision(rt.db)))
        stores, more = ms.recent_stores(owner, [], limit=10 ** 9)
        result["stores"] = dict(Counter(ref.kind for ref in stores))
        return result
    finally:
        rt.close()


def _inspect_copy(label: str, root: Path | None, reason: str | None = None) -> dict[str, Any]:
    if root is None:
        return {"host": label, "state": "unconfirmed", "reason": reason or "path_unknown"}
    for relative in ("agentlas_cloud/capabilities.json", "capabilities.json"):
        candidate = root / relative
        try:
            if candidate.is_file():
                payload = json.loads(candidate.read_text(encoding="utf-8").lstrip("﻿"))
                layout = payload.get("memory_layout") if isinstance(payload, dict) else None
                if isinstance(layout, str) and layout.strip().isdigit():
                    layout = int(layout.strip())
                elif isinstance(layout, float) and layout.is_integer():
                    layout = int(layout)
                if isinstance(layout, int) and not isinstance(layout, bool):
                    return {"host": label, "path": str(root), "state": "declared" if layout >= MIN_ENGINE_LAYOUT_CAPABILITY else "old", "memoryLayout": layout}
                return {"host": label, "path": str(root), "state": "unconfirmed", "reason": "capabilities_unreadable"}
        except (OSError, ValueError):
            return {"host": label, "path": str(root), "state": "unconfirmed", "reason": "capabilities_unreadable"}
    try:
        if not root.is_dir() or not (root / "agentlas_cloud").is_dir():
            return {"host": label, "path": str(root), "state": "unconfirmed", "reason": "copy_not_found"}
    except OSError:
        return {"host": label, "path": str(root), "state": "unconfirmed", "reason": "copy_unreadable"}
    return {"host": label, "path": str(root), "state": "old", "memoryLayout": 0}  # an engine that declares nothing predates the move


def _newest_version_folder(plugin: Path) -> Path | None:
    """The highest `<major>.<minor>.<patch>` folder of one cached plugin (Codex keeps the older ones next to it), or None."""
    best: tuple[tuple[int, int, int], Path] | None = None
    for child in plugin.iterdir():
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", child.name)
        if match and child.is_dir() and not child.is_symlink():
            key = (int(match[1]), int(match[2]), int(match[3]))
            if best is None or key > best[0]:
                best = (key, child)
    return best[1] if best else None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8").lstrip("﻿"))


def engine_inventory(extra_roots: Iterable[str | os.PathLike[str]] = ()) -> dict[str, Any]:
    """Every engine copy on this computer that can run a memory hook, and whether it declares ``memory_layout >= MIN_ENGINE_LAYOUT_CAPABILITY``.

    Sources: the engine running this call, the managed runtime (``<agentlas home>/runtime/current``), the Claude
    plugin installs that are *active* (``~/.claude/plugins/installed_plugins.json``; old versions left in the cache are
    not counted), the Codex plugin version the runtime marker says is active, and any roots the caller names (the
    desktop passes its bundled engine). A host whose list cannot be read, or whose format this code does not know, is
    ``unconfirmed``. Reads only; a host that is not installed contributes nothing. Agentlas 2.0: the count is a notice - ``start`` no longer holds the
    move for it (a copy below the number reads and writes as it always did, and the structure conversion raises the store's own version marker, which
    makes such a copy step aside by itself - §4.2); ``belowCurrent`` lists the copies that do not declare ``CURRENT_ENGINE_CAPABILITY``."""
    copies: list[dict[str, Any]] = [_inspect_copy("invoker", Path(__file__).resolve().parent.parent)]
    home = agent_home.agentlas_home()
    current = home / "runtime" / "current"
    if current.exists() or current.is_symlink():
        try:
            copies.append(_inspect_copy("runtime", current.resolve()))
        except OSError:
            copies.append(_inspect_copy("runtime", None, "runtime_unreadable"))
    try:
        user = Path.home()
    except (RuntimeError, KeyError, OSError):
        user = Path(os.path.expanduser("~"))
    def host_homes(variable: str, default: Path) -> list[Path]:
        """The folder the variable names and the default one, each once: a plugin can sit in either (the updater and the desktop follow the variable)."""
        found: list[Path] = []
        for candidate in (os.environ.get(variable), default):
            if candidate and all(Path(candidate).resolve() != other.resolve() for other in found):
                found.append(Path(candidate))
        return found

    for claude_home in host_homes("CLAUDE_CONFIG_DIR", user / ".claude"):
        installed = claude_home / "plugins" / "installed_plugins.json"
        if installed.is_file():
            try:
                plugins = _read_json(installed).get("plugins")
                if not isinstance(plugins, dict):
                    raise ValueError("format")
                seen = False
                for name, entries in plugins.items():
                    if "agentlas-core-engine" not in str(name):
                        continue
                    for entry in entries if isinstance(entries, list) else []:
                        seen = True
                        where = entry.get("installPath") if isinstance(entry, dict) else None
                        copies.append(_inspect_copy("claude", Path(where) if isinstance(where, str) and where else None, "install_path_missing"))
                if not seen:
                    pass  # Claude is installed but the engine is not one of its plugins
            except (OSError, ValueError, AttributeError):
                copies.append({"host": "claude", "state": "unconfirmed", "reason": "installed_plugins_unreadable"})
    for codex_home in host_homes("CODEX_HOME", user / ".codex"):
        codex = codex_home / "plugins" / "cache" / "agentlas-core-engine"
        if codex.is_dir():
            try:
                marker = _read_json(home / "runtime" / "host-plugin-activation.json")
                release: str | None = str(marker["hosts"]["codex"]["release"]).lstrip("v")
            except (OSError, ValueError, KeyError, TypeError):
                release = None   # a plugin added with `codex plugin add` and no managed runtime: nothing records which version is active
            try:
                versions = [path for plugin in sorted(codex.iterdir()) if plugin.is_dir() for path in [plugin / release] if path.is_dir()] if release else []
                if not versions:
                    # No record, or it names a version that is not in the cache: Codex loads the newest version it holds, so that one is read.
                    # Without this a plugin-only install stayed "unconfirmed" for good, even after the person updated it.
                    versions = [newest for plugin in sorted(codex.iterdir()) if plugin.is_dir() for newest in [_newest_version_folder(plugin)] if newest is not None]
                if not versions:
                    copies.append({"host": "codex", "state": "unconfirmed", "reason": "activation_unreadable" if release is None else "active_version_not_found"})
                copies.extend(_inspect_copy("codex", path) for path in versions)
            except OSError:
                copies.append({"host": "codex", "state": "unconfirmed", "reason": "activation_unreadable"})
    for extra in extra_roots:
        copies.append(_inspect_copy("extra", Path(extra)))
    unconfirmed = [c for c in copies if c["state"] != "declared"]
    behind = [c for c in copies if not (isinstance(c.get("memoryLayout"), int) and c["memoryLayout"] >= CURRENT_ENGINE_CAPABILITY)]
    return {"copies": copies, "allDeclared": not unconfirmed, "notDeclared": [{k: v for k, v in c.items() if k != "memoryLayout"} for c in unconfirmed],
            # Agentlas 2.0 §4.2: a notice, never a door. Host labels, states and numbers only (no path), what a status line can show.
            "belowCurrent": [{k: v for k, v in c.items() if k != "path"} for c in behind], "currentCapability": CURRENT_ENGINE_CAPABILITY}


def start(owner: str, *, homes_ready: bool, extra_engines: Iterable[str] = ()) -> dict[str, Any]:
    """Set the switch if every condition holds; otherwise change nothing and say which conditions failed.

    ``homes_ready`` comes from the desktop (it moved the agent folders); the rest is checked here: the root passes a quick integrity
    check and there is room for the move. Engine copies that do not declare the layout no longer hold the move (Agentlas 2.0, §4.2:
    ``engines_not_confirmed`` is a notice, not a door); they come back as ``notDeclared`` on the ``started`` answer so the caller can say which plugin to
    update. Already on is not an error; a layout value this engine does not know is left alone."""
    rt = open_root(owner)
    if rt is None:
        return {"state": "no_store"}
    try:
        value = _layout_value(rt.db)
        if value == ms.SPLIT_LAYOUT:
            return {"state": "already"}
        if value not in (None, "", PAUSED_LAYOUT):
            return {"state": "blocked", "reasons": ["layout_unknown"], "layoutValue": value}
        reasons: list[str] = []
        if not homes_ready:
            reasons.append("homes_not_ready")
        inventory = engine_inventory(extra_engines)
        try:
            if rt.db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                reasons.append("quick_check_failed")
        except sqlite3.Error:
            reasons.append("quick_check_failed")
        need = max(MIN_FREE_BYTES, 2 * _movable_bytes(rt.db))
        if free_bytes(rt.path) < need:
            reasons.append("disk_low")
        if reasons:
            return {"state": "blocked", "reasons": reasons, **({"notDeclared": inventory["notDeclared"]} if inventory["notDeclared"] else {}), "needBytes": need}
        rt.db.execute("BEGIN IMMEDIATE")
        try:
            _meta_set(rt.db, ms.LAYOUT_KEY, ms.SPLIT_LAYOUT)
            ms.mark_layout_switch_epoch(rt.db)  # forgets made so far stay scoped; the same transaction as the layout value
            _meta_delete(rt.db, SWEPT_KEY)
            rt.db.commit()
        except BaseException:
            rt.db.rollback()
            raise
        return {"state": "started", **({"notDeclared": inventory["notDeclared"]} if inventory["notDeclared"] else {})}
    finally:
        rt.close()


def _credit_linked_turns(db: sqlite3.Connection) -> None:
    """A turn whose counters say it wrote nothing but that a memory row names as its origin did write: set its ``written_count`` to 1.

    The cleanup of empty turns keeps such a turn only through that origin link (``empty_turn_condition``), and the link lives with the
    memory row, which leaves the root when it moves to its own store. Writing the fact into the counter makes the turn safe wherever
    the row goes. Runs under the move's lock, before the first row moves; nothing changes (no page is written) when no turn is in that
    state, and the counter of a turn that really wrote nothing is never touched."""
    tables = _tables(db)
    if not {"memory_tickets", "memory_origin_links"} <= tables:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("UPDATE memory_tickets SET written_count=1 WHERE written_count=0 AND deduped_count=0 AND ticket_id IN "
                   "(SELECT source_id FROM memory_origin_links WHERE source_kind IN ('ticket','memory-ticket') AND source_id IS NOT NULL)")
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _finalize(rt: Any, owner: str) -> None:
    """The move is complete for now: the per-agent and per-project copies under views/ are removed, and the ``MEMORY.md``
    files earlier engines left beside agent stores are deleted (nothing reads them)."""
    from .memory_views import process_memory_views
    try:
        for _ in range(4):
            if not process_memory_views(rt.db, rt.path, owner).get("moreWork"):
                break
    except Exception:  # noqa: BLE001 - views are disposable
        pass
    views = rt.path.parent / "views"
    for kind in ("agents", "projects"):
        base = views / kind
        try:
            for child in base.iterdir():
                if child.is_dir() and not any(child.iterdir()):
                    child.rmdir()
            if not any(base.iterdir()):
                base.rmdir()
        except OSError:
            pass
    stores, _more = ms.recent_stores(owner, [], limit=10 ** 9)
    for ref in stores:
        if ref.kind == ms.AGENT:
            ms.remove_agent_memory_md(ref)


def _volumes_short(root_path: Path, targets: Iterable[Path], need: int) -> bool:
    """True when the root's volume, or the volume of any destination store (agent folders may sit on another disk), has
    less than ``need`` bytes free."""
    seen: dict[int, Path] = {}
    for path in (root_path, *targets):
        probe = path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            seen.setdefault(probe.stat().st_dev, probe)
        except OSError:
            continue
    return any(free_bytes(probe) < need for probe in seen.values())


VACUUM_MIN_FREE_PAGES_BYTES = 32 * 1024 * 1024


def vacuum_verdict(rt: Any) -> dict[str, Any]:
    """Whether one VACUUM of the root is worth it now. Contract: ``{"worth": bool, "reason": "worth"|"small"|"disk_low", ...}``; the sizes
    are the file's own (page count, free pages) and the bar they are held to, never an estimate of what a VACUUM would give back.

    Worth it = the free pages are at least ``VACUUM_MIN_FREE_PAGES_BYTES`` and a quarter of the file, and the volume has room for the copy
    a VACUUM makes (the live data twice plus 64 MB)."""
    db = rt.db
    page = int(db.execute("PRAGMA page_size").fetchone()[0])
    total = int(db.execute("PRAGMA page_count").fetchone()[0]) * page
    free = int(db.execute("PRAGMA freelist_count").fetchone()[0]) * page
    bar = max(VACUUM_MIN_FREE_PAGES_BYTES, total // 4)
    verdict = {"worth": False, "reason": "small", "fileBytes": total, "freePageBytes": free, "thresholdBytes": bar}
    if free < bar:
        return verdict
    if free_bytes(rt.path) < (total - free) * 2 + 64 * 1024 * 1024:
        return {**verdict, "reason": "disk_low"}
    return {**verdict, "worth": True, "reason": "worth"}


class _TempBeside:
    """``with _TempBeside(db, folder) as placed``: for the length of the block the connection's temporary files (the copy a VACUUM makes) go
    into ``folder``, which is on the store's own volume, instead of the operating system's temporary folder (a RAM disk on some Linux machines).

    ``PRAGMA temp_store_directory`` does it; an environment variable such as ``SQLITE_TMPDIR`` is read when SQLite starts and does nothing
    from here. ``placed`` is False, and nothing is changed, when this SQLite build cannot honour the pragma: it is compiled without it (the pragma
    is deprecated and can be omitted), always keeps temporary data in memory (``TEMP_STORE=3``), or reads back something other than the folder
    that was set. The caller then skips the VACUUM with ``temp_dir_unsupported`` rather than let it fill another volume or the memory. The
    pragma is process-wide, so the previous value (normally none) is put back at the end."""

    def __init__(self, db: sqlite3.Connection, folder: Path):
        self.db, self.folder = db, str(folder)
        self.previous: tuple[str, int | None] | None = None

    def __enter__(self) -> bool:
        db = self.db
        try:
            if any("TEMP_STORE=3" in str(row[0]) for row in db.execute("PRAGMA compile_options")):
                return False
            row = db.execute("PRAGMA temp_store_directory").fetchone()
            was = str(row[0]) if row and row[0] else ""
            kept = db.execute("PRAGMA temp_store").fetchone()
            quoted = self.folder.replace("'", "''")
            db.execute(f"PRAGMA temp_store_directory='{quoted}'")
            got = db.execute("PRAGMA temp_store_directory").fetchone()
            if not got or str(got[0]) != self.folder:
                self._restore(was, None)
                return False
            self.previous = (was, int(kept[0]) if kept else None)
            db.execute("PRAGMA temp_store=FILE")
            return True
        except sqlite3.Error:
            return False

    def _restore(self, was: str, store: int | None) -> None:
        try:
            self.db.execute("PRAGMA temp_store_directory='" + was.replace("'", "''") + "'")
            if store is not None:
                self.db.execute(f"PRAGMA temp_store={int(store)}")
        except sqlite3.Error:
            pass

    def __exit__(self, *_exc: Any) -> None:
        if self.previous is not None:
            self._restore(*self.previous)


def vacuum_root(owner: str, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """The one VACUUM of the root, when ``vacuum_verdict`` says it is worth it (the desktop calls it as the app ends, with the services stopped).

    Always answers with a state, never raises: ``no_store``; ``busy`` (another mover holds the lock, a writer or a reader holds the file right
    now); ``skipped`` with ``reason`` ``small`` / ``disk_low`` / ``timeout`` / ``temp_dir_unsupported`` (this SQLite build cannot put the VACUUM's
    temporary copy beside the store) / a machine code of whatever else went wrong (nothing changed, and NO number is reported: a file that
    did not shrink has nothing to tell); ``done`` with ``reclaimedBytes`` = the file's size before minus after, measured, not estimated.

    ``timeout_seconds`` is checked while the VACUUM runs, and a VACUUM past it is rolled back whole, but SQLite only checks it while it
    builds the copy: the last stage, writing the copy back, cannot be interrupted, so a call can outlast its timeout by about as long as
    that stage takes (under a second at 200 000 rows). Killing the process then is safe: the next open rolls the journal back.

    The VACUUM's temporary file goes into the store's own folder (``_TempBeside``), and the free-space check (``vacuum_verdict``) looks at
    that same volume. The answer carries no path."""
    try:
        rt = open_root(owner)
    except (sqlite3.Error, OSError, ValueError) as error:
        return _vacuum_refused(error)
    if rt is None:
        return {"state": "no_store"}
    try:
        with SplitLock(rt.path.parent) as free:
            if not free:
                return {"state": "busy"}
            verdict = vacuum_verdict(rt)
            if not verdict["worth"]:
                return {"state": "skipped", "reason": verdict["reason"]}
            db = rt.db
            if db.in_transaction:
                db.commit()
            waited = int(db.execute("PRAGMA busy_timeout").fetchone()[0])
            deadline = time.monotonic() + max(0.0, timeout_seconds)
            try:
                with _TempBeside(db, rt.path.parent) as placed:
                    if not placed:
                        return {"state": "skipped", "reason": "temp_dir_unsupported"}
                    db.execute("PRAGMA busy_timeout=0")
                    db.execute("BEGIN IMMEDIATE")  # a writer is active right now: do not start
                    db.rollback()
                    db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
                    db.execute("PRAGMA auto_vacuum=INCREMENTAL")
                    db.execute("VACUUM")
            except sqlite3.Error as error:
                if "interrupt" in str(error).lower():
                    return {"state": "skipped", "reason": "timeout"}
                return _vacuum_refused(error)
            finally:
                try:
                    db.set_progress_handler(None, 0)
                    db.execute(f"PRAGMA busy_timeout={waited}")
                except sqlite3.Error:
                    pass
            after = int(db.execute("PRAGMA page_count").fetchone()[0]) * int(db.execute("PRAGMA page_size").fetchone()[0])
            return {"state": "done", "reclaimedBytes": max(0, verdict["fileBytes"] - after)}
    except (sqlite3.Error, OSError, ValueError) as error:
        return _vacuum_refused(error)
    finally:
        rt.close()


def _vacuum_refused(error: BaseException) -> dict[str, Any]:
    """``busy`` for a file somebody else holds, else ``skipped`` with a machine code; never the message (it can hold a path)."""
    from .first_run import _code
    code = _code(error)
    return {"state": "busy"} if code == "locked" else {"state": "skipped", "reason": code}


def _vacuum_if_worth(rt: Any) -> str:
    """One VACUUM of the root when the move is complete and a large part of the file is free pages.

    VACUUM locks the whole file for as long as it runs (about 1.3 s at 200 000 rows), so it starts only when nobody else holds
    the file: it checks for a writer and then asks for the lock with a zero wait, instead of queueing behind one and holding
    the file half locked. When it cannot start, or the saving is small, or the disk is short, it returns ``skipped:...`` and
    nothing changes; the next ``step`` that ends in ``done``, ``partial`` or ``idle`` looks again (each look is three header
    reads). A hook that writes during the VACUUM waits for it (``queue_hook_summary``). Never raises."""
    try:
        db = rt.db
        page = int(db.execute("PRAGMA page_size").fetchone()[0])
        total = int(db.execute("PRAGMA page_count").fetchone()[0]) * page
        free = int(db.execute("PRAGMA freelist_count").fetchone()[0]) * page
        if free < max(VACUUM_MIN_FREE_PAGES_BYTES, total // 4):
            return "skipped:small"
        if free_bytes(rt.path) < (total - free) * 2 + 64 * 1024 * 1024:
            return "skipped:disk_low"
        if db.in_transaction:
            db.commit()
        waited = int(db.execute("PRAGMA busy_timeout").fetchone()[0])
        try:
            with _TempBeside(db, rt.path.parent) as placed:  # the copy goes beside the store, on the volume that was checked above
                if not placed:
                    return "skipped:temp_dir_unsupported"
                db.execute("PRAGMA busy_timeout=0")
                db.execute("BEGIN IMMEDIATE")  # a writer is active right now: do not start
                db.rollback()
                db.execute("PRAGMA auto_vacuum=INCREMENTAL")  # takes effect with this VACUUM; later deletes are reclaimed in steps
                db.execute("VACUUM")
        finally:
            db.execute(f"PRAGMA busy_timeout={waited}")
        return f"done:{(free) // (1024 * 1024)}MB"
    except (sqlite3.Error, OSError):
        return "skipped:busy"


def step(owner: str, *, max_batches: int = 50, budget_seconds: float | None = 2.0, rescan: bool = False, batch_rows: int = BATCH_ROWS,
         pause: float = PAUSE_SECONDS, progress: Callable[[dict[str, Any]], None] | None = None, vacuum: bool = True) -> dict[str, Any]:
    """Move up to ``max_batches`` batches or ``budget_seconds`` of work, whichever ends first, then report.

    The first batch always runs, whatever the budget: the budget is checked after a batch, so a call moves at least one batch of rows when
    there is something to move, and a store that is slow to read (a look at 250 000 rows can take longer than 2 seconds) still gets
    somewhere with every call. ``budget_seconds=None`` (the command line's ``--budget-seconds 0``) is no time limit; ``max_batches`` still bounds the call.

    ``state``: ``off`` (switch not on), ``busy`` (another mover runs), ``blocked`` (``reason``), ``idle`` (nothing
    changed since the last complete sweep), ``moved`` (more remains), ``done`` (nothing movable is left; ``stuck`` counts
    what stays in the root and why). Safe to call again at any time and from any number of callers.

    ``vacuum=False`` never VACUUMs (the desktop passes it while the app is running and calls ``vacuum_root`` as it ends)."""
    started = time.monotonic()
    rt = open_root(owner)
    if rt is None:
        return {"state": "no_store"}
    try:
        value = _layout_value(rt.db)
        if value != ms.SPLIT_LAYOUT:
            return {"state": "off", "layoutValue": value}
        with SplitLock(rt.path.parent) as free:
            if not free:
                return {"state": "busy"}
            rt.db.execute("PRAGMA secure_delete=ON")  # rows that leave the root do not stay readable in its free pages
            revision = ms.store_revision(rt.db)
            swept_before = _meta_get(rt.db, SWEPT_KEY)
            if not rescan and swept_before == str(revision):
                idle: dict[str, Any] = {"state": "idle", "moved": 0}
                if vacuum:
                    vacuumed = _vacuum_if_worth(rt)  # a VACUUM that was skipped earlier gets its next chance here
                    if vacuumed != "skipped:small":
                        idle["vacuum"] = vacuumed
                return idle
            _credit_linked_turns(rt.db)  # before any row, and so any origin link, leaves the root
            found = scan(rt.db, owner)
            moves = sorted(found.moves, key=lambda move: (str(move.ref.path), move.row_id))  # a batch then touches few stores
            if moves:
                need = max(MIN_FREE_BYTES, 2 * _movable_bytes(rt.db))
                if _volumes_short(rt.path, {move.ref.path for move in moves}, need):
                    return {"state": "blocked", "reason": "disk_low", "needBytes": need, "remaining": len(moves), "stuck": dict(found.stuck)}
            moved_total, batches = 0, 0
            pacer = BatchPacer(batch_rows)  # ``batch_rows`` is the ceiling; the size follows how long the last batch held the root's write lock
            blocked: str | None = None
            skipped: Counter = Counter()
            missing: Counter = Counter()
            failed: set[str] = set()
            while moves and batches < max_batches and (batches == 0 or budget_seconds is None or time.monotonic() - started < budget_seconds):
                head = [move for move in moves if move.row_id not in failed][:pacer.size]
                if not head:
                    break
                by_id = {move.row_id: move.ref for move in moves if move.row_id not in failed}
                head = [move for move in _with_partners(rt.db, head, by_id, cap=max(2 * pacer.size, MIN_BATCH_ROWS)) if move.row_id not in failed]
                result = _move_batch(rt, owner, head)
                pacer.took(result.held, len(head))
                batches += 1
                moved_total += result.moved
                failed |= result.failed_ids
                skipped.update(result.skipped)
                missing.update(result.missing)
                done_ids = {move.row_id for move in head} - result.failed_ids
                moves = [move for move in moves if move.row_id not in done_ids]
                if progress:
                    progress({"event": "batch", "moved": result.moved, "movedTotal": moved_total, "remaining": len([m for m in moves if m.row_id not in failed])})
                if result.blocked:
                    blocked = result.blocked
                    break
                if moves:
                    time.sleep(pause)
            left = [move for move in moves if move.row_id not in failed]
            report: dict[str, Any] = {"moved": moved_total, "batches": batches, "remaining": len(left), "stuck": dict(found.stuck),
                                      "skipped": dict(skipped), "elapsedMs": int((time.monotonic() - started) * 1000)}
            if skipped:
                # Added only when something was skipped, so an answer of a move that went through is what it was. ``retryable``: asking again
                # later can change at least one of the reasons; false = every reason needs something to be fixed first.
                report["retryable"] = any(code in RETRYABLE_SKIPS for code in skipped)
                if missing:
                    report["skippedMissing"] = dict(missing)
            if blocked:
                return {"state": "blocked", "reason": blocked, **report}
            if left:
                return {"state": "moved", **report}
            # Nothing movable is left. Sweep once more from the current state before declaring it complete; the revision
            # read first is the one recorded, so any row that appears meanwhile makes the next call look again.
            again = scan(rt.db, owner)
            retry = [move for move in again.moves if move.row_id not in failed]
            if retry:
                return {"state": "moved", **{**report, "remaining": len(retry), "stuck": dict(again.stuck)}}
            _finalize(rt, owner)
            if swept_before is not None and moved_total:
                # Rows that reached the root after an earlier complete sweep: a window or session still on an older engine.
                report["lateRows"] = moved_total
            if failed:
                # Not everything moved. This is not "done": the count and the reasons are what the app shows.
                if vacuum:
                    report["vacuum"] = _vacuum_if_worth(rt)
                return {"state": "partial", **{**report, "left": len(failed), "reasons": dict(skipped), "stuck": dict(again.stuck)}}
            if not failed:
                # Recorded revision = the one read before the last look, so a row that appears meanwhile makes the next call look again.
                seen = ms.store_revision(rt.db)
                last = scan(rt.db, owner)
                if not last.moves:
                    rt.db.execute("BEGIN IMMEDIATE")
                    _meta_set(rt.db, SWEPT_KEY, str(seen))
                    rt.db.commit()
            if vacuum:
                report["vacuum"] = _vacuum_if_worth(rt)
            return {"state": "done", **{**report, "stuck": dict(again.stuck)}}
    finally:
        rt.close()


# --- turning it off ---------------------------------------------------------------------------------------------

def revert(owner: str, *, merge_back: bool = False, batch_rows: int = BATCH_ROWS, pause: float = PAUSE_SECONDS) -> dict[str, Any]:
    """Switch the split off. New rows go to the root again at once and nothing is moved any more; readers still read every
    store (the layout reads as ``split-paused``). With ``merge_back`` the rows in every store are moved back into the root
    in batches (same rules as the move) and, when all stores are empty, their files are removed and the key is cleared.
    Safe to repeat; a crash leaves rows in at least one place."""
    rt = open_root(owner)
    if rt is None:
        return {"state": "no_store"}
    try:
        value = _layout_value(rt.db)
        if value is None or value == "":
            return {"state": "off"}
        if value == ms.SPLIT_LAYOUT:
            rt.db.execute("BEGIN IMMEDIATE")
            _meta_set(rt.db, ms.LAYOUT_KEY, PAUSED_LAYOUT)
            _meta_delete(rt.db, SWEPT_KEY)
            rt.db.commit()
        elif value != PAUSED_LAYOUT:
            return {"state": "blocked", "reasons": ["layout_unknown"], "layoutValue": value}
        if not merge_back:
            return {"state": "paused"}
        with SplitLock(rt.path.parent) as free:
            if not free:
                return {"state": "busy"}
            moved = 0
            left: list[str] = []
            stores, _more = ms.recent_stores(owner, [], limit=10 ** 9)
            for ref in stores:
                opened, code = ms.open_store(ref, owner, rt.db)
                if opened is None:
                    # Another account's store and a store that is not there are not ours to merge. Anything else is a store of
                    # this account that could not be opened: its rows stay where they are and the layout key stays too.
                    if code not in ("owner_mismatch", "store_absent"):
                        left.append(f"{ref.kind}:{code}")
                    continue
                opened.db.close()
                while True:
                    src = sqlite3.connect(str(ref.path), timeout=0.5)
                    src.row_factory = sqlite3.Row
                    src.execute("PRAGMA foreign_keys=ON")
                    try:
                        ids = [r[0] for r in src.execute("SELECT id FROM memory_entries ORDER BY id LIMIT ?", (batch_rows,))]
                        if not ids:
                            break
                        rt.db.execute("BEGIN IMMEDIATE")
                        try:
                            copy_rows(src, rt.db, ids)
                            landed_ids = [i for i in ids if i in landed(src, rt.db, ids)]
                            rt.db.commit()
                        except BaseException:
                            rt.db.rollback()
                            raise
                        if len(landed_ids) != len(ids):
                            return {"state": "partial", "reason": "merge_incomplete", "left": left + [f"{ref.kind}:merge_incomplete"], "moved": moved}
                        src.execute("BEGIN IMMEDIATE")
                        _delete_rows(src, landed_ids)
                        src.commit()
                        moved += len(landed_ids)
                    finally:
                        src.close()
                    time.sleep(pause)
                _remove_store_files(ref)
            if left:
                # The key stays: with it gone the readers would stop looking in the stores that could not be merged.
                return {"state": "partial", "left": left, "moved": moved}
            rt.db.execute("BEGIN IMMEDIATE")
            _meta_delete(rt.db, ms.LAYOUT_KEY)
            _meta_delete(rt.db, SWEPT_KEY)
            rt.db.commit()
            return {"state": "merged", "moved": moved}
    finally:
        rt.close()


def _remove_store_files(ref: ms.StoreRef) -> None:
    """An emptied store's own files. An agent store keeps its folder (it belongs to the agent); a project store's folder goes."""
    folder = ref.path.parent
    own = (ms.STORE_FILE, ms.STORE_FILE + "-journal", ms.STORE_FILE + "-wal", ms.STORE_FILE + "-shm")
    for name in os.listdir(folder) if folder.is_dir() else []:
        if name not in own and name != "MEMORY.md":  # other files in the folder (a project's code index) are not ours
            continue
        try:
            (folder / name).unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
        if ref.kind == ms.AGENT:
            folder.parent.rmdir()  # .agentlas-local/memory when it holds nothing else
    except OSError:
        pass


# --- forgetting --------------------------------------------------------------------------------------------------

def owner_keys(row: Any) -> list[str]:
    """Public name (was ``_owner_keys``). Contract: the revocation owner keys of one memory row (``scope``, ``project_path``,
    ``project_id``, ``agent_id``, ``chat_id``); the first is the canonical one. One implementation, ``memory_stores.row_owner_keys``."""
    return ms.row_owner_keys(row)


_owner_keys = owner_keys

RECALL_INDEX = "recall-index.sqlite"


def drop_recall_index(folder: Path) -> bool:
    """Public name (was ``_drop_recall_index``). Contract: delete the search index beside the store in ``folder``; True when none is left.

    Delete the search index (``recall-index.sqlite`` and its journal files) that sits beside a store. It is rebuilt from the
    store by the next search, so removing the file is the whole repair: a delete inside it would leave the words in its free
    pages. True when nothing of it is left."""
    clean = True
    for suffix in ("", "-wal", "-shm", "-journal"):
        target = folder / (RECALL_INDEX + suffix)
        try:
            if target.is_symlink() or target.exists():
                target.unlink()
        except OSError:
            clean = False
    try:  # a search that runs in this process must not serve the rows it cached from the deleted file
        from . import memory_recall
        with memory_recall._CACHE_LOCK:
            memory_recall._CACHE.pop(str(folder / RECALL_INDEX), None)
    except Exception:  # noqa: BLE001 - the cache is an optimisation
        pass
    return clean and not (folder / RECALL_INDEX).exists() and not (folder / RECALL_INDEX).is_symlink()


_drop_recall_index = drop_recall_index


def refresh_views_reason(rt: Any, owner: str) -> str | None:
    """None when the views are written again from the rows that are left (or there are none to write); else the machine code of why not:
    ``views_path_too_long`` (the path cannot be opened on this machine; it ends here and trying again changes nothing),
    ``views_file_busy`` (another process holds a view file; it passes) or ``views_retry`` (anything else, tried again at the next write)."""
    if not (rt.path.parent / "views").is_dir():
        return None
    from .memory_views import process_memory_views
    result: dict[str, Any] = {}
    try:
        for _ in range(4):
            result = process_memory_views(rt.db, rt.path, owner)
            if not result.get("moreWork"):
                break
    except Exception:  # noqa: BLE001
        return "views_retry"
    if result.get("state") in ("retry", "failed"):
        return str(result.get("reason") or "views_retry")
    return None


def refresh_views(rt: Any, owner: str) -> bool:
    """Public name (was ``_refresh_views``). Contract: write ``views/**/memory.json`` again from the rows that are left; False when it could not run.

    Write ``views/**/memory.json`` again from the rows that are left (the same projection the curation runs; a user whose
    views are fresh pays nothing, and a user who has no views folder gets none). False when the projection could not run."""
    return refresh_views_reason(rt, owner) is None


_refresh_views = refresh_views


FORGET_CHAIN_MAX_DEPTH = 16   # how many generations of older versions one forget follows; beyond it the answer is ``partial`` with ``supersede_depth``
_SUPERSEDES_TOKEN = "supersedes:"


def _older_versions(places: "list[tuple[Any, sqlite3.Connection]]", row_id: str) -> set[str]:
    """The ids of the rows ``row_id`` replaced (its older versions), from the three places a replacement is written: the ``supersedes:<id>`` token in the
    row's evidence (the desktop's owner edit and dreaming), a ``memory_origin_links`` line of relation ``supersedes`` (the engine's curation) and a
    ``supersedes`` edge of ``memory_relation_edges`` (from the newer row to the older one). Looks in every store; a table or column a store does not have
    gives nothing."""
    older: set[str] = set()
    for _ref, db in places:
        tables = _tables(db)
        try:
            if "memory_entries" in tables:
                row = db.execute("SELECT evidence_json FROM memory_entries WHERE id=?", (row_id,)).fetchone()
                if row and row[0]:
                    try:
                        evidence = json.loads(row[0])
                    except ValueError:
                        evidence = []
                    if isinstance(evidence, list):
                        older.update(item[len(_SUPERSEDES_TOKEN):] for item in evidence
                                     if isinstance(item, str) and item.startswith(_SUPERSEDES_TOKEN) and 0 < len(item) - len(_SUPERSEDES_TOKEN) <= 256)
            if "memory_origin_links" in tables:
                older.update(r[0] for r in db.execute("SELECT source_id FROM memory_origin_links WHERE memory_id=? AND source_kind='memory' AND relation='supersedes'", (row_id,)) if r[0])
            if "memory_relation_edges" in tables:
                older.update(r[0] for r in db.execute("SELECT to_memory_id FROM memory_relation_edges WHERE from_memory_id=? AND relation_type='supersedes'", (row_id,)) if r[0])
        except sqlite3.Error:
            continue
    older.discard(row_id)
    return older


def _supersede_ancestors(places: "list[tuple[Any, sqlite3.Connection]]", selected: Any) -> "tuple[list[Any], list[str]]":
    """The older versions of the row being forgotten (principle P8, design 2.3 item 9): every row it replaced, and the ones those replaced, up to
    ``FORGET_CHAIN_MAX_DEPTH`` generations, in any store. Only rows of the SAME owner as the forgotten row (its canonical owner key) are taken, and the walk
    does not go through a row of another owner. Cycle-safe (a seen id is never visited twice) and iterative. Returns ``(rows that still hold words, the older
    versions left unvisited because the depth ran out)``. The newer versions of the row are never touched: a later memory is a different memory."""
    mine = owner_keys(selected)[0]
    seen = {selected["id"]}
    frontier = [selected["id"]]
    found: list[Any] = []
    for _depth in range(FORGET_CHAIN_MAX_DEPTH):
        step: list[str] = []
        for row_id in frontier:
            for older in sorted(_older_versions(places, row_id) - seen):
                seen.add(older)
                row = None
                for _ref, db in places:
                    try:
                        row = db.execute("SELECT id,scope,kind,content,project_id,project_path,agent_id,chat_id,superseded_at FROM memory_entries WHERE id=?", (older,)).fetchone()
                    except sqlite3.Error:
                        row = None
                    if row:
                        break
                if row is None:
                    step.append(older)   # a row this store set does not hold may still be linked on to its own older versions
                    continue
                try:
                    if owner_keys(row)[0] != mine:
                        continue
                except Exception:  # noqa: BLE001 - an owner that cannot be worked out is not touched
                    continue
                if not row["superseded_at"]:
                    continue   # D2: a line that was only pointed at (a replacement that failed halfway, a citation) and is still live is not an older version
                if row["content"]:
                    found.append(row)
                step.append(older)
        frontier = step
        if not frontier:
            return found, []
    return found, sorted(set().union(*(_older_versions(places, row_id) - seen for row_id in frontier)))


def _entry_select(db: sqlite3.Connection, kind_column: str, where: str) -> str:
    """The columns a forget reads from a line, with the binding's ``actor_id`` when the file has bindings (the owner is ``agent_id`` or, when the line has none, that actor: the desktop's ``agent_id ?? actor_id``)."""
    if "memory_identity_bindings" in _tables(db):
        return (f"SELECT m.id,m.scope,{kind_column} AS kind,m.content,m.project_id,m.project_path,m.agent_id,m.chat_id,b.actor_id AS actor_id "
                f"FROM memory_entries m LEFT JOIN memory_identity_bindings b ON b.memory_id=m.id WHERE {where}")
    return f"SELECT m.id,m.scope,{kind_column} AS kind,m.content,m.project_id,m.project_path,m.agent_id,m.chat_id FROM memory_entries m WHERE {where}"


def forget(owner: str, memory_id: str) -> dict[str, Any]:
    """Forget one memory everywhere this account keeps it.

    Order (a crash anywhere is finished by the next open of a store, which compares its ``forget_epoch_applied`` with
    the root's clock): 1. the root records the revocation and advances the clock in one transaction, naming every row
    that holds the same words (same kind, same normalised text) in any store, and blanks the ones in the root; 2. each
    other store is opened, which blanks what the ledger says it still holds; 3. episode summaries that quote the words are emptied (the tickets come from the rows' own links), the observed turn each ticket kept
    (``memory_operations.payload_json``) is emptied and the continuation hint made from it is deleted, all in the same transaction as 1.
    From step 1 on, the same words are refused as a new memory under any agent or project (the check is by text, not by
    owner). The recall indexes follow the stores' revision.

    The older versions the row replaced (``supersedes``, up to ``FORGET_CHAIN_MAX_DEPTH`` generations, the same owner only, only lines that are marked superseded) are
    blanked with it by their ids (no stamp of their words, and no other line that says the same words), in the same transaction: a chain is wholly forgotten or not at all. A chain deeper than the cap ends as
    ``partial`` (``left`` has ``supersede_depth``, ``continueWith`` the ids to forget next). Forgetting a row that is already blank and was forgotten
    finishes what a crash left (the stores' catch-up, the views, the search indexes) and answers like the first call."""
    from .memory_runtime import _content_hash
    rt = open_root(owner)
    if rt is None:
        return {"state": "no_store"}
    try:
        stores, _more = ms.recent_stores(owner, [], limit=10 ** 9)
        places: list[tuple[ms.StoreRef | None, sqlite3.Connection]] = [(None, rt.db)]
        extra: list[sqlite3.Connection] = []
        for ref in stores:
            try:
                db = ms._connect_ro(ref.path)
            except (sqlite3.Error, OSError, ValueError):
                continue
            extra.append(db)
            places.append((ref, db))
        try:
            selected = None
            for _ref, db in places:
                selected = db.execute(_entry_select(db, "m.kind", "m.id=? AND m.content<>''"), (memory_id,)).fetchone()
                if selected:
                    break
            if not selected:
                if rt.db.execute("SELECT 1 FROM memory_revocation_sources WHERE source_memory_id=?", (memory_id,)).fetchone() is None:
                    return {"state": "not_found"}
                return _finish_forget(rt, owner, stores, None, resumed=True)   # forgotten before: what a crash left behind is finished now
            ancestors, depth_left = _supersede_ancestors(places, selected)
            # D1: the words that are stamped and matched by text are the forgotten line's OWN. An older version it replaced is blanked by its id only (in the store that holds it),
            # with no stamp of its own: another line that happens to say the same words (a live one, another agent's, Personal) is a different memory and stays.
            digest, kind = _content_hash(selected["content"]), selected["kind"]
            ancestor_ids = sorted({row["id"] for row in ancestors})
            matched: dict[str, list[str]] = {}
            tickets: set[str] = set()  # the tickets whose episode summaries quote the forgotten words
            #': the words are matched inside the OWNER of the forgotten line (its scope and its agent, project or Personal), in the root and in every store: the same words alive under another agent,
            # another project or Personal are those subjects' lines and stay (they were matched account-wide once the layout switch was on).
            #'': "the same words" is the stamp's own rule (one trailing mark may differ, the kind never takes part when the ruleset is usable: ``memory_stores.words_match``), so the lines a forget blanks are exactly the lines
            # the stamp refuses to write again; the owner is the family of the personal agent (Personal + its own work knowledge, ``family_owner_keys``) or the line's own owner for every other subject, and a project is known by folder and id.
            from . import memory_classify
            selected_keys = set(ms.family_owner_keys(selected))
            kind_blind = memory_classify.active() is not None
            for ref, db in places:
                found = {r["id"] for r in db.execute(_entry_select(db, "m.kind", "m.content<>''" + ("" if kind_blind else " AND m.kind=?")), () if kind_blind else (kind,))
                         if ms.words_match(r["content"], digest) and (r["id"] == memory_id or selected_keys & set(ms.row_owner_keys(r)))}
                for chunk in _chunks(ancestor_ids):
                    found.update(r[0] for r in db.execute(f"SELECT id FROM memory_entries WHERE content<>'' AND id IN ({_marks(len(chunk))})", chunk))
                ids = sorted(found)
                if ids:
                    matched[str(ref.path) if ref else "root"] = ids
                    if "memory_origin_links" in _tables(db):
                        for chunk in _chunks(ids):   #': the desktop writes its turn links as `ticket`, the engine's own are `memory-ticket`: both are turns the line came from
                            tickets.update(r[0] for r in db.execute(
                                f"SELECT source_id FROM memory_origin_links WHERE source_kind IN ('memory-ticket','ticket') AND memory_id IN ({_marks(len(chunk))})", chunk))
        finally:
            for db in extra:
                db.close()
        all_ids = sorted({i for ids in matched.values() for i in ids} | {memory_id})
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        import uuid
        rt.db.execute("PRAGMA secure_delete=ON")  # the pages the words leave are overwritten, not just unlinked
        #': the host facts kept beside an episode's summary (`detail_json`: the owner's own message of that turn) are the turn record's too
        detail = ",detail_json=NULL" if "detail_json" in _columns(rt.db, "memory_episodes") else ""
        rt.db.execute("BEGIN IMMEDIATE")
        try:
            rt.db.execute("UPDATE memory_forget_clock SET epoch=epoch+1 WHERE id=1")
            epoch = int(rt.db.execute("SELECT epoch FROM memory_forget_clock WHERE id=1").fetchone()[0])
            revocation = "mrv_" + uuid.uuid4().hex
            for key in ms.family_owner_keys(selected):
                rt.db.execute("INSERT INTO memory_revocations(revocation_id,owner_key,memory_kind,content_hash,source_memory_id,revoked_epoch,revoked_at) VALUES(?,?,?,?,?,?,?) "
                              "ON CONFLICT(owner_key,memory_kind,content_hash) DO UPDATE SET source_memory_id=excluded.source_memory_id,revoked_epoch=excluded.revoked_epoch,revoked_at=excluded.revoked_at",
                              ("mrv_" + uuid.uuid4().hex if key != ms.family_owner_keys(selected)[0] else revocation, key, kind, digest, memory_id, epoch, now))
            canonical = rt.db.execute("SELECT revocation_id FROM memory_revocations WHERE owner_key=? AND memory_kind=? AND content_hash=?",
                                      (owner_keys(selected)[0], kind, digest)).fetchone()[0]
            for ident in all_ids:   # the older versions' ids are tied to this stamp as sources only (so a store that was not open catches them up by id), never stamped by their words
                rt.db.execute("INSERT INTO memory_revocation_sources(source_memory_id,revocation_id) VALUES(?,?) "
                              "ON CONFLICT(source_memory_id) DO UPDATE SET revocation_id=excluded.revocation_id", (ident, canonical))
            in_root = matched.get("root", [])
            if in_root or tickets:
                #'': the root file is owed one rewrite after this forget blanked something in it (a page a writer without secure_delete split keeps old cell bytes where no row points). The marker is the desktop's own
                # key (``ROOT_RESIDUE_PENDING_KEY``, stores.ts); the desktop's resting-time pass rewrites the file and deletes it. Same transaction as the stamp; no new table or column.
                rt.db.execute("INSERT INTO memory_store_meta(key,value) VALUES('root_residue_pending',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(epoch),))
            if in_root:
                if "memory_episodes" in _tables(rt.db) and "memory_decisions" in _tables(rt.db):
                    for chunk in _chunks(in_root):
                        rt.db.execute(f"UPDATE memory_episodes SET summary=NULL,summary_hash=NULL,embedding_model=NULL,embedding_adapter=NULL,embedding_model_sha256=NULL,"
                                      f"embedding_content_hash=NULL,embedding_dimensions=NULL,embedding_json=NULL{detail} WHERE ticket_id IN "
                                      f"(SELECT ticket_id FROM memory_decisions WHERE target_memory_id IN ({_marks(len(chunk))}))", chunk)
                        ms._blank(rt.db, chunk, now)
            if in_root and "memory_decisions" in _tables(rt.db):
                for chunk in _chunks(in_root):
                    tickets.update(r[0] for r in rt.db.execute(f"SELECT ticket_id FROM memory_decisions WHERE target_memory_id IN ({_marks(len(chunk))})", chunk))
            if tickets and "memory_session_checkpoints" in _tables(rt.db):
                # The continuation hint made from a turn that carried the words quotes that turn's summary.
                for chunk in _chunks(sorted(tickets)):
                    rt.db.execute(f"DELETE FROM memory_session_checkpoints WHERE json_valid(payload_json) AND json_extract(payload_json,'$.ticket_ref') IN ({_marks(len(chunk))})", chunk)
                rt.db.execute("DELETE FROM memory_session_checkpoint_heads WHERE checkpoint_id NOT IN (SELECT checkpoint_id FROM memory_session_checkpoints)")
            if tickets and "memory_operations" in _tables(rt.db):
                # The observed turn that carried the words is kept as the operation's payload; nothing reads it once the turn is
                # decided, so it is emptied in this transaction (the operation id is its ticket id).
                for chunk in _chunks(sorted(tickets)):
                    rt.db.execute(f"UPDATE memory_operations SET payload_json='{{}}' WHERE payload_json<>'{{}}' AND operation_id IN ({_marks(len(chunk))})", chunk)
            if tickets and "memory_episodes" in _tables(rt.db):
                # A row written straight into a store has no root decision pointing at it; its tickets come from its own links.
                for chunk in _chunks(sorted(tickets)):
                    marks = _marks(len(chunk))
                    twins = [r[0] for r in rt.db.execute(f"SELECT episode_id FROM memory_episodes WHERE ticket_id IN ({marks})", chunk)]
                    rt.db.execute(f"UPDATE memory_episodes SET summary=NULL,summary_hash=NULL,embedding_model=NULL,embedding_adapter=NULL,embedding_model_sha256=NULL,"
                                  f"embedding_content_hash=NULL,embedding_dimensions=NULL,embedding_json=NULL{detail} WHERE ticket_id IN ({marks})", chunk)
                    for part in _chunks(twins):   #': the original-wording twin of an episode summary and its translation job quote the words too
                        if "memory_episode_native" in _tables(rt.db):
                            rt.db.execute(f"DELETE FROM memory_episode_native WHERE episode_id IN ({_marks(len(part))})", part)
                        if "memory_translation_jobs" in _tables(rt.db):
                            rt.db.execute(f"DELETE FROM memory_translation_jobs WHERE target_kind='memory_episode' AND target_id IN ({_marks(len(part))})", part)
            rt.db.commit()
        except BaseException:
            rt.db.rollback()
            raise
        result = _finish_forget(rt, owner, stores, matched, resumed=False,
                                head={"epoch": epoch, "forgotten": len(all_ids), "alsoForgotten": max(0, len(all_ids) - 1)})
        if ancestors:
            result["ancestors"] = len(ancestors)
        if depth_left:   # the chain is longer than one forget follows: not "forgotten" until the rest is; forgetting these ids goes on from here
            result["state"] = "partial"
            result["left"] = sorted({*result.get("left", []), "supersede_depth"})
            result["continueWith"] = sorted(depth_left)
        return result
    finally:
        rt.close()


def _finish_forget(rt: Any, owner: str, stores: "list[ms.StoreRef]", matched: "dict[str, list[str]] | None", *, resumed: bool,
                   head: "dict[str, Any] | None" = None) -> dict[str, Any]:
    """The part of a forget that runs after the root's transaction: the other stores catch up with the ledger, the views are written again and the
    search indexes are deleted. Each step is safe to run again, which is what makes a forget that died here resumable (``matched`` None = every store,
    the resumed case: nothing says which ones held the words). Answers the same keys as the first call, ``state`` ``partial`` when a copy is left."""
    pending: list[str] = []
    for ref in stores:
        if matched is not None and str(ref.path) not in matched:
            continue
        opened, code = ms.open_store(ref, owner, rt.db)
        if opened is None:
            pending.append(f"{ref.kind}:{code}")
            continue
        if opened.withheld:
            pending.append(f"{ref.kind}:forget_catchup_withheld")
        opened.db.close()
        ms.remove_agent_memory_md(ref)
    # The words also sit in two copies that are not rows: the views the curation writes (central layout) and the search
    # index beside each store. The first is written again from what is left, the second is deleted and rebuilt by the next search.
    left: list[str] = []
    reasons: dict[str, str] = {}
    why = refresh_views_reason(rt, owner)
    if why:
        left.append("views")
        reasons["views"] = why
    keys = ["root", *(matched if matched is not None else [str(ref.path) for ref in stores])]
    for key in dict.fromkeys(keys):
        if not drop_recall_index(rt.path.parent if key == "root" else Path(key).parent):
            left.append("recall_index")
    result: dict[str, Any] = {"state": "partial" if left else "forgotten"}
    if resumed:
        result.update({"epoch": int(rt.db.execute("SELECT epoch FROM memory_forget_clock WHERE id=1").fetchone()[0]), "resumed": True})
    result.update(head or {})
    result.update({"stores": sorted({"root" if key == "root" else "other" for key in (matched if matched is not None else ["root"])}), "pending": pending})
    if left:
        result["left"] = sorted(set(left))
        if reasons:
            result["leftReasons"] = reasons
    return result


# --- forgetting an agent or a project ----------------------------------------------------------------------------

def delete_sources(db: sqlite3.Connection, source_ids: Iterable[str], tables: set[str] | None = None) -> tuple[int, int]:
    """Delete source registrations (``memory_source_catalogue``) and their versions, versions first. Returns ``(versions, catalogue)``.
    Inside the caller's transaction; the order is the one the foreign key needs."""
    tables = _tables(db) if tables is None else tables
    versions = catalogue = 0
    for chunk in _chunks(sorted(set(source_ids))):
        if "memory_source_versions" in tables:
            versions += db.execute(f"DELETE FROM memory_source_versions WHERE source_id IN ({_marks(len(chunk))})", chunk).rowcount
        if "memory_source_catalogue" in tables:
            catalogue += db.execute(f"DELETE FROM memory_source_catalogue WHERE source_id IN ({_marks(len(chunk))})", chunk).rowcount
    return versions, catalogue


def purge_entries(rt: Any, entry_ids: list[str], ticket_ids: Iterable[str] = (), actor_ids: tuple[str, ...] = (), *, keep_tickets: bool = False,
                  still: Callable[[sqlite3.Connection, list[str]], Iterable[str]] | None = None,
                  known_sources: dict[str, str] | None = None) -> dict[str, int]:
    """Public name (was ``_purge_root``). Contract: delete these entries and these turn tickets from the root in one transaction, with everything
    that hangs on them, and count what went. It DELETES: it writes no retired stub (no ``superseded_at`` stamp on any row, no revocation, no
    forget-clock change), so a purged row simply does not exist afterwards; retiring a row is a different act that this function never does.

    It takes ids only: ``entry_ids``, ``ticket_ids`` and the ``actor_ids`` whose operations, tickets, source registrations and checkpoints go
    too. There is no way to hand it a piece of SQL (the forget calls inside this module use ``_purge_with_where`` for their own fixed conditions).

    One transaction in the root: the entries (and everything that hangs on them), the tickets with their episodes and
    decisions, the operations that carried the words, their source catalogue rows and the engine checkpoints made from those
    tickets. Written with ``secure_delete`` so the words do not stay in the file's free pages. Returns what went, each number the rows
    actually deleted (``DELETE`` row counts; rows that leave with their ticket are counted before and after, inside the same lock), never a
    difference of table sizes: ``tickets``, ``episodes``, ``decisions``, ``curation_jobs``, ``translation_jobs``, ``operations``, ``sources``,
    ``source_versions``, ``checkpoints``, ``entries`` (the ids asked for).

    ``keep_tickets`` leaves the tickets and their episodes where they are and removes only what hangs on them elsewhere (the operation
    rows and their source registrations): the first-run cleanup uses it for turns whose summary is still inside its retention. The project
    those operation rows named (``project_path``, ``project_ref`` in the payload, the only place a hook's turn says it) is first written onto the
    turn's ticket and episode where they have none, in the same transaction, so forgetting the project still finds the turn afterwards.
    ``still`` is called after the write lock is held with the ticket ids chosen so far and returns the ones that still qualify, so a
    caller that chose them before taking the lock does not delete a turn that changed meanwhile. With ``still`` the ``actor_ids`` reach their
    rows through those tickets only (no delete by actor id on the operations, sources and checkpoints).
    ``known_sources`` (``source_id`` -> ``logical_key``, found by the caller before the lock was taken) replaces the scan of the whole source
    registration table that finds the registrations of the tickets: under the lock each is looked up by its key and kept only while its
    ``logical_key`` is still one of the tickets, so a long cleanup does not hold the write lock for a table scan every batch. A registration
    made for these turns after the caller looked is not removed here; the sweep of registrations that no operation row names removes it."""
    return _purge_with_where(rt, entry_ids, ticket_ids, actor_ids, None, None, keep_tickets=keep_tickets, still=still, known_sources=known_sources)


def _purge_with_where(rt: Any, entry_ids: list[str], ticket_ids: Iterable[str] = (), actor_ids: tuple[str, ...] = (),
                      episode_where: tuple[str, tuple[Any, ...]] | None = None,
                      operation_where: tuple[str, tuple[Any, ...]] | None = None, *, keep_tickets: bool = False,
                      still: Callable[[sqlite3.Connection, list[str]], Iterable[str]] | None = None,
                      known_sources: dict[str, str] | None = None) -> dict[str, int]:
    """``purge_entries`` with the two fixed conditions the forget calls need: ``episode_where`` (rows of ``memory_episodes``) and
    ``operation_where`` (rows of ``memory_operations`` whose ticket goes). Both are SQL written by the caller from placeholders, so this
    stays inside the module."""
    if not isinstance(ticket_ids, set):
        ticket_ids = set(ticket_ids)  # the body adds the tickets of ``actor_ids`` / ``operation_where``; a set passed in is filled in place as before
    db = rt.db
    tables = _tables(db)
    removed = Counter()
    direct_actors = actor_ids if still is None else ()  # with ``still`` the actors' rows go only through the tickets it let stay
    db.execute("PRAGMA secure_delete=ON")
    db.execute("BEGIN IMMEDIATE")
    try:
        if "memory_operations" in tables and actor_ids:
            ticket_ids.update(r[0] for r in db.execute(f"SELECT operation_id FROM memory_operations WHERE actor_id IN ({_marks(len(actor_ids))})", actor_ids))
        if "memory_tickets" in tables and actor_ids:
            ticket_ids.update(r[0] for r in db.execute(f"SELECT ticket_id FROM memory_tickets WHERE agent_id IN ({_marks(len(actor_ids))})", actor_ids))
        if "memory_operations" in tables and operation_where:
            # A turn the hooks observed names its project only inside the operation's payload (the ticket carries neither the
            # id nor the path hash); the operation id is its ticket id.
            ticket_ids.update(r[0] for r in db.execute(f"SELECT operation_id FROM memory_operations WHERE {operation_where[0]}", operation_where[1]))
        if still is not None:
            ticket_ids.intersection_update(still(db, sorted(ticket_ids)))
        tickets = sorted(ticket_ids)
        if keep_tickets and "memory_operations" in tables:
            _carry_project(db, tickets, tables)  # the operation rows below are the only place a hook's turn names its project
        if "memory_session_checkpoints" in tables:
            doomed: set[str] = set()
            for chunk in _chunks(tickets):
                doomed.update(r[0] for r in db.execute(
                    f"SELECT checkpoint_id FROM memory_session_checkpoints WHERE json_valid(payload_json) AND json_extract(payload_json,'$.ticket_ref') IN ({_marks(len(chunk))})", chunk))
            if direct_actors:
                doomed.update(r[0] for r in db.execute(
                    f"SELECT checkpoint_id FROM memory_session_checkpoints WHERE json_valid(payload_json) AND json_extract(payload_json,'$.actor_id') IN ({_marks(len(direct_actors))})", direct_actors))
            for chunk in _chunks(sorted(doomed)):
                removed["checkpoints"] += db.execute(f"DELETE FROM memory_session_checkpoints WHERE checkpoint_id IN ({_marks(len(chunk))})", chunk).rowcount
            db.execute("DELETE FROM memory_session_checkpoint_heads WHERE checkpoint_id NOT IN (SELECT checkpoint_id FROM memory_session_checkpoints)")
        if "memory_source_catalogue" in tables:
            sources: set[str] = set()
            if known_sources is None:
                for chunk in _chunks(tickets):
                    sources.update(r[0] for r in db.execute(f"SELECT source_id FROM memory_source_catalogue WHERE logical_key IN ({_marks(len(chunk))})", chunk))
            else:
                wanted = set(tickets)
                for chunk in _chunks(sorted(known_sources)):
                    sources.update(r[0] for r in db.execute(f"SELECT source_id,logical_key FROM memory_source_catalogue WHERE source_id IN ({_marks(len(chunk))})", chunk)
                                   if r[1] in wanted)
            if direct_actors:
                sources.update(r[0] for r in db.execute(f"SELECT source_id FROM memory_source_catalogue WHERE actor_id IN ({_marks(len(direct_actors))})", direct_actors))
            if sources:
                versions, catalogue = delete_sources(db, sources, tables)
                removed["sources"] += catalogue
                if versions:
                    removed["source_versions"] += versions
        if "memory_operations" in tables:
            for chunk in _chunks(tickets):
                removed["operations"] += db.execute(f"DELETE FROM memory_operations WHERE operation_id IN ({_marks(len(chunk))})", chunk).rowcount
            if direct_actors:
                removed["operations"] += db.execute(f"DELETE FROM memory_operations WHERE actor_id IN ({_marks(len(direct_actors))})", direct_actors).rowcount
        if "memory_episodes" in tables and episode_where:
            removed["episodes"] += db.execute(f"DELETE FROM memory_episodes WHERE {episode_where[0]}", episode_where[1]).rowcount
        if "memory_tickets" in tables and not keep_tickets:
            if "memory_translation_jobs" in tables and "memory_episodes" in tables:
                # The desktop queues translations of episode summaries and keeps the original wording beside them; neither outlives the episode.
                for chunk in _chunks(tickets):
                    removed["translation_jobs"] += db.execute(f"DELETE FROM memory_translation_jobs WHERE target_kind='memory_episode' AND target_id IN "
                                                              f"(SELECT episode_id FROM memory_episodes WHERE ticket_id IN ({_marks(len(chunk))}))", chunk).rowcount
                    if "memory_episode_native" in tables:
                        db.execute(f"DELETE FROM memory_episode_native WHERE episode_id IN "
                                   f"(SELECT episode_id FROM memory_episodes WHERE ticket_id IN ({_marks(len(chunk))}))", chunk)
            children = [(name, table) for name, table in (("episodes", "memory_episodes"), ("decisions", "memory_decisions"), ("curation_jobs", "memory_curation_jobs"))
                        if table in tables]
            for chunk in _chunks(tickets):  # decisions, the tickets' own episodes and quarantines go with them
                marks = _marks(len(chunk))
                held = {name: db.execute(f"SELECT COUNT(*) FROM {table} WHERE ticket_id IN ({marks})", chunk).fetchone()[0] for name, table in children}
                removed["tickets"] += db.execute(f"DELETE FROM memory_tickets WHERE ticket_id IN ({marks})", chunk).rowcount
                for name, table in children:  # what left with the ticket, counted inside the lock: exact
                    removed[name] += held[name] - db.execute(f"SELECT COUNT(*) FROM {table} WHERE ticket_id IN ({marks})", chunk).fetchone()[0]
        if entry_ids:
            _delete_rows(db, entry_ids)  # bindings, links, relation edges, native text, outbox and translation jobs
            removed["entries"] = len(entry_ids)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return dict(removed)


_purge_root = purge_entries


def _carry_project(db: sqlite3.Connection, tickets: list[str], tables: set[str]) -> None:
    """Before a turn's operation row goes, write the project it named onto the turn's ticket (only where it names none; the summary is left as the hook wrote it, so recall still finds it everywhere).

    A turn the hooks observed has neither ``project_id`` nor ``project_path_hash`` on its ticket unless the app passed a project ref; the
    folder is only in the operation's payload. Without this the project forget, which finds hook turns by those two columns, could not find
    the turn once its operation row was cleaned up. Inside the caller's transaction; a column the schema lacks is skipped."""
    for table in ("memory_tickets", "memory_episodes"):
        if table not in tables:
            return
    columns = {table: {row[1] for row in db.execute(f"PRAGMA table_info({table})")} for table in ("memory_tickets", "memory_episodes")}
    for chunk in _chunks(tickets):
        rows = db.execute("SELECT operation_id, CASE WHEN json_valid(payload_json) THEN json_extract(payload_json,'$.project_path') END, "
                          "CASE WHEN json_valid(payload_json) THEN json_extract(payload_json,'$.project_ref') END "
                          f"FROM memory_operations WHERE operation_id IN ({_marks(len(chunk))})", chunk).fetchall()
        for ticket, path, ref in rows:
            for column, value in (("project_path_hash", _hash(path) if isinstance(path, str) and path else None),
                                  ("project_id", ref if isinstance(ref, str) and ref else None)):
                if value is None:
                    continue
                for table in ("memory_tickets",):
                    if column in columns[table]:
                        db.execute(f"UPDATE {table} SET {column}=? WHERE ticket_id=? AND COALESCE({column},'')=''", (value, ticket))


def _store_dirs_gone(folders: Iterable[Path], boundary: Path) -> list[str]:
    left: list[str] = []
    for folder in folders:
        if folder.exists() or folder.is_symlink():
            if not _rmtree_owned(folder, boundary) or folder.exists():
                left.append("store_files")
    return left


def _locked(error: BaseException) -> bool:
    text = str(error).lower()
    return isinstance(error, sqlite3.OperationalError) and ("locked" in text or "busy" in text)


# The desktop keeps the losing side of an agent-folder merge under ``<agent folder>/.agentlas-local/absorbed-<ISO time with : and . as ->/``
# (electron/agents/home-move.ts, nothing there is ever deleted by the merge itself) and heals its memory files back into the live store.
# The name rule is the desktop's, character for character: a folder that does not match it is not ours and is left alone.
_ABSORBED = re.compile(r"^absorbed-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z$")


def _absorbed_copies_gone(owner: str, home: Path) -> list[str]:
    """This account's memory folder inside each preserved ``absorbed-*`` copy of the agent folder (same relative place as the live one:
    ``absorbed-*/memory/o-<account>/``), so a forgotten agent's words cannot be healed back from a copy. Another account's folder in the
    copy, any other file in it and every link are not touched (a link is never followed). Returns ``store_files`` when one is left."""
    state = home / agent_home.AGENT_LOCAL_STATE_FOLDER
    left: list[str] = []
    try:
        if state.is_symlink() or not state.is_dir():
            return left
        copies = sorted(child for child in state.iterdir() if _ABSORBED.match(child.name))
    except OSError:
        return ["store_files"]
    for copy in copies:
        try:
            if copy.is_symlink() or not copy.is_dir():
                continue
            mine = long_path.extended(copy / "memory" / ms.agent_account_folder(owner), 40)
            if mine.exists() or mine.is_symlink():
                if not _rmtree_owned(mine, home) or mine.exists() or mine.is_symlink():
                    left.append("store_files")
                    continue
            try:
                (copy / "memory").rmdir()  # when it holds nothing else
            except OSError:
                pass
        except OSError:
            left.append("store_files")
    return left


def forget_agent(owner: str, agent_id: str, aliases: Iterable[str] = ()) -> dict[str, Any]:
    """Everything this account keeps for one agent that deleting the agent's folder does not take with it: the agent's rows
    and the turns they came from in the root (episode summaries, operations, tickets, translation jobs, relation edges, the
    agent's own continuation checkpoints), the copies of those words that are not rows (the views and the search index in the
    account's folder) and, while the folder still exists, the account's whole memory folder inside it (memory file and search
    index). Another account's file, another agent and the account's revocation ledger are not touched. A Hub agent, One and
    ``host:*`` actors have no memory of their own and are skipped. Safe to run again: a second run finds nothing and says so.

    Call it BEFORE the agent's folder is deleted: the folder's ``owner.json`` names the agent's other ids and the account's
    store lives in it. When the folder is already gone, pass the ids the app knew from ``owner.json`` as ``aliases``; their
    rows in the root are removed as well (``agentFolder`` says ``not_found`` then)."""
    aid = ms.store_agent_id(agent_id)
    if aid is None:
        return {"state": "skipped", "reason": "not_an_agent_with_memory", "scope": "agent"}
    home = ms.find_agent_home(aid)
    named = [item.strip() for item in aliases if isinstance(item, str) and item.strip()]
    found = [i for i in (ms._owner_ids(home) if home is not None else []) if ms.store_agent_id(i)]
    aliases = tuple(dict.fromkeys([aid, *found, *(i for i in named if ms.store_agent_id(i))]))
    left: list[str] = []
    reasons: dict[str, str] = {}
    removed: dict[str, int] = {}
    rt = None
    try:
        rt = open_root(owner)
    except (sqlite3.Error, ValueError) as error:
        left.append("root_locked" if _locked(error) else "root_unreadable")
    if rt is not None:
        try:
            marks = _marks(len(aliases))
            ids = [row["id"] for row in rt.db.execute(f"SELECT id,scope,agent_id,project_id,project_path,chat_id FROM memory_entries WHERE agent_id IN ({marks})", aliases)
                   if (owned := owner_scope_of(row)) is not None and owned.kind == ms.AGENT]
            removed = _purge_with_where(rt, ids, set(), aliases, (f"agent_id IN ({marks})", aliases))
            why = refresh_views_reason(rt, owner)
            if why:
                left.append("views")
                reasons["views"] = why
            if not drop_recall_index(rt.path.parent):
                left.append("recall_index")
        except sqlite3.Error as error:
            left.append("root_locked" if _locked(error) else "root_unreadable")
        finally:
            rt.close()
    if home is not None:
        ref = ms.agent_ref(owner, home, aid)
        folder = ref.path.parent  # the account's folder inside the agent folder: memory file, search index, MEMORY.md
        if folder.exists() or folder.is_symlink():
            if not _rmtree_owned(folder, home):
                _remove_store_files(ref)
                drop_recall_index(folder)
        try:
            folder.parent.rmdir()  # .agentlas-local/memory when it holds nothing else
        except OSError:
            pass
        if folder.exists() or folder.is_symlink():
            left.append("store_files")
        left.extend(_absorbed_copies_gone(owner, home))
    result: dict[str, Any] = {"state": "partial" if left else "forgotten", "scope": "agent", "removed": removed, "agentFolder": "found" if home is not None else "not_found"}
    if left:
        result["left"] = sorted(set(left))
        if reasons:
            result["leftReasons"] = reasons
    return result


class _Located:
    """One project store folder this call found, the code-index folders of this project inside it, and whether another
    live folder shares the store."""

    def __init__(self) -> None:
        self.ours: list[Path] = []
        self.shared = False


def _locate_project_stores(owner: str, paths: list[str], keys: list[str]) -> dict[Path, _Located]:
    """The project stores (``projects/<key>/``) that belong to the named folder: by the key the folder or the app gives, and by
    the code index the folder left behind (``index/<hash of the real path>/manifest.json`` carries ``projectRoot``), which still
    finds the store after the folder, and so its marker, is gone. A store is shared when its ``index/`` holds the code index of
    another folder that still exists (a ``cp -r`` copy keeps the marker's uid and so uses the same store); an index that does
    not say whose it is (no ``projectRoot``) proves nothing and is not counted. Without a path the call names the project by id alone and every store of that id goes."""
    from .code_index_location import INDEX_DIRNAME, _path_hash, _read_manifest
    located: dict[Path, _Located] = {}
    for key in keys:
        located.setdefault(ms.project_ref(owner, key).path.parent, _Located())
    real = {os.path.realpath(p) for p in paths}
    ours_hash = {_path_hash(p) for p in paths}
    try:
        children = sorted((ms.account_dir(owner) / "projects").iterdir())
    except OSError:
        children = []
    for child in children:
        index = child / INDEX_DIRNAME
        if not paths or child.is_symlink() or index.is_symlink() or not index.is_dir():
            continue
        mine: list[Path] = []
        other_alive = False
        try:
            entries = sorted(index.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink() or not entry.is_dir():
                continue
            recorded = _read_manifest(entry).get("projectRoot")
            recorded = recorded if isinstance(recorded, str) and recorded else None
            if entry.name in ours_hash or (recorded is not None and os.path.realpath(recorded) in real):
                mine.append(entry)
            elif recorded is not None and Path(recorded).is_dir():
                other_alive = True
        if mine or child in located:
            found = located.setdefault(child, _Located())
            found.ours, found.shared = mine, other_alive
    return located


def _trim_shared_store(owner: str, folder: Path, found: _Located, paths: list[str]) -> list[str]:
    """A store another live folder still uses: this folder's code index and the rows bound to this folder's path go, the rest
    of the store stays. Returns what could not be removed."""
    left: list[str] = []
    for entry in found.ours:
        if not _rmtree_owned(entry, ms.account_dir(owner)) or entry.exists():
            left.append("store_files")
    store = folder / ms.STORE_FILE
    if store.is_file() and paths:
        try:
            db = sqlite3.connect(str(store), timeout=5.0)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA secure_delete=ON")
            try:
                # What is the project's: project and team lines, and an agent line bound to this folder's path (an agent line is
                # project-limited by the path it carries, and the project is gone; the agent's global lines carry no path and are not here).
                ids = [r[0] for r in db.execute(f"SELECT id FROM memory_entries WHERE scope IN ('project','team_memory','agent_team','agent_repo') AND project_path IN ({_marks(len(paths))})", paths)]
                if ids:
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        _delete_rows(db, ids)
                        db.commit()
                    except BaseException:
                        db.rollback()
                        raise
            finally:
                db.close()
        except sqlite3.Error as error:
            left.append("store_locked" if _locked(error) else "store_files")
    if not drop_recall_index(folder):
        left.append("recall_index")  # it holds the rows that went
    return left


def _forget_project_in_agent_stores(owner: str, project_id: str | None, paths: list[str]) -> tuple[int, list[str]]:
    """The desktop's rule for an agent folder's store of this account (electron/memory/store-delete.ts purgeProjectRowsFromAgentStores): the
    project's own lines (project, team and session lines that carry the project id or this folder's path) and every agent line bound to this
    folder's path go; an agent line without a path (the agent's own learning, even with the project id as its source tag) stays. Only
    stores that exist are opened (one stat per agent folder), never through a link, never another account's. Returns (rows removed, codes
    of what could not be cleaned)."""
    left: list[str] = []
    removed = 0
    if not project_id and not paths:
        return 0, left
    project_where = " OR ".join([*(["project_id=?"] if project_id else []), *([f"project_path IN ({_marks(len(paths))})"] if paths else [])])
    where = f"(scope IN ('project','team_memory','agent_team','session') AND ({project_where}))"
    args: list[Any] = [*([project_id] if project_id else []), *paths]
    if paths:
        where += f" OR (scope='agent_repo' AND project_path IN ({_marks(len(paths))}))"
        args.extend(paths)
    seen: set[Path] = set()
    for agent_id, folder in sorted(ms.agent_folder_index().items()):
        if folder in seen:
            continue
        seen.add(folder)
        ref = ms.agent_ref(owner, folder, agent_id)
        try:
            if not ref.path.is_file() or ref.path.is_symlink() or ms._contained_agent_path(ref):
                continue  # no store of this account here, or a link (never followed: recall does not read it either)
        except OSError:
            continue
        try:
            db = sqlite3.connect(long_path.file_uri(ref.path) + "?mode=rw", uri=True, timeout=5.0)
        except (sqlite3.Error, OSError, ValueError):
            left.append("store_files")
            continue
        try:
            if "memory_entries" not in _tables(db):
                continue
            meta = {r[0]: r[1] for r in db.execute("SELECT key,value FROM memory_store_meta")} if "memory_store_meta" in _tables(db) else {}
            if meta.get("owner_namespace") not in (None, owner):
                continue
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA secure_delete=ON")
            ids = [r[0] for r in db.execute(f"SELECT id FROM memory_entries WHERE {where}", args)]
            if not ids:
                continue
            db.execute("BEGIN IMMEDIATE")
            try:
                _delete_rows(db, ids)
                db.commit()
            except BaseException:
                db.rollback()
                raise
            removed += len(ids)
            try:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # the deleted words must not stay in the main file
            except sqlite3.Error:
                pass
            if not drop_recall_index(ref.path.parent):
                left.append("recall_index")
            ms.remove_agent_memory_md(ref)  # earlier engines wrote the words there too
        except sqlite3.Error as error:
            left.append("store_locked" if _locked(error) else "store_files")
        finally:
            db.close()
    return removed, left


def forget_project(owner: str, project_id: str | None = None, project_path: str | None = None) -> dict[str, Any]:
    """Everything this account keeps for one project that is not in the project's own folder: the project's rows and the
    turns they came from in the root (the hooks' turns are found by the path in the operation's payload), the copies of those
    words that are not rows (the views and the search index) and the project's whole memory folder (``projects/<key>/``: its
    memory file and the code index under ``index/``). The project is named by the id the app uses (``project_id``, which is
    also the store key when the app passes it as the project ref) and/or its folder (``project_path``: matches rows bound to
    that path and finds the folder's own key). An agent line bound to the folder's path goes too (the path limits it to this
    project), in the root and, with the layout switch on, in each agent folder's store of this account; an agent line without a
    path stays even when it carries the project id as its source tag (the agent's own learning). Other projects, agents,
    accounts and the user's own project folder are not touched. Safe to run again.

    Call it BEFORE the project's folder is deleted and with both the id and the path. Without the folder the store's key is
    unknown: it is found again by the code index the folder left (``storesFound``), and when that fails too the answer is
    ``partial`` with ``store_not_found`` instead of ``forgotten``. A ``cp -r`` copy keeps the project's uid and so shares its
    store with the original: while another folder that still exists uses the store, only this folder's code index and the
    rows bound to this folder's path are removed and the answer is ``partial`` with ``reason: shared_with_other_folder``."""
    project_id = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
    project_path = project_path.strip() if isinstance(project_path, str) and project_path.strip() else None
    if not project_id and not project_path:
        return {"state": "skipped", "reason": "project_not_named", "scope": "project"}
    #'/ the hash a hook turn now stamps is the disk's own spelling (project_identity.canonical_real_path); the spelling as given and the resolved ones stay, so a turn an older engine stamped is found too
    from .project_identity import canonical_real_path
    paths = list(dict.fromkeys(p for p in (project_path, os.path.realpath(project_path) if project_path else None, str(Path(project_path).resolve()) if project_path else None,
                                           canonical_real_path(project_path) if project_path else None) if p))
    path_hashes = tuple(dict.fromkeys(_hash(p) for p in paths))
    keys = ms.project_keys(project_path, project_id)
    located = _locate_project_stores(owner, paths, keys)
    shared = any(item.shared for item in located.values())
    by_id = bool(project_id) and not shared  # a shared uid names the other folder's rows too: then only this folder's path counts
    left: list[str] = []
    reasons: dict[str, str] = {}
    removed: dict[str, int] = {}
    split_layout = False
    rt = None
    try:
        rt = open_root(owner)
    except (sqlite3.Error, ValueError) as error:
        left.append("root_locked" if _locked(error) else "root_unreadable")
    if rt is not None:
        try:
            split_layout = ms.layout_of(rt.db) == ms.SPLIT
            conditions, args = [], []
            if by_id:
                conditions.append("project_id=?")
                args.append(project_id)
            if paths:
                conditions.append(f"project_path IN ({_marks(len(paths))})")
                args.extend(paths)
            # The project's rows, and an agent line bound to this folder's path: the path limits where the line is recalled ("only in this
            # project", memory_stores._HOOK_AGENT_SQL), so it goes with the project. An agent line that carries only the project id (its source
            # tag) is the agent's own learning and stays, as does one that carries another folder.
            ids = [row["id"] for row in rt.db.execute(f"SELECT id,scope,agent_id,project_id,project_path,chat_id FROM memory_entries WHERE {' OR '.join(conditions)}", args)
                   if ((owned := owner_scope_of(row)) is not None and owned.kind == ms.PROJECT)
                   or (row["scope"] == "agent_repo" and row["project_path"] in paths)] if conditions else []
            ticket_conditions, ticket_args = [], []
            if by_id:
                ticket_conditions.append("project_id=?")
                ticket_args.append(project_id)
            if path_hashes:
                ticket_conditions.append(f"project_path_hash IN ({_marks(len(path_hashes))})")
                ticket_args.extend(path_hashes)
            tickets = {r[0] for r in rt.db.execute(f"SELECT ticket_id FROM memory_tickets WHERE {' OR '.join(ticket_conditions)}", ticket_args)} \
                if ticket_conditions and "memory_tickets" in _tables(rt.db) else set()
            operation_conditions, operation_args = [], []
            if paths:
                operation_conditions.append(f"CASE WHEN json_valid(payload_json) THEN json_extract(payload_json,'$.project_path') END IN ({_marks(len(paths))})")
                operation_args.extend(paths)
            if by_id:
                operation_conditions.append("CASE WHEN json_valid(payload_json) THEN json_extract(payload_json,'$.project_ref') END = ?")
                operation_args.append(project_id)
            removed = _purge_with_where(rt, ids, tickets, (), (" OR ".join(ticket_conditions), tuple(ticket_args)) if ticket_conditions else None,
                                  (" OR ".join(operation_conditions), tuple(operation_args)) if operation_conditions else None)
            why = refresh_views_reason(rt, owner)
            if why:
                left.append("views")
                reasons["views"] = why
            if not drop_recall_index(rt.path.parent):
                left.append("recall_index")
            if ms.layout_of(rt.db) != ms.CENTRAL:  # with the switch off no agent store exists: nothing is opened
                gone_rows, agent_left = _forget_project_in_agent_stores(owner, project_id if by_id else None, paths)
                left.extend(agent_left)
                if gone_rows:
                    removed = {**removed, "agent_store_entries": gone_rows}
        except sqlite3.Error as error:
            left.append("root_locked" if _locked(error) else "root_unreadable")
        finally:
            rt.close()
    present = [folder for folder in located if folder.exists() or folder.is_symlink()]
    boundary = ms.account_dir(owner)
    for folder in present:
        if located[folder].shared:
            left.extend(_trim_shared_store(owner, folder, located[folder], paths))
        else:
            left.extend(_store_dirs_gone([folder], boundary))
    if shared:
        left.append("shared_store")
    certain = bool(project_id) or any(os.path.isdir(p) for p in paths)  # the folder's marker or the app's id gives the store's key
    if not present and split_layout and not certain:
        left.append("store_not_found")
    gone = [folder for folder in present if not folder.exists() and not folder.is_symlink()]
    result: dict[str, Any] = {"state": "partial" if left else "forgotten", "scope": "project", "removed": removed,
                              "stores": len(present), "storesFound": len(present), "storesRemoved": len(gone)}
    if shared:
        result["reason"] = "shared_with_other_folder"
    if left:
        result["left"] = sorted(set(left))
        if reasons:
            result["leftReasons"] = reasons
    return result


# --- deleting stores --------------------------------------------------------------------------------------------

def _rmtree_owned(path: Path, boundary: Path) -> bool:
    """Remove a folder only if it is inside ``boundary`` and neither it nor anything above it up to the boundary is a link."""
    try:
        real = path.resolve()
        if long_path.plain(boundary.resolve()) not in long_path.plain(real).parents:
            return False
        stop = long_path.plain(boundary)
        for part in (path, *path.parents):
            if long_path.plain(part) == stop:
                break
            if part.is_symlink():
                return False
        if not path.exists():
            return True
        shutil.rmtree(path)
        return not path.exists()
    except OSError:
        return False


def delete_account_stores(owner: str) -> dict[str, Any]:
    """The account's session file, its project stores and its folder inside every agent folder. The root store is left
    to the caller (the desktop deletes the whole owner folder). Returns what is still on disk; empty = done."""
    base = ms.account_dir(owner)
    removed: list[str] = []
    left: list[str] = []
    for name in ("session.sqlite", "session.sqlite-journal", "session.sqlite-wal", "session.sqlite-shm"):
        target = base / name
        if target.is_symlink() or target.exists():
            try:
                target.unlink()
                removed.append("session")
            except OSError:
                left.append(str(long_path.plain(target)))
    if not _rmtree_owned(base / "projects", ms._memory_root()):
        left.append(str(long_path.plain(base / "projects")))
    elif (base / "projects").exists():
        left.append(str(long_path.plain(base / "projects")))
    else:
        removed.append("projects")
    folders = {str(folder): folder for folder in ms.agent_folder_index(refresh=True).values()}
    try:
        # A folder that lost its owner.json is still an agent folder under the agents root; its store for this account goes too.
        for child in agent_home.agents_root().iterdir():
            if child.is_dir():
                folders.setdefault(str(child), child)
    except OSError:
        pass
    for folder in folders.values():
        store = long_path.extended(folder / agent_home.AGENT_LOCAL_STATE_FOLDER / "memory" / ms.agent_account_folder(owner), 40)
        if store.exists() or store.is_symlink():
            if _rmtree_owned(store, folder):
                removed.append("agent")
            else:
                left.append(str(long_path.plain(store)))
    return {"state": "deleted" if not left else "incomplete", "removed": sorted(set(removed)), "left": left}


# --- command line -------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memory_split", description="Move memory rows into their own stores; one JSON line per call")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    start_p = commands.add_parser("start")
    start_p.add_argument("--homes-ready", action="store_true")
    start_p.add_argument("--engine", action="append", default=[])
    commands.add_parser("engines").add_argument("--engine", action="append", default=[])
    step_p = commands.add_parser("step")
    step_p.add_argument("--max-batches", type=int, default=50)
    step_p.add_argument("--budget-seconds", type=float, default=2.0)
    step_p.add_argument("--batch-rows", type=int, default=BATCH_ROWS)
    step_p.add_argument("--rescan", action="store_true")
    step_p.add_argument("--no-vacuum", action="store_true", help="never VACUUM in this call (the app runs `vacuum` as it ends)")
    step_p.add_argument("--jsonl", action="store_true", help="also print one JSON line per batch before the final line")
    vacuum_p = commands.add_parser("vacuum", help="one VACUUM of the root when it is worth it; reports bytes only when it ran")
    vacuum_p.add_argument("--timeout-seconds", type=float, default=5.0)
    revert_p = commands.add_parser("revert")
    revert_p.add_argument("--merge-back", action="store_true")
    commands.add_parser("forget").add_argument("--memory-id", required=True)
    commands.add_parser("delete-account")
    forget_agent_p = commands.add_parser("forget-agent", help="call BEFORE the agent's folder is deleted; --alias repeats for the ids in its owner.json ids[]")
    forget_agent_p.add_argument("--agent-id", required=True)
    forget_agent_p.add_argument("--alias", action="append", default=[], help="another id of the same agent (owner.json ids[]); used when the folder is already gone")
    forget_project_p = commands.add_parser("forget-project", help="call BEFORE the project's folder is deleted, with both --project-id (the uid) and --project-path")
    forget_project_p.add_argument("--project-id", default=None)
    forget_project_p.add_argument("--project-path", default=None)
    args = parser.parse_args(argv)
    from .memory_runtime import owner_binding
    owner = owner_binding(create=False)
    if not owner:
        print(_json({"state": "deferred", "reason": "owner_unbound"}))
        return 0
    try:
        result = _run_command(args, owner)
    except sqlite3.OperationalError as error:
        if args.command != "step" or not _locked(error):
            raise                      # the other commands keep their behaviour: a half-done forget or revert must not read as "busy"
        # A ``step`` whose write lock on the root was held by another writer (a hook, the desktop) for the whole wait: a batch is one transaction, so nothing of it is left half-done and the answer is the one a held mover lock already
        # gets (``busy``; safe to call again), never a traceback (#15).
        result = {"state": "busy", "reason": "locked"}
    print(_json(result))
    return 0


def _run_command(args: argparse.Namespace, owner: str) -> dict[str, Any]:
    if args.command == "engines":
        result = engine_inventory(args.engine)
    elif args.command == "status":
        result = status(owner)
    elif args.command == "start":
        result = start(owner, homes_ready=args.homes_ready, extra_engines=args.engine)
    elif args.command == "step":
        result = step(owner, max_batches=args.max_batches, budget_seconds=args.budget_seconds, rescan=args.rescan, batch_rows=args.batch_rows,
                      progress=(lambda event: print(_json(event), flush=True)) if args.jsonl else None, vacuum=not args.no_vacuum)
    elif args.command == "vacuum":
        result = vacuum_root(owner, timeout_seconds=args.timeout_seconds)
    elif args.command == "revert":
        result = revert(owner, merge_back=args.merge_back)
    elif args.command == "forget":
        result = forget(owner, args.memory_id)
    elif args.command == "forget-agent":
        result = forget_agent(owner, args.agent_id, args.alias)
    elif args.command == "forget-project":
        result = forget_project(owner, args.project_id, args.project_path)
    else:
        result = delete_account_stores(owner)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
