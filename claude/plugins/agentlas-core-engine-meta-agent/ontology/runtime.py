from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .embeddings import LocalHashingVectorAdapter, cosine_similarity, tokenize
from .parsers import ParsedRecord, SourceParserRegistry
from .utils import clamp, content_hash, estimate_tokens, json_dumps, json_loads, normalize_name, normalized_key, stable_hash, utc_now


SCHEMA_VERSION = 1
DEFAULT_DB_PATH = Path(".agentlas/ontology-runtime.sqlite")


class DirectDurableMemoryWriteBlocked(RuntimeError):
    """Raised when a caller tries to bypass Memory Curator candidate tickets."""


@dataclass
class RuntimeConfig:
    db_path: Path | str = DEFAULT_DB_PATH
    chunk_token_limit: int = 220
    working_memory_ttl_seconds: int = 3600


class OntologyRuntime:
    def __init__(self, config: RuntimeConfig | None = None):
        self.config = config or RuntimeConfig()
        self.db_path = Path(self.config.db_path)
        self.parser_registry = SourceParserRegistry()
        self.vector_adapter = LocalHashingVectorAdapter()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def migrate(self) -> None:
        with closing(self.connect()) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version INTEGER PRIMARY KEY,
                  applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sources (
                  source_id TEXT PRIMARY KEY,
                  uri TEXT NOT NULL UNIQUE,
                  display_name TEXT NOT NULL,
                  source_type TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  version INTEGER NOT NULL,
                  parser_status TEXT NOT NULL,
                  parser_message TEXT,
                  adapter_name TEXT,
                  access_scope TEXT NOT NULL,
                  privacy_scope TEXT NOT NULL,
                  parent_source_id TEXT,
                  derived_from_json TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_lineage (
                  parent_source_id TEXT NOT NULL,
                  child_source_id TEXT NOT NULL,
                  relationship TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY(parent_source_id, child_source_id, relationship)
                );

                CREATE TABLE IF NOT EXISTS chunks (
                  chunk_id TEXT PRIMARY KEY,
                  source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                  chunk_index INTEGER NOT NULL,
                  text TEXT NOT NULL,
                  source_span_json TEXT NOT NULL,
                  token_estimate INTEGER NOT NULL,
                  checksum TEXT NOT NULL,
                  privacy_scope TEXT NOT NULL,
                  source_lineage_json TEXT NOT NULL,
                  vector_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(source_id, chunk_index, checksum)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                  chunk_id UNINDEXED,
                  text,
                  tokenize='porter'
                );

                CREATE TABLE IF NOT EXISTS entities (
                  entity_id TEXT PRIMARY KEY,
                  canonical_name TEXT NOT NULL UNIQUE,
                  entity_type TEXT NOT NULL,
                  status TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS entity_aliases (
                  alias TEXT NOT NULL,
                  normalized_alias TEXT NOT NULL UNIQUE,
                  entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS relations (
                  relation_id TEXT PRIMARY KEY,
                  subject_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                  object_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                  relation_type TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  evidence_chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
                  source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                  source_lineage_json TEXT NOT NULL,
                  valid_from TEXT,
                  valid_to TEXT,
                  observed_at TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(subject_entity_id, object_entity_id, relation_type, evidence_chunk_id)
                );

                CREATE TABLE IF NOT EXISTS memory_candidates (
                  ticket_id TEXT PRIMARY KEY,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  query TEXT NOT NULL,
                  candidate_text TEXT NOT NULL,
                  source_refs_json TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  risk TEXT NOT NULL,
                  expiry TEXT,
                  suggested_scope TEXT NOT NULL,
                  status TEXT NOT NULL,
                  durable_write_enabled INTEGER NOT NULL DEFAULT 0 CHECK (durable_write_enabled = 0),
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_candidate_events (
                  event_id TEXT PRIMARY KEY,
                  ticket_id TEXT NOT NULL REFERENCES memory_candidates(ticket_id) ON DELETE CASCADE,
                  decision TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS working_memory (
                  item_id TEXT PRIMARY KEY,
                  agent_id TEXT NOT NULL,
                  task_scope TEXT NOT NULL,
                  memory_item TEXT NOT NULL,
                  source_refs_json TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  importance REAL NOT NULL,
                  ttl_seconds INTEGER NOT NULL,
                  expires_at TEXT NOT NULL,
                  last_used_at TEXT,
                  status TEXT NOT NULL,
                  invalidation_reason TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(agent_id, task_scope, memory_item, source_refs_json)
                );

                CREATE TABLE IF NOT EXISTS runtime_adapters (
                  name TEXT PRIMARY KEY,
                  kind TEXT NOT NULL,
                  status TEXT NOT NULL,
                  config_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )
            vector_config = {"provider": "local_hashing"}
            if hasattr(self.vector_adapter, "dimensions"):
                vector_config["dimensions"] = self.vector_adapter.dimensions
            conn.execute(
                """
                INSERT OR REPLACE INTO runtime_adapters(name, kind, status, config_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (self.vector_adapter.name, "vector", self.vector_adapter.status, json_dumps(vector_config), utc_now()),
            )
            for name, status in self.parser_registry.adapter_statuses():
                conn.execute(
                    "INSERT OR REPLACE INTO runtime_adapters(name, kind, status, config_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (name, "parser", status, "{}", utc_now()),
                )

    def ingest_path(self, path: str | Path, access_scope: str = "internal", parent_source_id: str | None = None) -> dict[str, Any]:
        root = Path(path)
        if root.is_file():
            files = [root]
        else:
            files = sorted(
                item
                for item in root.rglob("*")
                if item.is_file()
                and not any(part.startswith(".") for part in item.relative_to(root).parts)
            )
        summary = {
            "db_path": str(self.db_path),
            "sources": [],
            "chunks_written": 0,
            "entities_written": 0,
            "relations_written": 0,
            "idempotent_skips": 0,
        }
        with closing(self.connect()) as conn, conn:
            for source_path in files:
                result = self._ingest_file(conn, source_path, access_scope, parent_source_id)
                summary["sources"].append(result["source"])
                summary["chunks_written"] += result["chunks_written"]
                summary["entities_written"] += result["entities_written"]
                summary["relations_written"] += result["relations_written"]
                summary["idempotent_skips"] += 1 if result["unchanged"] else 0
        return summary

    def query(
        self,
        question: str,
        agent_id: str | None = None,
        allowed_scopes: Iterable[str] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        scopes = list(allowed_scopes or ["public", "internal"])
        with closing(self.connect()) as conn, conn:
            chunks = self._search_chunks(conn, question, scopes, limit)
            entities = self._related_entities(conn, question, chunks)
            relations = self._relation_edges(conn, entities, chunks)
            candidates = self._create_memory_candidates(conn, question, chunks, relations)
            working_memory: list[dict[str, Any]] = []
            if agent_id:
                self._raise_if_no_source_refs(chunks)
                for item in self._working_memory_items_from_query(question, chunks, relations):
                    self.add_working_memory(
                        agent_id=agent_id,
                        task_scope="query",
                        memory_item=item["memory_item"],
                        source_refs=item["source_refs"],
                        confidence=item["confidence"],
                        importance=item["importance"],
                        ttl_seconds=self.config.working_memory_ttl_seconds,
                        _conn=conn,
                    )
                working_memory = self.read_working_memory(agent_id, _conn=conn)
        return {
            "query": question,
            "chunks": chunks,
            "related_entities": entities,
            "relation_edges": relations,
            "memory_candidate_suggestions": candidates,
            "working_memory": working_memory,
            "vector_adapter": {"name": self.vector_adapter.name, "status": self.vector_adapter.status},
        }

    def graph_entity(self, name: str) -> dict[str, Any]:
        with closing(self.connect()) as conn, conn:
            entity = self._find_entity(conn, name)
            if entity is None:
                return {"entity": None, "aliases": [], "relations": [], "evidence_chunks": []}
            relations = self._relations_for_entity(conn, entity["entity_id"])
            chunk_ids = sorted({relation["evidence_chunk_id"] for relation in relations})
            evidence = self._chunks_by_ids(conn, chunk_ids)
            aliases = [
                row["alias"]
                for row in conn.execute("SELECT alias FROM entity_aliases WHERE entity_id = ? ORDER BY alias", (entity["entity_id"],))
            ]
        return {"entity": entity, "aliases": aliases, "relations": relations, "evidence_chunks": evidence}

    def list_memory_candidates(self, status: str | None = None) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn, conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM memory_candidates WHERE status = ? ORDER BY created_at DESC, ticket_id",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM memory_candidates ORDER BY created_at DESC, ticket_id").fetchall()
        return [self._memory_candidate_row(row) for row in rows]

    def decide_memory_candidate(self, ticket_id: str, decision: str, reason: str) -> dict[str, Any]:
        status_map = {
            "approve": "approved_pending_curator",
            "reject": "rejected",
            "quarantine": "quarantined",
            "supersede": "superseded",
            "deprecate": "deprecated",
        }
        if decision not in status_map:
            raise ValueError(f"unsupported memory candidate decision: {decision}")
        now = utc_now()
        with closing(self.connect()) as conn, conn:
            row = conn.execute("SELECT * FROM memory_candidates WHERE ticket_id = ?", (ticket_id,)).fetchone()
            if row is None:
                raise KeyError(ticket_id)
            event_id = stable_hash(f"candidate-event:{ticket_id}:{decision}:{reason}:{now}")
            conn.execute(
                "INSERT INTO memory_candidate_events(event_id, ticket_id, decision, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, ticket_id, decision, reason, now),
            )
            conn.execute(
                "UPDATE memory_candidates SET status = ?, updated_at = ? WHERE ticket_id = ?",
                (status_map[decision], now, ticket_id),
            )
            updated = conn.execute("SELECT * FROM memory_candidates WHERE ticket_id = ?", (ticket_id,)).fetchone()
        return self._memory_candidate_row(updated)

    def write_durable_memory(self, agent_id: str, payload: dict[str, Any]) -> None:
        raise DirectDurableMemoryWriteBlocked(
            "Ontology runtime cannot write durable memory directly; create a Memory Curator candidate ticket instead."
        )

    def add_working_memory(
        self,
        agent_id: str,
        task_scope: str,
        memory_item: str,
        source_refs: list[dict[str, Any]],
        confidence: float,
        importance: float,
        ttl_seconds: int | None = None,
        _conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        ttl = self.config.working_memory_ttl_seconds if ttl_seconds is None else ttl_seconds
        now = datetime.now(timezone.utc).replace(microsecond=0)
        expires_at = (now + timedelta(seconds=ttl)).isoformat()
        source_refs_json = json_dumps(source_refs)
        item_id = stable_hash(f"working-memory:{agent_id}:{task_scope}:{memory_item}:{source_refs_json}")
        conn = _conn or self.connect()
        close = _conn is None
        try:
            conn.execute(
                """
                INSERT INTO working_memory(
                  item_id, agent_id, task_scope, memory_item, source_refs_json,
                  confidence, importance, ttl_seconds, expires_at, last_used_at,
                  status, invalidation_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?, ?)
                ON CONFLICT(agent_id, task_scope, memory_item, source_refs_json)
                DO UPDATE SET last_used_at = excluded.last_used_at, expires_at = excluded.expires_at,
                  status = 'active', invalidation_reason = NULL, updated_at = excluded.updated_at
                """,
                (
                    item_id,
                    agent_id,
                    task_scope,
                    memory_item,
                    source_refs_json,
                    clamp(confidence),
                    clamp(importance),
                    ttl,
                    expires_at,
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            if close:
                conn.commit()
            row = conn.execute("SELECT * FROM working_memory WHERE item_id = ?", (item_id,)).fetchone()
            return self._working_memory_row(row)
        finally:
            if close:
                conn.close()

    def read_working_memory(
        self,
        agent_id: str,
        include_expired: bool = False,
        _conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        now = utc_now()
        conn = _conn or self.connect()
        close = _conn is None
        try:
            if include_expired:
                rows = conn.execute(
                    "SELECT * FROM working_memory WHERE agent_id = ? ORDER BY importance DESC, updated_at DESC",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM working_memory
                    WHERE agent_id = ? AND status = 'active' AND expires_at > ?
                    ORDER BY importance DESC, updated_at DESC
                    """,
                    (agent_id, now),
                ).fetchall()
                conn.execute(
                    "UPDATE working_memory SET last_used_at = ?, updated_at = ? WHERE agent_id = ? AND status = 'active' AND expires_at > ?",
                    (now, now, agent_id, now),
                )
                if close:
                    conn.commit()
            return [self._working_memory_row(row) for row in rows]
        finally:
            if close:
                conn.close()

    def prune_working_memory(self, agent_id: str, min_importance: float = 0.0) -> dict[str, Any]:
        now = utc_now()
        with closing(self.connect()) as conn, conn:
            expired = conn.execute(
                """
                UPDATE working_memory
                SET status = 'expired', invalidation_reason = 'ttl_expired', updated_at = ?
                WHERE agent_id = ? AND status = 'active' AND expires_at <= ?
                """,
                (now, agent_id, now),
            ).rowcount
            evicted = conn.execute(
                """
                UPDATE working_memory
                SET status = 'evicted', invalidation_reason = 'low_importance', updated_at = ?
                WHERE agent_id = ? AND status = 'active' AND importance < ?
                """,
                (now, agent_id, min_importance),
            ).rowcount
        return {"agent_id": agent_id, "expired": expired, "evicted": evicted}

    def verify(self) -> dict[str, Any]:
        with closing(self.connect()) as conn, conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            counts = {
                table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ["sources", "chunks", "entities", "relations", "memory_candidates", "working_memory"]
            }
            migration = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            unsupported = conn.execute(
                "SELECT count(*) FROM sources WHERE parser_status = 'unsupported_pending_adapter'"
            ).fetchone()[0]
        direct_write_blocked = False
        try:
            self.write_durable_memory("verify", {"probe": True})
        except DirectDurableMemoryWriteBlocked:
            direct_write_blocked = True
        status = "pass" if integrity == "ok" and migration == SCHEMA_VERSION and direct_write_blocked else "fail"
        return {
            "status": status,
            "schema_version": migration,
            "integrity_check": integrity,
            "counts": counts,
            "unsupported_pending_adapters": unsupported,
            "direct_durable_memory_write_blocked": direct_write_blocked,
            "storage_adapter": {"name": "sqlite", "status": "available", "path": str(self.db_path)},
            "vector_adapter": {"name": self.vector_adapter.name, "status": self.vector_adapter.status},
        }

    def backup(self, destination: str | Path) -> dict[str, Any]:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
        return {"status": "ok", "backup_path": str(destination)}

    def export_json(self, destination: str | Path) -> dict[str, Any]:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, list[dict[str, Any]]] = {}
        tables = ["sources", "chunks", "entities", "entity_aliases", "relations", "memory_candidates", "working_memory"]
        with closing(self.connect()) as conn, conn:
            for table in tables:
                data[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
        destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "ok", "export_path": str(destination), "tables": tables}

    def import_json(self, source: str | Path) -> dict[str, Any]:
        source = Path(source)
        data = json.loads(source.read_text(encoding="utf-8"))
        with closing(self.connect()) as conn, conn:
            for table, rows in data.items():
                if not rows:
                    continue
                keys = list(rows[0].keys())
                placeholders = ", ".join(["?"] * len(keys))
                columns = ", ".join(keys)
                for row in rows:
                    conn.execute(
                        f"INSERT OR REPLACE INTO {table}({columns}) VALUES ({placeholders})",
                        tuple(row[key] for key in keys),
                    )
        return {"status": "ok", "import_path": str(source)}

    def _ingest_file(self, conn: sqlite3.Connection, path: Path, access_scope: str, parent_source_id: str | None) -> dict[str, Any]:
        raw = path.read_bytes()
        checksum = content_hash(raw)
        uri = path.resolve().as_uri()
        source_id = stable_hash(f"source:{uri}")
        existing = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        if existing and existing["content_hash"] == checksum:
            return {
                "source": self._source_row(existing, unchanged=True),
                "chunks_written": 0,
                "entities_written": 0,
                "relations_written": 0,
                "unchanged": True,
            }

        if existing:
            self._delete_source_derivatives(conn, source_id)
            version = int(existing["version"]) + 1
            created_at = existing["created_at"]
        else:
            version = 1
            created_at = utc_now()

        parsed = self.parser_registry.parse(path)
        now = utc_now()
        lineage = {
            "source_id": source_id,
            "uri": uri,
            "content_hash": checksum,
            "version": version,
            "parent_source_id": parent_source_id,
            "derived_from": [parent_source_id] if parent_source_id else [],
        }
        conn.execute(
            """
            INSERT INTO sources(
              source_id, uri, display_name, source_type, content_hash, version,
              parser_status, parser_message, adapter_name, access_scope, privacy_scope,
              parent_source_id, derived_from_json, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              content_hash = excluded.content_hash,
              version = excluded.version,
              parser_status = excluded.parser_status,
              parser_message = excluded.parser_message,
              adapter_name = excluded.adapter_name,
              access_scope = excluded.access_scope,
              privacy_scope = excluded.privacy_scope,
              parent_source_id = excluded.parent_source_id,
              derived_from_json = excluded.derived_from_json,
              metadata_json = excluded.metadata_json,
              updated_at = excluded.updated_at
            """,
            (
                source_id,
                uri,
                path.name,
                parsed.source_type,
                checksum,
                version,
                parsed.parser_status,
                parsed.parser_message,
                parsed.adapter_name,
                access_scope,
                access_scope,
                parent_source_id,
                json_dumps(lineage["derived_from"]),
                json_dumps({"size_bytes": len(raw), "path_name": path.name}),
                created_at,
                now,
            ),
        )
        if parent_source_id:
            conn.execute(
                """
                INSERT OR IGNORE INTO source_lineage(parent_source_id, child_source_id, relationship, metadata_json, created_at)
                VALUES (?, ?, 'derived_from', ?, ?)
                """,
                (parent_source_id, source_id, json_dumps({"child_uri": uri}), now),
            )

        chunks_written = 0
        entities_written = 0
        relations_written = 0
        if parsed.parser_status == "parsed":
            for index, record in enumerate(self._chunk_records(parsed.records), start=0):
                chunk = self._write_chunk(conn, source_id, index, record, access_scope, lineage)
                chunks_written += 1 if chunk["inserted"] else 0
                entity_result = self._extract_and_write_graph(conn, chunk["chunk"], record)
                entities_written += entity_result["entities_written"]
                relations_written += entity_result["relations_written"]

        row = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        return {
            "source": self._source_row(row, unchanged=False),
            "chunks_written": chunks_written,
            "entities_written": entities_written,
            "relations_written": relations_written,
            "unchanged": False,
        }

    def _delete_source_derivatives(self, conn: sqlite3.Connection, source_id: str) -> None:
        chunk_ids = [row["chunk_id"] for row in conn.execute("SELECT chunk_id FROM chunks WHERE source_id = ?", (source_id,))]
        for chunk_id in chunk_ids:
            conn.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (chunk_id,))
        conn.execute("DELETE FROM relations WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))

    def _chunk_records(self, records: list[ParsedRecord]) -> list[ParsedRecord]:
        chunks: list[ParsedRecord] = []
        for record in records:
            words = record.text.split()
            if not words:
                continue
            if len(words) <= self.config.chunk_token_limit:
                chunks.append(record)
                continue
            for start in range(0, len(words), self.config.chunk_token_limit):
                part = " ".join(words[start : start + self.config.chunk_token_limit])
                span = dict(record.span)
                span["token_start"] = start
                span["token_end"] = min(len(words), start + self.config.chunk_token_limit)
                chunks.append(ParsedRecord(part, span, dict(record.metadata)))
        return chunks

    def _write_chunk(
        self,
        conn: sqlite3.Connection,
        source_id: str,
        index: int,
        record: ParsedRecord,
        privacy_scope: str,
        lineage: dict[str, Any],
    ) -> dict[str, Any]:
        checksum = content_hash(record.text.encode("utf-8"))
        chunk_id = stable_hash(f"chunk:{source_id}:{index}:{checksum}")
        now = utc_now()
        vector = self.vector_adapter.embed(record.text)
        inserted = conn.execute(
            """
            INSERT OR IGNORE INTO chunks(
              chunk_id, source_id, chunk_index, text, source_span_json, token_estimate,
              checksum, privacy_scope, source_lineage_json, vector_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                source_id,
                index,
                record.text,
                json_dumps(record.span),
                estimate_tokens(record.text),
                checksum,
                privacy_scope,
                json_dumps(lineage),
                json_dumps(vector),
                now,
                now,
            ),
        ).rowcount == 1
        conn.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (chunk_id,))
        conn.execute("INSERT INTO chunk_fts(chunk_id, text) VALUES (?, ?)", (chunk_id, record.text))
        row = conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return {"inserted": inserted, "chunk": self._chunk_row(row)}

    def _extract_and_write_graph(self, conn: sqlite3.Connection, chunk: dict[str, Any], record: ParsedRecord) -> dict[str, int]:
        entities_written = 0
        relations_written = 0
        entity_names = extract_entity_names(chunk["text"])
        for name in entity_names:
            entities_written += 1 if self._ensure_entity(conn, name)[1] else 0
        for subject, relation_type, obj, confidence in extract_relations(chunk["text"]):
            subject_id, subject_new = self._ensure_entity(conn, subject)
            object_id, object_new = self._ensure_entity(conn, obj)
            entities_written += 1 if subject_new else 0
            entities_written += 1 if object_new else 0
            relation_id = stable_hash(f"relation:{subject_id}:{relation_type}:{object_id}:{chunk['chunk_id']}")
            now = utc_now()
            inserted = conn.execute(
                """
                INSERT OR IGNORE INTO relations(
                  relation_id, subject_entity_id, object_entity_id, relation_type, confidence,
                  evidence_chunk_id, source_id, source_lineage_json, valid_from, valid_to,
                  observed_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, 'active', ?, ?)
                """,
                (
                    relation_id,
                    subject_id,
                    object_id,
                    relation_type,
                    confidence,
                    chunk["chunk_id"],
                    chunk["source_id"],
                    json_dumps(chunk["source_lineage"]),
                    now,
                    now,
                    now,
                ),
            ).rowcount == 1
            relations_written += 1 if inserted else 0
        return {"entities_written": entities_written, "relations_written": relations_written}

    def _ensure_entity(self, conn: sqlite3.Connection, name: str) -> tuple[str, bool]:
        canonical = normalize_name(name)
        key = normalized_key(canonical)
        alias = conn.execute("SELECT entity_id FROM entity_aliases WHERE normalized_alias = ?", (key,)).fetchone()
        if alias:
            return alias["entity_id"], False
        entity_id = stable_hash(f"entity:{key}")
        now = utc_now()
        entity_type = infer_entity_type(canonical)
        inserted = conn.execute(
            """
            INSERT OR IGNORE INTO entities(entity_id, canonical_name, entity_type, status, confidence, created_at, updated_at)
            VALUES (?, ?, ?, 'active', 0.72, ?, ?)
            """,
            (entity_id, canonical, entity_type, now, now),
        ).rowcount == 1
        conn.execute(
            "INSERT OR IGNORE INTO entity_aliases(alias, normalized_alias, entity_id, created_at) VALUES (?, ?, ?, ?)",
            (canonical, key, entity_id, now),
        )
        return entity_id, inserted

    def _search_chunks(self, conn: sqlite3.Connection, question: str, scopes: list[str], limit: int) -> list[dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        tokens = [token for token in tokenize(question) if len(token) > 2]
        scope_marks = ", ".join(["?"] * len(scopes))
        if tokens:
            fts_query = " OR ".join(tokens)
            try:
                rows = conn.execute(
                    f"""
                    SELECT c.*, s.uri AS source_uri, s.source_type, bm25(chunk_fts) AS rank
                    FROM chunk_fts
                    JOIN chunks c ON c.chunk_id = chunk_fts.chunk_id
                    JOIN sources s ON s.source_id = c.source_id
                    WHERE chunk_fts MATCH ? AND c.privacy_scope IN ({scope_marks})
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, *scopes, limit * 4),
                ).fetchall()
                for row in rows:
                    item = self._chunk_row(row)
                    item["full_text_score"] = 1.0 / (1.0 + abs(float(row["rank"])))
                    candidates[item["chunk_id"]] = item
            except sqlite3.OperationalError:
                pass
        query_vector = self.vector_adapter.embed(question)
        rows = conn.execute(
            f"""
            SELECT c.*, s.uri AS source_uri, s.source_type
            FROM chunks c JOIN sources s ON s.source_id = c.source_id
            WHERE c.privacy_scope IN ({scope_marks})
            """,
            tuple(scopes),
        ).fetchall()
        for row in rows:
            item = candidates.get(row["chunk_id"], self._chunk_row(row))
            item["vector_score"] = max(0.0, cosine_similarity(query_vector, json_loads(row["vector_json"], [])))
            item["full_text_score"] = item.get("full_text_score", self._keyword_score(question, row["text"]))
            item["score"] = round(item["full_text_score"] * 0.65 + item["vector_score"] * 0.35, 6)
            if item["score"] > 0:
                candidates[item["chunk_id"]] = item
        return sorted(candidates.values(), key=lambda item: item["score"], reverse=True)[:limit]

    def _keyword_score(self, question: str, text: str) -> float:
        query_tokens = set(tokenize(question))
        text_tokens = set(tokenize(text))
        if not query_tokens:
            return 0.0
        return len(query_tokens & text_tokens) / len(query_tokens)

    def _related_entities(self, conn: sqlite3.Connection, question: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]
        entity_ids: set[str] = set()
        if chunk_ids:
            marks = ", ".join(["?"] * len(chunk_ids))
            for row in conn.execute(
                f"""
                SELECT subject_entity_id AS entity_id FROM relations WHERE evidence_chunk_id IN ({marks})
                UNION
                SELECT object_entity_id AS entity_id FROM relations WHERE evidence_chunk_id IN ({marks})
                """,
                (*chunk_ids, *chunk_ids),
            ):
                entity_ids.add(row["entity_id"])
        for name in extract_entity_names(question):
            entity = self._find_entity(conn, name)
            if entity:
                entity_ids.add(entity["entity_id"])
        if not entity_ids:
            return []
        marks = ", ".join(["?"] * len(entity_ids))
        rows = conn.execute(f"SELECT * FROM entities WHERE entity_id IN ({marks}) ORDER BY canonical_name", tuple(entity_ids)).fetchall()
        return [self._entity_row(row) for row in rows]

    def _relation_edges(self, conn: sqlite3.Connection, entities: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entity_ids = [entity["entity_id"] for entity in entities]
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]
        clauses = []
        args: list[Any] = []
        if entity_ids:
            marks = ", ".join(["?"] * len(entity_ids))
            clauses.append(f"(r.subject_entity_id IN ({marks}) OR r.object_entity_id IN ({marks}))")
            args.extend(entity_ids)
            args.extend(entity_ids)
        if chunk_ids:
            marks = ", ".join(["?"] * len(chunk_ids))
            clauses.append(f"r.evidence_chunk_id IN ({marks})")
            args.extend(chunk_ids)
        if not clauses:
            return []
        rows = conn.execute(
            f"""
            SELECT r.*, s.canonical_name AS subject, o.canonical_name AS object
            FROM relations r
            JOIN entities s ON s.entity_id = r.subject_entity_id
            JOIN entities o ON o.entity_id = r.object_entity_id
            WHERE r.status = 'active' AND ({" OR ".join(clauses)})
            ORDER BY r.confidence DESC, r.observed_at DESC
            LIMIT 20
            """,
            tuple(args),
        ).fetchall()
        return [self._relation_row(row) for row in rows]

    def _create_memory_candidates(
        self,
        conn: sqlite3.Connection,
        question: str,
        chunks: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []
        source_refs = [
            {
                "source_id": chunk["source_id"],
                "chunk_id": chunk["chunk_id"],
                "source_span": chunk["source_span"],
                "checksum": chunk["checksum"],
            }
            for chunk in chunks[:3]
        ]
        for relation in relations[:5]:
            source_refs.append(
                {
                    "relation_id": relation["relation_id"],
                    "evidence_chunk_id": relation["evidence_chunk_id"],
                    "confidence": relation["confidence"],
                }
            )
        relation_text = "; ".join(
            f"{edge['subject']} {edge['relation_type']} {edge['object']}" for edge in relations[:3]
        )
        candidate_text = relation_text or chunks[0]["text"][:360]
        idempotency_key = stable_hash(f"memory-candidate:{question}:{json_dumps(source_refs)}")
        ticket_id = stable_hash(f"ticket:{idempotency_key}")
        now = utc_now()
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_candidates(
              ticket_id, idempotency_key, query, candidate_text, source_refs_json,
              reason, confidence, risk, expiry, suggested_scope, status,
              durable_write_enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', 0, ?, ?)
            """,
            (
                ticket_id,
                idempotency_key,
                question,
                candidate_text,
                json_dumps(source_refs),
                "GraphRAG query returned source-backed chunks and graph edges that may be useful beyond this turn.",
                clamp(max([chunk.get("score", 0.0) for chunk in chunks] + [0.0])),
                "low" if all(chunk["privacy_scope"] in {"public", "internal"} for chunk in chunks) else "review_required",
                None,
                "session",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM memory_candidates WHERE ticket_id = ?", (ticket_id,)).fetchone()
        return [self._memory_candidate_row(row)]

    def _working_memory_items_from_query(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if relations:
            edge = relations[0]
            return [
                {
                    "memory_item": f"GraphRAG edge: {edge['subject']} {edge['relation_type']} {edge['object']}",
                    "source_refs": [
                        {
                            "relation_id": edge["relation_id"],
                            "evidence_chunk_id": edge["evidence_chunk_id"],
                            "source_lineage": edge["source_lineage"],
                        }
                    ],
                    "confidence": edge["confidence"],
                    "importance": 0.75,
                }
            ]
        return [
            {
                "memory_item": f"GraphRAG chunk for query '{question}': {chunks[0]['text'][:180]}",
                "source_refs": [{"source_id": chunks[0]["source_id"], "chunk_id": chunks[0]["chunk_id"]}],
                "confidence": chunks[0].get("score", 0.5),
                "importance": 0.55,
            }
        ]

    def _raise_if_no_source_refs(self, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        for chunk in chunks:
            if not chunk.get("source_id") or not chunk.get("source_span"):
                raise ValueError("working memory cache items require source refs and spans")

    def _find_entity(self, conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
        key = normalized_key(name)
        row = conn.execute(
            """
            SELECT e.* FROM entity_aliases a JOIN entities e ON e.entity_id = a.entity_id
            WHERE a.normalized_alias = ?
            """,
            (key,),
        ).fetchone()
        return self._entity_row(row) if row else None

    def _relations_for_entity(self, conn: sqlite3.Connection, entity_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT r.*, s.canonical_name AS subject, o.canonical_name AS object
            FROM relations r
            JOIN entities s ON s.entity_id = r.subject_entity_id
            JOIN entities o ON o.entity_id = r.object_entity_id
            WHERE r.subject_entity_id = ? OR r.object_entity_id = ?
            ORDER BY r.confidence DESC, r.observed_at DESC
            """,
            (entity_id, entity_id),
        ).fetchall()
        return [self._relation_row(row) for row in rows]

    def _chunks_by_ids(self, conn: sqlite3.Connection, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        marks = ", ".join(["?"] * len(chunk_ids))
        rows = conn.execute(
            f"""
            SELECT c.*, s.uri AS source_uri, s.source_type
            FROM chunks c JOIN sources s ON s.source_id = c.source_id
            WHERE c.chunk_id IN ({marks})
            """,
            tuple(chunk_ids),
        ).fetchall()
        return [self._chunk_row(row) for row in rows]

    def _source_row(self, row: sqlite3.Row, unchanged: bool = False) -> dict[str, Any]:
        return {
            "source_id": row["source_id"],
            "uri": row["uri"],
            "display_name": row["display_name"],
            "source_type": row["source_type"],
            "content_hash": row["content_hash"],
            "version": row["version"],
            "parser_status": row["parser_status"],
            "parser_message": row["parser_message"],
            "adapter_name": row["adapter_name"],
            "access_scope": row["access_scope"],
            "privacy_scope": row["privacy_scope"],
            "parent_source_id": row["parent_source_id"],
            "derived_from": json_loads(row["derived_from_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "unchanged": unchanged,
        }

    def _chunk_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "chunk_id": row["chunk_id"],
            "source_id": row["source_id"],
            "chunk_index": row["chunk_index"],
            "text": row["text"],
            "source_span": json_loads(row["source_span_json"], {}),
            "token_estimate": row["token_estimate"],
            "checksum": row["checksum"],
            "privacy_scope": row["privacy_scope"],
            "source_lineage": json_loads(row["source_lineage_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "source_uri": row["source_uri"] if "source_uri" in row.keys() else None,
            "source_type": row["source_type"] if "source_type" in row.keys() else None,
        }

    def _entity_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "entity_id": row["entity_id"],
            "canonical_name": row["canonical_name"],
            "entity_type": row["entity_type"],
            "status": row["status"],
            "confidence": row["confidence"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _relation_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "relation_id": row["relation_id"],
            "subject_entity_id": row["subject_entity_id"],
            "object_entity_id": row["object_entity_id"],
            "subject": row["subject"],
            "object": row["object"],
            "relation_type": row["relation_type"],
            "confidence": row["confidence"],
            "evidence_chunk_id": row["evidence_chunk_id"],
            "source_id": row["source_id"],
            "source_lineage": json_loads(row["source_lineage_json"], {}),
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "observed_at": row["observed_at"],
            "status": row["status"],
        }

    def _memory_candidate_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "ticket_id": row["ticket_id"],
            "idempotency_key": row["idempotency_key"],
            "query": row["query"],
            "candidate_text": row["candidate_text"],
            "source_refs": json_loads(row["source_refs_json"], []),
            "reason": row["reason"],
            "confidence": row["confidence"],
            "risk": row["risk"],
            "expiry": row["expiry"],
            "suggested_scope": row["suggested_scope"],
            "status": row["status"],
            "durable_write_enabled": bool(row["durable_write_enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _working_memory_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "item_id": row["item_id"],
            "agent_id": row["agent_id"],
            "task_scope": row["task_scope"],
            "memory_item": row["memory_item"],
            "source_refs": json_loads(row["source_refs_json"], []),
            "confidence": row["confidence"],
            "importance": row["importance"],
            "ttl_seconds": row["ttl_seconds"],
            "expires_at": row["expires_at"],
            "last_used_at": row["last_used_at"],
            "status": row["status"],
            "invalidation_reason": row["invalidation_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def extract_entity_names(text: str) -> list[str]:
    names: set[str] = set()
    for line in text.splitlines():
        if line.startswith("#"):
            value = normalize_name(line.lstrip("#"))
            if value:
                names.add(value)
    for match in re_find_title_phrases(text):
        names.add(match)
    for key, value in extract_fields(text).items():
        if key.split(".")[-1] in {"name", "team", "owner", "depends_on", "role"} or key.endswith("depends_on"):
            for phrase in re_find_title_phrases(value):
                names.add(phrase)
            if is_entity_like(value):
                names.add(normalize_name(value))
    return sorted(name for name in names if len(name) >= 3 and normalized_key(name) not in {"not", "the", "and"})


def extract_relations(text: str) -> list[tuple[str, str, str, float]]:
    relations: list[tuple[str, str, str, float]] = []
    phrase = r"([A-Z][A-Za-z0-9]+(?:[ \t]+[A-Z][A-Za-z0-9]+){0,4})"
    for subject, obj in re_pairs(rf"{phrase}[ \t]+depends on[ \t]+{phrase}", text):
        relations.append((subject, "depends_on", obj, 0.88))
    for subject, obj in re_pairs(rf"{phrase}[ \t]+owns[ \t]+{phrase}", text):
        relations.append((subject, "owns", obj, 0.84))
    for subject, obj in re_pairs(rf"{phrase}[ \t]+creates[ \t]+{phrase}", text):
        relations.append((subject, "creates", obj, 0.78))
    fields = extract_fields(text)
    subject = first_field(fields, ["name", "team", "$.team"])
    depends_on = first_field(fields, ["depends_on", "$.depends_on"])
    owner = first_field(fields, ["owner", "$.owner"])
    if subject and depends_on:
        relations.append((subject, "depends_on", depends_on, 0.82))
    if owner and subject:
        relations.append((owner, "owns", subject, 0.8))
    return dedupe_relations(relations)


def re_find_title_phrases(text: str) -> list[str]:
    import re

    results = []
    for match in re.finditer(r"\b(?:[A-Z][A-Za-z0-9]+|[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*)(?:[ \t]+(?:[A-Z][A-Za-z0-9]+|[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*)){0,4}\b", text):
        value = normalize_name(match.group(0))
        if value and not value.lower().startswith(("what ", "this ", "that ")):
            results.append(value)
    return results


def re_pairs(pattern: str, text: str) -> list[tuple[str, str]]:
    import re

    pairs = []
    for match in re.finditer(pattern, text):
        pairs.append((normalize_name(match.group(1)), normalize_name(match.group(2))))
    return pairs


def extract_fields(text: str) -> dict[str, str]:
    import re

    fields = {}
    for key, value in re.findall(r"([A-Za-z0-9_.$\[\]-]+):\s*([^|\n]+)", text):
        fields[key.strip()] = normalize_name(value)
    return fields


def first_field(fields: dict[str, str], names: list[str]) -> str | None:
    for name in names:
        if name in fields and fields[name]:
            return fields[name]
    for key, value in fields.items():
        if any(key.endswith(f".{name}") or key.endswith(name) for name in names) and value:
            return value
    return None


def is_entity_like(value: str) -> bool:
    return any(part[:1].isupper() for part in value.split())


def infer_entity_type(name: str) -> str:
    key = normalized_key(name)
    if "project" in key:
        return "project"
    if "agent" in key or "memory" in key or "runtime" in key:
        return "capability"
    if "robotics" in key or "company" in key:
        return "organization"
    return "concept"


def dedupe_relations(relations: list[tuple[str, str, str, float]]) -> list[tuple[str, str, str, float]]:
    seen = set()
    result = []
    for subject, relation_type, obj, confidence in relations:
        key = (normalized_key(subject), relation_type, normalized_key(obj))
        if key in seen:
            continue
        seen.add(key)
        result.append((normalize_name(subject), relation_type, normalize_name(obj), confidence))
    return result
