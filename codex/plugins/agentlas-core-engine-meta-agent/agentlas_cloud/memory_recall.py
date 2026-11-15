"""Active, read-only recall over this machine's Agentlas memory store.

The owner memory store (``memory.sqlite``) is shared with Agentlas Desktop and
the terminal and is only ever opened read-only here. Search runs over a
rebuildable side index (``recall-index.sqlite``) next to it. Every result is
re-checked against the store before it is returned, so a stale index can never
surface a superseded, disabled or forgotten memory.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
from array import array
from collections import OrderedDict
from datetime import datetime, timezone
from operator import mul
from pathlib import Path
from typing import Any, Iterable

from .project_identity import canonical_spelling

INDEX_SCHEMA = "agentlas.memory-recall-index.v1"
INDEX_ENV = "AGENTLAS_MEMORY_RECALL_INDEX"
LIVE_SCOPES = frozenset({"user_identity", "team_memory", "agent_repo", "project"})
CONFIDENCE = {"high": 1.0, "medium": 0.6, "low": 0.2}
TEXT_LIMIT = 600
ENTRY_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9:._/+=-]{0,511}"
"""The one grammar of a memory line's id (after the ``m:`` / ``e:`` prefix the model sees): ASCII letters and digits first, then ``: . _ / + = -``, 512 characters at most. ``get`` accepts nothing else, and a line
whose id is outside it is never brought in by ``one_pack`` (an id reaches the model as ``canonical[kind; source=<id>]`` and as ``m:<id>``)."""
ENTRY_ID_MAX_CHARS = 512
ENTRY_ID_RE = re.compile(ENTRY_ID_PATTERN)
LABELS_REVISION = "1"  # the index carries origin_class / certainty; an index without this key is brought level once
SYNC_BUDGET_SECONDS = 2.5
VECTOR_FLOOR, CJK_VECTOR_FLOOR, RELATIVE_FLOOR = 0.15, 0.12, 0.72
RELATED_SIMILARITY = 0.55
_CJK = re.compile(r"[ᄀ-ᇿ぀-ヿ㄰-㆏㐀-鿿가-힯]")


class RecallError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- store access -----------------------------------------------------------

def _owner() -> str:
    from .memory_runtime import owner_binding
    owner = owner_binding(create=False)
    if not owner:
        raise RecallError("memory_store_absent")
    return owner


def _store_path(owner: str) -> Path:
    from .memory_runtime import memory_path
    path = memory_path(owner)
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise RecallError("memory_store_symlink")
    return path


def _index_path(store: Path) -> Path:
    explicit = os.environ.get(INDEX_ENV, "").strip()
    return Path(explicit).expanduser() if explicit else store.parent / "recall-index.sqlite"


READ_BUSY_SECONDS = 0.5
"""How long a read-only open waits for a writer's lock. The hook sets it to 0.1 for the recall after its first read (the previous turn's summary) already
waited this long and found the store busy: one wait per hook, not two."""


def _read_only(path: Path) -> sqlite3.Connection:
    from . import long_path
    from .memory_runtime import assert_read_root_isolated
    assert_read_root_isolated(path)
    db = sqlite3.connect(long_path.raw_read_only_uri(path), uri=True, timeout=READ_BUSY_SECONDS)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=1")
    return db


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _applicability(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        return {"enabled": False}
    return value if isinstance(value, dict) else {"enabled": False}


def _recallable(applicability: dict[str, Any]) -> bool:
    return applicability.get("enabled") is not False and applicability.get("recallChannel") in (None, "default")


def _store_signature(db: sqlite3.Connection) -> str:
    revision = db.execute("SELECT value FROM memory_store_meta WHERE key='revision'").fetchone()
    epoch = db.execute("SELECT epoch FROM memory_forget_clock WHERE id=1").fetchone() if _has_table(db, "memory_forget_clock") else None
    # A project or agent store has no episode ledger (that stays in the root store).
    episodes = (db.execute("SELECT count(*), max(created_at) FROM memory_episodes WHERE summary IS NOT NULL").fetchone()
                if _has_table(db, "memory_episodes") else (0, None))
    return _sha(json.dumps([revision[0] if revision else None, epoch[0] if epoch else 0, episodes[0], episodes[1]]))


def _has_columns(db: sqlite3.Connection, table: str, *names: str) -> bool:
    return set(names) <= {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _live_memories(db: sqlite3.Connection) -> Iterable[dict[str, Any]]:
    native = _has_table(db, "memory_entry_native")
    labelled = _has_columns(db, "memory_entries", "origin_class", "certainty")  # a store from before the two columns has none: no label, tier "none"
    rows = db.execute(
        "SELECT e.id,e.scope,e.kind,e.content,e.project_id,e.project_path,e.agent_id,e.chat_id,e.confidence,"
        "e.sensitivity,e.created_at,b.applicability_json" + (",n.content_native" if native else ",NULL AS content_native") +
        (",e.origin_class,e.certainty" if labelled else ",NULL AS origin_class,NULL AS certainty") +
        " FROM memory_entries e LEFT JOIN memory_identity_bindings b ON b.memory_id=e.id" +
        (" LEFT JOIN memory_entry_native n ON n.entry_id=e.id" if native else "") +
        " WHERE e.superseded_at IS NULL AND e.content<>''")
    for row in rows:
        applicability = _applicability(row["applicability_json"])
        if row["scope"] not in LIVE_SCOPES or row["sensitivity"] == "secret" or not _recallable(applicability):
            continue
        text = (row["content"] or "")[:4000]
        native_text = (row["content_native"] or "")[:4000] or None
        policy = json.dumps([row["scope"], row["kind"], row["project_id"], row["project_path"], row["agent_id"],
                             row["sensitivity"], row["confidence"], applicability], sort_keys=True)
        yield {"id": "m:" + row["id"], "type": "memory", "kind": row["kind"], "scope": row["scope"],
               "project_id": row["project_id"], "project_path": row["project_path"],
               "project_path_hash": _sha(row["project_path"]) if row["project_path"] else None,
               "agent_id": row["agent_id"], "chat_id": row["chat_id"], "ticket_id": None,
               "sensitivity": row["sensitivity"], "confidence": row["confidence"], "created_at": row["created_at"],
               "origin_class": row["origin_class"], "certainty": row["certainty"],
               "content_hash": _sha(text + "\0" + (native_text or "") + "\0" + policy), "text": text, "text_native": native_text}


def _live_episodes(db: sqlite3.Connection) -> Iterable[dict[str, Any]]:
    if not _has_table(db, "memory_episodes"):
        return
    quarantine = " AND p.ticket_id NOT IN (SELECT ticket_id FROM memory_episode_quarantines)" if _has_table(db, "memory_episode_quarantines") else ""
    for row in db.execute(
            "SELECT p.episode_id,p.ticket_id,p.project_id,p.project_path_hash,p.agent_id,p.chat_id,p.summary,p.created_at "
            "FROM memory_episodes p WHERE p.summary IS NOT NULL AND p.summary<>''" + quarantine):
        text = (row["summary"] or "")[:4000]
        yield {"id": "e:" + row["episode_id"], "type": "episode", "kind": "episode", "scope": None,
               "project_id": row["project_id"], "project_path": None, "project_path_hash": row["project_path_hash"],
               "agent_id": row["agent_id"], "chat_id": row["chat_id"], "ticket_id": row["ticket_id"],
               "sensitivity": None, "confidence": None, "created_at": row["created_at"], "origin_class": None, "certainty": None,
               "content_hash": _sha(text + "\0" + (row["project_path_hash"] or "")), "text": text, "text_native": None}


# --- vectors ----------------------------------------------------------------

_ADAPTER: Any = None
_ADAPTER_LOCK = threading.Lock()


def _adapter() -> Any:
    global _ADAPTER
    with _ADAPTER_LOCK:
        if _ADAPTER is None:
            from ontology.embeddings import select_vector_adapter
            _ADAPTER = select_vector_adapter("auto")
        return _ADAPTER


def _adapter_identity(adapter: Any) -> str:
    return f"{adapter.name}:{getattr(adapter, 'identity', '')}:{adapter.dimensions}"


def _pack(vector: list[float]) -> bytes:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return array("b", (max(-127, min(127, round(value / norm * 127))) for value in vector)).tobytes()


def _unpack(blob: bytes) -> tuple[array, float]:
    values = array("f", array("b", blob))
    return values, math.sqrt(sum(map(mul, values, values))) or 1.0


def _embed(text: str) -> tuple[array, float]:
    return _unpack(_pack(_adapter().embed(text[:4000])))


# --- side index -------------------------------------------------------------

def _open_index(path: "Path | str") -> sqlite3.Connection:
    in_memory = str(path) == ":memory:"
    if not in_memory and Path(path).is_symlink():
        raise RecallError("memory_recall_index_symlink")
    created = not in_memory and not Path(path).exists()
    db = sqlite3.connect(str(path), timeout=5, check_same_thread=not in_memory)
    db.row_factory = sqlite3.Row
    if created and os.name == "posix":
        os.chmod(path, 0o600)
    db.executescript(
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, type TEXT NOT NULL, kind TEXT, scope TEXT,"
        " project_id TEXT, project_path TEXT, project_path_hash TEXT, agent_id TEXT, chat_id TEXT, ticket_id TEXT,"
        " sensitivity TEXT, confidence TEXT, created_at TEXT NOT NULL, content_hash TEXT NOT NULL,"
        " text TEXT NOT NULL, text_native TEXT, vec BLOB NOT NULL, origin_class TEXT, certainty TEXT);"
        "CREATE INDEX IF NOT EXISTS items_created ON items(created_at);"
        "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(id UNINDEXED, text, text_native,"
        " tokenize='unicode61 remove_diacritics 2');")
    if not _has_columns(db, "items", "origin_class", "certainty"):
        # An index from before the two tie labels are added in place. The labels are not part of the content hash (a label change must not
        # embed a line again); the sync below fills them once and keeps them equal to the store's.
        db.execute("ALTER TABLE items ADD COLUMN origin_class TEXT")
        db.execute("ALTER TABLE items ADD COLUMN certainty TEXT")
        db.commit()
    return db


def _meta(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))


def _repair_empty_vectors(index_db: sqlite3.Connection, adapter: Any, started: float, budget_seconds: float) -> None:
    """Re-embed items stored with an all-zero vector under an older segmentation (embeddings.SEGMENTATION_REVISION).

    Other items embed the same as before, so only these are redone, inside the sync budget; the meta key ends the
    scan once a pass finishes.
    """
    from ontology.embeddings import SEGMENTATION_REVISION

    revision = str(SEGMENTATION_REVISION)
    if _meta(index_db, "empty_vector_repair") == revision:
        return
    rows = index_db.execute(
        "SELECT id, text FROM items WHERE vec = zeroblob(length(vec)) AND length(trim(text)) > 0").fetchall()
    done = 0
    for row in rows:
        if time.monotonic() - started > budget_seconds:
            break
        index_db.execute("UPDATE items SET vec = ? WHERE id = ?", (_pack(adapter.embed(row["text"])), row["id"]))
        done += 1
    if done:
        _set_meta(index_db, "generation", str(int(_meta(index_db, "generation") or 0) + 1))
    if done == len(rows):
        _set_meta(index_db, "empty_vector_repair", revision)
    index_db.commit()


def _index_priority(row: dict[str, Any]) -> int:
    """Which lines the index takes first when it cannot take all of them in one call (; before it the NEWEST went first, so on a 6,000-line store
    the oldest rule was searched on the 10th call): 0 = Personal lines and lines the person said, 1 = the rule kinds, 2 = other lines, 3 = turn records.
    Only structured columns are read (scope, origin, kind), never the words. Inside a class the newest is first."""
    if row["type"] != "memory":
        return 3
    if row["scope"] == "user_identity" or row.get("origin_class") == "user":
        return 0
    return 1 if row["kind"] in ("decision", "procedure", "risk", "preference", "boundary") else 2


def sync_index(store_db: sqlite3.Connection, index_db: sqlite3.Connection, *,
               budget_seconds: float = SYNC_BUDGET_SECONDS) -> dict[str, Any]:
    """Bring the side index in line with the store; stop at the time budget."""
    started = time.monotonic()
    adapter = _adapter()
    identity = _adapter_identity(adapter)
    signature = _store_signature(store_db)
    if _meta(index_db, "schema") != INDEX_SCHEMA or _meta(index_db, "adapter") != identity:
        index_db.execute("DELETE FROM items")
        index_db.execute("DELETE FROM items_fts")
        _set_meta(index_db, "schema", INDEX_SCHEMA)
        _set_meta(index_db, "adapter", identity)
        _set_meta(index_db, "store_signature", "")
        index_db.commit()
    _repair_empty_vectors(index_db, adapter, started, budget_seconds)
    if _meta(index_db, "store_signature") == signature and _meta(index_db, "labels") == LABELS_REVISION:
        total = index_db.execute("SELECT count(*) FROM items").fetchone()[0]
        return {"indexed": total, "pending": 0, "changed": 0, "partial": False}
    live = {row["id"]: row for row in (*_live_memories(store_db), *_live_episodes(store_db))}
    indexed = {row[0]: row[1] for row in index_db.execute("SELECT id, content_hash FROM items")}
    relabelled = 0
    for row in index_db.execute("SELECT id, origin_class, certainty FROM items").fetchall():
        line = live.get(row[0])
        if line is not None and (line["origin_class"], line["certainty"]) != (row[1], row[2]):
            index_db.execute("UPDATE items SET origin_class=?, certainty=? WHERE id=?", (line["origin_class"], line["certainty"], row[0]))
            relabelled += 1
    stale = [key for key, digest in indexed.items() if key not in live or live[key]["content_hash"] != digest]
    for start in range(0, len(stale), 500):
        chunk = stale[start:start + 500]
        marks = ",".join("?" * len(chunk))
        index_db.execute(f"DELETE FROM items WHERE id IN ({marks})", chunk)
        index_db.execute(f"DELETE FROM items_fts WHERE id IN ({marks})", chunk)
    stale_set = set(stale)
    missing = sorted((row for key, row in live.items() if key not in indexed or key in stale_set),
                     key=lambda row: row["created_at"] or "", reverse=True)
    missing.sort(key=_index_priority)  # stable: inside one class the newest is still first
    added = 0
    for row in missing:
        if time.monotonic() - started > budget_seconds:
            break
        vector = _pack(adapter.embed(row["text"]))
        index_db.execute(
            "INSERT OR REPLACE INTO items(id,type,kind,scope,project_id,project_path,project_path_hash,agent_id,chat_id,"
            "ticket_id,sensitivity,confidence,created_at,content_hash,text,text_native,vec,origin_class,certainty) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], row["type"], row["kind"], row["scope"], row["project_id"], row["project_path"], row["project_path_hash"],
             row["agent_id"], row["chat_id"], row["ticket_id"], row["sensitivity"], row["confidence"], row["created_at"],
             row["content_hash"], row["text"], row["text_native"], vector, row["origin_class"], row["certainty"]))
        index_db.execute("INSERT INTO items_fts(id,text,text_native) VALUES(?,?,?)", (row["id"], row["text"], row["text_native"] or ""))
        added += 1
    pending = len(missing) - added
    waiting = missing[added:]
    if pending == 0:
        _set_meta(index_db, "store_signature", signature)
        _set_meta(index_db, "labels", LABELS_REVISION)
    if stale or added or relabelled:
        _set_meta(index_db, "generation", str(int(_meta(index_db, "generation") or 0) + 1))
    index_db.commit()
    total = index_db.execute("SELECT count(*) FROM items").fetchone()[0]
    return {"indexed": total, "pending": pending, "changed": len(stale) + added + relabelled, "partial": pending > 0, "pending_rows": waiting}


# Rows kept between calls are bounded: at most _CACHE_MAX_INDEXES indexes and _CACHE_MAX_ITEMS rows in all
# (about 1.5-2.6 KB per row). An index larger than the row bound is read for the call that needs it and
# released with that call; it is never kept, so one very large store cannot hold the process hostage.
# Only the long-lived MCP stdio server benefits: hooks and the CLI are a new process per call. Measured at
# 50,000 rows: bound 20,000 -> warm search p50 1,136 ms; bound 60,000 -> 343 ms but resident memory 277 -> 520 MB
# (+243 MB), so the bound stays at 20,000. Once the stores are split per agent/project each is far below it.
# The old entry is dropped before a changed index is read again, so a refresh never holds two copies.
# Next change (not done here): keep only id, int8 vector, norm and filter columns instead of whole rows.
_CACHE_MAX_INDEXES = 8
_CACHE_MAX_ITEMS = 20_000
_CACHE: OrderedDict[str, tuple[str, list[dict[str, Any]]]] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _cached_items(index_path: Path, index_db: sqlite3.Connection) -> list[dict[str, Any]]:
    generation = _meta(index_db, "generation") or "0"
    key = str(index_path)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == generation:
            _CACHE.move_to_end(key)
            return hit[1]
        _CACHE.pop(key, None)  # stale or absent: release it before the replacement is read
    items = []
    for row in index_db.execute("SELECT * FROM items"):
        item = dict(row)
        item["vector"], item["norm"] = _unpack(item.pop("vec"))
        items.append(item)
    with _CACHE_LOCK:
        _CACHE.pop(key, None)
        if len(items) <= _CACHE_MAX_ITEMS:
            _CACHE[key] = (generation, items)
            while len(_CACHE) > _CACHE_MAX_INDEXES or sum(len(entry[1]) for entry in _CACHE.values()) > _CACHE_MAX_ITEMS:
                _CACHE.popitem(last=False)
    return items


# --- policy -----------------------------------------------------------------

class _Folder(tuple):
    """``(path, hash)`` of the folder a read is bound to, exactly the pair it always was; ``also`` holds the folders an older engine bound the same session to (EK4): the folder as it was given
    (a sub-folder of a project with no project state used to be a project of its own), as paths and as hashes. A record stamped with one of them is still read there."""

    also_paths: tuple[str, ...] = ()
    also_hashes: frozenset[str] = frozenset()

    def __new__(cls, path: str | None, digest: str | None, also: tuple[str, ...] = ()) -> "_Folder":
        self = super().__new__(cls, (path, digest))
        self.also_paths = tuple(dict.fromkeys(a for a in also if a and a != path))
        self.also_hashes = frozenset(_sha(a) for a in self.also_paths)
        return self


def _project(project_dir: str | None) -> _Folder:
    raw = project_dir or os.getcwd()
    try:
        given = Path(raw).expanduser().resolve()
        path = Path(canonical_spelling(str(given)))  # EK4: the disk's spelling, the one the hook stamps on a turn and the desktop hashes
        home = Path(canonical_spelling(str(Path.home().resolve())))
    except (OSError, RuntimeError):
        return _Folder(None, None)
    if not path.is_dir() or path == Path(path.anchor) or path == home:
        return _Folder(None, None)
    bound = _bound_folder(path)
    return _Folder(str(bound), _sha(str(bound)), (str(path), str(given)))


def _bound_folder(path: Path) -> Path:
    """The folder a line is bound to, the same one the hook stamps a turn record with (``memory_runtime.hook_project_binding``, EK4): the nearest folder with project state, else the nearest
    repository or manifest root above, else the folder itself. A reader that hashed the folder as given would not find what the hook wrote from a sub-folder."""
    try:
        from .memory_hook import _project_walk
        root, boundary = _project_walk(path)
        return root or boundary or path
    except Exception:  # noqa: BLE001 - the folder as given is the safe answer
        return path


def _project_ref() -> str | None:
    """The project id the host named (``AGENTLAS_MEMORY_PROJECT_REF``), as the hook has always read it; a value that is not a plain id counts as none."""
    raw = (os.environ.get("AGENTLAS_MEMORY_PROJECT_REF") or "").strip()
    if not raw:
        return None
    from .memory_runtime import _safe_id
    try:
        return _safe_id(raw)
    except ValueError:
        return None


def _allowed(item: dict[str, Any], *, scope: str, project: tuple[str | None, str | None],
             include_confidential: bool, project_ref: str | None = None) -> bool:
    """The one reader rule of a store line, for the turn-start hook and for the ``memory.*`` tools alike.

    A project-bound line is read when the folder is its project: the path hash is the folder's, or (no path on the line) the line's
    project id is the host's ``AGENTLAS_MEMORY_PROJECT_REF``; a line that names an id must name this one (before the tools looked at
    the path only and the hook at both: one reader now). An agent line bound to a project follows the same two checks."""
    path, path_hash = project
    item_hash = item.get("project_path_hash")
    also = getattr(project, "also_hashes", ())
    ref = project_ref if project_ref is not None else _project_ref()
    pid = item.get("project_id")
    same_path = bool(item_hash and (item_hash == path_hash or item_hash in also))
    this_project = (item_hash is None or same_path) and (not pid or (ref is not None and pid == ref))
    if item["type"] == "episode":
        return scope == "owner_all" or item_hash is None or same_path
    if item.get("sensitivity") == "secret":
        return False
    if item.get("sensitivity") == "confidential" and not (include_confidential and (same_path or (ref is not None and pid == ref))):
        return False
    if scope == "owner_all":
        return True
    if item["scope"] == "team_memory":
        return True
    if item["scope"] == "user_identity":
        return item_hash is None or same_path  # a Personal line that names a folder belongs to that folder (the hook always read it so; the tools read it everywhere)
    if item["scope"] == "project":
        return (item_hash is not None or bool(pid)) and this_project
    if item["scope"] == "agent_repo":
        return this_project
    return False


def _in_range(item: dict[str, Any], since: str | None, until: str | None) -> bool:
    created = _normal_time(item.get("created_at"))
    return (not since or created >= since) and (not until or created <= until)


def _normal_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _time_bound(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    normalized = _normal_time(value)
    if not normalized or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", normalized):
        raise RecallError(f"memory_{field}_invalid")
    return normalized


# --- re-check against the store ---------------------------------------------

def _recheck(store_db: sqlite3.Connection, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    memories = [item["id"][2:] for item in items if item["type"] == "memory"]
    episodes = [item["id"][2:] for item in items if item["type"] == "episode"]
    alive: dict[str, str] = {}
    if memories:
        marks = ",".join("?" * len(memories))
        native = _has_table(store_db, "memory_entry_native")
        for row in store_db.execute(
                "SELECT e.id,e.content,e.scope,e.kind,e.project_id,e.project_path,e.agent_id,e.sensitivity,e.confidence,"
                "b.applicability_json" + (",n.content_native" if native else ",NULL AS content_native") +
                " FROM memory_entries e LEFT JOIN memory_identity_bindings b ON b.memory_id=e.id" +
                (" LEFT JOIN memory_entry_native n ON n.entry_id=e.id" if native else "") +
                f" WHERE e.id IN ({marks}) AND e.superseded_at IS NULL AND e.content<>''", memories):
            applicability = _applicability(row["applicability_json"])
            if row["scope"] in LIVE_SCOPES and row["sensitivity"] != "secret" and _recallable(applicability):
                text = (row["content"] or "")[:4000]
                native_text = (row["content_native"] or "")[:4000]
                policy = json.dumps([row["scope"], row["kind"], row["project_id"], row["project_path"], row["agent_id"],
                                     row["sensitivity"], row["confidence"], applicability], sort_keys=True)
                alive["m:" + row["id"]] = _sha(text + "\0" + native_text + "\0" + policy)
    if episodes:
        marks = ",".join("?" * len(episodes))
        quarantine = " AND ticket_id NOT IN (SELECT ticket_id FROM memory_episode_quarantines)" if _has_table(store_db, "memory_episode_quarantines") else ""
        for row in store_db.execute(
                f"SELECT episode_id,summary,project_path_hash FROM memory_episodes WHERE episode_id IN ({marks}) "
                f"AND summary IS NOT NULL AND summary<>''" + quarantine, episodes):
            alive["e:" + row["episode_id"]] = _sha((row["summary"] or "")[:4000] + "\0" + (row["project_path_hash"] or ""))
    return [item for item in items if alive.get(item["id"]) == item["content_hash"]]


# --- ranking ----------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    from ontology.embeddings import tokenize
    return {token for token in tokenize(text.lower()) if len(token) > 1 or _CJK.match(token)}


def _fts_terms(query: str) -> str | None:
    terms = [term for term in re.findall(r"\w+", query.lower()) if len(term) > 1][:24]
    return " OR ".join('"' + term.replace('"', "") + '"' for term in terms) or None


def _lexical_hits(index_db: sqlite3.Connection, query: str, limit: int = 2000) -> dict[str, int]:
    """FTS5 BM25 rank position per item id (0 = best); rare terms weigh more."""
    terms = _fts_terms(query)
    if not terms:
        return {}
    try:
        rows = index_db.execute(
            "SELECT id FROM items_fts WHERE items_fts MATCH ? ORDER BY bm25(items_fts) LIMIT ?", (terms, limit)).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row[0]: position for position, row in enumerate(rows)}


PER_STORE_LEXICAL = 200


def _lexical_merged(indexes: list[sqlite3.Connection], query: str) -> dict[str, int]:
    """BM25 positions over several stores: each store's best PER_STORE_LEXICAL, ordered together by their scores
    (a position inside one store means nothing next to another store's)."""
    terms = _fts_terms(query)
    if not terms:
        return {}
    scored: list[tuple[float, str]] = []
    for index_db in indexes:
        try:
            scored.extend((row[1], row[0]) for row in index_db.execute(
                "SELECT id,bm25(items_fts) FROM items_fts WHERE items_fts MATCH ? ORDER BY bm25(items_fts) LIMIT ?",
                (terms, PER_STORE_LEXICAL)))
        except sqlite3.OperationalError:
            continue
    scored.sort(key=lambda pair: (pair[0], pair[1]))
    positions: dict[str, int] = {}
    for _, ident in scored:
        positions.setdefault(ident, len(positions))
    return positions


LEXICAL_WEIGHT = 0.3
LEXICAL_DECAY = 5.0
LEXICAL_MIN_VECTOR = 0.30
STRONG_VECTOR = 0.55
LEXICAL_STRONG_RANK = 10
LEXICAL_STRONG_VECTOR = 0.45
STRONG_LEXICAL = 0.5  # contract lexical score (token overlap) from which a line with no model vector counts as a strong match
MIN_VECTOR = 0.35


def _rank(query: str, items: list[dict[str, Any]], hits: dict[str, int]) -> list[tuple[float, float, float, dict[str, Any]]]:
    """Semantic similarity first, BM25 as a bounded boost, with an explicit match strength.

    Returns (score, lexical, vector, item); lexical is 1/(1+bm25 position/5) or 0.
    A shared common word alone is not evidence: lexical only counts when the
    row is also semantically close, so a short query does not return the
    least-unrelated rows of a large store (measured on the owner store,
    2026-11-03: '틱톡 채널 분석' lost its 0.47 match to 0.34 rows sharing '분석').
    """
    query_vector, query_norm = _embed(query)
    floor = CJK_VECTOR_FLOOR if _CJK.search(query) else VECTOR_FLOOR
    vectors = [(sum(map(mul, query_vector, item["vector"])) / (query_norm * item["norm"]), item) for item in items]
    best = max((vector for vector, _ in vectors), default=0.0)
    threshold = max(floor, RELATIVE_FLOOR * best)
    ranked = []
    for vector, item in vectors:
        position = hits.get(item["id"])
        lexical = 1.0 / (1 + position / LEXICAL_DECAY) if position is not None and vector >= LEXICAL_MIN_VECTOR else 0.0
        if vector < threshold and lexical == 0.0:
            continue
        strong = vector >= STRONG_VECTOR or (position is not None and position < LEXICAL_STRONG_RANK and vector >= LEXICAL_STRONG_VECTOR)
        score = vector + LEXICAL_WEIGHT * lexical + 0.002 * CONFIDENCE.get(item.get("confidence") or "", 0.0)
        ranked.append((score, lexical, vector, {**item, "_strong": strong}))
    ranked.sort(key=lambda entry: (entry[0], entry[3].get("created_at") or ""), reverse=True)
    return ranked


# --- the one recall contract -------------------------------
# The turn-start hook and the memory.search tool rank, break ties and print a line through the functions below, which hand the work to
# memory_recall_v2 (', ruleset ``recall``: the weighted sum ``lexical + 0.05 x (vector - floor)`` + 0.002 x prior, floor 0.15 / 0.12 for
# a Korean/Chinese/Japanese query, a vector counts from 72% of the best one; ties on tier, newer, id). ``_rank`` above (BM25 position + vector)
# stays only for memory.crosscheck, which finds related statements and recalls nothing.

RECENT_LIMIT = 5
"""Turn records (the "what was done recently" layer) a memory.search answers: their own list, never mixed into the lines."""


def _vectors_ready() -> bool:
    """The contract has no hash vectors: a caller without the model vectors gives none and the ranking is lexical alone."""
    try:
        return getattr(_adapter(), "status", "") == "available"
    except ValueError:  # the verified model asset is not usable: no vectors, the ranking is lexical alone
        return False


def bare_id(item: dict[str, Any]) -> str:
    """The id a ticket's ``targets`` takes: the line's own id without the ``m:`` the tools name it by (an episode keeps ``e:``)."""
    value = str(item["id"])
    return value[2:] if value.startswith("m:") else value


def display_line(item: dict[str, Any]) -> str:
    """The one way a recalled line is shown to a model: ``[id · kind] text``. The id is what ``memory.record`` takes in ``targets``."""
    return "[" + bare_id(item) + " \u00b7 " + str(item.get("kind") or "") + "] " + " ".join(str(item["text"][:TEXT_LIMIT]).split())


def contract_lines(query: str | None, items: list[dict[str, Any]], *, vectors: bool | None = None) -> list[dict[str, Any]]:
    """``items`` as memory_recall_v2 lines: the vector score of each against ``query`` (given only when the model vectors are loaded), the two
    tie labels, the dates. ``store`` is one key: who may read a line was decided before (``_allowed`` and the session's reader rules)."""
    use_vectors = bool(query and items) and (_vectors_ready() if vectors is None else vectors)  # no query, no model to load
    query_vector = _embed(query) if use_vectors else None
    lines = []
    for item in items:
        vector = None
        if query_vector is not None and item.get("vector") is not None:  # a line the index has not taken yet has no vector: its words decide
            vector = sum(map(mul, query_vector[0], item["vector"])) / (query_vector[1] * item["norm"])
        lines.append({"id": item["id"], "kind": item.get("kind") or "", "text": item["text"], "text_native": item.get("text_native"),
                      "vec": vector, "origin_class": item.get("origin_class"), "certainty": item.get("certainty"),
                      "created_at": item.get("created_at"), "store": "s", "project": None})
    return lines


CONTRACT_READER = {"stores": ["s"], "project": None, "history": False}


def contract_rank(query: str, items: list[dict[str, Any]], *, vectors: bool | None = None) -> list[dict[str, Any]]:
    """The contract order of ``items`` for ``query``: ``[{item, lexical, vector, semantic, score}]``, best first.

    A line is a candidate when its words match or its vector counts (memory_recall_v2.rank); nothing else is returned."""
    from . import memory_recall_v2 as v2
    lines = contract_lines(query, items, vectors=vectors)
    by_id = {item["id"]: item for item in items}
    given = {line["id"]: line["vec"] for line in lines}
    query_tokens = set(v2.tokens(query))
    out = []
    for row in v2.rank(query, lines):
        item = by_id[row["id"]]
        lexical = v2.lexical(query_tokens, item["text"], item.get("kind") or "")
        if item.get("text_native"):
            lexical = max(lexical, v2.lexical(query_tokens, item["text_native"], item.get("kind") or ""))
        out.append({"item": item, "lexical": lexical, "vector": given[row["id"]], "semantic": row["semantic"], "score": row["score"]})
    return out


def contract_recent(items: list[dict[str, Any]], *, query: str | None = None, limit: int = RECENT_LIMIT, vectors: bool | None = None) -> list[dict[str, Any]]:
    """The turn-record layer: the records that answer the query (the contract order), or with no query the newest ones, at most ``limit``."""
    if query:
        return [row["item"] for row in contract_rank(query, items, vectors=vectors)[:limit]]
    return sorted(items, key=lambda item: (_normal_time(item.get("created_at")), item["id"]), reverse=True)[:limit]


# --- output -----------------------------------------------------------------

def _age_days(created: Any) -> int | None:
    normalized = _normal_time(created)
    if not normalized:
        return None
    try:
        then = datetime.fromisoformat(normalized).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - then).days)


def _public(item: dict[str, Any], *, lexical: float | None = None, vector: float | None = None,
            show_project: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"id": item["id"], "type": item["type"], "kind": item["kind"],
                           "text": item["text"][:TEXT_LIMIT], "createdAt": item["created_at"],
                           "ageDays": _age_days(item["created_at"]), "source": "agentlas-memory", "line": display_line(item)}
    if item.get("text_native"):
        out["textNative"] = item["text_native"][:TEXT_LIMIT]
    for key, name in (("scope", "scope"), ("confidence", "confidence"), ("sensitivity", "sensitivity"),
                      ("agent_id", "agentId"), ("ticket_id", "ticketId")):
        if item.get(key):
            out[name] = item[key]
    if show_project and item.get("project_path"):
        out["projectName"] = Path(item["project_path"]).name
    if lexical is not None:
        out["score"] = {"lexical": round(lexical, 3), "vector": round(vector or 0.0, 3)}
    if "_strong" in item:
        out["match"] = "strong" if item["_strong"] else "weak"
    return out


# A store with fewer live rows than this and no index file of its own is searched from a throwaway in-memory index
# instead of getting a recall-index.sqlite file. Embedding costs about 0.4 ms per row (measured, short text), so this
# bound keeps one cold search of a small store near 60 ms; a bigger store earns an index beside it.
DIRECT_SCAN_ROWS = 150


# In-memory indexes of small stores, kept between calls of a long-lived process (the MCP server) so a repeated search
# does not embed them again. Bounded by count and by rows (each under DIRECT_SCAN_ROWS rows): the rows bound is the same
# 20,000 the shared cache keeps, so an owner_all recall over a few hundred small stores stays warm and the process holds
# no more than one big store's worth of rows (measured: fix-engine-2/bench-after.jsonl).
_DIRECT_MAX = 400
_DIRECT_MAX_ROWS = _CACHE_MAX_ITEMS
_DIRECT: OrderedDict[str, tuple[sqlite3.Connection, int]] = OrderedDict()


def _direct_index(key: str, rows: int = DIRECT_SCAN_ROWS) -> sqlite3.Connection:
    with _CACHE_LOCK:
        hit = _DIRECT.get(key)
        if hit is not None:
            _DIRECT.move_to_end(key)
            return hit[0]
    db = _open_index(":memory:")
    with _CACHE_LOCK:
        _DIRECT[key] = (db, rows)
        while len(_DIRECT) > 1 and (len(_DIRECT) > _DIRECT_MAX or sum(entry[1] for entry in _DIRECT.values()) > _DIRECT_MAX_ROWS):
            _DIRECT.popitem(last=False)[1][0].close()
    return db


class _Part:
    """One store taking part in a call: its read-only connection, its index and its indexed items."""

    def __init__(self, kind: str, store: sqlite3.Connection, index: sqlite3.Connection, items: list[dict[str, Any]], *, shared_index: bool = False):
        self.kind, self.store, self.index, self.items, self.shared_index = kind, store, index, items, shared_index

    def close(self) -> None:
        self.store.close()
        if not self.shared_index:
            self.index.close()


def _read_items(index_db: sqlite3.Connection) -> list[dict[str, Any]]:
    items = []
    for row in index_db.execute("SELECT * FROM items"):
        item = dict(row)
        item["vector"], item["norm"] = _unpack(item.pop("vec"))
        items.append(item)
    return items


class _NoRoom(Exception):
    """A store that would take the call past its row ceiling: it is not opened and the answer says so."""


# An owner_all call reads every store of the owner (the move to sub-stores spreads one root over many), nearest the
# current work first, until the rows of the others reach this ceiling or the call's time budget is spent; what is left is
# answered as notOpened and partial. 20,000 is the row bound the root's own index was kept under before the move
# (_CACHE_MAX_ITEMS), so a scope that found a line in the root finds it in the stores up to the same size.
OWNER_ALL_ROWS = 20_000
# The time an owner_all call may spend on the others' stores beyond the ordinary sync budget (a cold process embeds a
# small store's rows at about 0.4 ms each; 44 stores of 60 rows took 2.1 s measured).
OWNER_ALL_EXTRA_SECONDS = 3.0


class _Session:
    """One call's store connections, synced indexes and cached items.

    With the central layout (the default) this is exactly one store. With a split or newer layout it also opens the
    project's store and the answering agent's, and for ``owner_all`` the most recently used others, and reads them as
    one pool: one row per id, lexical rank merged across stores, each result re-checked against the store it came from.
    """

    def __init__(self, budget_seconds: float = SYNC_BUDGET_SECONDS, *, project_dir: str | None = None, scope: str = "default",
                 host: str | None = None):
        started = time.monotonic()
        self.host = host
        self.owner = _owner()
        self.store_path = _store_path(self.owner)
        self.coverage: dict[str, Any] = {"storeLocked": False, "partial": False}
        if not self.store_path.exists():
            raise RecallError("memory_store_absent")
        self.store = _read_only(self.store_path)
        self.index_path = _index_path(self.store_path)
        on_disk = True
        try:
            self.index = _open_index(self.index_path)
        except (sqlite3.Error, OSError):
            # A home the index file cannot be written to (read-only, full disk): the root is searched from an in-memory index, as a small store is.
            self.index = _direct_index(str(self.store_path), 10 ** 9)
            on_disk = False
        pending_rows: list[dict[str, Any]] = []
        try:
            status = sync_index(self.store, self.index, budget_seconds=budget_seconds)
            pending_rows = status.pop("pending_rows", [])
            self.coverage.update(status)
        except sqlite3.OperationalError as error:
            if "locked" not in str(error) and "busy" not in str(error):
                raise
            self.coverage.update(storeLocked=True, partial=True)
            # The store is busy (a writer's EXCLUSIVE commit): the first wait of 0.5 s was spent; every later read of this call fails at once instead of
            # waiting 0.5 s again (five waits in a row made the hook take 3.9 s under a lock the old hook gave up on in 1.0 s).
            self.store.execute("PRAGMA busy_timeout=0")
        adapter = _adapter()
        self.coverage["adapter"] = "local_model" if getattr(adapter, "status", "") == "available" else "degraded_hash"
        self.items = _cached_items(self.index_path, self.index) if on_disk else _read_items(self.index)
        self.parts: list[_Part] = [_Part("personal", self.store, self.index, self.items, shared_index=not on_disk)]
        self._part_of: dict[str, _Part] = {}
        # Lines the index has not taken yet are still read, by their words (no vector): a partly built index leaves no line blind.
        self.pending: list[dict[str, Any]] = [{**row, "vector": None, "norm": None} for row in pending_rows]
        from . import memory_stores
        if memory_stores.reads_union(self.store):
            self._open_union(memory_stores, started, budget_seconds, project_dir, scope)
        self.hub_actor = (os.environ.get("AGENTLAS_MEMORY_ACTOR_ID") or "").startswith("hub:")
        # the owner's Personal facts are read by the personal agent only; every other subject, an unnamed one included, does not get them.
        from . import memory_classify
        # With the workspace-rules switch on (read from the root store; a busy store counts as on: this tool hides what the switch hides) no
        # Personal line is read unless the host says this is the personal agent's own conversation (the flag) and the subject is the One family.
        self.items = self._reader_view(self.items)
        self.pending = self._reader_view(self.pending)

    def _reader_view(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """What the reader of this call may see of ``items`` (the Personal, turn-summary, Hub and own-agent rules)."""
        from . import memory_classify
        reader = os.environ.get("AGENTLAS_MEMORY_ACTOR_ID") or None
        rules = memory_classify.active()
        rules_on = memory_classify.workspace_rules_on(self.store, rules, locked=True) if rules is not None else False
        flag = memory_classify.personal_flag(rules)
        if not memory_classify.reads_personal(reader, None, rules_on, flag):
            items = [item for item in items if item.get("type") == "episode" or memory_classify.personal_visible(
                item.get("scope"), item.get("kind"), reader, None, rules_on, flag)]
            if rules_on:
                # A turn summary of the personal agent's own conversation (an episode of the One family) is read only by whoever may read Personal lines:
                # the same reader rule as the lines themselves. Before the switch the summaries stay as they were.
                from .memory_actor_family import is_one_memory_actor
                items = [item for item in items if not (item.get("type") == "episode" and is_one_memory_actor(item.get("agent_id")))]
        if self.hub_actor:
            # A borrowed Hub agent reads no agent memory; project and personal knowledge stay. It reads no turn summary either:
            # a summary is the owner's own conversation (E1; the guest rule of principle P10), switch or not.
            items = [item for item in items
                          if item.get("type") != "episode" and item.get("scope") != "agent_repo" and not str(item.get("agent_id") or "").startswith("hub:")]
        # Agentlas 2.0: each agent reads its own lines only, as the turn-start hook does. The subject is the
        # one the hook would have (``host_actor_id``: the environment's actor, else the host window's own ``host:*``); the ids it may read are
        # the hook's own function. A line of the own agent store is the agent's by where it lives; any other ``agent_repo`` line must carry
        # one of those ids. Turn summaries (episodes) are not touched: fixed who reads them (tests/test_memory_repair54.py), and the hook does not recall them.
        from .memory_runtime import host_actor_id, readable_agent_ids
        readable = set(readable_agent_ids(host_actor_id(self.host)))

        def mine(item: dict[str, Any]) -> bool:
            if item.get("type") == "episode" or item.get("scope") != "agent_repo":
                return True
            part = self._part_of.get(item["id"])
            return (part is not None and part.kind == "agent") or item.get("agent_id") in readable

        items = [item for item in items if mine(item)]
        return items

    def _open_union(self, stores: Any, started: float, budget_seconds: float, project_dir: str | None, scope: str) -> None:
        refs = stores.stores_for_context(
            self.owner, project_path=_project(project_dir)[0], project_ref_hint=os.environ.get("AGENTLAS_MEMORY_PROJECT_REF") or None,
            actor=os.environ.get("AGENTLAS_MEMORY_ACTOR_ID") or None)
        folder = _project(project_dir)
        for older in folder.also_paths:  # EK4: a project store an older engine opened for the folder as it was given is still read (read only, never written)
            for ref in stores.stores_for_context(self.owner, project_path=older, project_ref_hint=None, actor=None):
                if ref.kind == "project" and ref not in refs:
                    refs.append(ref)
        skipped: list[str] = []
        extra = 0
        context_refs = set(refs)
        project_hash = folder[1]
        hub = (os.environ.get("AGENTLAS_MEMORY_ACTOR_ID") or "").startswith("hub:")
        wide: set[Any] = set()
        room = OWNER_ALL_ROWS
        if scope == "owner_all":
            more, _ = stores.recent_stores(self.owner, refs, limit=10 ** 9)
            # No agent's store but the reader's own is opened (it is already among ``refs``): "every project" is not "every agent"
            # (Agentlas 2.0; for a borrowed Hub agent,/ for the rest).
            more = [ref for ref in more if ref.kind != "agent"]
            refs = [*refs, *more]
            wide = set(more)
        forgotten = stores.forgotten_ids(self.store)
        seen = {item["id"] for item in self.items}
        merged = list(self.items)
        indexed = pending = 0
        partial = bool(self.coverage.get("partial"))
        for ref in refs:
            if ref in wide and time.monotonic() - started > budget_seconds + OWNER_ALL_EXTRA_SECONDS:
                extra += 1
                continue
            try:
                opened, code = stores.open_store(ref, self.owner, self.store)
            except Exception:  # noqa: BLE001 - one store never stops a search
                opened, code = None, "store_unreadable"
            if opened is None:
                if code != "store_absent":
                    skipped.append(f"{ref.kind}:{code}")
                continue
            skipped.extend(f"{ref.kind}:{note}" for note in opened.notes)
            try:
                part = self._open_part(opened, max(0.5, budget_seconds + (OWNER_ALL_EXTRA_SECONDS if ref in wide else 0.0) - (time.monotonic() - started)),
                                       room if ref in wide else None)
            except _NoRoom:
                opened.db.close()
                extra += 1
                continue
            except (sqlite3.Error, RecallError, OSError):
                opened.db.close()
                skipped.append(f"{ref.kind}:store_unreadable")
                continue
            self.parts.append(part)
            if ref in wide:
                room -= len(part.items)
            hidden = set(opened.withheld) | (forgotten or set())
            current = ref in context_refs and ref.kind == "project" and scope != "owner_all"
            for item in part.items:
                if item["id"] in seen or (hidden and item["id"][2:] in hidden):
                    continue
                seen.add(item["id"])
                if current and item["scope"] == "project" and item.get("project_path_hash") != project_hash:
                    # Being in this folder's project store is what makes the row this project's; a stored path may be
                    # from before the folder moved.
                    item = {**item, "project_path_hash": project_hash}
                merged.append(item)
                self._part_of[item["id"]] = part
            indexed += len(part.items)
            for row in getattr(part, "pending_rows", []):
                if row["id"] not in seen and not (hidden and row["id"][2:] in hidden):
                    self.pending.append({**row, "vector": None, "norm": None})
                    self._part_of[row["id"]] = part
            if getattr(part, "pending", 0):
                pending += part.pending
                partial = True
        self.items = merged
        self.coverage["indexed"] = int(self.coverage.get("indexed", 0)) + indexed
        self.coverage["pending"] = int(self.coverage.get("pending", 0)) + pending
        self.coverage["partial"] = partial or extra > 0  # stores past the row ceiling or the time budget were not searched
        self.coverage["stores"] = {"searched": len(self.parts), "skipped": skipped, "notOpened": extra}

    def _open_part(self, opened: Any, budget: float, room: int | None = None) -> _Part:
        store = opened.db
        store.row_factory = sqlite3.Row
        store.execute("PRAGMA query_only=1")
        disk = opened.ref.path.parent / "recall-index.sqlite"
        index: sqlite3.Connection | None = None
        on_disk = False
        live = store.execute("SELECT count(*) FROM memory_entries WHERE superseded_at IS NULL AND content<>''").fetchone()[0]
        if room is not None and live > room:
            raise _NoRoom()
        if disk.exists() or live >= DIRECT_SCAN_ROWS:
            try:
                index = _open_index(disk)
                on_disk = True
            except (sqlite3.Error, RecallError, OSError):
                index = None
        if index is None:
            index = _direct_index(str(opened.ref.path), live)
        status = sync_index(store, index, budget_seconds=budget)
        items = _cached_items(disk, index) if on_disk else _read_items(index)
        part = _Part(opened.ref.kind, store, index, items, shared_index=not on_disk)
        part.pending = status.get("pending", 0)
        part.pending_rows = status.get("pending_rows", [])
        return part

    def close(self) -> None:
        for part in self.parts:
            part.close()

    def part_for(self, identifier: str) -> _Part:
        return self._part_of.get(identifier, self.parts[0])

    def lexical(self, query: str) -> dict[str, int]:
        if len(self.parts) == 1:
            return _lexical_hits(self.index, query)
        return _lexical_merged([part.index for part in self.parts], query)

    def verified(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            if len(self.parts) == 1:
                return _recheck(self.store, items)
            alive: set[str] = set()
            groups: dict[int, tuple[_Part, list[dict[str, Any]]]] = {}
            for item in items:
                part = self.part_for(item["id"])
                groups.setdefault(id(part), (part, []))[1].append(item)
            for part, group in groups.values():
                alive.update(entry["id"] for entry in _recheck(part.store, group))
            return [item for item in items if item["id"] in alive]
        except sqlite3.OperationalError:
            self.coverage.update(storeLocked=True, partial=True)
            return []

    def result(self, **fields: Any) -> dict[str, Any]:
        owner_kind = "host-bound" if os.environ.get("AGENTLAS_MEMORY_BINDING_FILE") else self.owner.split(":", 1)[0]
        return {"status": "ok", **fields, "coverage": self.coverage, "owner": owner_kind}


def _common(arguments: dict[str, Any]) -> tuple[str, tuple[str | None, str | None], set[str], bool]:
    scope = arguments.get("scope") or "default"
    if scope not in {"default", "owner_all"}:
        raise RecallError("memory_scope_invalid")
    types = set(arguments.get("types") or ["memory", "episode"])
    if not types <= {"memory", "episode"}:
        raise RecallError("memory_types_invalid")
    return scope, _project(arguments.get("projectDir")), types, bool(arguments.get("include_confidential"))


def _limit(value: Any, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise RecallError("memory_limit_invalid")
    return value


def _result_item(row: dict[str, Any], *, show_project: bool) -> dict[str, Any]:
    item, lexical, vector = row["item"], row["lexical"], row["vector"]
    out = _public(item, show_project=show_project)
    out["score"] = {"lexical": round(lexical, 3), "vector": round(vector or 0.0, 3), "total": round(row["score"], 3)}
    out["match"] = "strong" if (vector is not None and (vector >= STRONG_VECTOR or (lexical > 0 and vector >= LEXICAL_STRONG_VECTOR))) \
        or lexical >= STRONG_LEXICAL else "weak"
    return out


def search(arguments: dict[str, Any], *, host: str | None = None) -> dict[str, Any]:
    """Lines that answer ``query``, in the contract order (``contract_rank``), as ``items``; the turn records that answer it come as their own
    list ``recent`` (at most ``RECENT_LIMIT``), never mixed into the lines. ``types`` picks which of the two are looked in."""
    query = str(arguments.get("query") or "").strip()
    if not query or len(query) > 2000:
        raise RecallError("memory_query_invalid")
    scope, project, types, confidential = _common(arguments)
    since, until = _time_bound(arguments.get("since"), "since"), _time_bound(arguments.get("until"), "until")
    kinds = set(arguments.get("kinds") or [])
    limit = _limit(arguments.get("limit"), 8, 30)
    session = _Session(project_dir=arguments.get("projectDir"), scope=scope, host=host)
    try:
        ref = _project_ref()
        pool = [item for item in [*session.items, *session.pending]
                if item["type"] in types and (not kinds or item["kind"] in kinds) and _in_range(item, since, until)
                and _allowed(item, scope=scope, project=project, include_confidential=confidential, project_ref=ref)]
        lines = [item for item in pool if item["type"] == "memory"]
        records = [item for item in pool if item["type"] == "episode"]
        ranked = contract_rank(query, lines)
        candidates = ranked[: limit * 3]
        alive = {item["id"] for item in session.verified([row["item"] for row in candidates])}
        results = [_result_item(row, show_project=scope == "owner_all") for row in candidates if row["item"]["id"] in alive][:limit]
        recent_ranked = contract_rank(query, records)[: RECENT_LIMIT * 3]
        recent_alive = {item["id"] for item in session.verified([row["item"] for row in recent_ranked])}
        recent = [_result_item(row, show_project=scope == "owner_all") for row in recent_ranked if row["item"]["id"] in recent_alive][:RECENT_LIMIT]
        session.coverage["searched"] = len(pool)
        shown = [*results, *recent]
        found = "strong" if any(item.get("match") == "strong" for item in shown) else ("weak_only" if shown else "none")
        return session.result(query=query, scope=scope, found=found, items=results, recent=recent)
    finally:
        session.close()


def timeline(arguments: dict[str, Any], *, host: str | None = None) -> dict[str, Any]:
    since = _time_bound(arguments.get("since"), "since")
    if not since:
        raise RecallError("memory_since_required")
    until = _time_bound(arguments.get("until"), "until")
    scope, project, types, confidential = _common(arguments)
    limit = _limit(arguments.get("limit"), 40, 100)
    offset = arguments.get("cursor") or 0
    if isinstance(offset, str) and offset.isdigit():
        offset = int(offset)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise RecallError("memory_cursor_invalid")
    session = _Session(project_dir=arguments.get("projectDir"), scope=scope, host=host)
    try:
        pool = sorted((item for item in session.items
                       if item["type"] in types and _in_range(item, since, until)
                       and _allowed(item, scope=scope, project=project, include_confidential=confidential, project_ref=_project_ref())),
                      key=lambda item: _normal_time(item["created_at"]))
        page = pool[offset: offset + limit]
        alive = {item["id"] for item in session.verified(page)}
        results = [_public(item, show_project=scope == "owner_all") for item in page if item["id"] in alive]
        session.coverage["searched"] = len(pool)
        following = offset + limit if offset + limit < len(pool) else None
        return session.result(since=since, until=until, items=results, nextCursor=following)
    finally:
        session.close()


def crosscheck(arguments: dict[str, Any], *, host: str | None = None) -> dict[str, Any]:
    claims = arguments.get("claims")
    if (not isinstance(claims, list) or not 1 <= len(claims) <= 10
            or any(not isinstance(claim, str) or not claim.strip() or len(claim) > 500 for claim in claims)):
        raise RecallError("memory_claims_invalid")
    scope, project, _, confidential = _common(arguments)
    session = _Session(project_dir=arguments.get("projectDir"), scope=scope, host=host)
    try:
        pool = [item for item in session.items if _allowed(item, scope=scope, project=project, include_confidential=confidential, project_ref=_project_ref())]
        checks = []
        for claim in claims:
            ranked = _rank(claim, pool, session.lexical(claim))
            related = [entry for entry in ranked if entry[2] >= RELATED_SIMILARITY or (entry[1] >= 1 / (1 + LEXICAL_STRONG_RANK / LEXICAL_DECAY) and entry[2] >= LEXICAL_STRONG_VECTOR)][:5]
            alive = {item["id"] for item in session.verified([entry[3] for entry in related])}
            checks.append({"claim": claim, "related": [
                {**_public(item, show_project=scope == "owner_all"), "similarity": round(vector, 3), "lexical": round(lexical, 3)}
                for _, lexical, vector, item in related if item["id"] in alive]})
        session.coverage["searched"] = len(pool)
        return session.result(checks=checks, note="similar is not the same; judge agreement or conflict yourself and prefer the newer dated evidence only after checking it")
    finally:
        session.close()


def get(arguments: dict[str, Any], *, host: str | None = None) -> dict[str, Any]:
    identifier = str(arguments.get("id") or "")
    if not re.fullmatch("[me]:" + ENTRY_ID_PATTERN, identifier):
        # The hook capsule prints a line as "[id · kind] text" with the bare id (what a ticket's targets takes): a bare id names that line.
        if not ENTRY_ID_RE.fullmatch(identifier):
            raise RecallError("memory_id_invalid")
        identifier = "m:" + identifier
    scope, project, _, confidential = _common(arguments)
    session = _Session(project_dir=arguments.get("projectDir"), scope=scope, host=host)
    try:
        item = next((entry for entry in session.items if entry["id"] == identifier), None)
        if not item or not _allowed(item, scope=scope, project=project, include_confidential=confidential) or not session.verified([item]):
            return {"status": "not_found", "id": identifier, "coverage": session.coverage}
        detail: dict[str, Any] = {"item": _public(item, show_project=True)}
        raw = identifier[2:]
        db = session.part_for(identifier).store  # the store this row lives in; tickets and episodes stay in the root
        if item["type"] == "memory":
            binding = db.execute("SELECT actor_id,origin_refs_json,applicability_json,curation_actor,revision "
                                 "FROM memory_identity_bindings WHERE memory_id=?", (raw,)).fetchone()
            if binding:
                detail["binding"] = {"actorId": binding["actor_id"], "curationActor": binding["curation_actor"],
                                     "revision": binding["revision"], "applicability": _applicability(binding["applicability_json"])}
            origins = [dict(row) for row in db.execute(
                "SELECT source_kind,source_id,relation FROM memory_origin_links WHERE memory_id=?", (raw,))]
            detail["origins"] = origins
            tickets = [origin["source_id"] for origin in origins if origin["source_kind"] in {"ticket", "memory-ticket"}]
            detail["replaces"] = ["m:" + origin["source_id"] for origin in origins if origin["relation"] == "supersedes"]
            detail["replacedBy"] = ["m:" + row[0] for row in db.execute(
                "SELECT memory_id FROM memory_origin_links WHERE source_id=? AND relation='supersedes'", (raw,))]
        else:
            tickets = [item["ticket_id"]] if item.get("ticket_id") else []
            detail["memoriesFromThisTurn"] = ["m:" + row[0] for row in db.execute(
                "SELECT memory_id FROM memory_origin_links WHERE source_kind IN ('ticket','memory-ticket') AND source_id=?",
                (item.get("ticket_id") or "",))]
        if tickets:
            marks = ",".join("?" * len(tickets))
            detail["tickets"] = [{key: row[key] for key in row.keys() if key not in {"project_path_hash"}} for row in session.store.execute(
                f"SELECT ticket_id,state,emitter_status,curation_outcome,written_count,deduped_count,created_at,agent_id "
                f"FROM memory_tickets WHERE ticket_id IN ({marks})", tickets)]
        pool = [entry for entry in session.items if entry["id"] != identifier
                and _allowed(entry, scope=scope, project=project, include_confidential=confidential)]
        similar = sorted(((sum(map(mul, item["vector"], entry["vector"])) / (item["norm"] * entry["norm"]), entry) for entry in pool),
                         key=lambda pair: pair[0], reverse=True)[:6]
        alive = {entry["id"] for entry in session.verified([entry for _, entry in similar])}
        detail["similar"] = [{**_public(entry), "similarity": round(score, 3)} for score, entry in similar
                             if entry["id"] in alive and score >= RELATED_SIMILARITY][:3]
        return session.result(**detail)
    finally:
        session.close()


# The bytes of memory lines a capsule carries. ONE source: the ruleset's ``recall.budget.maxBytes`` (``memory_recall_v2.MAX_BYTES``, pinned to the
# file by tests/test_memory_recall_v2_contract.py), 2,400 bytes of "- [kind] text" with the Personal always-lines taken out of it.
# Before audit this file had its own 1,200 (the old one-layer share): a Korean line over 420 characters was saved "ok" and never shown.
# A line is at most TEXT_LIMIT (600) characters = 1,800 bytes of Hangul/Kana/Han (3 bytes each in UTF-8) + "- [procedure] " + newline = 1,816:
HOOK_LINE_FLOOR_BYTES = TEXT_LIMIT * 3 + 16
# so the room left for the ranked lines is never below that: one line of the longest size always fits, even next to 800 bytes of Personal lines
# (2,400 - 800 = 1,600 would not hold it). A line that still does not fit (600 four-byte characters, emoji) is not dropped silently: it is named
# in the capsule's "too long to show" line with its id (``skipped`` below) and the model reads it with memory.get.
HOOK_PERSONAL_BYTES = 800
"""The Personal always-lines (ruleset ``stores.user_identity.alwaysLoad.maxBytes``; a test pins it): the most the hook spends on them."""
HOOK_ID_ALLOWANCE = 48
"""Characters a printed line adds to the contract's cost ("[id · kind]" for "- [kind]"): ids are 36-character uuids or shorter. The capsule layer budget
counts it per line (12 lines); a line whose id is longer is named in the "too long to show" line instead of dropped silently."""
HOOK_SYNC_SECONDS = 1.0
"""How long a turn-start hook spends bringing the side index level (measured: about 750 lines a second with the 128M int8 model on the
benchmark machine). Lines not yet indexed are NOT left out: they are read by their words (``pending`` rows), newest-first is replaced by
"the lines the person said and the rule kinds first"."""
HOOK_MEMORY_LAYER_BYTES = max(2400, HOOK_PERSONAL_BYTES + HOOK_LINE_FLOOR_BYTES) + 12 * HOOK_ID_ALLOWANCE
"""The capsule's one layer for memory lines, in printed characters (<= bytes): the larger of the contract's 2,400 and 800 + 1,816 (= 2,616), plus
12 x 48 for the ids = 3,192. memory_hook.LAYER_BUDGETS["one"] is this value (the One-drawer lines take what is left of it)."""
HOOK_OTHER_LINES_MIN = 4
"""The Personal lines a hook always carries (at most 8) take lines from the cap, but never leave the other lines fewer than this (flaw 8)."""
HOOK_RECENT_LINES = 3
HOOK_SKIPPED_NAMED = 3
"""At most this many ids of too-long lines the capsule names (about 150 characters): enough for the model to read the best ones with memory.get."""
HOOK_RECENT_CHARS = 220


def hook_recall(*, host: str | None, project_dir: str | None, user_text: str | None, previous_summary: str | None = None,
                exclude_chat: str | None = None, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a turn-start hook recalls for one turn, through the same contract and the same reader as ``memory.search``.

    ``{"lines": [{id, kind, line}], "recent": [{id, line}], "mode": "ranked" | "latest", "always": n}``: ``lines`` are memory lines (the
    owner's Personal preference lines first, as before, then the contract's 12 lines / the ruleset's byte budget; with no prompt the newest 8),
    ``recent`` is the turn-record layer (their own list, at most ``HOOK_RECENT_LINES``, records of this conversation left out: the model
    has them). Raises ``RecallError`` when there is no store to read."""
    from . import memory_classify, memory_recall_v2 as v2
    from .memory_runtime import _safe_summary
    session = _Session(budget_seconds=HOOK_SYNC_SECONDS, project_dir=project_dir, scope="default", host=host)
    try:
        project, ref = _project(project_dir), _project_ref()
        pool = [item for item in [*session.items, *session.pending] if _allowed(item, scope="default", project=project, include_confidential=False, project_ref=ref)]
        memories = [item for item in pool if item["type"] == "memory"]
        records = [item for item in pool if item["type"] == "episode" and not (exclude_chat and item.get("chat_id") == exclude_chat)]
        query = v2.assemble_query(user_text, previous_summary)

        def safe(text: str) -> bool:
            try:
                _safe_summary(text)
                return True
            except ValueError:
                return False

        always_rows = memory_classify.personal_always(
            [(item["id"], item["kind"], item["text"], item["created_at"], item["scope"]) for item in memories if item["scope"] == "user_identity"], rules)
        always_ids = [row[0] for row in always_rows if safe(row[2])]
        pinned = [next(item for item in memories if item["id"] == ident) for ident in always_ids]
        rest = [item for item in memories if item["id"] not in set(always_ids)]
        spent = sum(len(display_line(item).encode("utf-8")) + 1 for item in pinned)
        room = max(v2.MAX_BYTES - spent, HOOK_LINE_FLOOR_BYTES)  # never below one line of the longest size (see HOOK_LINE_FLOOR_BYTES)
        by_id = {item["id"]: item for item in rest}
        lines = contract_lines(query, rest)
        banned: set[str] = set()
        picked: list[dict[str, Any]] = []
        mode = "latest"
        for _ in range(4):  # a selected line the safety check refuses is left out and the next best one is taken
            for line in lines:
                line["disabled"] = line["id"] in banned
            base = v2.SESSION_START_LINES if query is None else v2.MAX_LINES
            result = v2.recall({"user_text": user_text, "previous_summary": previous_summary}, lines, CONTRACT_READER,
                               options={"max_lines": max(HOOK_OTHER_LINES_MIN, base - len(pinned)), "max_bytes": room})
            mode = result["mode"]
            ranked_ids = [row["id"] for row in result["ranked"]]
            bad = {row["id"] for row in result["selected"] if not safe(by_id[row["id"]]["text"])}
            picked = [by_id[row["id"]] for row in result["selected"]]
            if not bad:
                break
            banned |= bad
        else:
            picked = [item for item in picked if item["id"] not in banned]
        # Lines that did not fit the byte room but rank above a line that was taken: named in the capsule, never dropped silently.
        chosen = {item["id"] for item in picked}
        last = max((ranked_ids.index(i) for i in chosen if i in ranked_ids), default=-1)
        skipped = [i for i in ranked_ids[:last] if i in set(result["skipped_over_budget"]) and i not in banned][:HOOK_SKIPPED_NAMED]
        recent = []
        for item in contract_recent(records, query=query, limit=HOOK_RECENT_LINES * 3, vectors=None):
            text = " ".join(str(item["text"]).split())
            if text and safe(item["text"]):
                recent.append({"id": item["id"], "line": "[" + str(item["created_at"] or "")[:10] + "] " + text[:HOOK_RECENT_CHARS]})
            if len(recent) >= HOOK_RECENT_LINES:
                break
        return {"lines": [{"id": item["id"], "kind": item["kind"], "line": display_line(item), "text": item["text"][:TEXT_LIMIT]} for item in [*pinned, *picked]],
                "recent": recent, "mode": mode, "always": len(pinned), "coverage": session.coverage,
                "skipped": skipped}
    finally:
        session.close()


def record(arguments: dict[str, Any], *, host: str | None = None) -> dict[str, Any]:
    """The engine's memory write tool (Agentlas 2.0): the model's tickets are received by the one ticket receiver and
    written by ``memory_ticket_write`` (add, rewrite, condense, remove through the functions that already exist). No model is called, nothing is queued,
    no worker is started. The answer is one entry per ticket; the model may say it saved something only after an ``ok`` answer.

    The old argument shape (``turn_summary`` and ``observations``) is still read for one release: the observations become add tickets of the lowest
    source tier, the summary becomes a turn record."""
    from . import memory_ticket_write as writer
    from .memory_runtime import hook_project_binding, host_actor_id, owner_binding
    raw: Any = arguments
    summary = arguments.get("turn_summary")
    if "tickets" not in arguments:
        observations = arguments.get("observations")
        if isinstance(observations, list):
            if len(observations) > 8:
                raise RecallError("memory_observations_invalid")
            raw = {"tickets": writer.tickets_from_candidates(observations)}
        elif isinstance(summary, str):
            raw = {"tickets": []}
    if summary is not None and (not isinstance(summary, str) or not summary.strip() or len(summary) > 300):
        raise RecallError("memory_turn_summary_invalid")
    project_path, _ = _project(arguments.get("projectDir"))
    in_project = False
    if project_path:
        # The same function as the hook: the nearest enclosing project root, and whether one was found ((e)), so
        # the same folder and the same actor end in the same store whichever door the turn came through.
        bound, found = hook_project_binding({"cwd": project_path})
        if bound:
            project_path, in_project = bound, found
    actor = host_actor_id(host or "mcp")
    if not owner_binding(create=True):
        raise RecallError("memory_store_absent")
    out: dict[str, Any] = {"status": "ok", "answers": []}
    if isinstance(raw, dict) and not raw.get("tickets") and "tickets" in raw and isinstance(summary, str):
        pass
    else:
        try:
            written = writer.write_tickets(raw, actor=actor, project_path=project_path, in_project=in_project)
        except sqlite3.Error as error:  # a locked or full file is an answer the model can read, never a crash of the tool
            raise RecallError("memory_store_busy" if "lock" in str(error).lower() or "busy" in str(error).lower() else "memory_store_unavailable") from error
        if written["unreadable"]:
            raise RecallError("memory_tickets_unreadable")
        out["answers"] = written["answers"]
    if isinstance(summary, str) and summary.strip():
        from .memory_runtime import MemoryRuntime
        owner = owner_binding(create=True)
        context = "mcp-session:" + _sha(f"{actor}:{os.getpid()}:{_PROCESS_STARTED}")[:32]
        runtime = MemoryRuntime(owner)
        try:
            import uuid
            receipt = runtime.enqueue(actor_id=actor, context_key=context, source_ref="mcp-record:" + uuid.uuid4().hex,
                                      source_revision=time.time_ns() // 1_000_000, summary=summary.strip(), project_path=project_path,
                                      update_checkpoint=False, in_project=in_project or None, ledger_only=True)
        finally:
            runtime.db.close()
        out["turnRecord"] = receipt["operation_id"]
    return out


_PROCESS_STARTED = time.time_ns()
