"""Where one owner's memory rows can live, and how to READ across all of those places.

Memory is split into four kinds of store. The root store (``memory.sqlite``) is the personal one
and always exists. Three more can exist next to it or in an agent's folder:

* agent    ``<agent folder>/.agentlas-local/memory/o-<sha256(owner)[:16]>/memory.sqlite`` (this computer only)
* project  ``<memory root>/owners/<sha256(owner)>/projects/<sha256(project key)[:32]>/memory.sqlite``
* session  ``<memory root>/owners/<sha256(owner)>/session.sqlite`` (the desktop's checkpoints; the engine only knows the path)
* worker ``<memory root>/owners/<sha256(owner)>/worker/memory.sqlite`` (Agentlas 2.0 "this computer's work knowledge", the lines and turn
           records of the resident subjects, see ``store_for(..., layout=SPLIT2_LAYOUT)``; nothing writes or moves a row there yet)

This module only READS. It creates no file, writes no meta and adds no column; nothing here changes what an older
engine or desktop sees. Writing to these stores, and moving rows into them, is.

The layout switch is the root store's ``memory_store_meta`` key ``memory_layout``:

* missing or empty -> ``central``: nothing here is consulted at all, behaviour is exactly the single-store one;
* exactly ``split-1`` -> ``split``;
* any other value  -> ``union``: a newer layout this engine does not know. Rows are read from every store, writes stay
  in the root, and nothing is moved. Reading never refuses over a value it does not recognise.

Reading follows the rule of it reads what can be read and keeps going. A store with a newer
schema is opened read-only and read as far as its columns allow; a missing, unreadable or half-written store is
skipped and named in the returned notes (a code, never a sentence). The one thing that is skipped for privacy is a
store that belongs to another owner namespace.

Forgetting: the root store holds the forget clock and the revocation ledger. Before a sub-store is read, rows it
still holds for revocations newer than its ``forget_epoch_applied`` are blanked (the same redaction the desktop
performs). When the store cannot be written (read-only folder, locked) those ids are withheld from the reader
instead; when the root's ledger cannot be read the store is not read at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, NamedTuple

from . import agent_home
from .memory_actor_family import is_one_memory_actor, memory_actor_ids
from .memory_scopes import owner_scope_of
from .project_identity import MARKER_RELATIVE, legacy_path_key, project_key

LAYOUT_KEY = "memory_layout"
SPLIT_LAYOUT = "split-1"
SPLIT2_LAYOUT = "split-2"
"""The value the 2.0 structure conversion (K5) will write. K1 defines and reads it and writes it nowhere: ``layout_of`` answers ``SPLIT2`` for it;
every caller that compares with ``CENTRAL`` or ``SPLIT`` treats it as it treats any layout it does not move rows for (rows are read from every store,
writes stay in the root), which is also what an engine that has never heard of the value does."""
CENTRAL, SPLIT, UNION, SPLIT2 = "central", "split", "union", "split2"
FIRST_RUN_MERGE_KEY = "first_run_merge"
"""Root meta key of the 2.0 first-run merge step (K5): a JSON object ``{"v": 1, "state": "done"|..., "last": <iso time>, "tries": <int>}``. Read only
here (``first_run_merge``); one small row, kept for good."""

PERSONAL, AGENT, PROJECT, SESSION, WORKER = "personal", "agent", "project", "session", "worker"
STORE_FILE = "memory.sqlite"
HOOK_LIMIT = 16
# A forget being applied to a store waits this long for its write lock; a locked store withholds those ids and is caught up next time.
CATCHUP_LOCK_WAIT = 0.05


class StoreRef(NamedTuple):
    kind: str          # personal | agent | project | session
    key: str | None    # agent id / project key / None for personal and session
    path: Path         # the memory.sqlite file (it may not exist)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# --- layout switch ----------------------------------------------------------------------------------------------

def layout_of(root_db: sqlite3.Connection | None) -> str:
    """``central`` | ``split`` | ``union`` from the root store's meta. Never raises; any failure reads as ``central``."""
    if root_db is None:
        return CENTRAL
    try:
        row = root_db.execute("SELECT value FROM memory_store_meta WHERE key=?", (LAYOUT_KEY,)).fetchone()
    except sqlite3.Error:
        return CENTRAL
    value = row[0] if row else None
    if value is None or (isinstance(value, str) and not value.strip()):
        return CENTRAL
    if value == SPLIT_LAYOUT:
        return SPLIT
    return SPLIT2 if value == SPLIT2_LAYOUT else UNION


def first_run_merge(root_db: sqlite3.Connection | None) -> dict[str, Any] | None:
    """The root's ``first_run_merge`` meta value as a dict, or None (no such key, unreadable, not an object). Never raises, writes nothing."""
    if root_db is None:
        return None
    try:
        row = root_db.execute("SELECT value FROM memory_store_meta WHERE key=?", (FIRST_RUN_MERGE_KEY,)).fetchone()
        value = json.loads(row[0]) if row and isinstance(row[0], str) else None
    except (sqlite3.Error, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def reads_union(root_db: sqlite3.Connection | None) -> bool:
    return layout_of(root_db) != CENTRAL


# --- paths ------------------------------------------------------------------------------------------------------

def _memory_root() -> Path:
    from .memory_runtime import memory_io_root
    return memory_io_root()


def account_dir(owner: str) -> Path:
    """``<memory root>/owners/<sha256(owner)>``, the folder of the root store."""
    return _memory_root() / "owners" / _sha(owner)


def worker_ref(owner: str) -> StoreRef:
    """The one work-knowledge store of an owner on this computer (Agentlas 2.0 §2.5). Path only: nothing here creates or reads it."""
    return StoreRef(WORKER, None, account_dir(owner) / "worker" / STORE_FILE)


def session_ref(owner: str) -> StoreRef:
    # Path only (shared with the desktop's path table, contracts/test-vectors/memory-store-path-vectors.json). The engine
    # keeps its continuation checkpoints in the root store and neither creates nor reads this file.
    return StoreRef(SESSION, None, account_dir(owner) / "session.sqlite")


def project_ref(owner: str, key: str) -> StoreRef:
    return StoreRef(PROJECT, key, account_dir(owner) / "projects" / _sha(key)[:32] / STORE_FILE)


def agent_account_folder(owner: str) -> str:
    return "o-" + _sha(owner)[:16]


def agent_ref(owner: str, agent_folder: Path, agent_id: str) -> StoreRef:
    from . import long_path  # an agent folder deep enough that its store passes 259 characters on Windows opens only with the prefix
    return StoreRef(AGENT, agent_id, long_path.extended(agent_folder / agent_home.AGENT_LOCAL_STATE_FOLDER / "memory" / agent_account_folder(owner) / STORE_FILE, 20))


def project_keys(project_path: str | os.PathLike[str] | None, ref: str | None = None) -> list[str]:
    """Candidate project keys, best first: the environment's project ref, then the folder's own key (marker uid or
    path hash). A row's folder-name ``project_id`` is not a key. Reading tries every candidate: a project reached once
    through the desktop (ref) and once from a terminal (folder) is still one project's memory."""
    keys: list[str] = []
    if isinstance(ref, str) and ref.strip():
        keys.append(ref.strip())
    if project_path:
        try:
            keys.append(project_key(project_path))
            legacy = legacy_path_key(project_path)  # EK4: a store an older engine keyed by the folder as it was typed is still found (read last, never written)
            if legacy:
                keys.append(legacy)
        except Exception:  # noqa: BLE001 - a hook never fails over project identity
            pass
    return list(dict.fromkeys(keys))


# --- agent folders ----------------------------------------------------------------------------------------------

_AGENT_INDEX: tuple[str, int, dict[str, Path]] | None = None


def _owner_ids(folder: Path) -> list[str]:
    """Every id a folder's owner.json names: ``agentId`` and, when present, the ``ids`` list (aliases)."""
    marker = folder / agent_home.AGENT_LOCAL_STATE_FOLDER / agent_home.AGENT_OWNER_FILE
    try:
        if marker.is_symlink():
            return []
        payload = json.loads(marker.read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    found = [payload.get("agentId")]
    ids = payload.get("ids")
    if isinstance(ids, list):
        found.extend(ids)
    return [item for item in dict.fromkeys(found) if isinstance(item, str) and item]


def agent_folder_index(root: str | Path | None = None, *, refresh: bool = False) -> dict[str, Path]:
    """``{agent id: folder}`` for the folders under the agents root that carry an owner.json. Read-only.

    Cached for the process by the root folder's mtime; a lookup that misses rescans once (a folder gaining its
    owner.json later does not change the root's mtime).
    """
    global _AGENT_INDEX
    base = Path(root) if root else agent_home.agents_root()
    try:
        stamp = base.stat().st_mtime_ns
    except OSError:
        return {}
    cached = _AGENT_INDEX
    if cached and cached[0] == str(base) and cached[1] == stamp and not refresh:
        return cached[2]
    index: dict[str, Path] = {}
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return {}
    for entry in entries:
        try:
            if not entry.is_dir():
                continue
        except OSError:
            continue
        for ident in _owner_ids(entry):
            index.setdefault(ident, entry)
    _AGENT_INDEX = (str(base), stamp, index)
    return index


AGENT_FOLDER_ENV = "AGENTLAS_MEMORY_AGENT_FOLDER"


def _env_agent_home(agent_id: str) -> Path | None:
    """The folder the app resolved for this agent and passed in ``AGENTLAS_MEMORY_AGENT_FOLDER`` (absolute path), when its
    owner.json names the agent. One file read; anything else (unset, relative, wrong agent) falls back to the scan."""
    raw = os.environ.get(AGENT_FOLDER_ENV, "").strip()
    if not raw:
        return None
    folder = Path(raw)
    if not folder.is_absolute():
        return None
    return folder if agent_id in _owner_ids(folder) else None


def find_agent_home(agent_id: str | None, *, rescan: bool = True) -> Path | None:
    """The folder the desktop marked as this agent's, or None. A borrowed Hub agent (``hub:``) has no folder.
    ``rescan=False`` (the hook) does not scan the agents root a second time after a miss."""
    if not isinstance(agent_id, str) or not agent_id or agent_id.startswith("hub:"):
        return None
    home = _env_agent_home(agent_id)
    if home is not None:
        return home
    home = agent_folder_index().get(agent_id)
    if home is None and rescan:
        home = agent_folder_index(refresh=True).get(agent_id)
    return home


def store_agent_id(actor: str | None) -> str | None:
    """The agent id whose own store an actor reads, or None for the actors that have none: a One actor, hook
    attribution ``host:*``, resident ``builtin-agentlas-*`` actors, and a borrowed Hub agent (it
    keeps no memory and reads none)."""
    if not isinstance(actor, str) or not actor.strip():
        return None
    scope = owner_scope_of({"scope": "agent_repo", "agent_id": actor})
    return scope.owner_id if scope is not None and scope.kind == AGENT else None


# --- routing (pure; the writer is) ------------------------------------------------------------------------

def store_for(row: Any, owner: str, *, layout: str = CENTRAL, project_ref_hint: str | None = None) -> StoreRef | None:
    """Which store a row belongs to. ``None`` = never stored. The layout switch is the only branch: ``split-1`` routes by
    the ownership table, ``split-2`` (K1: defined, no caller passes it yet) by the same table with the resident subjects'
    agent lines owned by the work store (``owner_scope_of(row, split2=True)``); anything else answers the root. Computed
    from the row and the disk's agent folders; creates nothing."""
    split2 = layout == SPLIT2_LAYOUT
    owned = owner_scope_of(row, split2=True) if split2 else owner_scope_of(row)
    if owned is None:
        return None
    root = StoreRef(PERSONAL, None, _memory_root() / "owners" / _sha(owner) / STORE_FILE)
    if split2 and owned.kind == WORKER:
        return worker_ref(owner)
    if layout not in (SPLIT_LAYOUT, SPLIT2_LAYOUT) or owned.kind in (PERSONAL, "legacy-shared") or owned.owner_id is None:
        return root
    if owned.kind == SESSION:
        return session_ref(owner)
    if owned.kind == PROJECT:
        path = row["project_path"] if _has(row, "project_path") else None
        keys = project_keys(path if isinstance(path, str) and path else None, project_ref_hint)
        return project_ref(owner, keys[0]) if keys else root
    if owned.kind == AGENT:
        home = find_agent_home(owned.owner_id)
        return agent_ref(owner, home, owned.owner_id) if home is not None else root
    return root


def _has(row: Any, key: str) -> bool:
    try:
        row[key]
        return True
    except Exception:  # noqa: BLE001 - dict, sqlite3.Row and odd mappings alike
        return False


# --- opening for read -------------------------------------------------------------------------------------------

class OpenedStore(NamedTuple):
    ref: StoreRef
    db: sqlite3.Connection
    notes: tuple[str, ...]          # degrade codes: the store was opened but not trusted fully
    withheld: frozenset[str]        # row ids that must not be shown (a forget not yet applied to this file)


def _contained_agent_path(ref: StoreRef) -> str | None:
    """Symlink rule for an agent store: the agent folder itself may be a link, but ``.agentlas-local`` and everything
    under it must not be. Returns a degrade code, or None."""
    state = ref.path
    for _ in range(3):  # memory.sqlite -> o-xxx -> memory -> .agentlas-local
        state = state.parent
    local = state
    if local.name != agent_home.AGENT_LOCAL_STATE_FOLDER:
        return None
    for part in (local, local / "memory", ref.path.parent, ref.path):
        try:
            if part.is_symlink():
                return "agent_local_state_symlink"
        except OSError:
            return "agent_local_state_unreadable"
    return None


def _contained_account_path(ref: StoreRef) -> str | None:
    base = _memory_root()
    try:
        for part in (ref.path, *ref.path.parents):
            if part == base:
                break
            if part.is_symlink():
                return "store_symlink"
    except OSError:
        return "store_unreadable"
    return None


def _connect_ro(path: Path) -> sqlite3.Connection:
    from . import long_path
    from .memory_runtime import assert_read_root_isolated
    assert_read_root_isolated(path)
    uri = long_path.file_uri(path)
    last: sqlite3.Error | None = None
    for suffix in ("?mode=ro", "?mode=ro&immutable=1"):
        db = sqlite3.connect(uri + suffix, uri=True, timeout=0.5)
        try:
            db.execute("SELECT count(*) FROM sqlite_master").fetchone()
            db.row_factory = sqlite3.Row
            return db
        except sqlite3.OperationalError as error:
            db.close()
            last = error
    raise last if last else sqlite3.OperationalError("unable to open database file")


def _recover_hot_journal(path: Path) -> bool:
    """Open the store once for writing so SQLite rolls back a rollback journal left beside it. True when there was a journal to roll back and the store opened."""
    try:
        if not (path.parent / (path.name + "-journal")).is_file():
            return False
        writer = sqlite3.connect(str(path), timeout=0.5)
        try:
            writer.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            writer.close()
        return True
    except (sqlite3.Error, OSError):
        return False


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


JOURNAL_TABLE = "memory_recall_changes"
_FOREIGN_WATCH_NAME = re.compile(r"^memory_recall_watch_[A-Za-z0-9_]{1,96}$")
_FOREIGN_WATCH_BODY = re.compile(r"\bINTO\s+[\"`\[]?memory_recall_changes\b", re.IGNORECASE)


def heal_foreign_triggers(db: sqlite3.Connection) -> int:
    """Drop, from a sub-store, the desktop's recall-journal watch triggers an earlier engine copied into it, and nothing else.

    The desktop keeps a change journal (``memory_recall_changes``) in the ROOT only and watches its tables with triggers named
    ``memory_recall_watch_<table>_<event>`` that insert into it. A sub-store has no such table, so a copy of one of those triggers
    makes every write to the table it watches fail with ``no such table`` (the move stalled on it; a forget could not clear the
    original wording). A trigger is removed only when its NAME has that exact shape AND its SQL inserts into ``memory_recall_changes`` AND
    this file has no such table; any other trigger (the store's own, the forget triggers, a user's) stays. Writes DDL: call it on a
    connection that may write, inside or outside a transaction. Returns how many were dropped."""
    if _has_table(db, JOURNAL_TABLE):
        return 0
    dropped = 0
    for row in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'memory\\_recall\\_watch\\_%' ESCAPE '\\' AND sql IS NOT NULL").fetchall():
        name, sql = row[0], row[1]
        if _FOREIGN_WATCH_NAME.match(name) and _FOREIGN_WATCH_BODY.search(sql):
            db.execute('DROP TRIGGER IF EXISTS "' + name.replace('"', '""') + '"')
            dropped += 1
    return dropped


def _meta(db: sqlite3.Connection) -> dict[str, str]:
    if not _has_table(db, "memory_store_meta"):
        return {}
    return {str(k): str(v) for k, v in db.execute("SELECT key,value FROM memory_store_meta")}


def _root_clock(root_db: sqlite3.Connection) -> int | None:
    """The root's forget epoch, or None when it cannot be read."""
    try:
        if not _has_table(root_db, "memory_forget_clock"):
            row = root_db.execute("SELECT value FROM memory_store_meta WHERE key='revocation_epoch'").fetchone()
            return int(row[0]) if row else 0
        row = root_db.execute("SELECT epoch FROM memory_forget_clock WHERE id=1").fetchone()
        return int(row[0]) if row else 0
    except (sqlite3.Error, ValueError, TypeError):
        return None


def forgotten_ids(root_db: sqlite3.Connection, *, after: int = 0) -> set[str] | None:
    """Memory ids the root's ledger says were forgotten at an epoch later than ``after``; None if unreadable."""
    try:
        if not _has_table(root_db, "memory_revocations"):
            return set()
        ids = {row[0] for row in root_db.execute("SELECT source_memory_id FROM memory_revocations WHERE revoked_epoch>?", (after,))}
        if _has_table(root_db, "memory_revocation_sources"):
            ids |= {row[0] for row in root_db.execute(
                "SELECT s.source_memory_id FROM memory_revocation_sources s JOIN memory_revocations r "
                "ON r.revocation_id=s.revocation_id WHERE r.revoked_epoch>?", (after,))}
        return {item for item in ids if isinstance(item, str)}
    except sqlite3.Error:
        return None


SWITCH_EPOCH_KEY = "layout_switch_epoch"
"""Root ``memory_store_meta`` key (no new table or column): the forget number at the moment the layout switch was turned on. Forgets
numbered at or below it were made while memory lived in one store, so they were scoped (that agent's / that project's words only, as
the owner asked); forgets after it hold for the whole account. Written by ``memory_split.start`` in the transaction that sets the
layout (first value wins, it is never overwritten); read by ``forgotten_hashes`` and the writer's revocation check. The desktop reads
and may write the same key (``layoutSwitchEpoch`` / ``markLayoutSwitchEpoch``, stores.ts). Absent = every forget is account-wide."""


def layout_switch_epoch(root_db: sqlite3.Connection) -> int:
    """The switch-time forget number, or 0 (unknown, or the switch is off): 0 means every forget counts for the whole account."""
    try:
        if layout_of(root_db) == CENTRAL:
            return 0
        row = root_db.execute("SELECT value FROM memory_store_meta WHERE key=?", (SWITCH_EPOCH_KEY,)).fetchone()
        value = int(str(row[0]).strip()) if row else 0
        return value if value > 0 else 0
    except (sqlite3.Error, ValueError, TypeError):
        return 0


def mark_layout_switch_epoch(root_db: sqlite3.Connection) -> int:
    """Pin the current forget number as the switch boundary. Call it inside the transaction that sets the layout. An existing value is kept
    (a switch turned on again after a pause keeps the first boundary: a forget made in between is then account-wide, the side that
    never leaves a forgotten text alive). Returns the current forget number."""
    clock = _root_clock(root_db) or 0
    root_db.execute("INSERT OR IGNORE INTO memory_store_meta(key,value) VALUES(?,?)", (SWITCH_EPOCH_KEY, str(clock)))
    return clock


def _row_value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def row_owner_keys(row: Any) -> list[str]:
    """The revocation owner keys of one memory row (``scope``, ``project_path``, ``project_id``, ``agent_id`` (or the binding's ``actor_id`` when the row has none, the desktop's ``agent_id ?? actor_id``), ``chat_id``); the first is canonical.

'': a project that has a folder AND an id is known by both keys (the folder's first), so a line written before the folder was attached, or after it moved, is the same project. A project with only one of them keeps its single key."""
    scope = row["scope"]
    agent = _row_value(row, "agent_id")
    if agent is None:
        agent = _row_value(row, "actor_id")
    agent = str(agent).strip() if agent is not None else ""
    if scope == "project":
        path = row["project_path"]
        authorities = ["project-path:" + _sha(path) if path else ("project-id:" + row["project_id"] if row["project_id"] else "project-unbound")]
        if path and row["project_id"]:
            authorities.append("project-id:" + row["project_id"])
    elif scope == "agent_repo":
        authorities = ["agent:" + alias for alias in memory_actor_ids(agent or "unbound")]
    elif scope == "session":
        authorities = ["chat:" + (row["chat_id"] or "unbound")]
    else:
        authorities = ["shared"]
    return list(dict.fromkeys(_sha("agentlas-memory-owner-v1\0" + scope + "\0" + item) for item in authorities))


def family_owner_keys(row: Any) -> list[str]:
    """'': the keys a forget of one line reaches. The personal agent reads two places as ONE subject: its Personal lines (scope ``user_identity``) and its own work knowledge (``agent_repo`` of the One actor family).
    Forgetting a line in either also forgets the same words in the other, and the stamp holds for both. Every other subject has no family: its own keys. The desktop twin: ``memoryFamilyOwnerKeys`` (revocations.ts); a shared vector keeps the two equal."""
    own = row_owner_keys(row)
    scope = row["scope"]
    agent = _row_value(row, "agent_id")
    if agent is None:
        agent = _row_value(row, "actor_id")
    if scope == "user_identity":
        return list(dict.fromkeys(own + row_owner_keys({"scope": "agent_repo", "agent_id": "builtin-agentlas-one", "project_path": None, "project_id": None, "chat_id": None})))
    if scope == "agent_repo" and is_one_memory_actor(str(agent).strip() if agent is not None else None):
        return list(dict.fromkeys(own + row_owner_keys({"scope": "user_identity", "agent_id": None, "project_path": None, "project_id": None, "chat_id": None})))
    return own


def words_match(content: str, stamp_hash: str, rules: Any = None) -> bool:
    """'': whether a line's text is "the same words" as a stamp's hash: the stamp's own rule (the text, and the text with one trailing mark taken off or swapped, ``memory_classify.forget_forms``), so the lines a forget blanks
    are exactly the lines the stamp refuses to write again. Without usable rules the exact text. The desktop twin: ``forgetStampHashes`` (revocations.ts)."""
    from . import memory_classify
    from .memory_runtime import _content_hash
    active = memory_classify.active() if rules is None else rules
    if active is None:
        return _content_hash(content) == stamp_hash
    return stamp_hash in {_content_hash(form) for form in memory_classify.forget_forms(content, active)}


ONE_PACK_STAMP_SOURCE = "one-pack:personal-stamp"
ONE_PACK_STAMP_PREFIX = "one-pack:"
"""The ``source_memory_id`` an imported move-bundle stamp carries (Agentlas 2.0 O-M2, B1 and B2; ``one_pack._merge_stamps`` writes it, the desktop twin is ``ONE_PACK_STAMP_SOURCE`` in
``electron/memory/stores.ts``; a vector in the tests keeps the two texts equal). Not a memory id: no row can have it (an import refuses a row whose id starts with the prefix), so the id paths
(``forgotten_ids``, the recall and hook filters, the catch-up's id blanking) never reach a line through it. A stamp that carries it holds for the owner key it was made for ONLY (the Personal key),
whatever its number, the switch boundary or the clock: it is the owner's own 'forget this' made on another computer, not a forget of this account's other stores. A stamp without the prefix is read
exactly as before (the number against the boundary)."""


def stamp_is_personal_only(source: Any) -> bool:
    return isinstance(source, str) and source.startswith(ONE_PACK_STAMP_PREFIX)


def forgotten_hashes(root_db: sqlite3.Connection, *, after: int = 0) -> dict[tuple[str, str], frozenset[str] | None]:
    """(kind, content hash) of the revocations newer than ``after`` -> the owner keys that forget reached. Empty when unreadable (the id path still applies).

': every stamp reaches the OWNER it was made for (the agent, the project, Personal) and no other, whatever its number and whether or not a layout switch was ever turned on. It used to reach the whole account
    (``None``) for every forget after the switch, so the same words in another subject's store were blanked by a forget of someone else's line. A move-bundle stamp (``ONE_PACK_STAMP_SOURCE``) was already its own owner key's only.
    The value type keeps ``None`` for callers written for the old rule; this function no longer returns it."""
    result: dict[tuple[str, str], frozenset[str] | None] = {}
    try:
        if not _has_table(root_db, "memory_revocations"):
            return result
        for kind, digest, owner_key in root_db.execute(
                "SELECT memory_kind,content_hash,owner_key FROM memory_revocations WHERE revoked_epoch>?", (after,)):
            key = (kind, digest)
            result[key] = (result.get(key) or frozenset()) | {owner_key}
    except (sqlite3.Error, ValueError, TypeError):
        return {}
    return result


def _blank(db: sqlite3.Connection, ids: list[str], now: str) -> None:
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        marks = ",".join("?" * len(chunk))
        db.execute(
            "UPDATE memory_entries SET content='', evidence_json='[]', context_json='{}', chat_id=NULL, "
            "embedding_model=NULL, embedding_adapter=NULL, embedding_model_sha256=NULL, embedding_content_hash=NULL, "
            f"embedding_dimensions=NULL, embedding_json=NULL, superseded_at=COALESCE(superseded_at,?) WHERE id IN ({marks})",
            (now, *chunk))
        if _has_table(db, "memory_relation_edges"):
            db.execute(f"DELETE FROM memory_relation_edges WHERE from_memory_id IN ({marks}) OR to_memory_id IN ({marks})", (*chunk, *chunk))
        if _has_table(db, "memory_entry_native"):
            db.execute(f"DELETE FROM memory_entry_native WHERE entry_id IN ({marks})", chunk)


def _catch_up(ref: StoreRef, db: sqlite3.Connection, root_db: sqlite3.Connection, meta: dict[str, str]) -> tuple[frozenset[str], str | None] | None:
    """Apply forgets this store has not seen. Returns (withheld ids, note), or None when the store must not be read.

    A store whose ``forget_epoch_applied`` is not behind the root's clock costs one meta read. Otherwise the
    revocations newer than its number are applied to the file; if it cannot be written the same ids are withheld
    from the caller, so a forgotten text never comes back through a file that was not yet cleaned.
    """
    clock = _root_clock(root_db)
    if clock is None:
        return None
    try:
        applied = int(meta.get("forget_epoch_applied", "0"))
    except ValueError:
        applied = 0
    #'': a rewrite (VACUUM) that did not finish is kept in the file (``forget_residue_pending``, written with the cursor), so it survives a restart and a kill; only the rewrite is redone, the lines are not blanked again.
    residue_note: str | None = None
    if RESIDUE_PENDING_KEY in meta and not _rewrite_store(ref):
        residue_note = "forget_residue_busy"
    if applied >= clock:
        return frozenset(), residue_note
    ids = forgotten_ids(root_db, after=applied)
    if ids is None:
        return None
    hashes = forgotten_hashes(root_db, after=applied)
    if not ids and not hashes:
        return frozenset(), residue_note
    if not _has_table(db, "memory_entries"):
        return frozenset(), residue_note
    present_ids: set[str] = set()
    for chunk in range(0, len(ids), 800):
        part = list(ids)[chunk:chunk + 800]
        present_ids.update(row[0] for row in db.execute(
            f"SELECT id FROM memory_entries WHERE id IN ({','.join('?' * len(part))}) AND (content<>'' OR superseded_at IS NULL)", part))
    unkeyed: set[str] = set()
    if hashes:
        # A store that was not connected when a text was forgotten has no id of it in the ledger: the words themselves
        # are what the ledger holds, so the same words in this store go too (by the engine's own text hash).
        #'': "the same words" is the stamp's own rule (one trailing mark may differ; the kind never takes part when the ruleset is usable), so what is blanked here is what the stamp refuses to write again.
        from . import memory_classify
        from .memory_runtime import _content_hash
        rules = memory_classify.active()
        by_hash: dict[str, list[tuple[str, frozenset[str] | None]]] = {}
        for (kind, digest), owners in hashes.items():
            by_hash.setdefault(digest, []).append((kind, owners))
        for row in db.execute("SELECT id,kind,content,scope,project_id,project_path,agent_id,chat_id FROM memory_entries WHERE content<>''"):
            forms = {_content_hash(form) for form in memory_classify.forget_forms(row[2], rules)} if rules is not None else {_content_hash(row[2])}
            mine: list[str] | None = None
            reached = False
            for form in forms:
                for kind, owners in by_hash.get(form, ()):
                    if rules is None and kind != row[1]:
                        continue
                    if owners is None:   # a caller written for the old rule
                        reached = True
                        break
                    if mine is None:
                        try:
                            mine = row_owner_keys({"scope": row[3], "project_id": row[4], "project_path": row[5], "agent_id": row[6], "chat_id": row[7]})
                        except Exception:  # noqa: BLE001
                            mine = []
                    if not mine:
                        #'': an owner that cannot be worked out is NOT counted as reached: a delete is never widened by a missing key (only the lines the ledger names by id are blanked), and the line is kept out of
                        # reads at this open (withheld) - the side that never lets a forgotten text out. The desktop twin does the same (stores.ts presentForgotten `unkeyed`).
                        unkeyed.add(row[0])
                        continue
                    if owners.intersection(mine):
                        reached = True
                        break
                if reached:
                    break
            if reached:
                present_ids.add(row[0])
    present = sorted(present_ids)
    held = frozenset(unkeyed - present_ids)
    if not present:
        _stamp_epoch(ref, clock)
        return held, ("forget_catchup_withheld" if held else residue_note)
    done = _apply_forgets(ref, present, clock)
    if done:
        return held, ("forget_catchup_withheld" if held else (residue_note or ("forget_residue_busy" if done == "residue" else None)))
    return frozenset(present) | held, "forget_catchup_withheld"


RESIDUE_PENDING_KEY = "forget_residue_pending"
"""'': ``memory_store_meta`` key of a store whose old pages may still hold a forgotten text (lines blanked, cursor moved, the rewrite not finished: disk full, a reader holds the log, killed). Written in the same transaction as
``forget_epoch_applied`` (``_apply_forgets``), read by ``_catch_up`` on every open (the meta is already read), deleted only after a VACUUM and a clean TRUNCATE checkpoint. The desktop writes and reads the same key
(``RESIDUE_PENDING_KEY`` in stores.ts). No new table or column."""


def _vacuum_and_checkpoint(writer: sqlite3.Connection) -> bool:
    try:
        writer.execute("VACUUM")
        row = writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return not (row and row[0])
    except sqlite3.Error:
        return False


def _clear_residue_key(writer: sqlite3.Connection) -> None:
    try:
        writer.execute("DELETE FROM memory_store_meta WHERE key=?", (RESIDUE_PENDING_KEY,))
        writer.commit()
    except sqlite3.Error:
        pass  # the next open rewrites once more: harmless


def _rewrite_store(ref: StoreRef) -> bool:
    """Redo only the rewrite of a store whose lines are already blank. True when finished and the key is gone."""
    try:
        writer = sqlite3.connect(str(ref.path), timeout=CATCHUP_LOCK_WAIT, isolation_level=None)
    except sqlite3.Error:
        return False
    try:
        writer.execute("PRAGMA secure_delete=ON")
        if not _vacuum_and_checkpoint(writer):
            return False
        writer.isolation_level = ""
        _clear_residue_key(writer)
        return True
    finally:
        writer.close()


def _apply_forgets(ref: StoreRef, ids: list[str], clock: int) -> str | bool:
    """False = could not write (withhold); True = done; "residue" = lines blanked but the rewrite is still owed (the key stays in the file)."""
    from datetime import datetime, timezone
    try:
        writer = sqlite3.connect(str(ref.path), timeout=CATCHUP_LOCK_WAIT)
    except sqlite3.Error:
        return False
    try:
        writer.execute("PRAGMA secure_delete=ON")  # the pages the words leave are overwritten, not just unlinked
        writer.execute("BEGIN IMMEDIATE")
        heal_foreign_triggers(writer)  # a copied journal trigger would fail the DELETE of the original wording below and leave the forgotten text withheld for good
        _blank(writer, ids, datetime.now(timezone.utc).isoformat())
        writer.execute("INSERT INTO memory_store_meta(key,value) VALUES('forget_epoch_applied',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(clock),))
        writer.execute("INSERT INTO memory_store_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (RESIDUE_PENDING_KEY, str(clock)))
        writer.commit()
        #': a page a writer without secure_delete split or rebalanced keeps the old cell bytes in its unused part, where no cell points and the blanking above cannot reach (found by reading every byte of an agent
        # store after its line was forgotten). The store that just held the words is rewritten (one file, every page new); a store is small. A store that is locked keeps its pages for the next open: the ids stay applied, the words
        # may still be in the old pages, and that is told as `forget_residue_busy` by the desktop's twin; here the catch-up has no such note, so the next forget of anything in this store rewrites it again.
        if not _vacuum_and_checkpoint(writer):
            return "residue"
        _clear_residue_key(writer)
        return True
    except sqlite3.Error:
        try:
            writer.rollback()
        except sqlite3.Error:
            pass
        return False
    finally:
        writer.close()


def _stamp_epoch(ref: StoreRef, clock: int) -> None:
    """Nothing left to blank: record that the store has seen the clock (a failure only means the next open checks again)."""
    try:
        writer = sqlite3.connect(str(ref.path), timeout=0.2)
        try:
            writer.execute("INSERT INTO memory_store_meta(key,value) VALUES('forget_epoch_applied',?) "
                           "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(clock),))
            writer.commit()
        finally:
            writer.close()
    except sqlite3.Error:
        pass


def open_store(ref: StoreRef, owner: str, root_db: sqlite3.Connection, *, create: bool = False) -> tuple[OpenedStore | None, str | None]:
    """Open one store for reading. Returns (store, None), (store, note) or (None, code).

    ``None`` with ``store_absent`` means the file is not there, which is a normal "empty store"; every other code is a
    store that exists but was skipped. A read creates nothing. With ``create=True`` (the writers' path) a missing
    store is made first by ``ensure_store`` and then opened the same way; it is refused (``agent_home_absent``) for an
    agent whose folder the desktop has not marked with an owner.json, because the engine never builds an agent folder.
    """
    path = ref.path
    try:
        if not path.is_file():
            if not create:
                return None, "store_absent"
            made = ensure_store(ref, owner)
            if made:
                return None, made
    except OSError:
        return None, "store_unreadable"
    problem = _contained_agent_path(ref) if ref.kind == AGENT else _contained_account_path(ref)
    if problem:
        return None, problem
    try:
        try:
            db = _connect_ro(path)
        except sqlite3.DatabaseError:
            # A store a ``kill -9`` or a power cut left with a hot rollback journal cannot be opened read-only (SQLite cannot roll the journal back through a
            # read-only connection), and it stays that way until something opens it for writing. A writer's path (``create=True``) opens it once for
            # writing, which rolls the journal back, and looks again (defect 17).
            if not create or not _recover_hot_journal(path):
                raise
            db = _connect_ro(path)
    except (sqlite3.Error, OSError, ValueError):
        return None, "store_unreadable"
    notes: list[str] = []
    try:
        meta = _meta(db)
        if meta.get("owner_namespace") not in (None, owner):
            db.close()
            return None, "owner_mismatch"
        if not _has_table(db, "memory_entries"):
            db.close()
            return None, "entries_missing"
        from .memory_runtime import SCHEMA
        if meta.get("schema_version") not in (None, "1", "2"):
            notes.append("degraded:schema_version")
        if meta.get("core_schema_version") not in (None, SCHEMA):
            notes.append("degraded:core_schema_version")
        if meta.get("store_kind") not in (None, ref.kind):
            notes.append("degraded:store_kind")
        if not meta:
            notes.append("degraded:meta_missing")
        caught = _catch_up(ref, db, root_db, meta)
        if caught is None:
            db.close()
            return None, "forget_clock_unreadable"
        withheld, note = caught
        if note:
            notes.append(note)
        return OpenedStore(ref, db, tuple(notes), withheld), None
    except sqlite3.Error:
        try:
            db.close()
        except sqlite3.Error:
            pass
        return None, "store_unreadable"


# --- which stores a read opens ----------------------------------------------------------------------------------

def stores_for_context(owner: str, *, project_path: str | os.PathLike[str] | None, project_ref_hint: str | None,
                       actor: str | None) -> list[StoreRef]:
    """Candidate stores for one turn or one search: the project's, and the answering agent's. The session store
    holds checkpoints and no row a recall path reads, so it is not part of this set."""
    refs: list[StoreRef] = []
    for key in project_keys(project_path, project_ref_hint):
        refs.append(project_ref(owner, key))
    agent_id = store_agent_id(actor)
    home = find_agent_home(agent_id, rescan=False) if agent_id else None
    if home is not None and agent_id:
        refs.append(agent_ref(owner, home, agent_id))
    return refs


def recent_stores(owner: str, exclude: Iterable[StoreRef], limit: int = 10 ** 9) -> tuple[list[StoreRef], int]:
    """Existing project and agent stores other than ``exclude``, most recently modified first, at most ``limit``.
    Returns (stores, how many more exist beyond the limit). One directory listing per kind; nothing is opened."""
    skip = {str(ref.path) for ref in exclude}
    found: list[tuple[float, StoreRef]] = []
    projects = account_dir(owner) / "projects"
    try:
        for entry in projects.iterdir():
            path = entry / STORE_FILE
            if str(path) in skip:
                continue
            try:
                found.append((path.stat().st_mtime, StoreRef(PROJECT, None, path)))
            except OSError:
                continue
    except OSError:
        pass
    # One entry per folder: owner.json may name several ids (aliases) for the same folder.
    folders = {str(folder): (ident, folder) for ident, folder in agent_folder_index().items()}
    for ident, folder in folders.values():
        path = agent_ref(owner, folder, ident).path
        if str(path) in skip:
            continue
        try:
            found.append((path.stat().st_mtime, StoreRef(AGENT, ident, path)))
        except OSError:
            continue
    found.sort(key=lambda pair: (pair[0], str(pair[1].path)), reverse=True)
    return [ref for _, ref in found[:limit]], max(0, len(found) - limit)


# --- hook read --------------------------------------------------------------------------------------------------

_POLICY = """(b.memory_id IS NULL OR b.owner_namespace=?)
  AND COALESCE(CASE WHEN json_valid(b.applicability_json) THEN json_extract(b.applicability_json,'$.enabled') END,1)!=0
  AND COALESCE(CASE WHEN json_valid(b.applicability_json) THEN json_extract(b.applicability_json,'$.recallChannel') END,'default')!='legacy_one_overlay'"""

_HOOK_PROJECT_SQL = f"""SELECT m.id,m.kind,m.content,m.created_at FROM memory_entries m
  LEFT JOIN memory_identity_bindings b ON b.memory_id=m.id
  WHERE m.superseded_at IS NULL AND {_POLICY} AND m.scope='project'
  ORDER BY m.created_at DESC,m.id DESC LIMIT {HOOK_LIMIT}"""

_HOOK_AGENT_SQL = f"""SELECT m.id,m.kind,m.content,m.created_at FROM memory_entries m
  LEFT JOIN memory_identity_bindings b ON b.memory_id=m.id
  WHERE m.superseded_at IS NULL AND {_POLICY} AND m.scope='agent_repo'
    AND (m.project_id IS NULL OR m.project_id=?) AND (m.project_path IS NULL OR m.project_path=?)
  ORDER BY m.created_at DESC,m.id DESC LIMIT {HOOK_LIMIT}"""


def hook_rows(root_db: sqlite3.Connection, owner: str, *, project_path: str | None, project_ref_hint: str | None,
              project_id: str | None, actor: str | None) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """Rows from the project and agent stores for the prompt hook, plus the codes of stores that were skipped or
    degraded. Never raises. ``project_id`` and ``project_path`` keep the agent store project-limited (N-B08) the way
    the root query does."""
    rows: list[tuple[str, str, str, str]] = []
    notes: list[str] = []
    forgotten = forgotten_ids(root_db)
    for ref in stores_for_context(owner, project_path=project_path, project_ref_hint=project_ref_hint, actor=actor):
        try:
            opened, code = open_store(ref, owner, root_db)
        except Exception:  # noqa: BLE001 - a hook never stops over one store
            notes.append(f"{ref.kind}:store_unreadable")
            continue
        if opened is None:
            if code != "store_absent":
                notes.append(f"{ref.kind}:{code}")
            continue
        notes.extend(f"{ref.kind}:{note}" for note in opened.notes)
        try:
            args: tuple[Any, ...] = (owner,) if ref.kind == PROJECT else (owner, project_id, project_path)
            for row in opened.db.execute(_HOOK_PROJECT_SQL if ref.kind == PROJECT else _HOOK_AGENT_SQL, args):
                if row[0] in opened.withheld or (forgotten and row[0] in forgotten):
                    continue
                rows.append((row[0], row[1], row[2], row[3]))
        except sqlite3.Error:
            notes.append(f"{ref.kind}:store_unreadable")
        finally:
            opened.db.close()
    return rows, notes


def merge_rows(*groups: Iterable[tuple[Any, ...]], limit: int = HOOK_LIMIT, actor: str | None = None, check_reader: bool = False,
               rules_on: bool = False, personal_flag: bool = False) -> list[tuple[Any, ...]]:
    """Newest first (``created_at`` then ``id``, both descending, the root query's own order), one row per id, at
    most ``limit``. The first group wins a duplicate id (a row copied to a store but not yet removed from the root).
    With the curator ruleset's ``stores`` block present the owner's Personal preference lines of the root rows
    (a fifth ``scope`` column) go first, see ``memory_classify.personal_first``; the other lines keep their order.

    ``rules_on`` / ``personal_flag`` (the workspace-rules switch the caller read once, and the host's flag): with the switch on and a reader that may
    not read Personal lines, no row of the ``user_identity`` scope is kept and nothing is put first; with it off the answer is what it was."""
    seen: dict[str, tuple[Any, ...]] = {}
    from . import memory_classify
    rules = memory_classify.active()
    closed = rules_on and not memory_classify.reads_personal(actor, rules, rules_on, personal_flag) if check_reader else False
    for group in groups:
        for row in group:
            # a Personal fact is read by the personal agent only. The SQL that produced the rows already leaves it out for any other
            # subject; a caller that names the reader (``check_reader``) has the rows checked here as well, so no path around that SQL reads it.
            if check_reader and len(row) > 4 and not memory_classify.personal_visible(row[4], row[1], actor, rules, rules_on, personal_flag):
                continue
            seen.setdefault(row[0], row)
    if closed:
        return sorted(seen.values(), key=lambda r: (str(r[3]), str(r[0])), reverse=True)[:limit]
    return memory_classify.personal_first(list(seen.values()), rules, limit=limit)

# --- writing stores -------------------------------------------------------------------------------------------
#
# Only the ``memory_layout = split-1`` path calls anything below. The tables a sub-store holds are the "entries" slice of
# schemas/memory-store.sql: the statements are picked out of that file by table name, so the file itself (which the desktop
# keeps as a character-for-character copy in electron/memory/schema.ts) is not touched. The ledger tables (tickets,
# decisions, the forget clock and revocations) stay in the root store only.
#
# Agentlas 2.0 adds the turn record (``memory_episodes``) to the slice: a line's turn record goes to the store that owns the line (§2.1, §4.1-3).
# Nothing writes an episode into a sub-store yet (K5 moves them); the table is only there, empty. Two deliberate differences from the root's table:
# the ``FOREIGN KEY(ticket_id) REFERENCES memory_tickets`` clause is left out (the ticket stays in the root, so the reference is by id only and a
# write with foreign keys on cannot fail on a table the sub-store does not have; a record leaves with its lines, not by cascade), and the table of
# the original wording of a summary (``memory_episode_native``, the desktop's own DDL) comes with its two forget triggers.

ENTRY_TABLES = ("memory_entries", "memory_identity_bindings", "memory_project_links", "memory_origin_links",
                "memory_relation_edges", "memory_episodes", "memory_store_meta")
SLICE_VERSION = "agentlas.memory-slice.v1"
_EPISODE_FK = re.compile(r",\s*FOREIGN KEY\(ticket_id\) REFERENCES memory_tickets\(ticket_id\) ON DELETE CASCADE")
EPISODE_NATIVE_DDL = ("CREATE TABLE IF NOT EXISTS memory_episode_native(episode_id TEXT PRIMARY KEY,summary_native TEXT NOT NULL,created_at TEXT NOT NULL)",
                      "CREATE TRIGGER IF NOT EXISTS memory_episode_native_forget AFTER UPDATE OF summary ON memory_episodes "
                      "WHEN NEW.summary IS NULL OR NEW.summary = '' BEGIN DELETE FROM memory_episode_native WHERE episode_id = NEW.episode_id; END",
                      "CREATE TRIGGER IF NOT EXISTS memory_episode_native_delete AFTER DELETE ON memory_episodes "
                      "BEGIN DELETE FROM memory_episode_native WHERE episode_id = OLD.episode_id; END")
"""The original-wording table of a turn summary and its two forget triggers, in the shape the desktop makes (``electron/memory/native-text.ts``; the desktop adds a
``native_embedding`` column in place when it opens a store, as it does for the line table)."""
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "memory-store.sql"


def _sql_statements(sql: str) -> list[str]:
    parts: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            parts.append(buffer.strip())
            buffer = ""
    return parts


def entries_slice_sql() -> list[str]:
    """The statements that make a sub-store: the entries tables, their revision triggers and the revision seed."""
    wanted = set(ENTRY_TABLES)
    picked: list[str] = []
    for statement in _sql_statements(_SCHEMA_PATH.read_text(encoding="utf-8")):
        body = "\n".join(line for line in statement.splitlines() if not line.lstrip().startswith("--"))
        table = re.match(r"\s*CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)", body, re.I)
        trigger = re.match(r"\s*CREATE\s+TRIGGER\s+IF\s+NOT\s+EXISTS\s+\w+[\s\S]*?\bON\s+(\w+)", body, re.I)
        if (table and table.group(1) in wanted) or (trigger and trigger.group(1) == "memory_entries") \
                or re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\s+memory_store_meta", body, re.I):
            text = body.strip()
            if table and table.group(1) == "memory_episodes":
                text = _EPISODE_FK.sub("", text, count=1)
            picked.append(text)
    return picked + list(EPISODE_NATIVE_DDL)


COLUMNS_KEY = "store_columns"
COLUMNS_VALUE = "k1"
K1_COLUMNS = (("memory_entries", "origin_class"), ("memory_entries", "certainty"), ("memory_entries", "derived_by"), ("memory_episodes", "detail_json"))
"""The columns Agentlas 2.0 adds (§4.1 1-2): a line's origin class, certainty and who derived it; a turn record's detail. All TEXT, all NULL for every
row that exists (nothing is invented for an old row). ``schemas/memory-store.sql`` has them for a store made from now on; ``ensure_k1_columns`` adds them to one made before."""


def ensure_k1_columns(db: sqlite3.Connection) -> str:
    """Add the K1 columns a store lacks, once, and say so in the store's own meta (``store_columns = k1``). Safe to call on every open and from two processes.

    Answers ``present`` (the marker is there: one meta read, nothing else), ``added`` (columns were added and marked), ``partial`` (a table the columns belong to
    is not in this file yet; what could be added was; no marker, so the next open looks again), ``locked`` (another process holds the file: nothing was changed, the next open
    does it; the wait is the connection's own busy timeout, so this never waits longer than any other write of this process) or ``no_meta`` (not a memory store).
    Never raises over a database error: a store that cannot take the columns now is simply read and written as it was (no code reads a new column before K2). An open
    transaction of the caller is joined, not committed. A process killed in the middle leaves either the columns or not (SQLite's journal), and the marker is written in the same
    transaction as the last of them, so the next open finishes whatever is missing."""
    from .memory_runtime import assert_write_root_isolated
    try:
        files = [row[2] for row in db.execute("PRAGMA database_list").fetchall() if row[1] == "main" and row[2]]
    except sqlite3.Error:
        files = []
    if files:  # the one error this function raises: a test run must not add columns to a store inside the real root
        assert_write_root_isolated(files[0])
    try:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_store_meta'").fetchone() is None:
            return "no_meta"
        row = db.execute("SELECT value FROM memory_store_meta WHERE key=?", (COLUMNS_KEY,)).fetchone()
        if row and row[0] == COLUMNS_VALUE:
            return "present"
        own = not db.in_transaction
        if own:
            db.execute("BEGIN IMMEDIATE")
        try:
            complete = True
            for table, column in K1_COLUMNS:
                have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                if not have:
                    complete = False
                elif column not in have:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
            if complete:
                db.execute("INSERT OR REPLACE INTO memory_store_meta(key,value) VALUES(?,?)", (COLUMNS_KEY, COLUMNS_VALUE))
            if own:
                db.commit()
        except BaseException:
            if own:
                db.rollback()
            raise
        return "added" if complete else "partial"
    except sqlite3.OperationalError as error:
        text = str(error).lower()
        if "locked" in text or "busy" in text:
            return "locked"
        if "duplicate column" in text:  # a second process added it between the look and the ALTER: the next open marks it
            return "locked"
        raise
    except sqlite3.DatabaseError:
        return "locked"


def _local_folder_of(ref: StoreRef) -> Path:
    state = ref.path
    for _ in range(3):
        state = state.parent
    return state


def ensure_store(ref: StoreRef, owner: str) -> str | None:
    """Make an empty sub-store file if it is missing. Returns None, or a code for why it was not made.

    The file is built whole under a temporary name and linked into place, so a reader or a second creator never sees a
    half-made store and never loses rows to a replace. An agent store is only made inside a folder the desktop already
    marked with an owner.json; the folder itself is never created here.
    """
    problem = _contained_agent_path(ref) if ref.kind == AGENT else _contained_account_path(ref)
    if problem:
        return problem
    if ref.kind == AGENT:
        marker = _local_folder_of(ref) / agent_home.AGENT_OWNER_FILE
        try:
            if marker.is_symlink() or not marker.is_file():
                return "agent_home_absent"
        except OSError:
            return "agent_home_absent"
    temporary = ref.path.with_name(f".{ref.path.name}.new-{os.getpid()}-{os.urandom(4).hex()}")
    try:
        ref.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(str(temporary))
        try:
            db.execute("PRAGMA secure_delete=ON")
            for statement in entries_slice_sql():
                db.execute(statement)
            from .memory_runtime import SCHEMA
            for key, value in (("schema_version", "1"), ("core_schema_version", SCHEMA), ("owner_namespace", owner),
                               ("store_kind", ref.kind), ("store_ref", ref.key or ""), ("store_slice", SLICE_VERSION),
                               ("forget_epoch_applied", "0"), (COLUMNS_KEY, COLUMNS_VALUE)):
                db.execute("INSERT OR IGNORE INTO memory_store_meta VALUES(?,?)", (key, value))
            db.commit()
        finally:
            db.close()
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        try:
            os.link(temporary, ref.path)
        except FileExistsError:
            pass
        except OSError:  # a file system without hard links: rename, which is only unsafe if a second creator races this exact moment
            if not ref.path.exists():
                os.replace(temporary, ref.path)
    except (OSError, sqlite3.Error):
        return "store_unwritable"
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass
    return None


def open_store_for_write(ref: StoreRef, owner: str, root_db: sqlite3.Connection) -> tuple[sqlite3.Connection | None, str | None]:
    """A read-write connection to a sub-store (made if missing), or (None, code). The caller falls back to the root.

    Refused when the store is another owner's, has a newer schema than this engine writes, is a link, or still holds a
    forget it cannot apply: new rows never go into a file that has not been cleaned of what the owner forgot.
    """
    from .memory_runtime import assert_write_root_isolated
    assert_write_root_isolated()
    opened, code = open_store(ref, owner, root_db, create=True)
    if opened is None:
        return None, code
    notes = opened.notes
    opened.db.close()
    if opened.withheld:
        return None, "forget_catchup_withheld"
    if any(note.startswith("degraded:schema_version") or note.startswith("degraded:core_schema_version") for note in notes):
        return None, "store_schema_newer"
    try:
        db = sqlite3.connect(str(ref.path), timeout=0.5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")  #': a page this connection splits or rebalances keeps no copy of the cells that moved
        db.execute("PRAGMA foreign_keys=ON")
        for statement in entries_slice_sql():  # a store another tool left half made is completed, never rebuilt
            db.execute(statement)
        heal_foreign_triggers(db)  # a store an earlier engine poisoned with the desktop's journal triggers is cleaned before anything is written to it
        db.commit()
        ensure_k1_columns(db)  # K1: the new columns of a store made before them (one meta read once it is marked)
        return db, None
    except sqlite3.Error:
        return None, "store_unwritable"


def store_revision(db: sqlite3.Connection) -> int:
    try:
        row = db.execute("SELECT value FROM memory_store_meta WHERE key='revision'").fetchone()
        return int(row[0]) if row else 0
    except (sqlite3.Error, ValueError, TypeError):
        return 0


def remove_agent_memory_md(ref: StoreRef) -> bool:
    """Earlier engines wrote ``MEMORY.md`` beside an agent store; nothing reads it and it kept forgotten words on disk.
    Remove it (and its temporary files) wherever it is found. Never raises."""
    if ref.kind != AGENT:
        return False
    removed = False
    try:
        for name in os.listdir(ref.path.parent):
            if name == "MEMORY.md" or (name.startswith(".MEMORY.md.") and name.endswith(".tmp")):
                try:
                    (ref.path.parent / name).unlink()
                    removed = True
                except OSError:
                    pass
    except OSError:
        pass
    return removed
