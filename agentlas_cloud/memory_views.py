"""Disposable canonical memory views; no model, admission or project-file writer.

Core drains its own view jobs. Node producer jobs retain their pending Graph
repair authority; rendering these files never fabricates that repair receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = "agentlas.memory-view.v1"
MAX_ROWS = 20_000
MAX_BYTES = 12 * 1024 * 1024
VIEW_PATH = re.compile(r"(?:one|agents/[a-f0-9]{64}|projects/[a-f0-9]{64})/memory\.json\Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _guard(db: sqlite3.Connection) -> None:
    guard = getattr(db, "_binding_guard", None)
    if guard:
        guard()


def _directory(base: Path, relative: str = "") -> Path:
    for parent in (base, *base.parents):
        if parent.is_symlink():
            raise ValueError("memory_view_directory_changed")
    if not base.is_dir():
        raise ValueError("memory_view_directory_changed")
    current = base
    for part in filter(None, relative.split("/")):
        if part in {".", ".."} or not re.fullmatch(r"[a-z0-9._-]+", part):
            raise ValueError("memory_view_path_invalid")
        current = current / part
        current.mkdir(mode=0o700, exist_ok=True)
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or current.is_symlink():
            raise ValueError("memory_view_directory_changed")
    return current


def is_generated_memory_view(value: Any) -> bool:
    return isinstance(value, dict) and value.get("schemaVersion") == SCHEMA and value.get("generated") is True


def _managed(file: Path, owner_ref: str) -> dict[str, Any] | None:
    try:
        info = file.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or file.is_symlink() or info.st_size > MAX_BYTES:
        raise ValueError("memory_view_file_changed")
    fd = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if opened.st_ino != info.st_ino or opened.st_dev != info.st_dev:
            raise ValueError("memory_view_file_changed")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("memory_view_budget_exceeded")
    finally:
        os.close(fd)
    value = json.loads(raw)
    if not is_generated_memory_view(value) or value.get("ownerRef") != owner_ref:
        raise ValueError("memory_view_foreign_file")
    return value


def _write(db: sqlite3.Connection, base: Path, relative: str, value: Any, owner_ref: str) -> None:
    _guard(db)
    parent = _directory(base, str(Path(relative).parent).replace("\\", "/") if "/" in relative else "")
    target = parent / Path(relative).name
    _managed(target, owner_ref)
    temporary = parent / (".memory-" + str(uuid.uuid4()) + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        _guard(db)
        _directory(base, str(parent.relative_to(base)).replace("\\", "/") if parent != base else "")
        _managed(target, owner_ref)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _remove(db: sqlite3.Connection, base: Path, relative: str, owner_ref: str) -> None:
    if relative != "manifest.json" and not VIEW_PATH.fullmatch(relative):
        raise ValueError("memory_view_path_invalid")
    _guard(db)
    _directory(base, relative.rsplit("/", 1)[0] if "/" in relative else "")
    file = base.joinpath(*relative.split("/"))
    if _managed(file, owner_ref):
        file.unlink()


def _object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _state(db: sqlite3.Connection, owner: str) -> tuple[int, int]:
    bound = db.execute("SELECT value FROM memory_store_meta WHERE key='owner_namespace'").fetchone()
    if not bound or bound[0] != owner:
        raise ValueError("memory_view_owner_mismatch")
    revision = int(db.execute("SELECT value FROM memory_store_meta WHERE key='revision'").fetchone()[0])
    epoch = db.execute("SELECT epoch FROM memory_forget_clock WHERE id=1").fetchone()
    return revision, int(epoch[0]) if epoch else 0


def _track_dependencies(db: sqlite3.Connection) -> None:
    for table in ("memory_identity_bindings", "memory_origin_links", "memory_project_links", "memory_entry_native"):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue
        installed = False
        for operation in ("INSERT", "UPDATE", "DELETE"):
            trigger = "memory_view_revision_" + table + "_" + operation.lower()
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?", (trigger,)).fetchone():
                continue
            db.execute("CREATE TRIGGER IF NOT EXISTS " + trigger + " AFTER " + operation + " ON " + table +
                       " BEGIN UPDATE memory_store_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'; END")
            installed = True
        if installed:
            db.execute("UPDATE memory_store_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")


def process_memory_views(db: sqlite3.Connection, database_path: Path, owner: str) -> dict[str, Any]:
    """Bounded, synchronous background projection; original commit never waits for a model here."""
    if db.in_transaction:
        return {"completed": 0, "state": "idle"}
    base, ref = database_path.parent / "views", _hash(owner)
    if database_path.parent.name != ref:
        return {"completed": 0, "state": "retry", "reason": "memory_view_owner_path_mismatch"}
    try:
        db.execute("BEGIN IMMEDIATE")
        _track_dependencies(db)
        revision, epoch = _state(db, owner)
        pending = db.execute("SELECT outbox_id FROM memory_projection_outbox WHERE outbox_id LIKE 'core-projection:%' AND state IN ('queued','processing','retry') ORDER BY created_at LIMIT 32").fetchall()
        if base.exists():
            _directory(database_path.parent, "views")
        existing = _managed(base / "manifest.json", ref) if base.exists() else None
        if existing and (not isinstance(existing.get("files"), list) or len(existing["files"]) > MAX_ROWS):
            raise ValueError("memory_view_manifest_invalid")
        fresh = existing and existing.get("authorityRevision") == revision and existing.get("revocationEpoch") == epoch
        if not fresh:
            rows = db.execute("""SELECT m.id,m.scope,m.kind,m.content,m.agent_id,b.actor_id,m.project_id,
                m.confidence,m.sensitivity,m.created_at,b.origin_refs_json,b.applicability_json,b.curation_actor,b.policy_version
                FROM memory_entries m LEFT JOIN memory_identity_bindings b ON b.memory_id=m.id
                WHERE m.superseded_at IS NULL AND m.content<>'' AND m.scope<>'session' AND m.sensitivity<>'secret'
                AND (b.owner_namespace IS NULL OR b.owner_namespace=?)
                AND COALESCE(json_extract(b.applicability_json,'$.enabled'),1)<>0 ORDER BY m.created_at,m.id LIMIT ?""", (owner, MAX_ROWS + 1)).fetchall()
            if len(rows) > MAX_ROWS:
                raise ValueError("memory_view_budget_exceeded")
            native = {}
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_entry_native'").fetchone():
                native = {row[0]: row[1] for row in db.execute("SELECT entry_id,content_native FROM memory_entry_native")}
            links: dict[str, list[dict[str, str]]] = {}
            for row in db.execute("SELECT memory_id,project_id,relation FROM memory_project_links"):
                links.setdefault(row[0], []).append({"projectId": row[1], "relation": row[2]})
            groups: dict[str, dict[str, Any]] = {}
            def add(key: str, description: dict[str, Any], entry: dict[str, Any]) -> None:
                groups.setdefault(key, {**description, "entries": []})["entries"].append(entry)
            for row in rows:
                actor = row["actor_id"] if row["actor_id"] is not None else row["agent_id"]
                try:
                    origins = json.loads(row["origin_refs_json"] or "[]")
                except ValueError:
                    origins = []
                entry = {"id": row["id"], "scope": row["scope"], "kind": row["kind"], "content": row["content"],
                    "actorId": actor, "originProjectId": row["project_id"], "projectRelations": links.get(row["id"], []),
                    "applicability": _object(row["applicability_json"]), "originRefs": origins,
                    "curationActor": row["curation_actor"] or "legacy", "policyVersion": row["policy_version"],
                    "confidence": row["confidence"], "sensitivity": row["sensitivity"], "createdAt": row["created_at"]}
                if row["id"] in native:
                    entry["contentNative"] = native[row["id"]]
                if actor:
                    key = "one/memory.json" if actor == "agentlas-one" else "agents/" + _hash(actor) + "/memory.json"
                    add(key, {"kind": "one" if actor == "agentlas-one" else "agent", "actorId": actor}, entry)
                projects = {link["projectId"] for link in links.get(row["id"], [])}
                if row["project_id"]:
                    projects.add(row["project_id"])
                for project in sorted(projects):
                    add("projects/" + _hash(project) + "/memory.json", {"kind": "project", "projectId": project}, entry)
            groups.setdefault("one/memory.json", {"kind": "one", "actorId": "agentlas-one", "entries": []})
            common = {"schemaVersion": SCHEMA, "generated": True, "ownerRef": ref, "authorityRevision": revision, "revocationEpoch": epoch}
            manifest = {**common, "files": [{"path": key, **{name: value for name, value in group.items() if name != "entries"}, "count": len(group["entries"])} for key, group in sorted(groups.items())]}
            rendered = [(key, {**common, **group}) for key, group in sorted(groups.items())]
            if sum(len(_json(value)) for _, value in rendered) > MAX_BYTES:
                raise ValueError("memory_view_budget_exceeded")
            _directory(database_path.parent, "views")
            for key, value in rendered:
                _write(db, base, key, value, ref)
            next_files = set(groups)
            for file in (existing or {}).get("files", []):
                if file["path"] not in next_files:
                    _remove(db, base, file["path"], ref)
            if _state(db, owner) != (revision, epoch):
                raise ValueError("memory_view_source_changed")
            _write(db, base, "manifest.json", manifest, ref)
        _guard(db)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for row in pending:
            db.execute("UPDATE memory_projection_outbox SET state='complete',updated_at=? WHERE outbox_id=?", (now, row[0]))
        more = bool(db.execute("SELECT 1 FROM memory_projection_outbox WHERE outbox_id LIKE 'core-projection:%' AND state IN ('queued','processing','retry') LIMIT 1").fetchone())
        db.commit()
        return {"completed": len(pending), "state": "complete" if pending or not fresh else "idle", "moreWork": more}
    except (OSError, ValueError, sqlite3.Error, TypeError, KeyError):
        db.rollback()
        try:
            db.execute("UPDATE memory_projection_outbox SET state='retry' WHERE outbox_id LIKE 'core-projection:%' AND state IN ('queued','processing','retry')")
            db.commit()
        except (ValueError, sqlite3.Error):
            db.rollback()
        return {"completed": 0, "state": "retry"}
