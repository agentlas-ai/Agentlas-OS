"""Reclassifying the memory that piled up before the four-memory structure (engine part; section 12-7, section 11.4).

Step 5 of the 2.0 first-run migration. Two parts, both of which only ever change where a live line belongs; **no line is deleted,
retired or rewritten**, and every change can be undone one line at a time:

* **5a ``reclassify``** (code only, no model): a resident actor's ``agent_repo`` line that was learned in exactly one project folder
  that exists now becomes that project's line. The decision is ``first_run.EntryScan``'s, the one the preview counts with, so what
  ``plan`` reported is what this does. Lines about a person, preferences, and every line whose project is not settled stay where they are.
* **5b ``label_candidates`` / ``apply_labels``** (the model is the desktop's): the lines that are about the owner as a person are
  offered, as numbered text, to a model the desktop calls; its answer comes back as ``{"i", "s"}`` and the engine re-checks every
  condition itself before it moves a line to the owner's Personal memory. The model never sees a project, a secret, a path or a kind
  to choose: the kind comes from the ruleset's own correction table.

A change leaves one origin link on the line (``source_kind='reclassified'``, ``source_id='agent_repo:<the actor>'``,
``relation='from'``) whose ``source_revision`` holds the values that were replaced, so ``undo`` puts them back (the link stays, as
``relation='undone'``, so a line the owner took back is not moved again). A line with such a link is never looked at again.

No new table, column, scope or kind. Meta keys: ``first_run_classified`` (5a is finished) and ``first_run_llm`` (5b's progress:
``{"v": ruleset version, "last": last line id handled, "tries": model attempts, "b": planned batches, "state": running | waiting_model |
done | capped}``). Every write is a transaction of its own batch and re-reads what it changes under the write lock, so a ``kill -9``
leaves a whole batch or none. The engine never calls these by itself: only the desktop does (it holds the project table).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from typing import Any, Callable, Iterable, NamedTuple

from . import memory_classify
from . import memory_split as split
from . import memory_stores as ms
from .first_run import (LABEL_KINDS, LABEL_TEXT_CHARS, META_CLASSIFIED, META_LLM, META_ONE_IMPORT_RETIRED, PERSON, RESIDENT, EntryScan, ProjectFolders,
                        actor_family, label_text_ok, narrow_person, prime_folders, read_drawer, _code, _h8, _json, _meta, _tables)
from .memory_actor_family import ONE_MEMORY_ACTOR_IDS
from .memory_runtime import content_hash

CLASSIFY_SCHEMA = "agentlas.first-run-classify.v1"
LABELS_SCHEMA = "agentlas.first-run-labels.v1"
UNDO_SCHEMA = "agentlas.first-run-undo.v1"
MARKER = "reclassified"
MARKER_FROM, MARKER_UNDONE = "from", "undone"
DEFAULT_LABEL_BATCH = 40           # lines per model call (a local model is given 10 by its caller)
MAX_LABEL_BATCH = 100
MAX_TRIES = 400                    # a ceiling only: the cap is 2 x batches + 4 (defect 5; it was batches + 4, at most 24)
EXTRA_TRIES = 4
MAX_ANSWER_ROWS = 200
MAX_ANSWER_BYTES = 1 << 20
DENIED_HOME_STATES = ("away", "sealed")
_STORE_PROBLEMS = ("store_locked", "store_unwritable", "conflict", "agent_home_removed", "forget_catchup_withheld", "store_schema_newer", "store_absent")
LLM_STATES = ("running", "waiting_model", "done", "capped")
_PATH_TOKEN = re.compile(r"(?:(?<=^)|(?<=[\s`\"'(\[=:,]))(?:/(?:Users|home|var|opt|private|tmp|Volumes|mnt|srv|media|root)/|~/|[A-Za-z]:[\\/]|file://)[^\s`\"')\]]*")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _mask_paths(text: str) -> str:
    return _PATH_TOKEN.sub("<path>", text)


def _meta_set(db: sqlite3.Connection, key: str, value: str) -> None:
    split._meta_set(db, key, value)


# --- the marker --------------------------------------------------------------------------------------------------------

def marker_revision(*, kind: str, project_id: str | None, project_path: str | None, binding: str | None, by: str, scope: str = "agent_repo") -> str:
    """What the line was before (the ``source_revision`` of its marker): enough for ``undo`` to put every changed column back."""
    return _json({"v": 1, "by": by, "os": scope, "k": kind, "pid": project_id, "pp": project_path, "ba": binding})


def _binding_json(db: sqlite3.Connection, memory_id: str) -> str | None:
    row = db.execute("SELECT applicability_json FROM memory_identity_bindings WHERE memory_id=?", (memory_id,)).fetchone()
    return None if row is None else (row[0] if isinstance(row[0], str) else "{}")


def _aligned_binding(raw: Any, scope: str, project_id: str | None, project_path: str | None) -> str | None:
    """The binding's applicability JSON as it must read for a line that now sits at (``scope``, ``project_id``, ``project_path``), or ``None`` when it
    already does. The binding holds a second record of the line's place (``projectIds``, ``projectPathHash``; the desktop writes both for an agent line)
    and both readers (the desktop's ``recall-policy.ts`` and the engine's ``_default_applicability_matches``) refuse a line whose two records differ,
    so a change of place changes them with it. Only the keys that are there are touched (an engine line holds the scope alone); every other key and
    byte stays. The place the line came from is not lost: the marker's ``source_revision`` holds the whole original binding."""
    try:
        policy = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        policy = None
    if not isinstance(policy, dict):
        policy = {}
    want = dict(policy)
    want["scope"] = scope
    if "projectIds" in want:
        want["projectIds"] = [project_id] if project_id else []
    if "projectPathHash" in want:
        if project_path:
            want["projectPathHash"] = hashlib.sha256(project_path.encode("utf-8")).hexdigest()
        else:
            del want["projectPathHash"]
    if want == policy and isinstance(raw, str):
        return None
    return json.dumps(want, ensure_ascii=False, separators=(",", ":"))


def _set_binding_scope(db: sqlite3.Connection, memory_id: str, scope: str, project_id: str | None = None, project_path: str | None = None) -> None:
    """The line's binding follows the line to its new place (scope and the two place records; see ``_aligned_binding``)."""
    row = db.execute("SELECT applicability_json FROM memory_identity_bindings WHERE memory_id=?", (memory_id,)).fetchone()
    if row is None:
        return
    aligned = _aligned_binding(row[0], scope, project_id, project_path)
    if aligned is not None:
        db.execute("UPDATE memory_identity_bindings SET applicability_json=? WHERE memory_id=?", (aligned, memory_id))


def _has_marker(db: sqlite3.Connection, memory_id: str) -> bool:
    return db.execute("SELECT 1 FROM memory_origin_links WHERE memory_id=? AND source_kind=?", (memory_id, MARKER)).fetchone() is not None


# --- forgotten words ---------------------------------------------------------------------------------------------------

class ForgetGate:
    """Whether a text was forgotten for a place a line is about to move to, the way the writer decides it (``canonical_writer``): the stamp holds
    whatever kind it was made with and with one trailing character more or less; under the central layout only for the same owner key, under
    the split layout for the whole account after the switch, and for the whole account when the switch's forget number is unknown.
    Loaded once per batch under the write lock (the table holds one row per forgotten text, a handful)."""

    def __init__(self, db: sqlite3.Connection, rs: dict[str, Any] | None):
        self.rs = rs
        self.central = ms.layout_of(db) == ms.CENTRAL
        self.switched = ms.layout_switch_epoch(db)
        self.stamps: dict[str, list[tuple[str, int, bool]]] = {}
        try:
            for key, digest, epoch, source in db.execute("SELECT owner_key,content_hash,revoked_epoch,source_memory_id FROM memory_revocations"):
                self.stamps.setdefault(digest, []).append((key, int(epoch), ms.stamp_is_personal_only(source)))
        except sqlite3.Error:
            self.stamps = {}

    def forgotten(self, target: dict[str, Any], text: str) -> bool:
        """``target`` is the line as it will be stored (``scope``, ``project_path``, ``project_id``, ``agent_id``)."""
        if not self.stamps:
            return False
        keys = set(ms.row_owner_keys(target))
        forms = memory_classify.forget_forms(text, self.rs) if self.rs is not None else [text]
        for form in forms:
            for key, epoch, personal_only in self.stamps.get(content_hash(form), ()):
                # a move-bundle stamp (memory_stores.ONE_PACK_STAMP_SOURCE) holds for its own owner key only, whatever the number
                if key in keys or (not personal_only and not self.central and (self.switched <= 0 or epoch > self.switched)):
                    return True
        return False


# --- 5a: lines learned in exactly one project ---------------------------------------------------------------------------

class Decision(NamedTuple):
    id: str
    root: str
    origin: str
    agent: str | None
    via: str | None


def _ticket_project_id(db: sqlite3.Connection, memory_id: str) -> str | None:
    """The project id the engine's turns of this line carried: one value, else none (a hook turn has none)."""
    values = {row[0] for row in db.execute(
        "SELECT t.project_id FROM memory_origin_links l JOIN memory_tickets t ON t.ticket_id=l.source_id "
        "WHERE l.memory_id=? AND l.source_kind='memory-ticket' AND t.project_id IS NOT NULL", (memory_id,))}
    return next(iter(values)) if len(values) == 1 else None


def _goes_to_project(entry: Any) -> bool:
    """The preview's own condition for ``toProject`` (first_run.plan): live, a resident actor's ``agent_repo`` line, not a preference, not about a person,
    learned in exactly one project folder that exists now."""
    return (entry.live and entry.scope == "agent_repo" and entry.origin is not None and entry.kind != "preference" and not entry.person
            and entry.signal == "ok" and bool(entry.root))


def _project_values(db: sqlite3.Connection, decision: Decision, ids_by_folder: dict[str, list[str]]) -> dict[str, Any]:
    """The columns of the line as the side that wrote it would have written a project line: an engine line has no actor and the project id
    of its turn's ticket; a desktop line (a drawer block, a turn, a consolidation) keeps its actor and takes the id the caller named for the folder."""
    if decision.origin == "engine":
        return {"agent_id": None, "project_id": _ticket_project_id(db, decision.id), "project_path": decision.root}
    ids = ids_by_folder.get(decision.root)
    return {"agent_id": decision.agent, "project_id": ids[0] if ids else None, "project_path": decision.root}


class _Batch(NamedTuple):
    moved: int
    skipped: dict[str, int]
    failed: bool
    held: float
    blocked: str | None
    by_origin: dict[str, int]
    via: dict[str, int]
    in_place: int = 0   # of ``moved``: the lines that changed their kind or scope where they sit in the root (the move of step 6 carries them to their store, where they are counted again)


def _checked_row(db: sqlite3.Connection, decision: Decision) -> tuple[Any, str | None]:
    """The line as it is now, or the reason it is no longer a candidate. Run under the write lock."""
    row = db.execute("SELECT id,scope,kind,content,project_id,project_path,agent_id,chat_id,superseded_at FROM memory_entries WHERE id=?", (decision.id,)).fetchone()
    if row is None:
        return None, "changed"
    if row[1] != "agent_repo" or row[8] is not None or not row[3] or row[2] == "preference" or row[6] != decision.agent:
        return None, "changed"
    if _has_marker(db, decision.id):
        return None, "marked"
    if PERSON.search(row[3]):
        return None, "person"
    if not os.path.isdir(decision.root):
        return None, "folder_gone"
    return row, None


def _gather(root: sqlite3.Connection, owner: str, batch: list[Decision], ids_by_folder: dict[str, list[str]], rs: dict[str, Any] | None,
            skipped: dict[str, int]) -> tuple[Any, list[tuple[ms.StoreRef | None, list[tuple[Decision, Any, dict[str, Any]]]]]]:
    """Under the root's write lock: the lines of the batch that are still candidates, grouped by the store they go to (``None`` = they change where they are:
    the central layout, or a line whose translation is still to do, which the translator reads in the root only). Returns ``(layout, groups)``."""
    gate = ForgetGate(root, rs)
    layout = ms.layout_of(root)
    ready: list[tuple[Decision, Any, dict[str, Any]]] = []
    for decision in batch:
        row, why = _checked_row(root, decision)
        if row is None:
            skipped[why or "changed"] = skipped.get(why or "changed", 0) + 1
            continue
        values = _project_values(root, decision, ids_by_folder)
        target = {"scope": "project", **values, "chat_id": row[7]}
        if gate.forgotten(target, row[3]):
            skipped["forgotten"] = skipped.get("forgotten", 0) + 1
            continue
        ready.append((decision, row, values))
    groups: dict[Any, tuple[ms.StoreRef | None, list[tuple[Decision, Any, dict[str, Any]]]]] = {}
    translating: set[str] = set()   #': nothing is held for a translation any more (the queue and its worker are gone)
    for item in ready:
        ref = (ms.store_for({"scope": "project", **item[2], "chat_id": item[1][7]}, owner, layout=ms.SPLIT_LAYOUT)
               if layout == ms.SPLIT and item[0].id not in translating else None)
        place = ref if ref is not None and ref.kind == ms.PROJECT else None
        groups.setdefault(place.path if place else None, (place, []))[1].append(item)
    return layout, list(groups.values())


def _apply_projects(rt: Any, owner: str, batch: list[Decision], ids_by_folder: dict[str, list[str]], rs: dict[str, Any] | None) -> _Batch:
    """One batch of 5a. The root's write lock is taken for one project store at a time (and once, first, for the lines that change where they are):
    in each transaction the lines are read, checked, copied, removed and committed together, so no writer changes a line between being checked and being
    changed and no forget slips in between. The lock is never held while a store is waited for beyond that store's own short busy time, and a store
    that is locked is skipped at once (its lines stay in the root; the others go on).

    Everything in a transaction is read through ``root`` itself. A second connection of this process on the root cannot read once ``root``'s transaction
    has made changes (the root is a rollback-journal file: after enough changes the writer takes the exclusive lock and a reader of the same file is turned
    away for its whole busy time, 5 s, then ``database is locked``): that was the 48-second stall (defect 1)."""
    root = rt.db
    skipped: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    via: dict[str, int] = {}
    failed, blocked = False, None
    moved = 0
    in_place = 0
    held = 0.0
    locked_total = 0.0     # how long the root's lock was held since the last gap

    def count(items: list[tuple[Decision, Any, dict[str, Any]]], landed_ids: set[str]) -> None:
        for decision, _row, _values in items:
            if decision.id in landed_ids:
                by_origin[decision.origin] = by_origin.get(decision.origin, 0) + 1
                if decision.via in ("tie1", "tie2"):
                    via[decision.via] = via.get(decision.via, 0) + 1

    try:
        # Lines that change where they are (and the grouping, read under the lock).
        root.execute("BEGIN IMMEDIATE")
        locked_at = time.monotonic()
        try:
            _layout, groups = _gather(root, owner, batch, ids_by_folder, rs, skipped)
            for place, items in groups:
                if place is None:
                    for decision, row, values in items:
                        _change_in_place(root, decision, row, values)
                    count(items, {item[0].id for item in items})
                    moved += len(items)
                    in_place += len(items)
            root.commit()
            held = max(held, time.monotonic() - locked_at)
            locked_total = time.monotonic() - locked_at
        except BaseException:
            root.rollback()
            raise
        for place, items in groups:
            if place is None:
                continue
            # A store that is not there or cannot be written is found out before the root is locked for it.
            sdb, code = ms.open_store_for_write(place, owner, root)
            if sdb is None:
                skipped[code or "store_unwritable"] = skipped.get(code or "store_unwritable", 0) + len(items)
                failed = True
                continue
            sdb.execute("PRAGMA busy_timeout=0")   # the root's lock is held while this store is written: a locked store is skipped at once, not waited for
            try:
                root.execute("BEGIN IMMEDIATE")
                locked_at = time.monotonic()
                # The lines are checked again under this lock (they may have changed, or been forgotten, since the first one).
                again: list[tuple[Decision, Any, dict[str, Any]]] = []
                gate = ForgetGate(root, rs)
                for decision, _row, _values in items:
                    row, why = _checked_row(root, decision)
                    if row is None:
                        skipped[why or "changed"] = skipped.get(why or "changed", 0) + 1
                        continue
                    values = _project_values(root, decision, ids_by_folder)
                    if gate.forgotten({"scope": "project", **values, "chat_id": row[7]}, row[3]):
                        skipped["forgotten"] = skipped.get("forgotten", 0) + 1
                        continue
                    again.append((decision, row, values))
                landed = _move_to_store(root, sdb, again, skipped) if again else []
                if landed == "disk_full":
                    root.rollback()
                    return _Batch(moved, skipped, True, held, "disk_full", by_origin, via, in_place)
                if landed is None:
                    root.rollback()
                    failed = True
                    continue
                root.commit()
                held = max(held, time.monotonic() - locked_at)
                count(again, set(landed))
                moved += len(landed)
                locked_total += time.monotonic() - locked_at
                if locked_total >= split.PAUSE_SECONDS:   # a gap in the root's lock for a waiting writer once the stores have held it that long since the last gap (defect 9)
                    time.sleep(split.PAUSE_SECONDS)
                    locked_total = 0.0
            except BaseException:
                root.rollback()
                raise
            finally:
                sdb.close()
    except sqlite3.OperationalError as error:
        if split._is_disk_full(error):
            return _Batch(moved, skipped, True, held, "disk_full", by_origin, via, in_place)
        raise
    return _Batch(moved, skipped, failed, held, blocked, by_origin, via, in_place)


def _change_in_place(db: sqlite3.Connection, decision: Decision, row: Any, values: dict[str, Any]) -> None:
    """The line becomes a project line where it is (the central layout, or no project store to go to): the columns, the binding's scope, the marker."""
    revision = marker_revision(kind=row[2], project_id=row[4], project_path=row[5], binding=_binding_json(db, decision.id), by="project")
    db.execute("UPDATE memory_entries SET scope='project',project_id=?,project_path=?,agent_id=? WHERE id=? AND scope='agent_repo'",
               (values["project_id"], values["project_path"], values["agent_id"], decision.id))
    _set_binding_scope(db, decision.id, "project", values["project_id"], values["project_path"])
    db.execute("INSERT OR IGNORE INTO memory_origin_links(memory_id,source_kind,source_id,source_revision,relation) VALUES(?,?,?,?,?)",
               (decision.id, MARKER, "agent_repo:" + (row[6] or ""), revision, MARKER_FROM))


def _move_to_store(root: sqlite3.Connection, sdb: sqlite3.Connection, items: list[tuple[Decision, Any, dict[str, Any]]],
                   skipped: dict[str, int]) -> list[str] | str | None:
    """Under the split layout, inside the root's open transaction: the lines are copied from the root (the same connection, so its own uncommitted state is
    what is read) into the project store ``sdb`` as the project lines they become (the copy, the new columns, the binding's scope and the marker are one
    transaction there), then removed from the root. Until the root's commit the line is still the old one in the root, so a crash leaves it in the root and
    the next call does the same copy again. Returns the ids that landed, ``"disk_full"``, or ``None`` when the store could not be written (locked)."""
    ids = [item[0].id for item in items]
    try:
        sdb.execute("BEGIN IMMEDIATE")
        split.copy_rows(root, sdb, ids)
        for decision, row, values in items:
            revision = marker_revision(kind=row[2], project_id=row[4], project_path=row[5], binding=_binding_json(root, decision.id), by="project")
            sdb.execute("UPDATE memory_entries SET scope='project',project_id=?,project_path=?,agent_id=? WHERE id=?",
                        (values["project_id"], values["project_path"], values["agent_id"], decision.id))
            _set_binding_scope(sdb, decision.id, "project", values["project_id"], values["project_path"])
            sdb.execute("INSERT OR IGNORE INTO memory_origin_links(memory_id,source_kind,source_id,source_revision,relation) VALUES(?,?,?,?,?)",
                        (decision.id, MARKER, "agent_repo:" + (row[6] or ""), revision, MARKER_FROM))
        sdb.commit()
        present = split.landed(root, sdb, ids)
    except sqlite3.OperationalError as error:
        try:
            sdb.rollback()
        except sqlite3.Error:
            pass
        if split._is_disk_full(error):
            return "disk_full"
        skipped["store_locked"] = skipped.get("store_locked", 0) + len(ids)
        return None
    landed = [ident for ident in ids if ident in present]
    if len(landed) != len(ids):
        skipped["conflict"] = skipped.get("conflict", 0) + len(ids) - len(landed)
    if landed:
        split._keep_supersedes(root, landed, set(landed))
        split._delete_rows(root, landed)
    return landed


def reclassify(owner: str, *, projects: Iterable[str] = (), projects_under: Iterable[str] = (), project_names: Iterable[str] = (),
               budget_seconds: float | None = 2.0, batch_rows: int = split.BATCH_ROWS) -> dict[str, Any]:
    """5a on the owner's root store. Safe to call again and again: what is already settled is not a candidate any more, and when nothing is left the
    meta key ``first_run_classified`` is set and every later call answers ``done`` without reading a line.

    ``remaining`` with ``budget`` (the time ran out), ``busy`` (another mover holds the store), ``one_import_not_retired`` (the desktop still imports the
    drawer; that key is its to set), ``disk_full``, ``store_locked`` / ``store_unwritable`` / ``conflict`` (a line could not be moved this time)."""
    started = time.monotonic()
    rt = split.open_root(owner)
    if rt is None:
        return {"schema": CLASSIFY_SCHEMA, "state": "done", "reason": "no_store", "moved": 0}
    try:
        _align(rt, owner)     # a store an earlier build classified is put right once (a best effort; the answer is not part of this report)
        return _reclassify(rt, owner, list(projects), list(projects_under), list(project_names), budget_seconds, batch_rows, started)
    finally:
        rt.close()


def _reclassify(rt: Any, owner: str, projects: list[str], under: list[str], names: list[str], budget: float | None, batch_rows: int, started: float) -> dict[str, Any]:
    db = rt.db
    base = {"schema": CLASSIFY_SCHEMA}
    if _meta(db, META_CLASSIFIED) is not None:
        return {**base, "state": "done", "reason": "already", "moved": 0}
    if _meta(db, META_ONE_IMPORT_RETIRED) is None:
        return {**base, "state": "remaining", "reason": "one_import_not_retired", "moved": 0}
    tables = _tables(db)
    rs = memory_classify.active()
    moved, by_origin, via, skipped = 0, {}, {}, {}
    in_place_total = 0
    holds: list[float] = []
    stop: str | None = None
    with split.SplitLock(rt.path.parent) as free:
        if not free:
            return {**base, "state": "remaining", "reason": "busy", "moved": 0}
        folders = ProjectFolders(projects, under, names)
        ids_by_folder: dict[str, list[str]] = {}
        for ident, real in sorted(folders.by_id.items()):
            ids_by_folder.setdefault(real, []).append(ident)
        reader = sqlite3.connect(str(rt.path), timeout=5.0)
        reader.execute("PRAGMA query_only=ON")
        try:
            prime_folders(reader, tables, folders)
            scan = EntryScan(reader, tables, owner, read_drawer(), folders)
            pacer = split.BatchPacer(max(1, int(batch_rows)))
            pending: list[Decision] = []
            more = False

            def flush() -> bool:
                """Apply the lines gathered so far; False when the run has to stop (a full disk)."""
                nonlocal moved, pending, stop, in_place_total
                if not pending:
                    return True
                chunk, pending = pending, []
                result = _apply_projects(rt, owner, chunk, ids_by_folder, rs)
                moved += result.moved
                in_place_total += result.in_place
                holds.append(result.held)
                for key, count in result.skipped.items():
                    skipped[key] = skipped.get(key, 0) + count
                for key, count in result.by_origin.items():
                    by_origin[key] = by_origin.get(key, 0) + count
                for key, count in result.via.items():
                    via[key] = via.get(key, 0) + count
                if result.blocked:
                    stop = result.blocked
                elif result.failed and stop is None:
                    stop = next((code for code in result.skipped if code in _STORE_PROBLEMS), "store_unwritable")
                pacer.took(result.held, len(chunk))
                time.sleep(split.PAUSE_SECONDS)
                return result.blocked is None

            for entry in scan:
                if not _goes_to_project(entry):
                    continue
                pending.append(Decision(entry.id, entry.root or "", entry.origin or "", entry.agent_id, entry.via))
                if len(pending) >= pacer.size:
                    if not flush():
                        break
                    if budget is not None and budget > 0 and time.monotonic() - started >= budget:
                        more = True
                        break
            else:
                flush()
        finally:
            reader.close()
    held = [value for value in holds if value > 0]
    report = {**base, "moved": moved, "inPlace": in_place_total, "byOrigin": by_origin, "viaTieBreak": via, "skipped": skipped,
              "holdMs": {"batches": len(held), "median": int(sorted(held)[len(held) // 2] * 1000) if held else 0, "max": int(max(held) * 1000) if held else 0},
              "elapsedMs": int((time.monotonic() - started) * 1000)}
    if stop is not None:
        return {**report, "state": "remaining", "reason": stop}
    if more:
        return {**report, "state": "remaining", "reason": "budget", "budget": True}
    # The whole table was read and every candidate that could move has moved. A candidate that was skipped (changed meanwhile, a folder that vanished)
    # is not one any more, or is a verdict the next read gives again: either way this key says "5a has run to its end once".
    with split.SplitLock(rt.path.parent) as free:
        if not free:
            return {**report, "state": "remaining", "reason": "busy"}
        db.execute("BEGIN IMMEDIATE")
        try:
            _meta_set(db, META_CLASSIFIED, _now_iso()[:10])
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return {**report, "state": "done"}


# --- the cure for a store an earlier build already classified ------------------------------------------------------------

META_BINDINGS_ALIGNED = "first_run_bindings_aligned"
ALIGN_SCHEMA = "agentlas.first-run-align.v1"
_ALIGN_SQL = ("SELECT e.id,e.scope,e.project_id,e.project_path,b.applicability_json,l.source_revision FROM memory_origin_links l "
              "JOIN memory_entries e ON e.id=l.memory_id JOIN memory_identity_bindings b ON b.memory_id=e.id "
              "WHERE l.source_kind=? AND l.relation=? AND e.superseded_at IS NULL AND e.scope IN ('user_identity','project')")


def _misaligned(db: sqlite3.Connection) -> list[tuple[str, str]]:
    """``(id, binding)`` of the lines this feature changed (a marker still ``from``) that sit where it put them (Personal after 5b, project after 5a) and whose
    binding does not say so. A line the owner took back (``undone``), moved elsewhere since, or never touched is not looked at: the join starts from the markers
    (one per reclassified line), not from the table."""
    result: list[tuple[str, str]] = []
    for ident, scope, project_id, project_path, binding, revision in db.execute(_ALIGN_SQL, (MARKER, MARKER_FROM)).fetchall():
        try:
            by = json.loads(revision).get("by")
        except (ValueError, TypeError, AttributeError):
            continue
        if (by, scope) not in (("personal", "user_identity"), ("project", "project")):
            continue
        aligned = _aligned_binding(binding, scope, project_id, project_path)
        if aligned is not None:
            result.append((ident, aligned))
    return result


def align_bindings(owner: str) -> dict[str, Any]:
    """Once per store: bring the binding of every line the classification moved in step with where it sits (the defect of the first build left the origin project in
    ``projectIds`` / ``projectPathHash`` of a line that became Personal or went to another project, and both readers then refused it). Cost: one meta read when
    done; the first pass reads the marker rows of the root and of each project store (one read-only open each), and writes only the lines that differ. A store that
    cannot be written this time leaves the key unset, so the next open tries again. Never raises for a store problem."""
    rt = split.open_root(owner)
    if rt is None:
        return {"schema": ALIGN_SCHEMA, "state": "done", "reason": "no_store", "fixed": 0}
    try:
        return _align(rt, owner)
    finally:
        rt.close()


def _align(rt: Any, owner: str) -> dict[str, Any]:
    db = rt.db
    base = {"schema": ALIGN_SCHEMA}
    try:
        if _meta(db, META_BINDINGS_ALIGNED) is not None:
            return {**base, "state": "done", "reason": "already", "fixed": 0}
        with split.SplitLock(rt.path.parent) as free:
            if not free:
                return {**base, "state": "remaining", "reason": "busy", "fixed": 0}
            fixed, pending = 0, False
            db.execute("BEGIN IMMEDIATE")
            try:
                for ident, binding in _misaligned(db):
                    db.execute("UPDATE memory_identity_bindings SET applicability_json=? WHERE memory_id=?", (binding, ident))
                    fixed += 1
                db.commit()
            except BaseException:
                db.rollback()
                raise
            if ms.reads_union(db):
                for ref in ms.recent_stores(owner, [], limit=10 ** 9)[0]:
                    if ref.kind != ms.PROJECT:
                        continue
                    try:
                        found = ms._connect_ro(ref.path)
                        try:
                            todo = _misaligned(found)
                        finally:
                            found.close()
                    except (sqlite3.Error, OSError, ValueError):
                        pending = True
                        continue
                    if not todo:
                        continue
                    sdb, _code = ms.open_store_for_write(ref, owner, db)
                    if sdb is None:
                        pending = True
                        continue
                    try:
                        sdb.execute("PRAGMA busy_timeout=500")
                        sdb.execute("BEGIN IMMEDIATE")
                        for ident, binding in todo:
                            sdb.execute("UPDATE memory_identity_bindings SET applicability_json=? WHERE memory_id=?", (binding, ident))
                        sdb.commit()
                        fixed += len(todo)
                    except sqlite3.Error:
                        try:
                            sdb.rollback()
                        except sqlite3.Error:
                            pass
                        pending = True
                    finally:
                        sdb.close()
            if pending:
                return {**base, "state": "remaining", "reason": "store_unwritable", "fixed": fixed}
            db.execute("BEGIN IMMEDIATE")
            try:
                _meta_set(db, META_BINDINGS_ALIGNED, _now_iso()[:10])
                db.commit()
            except BaseException:
                db.rollback()
                raise
            return {**base, "state": "done", "fixed": fixed}
    except sqlite3.Error:
        return {**base, "state": "remaining", "reason": "store_unwritable", "fixed": 0}


# --- undo ---------------------------------------------------------------------------------------------------------------

def undo(owner: str, memory_id: str) -> dict[str, Any]:
    """Put one line back as it was before 5a or 5b changed it: scope, kind, actor, project id and path, binding. The marker stays as ``undone`` (so the
    line is not moved again). A line the owner forgot (its words are gone) is not brought back, and a line that was never reclassified is not touched.
    Under the split layout the line may sit in a project store: it is copied back into the root in one transaction, then removed from the store."""
    rt = split.open_root(owner)
    if rt is None:
        return {"schema": UNDO_SCHEMA, "state": "no_store"}
    try:
        with split.SplitLock(rt.path.parent) as free:
            if not free:
                return {"schema": UNDO_SCHEMA, "state": "busy"}
            return _undo(rt, owner, memory_id)
    finally:
        rt.close()


def _find_marker(db: sqlite3.Connection, memory_id: str) -> tuple[Any, tuple[str, str, str] | None]:
    row = db.execute("SELECT id,scope,kind,content,superseded_at FROM memory_entries WHERE id=?", (memory_id,)).fetchone()
    if row is None:
        return None, None
    link = db.execute("SELECT source_id,source_revision,relation FROM memory_origin_links WHERE memory_id=? AND source_kind=?", (memory_id, MARKER)).fetchone()
    return row, (tuple(link) if link else None)  # type: ignore[return-value]


def _restore(db: sqlite3.Connection, memory_id: str, original: dict[str, Any], agent: str | None) -> None:
    db.execute("UPDATE memory_entries SET scope=?,kind=?,project_id=?,project_path=?,agent_id=? WHERE id=?",
               (original.get("os") or "agent_repo", original["k"], original.get("pid"), original.get("pp"), agent, memory_id))
    binding = original.get("ba")
    if isinstance(binding, str):
        db.execute("UPDATE memory_identity_bindings SET applicability_json=? WHERE memory_id=?", (binding, memory_id))
    db.execute("UPDATE memory_origin_links SET relation=? WHERE memory_id=? AND source_kind=?", (MARKER_UNDONE, memory_id, MARKER))


def _undo(rt: Any, owner: str, memory_id: str) -> dict[str, Any]:
    root = rt.db
    row, link = _find_marker(root, memory_id)
    place = None
    if row is None and ms.reads_union(root):
        for ref in ms.recent_stores(owner, [], limit=10 ** 9)[0]:
            if ref.kind != ms.PROJECT:
                continue
            try:
                found = ms._connect_ro(ref.path)
            except (sqlite3.Error, OSError, ValueError):
                continue
            try:
                row, link = _find_marker(found, memory_id)
            finally:
                found.close()
            if row is not None:
                place = ref
                break
    if row is None:
        return {"schema": UNDO_SCHEMA, "state": "not_found"}
    if link is None or link[2] != MARKER_FROM:
        return {"schema": UNDO_SCHEMA, "state": "not_reclassified"}
    if not row[3]:
        return {"schema": UNDO_SCHEMA, "state": "forgotten"}   # the words are gone; nothing is brought back
    try:
        original = json.loads(link[1])
        agent = link[0].split(":", 1)[1] or None
        if not isinstance(original, dict) or not isinstance(original.get("k"), str):
            raise ValueError("marker")
    except (ValueError, IndexError, TypeError):
        return {"schema": UNDO_SCHEMA, "state": "failed", "reason": "marker_unreadable"}
    if place is None:
        root.execute("BEGIN IMMEDIATE")
        try:
            _row, again = _find_marker(root, memory_id)
            if again is None or again[2] != MARKER_FROM or not _row[3]:
                root.rollback()
                return {"schema": UNDO_SCHEMA, "state": "not_reclassified"}
            _restore(root, memory_id, original, agent)
            root.commit()
        except BaseException:
            root.rollback()
            raise
        return {"schema": UNDO_SCHEMA, "state": "done", "restored": True, "scope": original.get("os") or "agent_repo"}
    # In a project store: the line goes back to the root (a resident actor's agent_repo line has no other place under any layout).
    source = sqlite3.connect(str(place.path), timeout=5.0)
    source.row_factory = sqlite3.Row
    try:
        root.execute("BEGIN IMMEDIATE")
        try:
            split.copy_rows(source, root, [memory_id])
            _restore(root, memory_id, original, agent)
            root.commit()
        except BaseException:
            root.rollback()
            raise
        opened, _code_ = ms.open_store_for_write(place, owner, root)
        if opened is not None:
            try:
                opened.execute("BEGIN IMMEDIATE")
                split._delete_rows(opened, [memory_id])
                opened.commit()
            finally:
                opened.close()
    finally:
        source.close()
    return {"schema": UNDO_SCHEMA, "state": "done", "restored": True, "scope": original.get("os") or "agent_repo"}


# --- 5b: the lines about a person ----------------------------------------------------------------------------------------

_LIKE = ("%user%", "%owner%", "%사용자%", "%오너%")
_RESIDENT_SQL = "(m.agent_id IN (%s) OR lower(m.agent_id) LIKE 'host:%%' OR lower(m.agent_id) LIKE 'builtin-agentlas-%%')" % ",".join("'" + i + "'" for i in ONE_MEMORY_ACTOR_IDS)
_PAGE = 300


class Candidate(NamedTuple):
    id: str
    kind: str
    text: str
    agent: str | None


def label_eligible(kind: str, agent: str | None, text: str) -> bool:
    """The one definition of a line the person labelling offers and, again, may change: a resident actor's (never a special agent's) line of a kind
    that is not already Personal's, whose text is about a person as a subject (``narrow_person``) and holds no secret shape and no host path."""
    return (actor_family(agent) in RESIDENT and kind in LABEL_KINDS and PERSON.search(text) is not None and narrow_person(text) and label_text_ok(text))


def _candidate_rows(db: sqlite3.Connection, after: str | None, limit: int | None = None) -> Iterable[Candidate]:
    """The live resident ``agent_repo`` lines of the labelling's kinds after ``after`` (by id) that pass ``label_eligible``, oldest id first. The SQL only
    narrows by the person words; the Python check is the definition."""
    like = " OR ".join("m.content LIKE ?" for _ in _LIKE)
    kinds = ",".join("?" * len(LABEL_KINDS))
    sql = (f"SELECT m.id,m.kind,m.content,m.agent_id FROM memory_entries m WHERE m.id>? AND m.scope='agent_repo' AND m.superseded_at IS NULL AND m.content<>'' "
           f"AND m.sensitivity<>'secret' AND m.kind IN ({kinds}) AND ({like}) AND {_RESIDENT_SQL} "
           f"AND NOT EXISTS (SELECT 1 FROM memory_origin_links l WHERE l.memory_id=m.id AND l.source_kind=?) ORDER BY m.id LIMIT {_PAGE}")
    cursor, found = after or "", 0
    while True:
        rows = db.execute(sql, (cursor, *LABEL_KINDS, *_LIKE, MARKER)).fetchall()
        if not rows:
            return
        for ident, kind, text, agent in rows:
            cursor = ident
            if label_eligible(kind, agent, text):
                found += 1
                yield Candidate(ident, kind, text, agent)
                if limit is not None and found >= limit:
                    return


def _personal_gate(db: sqlite3.Connection, rs: dict[str, Any] | None) -> ForgetGate:
    return ForgetGate(db, rs)


def _offerable(db: sqlite3.Connection, rs: dict[str, Any] | None, after: str | None, limit: int | None) -> list[Candidate]:
    """``_candidate_rows`` without the lines whose words the owner forgot for Personal memory."""
    gate = _personal_gate(db, rs)
    out: list[Candidate] = []
    for candidate in _candidate_rows(db, after):
        if gate.forgotten({"scope": "user_identity"}, candidate.text):
            continue
        out.append(candidate)
        if limit is not None and len(out) >= limit:
            break
    return out


def personal_kind(rs: dict[str, Any] | None, kind: str) -> str | None:
    """The kind a line gets when the migration lifts it into Personal memory: a preference stays a preference; every other kind Personal accepts (by the
    ruleset's own correction table: a fact, decision, procedure or risk) becomes a **fact**, which only the personal agent reads (defect 2: a
    ``preference`` is read by every agent, so a decision or a risk about the owner must not become one). A kind Personal does not accept is ``None``
    (the line stays where it is). Never the model's choice."""
    table = memory_classify.remap_table(rs, "user_identity") if rs is not None else {"decision": "preference", "procedure": "preference", "risk": "preference"}
    corrected = table.get(kind, kind)
    if corrected not in ("preference", "fact"):
        return None
    return "preference" if kind == "preference" else "fact"


def _labels_layout_ready(db: sqlite3.Connection) -> bool:
    """5b changes nothing before the split layout is on (defect 3): until then a copy of the engine that reads no range filter may still be in use
    by an open Claude Code or Codex window, and it would show a Personal line to every agent."""
    return ms.layout_of(db) == ms.SPLIT


def read_llm(db: sqlite3.Connection) -> dict[str, Any] | None:
    raw = _meta(db, META_LLM)
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("state") not in LLM_STATES:
        return None
    return value


def _ruleset_version(rs: dict[str, Any] | None) -> str:
    try:
        from .one_workspace import load_ruleset
        return str((rs or load_ruleset()[0]).get("rulesetVersion") or "")
    except Exception:  # noqa: BLE001
        return ""


def _home(db: sqlite3.Connection, rs: dict[str, Any] | None) -> str:
    return memory_classify.home_state(db, rs)


def _try_cap(state: dict[str, Any]) -> int:
    """Model attempts allowed in all. An attempt is counted when its batch is applied (``apply_labels`` ``spent``), never when it is offered: an offer the desktop
    never finished (a quit, a kill, an engine failure, no model reached) costs nothing."""
    return min(MAX_TRIES, 2 * int(state.get("b") or 0) + EXTRA_TRIES)


def _write_llm(db: sqlite3.Connection, state: dict[str, Any]) -> None:
    _meta_set(db, META_LLM, _json(state))


def llm_state(owner: str) -> dict[str, Any]:
    """Read-only: 5a's flag, the 5b progress key, whether this computer is the personal agent's home. No scan; the answer is three meta reads."""
    from .first_run import open_readonly, Unreadable
    from .memory_runtime import memory_path
    path = memory_path(owner)
    if path.is_symlink() or not path.is_file():
        return {"schema": LABELS_SCHEMA, "state": "done", "reason": "no_store"}
    try:
        db, _mode = open_readonly(path)
    except Unreadable as error:
        return {"schema": LABELS_SCHEMA, "state": "remaining" if error.code == "locked" else "failed", "reason": error.code}
    try:
        rs = memory_classify.active()
        llm = read_llm(db)
        classified = _meta(db, META_CLASSIFIED) is not None
        home = _home(db, rs)
    finally:
        db.close()
    state = llm["state"] if llm else None
    return {"schema": LABELS_SCHEMA, "state": "done" if state in ("done", "capped") else "remaining", "llm": llm, "classified": classified, "home": home,
            **({"reason": "capped"} if state == "capped" else {})}


def label_candidates(owner: str, *, limit: int = DEFAULT_LABEL_BATCH) -> dict[str, Any]:
    """The next batch of lines for the model (state ``running``; the attempt is counted when ``apply_labels`` is told what was spent, not here).

    Rows: ``i`` (1..n, what the model answers by), ``id`` (the caller keeps it, the model is not told), ``kind``, ``scope`` (``agent_repo``), ``text`` (the
    first 400 characters, any path token masked), ``fp`` (a fingerprint of the whole text, handed back to ``apply_labels``). ``through`` is the last id of
    the batch. Nothing is offered before 5a has finished (``reclassify_pending``), and nothing when the key says ``done`` / ``capped``. When the
    computer is not the personal agent's home (``away`` / ``sealed``) or no line is left, the key is set to ``done`` here and no row comes back.
    ``capped`` when the attempts spent have reached the cap (2 x batches planned + 4)."""
    limit = max(1, min(int(limit), MAX_LABEL_BATCH))
    rt = split.open_root(owner)
    if rt is None:
        return {"schema": LABELS_SCHEMA, "state": "done", "reason": "no_store", "rows": []}
    try:
        db = rt.db
        _align(rt, owner)
        rs = memory_classify.active()
        llm = read_llm(db)
        if llm and llm["state"] in ("done", "capped"):
            return {"schema": LABELS_SCHEMA, "state": "done", "llm": llm, "rows": [], **({"reason": "capped"} if llm["state"] == "capped" else {})}
        if _meta(db, META_CLASSIFIED) is None:
            return {"schema": LABELS_SCHEMA, "state": "remaining", "reason": "reclassify_pending", "llm": llm, "rows": []}
        if not _labels_layout_ready(db):
            return {"schema": LABELS_SCHEMA, "state": "remaining", "reason": "layout_not_split", "llm": llm, "rows": []}
        db.execute("BEGIN IMMEDIATE")
        try:
            llm = read_llm(db)  # read again under the lock: another caller may have finished meanwhile
            if llm and llm["state"] in ("done", "capped"):
                db.rollback()
                return {"schema": LABELS_SCHEMA, "state": "done", "llm": llm, "rows": []}
            last = llm.get("last") if llm else None
            if _home(db, rs) in DENIED_HOME_STATES:
                state = {"v": (llm or {}).get("v") or _ruleset_version(rs), "last": last, "tries": int((llm or {}).get("tries") or 0), "b": int((llm or {}).get("b") or 0),
                         "state": "done"}
                _write_llm(db, state)
                db.commit()
                return {"schema": LABELS_SCHEMA, "state": "done", "reason": "home_state", "llm": state, "rows": []}
            rows = _offerable(db, rs, last, limit)
            if not rows:
                state = {"v": (llm or {}).get("v") or _ruleset_version(rs), "last": last, "tries": int((llm or {}).get("tries") or 0), "b": int((llm or {}).get("b") or 0),
                         "state": "done"}
                _write_llm(db, state)
                db.commit()
                return {"schema": LABELS_SCHEMA, "state": "done", "reason": "nothing_left", "llm": state, "rows": []}
            if llm is None or not llm.get("b"):
                total = len(_offerable(db, rs, last, None))   # the plan's batch count is fixed once: the cap does not shrink as lines are taken
                llm = {**(llm or {"v": _ruleset_version(rs), "last": last, "tries": 0}), "b": max(1, -(-total // limit)), "state": "running"}
            if int(llm.get("tries") or 0) >= _try_cap(llm):
                state = {**llm, "state": "capped"}
                _write_llm(db, state)
                db.commit()
                return {"schema": LABELS_SCHEMA, "state": "done", "reason": "capped", "llm": state, "rows": []}
            state = {**llm, "tries": int(llm.get("tries") or 0), "state": "running"}
            _write_llm(db, state)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return {"schema": LABELS_SCHEMA, "state": "remaining", "reason": "batch", "llm": state, "through": rows[-1].id,
                "rows": [{"i": n, "id": item.id, "kind": item.kind, "scope": "agent_repo", "text": _mask_paths(item.text)[:LABEL_TEXT_CHARS], "fp": _fingerprint(item.text)}
                         for n, item in enumerate(rows, start=1)]}
    finally:
        rt.close()


def apply_labels(owner: str, answers: dict[str, Any]) -> dict[str, Any]:
    """Apply one batch of the model's answers in ONE transaction, together with the progress key.

    ``answers``: ``{"rows": [{"i", "id", "fp", "s"}], "through": id, "spent": model attempts spent on this batch (the first ask, re-asks, other runners; 0 when none was made),
    "waiting": true}``. ``waiting`` records that no model is connected (``waiting_model``; nothing else changes). A row changes only when ALL hold,
    checked again here under the write lock: the answer is ``user_identity``; the line still passes ``label_eligible`` (live, still ``agent_repo``, a
    resident actor's, a person as the subject, no secret or path, no marker); its text still has the fingerprint it had when it was offered; the owner did
    not forget those words for Personal memory; the computer is not ``away`` / ``sealed``. Anything else leaves the line exactly as it was. The line's
    columns then become ``scope='user_identity'``, no project id or path, the binding's scope, and the kind by ``personal_kind`` (preference stays, the others become fact)."""
    rows = answers.get("rows") if isinstance(answers.get("rows"), list) else []
    through = answers.get("through") if isinstance(answers.get("through"), str) else None
    extra = answers.get("attempts") if isinstance(answers.get("attempts"), int) and not isinstance(answers.get("attempts"), bool) else 0
    extra = max(0, min(extra, 8))
    # Model attempts spent on this call (0..8): ``spent`` when the caller says so; an older caller (the offer used to count one) sends ``attempts`` = the spare ones.
    given = answers.get("spent")
    spent = max(0, min(given, 8)) if isinstance(given, int) and not isinstance(given, bool) else (1 + extra if through is not None else extra)
    waiting = answers.get("waiting") is True
    if len(rows) > MAX_ANSWER_ROWS:
        return {"schema": LABELS_SCHEMA, "state": "failed", "reason": "bad_arguments"}
    rt = split.open_root(owner)
    if rt is None:
        return {"schema": LABELS_SCHEMA, "state": "done", "reason": "no_store"}
    started = time.monotonic()
    try:
        db = rt.db
        rs = memory_classify.active()
        applied, kept, skipped = 0, 0, {}
        results: list[dict[str, Any]] = []
        db.execute("BEGIN IMMEDIATE")
        try:
            llm = read_llm(db)
            if llm and llm["state"] in ("done", "capped"):
                db.rollback()
                return {"schema": LABELS_SCHEMA, "state": "done", "llm": llm, "applied": 0, "kept": 0, "skipped": {}, **({"reason": "capped"} if llm["state"] == "capped" else {})}
            if _meta(db, META_CLASSIFIED) is None:
                db.rollback()
                return {"schema": LABELS_SCHEMA, "state": "remaining", "reason": "reclassify_pending", "llm": llm, "applied": 0, "kept": 0, "skipped": {}}
            if not waiting and not _labels_layout_ready(db):
                db.rollback()
                return {"schema": LABELS_SCHEMA, "state": "remaining", "reason": "layout_not_split", "llm": llm, "applied": 0, "kept": 0, "skipped": {}}
            state = dict(llm) if llm else {"v": _ruleset_version(rs), "last": None, "tries": 0, "b": 0, "state": "running"}
            home = _home(db, rs)
            locked_at = time.monotonic()
            if waiting:
                state["state"] = "waiting_model"
            elif home in DENIED_HOME_STATES:
                state["state"] = "done"
                skipped["home_state"] = len(rows)
                results = [{"i": item.get("i") if isinstance(item, dict) else None, "r": "home_state"} for item in rows]
            else:
                gate = _personal_gate(db, rs)
                for item in rows:
                    outcome = _apply_one(db, rs, gate, item)
                    results.append({"i": item.get("i") if isinstance(item, dict) else None, "r": outcome})
                    if outcome == "applied":
                        applied += 1
                    elif outcome == "kept":
                        kept += 1
                    else:
                        skipped[outcome] = skipped.get(outcome, 0) + 1
                state["tries"] = int(state.get("tries") or 0) + spent
                if through is not None and (state.get("last") is None or through > str(state["last"])):
                    state["last"] = through
                left = len(_offerable(db, rs, state.get("last"), None))
                state["state"] = "done" if left == 0 else "capped" if int(state["tries"]) >= _try_cap(state) else "running"
            _write_llm(db, state)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        held = time.monotonic() - locked_at
        final = state["state"]
        report = {"schema": LABELS_SCHEMA, "state": "done" if final in ("done", "capped") else "remaining", "llm": state, "applied": applied, "kept": kept, "skipped": skipped, "results": results,
                  "holdMs": int(held * 1000), "elapsedMs": int((time.monotonic() - started) * 1000)}
        if final == "waiting_model":
            report["reason"] = "waiting_model"
        elif final == "capped":
            report["reason"] = "capped"
        elif home in DENIED_HOME_STATES and not waiting:
            report["reason"] = "home_state"
        return report
    finally:
        rt.close()


def _apply_one(db: sqlite3.Connection, rs: dict[str, Any] | None, gate: ForgetGate, item: Any) -> str:
    """One answered row. ``applied`` | ``kept`` (the model said the line stays) | a reason code why it was not applied (the line is untouched)."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        return "bad_row"
    if item.get("s") != "user_identity":
        return "kept"
    row = db.execute("SELECT id,scope,kind,content,project_id,project_path,agent_id,superseded_at,sensitivity FROM memory_entries WHERE id=?", (item["id"],)).fetchone()
    if row is None or row[1] != "agent_repo" or row[7] is not None or not row[3] or row[8] == "secret":
        return "changed"
    if _fingerprint(row[3]) != item.get("fp"):
        return "changed"
    if _has_marker(db, row[0]):
        return "marked"
    if not label_eligible(row[2], row[6], row[3]):
        return "not_person"
    kind = personal_kind(rs, row[2])
    if kind is None:
        return "kind_not_accepted"
    if gate.forgotten({"scope": "user_identity"}, row[3]):
        return "forgotten"
    revision = marker_revision(kind=row[2], project_id=row[4], project_path=row[5], binding=_binding_json(db, row[0]), by="personal")
    db.execute("UPDATE memory_entries SET scope='user_identity',kind=?,project_id=NULL,project_path=NULL WHERE id=? AND scope='agent_repo'", (kind, row[0]))
    _set_binding_scope(db, row[0], "user_identity", None, None)
    db.execute("INSERT OR IGNORE INTO memory_origin_links(memory_id,source_kind,source_id,source_revision,relation) VALUES(?,?,?,?,?)",
               (row[0], MARKER, "agent_repo:" + (row[6] or ""), revision, MARKER_FROM))
    return "applied"
