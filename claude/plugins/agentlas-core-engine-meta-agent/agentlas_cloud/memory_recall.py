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
from datetime import datetime, timezone
from operator import mul
from pathlib import Path
from typing import Any, Iterable

INDEX_SCHEMA = "agentlas.memory-recall-index.v1"
INDEX_ENV = "AGENTLAS_MEMORY_RECALL_INDEX"
LIVE_SCOPES = frozenset({"user_identity", "team_memory", "agent_repo", "project"})
CONFIDENCE = {"high": 1.0, "medium": 0.6, "low": 0.2}
TEXT_LIMIT = 600
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


def _read_only(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.5)
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
    episodes = db.execute("SELECT count(*), max(created_at) FROM memory_episodes WHERE summary IS NOT NULL").fetchone()
    return _sha(json.dumps([revision[0] if revision else None, epoch[0] if epoch else 0, episodes[0], episodes[1]]))


def _live_memories(db: sqlite3.Connection) -> Iterable[dict[str, Any]]:
    native = _has_table(db, "memory_entry_native")
    rows = db.execute(
        "SELECT e.id,e.scope,e.kind,e.content,e.project_id,e.project_path,e.agent_id,e.chat_id,e.confidence,"
        "e.sensitivity,e.created_at,b.applicability_json" + (",n.content_native" if native else ",NULL AS content_native") +
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
               "content_hash": _sha(text + "\0" + (native_text or "") + "\0" + policy), "text": text, "text_native": native_text}


def _live_episodes(db: sqlite3.Connection) -> Iterable[dict[str, Any]]:
    quarantine = " AND p.ticket_id NOT IN (SELECT ticket_id FROM memory_episode_quarantines)" if _has_table(db, "memory_episode_quarantines") else ""
    for row in db.execute(
            "SELECT p.episode_id,p.ticket_id,p.project_id,p.project_path_hash,p.agent_id,p.chat_id,p.summary,p.created_at "
            "FROM memory_episodes p WHERE p.summary IS NOT NULL AND p.summary<>''" + quarantine):
        text = (row["summary"] or "")[:4000]
        yield {"id": "e:" + row["episode_id"], "type": "episode", "kind": "episode", "scope": None,
               "project_id": row["project_id"], "project_path": None, "project_path_hash": row["project_path_hash"],
               "agent_id": row["agent_id"], "chat_id": row["chat_id"], "ticket_id": row["ticket_id"],
               "sensitivity": None, "confidence": None, "created_at": row["created_at"],
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

def _open_index(path: Path) -> sqlite3.Connection:
    if path.is_symlink():
        raise RecallError("memory_recall_index_symlink")
    created = not path.exists()
    db = sqlite3.connect(str(path), timeout=5)
    db.row_factory = sqlite3.Row
    if created and os.name == "posix":
        os.chmod(path, 0o600)
    db.executescript(
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, type TEXT NOT NULL, kind TEXT, scope TEXT,"
        " project_id TEXT, project_path TEXT, project_path_hash TEXT, agent_id TEXT, chat_id TEXT, ticket_id TEXT,"
        " sensitivity TEXT, confidence TEXT, created_at TEXT NOT NULL, content_hash TEXT NOT NULL,"
        " text TEXT NOT NULL, text_native TEXT, vec BLOB NOT NULL);"
        "CREATE INDEX IF NOT EXISTS items_created ON items(created_at);"
        "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(id UNINDEXED, text, text_native,"
        " tokenize='unicode61 remove_diacritics 2');")
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
    if _meta(index_db, "store_signature") == signature:
        total = index_db.execute("SELECT count(*) FROM items").fetchone()[0]
        return {"indexed": total, "pending": 0, "changed": 0, "partial": False}
    live = {row["id"]: row for row in (*_live_memories(store_db), *_live_episodes(store_db))}
    indexed = {row[0]: row[1] for row in index_db.execute("SELECT id, content_hash FROM items")}
    stale = [key for key, digest in indexed.items() if key not in live or live[key]["content_hash"] != digest]
    for start in range(0, len(stale), 500):
        chunk = stale[start:start + 500]
        marks = ",".join("?" * len(chunk))
        index_db.execute(f"DELETE FROM items WHERE id IN ({marks})", chunk)
        index_db.execute(f"DELETE FROM items_fts WHERE id IN ({marks})", chunk)
    stale_set = set(stale)
    missing = sorted((row for key, row in live.items() if key not in indexed or key in stale_set),
                     key=lambda row: row["created_at"] or "", reverse=True)
    added = 0
    for row in missing:
        if time.monotonic() - started > budget_seconds:
            break
        vector = _pack(adapter.embed(row["text"]))
        index_db.execute(
            "INSERT OR REPLACE INTO items(id,type,kind,scope,project_id,project_path,project_path_hash,agent_id,chat_id,"
            "ticket_id,sensitivity,confidence,created_at,content_hash,text,text_native,vec) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], row["type"], row["kind"], row["scope"], row["project_id"], row["project_path"], row["project_path_hash"],
             row["agent_id"], row["chat_id"], row["ticket_id"], row["sensitivity"], row["confidence"], row["created_at"],
             row["content_hash"], row["text"], row["text_native"], vector))
        index_db.execute("INSERT INTO items_fts(id,text,text_native) VALUES(?,?,?)", (row["id"], row["text"], row["text_native"] or ""))
        added += 1
    pending = len(missing) - added
    if pending == 0:
        _set_meta(index_db, "store_signature", signature)
    if stale or added:
        _set_meta(index_db, "generation", str(int(_meta(index_db, "generation") or 0) + 1))
    index_db.commit()
    total = index_db.execute("SELECT count(*) FROM items").fetchone()[0]
    return {"indexed": total, "pending": pending, "changed": len(stale) + added, "partial": pending > 0}


_CACHE: dict[str, tuple[str, list[dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()


def _cached_items(index_path: Path, index_db: sqlite3.Connection) -> list[dict[str, Any]]:
    generation = _meta(index_db, "generation") or "0"
    key = str(index_path)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == generation:
            return hit[1]
    items = []
    for row in index_db.execute("SELECT * FROM items"):
        item = dict(row)
        item["vector"], item["norm"] = _unpack(item.pop("vec"))
        items.append(item)
    with _CACHE_LOCK:
        _CACHE[key] = (generation, items)
    return items


# --- policy -----------------------------------------------------------------

def _project(project_dir: str | None) -> tuple[str | None, str | None]:
    raw = project_dir or os.getcwd()
    try:
        path = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError):
        return None, None
    if not path.is_dir() or path == Path(path.anchor) or path == Path.home().resolve():
        return None, None
    return str(path), _sha(str(path))


def _allowed(item: dict[str, Any], *, scope: str, project: tuple[str | None, str | None],
             include_confidential: bool) -> bool:
    path, path_hash = project
    item_hash = item.get("project_path_hash")
    same_project = bool(path_hash and item_hash == path_hash)
    if item["type"] == "episode":
        return scope == "owner_all" or item_hash is None or same_project
    if item.get("sensitivity") == "secret":
        return False
    if item.get("sensitivity") == "confidential" and not (include_confidential and same_project):
        return False
    if scope == "owner_all":
        return True
    if item["scope"] in {"user_identity", "team_memory"}:
        return True
    if item["scope"] == "project":
        return same_project
    if item["scope"] == "agent_repo":
        return item_hash is None or same_project
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


LEXICAL_WEIGHT = 0.3
LEXICAL_DECAY = 5.0
LEXICAL_MIN_VECTOR = 0.30
STRONG_VECTOR = 0.55
LEXICAL_STRONG_RANK = 10
LEXICAL_STRONG_VECTOR = 0.45
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
                           "ageDays": _age_days(item["created_at"]), "source": "agentlas-memory"}
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


class _Session:
    """One call's store connection, synced index and cached items."""

    def __init__(self, budget_seconds: float = SYNC_BUDGET_SECONDS):
        self.owner = _owner()
        self.store_path = _store_path(self.owner)
        self.coverage: dict[str, Any] = {"storeLocked": False, "partial": False}
        if not self.store_path.exists():
            raise RecallError("memory_store_absent")
        self.store = _read_only(self.store_path)
        self.index_path = _index_path(self.store_path)
        self.index = _open_index(self.index_path)
        try:
            self.coverage.update(sync_index(self.store, self.index, budget_seconds=budget_seconds))
        except sqlite3.OperationalError as error:
            if "locked" not in str(error) and "busy" not in str(error):
                raise
            self.coverage.update(storeLocked=True, partial=True)
        adapter = _adapter()
        self.coverage["adapter"] = "local_model" if getattr(adapter, "status", "") == "available" else "degraded_hash"
        self.items = _cached_items(self.index_path, self.index)

    def close(self) -> None:
        self.store.close()
        self.index.close()

    def verified(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            return _recheck(self.store, items)
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


def search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query or len(query) > 2000:
        raise RecallError("memory_query_invalid")
    scope, project, types, confidential = _common(arguments)
    since, until = _time_bound(arguments.get("since"), "since"), _time_bound(arguments.get("until"), "until")
    kinds = set(arguments.get("kinds") or [])
    limit = _limit(arguments.get("limit"), 8, 30)
    session = _Session()
    try:
        pool = [item for item in session.items
                if item["type"] in types and (not kinds or item["kind"] in kinds) and _in_range(item, since, until)
                and _allowed(item, scope=scope, project=project, include_confidential=confidential)]
        ranked = _rank(query, pool, _lexical_hits(session.index, query))
        candidates = ranked[: limit * 3]
        alive = {item["id"] for item in session.verified([entry[3] for entry in candidates])}
        results = [_public(item, lexical=lexical, vector=vector, show_project=scope == "owner_all")
                   for _, lexical, vector, item in candidates if item["id"] in alive][:limit]
        session.coverage["searched"] = len(pool)
        found = "strong" if any(item.get("match") == "strong" for item in results) else ("weak_only" if results else "none")
        return session.result(query=query, scope=scope, found=found, items=results)
    finally:
        session.close()


def timeline(arguments: dict[str, Any]) -> dict[str, Any]:
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
    session = _Session()
    try:
        pool = sorted((item for item in session.items
                       if item["type"] in types and _in_range(item, since, until)
                       and _allowed(item, scope=scope, project=project, include_confidential=confidential)),
                      key=lambda item: _normal_time(item["created_at"]))
        page = pool[offset: offset + limit]
        alive = {item["id"] for item in session.verified(page)}
        results = [_public(item, show_project=scope == "owner_all") for item in page if item["id"] in alive]
        session.coverage["searched"] = len(pool)
        following = offset + limit if offset + limit < len(pool) else None
        return session.result(since=since, until=until, items=results, nextCursor=following)
    finally:
        session.close()


def crosscheck(arguments: dict[str, Any]) -> dict[str, Any]:
    claims = arguments.get("claims")
    if (not isinstance(claims, list) or not 1 <= len(claims) <= 10
            or any(not isinstance(claim, str) or not claim.strip() or len(claim) > 500 for claim in claims)):
        raise RecallError("memory_claims_invalid")
    scope, project, _, confidential = _common(arguments)
    session = _Session()
    try:
        pool = [item for item in session.items if _allowed(item, scope=scope, project=project, include_confidential=confidential)]
        checks = []
        for claim in claims:
            ranked = _rank(claim, pool, _lexical_hits(session.index, claim))
            related = [entry for entry in ranked if entry[2] >= RELATED_SIMILARITY or (entry[1] >= 1 / (1 + LEXICAL_STRONG_RANK / LEXICAL_DECAY) and entry[2] >= LEXICAL_STRONG_VECTOR)][:5]
            alive = {item["id"] for item in session.verified([entry[3] for entry in related])}
            checks.append({"claim": claim, "related": [
                {**_public(item, show_project=scope == "owner_all"), "similarity": round(vector, 3), "lexical": round(lexical, 3)}
                for _, lexical, vector, item in related if item["id"] in alive]})
        session.coverage["searched"] = len(pool)
        return session.result(checks=checks, note="similar is not the same; judge agreement or conflict yourself and prefer the newer dated evidence only after checking it")
    finally:
        session.close()


def get(arguments: dict[str, Any]) -> dict[str, Any]:
    identifier = str(arguments.get("id") or "")
    if not re.fullmatch(r"[me]:[A-Za-z0-9][A-Za-z0-9:._/+=-]{0,511}", identifier):
        raise RecallError("memory_id_invalid")
    scope, project, _, confidential = _common(arguments)
    session = _Session()
    try:
        item = next((entry for entry in session.items if entry["id"] == identifier), None)
        if not item or not _allowed(item, scope=scope, project=project, include_confidential=confidential) or not session.verified([item]):
            return {"status": "not_found", "id": identifier, "coverage": session.coverage}
        detail: dict[str, Any] = {"item": _public(item, show_project=True)}
        raw = identifier[2:]
        db = session.store
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
            detail["tickets"] = [{key: row[key] for key in row.keys() if key not in {"project_path_hash"}} for row in db.execute(
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


def record(arguments: dict[str, Any], *, host: str | None = None) -> dict[str, Any]:
    """Queue a turn summary through the existing ticket path; never write memory rows directly."""
    import uuid
    from .memory_runtime import MemoryRuntime, owner_binding, schedule_worker
    summary = arguments.get("turn_summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 300:
        raise RecallError("memory_turn_summary_invalid")
    observations = arguments.get("observations") or []
    if not isinstance(observations, list) or len(observations) > 8:
        raise RecallError("memory_observations_invalid")
    project_path, _ = _project(arguments.get("projectDir"))
    from .memory_runtime import host_actor_id
    actor = host_actor_id(host or "mcp")
    context = "mcp-session:" + _sha(f"{actor}:{os.getpid()}:{_PROCESS_STARTED}")[:32]
    owner = owner_binding(create=True)
    runtime = MemoryRuntime(owner)
    try:
        receipt = runtime.enqueue(actor_id=actor, context_key=context, source_ref="mcp-record:" + uuid.uuid4().hex,
                                  source_revision=time.time_ns() // 1_000_000, summary=summary.strip(),
                                  project_path=project_path, observations=observations, update_checkpoint=False)
    finally:
        runtime.db.close()
    scheduled = schedule_worker(receipt["operation_id"], owner)
    return {"status": "queued", "ticketId": receipt["operation_id"], "curation": "scheduled" if scheduled else "deferred"}


_PROCESS_STARTED = time.time_ns()
