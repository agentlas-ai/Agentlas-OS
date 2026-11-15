"""Agentlas 2.0: the engine's one memory write door - a ticket call.

``write_tickets(raw, ...)`` takes the tool call the model made (``memory.record`` with ``{"tickets":[...]}``, a bare list, one ticket, the old
``{"turn_summary","observations"}`` shape, or the ``candidates`` of an old ``## Memory Events`` envelope) and:

1. reads the lines the model could see (the same bounded originals the old curator was shown: ``MemoryRuntime._curation_originals``),
2. hands the call and the host's FACTS to ``memory_curation_v2.receive_tickets`` (the one receiver; it is never rewritten here),
3. writes what the receiver accepted through the functions that already exist: a new line = ``canonical_writer`` (duplicates, forget stamps, the
   store ceiling, the Hub-guest rule), a rewrite or a condense = ``_apply_curation_in`` (the old line is hidden, the successor links it), a remove =
   ``memory_split.forget`` (the one forgetting path), and fills the two columns (``origin_class``, ``certainty``) from the host's facts.

What the engine knows (and what it does not): a hook or an MCP server of Claude Code, Codex and the other CLIs cannot tell whether the owner wrote the
turn, which conversation of the app it belongs to, or whether a tool ran. So the conversation is ``outside_window`` (last-but-one row:
Personal is not written, a project line only inside a project, an agent line is moved to the project or kept as the machine's work knowledge) and the
turn source is ``unknown`` (a model's "the person said it" is lowered to inferred; an instruction or a remove is therefore not_said). A borrowed Hub
agent (actor ``hub:``) is a ``guest`` and keeps nothing. No model is called; nothing is queued; no worker is started.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from . import memory_curation_v2 as cv

DEFERRED = "deferred"
"""An answer word that is not the receiver's: the ticket was received (ok) but the store did not take it now (full, forgotten text, a Hub guest). The model
is told so, because it may say "saved" only after an ``ok`` answer."""
_ACTION_OF_RESULT = {"saved": "add", "rewritten": "revise", "condensed": "merge"}
_STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def engine_facts(actor: str, *, project_bound: bool) -> dict[str, Any]:
    """The host facts the engine really has (see the module text). Nothing here is read from the model."""
    return {"conversation": "guest" if str(actor).startswith("hub:") else "outside_window", "turn_source": "unknown",
            "project_bound": bool(project_bound), "owner_text": None, "outside_text": True, "tools_ran": False, "receipt": False}


def tickets_from_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Old shapes -> tickets: the ``observations`` of the old memory.record and the ``candidates`` an old ``## Memory Events`` envelope carried.

    Each becomes one add ticket read as far as it fits (the receiver is lenient): the text, the kind and the scope the model gave; the source is not
    claimed (a missing source is the lowest tier), so an old-shape call can never become ``user``. The old confidence and evidence are not read."""
    out: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        text = item.get("content") if isinstance(item.get("content"), str) else item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        ticket: dict[str, Any] = {"action": "add", "text": item.get("content_native") or text, "source": "inferred"}
        if item.get("content_native"):
            ticket["en"] = text
        kind = item.get("kind") or item.get("memory_kind")
        scope = item.get("scope") or item.get("suggested_scope")
        if isinstance(kind, str) and kind != "hypothesis":
            ticket["kind"] = kind
        if isinstance(scope, str):
            ticket["scope"] = scope
        out.append(ticket)
    return out[: cv.MAX_TICKETS]


def _visible_line(item: dict[str, Any]) -> dict[str, Any]:
    entry = item.get("entry") or {}
    ticket_kind = None
    try:
        ticket_kind = json.loads(entry.get("context_json") or "{}").get("ticket_kind")
    except (ValueError, AttributeError):
        pass
    line = {"id": item["id"], "scope": item["scope"], "kind": item["kind"], "text": item["content"],
            "origin_class": entry.get("origin_class"), "certainty": entry.get("certainty")}
    if isinstance(ticket_kind, str):
        line["ticket_kind"] = ticket_kind
    return line


def _stamp_columns(conn: sqlite3.Connection, memory_id: str, line: dict[str, Any], decision_extra: dict[str, Any]) -> None:
    """The two columns and the host marks, on the row just written (before its transaction commits). Only ever sets them on a row this write created."""
    context = {}
    row = conn.execute("SELECT context_json,evidence_json FROM memory_entries WHERE id=?", (memory_id,)).fetchone()
    if row is None:
        return
    try:
        context = json.loads(row[0] or "{}")
    except ValueError:
        context = {}
    if line.get("context"):
        context.update(line["context"])
    if line.get("marks"):
        context["marks"] = sorted(set(context.get("marks", [])) | set(line["marks"]))
    try:
        evidence = json.loads(row[1] or "[]")
    except ValueError:
        evidence = []
    for ref in decision_extra.get("evidence", []):
        if ref not in evidence:
            evidence.append(ref)
    conn.execute("UPDATE memory_entries SET origin_class=?,certainty=?,context_json=?,evidence_json=? WHERE id=?",
                 (line.get("origin_class"), line.get("certainty"), _json(context), _json(evidence), memory_id))


def _write_one(runtime: Any, item: dict[str, Any], originals: list[dict[str, Any]], source: dict[str, Any]) -> dict[str, Any]:
    """Write one accepted line; returns the writer's result ({memory_ref, action, written} or {action: defer, reason})."""
    from .memory_curation_decisions import digest  # noqa: F401 - the replacement key is made by _apply_curation_in
    line = item["line"]
    by_id = {o["id"]: o for o in originals}
    targets = [{"id": ident, "revision": by_id[ident]["revision"]} for ident in item["targets"] if ident in by_id]
    decision: dict[str, Any] = {"action": _ACTION_OF_RESULT[item["result"]] if targets else "add", "content": line["text"],
                                "kind": line["store_kind"], "scope": line["scope"], "targets": targets, "origin_refs": []}
    if line.get("native"):
        decision["content_native"] = line["native"]
    extra: dict[str, Any] = {"evidence": []}
    if item["result"] == "rewritten" and line.get("why") and item["targets"]:
        extra["evidence"].append(("corrects:" if line["why"] == "corrected" else "supersedes:") + item["targets"][0])
    if item["result"] == "condensed" and line.get("carry_evidence_from"):
        for ident in line["carry_evidence_from"]:
            try:
                old = json.loads((by_id.get(ident, {}).get("entry") or {}).get("evidence_json") or "[]")
            except ValueError:
                old = []
            extra["evidence"] += [ref for ref in old if isinstance(ref, str) and ref not in extra["evidence"]][:8]
    box: dict[str, Any] = {}

    def writer(db: sqlite3.Connection, proposal: dict[str, Any], write_source: dict[str, Any]) -> dict[str, Any]:
        result = runtime.canonical_writer(db, proposal, write_source)
        if result.get("written") and result.get("memory_ref"):
            tx = runtime._store_tx
            conn = tx["db"] if tx and tx.get("memory_id") == result["memory_ref"] else db
            _stamp_columns(conn, result["memory_ref"], line, extra)
        box["result"] = result
        return result

    runtime.db.execute("BEGIN IMMEDIATE")
    try:
        result = runtime._apply_curation(decision, source, {"originals": originals}, writer)
        runtime.db.commit()
    except BaseException:
        runtime.db.rollback()
        runtime._retire_later = {}  # the root did not commit: nothing is hidden in another store
        raise
    runtime.flush_retire_later()  # EK4: the lines a condense replaced in other stores are hidden now that the new line is committed
    return result


def _contradicts(runtime: Any, line_id: str, others: list[str]) -> None:
    """The edge of an owner-line conflict: from the line just written to each owner line it disagrees with (both must sit in this file; otherwise no edge)."""
    from . import memory_relations as relations
    row = runtime.db.execute("SELECT scope,agent_id,project_id,project_path FROM memory_entries WHERE id=?", (line_id,)).fetchone()
    if row is None:
        return
    key = relations.owner_scope_key(row[0], row[1], row[2], row[3])
    if not key:
        return
    runtime.db.execute("BEGIN IMMEDIATE")
    try:
        for other in others:
            try:
                relations.write_edge(runtime.db, line_id, other, "contradicts", owner_scope_key=key)
            except relations.RelationError:
                continue
        runtime.db.commit()
    except BaseException:
        runtime.db.rollback()
        raise


def _bare_target_ids(raw: Any) -> Any:
    """memory.search, timeline and get name a memory ``m:<id>`` (an episode ``e:<id>``); a ticket's ``targets`` are the bare ids the receiver was shown. A model that copies the id
    from a search result writes the prefixed form: read it as the line it names (an episode is not a line and stays unknown)."""
    if isinstance(raw, str):
        value = cv._extract(raw)
        raw = value if value is not None else raw
    if isinstance(raw, list):
        raw = {"tickets": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("tickets"), list):
        return raw
    fixed = []
    for ticket in raw["tickets"]:
        if isinstance(ticket, dict):
            ticket = dict(ticket)
            for key in ("targets", "target", "replaces"):
                value = ticket.get(key)
                items = value if isinstance(value, list) else [value] if isinstance(value, str) else None
                if items is not None:
                    cleaned = [i[2:] if isinstance(i, str) and i.startswith("m:") and len(i) > 2 else i for i in items]
                    ticket[key] = cleaned if isinstance(value, list) else cleaned[0]
        fixed.append(ticket)
    return {**raw, "tickets": fixed}


def _ceiling(item: dict[str, Any], why: str) -> dict[str, int]:
    """``{"max": n}``: the row ceiling of the store a line did not fit in (ruleset ``stores.<scope>.ceilingRows``), so the model can tell the owner how full it is."""
    if why != "store_full":
        return {}
    from . import memory_classify
    rules = memory_classify.active() or {}
    value = ((rules.get("stores") or {}).get(str(item.get("scope") or "")) or {}).get("ceilingRows")
    return {"max": value} if isinstance(value, int) and not isinstance(value, bool) else {}


def write_tickets(raw: Any, *, actor: str, project_path: str | None, in_project: bool, project_ref: str | None = None,
                  facts: dict[str, Any] | None = None, label: str = "mcp-ticket") -> dict[str, Any]:
    """Receive and write one ticket call. Returns ``{"answers": [...], "counts": {...}, "unreadable": code|None}``; an answer is what the tool tells the model.

    ``facts`` replaces the engine's own host facts (a caller that really knows the conversation passes them; the engine's hooks and MCP server do not).
    Never starts a worker and never calls a model. A store that cannot be opened raises ``ValueError('memory_...')`` for the caller's code mapping."""
    from .memory_runtime import MemoryRuntime, owner_binding
    owner = owner_binding(create=True)
    if not owner:
        raise ValueError("memory_store_absent")
    runtime = MemoryRuntime(owner)
    try:
        stamp = time.time_ns() // 1_000_000
        base = f"{label}:" + _hash(_json([owner, actor, project_path, stamp, str(raw)[:2000]]))[:32]
        source = {"owner_namespace": owner, "actor_id": actor, "project_ref": project_ref, "project_path": project_path,
                  "context_key": base, "source_ref": base, "source_revision": stamp, "ticket_ref": base, "coverage": "model_ticket"}
        originals = runtime._curation_originals(source)
        host = dict(facts) if facts is not None else engine_facts(actor, project_bound=in_project)
        host["visible"] = [_visible_line(o) for o in originals]
        receipt = cv.receive_tickets(_bare_target_ids(raw), host)
        answers: list[dict[str, Any]] = []
        saved_ids: list[str] = []
        for index, item in enumerate(receipt["items"]):
            answer = dict(receipt["answers"][index])
            if item["status"] != "ok":
                answers.append(answer)
                continue
            try:
                if item["result"] == "removed":
                    from . import memory_split
                    gone = [ident for ident in item["targets"] if memory_split.forget(owner, ident).get("state") not in (None, "not_found", "no_store")]
                    if not gone:
                        answers.append({"status": DEFERRED, "why": "target_not_found"})
                        continue
                    answer["id"] = gone[0]
                elif item["line"] is not None:
                    ticket_source = {**source, "ticket_ref": f"{base}:{index}", "source_ref": f"{base}:{index}"}
                    result = _write_one(runtime, item, originals, ticket_source)
                    if result.get("action") == "defer" or not result.get("memory_ref"):
                        why = str(result.get("reason") or "not_written")
                        answers.append({"status": DEFERRED, "why": why, **_ceiling(item, why)})
                        continue
                    answer["id"] = result["memory_ref"]
                    if result.get("action") == "deduped":
                        answer["result"] = "merged"
                    elif item["line"].get("contradicts"):
                        _contradicts(runtime, result["memory_ref"], list(item["line"]["contradicts"]))
                    saved_ids.append(result["memory_ref"])
            except (sqlite3.Error, ValueError, OSError) as error:
                code = str(error) if isinstance(error, ValueError) and str(error).startswith("memory_") else "store_unavailable"
                answers.append({"status": DEFERRED, "why": code})
                continue
            answers.append(answer)
        if saved_ids:
            runtime._process_views()
        return {"answers": answers, "counts": receipt["counts"], "unreadable": receipt["unreadable"], "ids": saved_ids}
    finally:
        runtime.close()


def record_stop(payload: dict[str, Any], host: str, summary: str | None, candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What a Stop hook does with a finished turn (Agentlas 2.0): record the turn (the host's excerpt of the reply, or the ``turn_summary`` of an old envelope the model
    still wrote) and nothing else; no queue, no worker, no model.

    ``candidates`` are the ``candidates`` of an old ``## Memory Events`` envelope (a session whose instructions predate', an old global block): they are not thrown
    away, they are turned into tickets and go through the same receiver as a tool call (once per turn: a turn already recorded is not written again). Never raises."""
    from .memory_runtime import host_actor_id, hook_project_binding, record_hook_turn
    out: dict[str, Any] = {}
    try:
        out["turnRecord"] = record_hook_turn(payload, host, summary)
    except Exception as error:  # noqa: BLE001 - a hook never blocks the host
        return {"turnRecord": {"state": "error", "reason": type(error).__name__}}
    if not candidates or out["turnRecord"].get("replayed") or out["turnRecord"].get("state") in {"busy", "skipped", "deferred"}:
        return out
    tickets = tickets_from_candidates(candidates)
    if not tickets:
        return out
    try:
        bound, found = hook_project_binding(payload)
        written = write_tickets({"tickets": tickets}, actor=host_actor_id(host), project_path=bound, in_project=found, label="envelope-ticket")
        out["envelopeTickets"] = written["counts"]
    except Exception as error:  # noqa: BLE001
        out["envelopeTickets"] = {"state": "error", "reason": type(error).__name__}
    return out
