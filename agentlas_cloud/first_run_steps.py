"""The engine's steps of the 2.0 first-run migration: the part of ``first_run`` that writes.

``run_steps`` runs ``engine_copies`` (1), ``empty_turns`` (4) and ``memory_move`` (6) in order. Each is safe to call again and answers
``done`` / ``remaining`` (with a reason code) / ``failed`` in one JSON line (command: ``python3 -m agentlas_cloud.first_run steps``);
``vacuum`` is the separate once-at-exit command. The engine never turns the layout switch on by itself: ``memory_move`` flips it only
when the caller says ``homes_ready`` (the desktop, after it has checked its own conditions). No new table, column or meta key: whether a
step has work left is answered by the data it works on; the keys the other steps own (``one-import:retired``, ``first_run_classified``)
are not read or written here. No model is called.
"""
from __future__ import annotations

import os
import signal
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import json
from collections import Counter

from . import agent_home
from . import memory_stores as ms
from .windows_console import no_console_window
from .first_run import (ORPHAN_SOURCES, ORPHAN_VERSIONS, RECEIPTS, KEEP_EMPTY_TURN_DAYS, STALE_TURN_DAYS, STEP_NAMES, STEPS_SCHEMA, WORK_ROW_GRACE_HOURS, Unreadable, _code, _h8, _iso,
                        _meta, _tables, empty_turn_condition, engines, open_readonly)

_DELETED_NAMES = (("tickets", "tickets"), ("episodes", "episodes"), ("decisions", "decisions"), ("curation_jobs", "curationJobs"), ("translation_jobs", "translationJobs"),
                  ("operations", "operations"), ("sources", "sourceCatalogue"), ("source_versions", "sourceVersions"), ("checkpoints", "checkpoints"))
PRUNE_BATCH = 500                # tickets per transaction of the empty-turn cleanup (§11.3)
UPDATER_TIMEOUT_SECONDS = 120    # one run of the installed engine's own updater (it downloads a release)


def _prune_args(now: float) -> dict[str, str]:
    return {"stale": _iso(now - STALE_TURN_DAYS * 86400), "keep": _iso(now - KEEP_EMPTY_TURN_DAYS * 86400),
            "grace": _iso(now - WORK_ROW_GRACE_HOURS * 3600)}


def _early_join(tables: set[str]) -> str:
    return "JOIN memory_operations o ON o.operation_id=t.ticket_id" if "memory_operations" in tables else ""


_ORPHAN_SOURCES, _ORPHAN_VERSIONS, _RECEIPTS = ORPHAN_SOURCES, ORPHAN_VERSIONS, RECEIPTS


def pending_prune(db: sqlite3.Connection, tables: set[str], now: float, *, orphans: bool = True) -> dict[str, bool]:
    """Which parts of the empty-turn cleanup still have something to remove. One ``EXISTS`` each, no counting, no write.

    ``turns``: a turn record past its 30 days; ``workRows``: an operation row whose turn ended more than a day ago;
    ``orphanSources`` / ``orphanVersions`` / ``receipts``: rows that nothing points at."""
    if "memory_tickets" not in tables:
        return {"turns": False, "workRows": False, "orphanSources": False, "orphanVersions": False, "receipts": False}
    args, cond = _prune_args(now), empty_turn_condition(tables)
    turns = db.execute(f"SELECT EXISTS(SELECT 1 FROM memory_tickets t WHERE {cond} AND t.created_at < :keep)", args).fetchone()[0]
    work = bool(_early_join(tables)) and db.execute(
        f"SELECT EXISTS(SELECT 1 FROM memory_tickets t {_early_join(tables)} WHERE {cond} AND t.created_at >= :keep AND o.updated_at < :grace)", args).fetchone()[0]
    sources = orphans and "memory_source_catalogue" in tables and "memory_operations" in tables and db.execute(
        f"SELECT EXISTS(SELECT 1 FROM memory_source_catalogue WHERE {_ORPHAN_SOURCES})").fetchone()[0]
    versions = orphans and "memory_source_versions" in tables and "memory_source_catalogue" in tables and db.execute(
        f"SELECT EXISTS(SELECT 1 FROM memory_source_versions WHERE {_ORPHAN_VERSIONS})").fetchone()[0]
    receipts = orphans and "memory_source_mappings" in tables and db.execute(f"SELECT EXISTS(SELECT 1 FROM memory_source_mappings WHERE {_RECEIPTS})").fetchone()[0]
    return {"turns": bool(turns), "workRows": bool(work), "orphanSources": bool(sources), "orphanVersions": bool(versions), "receipts": bool(receipts)}


def prune_empty_turns_in(rt: Any, *, now: float | None = None, batch_rows: int = PRUNE_BATCH, budget_seconds: float | None = None) -> dict[str, Any]:
    """Remove turn records that left no memory (``empty_turn_condition``) from the root ``rt`` opened by the caller; returns what went.

    Three kinds of work, each in transactions of at most ``batch_rows`` turns and each choosing its rows again under the write lock
    (``purge_entries(still=...)``), so a hook that writes meanwhile, a second caller or a ``kill -9`` between two batches can leave
    nothing half done: every batch is whole or absent, and the next call goes on from what is left.
      * a turn older than 30 days: ticket, summary, decisions, curation rows, operation row, source registration and its versions;
      * a turn inside its 30 days whose operation row has been idle for a day: only the operation row and its registration (the summary stays);
      * rows that nothing points at: source registrations of operation rows that no longer exist, their orphaned versions,
        and the migration receipts of an older desktop (``memory_source_mappings`` rows that are not entries).
    The order of deletes and the table list belong to ``memory_split.purge_entries``; nothing is copied, no whole-database copy is made.
    ``deleted`` is the sum of the rows each ``DELETE`` really removed (what ``purge_entries`` and the orphan batches counted), not the difference
    between two counts of a table: a turn that arrives while this runs does not change it. Its keys are the tables' names as before
    (``tickets``, ``episodes``, ``decisions``, ``curationJobs``, ``operations``, ``sourceCatalogue``, ``sourceVersions``, ``migrationReceipts``) plus
    ``translationJobs`` and ``checkpoints`` (queued translations of the removed summaries; continuation checkpoints made from the removed turns).
    A turn that is not removed because a context's two newest checkpoints point at it, or whose operation row is stuck ``processing``, stays past
    its 30 days: the 30 days of are "at least", not "exactly".
    ``busy`` when another mover holds ``.split.lock``; ``more`` is True when the budget ended before the work did."""
    from . import memory_split as split
    now = time.time() if now is None else now
    started = time.monotonic()
    with split.SplitLock(rt.path.parent) as free:
        if not free:
            return {"state": "busy"}
        db = rt.db
        tables = _tables(db)
        if "memory_tickets" not in tables:
            return {"state": "done", "reason": "no_table", "deleted": {}}
        args, cond = _prune_args(now), empty_turn_condition(tables)
        deleted: Counter = Counter()
        join = _early_join(tables)

        def over() -> bool:
            return budget_seconds is not None and time.monotonic() - started >= budget_seconds

        pacer = split.BatchPacer(batch_rows)  # ``batch_rows`` is the ceiling; the size follows how long the last transaction held the write lock
        locked_at: list[float] = []

        def recheck(extra: str, source: str) -> Callable[[sqlite3.Connection, list[str]], list[str]]:
            def check(conn: sqlite3.Connection, ids: list[str]) -> list[str]:
                locked_at.append(time.monotonic())  # called once the write lock is held: the hold is measured from here to the commit
                kept: list[str] = []
                for chunk in split._chunks(ids):
                    names = {f"id{n}": value for n, value in enumerate(chunk)}
                    marks = ",".join(":" + name for name in names)
                    kept += [r[0] for r in conn.execute(f"SELECT t.ticket_id FROM {source} WHERE t.ticket_id IN ({marks}) AND {cond} AND {extra}", {**args, **names})]
                return kept
            return check

        def known_sources(ids: list[str]) -> dict[str, str] | None:
            """The source registrations of these turns, found before the write lock is taken (the lookup scans the whole table: no index on the key)."""
            if "memory_source_catalogue" not in tables:
                return None
            found: dict[str, str] = {}
            for chunk in split._chunks(ids):
                found.update({r[0]: r[1] for r in db.execute(f"SELECT source_id,logical_key FROM memory_source_catalogue WHERE logical_key IN ({split._marks(len(chunk))})", chunk)})
            return found

        phases = (("turns", "t.created_at < :keep", "memory_tickets t", False),
                  ("workRows", "t.created_at >= :keep AND o.updated_at < :grace", f"memory_tickets t {join}", True)) if join else (
                  ("turns", "t.created_at < :keep", "memory_tickets t", False),)
        more = False
        for phase, extra, source, keep_tickets in phases:
            check = recheck(extra, source)
            window: list[Any] = []  # chosen (and their registrations looked up) once, outside the lock, then removed in transactions of the pacer's size
            known: dict[str, str] | None = None
            while True:
                if over():
                    more = True
                    break
                if len(window) < pacer.size:  # (re)choose; what is left of the old window is chosen again with the rest
                    window = [r[0] for r in db.execute(f"SELECT t.ticket_id FROM {source} WHERE {cond} AND {extra} ORDER BY t.created_at, t.ticket_id LIMIT :n",
                                                       {**args, "n": batch_rows})]
                    if not window:
                        break
                    known = known_sources(window)
                ids, window = window[:pacer.size], window[pacer.size:]
                chosen = set(ids)
                locked_at.clear()
                removed = split.purge_entries(rt, [], chosen, keep_tickets=keep_tickets, still=check,
                                              known_sources=None if known is None else {sid: key for sid, key in known.items() if key in chosen})
                if locked_at:
                    pacer.took(time.monotonic() - locked_at[0], len(ids))
                time.sleep(split.PAUSE_SECONDS)  # the lock is free between two batches, long enough for a waiting writer to get it
                for key, name in _DELETED_NAMES:
                    deleted[name] += removed.get(key, 0)
                progress = removed.get("operations", 0) if keep_tickets else removed.get("tickets", 0)
                if not progress:
                    break  # every chosen turn changed before the lock was taken; the next call chooses again
        for statement, table, ok in (
                (f"SELECT source_id FROM memory_source_catalogue WHERE {_ORPHAN_SOURCES} LIMIT :n", "memory_source_catalogue", "memory_operations" in tables),
                (f"SELECT rowid FROM memory_source_versions WHERE {_ORPHAN_VERSIONS} LIMIT :n", "memory_source_versions", "memory_source_catalogue" in tables),
                (f"SELECT rowid FROM memory_source_mappings WHERE {_RECEIPTS} LIMIT :n", "memory_source_mappings", True)):
            if table not in tables or not ok:
                continue
            window = []
            while not more:
                if over():
                    more = True
                    break
                if len(window) < pacer.size:  # (re)choose; what is left of the old window is chosen again with the rest
                    window = [r[0] for r in db.execute(statement, {"n": batch_rows})]
                    if not window:
                        break
                ids, window = window[:pacer.size], window[pacer.size:]
                db.execute("PRAGMA secure_delete=ON")
                db.execute("BEGIN IMMEDIATE")
                locked_at_orphans = time.monotonic()
                try:
                    if table == "memory_source_catalogue":  # chosen again under the lock: a registration is orphaned only while no operation row names it
                        ids = [r[0] for r in db.execute(f"SELECT source_id FROM memory_source_catalogue WHERE {_ORPHAN_SOURCES} AND source_id IN "
                                                        f"({','.join('?' * len(ids))})", ids)]
                        versions, catalogue = split.delete_sources(db, ids, tables)
                        deleted["sourceVersions"] += versions
                        deleted["sourceCatalogue"] += catalogue
                    else:
                        gone = db.execute(f"DELETE FROM {table} WHERE rowid IN ({','.join('?' * len(ids))}) AND " + (_ORPHAN_VERSIONS if table == "memory_source_versions" else _RECEIPTS), ids).rowcount
                        deleted["sourceVersions" if table == "memory_source_versions" else "migrationReceipts"] += gone
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
                pacer.took(time.monotonic() - locked_at_orphans, len(ids))
                time.sleep(split.PAUSE_SECONDS)
                if not ids:
                    break
        deleted = {name: count for name, count in deleted.items() if count}
        pending = pending_prune(db, tables, now)
        return {"state": "remaining" if more or any(pending.values()) else "done", "deleted": deleted, "more": more or any(pending.values()),
                "elapsedMs": int((time.monotonic() - started) * 1000)}


def prune_empty_turns(owner: str, *, now: float | None = None, batch_rows: int = PRUNE_BATCH, budget_seconds: float | None = None) -> dict[str, Any]:
    """``prune_empty_turns_in`` on the owner's root store (``no_store`` when there is none)."""
    from . import memory_split as split
    rt = split.open_root(owner)
    if rt is None:
        return {"state": "no_store"}
    try:
        return prune_empty_turns_in(rt, now=now, batch_rows=batch_rows, budget_seconds=budget_seconds)
    finally:
        rt.close()


def housekeep(runtime: Any) -> None:
    """The ongoing form of the cleanup, called once by the curation worker after it has drained its queue (``memory_runtime.run_curation``).

    Only on a root that the 2.0 desktop has already moved to the split layout; a user who never ran the first-run steps is untouched.
    One cheap ``EXISTS`` decides; when there is something, one second of batches, never waiting for a lock. Never raises."""
    try:
        db = runtime.db
        if ms.layout_of(db) != ms.SPLIT:
            return
        tables, now = _tables(db), time.time()
        pending = pending_prune(db, tables, now, orphans=False)
        if pending["turns"] or pending["workRows"]:
            prune_empty_turns_in(runtime, now=now, budget_seconds=1.0)
    except Exception:  # noqa: BLE001 - housekeeping never fails a curation
        pass


_UPDATER_CHILD = r'''
import json, os
if os.name != "nt":
    # The caller put this process in a group of its own so that a timeout can end everything below it. If the caller itself dies first
    # (killed from outside), nobody is left to do that: end the group, the updater's children with it, once the parent is gone.
    import signal, threading, time
    def _watch_parent(parent=os.getppid()):
        while True:
            time.sleep(2)
            if os.getppid() != parent:
                os.killpg(os.getpgrp(), signal.SIGKILL)
    threading.Thread(target=_watch_parent, daemon=True).start()
out = {"retry": None}
try:
    from agentlas_cloud import update as u
    original = getattr(u, "_retry_pending_host_plugins", None)  # an engine older than 1.2.92 has no such function; its own run_update still runs
    if original is not None:
        def spy(base):
            result = original(base)
            out["retry"] = result
            return result
        u._retry_pending_host_plugins = spy
    try:
        result = u.run_update(check_only=False)
        out["update"] = {"status": result.get("status"), "reason": str(result.get("reason") or result.get("error") or "")[:80]}
    except u.UpdateUnavailableError as error:
        out["update"] = {"status": "unreachable", "reason": str((error.payload or {}).get("error") or "")[:80]}
except Exception as error:
    out["error"] = type(error).__name__
print(json.dumps(out))
'''


def _retry_status(retry: Any) -> tuple[str, list[str]]:
    """The status table of what the installed engine's host-plugin retry answered, as one code and the hosts still pending."""
    if not isinstance(retry, dict):
        return "unknown", []
    status = retry.get("status")
    if status == "retried":
        pending = (retry.get("hostPluginSync") or {}).get("pendingHosts")
        pending = [str(host) for host in pending] if isinstance(pending, list) else []
        return ("retried_pending" if pending else "retried_done"), pending
    if status in ("not_needed", "not_applicable", "skipped", "failed"):
        return str(status), []
    return "skipped", []  # gave_up / waiting belong to the background worker, which this call is not


def _end_process_tree(process: Any) -> None:
    """End a child and everything it started. Bounded, never raises. POSIX: the child leads a group of its own (``start_new_session``) and the
    whole group is killed; Windows: ``taskkill /T`` walks the parent/child tree (no process group is requested there, see ``windows_console``)."""
    import subprocess
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False, **no_console_window())
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def run_installed_updater(timeout: float = UPDATER_TIMEOUT_SECONDS) -> dict[str, Any]:
    """The manual update path of the engine that is INSTALLED (``<agentlas home>/runtime/current``), run once in its own process.

    The environment loses ``HEPHAESTUS_AUTO_UPDATE_WORKER`` so the updater takes the manual path (no 30-minute spacing, no 20-try limit,
); a caller that was itself started by the background worker must not hand that flag on. The child's answer is the retry's
    own status plus whether the download part reached the network. When it runs past ``timeout`` the child and every process it started are
    ended (so the caller's own, longer limit never has to find them). Never raises."""
    current = agent_home.agentlas_home() / "runtime" / "current"
    try:
        root = current.resolve()
        if not (current.exists() or current.is_symlink()) or not (root / "agentlas_cloud" / "update.py").is_file():
            return {"status": "no_installed_engine"}
    except OSError:
        return {"status": "no_installed_engine"}
    env = {key: value for key, value in os.environ.items() if key != "HEPHAESTUS_AUTO_UPDATE_WORKER"}
    env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["HEPHAESTUS_RUNTIME_ROOT"] = str(root)
    import subprocess
    try:
        child = subprocess.Popen([sys.executable, "-c", _UPDATER_CHILD], cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 **({} if os.name == "nt" else {"start_new_session": True}), **no_console_window())
    except OSError as error:
        return {"status": "failed", "reason": _code(error)}
    try:
        stdout, _stderr = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _end_process_tree(child)
        try:
            child.communicate(timeout=5)  # reap it; a process outside the tree that still holds the pipes is not waited for
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        return {"status": "failed", "reason": "updater_timeout"}
    except BaseException:
        _end_process_tree(child)
        raise
    line = next((text for text in (stdout or "").splitlines()[::-1] if text.startswith("{")), "")
    try:
        answer = json.loads(line)
    except ValueError:
        return {"status": "failed", "reason": "updater_no_answer"}
    if not isinstance(answer, dict):
        return {"status": "failed", "reason": "updater_no_answer"}
    if answer.get("error"):
        return {"status": "crashed", "reason": str(answer["error"])[:60]}
    status, pending = _retry_status(answer.get("retry"))
    update = answer.get("update") if isinstance(answer.get("update"), dict) else {}
    return {"status": status, "pendingHosts": pending, "download": str(update.get("status") or "unknown")}


def step_engine_copies(*, extra_engines: Iterable[str] = (), run_updater: bool = True, timeout: float = UPDATER_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Step 1. Which engine copies on this computer are older than the split, and one try to bring them up through the installed engine.

    ``done`` when every copy declares the layout (nothing is run then). Otherwise the installed engine's updater runs once and the copies
    are read again: ``done`` when they now all declare it, else ``remaining`` with ``host_plugin_restart`` (Claude Code or Codex is running
    the old plugin: closing it applies the switch), ``host_plugin_manual`` (no installed engine, or its updater does not manage the hosts:
    the user has to update), ``engine_offline`` (the updater could not reach the release server) or ``updater_retry_next_start``
    (it was busy or failed and looks again at the next start). ``failed`` only when the updater could not be run at all. Whatever this says,
    the steps after it are not held back by it, except that ``memory_move`` reads the copies itself and waits."""
    extra = list(extra_engines)
    found = engines(extra)
    old = sorted({str(copy.get("host")) for copy in found["copies"] if copy.get("state") != "declared"})
    result: dict[str, Any] = {"name": "engine_copies", "oldHosts": old, "copies": found["copies"]}
    if not old:
        return {**result, "state": "done", "updater": {"status": "not_needed"}}
    if not run_updater:
        return {**result, "state": "remaining", "reason": "updater_not_run", "updater": {"status": "not_run"}}
    updater = run_installed_updater(timeout)
    result["updater"] = updater
    after = engines(extra)
    result["copies"], result["oldHosts"] = after["copies"], sorted({str(copy.get("host")) for copy in after["copies"] if copy.get("state") != "declared"})
    if not result["oldHosts"]:
        return {**result, "state": "done"}
    status = updater["status"]
    if status == "no_installed_engine" or status == "not_applicable":
        reason = "host_plugin_manual"
    elif status == "retried_pending":
        reason = "host_plugin_restart"
    elif updater.get("download") in ("unreachable", "check_failed"):
        reason = "engine_offline"
    elif status == "crashed" or (status == "failed" and updater.get("reason") in ("updater_timeout", "updater_no_answer")):
        return {**result, "state": "failed", "reason": updater["reason"]}
    elif status in ("skipped", "failed", "unknown"):
        reason = "updater_retry_next_start"
    else:
        reason = "host_plugin_restart"  # the switch was made (or nothing was owed) and a copy is still old: its program has not been restarted
    return {**result, "state": "remaining", "reason": reason}


def step_empty_turns(owner: str, *, now: float | None = None, budget_seconds: float | None = None, check_only: bool = False) -> dict[str, Any]:
    """Step 4 (``prune_empty_turns``) as a step answer. ``check_only`` reads (read-only connection) and reports what is left."""
    if check_only:
        path = _store_path(owner)
        if path is None:
            return {"name": "empty_turns", "state": "done", "reason": "no_store"}
        try:
            db, _mode = open_readonly(path)
        except Unreadable as error:  # a store another process holds for a moment is waiting, not failing: the writing path answers the same
            return {"name": "empty_turns", "state": "remaining" if error.code == "locked" else "failed", "reason": error.code}
        try:
            pending = pending_prune(db, _tables(db), time.time() if now is None else now)
        finally:
            db.close()
        return {"name": "empty_turns", "state": "remaining" if any(pending.values()) else "done", "pending": pending, **({"reason": "work_left"} if any(pending.values()) else {})}
    try:
        report = prune_empty_turns(owner, now=now, budget_seconds=budget_seconds)
    except (sqlite3.Error, OSError, ValueError) as error:
        code = _code(error)
        return {"name": "empty_turns", "state": "remaining" if code == "locked" else "failed", "reason": code}
    state = report.get("state")
    if state == "no_store":
        return {"name": "empty_turns", "state": "done", "reason": "no_store"}
    if state == "busy":
        return {"name": "empty_turns", "state": "remaining", "reason": "busy"}
    return {"name": "empty_turns", "state": state, **({"reason": "budget"} if state == "remaining" else {}), "deleted": report.get("deleted", {}),
            "elapsedMs": report.get("elapsedMs", 0)}


def step_tidy(owner: str, *, now: float | None = None, budget_seconds: float | None = None, check_only: bool = False, removed_agents: Iterable[str] = ()) -> dict[str, Any]:
    """The' step (``first_run_tidy``) as a step answer. ``check_only`` reads (read-only connection) what is left and what is left on purpose."""
    from . import first_run_tidy as tidy
    if check_only:
        path = _store_path(owner)
        if path is None:
            return {"name": "tidy", "state": "done", "reason": "no_store"}
        try:
            db, _mode = open_readonly(path)
        except Unreadable as error:
            return {"name": "tidy", "state": "remaining" if error.code == "locked" else "failed", "reason": error.code}
        try:
            report = tidy.left_over(db)
        finally:
            db.close()
        work = any(report["pending"].values())
        return {"name": "tidy", "state": "remaining" if work else "done", **({"reason": "work_left"} if work else {}), **report}
    try:
        report = tidy.tidy(owner, removed_agents=removed_agents, budget_seconds=budget_seconds, now=now)
    except (sqlite3.Error, OSError, ValueError) as error:
        code = _code(error)
        return {"name": "tidy", "state": "remaining" if code == "locked" else "failed", "reason": code}
    state = report.get("state")
    if state == "no_store":
        return {"name": "tidy", "state": "done", "reason": "no_store"}
    if state == "busy":
        return {"name": "tidy", "state": "remaining", "reason": "busy"}
    units = report.get("units", [])
    waiting = [u for u in units if u.get("state") == "remaining"]
    causes = {str(key) for u in waiting for key in (list(u.get("blocked", {})) + ([u["reason"]] if u.get("reason") else []))}
    reason = None
    if waiting:   # a machine word the desktop loops on (budget, again at once) or stands aside for (locked) or stops at (disk_low, partial)
        reason = "disk_low" if "disk_full" in causes else "locked" if causes & {"locked", "store_locked", "columns_locked"} else "partial" if causes or any(u.get("left") for u in waiting) else "budget"
    return {"name": "tidy", "state": state, **({"reason": reason} if reason else {}), "units": units, "elapsedMs": report.get("elapsedMs", 0)}


def _store_path(owner: str) -> Path | None:
    from .memory_runtime import memory_path
    path = memory_path(owner)
    return None if path.is_symlink() or not path.is_file() else path


def step_memory_move(owner: str, *, homes_ready: bool, extra_engines: Iterable[str] = (), budget_seconds: float | None = 2.0, prune_pending: bool = False) -> dict[str, Any]:
    """Step 6. Turn the split layout on (only when the caller says ``homes_ready``) and move for up to ``budget_seconds``.

    The engine never decides to start by itself. Held back, each as ``remaining`` with the code: ``homes_not_ready``;
    ``empty_turns_pending`` (step 4 has not finished: a turn whose counters are wrong must not be mistaken for an empty one while rows
    move); ``engines_not_confirmed`` (an engine copy does not declare the layout, read from the copies, not from the caller);
    ``disk_low``; ``quick_check_failed``; ``layout_unknown``. Moving reports ``more_to_move`` until nothing is left. Every call that has rows to move
    moves at least one batch (200 rows), whatever ``budget_seconds`` is (``None`` = no time limit, at most 50 batches); a call that
    moved nothing although rows are left answers ``no_progress`` instead, so a caller can tell a stalled move from a slow one and stops asking."""
    from . import memory_split as split
    status = split.status(owner)
    if status.get("state") == "no_store":
        return {"name": "memory_move", "state": "done", "reason": "no_store"}
    if status.get("layoutValue") != ms.SPLIT_LAYOUT:
        if not homes_ready:
            return {"name": "memory_move", "state": "remaining", "reason": "homes_not_ready"}
        if prune_pending:
            return {"name": "memory_move", "state": "remaining", "reason": "empty_turns_pending"}
        started = split.start(owner, homes_ready=True, extra_engines=extra_engines)
        if started.get("state") == "blocked":
            reasons = [str(reason) for reason in started.get("reasons", [])]
            return {"name": "memory_move", "state": "remaining", "reason": reasons[0] if reasons else "blocked", "reasons": reasons,
                    **({"notDeclared": [{key: item[key] for key in ("host", "state", "reason") if key in item} for item in started["notDeclared"]]}
                       if started.get("notDeclared") else {})}  # the copy's folder is left out: this answer carries no path
    moved = split.step(owner, budget_seconds=budget_seconds, vacuum=False)
    code = moved.get("state")
    base = {"name": "memory_move", "moved": moved.get("moved", 0), "remainingRows": moved.get("remaining", 0), "stuck": moved.get("stuck", {})}
    if moved.get("skipped"):
        # Why rows stayed (added only when there is a reason): the reason codes with their row counts, what a store lacked (machine
        # names, no text), and whether asking again can change anything. The fields that were there keep their meaning.
        base["skipped"] = moved["skipped"]
        if moved.get("skippedMissing"):
            base["skippedMissing"] = moved["skippedMissing"]
        if "retryable" in moved:
            base["retryable"] = moved["retryable"]
    if code in ("done", "idle"):
        return {**base, "state": "done"}
    if code == "moved":
        if base["moved"]:
            return {**base, "state": "remaining", "reason": "more_to_move"}
        stalled = {**base, "state": "remaining", "reason": "no_progress"}
        if base.get("skipped"):  # "no progress" says why: the reason that kept the most rows
            stalled["why"] = max(sorted(base["skipped"]), key=lambda key: base["skipped"][key])
        return stalled
    if code == "partial":
        return {**base, "state": "remaining", "reason": "partial", "left": moved.get("left", 0), "reasons": moved.get("reasons", {})}
    if code == "busy":
        return {**base, "state": "remaining", "reason": "busy"}
    if code == "blocked":
        return {**base, "state": "remaining", "reason": str(moved.get("reason") or "blocked")}
    return {**base, "state": "remaining", "reason": str(code or "unknown")}


def run_steps(owner: str, *, only: Iterable[str] = (), homes_ready: bool = False, extra_engines: Iterable[str] = (), budget_seconds: float = 2.0,
              run_updater: bool = True, check_only: bool = False, now: float | None = None, removed_agents: Iterable[str] = ()) -> dict[str, Any]:
    """The engine's steps in order, one answer. Each step is safe to call again; a step that fails or has to wait does not stop the next one
    (they ask the data, not each other, except that ``memory_move`` does not start while ``empty_turns`` has work left).

    ``state`` of the whole: ``failed`` when any step failed, else ``remaining`` when any step waits, else ``done``. ``check_only`` reads and
    reports, writes nothing, runs no updater and flips no switch.

    ``budget_seconds`` is the time each of ``empty_turns`` and ``memory_move`` works before it answers ``remaining``; **0 means no time limit
    for both** (``memory_move`` still stops after 50 batches), not "do nothing". The budget does not cover the time spent waiting for a
    file another process holds (up to 5 seconds each time a store is opened) or the installed engine's updater (up to 120 seconds), so a call
    can take longer than its budget. ``engine_copies`` runs that updater, which can use the network, every time it is called while a copy is
    still old: call it once per app start (``only=["engine_copies"]``) and pass ``run_updater=False`` (``--no-updater``) or ``only`` otherwise."""
    started = time.monotonic()
    wanted = [name for name in STEP_NAMES if not only or name in set(only)]
    steps: list[dict[str, Any]] = []
    left_to_prune = False
    for name in wanted:
        try:
            if name == "engine_copies":
                step = (step_engine_copies(extra_engines=extra_engines, run_updater=False) if check_only
                        else step_engine_copies(extra_engines=extra_engines, run_updater=run_updater))
            elif name == "empty_turns":
                step = step_empty_turns(owner, now=now, budget_seconds=budget_seconds if budget_seconds > 0 else None, check_only=check_only)
                left_to_prune = step.get("state") != "done"
            elif name == "tidy":
                step = step_tidy(owner, now=now, budget_seconds=budget_seconds if budget_seconds > 0 else None, check_only=check_only, removed_agents=removed_agents)
            else:
                if only and "empty_turns" not in set(only):
                    left_to_prune = step_empty_turns(owner, now=now, check_only=True).get("state") != "done"
                if check_only:
                    path = _store_path(owner)
                    layout = None
                    if path is not None:
                        db, _mode = open_readonly(path)
                        try:
                            layout = _meta(db, ms.LAYOUT_KEY)
                        finally:
                            db.close()
                    step = ({"name": "memory_move", "state": "done", "reason": "no_store"} if path is None else
                            {"name": "memory_move", "state": "remaining", "reason": "layout_off" if layout != ms.SPLIT_LAYOUT else "not_checked"})
                else:
                    step = step_memory_move(owner, homes_ready=homes_ready, extra_engines=extra_engines, budget_seconds=budget_seconds if budget_seconds > 0 else None,
                                        prune_pending=left_to_prune)
        except Exception as error:  # noqa: BLE001 - whatever a step raises is its own answer (a machine code, never the message); the next step still runs
            code = _code(error)
            if code == type(error).__name__:  # a bug in the step, not a state of the store: leave where it was (kind and file:line only, no message) on stderr
                tb = error.__traceback__
                while tb is not None and tb.tb_next is not None:
                    tb = tb.tb_next
                where = f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno}" if tb is not None else "?"
                print(f"first_run step {name} failed: {code} at {where}", file=sys.stderr)
            # A file another process holds for a moment is not a failure: the next call goes on from what is left.
            step = {"name": name, "state": "remaining" if code == "locked" else "failed", "reason": code}
        steps.append(step)
    states = {step["state"] for step in steps}
    return {"schema": STEPS_SCHEMA, "owner": {"id8": _h8(owner)}, "state": "failed" if "failed" in states else "remaining" if "remaining" in states else "done",
            "readOnly": bool(check_only), "steps": steps, "failed": [step["name"] for step in steps if step["state"] == "failed"],
            "remaining": {step["name"]: step.get("reason") for step in steps if step["state"] == "remaining"},
            "elapsedMs": int((time.monotonic() - started) * 1000)}
