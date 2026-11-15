"""The 2.0 first-run step ``tidy`` (Agentlas 2.0): converts and tidies what a 1.x memory store piled up. No model is called; no new table or column.

Seven units, each safe to call again, each in transactions that choose their rows again under the write lock (a kill between two batches leaves every
batch whole or absent; the next call goes on from what is left; pending work is answered by the data, never by a table of progress of ours):

  ``translation_queue`` rows of ``memory_translation_jobs`` still ``pending``. The worker that read them is gone ('), and the move used to keep a line in the root
                         while a job for it was pending: with the queue left alone those lines would never move. Nothing reads a finished job either, but they are
                         a few hundred rows of provenance and are left.
  ``receipts``           ``memory_source_mappings``: the 1.x desktop's per-row receipts of the copy into this store. The one reader (the desktop's forget path,
                         ``purgeLegacyMemoryCopies``) now finds a legacy copy by the frozen row itself. Run only by a desktop that has that reader (it is the only caller).
  ``hub_drawers`` the old per-agent drawers ``networking/hub-agents/<slug>/memory`` and the ``hub:<slug>`` rows of agents that were only called from the Hub.
                         A slug this computer has registered, or has a ``local-<slug>`` card for (the turn-start hook still reads such a drawer), is never touched; neither
                         is a drawer written in the last 24 hours.
  ``removed_agents`` the rows of agents the DESKTOP names as removed (it knows its own agent list; the engine does not). Each is checked again here: an id that
                         has a folder on this computer is skipped. The removal itself is ``memory_split.forget_agent`` (rows, turns, views, search index, one path).
  ``turn_folders``       an old turn record (ticket and summary) that names no working folder gets ``project_path_hash`` (sha256 of the path, the value the hooks write now,
                         e17f83cc) when its operation row still carries the folder in its payload; no operation row or no folder = left empty, nothing is guessed. Turn records stay
                         in the root (``memory_split.ROW_TABLES`` has no episodes table: confirmed).
  ``embeddings``         ``embedding_json`` of lines and turn summaries: the text of 96 or 256 numbers (about 2.4 KB) becomes ``q8:<scale>:<base64 of one signed byte per
                         number>`` (the 256 numbers become 256 bytes). A row is rewritten only when the decoded vector has the same length and a cosine of at least
                         0.9999 with the original, and only while the stored text is still exactly the one that was read. The desktop reads both forms.
  ``fill``               the two columns of a line (``origin_class``, ``certainty``): only a line whose own evidence carries BOTH host marks ``origin:owner-spoke`` and
                         ``origin:instruction`` (the owner wrote the turn and it was an instruction) gets ``user`` / ``self_reported``. Every other old line is left empty =
                         "no source" (the migration invents nothing). No line is ever removed for lacking a source.
  ``stamp``              ``first_run_stamp`` in the store's own meta (root and every sub-store that was visited): written once, the mark of "this store was converted".

What stays and why is in the answer: the ``similar_to`` edges are still read by the lessons grouping, the memory map and the inspector and are still written with every
new line, so they are counted and left (``left``). Free pages are not reclaimed here (the app's one VACUUM at quit does it, behind its own disk check).

The root's ``schema_version`` is raised from "1" to "2" in the same transaction as the root's stamp: an engine that knows only "1" (1.2.96, 1.2.97) then refuses to open the root (its hook answers ``{}``
and writes nothing); this engine and the 2.0 desktop accept both numbers. Sub-stores keep "1".
"""
from __future__ import annotations

import base64
import json
import math
import os
import sqlite3
import time
from array import array
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

from . import memory_stores as ms
from .first_run import _code, _tables, _meta

TIDY_SCHEMA = "agentlas.first-run-tidy.v1"
UNITS = ("translation_queue", "receipts", "hub_drawers", "removed_agents", "turn_folders", "embeddings", "fill", "stamp")
STAMP_KEY = "first_run_stamp"
STAMP_VERSION = 1
CONVERTED_SCHEMA_VERSION = "2"   # the root's `schema_version` once it is converted: an engine that knows only "1" (1.2.96, 1.2.97) steps back (hook answers `{}`, nothing is written); this one and the 2.0 desktop accept both
# How many rows one transaction may hold at most. The pacer (memory_split.BatchPacer) lowers the size to what keeps the write lock about 0.12 s.
# Measured on the synthetic 1.x home of tests/test_first_run_tidy.py (see evidence/k5-prime/RESULT.md): the light rows (a job, a receipt) go several thousand per
# 0.12 s; a row that carries text or a vector is slower, so those units start lower. Reaching the cap only means "as big as one transaction may be".
LIGHT_ROWS = 2000
HEAVY_ROWS = 200
HUB_DRAWER_GRACE_SECONDS = 24 * 3600   # = first_run.WORK_ROW_GRACE_HOURS: a drawer touched in the last day may belong to a session that is running; it is looked at again on a later call
COSINE_FLOOR = 0.999                   # a vector is rewritten only above this. Measured on the 1,599 real model2vec vectors of the engine's 79-pair set: worst 0.999808, 38 below 0.9999, none below 0.9995, and the rankings of all 79 pairs keep the same top-8 set and the same gold ranks (evidence/k5-prime/raw/eval79-q8.json)
COMPACT_EMBEDDINGS = True              # the ONE switch of the vector rewrite: False leaves every vector as it is (the unit answers done at once)
REMOVED_AGENTS_PER_CALL = 20           # one forget_agent opens, purges and rebuilds views of the root: this many per call, the rest on the next
MAX_DIMENSIONS = 2048


# --- the q8 form of a vector --------------------------------------------------------------------------------------------

def compact_vector(text: str) -> str | None:
    """``q8:<scale>:<base64>`` for a stored vector text, or None when the text is not a plain list of finite numbers or the rewrite would not be faithful."""
    if not isinstance(text, str) or not text.startswith("["):
        return None
    try:
        vector = json.loads(text)
    except ValueError:
        return None
    if not isinstance(vector, list) or not 0 < len(vector) <= MAX_DIMENSIONS:
        return None
    try:
        values = [float(v) for v in vector if not isinstance(v, bool)]
    except (TypeError, ValueError):
        return None
    if len(values) != len(vector) or any(not math.isfinite(v) for v in values):
        return None
    top = max(abs(v) for v in values)
    if top == 0.0:
        return None
    scale = float(f"{top / 127.0:.9g}")          # the text we store is the scale we quantise with, so the decoder sees exactly it
    packed = array("b", (max(-127, min(127, round(v / scale))) for v in values))
    encoded = f"q8:{scale:.9g}:{base64.b64encode(packed.tobytes()).decode('ascii')}"
    back = expand_vector(encoded)
    if back is None or len(back) != len(values):
        return None
    dot = sum(a * b for a, b in zip(values, back))
    norm = math.sqrt(sum(a * a for a in values)) * math.sqrt(sum(b * b for b in back))
    if norm == 0.0 or dot / norm < COSINE_FLOOR:
        return None
    return encoded


def expand_vector(text: str) -> list[float] | None:
    """The numbers of a stored vector, from either form (the JSON list or ``q8:``). The twin of the desktop's ``decodeStoredVector``."""
    if not isinstance(text, str):
        return None
    if text.startswith("q8:"):
        try:
            _, scale, payload = text.split(":", 2)
            raw = base64.b64decode(payload, validate=True)
            return [value * float(scale) for value in array("b", raw)]
        except (ValueError, TypeError):
            return None
    try:
        vector = json.loads(text)
    except ValueError:
        return None
    return [float(v) for v in vector] if isinstance(vector, list) else None


# --- helpers ------------------------------------------------------------------------------------------------------------

def _answer(unit: str, state: str, **more: Any) -> dict[str, Any]:
    return {"unit": unit, "state": state, **more}


def _locked_or_full(error: BaseException) -> str | None:
    """A code when the error is "not now" (another process holds the file, the disk is full), None when it is something else."""
    from . import memory_split as split
    if isinstance(error, sqlite3.OperationalError):
        text = str(error).lower()
        if "locked" in text or "busy" in text:
            return "locked"
        if split._is_disk_full(error):
            return "disk_full"
    return None


def _txn(db: sqlite3.Connection, work: Callable[[], int]) -> tuple[int, float]:
    """One transaction: the write lock is taken first, the rows are chosen inside it, and the hold (lock to commit) is measured for the pacer."""
    db.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        done = work()
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return done, time.monotonic() - started


def _loop(db: sqlite3.Connection, cap: int, over: Callable[[], bool], work: Callable[[int], int], *, secure: bool = False) -> tuple[int, bool]:
    """Batches of ``work(n)`` (rows it handled, 0 = nothing left) until nothing is left or the budget is over. Returns (rows, finished)."""
    from . import memory_split as split
    pacer = split.BatchPacer(cap)
    total = 0
    if secure:
        db.execute("PRAGMA secure_delete=ON")
    while True:
        if over():
            return total, False
        size = pacer.size
        done, held = _txn(db, lambda: work(size))
        pacer.took(held, done)
        total += done
        if done == 0:
            return total, True
        time.sleep(split.PAUSE_SECONDS)   # the lock is free between two batches, long enough for a waiting writer to get it


# --- units on the root --------------------------------------------------------------------------------------------------

def unit_translation_queue(db: sqlite3.Connection, over: Callable[[], bool]) -> dict[str, Any]:
    if "memory_translation_jobs" not in _tables(db):
        return _answer("translation_queue", "done", removed=0)
    removed, finished = _loop(db, LIGHT_ROWS, over, lambda n: db.execute(
        "DELETE FROM memory_translation_jobs WHERE rowid IN (SELECT rowid FROM memory_translation_jobs WHERE state='pending' LIMIT ?)", (n,)).rowcount)
    return _answer("translation_queue", "done" if finished else "remaining", removed=removed)


def unit_receipts(db: sqlite3.Connection, over: Callable[[], bool]) -> dict[str, Any]:
    if "memory_source_mappings" not in _tables(db):
        return _answer("receipts", "done", removed=0)
    removed, finished = _loop(db, LIGHT_ROWS, over, lambda n: db.execute(
        "DELETE FROM memory_source_mappings WHERE rowid IN (SELECT rowid FROM memory_source_mappings LIMIT ?)", (n,)).rowcount)
    return _answer("receipts", "done" if finished else "remaining", removed=removed)


def _registered_slugs() -> tuple[set[str], list[Path]]:
    """Slugs this computer registered (an agent folder, a local definition) and the folders of the global cards (both places the engine puts them: the networking
    home and the folder beside the drawers). Nothing is created."""
    from .agent_usability import RegisteredHere, norm_slug
    here = RegisteredHere()
    slugs = {norm_slug(name) for name in (*here.folders, *here.registry_slugs)}
    cards: list[Path] = []
    try:
        from .networking.bootstrap import hub_agents_dir, networking_home
        cards = [networking_home() / "cards" / "agents", hub_agents_dir().parent / "cards" / "agents"]
    except Exception:  # noqa: BLE001 - without a card folder only the first rule keeps a drawer
        cards = []
    return {slug for slug in slugs if slug}, cards


def _is_called_only(slug: str, registered: set[str], cards: list[Path]) -> bool:
    from .agent_usability import norm_slug
    key = norm_slug(slug)
    if not key or key in registered:
        return False
    if any((folder / f"local-{key}.json").exists() for folder in cards):
        return False
    return True


def unit_hub_drawers(rt: Any, over: Callable[[], bool], *, now: float | None = None) -> dict[str, Any]:
    """ Drawers first (files), then the ``hub:`` rows of the same kind of agent. Idempotent: a second call finds neither."""
    from . import memory_split as split
    from .networking.bootstrap import hub_agents_dir
    now = time.time() if now is None else now
    registered, cards = _registered_slugs()
    base = hub_agents_dir()
    drawers = skipped_recent = skipped_registered = 0
    try:
        names = sorted(item.name for item in base.iterdir() if item.is_dir() and not item.is_symlink())
    except OSError:
        names = []
    for name in names:
        if over():
            return _answer("hub_drawers", "remaining", drawers=drawers, rows=0)
        if not _is_called_only(name, registered, cards):
            skipped_registered += 1
            continue
        drawer = base / name / "memory"
        if not drawer.exists() and not drawer.is_symlink():
            continue
        if drawer.is_symlink():
            continue   # never follow or remove a link
        try:
            newest = max([drawer.stat().st_mtime, *(p.stat().st_mtime for p in drawer.rglob("*"))])
        except OSError:
            continue
        if now - newest < HUB_DRAWER_GRACE_SECONDS:
            skipped_recent += 1
            continue
        if split._rmtree_owned(drawer, base):
            drawers += 1
            try:
                (base / name).rmdir()          # the slug's folder when the drawer was all it held
            except OSError:
                pass
    # the rows: only agent ids of the Hub family (`hub:<slug>`), only slugs that are called-only
    db = rt.db
    rows = 0
    if "memory_entries" in _tables(db):
        ids: list[str] = []
        for row_id, agent in db.execute("SELECT id,agent_id FROM memory_entries WHERE agent_id LIKE 'hub:%'").fetchall():
            if _is_called_only(str(agent)[4:], registered, cards):
                ids.append(row_id)
        for chunk in split._chunks(ids, 200):
            if over():
                return _answer("hub_drawers", "remaining", drawers=drawers, rows=rows)
            split.purge_entries(rt, chunk)
            rows += len(chunk)
            time.sleep(split.PAUSE_SECONDS)
    return _answer("hub_drawers", "done", drawers=drawers, rows=rows, keptRecent=skipped_recent, keptRegistered=skipped_registered)


REMOVED_MAX_SHARE = 0.5   # a call that names more than half of the agents that have memory is a wrong list, not a removal: refused whole (closed word `removed_over_half`); the same share the desktop holds itself to


def _agents_with_memory(rt: Any) -> set[str]:
    """The plain agents (not One, ``host:*``, Hub) that have memory on this computer: a live line in the root, or an agent folder (its lines are in its own store once moved). What "half" is counted against."""
    found: set[str] = set()
    try:
        found.update(i for i in (ms.store_agent_id(k) for k in ms.agent_folder_index()) if i is not None)
    except OSError:
        pass
    for (agent,) in rt.db.execute("SELECT DISTINCT agent_id FROM memory_entries WHERE scope='agent_repo' AND agent_id IS NOT NULL"):
        aid = ms.store_agent_id(agent)
        if aid is not None:
            found.add(aid)
    return found


def unit_removed_agents(owner: str, removed: Iterable[str], over: Callable[[], bool], rt: Any = None) -> dict[str, Any]:
    from . import memory_split as split
    ids = list(dict.fromkeys(item for item in removed if isinstance(item, str) and item))
    if ids and rt is not None:
        named = {ms.store_agent_id(i) for i in ids} - {None}
        have = _agents_with_memory(rt)
        # the caller's list is not believed as it stands: more than half of the agents with memory "removed" is a registry that went wrong (a line of unclear ownership stays)
        if len(named & have) > len(have) * REMOVED_MAX_SHARE:
            return _answer("removed_agents", "remaining", agents=0, skipped=len(ids), reason="removed_over_half", reasons={"removed_over_half": len(ids)})
    done = skipped = left = 0
    reasons: Counter = Counter()
    for index, agent_id in enumerate(ids):
        if over() or index >= REMOVED_AGENTS_PER_CALL:
            return _answer("removed_agents", "remaining", agents=done, skipped=skipped, rest=len(ids) - index)
        aid = ms.store_agent_id(agent_id)
        if aid is None:
            skipped += 1
            reasons["not_an_agent_with_memory"] += 1
            continue
        if ms.find_agent_home(aid) is not None:   # a folder of this agent exists here: it is not removed, whatever the caller thinks
            skipped += 1
            reasons["has_folder"] += 1
            continue
        result = split.forget_agent(owner, aid)
        if result.get("state") == "forgotten":
            done += 1
        else:
            left += 1
            reasons[str(result.get("state"))] += 1
    return _answer("removed_agents", "remaining" if left else "done", agents=done, skipped=skipped, left=left, reasons=dict(reasons))


# --- units on the root and every sub-store -------------------------------------------------------------------------------

def _stores(owner: str, rt: Any) -> Iterable[tuple[str, sqlite3.Connection | None, str | None]]:
    """The root, then every sub-store file that exists (opened for writing the way the engine writes to it: forget catch-up first). A store that cannot be
    opened now is answered with its code and skipped; nothing here creates a store."""
    yield "root", rt.db, None
    refs, _more = ms.recent_stores(owner, [])
    for ref in refs:
        try:
            db, code = ms.open_store_for_write(ref, owner, rt.db)
        except (sqlite3.Error, OSError, ValueError) as error:
            yield ref.kind, None, _locked_or_full(error) or "store_unreadable"
            continue
        if db is None:
            yield ref.kind, None, code
            continue
        try:
            yield ref.kind, db, None
        finally:
            db.close()


def unit_turn_folders(db: sqlite3.Connection, over: Callable[[], bool]) -> dict[str, Any]:
    import hashlib
    tables = _tables(db)
    if not {"memory_tickets", "memory_episodes", "memory_operations"} <= tables:
        return _answer("turn_folders", "done", filled=0)
    if "project_path_hash" not in {r[1] for r in db.execute("PRAGMA table_info(memory_tickets)")}:
        return _answer("turn_folders", "done", filled=0)

    def work(n: int) -> int:
        rows = db.execute(
            "SELECT t.ticket_id, json_extract(o.payload_json,'$.project_path') FROM memory_tickets t JOIN memory_operations o ON o.operation_id=t.ticket_id "
            "WHERE COALESCE(t.project_path_hash,'')='' AND json_valid(o.payload_json) AND COALESCE(json_extract(o.payload_json,'$.project_path'),'')<>'' LIMIT ?", (n,)).fetchall()
        for ticket, path in rows:
            value = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
            db.execute("UPDATE memory_tickets SET project_path_hash=? WHERE ticket_id=? AND COALESCE(project_path_hash,'')=''", (value, ticket))
            db.execute("UPDATE memory_episodes SET project_path_hash=? WHERE ticket_id=? AND COALESCE(project_path_hash,'')=''", (value, ticket))
        return len(rows)
    filled, finished = _loop(db, HEAVY_ROWS, over, work)
    return _answer("turn_folders", "done" if finished else "remaining", filled=filled)


def _store_file(db: sqlite3.Connection) -> str:
    """The file of an open store (a stable name for "this store" across the units of one call)."""
    try:
        return next((str(r[2]) for r in db.execute("PRAGMA database_list") if r[1] == "main"), "")
    except sqlite3.Error:
        return ""


def _converted(db: sqlite3.Connection) -> bool:
    """The stamp says "converted": the vectors and the two columns of this store were finished once. Lines written afterwards are written in the new form, so a stamped
    store is not read again (D2, migration MG-1: every start used to read all 53 stores again for the 9 vectors that cannot be rewritten)."""
    try:
        return _meta(db, STAMP_KEY) is not None
    except sqlite3.Error:
        return False


def unit_embeddings(owner: str, rt: Any, over: Callable[[], bool], unfinished: set[str] | None = None) -> dict[str, Any]:
    """``unfinished`` (optional) receives the files of the stores this call did not finish, so the stamp unit does not stamp them."""
    if not COMPACT_EMBEDDINGS:
        return _answer("embeddings", "done", rewritten=0, kept=0, off=True)
    rewritten = kept = 0
    blocked: Counter = Counter()
    finished_all = True
    for kind, db, code in _stores(owner, rt):
        if db is None:
            blocked[code or "store_unreadable"] += 1
            continue
        if _converted(db):
            continue
        file = _store_file(db)
        for table in ("memory_entries", "memory_episodes"):
            if over():
                if unfinished is not None:
                    unfinished.add(file)
                return _answer("embeddings", "remaining", rewritten=rewritten, kept=kept)
            try:
                have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            except sqlite3.Error:
                continue
            if "embedding_json" not in have:
                continue
            last = [0]
            skipped_here = [0]

            def work(n: int, table: str = table, db: sqlite3.Connection = db, last: list[int] = last, skipped_here: list[int] = skipped_here) -> int:
                rows = db.execute(f"SELECT rowid,embedding_json FROM {table} WHERE rowid>? AND embedding_json LIKE '[%' ORDER BY rowid LIMIT ?", (last[0], n)).fetchall()
                handled = 0
                for rowid, text in rows:
                    last[0] = rowid
                    handled += 1
                    packed = compact_vector(text)
                    if packed is None:
                        skipped_here[0] += 1
                        continue
                    changed = db.execute(f"UPDATE {table} SET embedding_json=? WHERE rowid=? AND embedding_json=?", (packed, rowid, text)).rowcount
                    if not changed:
                        skipped_here[0] += 1
                return handled
            try:
                seen, finished = _loop(db, HEAVY_ROWS, over, work)
            except sqlite3.Error as error:
                reason = _locked_or_full(error)
                if reason is None:
                    raise
                blocked[reason] += 1
                finished_all = False
                if unfinished is not None:
                    unfinished.add(file)
                continue
            rewritten += seen - skipped_here[0]
            kept += skipped_here[0]
            if not finished:
                finished_all = False
                if unfinished is not None:
                    unfinished.add(file)
    done = finished_all and not blocked
    return _answer("embeddings", "done" if done else "remaining", rewritten=rewritten, kept=kept, **({"blocked": dict(blocked)} if blocked else {}))


_OWNER_MARKS = ("origin:owner-spoke", "origin:instruction")
_FILL_WHERE = ("origin_class IS NULL AND certainty IS NULL AND content<>'' AND json_valid(evidence_json) AND "
               "EXISTS(SELECT 1 FROM json_each(evidence_json) WHERE value=?) AND EXISTS(SELECT 1 FROM json_each(evidence_json) WHERE value=?)")


def unit_fill_and_stamp(owner: str, rt: Any, over: Callable[[], bool], *, now: float | None = None, unfinished: set[str] | None = None) -> dict[str, Any]:
    """The two columns of the lines that say they came from the owner's own instruction, then the stamp. A store whose columns are not there yet is
    stamped no more than it is filled (it is looked at again): the stamp means "converted"."""
    filled = 0
    stamped = 0
    blocked: Counter = Counter()
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if now is None else now))
    finished_all = True
    for kind, db, code in _stores(owner, rt):
        if db is None:
            blocked[code or "store_unreadable"] += 1
            finished_all = False
            continue
        try:
            if _converted(db):
                continue
            if over():
                return _answer("fill", "remaining", filled=filled, stamped=stamped)
            state = ms.ensure_k1_columns(db)
            if state in ("locked", "no_meta"):
                blocked[f"columns_{state}"] += 1
                finished_all = False
                continue
            have = {r[1] for r in db.execute("PRAGMA table_info(memory_entries)")}
            if not {"origin_class", "certainty"} <= have:
                blocked["columns_missing"] += 1
                finished_all = False
                continue
            last = [0]

            def work(n: int) -> int:
                rows = [r[0] for r in db.execute(f"SELECT rowid FROM memory_entries WHERE rowid>? AND {_FILL_WHERE} ORDER BY rowid LIMIT ?", (last[0], *_OWNER_MARKS, n))]
                if not rows:
                    return 0
                marks = ",".join("?" * len(rows))
                # chosen again by the same condition: a line the owner edited or a hook filled meanwhile is not overwritten
                db.execute(f"UPDATE memory_entries SET origin_class='user', certainty='self_reported' WHERE rowid IN ({marks}) AND {_FILL_WHERE}", (*rows, *_OWNER_MARKS))
                last[0] = rows[-1]
                return len(rows)
            count, finished = _loop(db, HEAVY_ROWS, over, work)
            filled += count
            if not finished:
                finished_all = False
                continue
            if unfinished and _store_file(db) in unfinished:   # its vectors were not finished in this call: not "converted" yet
                finished_all = False
                continue
            if _meta(db, STAMP_KEY) is None:
                db.execute("BEGIN IMMEDIATE")
                try:
                    db.execute("INSERT OR IGNORE INTO memory_store_meta(key,value) VALUES(?,?)",
                               (STAMP_KEY, json.dumps({"v": STAMP_VERSION, "at": iso}, separators=(",", ":"))))
                    if kind == "root":   # the one number old engines look at: raised once, in the same transaction as the stamp
                        db.execute("UPDATE memory_store_meta SET value=? WHERE key='schema_version' AND value='1'", (CONVERTED_SCHEMA_VERSION,))
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
                stamped += 1
        except sqlite3.Error as error:
            reason = _locked_or_full(error)
            if reason is None:
                raise
            blocked[reason] += 1
            finished_all = False
    return _answer("fill", "done" if finished_all else "remaining", filled=filled, stamped=stamped, **({"blocked": dict(blocked)} if blocked else {}))


# --- what is left (reads only) ------------------------------------------------------------------------------------------

def left_over(db: sqlite3.Connection) -> dict[str, Any]:
    """What this step would still do on the root, and what it leaves on purpose. One ``EXISTS`` per unit that is cheap; counts only where a count is the answer.
    A read-only connection is enough. Sub-stores are not opened here (their work shows when the step runs)."""
    tables = _tables(db)
    pending: dict[str, Any] = {}
    pending["translation_queue"] = "memory_translation_jobs" in tables and bool(db.execute("SELECT EXISTS(SELECT 1 FROM memory_translation_jobs WHERE state='pending')").fetchone()[0])
    pending["receipts"] = "memory_source_mappings" in tables and bool(db.execute("SELECT EXISTS(SELECT 1 FROM memory_source_mappings)").fetchone()[0])
    pending["embeddings"] = _meta(db, STAMP_KEY) is None and any(
        table in tables and bool(db.execute(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE embedding_json LIKE '[%')").fetchone()[0]) for table in ("memory_entries", "memory_episodes"))
    have = {r[1] for r in db.execute("PRAGMA table_info(memory_entries)")} if "memory_entries" in tables else set()
    pending["fill"] = {"origin_class", "certainty"} <= have and bool(db.execute(f"SELECT EXISTS(SELECT 1 FROM memory_entries WHERE {_FILL_WHERE})", _OWNER_MARKS).fetchone()[0])
    pending["stamp"] = _meta(db, STAMP_KEY) is None
    left: dict[str, Any] = {}
    if "memory_relation_edges" in tables:
        left["similarEdges"] = db.execute("SELECT COUNT(*) FROM memory_relation_edges WHERE relation_type='similar_to'").fetchone()[0]
    return {"pending": pending, "left": left}


# --- the step ----------------------------------------------------------------------------------------------------------

def tidy(owner: str, *, removed_agents: Iterable[str] = (), budget_seconds: float | None = None, now: float | None = None) -> dict[str, Any]:
    """The units in order, under the one mover lock of the root. ``busy`` when another mover holds it. Never raises for "not now" (a locked file, a full disk):
    the unit answers ``remaining`` with the code. The order puts the queue first (it is what keeps lines from moving) and the stamp last (it says "converted")."""
    from . import memory_split as split
    started = time.monotonic()

    def over() -> bool:
        return budget_seconds is not None and time.monotonic() - started >= budget_seconds

    rt = split.open_root(owner)
    if rt is None:
        return {"state": "no_store", "units": []}
    try:
        with split.SplitLock(rt.path.parent) as free:
            if not free:
                return {"state": "busy", "units": []}
            units: list[dict[str, Any]] = []
            unfinished: set[str] = set()
            for name in UNITS:
                if name == "stamp":
                    continue   # written by the fill unit, store by store, once each store's columns are filled
                try:
                    if name == "translation_queue":
                        units.append(unit_translation_queue(rt.db, over))
                    elif name == "receipts":
                        units.append(unit_receipts(rt.db, over))
                    elif name == "hub_drawers":
                        units.append(unit_hub_drawers(rt, over, now=now))
                    elif name == "removed_agents":
                        units.append(unit_removed_agents(owner, removed_agents, over, rt))
                    elif name == "turn_folders":
                        units.append(unit_turn_folders(rt.db, over))
                    elif name == "embeddings":
                        units.append(unit_embeddings(owner, rt, over, unfinished))
                    elif name == "fill":
                        units.append(unit_fill_and_stamp(owner, rt, over, now=now, unfinished=unfinished))
                except (sqlite3.Error, OSError) as error:
                    reason = _locked_or_full(error) or _code(error)
                    units.append(_answer(name, "remaining" if reason in ("locked", "disk_full") else "failed", reason=reason))
            state = "failed" if any(u["state"] == "failed" for u in units) else "remaining" if any(u["state"] == "remaining" for u in units) else "done"
            return {"state": state, "units": units, "elapsedMs": int((time.monotonic() - started) * 1000)}
    finally:
        rt.close()
