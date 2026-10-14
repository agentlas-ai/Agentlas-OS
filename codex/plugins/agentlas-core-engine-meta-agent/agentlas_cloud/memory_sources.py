"""Metadata catalogue of original host sources; never a permission or memory writer.

Raw retrieval is possible only through a supplied current host reader. Neither
an address, digest nor catalogue UUID gives filesystem or server authority.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

SCHEMA = "agentlas.memory-source.v1"
_ADDRESS_KEYS = {"path", "ref", "contextKey", "operationId", "endpoint", "metaKey"}

def _text(value: Any, maximum: int = 1024, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not empty) or len(value.encode("utf-8")) > maximum or "\0" in value:
        raise ValueError("memory_source_metadata_invalid")
    return value

def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

def producer(db: sqlite3.Connection, owner: str, host_kind: str, custody_ref: str) -> str:
    bound = db.execute("SELECT value FROM memory_store_meta WHERE key='owner_namespace'").fetchone()
    if not bound or bound[0] != owner:
        raise ValueError("memory_source_owner_changed")
    key = "source-producer:" + _text(host_kind, 128)
    db.execute("INSERT OR IGNORE INTO memory_store_meta(key,value) VALUES(?,?)", (key, str(uuid.uuid4())))
    identity = db.execute("SELECT value FROM memory_store_meta WHERE key=?", (key,)).fetchone()[0]
    db.execute("INSERT OR IGNORE INTO memory_source_producers VALUES(?,?,?,?,?)", (identity, owner, host_kind, _text(custody_ref), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    row = db.execute("SELECT owner_namespace,host_kind,custody_ref FROM memory_source_producers WHERE producer_id=?", (identity,)).fetchone()
    if tuple(row) != (owner, host_kind, custody_ref):
        raise ValueError("memory_source_producer_changed")
    return identity

def register_source(db: sqlite3.Connection, owner: str, producer_id: str, *, actor_id: str | None,
                    visibility_domain: str, logical_key: str, source_kind: str, reader_contract: str,
                    writer_contract: str, schema_version: str, source_revision: str,
                    address: dict[str, str], range_unit: str = "none", range_start: int = 0,
                    range_end: int = 0, content_digest: str | None = None, adopt_address: bool = False, expected_metadata_revision: int | None = None) -> dict[str, Any]:
    p = db.execute("SELECT owner_namespace FROM memory_source_producers WHERE producer_id=?", (producer_id,)).fetchone()
    bound = db.execute("SELECT value FROM memory_store_meta WHERE key='owner_namespace'").fetchone()
    if not p or p[0] != owner or not bound or bound[0] != owner:
        raise ValueError("memory_source_owner_changed")
    if actor_id is not None: _text(actor_id, 512)
    for value in (visibility_domain, logical_key, source_kind, reader_contract, writer_contract, schema_version): _text(value)
    _text(source_revision, 512, True)
    if (not isinstance(address, dict) or not address or set(address) - _ADDRESS_KEYS
        or any(not isinstance(v, str) for v in address.values())): raise ValueError("memory_source_address_invalid")
    for value in address.values(): _text(value, 4096, True)
    encoded = _json(address)
    if len(encoded.encode("utf-8")) > 8192: raise ValueError("memory_source_address_invalid")
    if (range_unit not in {"none", "seq", "utf8", "host-observation"} or type(range_start) is not int
        or type(range_end) is not int or not 0 <= range_start <= range_end <= 2**53-1): raise ValueError("memory_source_range_invalid")
    if content_digest is not None and (len(content_digest) != 64 or any(c not in "0123456789abcdef" for c in content_digest)): raise ValueError("memory_source_digest_invalid")
    old = db.execute("SELECT * FROM memory_source_catalogue WHERE producer_id=? AND owner_namespace=? AND actor_id IS ? AND visibility_domain=? AND reader_contract=? AND logical_key=?",
                     (producer_id, owner, actor_id, visibility_domain, reader_contract, logical_key)).fetchone()
    snapshot = (source_kind, writer_contract, schema_version, source_revision, encoded, range_unit, range_start, range_end, content_digest)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if old:
        # Positional layout matches the shared additive SQL contract.
        if old[11] != encoded and (not adopt_address or expected_metadata_revision != old[16]): raise ValueError("memory_source_address_adoption_required")
        previous = (old[6], old[8], old[9], old[10], old[11], old[12], old[13], old[14], old[15])
        if previous == snapshot: return {"sourceId": old[0], "metadataRevision": old[16], "sourceRevision": source_revision}
        identity, revision = old[0], old[16] + 1
        db.execute("UPDATE memory_source_catalogue SET source_kind=?,writer_contract=?,schema_version=?,source_revision=?,address_json=?,range_unit=?,range_start=?,range_end=?,content_digest=?,metadata_revision=?,updated_at=? WHERE source_id=? AND metadata_revision=?",
                   (*snapshot, revision, now, identity, old[16]))
    else:
        identity, revision = str(uuid.uuid4()), 1
        db.execute("INSERT INTO memory_source_catalogue VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (identity, producer_id, owner, actor_id, visibility_domain, logical_key, source_kind, reader_contract, writer_contract, schema_version, source_revision, encoded, range_unit, range_start, range_end, content_digest, revision, now, now))
    db.execute("INSERT INTO memory_source_versions VALUES(?,?,?,?,?,?,?,?,?)", (identity, revision, source_revision, encoded, range_unit, range_start, range_end, content_digest, now))
    return {"sourceId": identity, "metadataRevision": revision, "sourceRevision": source_revision}

def read_source(db: sqlite3.Connection, owner: str, source_id: str, *, actor_id: str | None,
                visibility_domain: str, reader_contract: str, expected_revision: int,
                start: int, end: int, reader: Callable[[dict[str, Any], int, int], bytes],
                assert_current: Callable[[], None], maximum: int = 131072) -> bytes:
    """The supplied existing reader revalidates original source ACL/revision."""
    assert_current()
    row = db.execute("SELECT * FROM memory_source_catalogue WHERE source_id=? AND owner_namespace=? AND actor_id IS ? AND visibility_domain=? AND reader_contract=?", (source_id, owner, actor_id, visibility_domain, reader_contract)).fetchone()
    if not row or row[16] != expected_revision: raise ValueError("memory_source_changed")
    if type(start) is not int or type(end) is not int or not row[13] <= start <= end <= row[14] or type(maximum) is not int or not 0 < maximum <= 131072: raise ValueError("memory_source_range_invalid")
    result = reader(dict(row), start, end)
    assert_current()
    after = db.execute("SELECT metadata_revision FROM memory_source_catalogue WHERE source_id=? AND owner_namespace=?", (source_id, owner)).fetchone()
    if not after or after[0] != expected_revision or not isinstance(result, bytes) or len(result) > maximum: raise ValueError("memory_source_changed")
    if row[12] == "utf8": result.decode("utf-8", errors="strict")
    return result

def observe_file(path: Path, text: str, *, logical_key: str, actor_id: str, visibility_domain: str, schema_version: str) -> dict[str, Any] | None:
    """Record only a successful stable original read; legacy/manual text stays put."""
    from .memory_runtime import MemoryRuntime, owner_binding, SCHEMA as CORE_SCHEMA
    try:
        if path.is_symlink() or any(p.is_symlink() for p in path.parents): return None
        before = path.stat(); raw = path.read_bytes()
        if len(raw) > 2*1024*1024 or raw.decode("utf-8") != text: return None
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns): return None
        owner = owner_binding(create=False)
        if not owner: return None
        runtime = MemoryRuntime(owner)
        try:
            with runtime.db:
                p = producer(runtime.db, owner, "portable-core", "canonical-owner:" + owner)
                digest = hashlib.sha256(raw).hexdigest()
                return register_source(runtime.db, owner, p, actor_id=actor_id, visibility_domain=visibility_domain, logical_key=logical_key,
                    source_kind="manual-file", reader_contract="core.manual-file.v1", writer_contract="manual-original", schema_version=schema_version,
                    source_revision=digest, address={"path": str(path.absolute())}, range_unit="utf8", range_end=len(raw), content_digest=digest)
        finally: runtime.close()
    except Exception:
        # Catalogue failure never changes legacy manual reader eligibility.
        return None
