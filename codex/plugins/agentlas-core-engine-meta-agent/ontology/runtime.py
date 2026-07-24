from __future__ import annotations

import json
import os
import sqlite3
import stat
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .embeddings import (
    CJK_RUN_PATTERN,
    LATIN_TOKEN_PATTERN,
    VectorAdapter,
    cosine_similarity,
    select_vector_adapter,
    tokenize,
    vector_adapter_metadata,
)
from .parsers import ParsedRecord, SourceParserRegistry
from .utils import clamp, content_hash, estimate_tokens, json_dumps, json_loads, normalize_name, normalized_key, stable_hash, utc_now


SCHEMA_VERSION = 4
DEFAULT_DB_PATH = Path(".agentlas/ontology-runtime.sqlite")
MAX_INGEST_FILES = 1_000
MAX_ONTOLOGY_INBOX_FILES = 80
MAX_INGEST_FILE_BYTES = 16 * 1024 * 1024
MAX_INGEST_TOTAL_BYTES = 128 * 1024 * 1024
MAX_INGEST_DEPTH = 12

# Hybrid document retrieval (A-2/A-3) uses bounded fallback scans. Governed
# experience retrieval is intentionally different: every eligible row is
# scored before the adaptive token-budget selector chooses all-relevant or
# vector/RRF top-k, so an arbitrary recency window cannot hide old evidence.
RRF_K = 60
RRF_MISSING_RANK = 10_000
VECTOR_FALLBACK_SCAN_CAP = 5_000
MIN_VECTOR_SCORE = 0.05
MIN_EXPERIENCE_VECTOR_SCORE = 0.08
MODEL2VEC_MIN_VECTOR_SCORE = 0.15
MODEL2VEC_CJK_MIN_VECTOR_SCORE = 0.12
VECTOR_RELATIVE_FLOOR = 0.72
DEFAULT_EXPERIENCE_TOKEN_BUDGET = 800
DEFAULT_EXPERIENCE_TOP_K = 8
ACTIVE_EXPERIENCE_STATUSES = (
    "active",
    "accepted",
    "approved",
    "approved_pending_curator",
    "promoted",
)


class DirectDurableMemoryWriteBlocked(RuntimeError):
    """Raised when a caller tries to bypass Memory Curator candidate tickets."""


@dataclass
class RuntimeConfig:
    db_path: Path | str = DEFAULT_DB_PATH
    chunk_token_limit: int = 220
    chunk_overlap_ratio: float = 0.15
    working_memory_ttl_seconds: int = 3600
    # A-4: optional host-runtime LLM hooks. Both default to None so path 1
    # (zero-cost local search) stays the baseline; a host CLI runtime
    # (Claude Code / Codex) can inject callables without any embedding API.
    query_expansion_hook: Callable[[str], list[str]] | None = None
    rerank_hook: Callable[[str, list[dict[str, Any]]], list[str]] | None = None
    # When the hooks call a local model (e.g. Ollama) the data-sovereignty
    # gate can be relaxed; cloud hooks never see chunks outside cloud_safe_scopes.
    hooks_run_locally: bool = False
    cloud_safe_scopes: tuple[str, ...] = ("public", "internal")
    rerank_candidate_limit: int = 20
    # Auto uses the verified bundled/installed multilingual Model2Vec int8
    # semantic vector. Hash-96 is only a visible degraded fallback when no
    # verified asset exists. Neither path downloads a model or calls a server
    # embedding API at runtime.
    vector_adapter: VectorAdapter | None = None
    vector_adapter_name: str = "auto"
    local_model_path: Path | str | None = None


class OntologyRuntime:
    def __init__(self, config: RuntimeConfig | None = None):
        self.config = config or RuntimeConfig()
        self.db_path = Path(self.config.db_path)
        self.parser_registry = SourceParserRegistry()
        self.vector_adapter = self.config.vector_adapter or select_vector_adapter(
            self.config.vector_adapter_name,
            model_path=self.config.local_model_path,
        )
        self.fts_tokenizer = "unicode61"
        self._expansion_cache: dict[str, list[str]] = {}
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
                  privacy_scope TEXT NOT NULL DEFAULT 'private',
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
                  agent_id TEXT NOT NULL DEFAULT '',
                  memory_kind TEXT NOT NULL DEFAULT 'candidate',
                  tags_json TEXT NOT NULL DEFAULT '[]',
                  salience REAL NOT NULL DEFAULT 0.5,
                  privacy_scope TEXT NOT NULL DEFAULT 'internal',
                  source_memory_id TEXT,
                  source_updated_at TEXT,
                  embedding_adapter TEXT NOT NULL DEFAULT '',
                  embedding_dimensions INTEGER NOT NULL DEFAULT 0,
                  embedding_json TEXT NOT NULL DEFAULT '[]',
                  embedding_content_hash TEXT NOT NULL DEFAULT '',
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

                -- Memory Relation Graph: typed edges between candidate tickets so a
                -- new learning never silently overwrites an older one. similar_to is
                -- machine-detected near-duplication; supersedes/contradicts are
                -- curator decisions that make replacement and conflict structural.
                CREATE TABLE IF NOT EXISTS memory_links (
                  link_id TEXT PRIMARY KEY,
                  from_ticket TEXT NOT NULL REFERENCES memory_candidates(ticket_id) ON DELETE CASCADE,
                  to_ticket TEXT NOT NULL REFERENCES memory_candidates(ticket_id) ON DELETE CASCADE,
                  link_type TEXT NOT NULL,
                  score REAL NOT NULL,
                  reason TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(from_ticket, to_ticket, link_type)
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

                -- Experience Relation Graph (agent-scoped, conversational).
                -- The document ingest path builds entities/relations from
                -- Title-Case declarative text; conversational experience never
                -- did, so recall was pure vector with no multi-hop. These three
                -- tables give the experience surface a real, rebuildable graph:
                -- entity nodes, ticket->entity mentions, and typed edges between
                -- entities (deterministic co_occurs_with by default, upgradable
                -- to LLM-typed predicates at curation time). Extraction happens at
                -- write; retrieval traversal stays pure-local (no LLM at query).
                CREATE TABLE IF NOT EXISTS experience_entities (
                  agent_id TEXT NOT NULL,
                  entity_key TEXT NOT NULL,
                  canonical TEXT NOT NULL,
                  entity_type TEXT NOT NULL DEFAULT 'concept',
                  mention_count INTEGER NOT NULL DEFAULT 0,
                  first_seen TEXT NOT NULL,
                  last_seen TEXT NOT NULL,
                  PRIMARY KEY (agent_id, entity_key)
                );

                CREATE TABLE IF NOT EXISTS experience_mentions (
                  agent_id TEXT NOT NULL,
                  ticket_id TEXT NOT NULL REFERENCES memory_candidates(ticket_id) ON DELETE CASCADE,
                  entity_key TEXT NOT NULL,
                  weight REAL NOT NULL DEFAULT 1.0,
                  PRIMARY KEY (agent_id, ticket_id, entity_key)
                );
                CREATE INDEX IF NOT EXISTS idx_exp_mentions_entity ON experience_mentions(agent_id, entity_key);

                CREATE TABLE IF NOT EXISTS experience_relations (
                  agent_id TEXT NOT NULL,
                  src_key TEXT NOT NULL,
                  dst_key TEXT NOT NULL,
                  predicate TEXT NOT NULL DEFAULT 'co_occurs_with',
                  directed INTEGER NOT NULL DEFAULT 0,
                  confidence REAL NOT NULL DEFAULT 0.3,
                  extractor TEXT NOT NULL DEFAULT 'cooccur',
                  cooccur_count INTEGER NOT NULL DEFAULT 1,
                  valid_from TEXT,
                  valid_to TEXT,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY (agent_id, src_key, dst_key, predicate)
                );
                CREATE INDEX IF NOT EXISTS idx_exp_relations_src ON experience_relations(agent_id, src_key);
                """
            )
            self._ensure_memory_candidate_columns(conn)
            self._ensure_relation_privacy_scope(conn)
            self.fts_tokenizer = self._ensure_fts_table(conn)
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            vector_config = vector_adapter_metadata(self.vector_adapter)
            needs_reindex = bool(applied) and max(applied) < SCHEMA_VERSION
            stale_vector_rows = [
                row
                for row in conn.execute("SELECT name, config_json FROM runtime_adapters WHERE kind = 'vector'")
                if row["name"] != self.vector_adapter.name
                or json_loads(row["config_json"], {}).get("dimensions") != vector_config.get("dimensions")
                or json_loads(row["config_json"], {}).get("identity") not in {None, vector_config.get("identity")}
            ]
            if needs_reindex or stale_vector_rows:
                # Tokenizer/schema upgrades and adapter switches invalidate
                # stored document and experience vectors.
                self._reindex_chunks(conn)
                self._reindex_memory_candidates(conn)
                conn.execute(
                    "DELETE FROM runtime_adapters WHERE kind = 'vector' AND name != ?",
                    (self.vector_adapter.name,),
                )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )
            self._register_vector_adapter(conn)
            conn.execute(
                "INSERT OR REPLACE INTO runtime_adapters(name, kind, status, config_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("chunk_fts", "fts", "available", json_dumps({"tokenizer": self.fts_tokenizer}), utc_now()),
            )
            for name, status in self.parser_registry.adapter_statuses():
                conn.execute(
                    "INSERT OR REPLACE INTO runtime_adapters(name, kind, status, config_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (name, "parser", status, "{}", utc_now()),
                )

    @staticmethod
    def _ensure_memory_candidate_columns(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(memory_candidates)")}
        additions = {
            "agent_id": "TEXT NOT NULL DEFAULT ''",
            "memory_kind": "TEXT NOT NULL DEFAULT 'candidate'",
            "tags_json": "TEXT NOT NULL DEFAULT '[]'",
            "salience": "REAL NOT NULL DEFAULT 0.5",
            "privacy_scope": "TEXT NOT NULL DEFAULT 'internal'",
            "source_memory_id": "TEXT",
            "source_updated_at": "TEXT",
            "embedding_adapter": "TEXT NOT NULL DEFAULT ''",
            "embedding_dimensions": "INTEGER NOT NULL DEFAULT 0",
            "embedding_json": "TEXT NOT NULL DEFAULT '[]'",
            "embedding_content_hash": "TEXT NOT NULL DEFAULT ''",
        }
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE memory_candidates ADD COLUMN {name} {ddl}")

    @staticmethod
    def _ensure_relation_privacy_scope(conn: sqlite3.Connection) -> None:
        """Add and safely backfill relation scope for pre-v4 databases.

        The additive column defaults to ``private`` so a crash, corrupt legacy
        row, or missing provenance can never turn unknown relation data into a
        public/internal result. Only rows whose evidence chunk and source agree
        on a valid scope are backfilled to that proven scope.
        """

        existing = {row["name"] for row in conn.execute("PRAGMA table_info(relations)")}
        if "privacy_scope" not in existing:
            conn.execute("ALTER TABLE relations ADD COLUMN privacy_scope TEXT NOT NULL DEFAULT 'private'")
            conn.execute(
                """
                UPDATE relations
                SET privacy_scope = (
                  SELECT c.privacy_scope
                  FROM chunks c
                  JOIN sources s ON s.source_id = c.source_id
                  WHERE c.chunk_id = relations.evidence_chunk_id
                    AND c.source_id = relations.source_id
                    AND c.privacy_scope = s.privacy_scope
                    AND c.privacy_scope IN ('public', 'internal', 'private')
                )
                WHERE EXISTS (
                  SELECT 1
                  FROM chunks c
                  JOIN sources s ON s.source_id = c.source_id
                  WHERE c.chunk_id = relations.evidence_chunk_id
                    AND c.source_id = relations.source_id
                    AND c.privacy_scope = s.privacy_scope
                    AND c.privacy_scope IN ('public', 'internal', 'private')
                )
                """
            )

        # Imported or manually edited rows can still carry an invalid or
        # provenance-mismatched scope. Fail closed on every startup rather than
        # trusting an unproved label.
        conn.execute(
            """
            UPDATE relations
            SET privacy_scope = 'private'
            WHERE privacy_scope NOT IN ('public', 'internal', 'private')
               OR NOT EXISTS (
                 SELECT 1
                 FROM chunks c
                 JOIN sources s ON s.source_id = c.source_id
                 WHERE c.chunk_id = relations.evidence_chunk_id
                   AND c.source_id = relations.source_id
                   AND c.privacy_scope = relations.privacy_scope
                   AND s.privacy_scope = relations.privacy_scope
               )
            """
        )

    def _register_vector_adapter(self, conn: sqlite3.Connection) -> None:
        metadata = vector_adapter_metadata(self.vector_adapter)
        conn.execute(
            """
            INSERT OR REPLACE INTO runtime_adapters(name, kind, status, config_json, updated_at)
            VALUES (?, 'vector', ?, ?, ?)
            """,
            (self.vector_adapter.name, self.vector_adapter.status, json_dumps(metadata), utc_now()),
        )

    def _ensure_fts_table(self, conn: sqlite3.Connection) -> str:
        desired = "trigram" if self._fts_trigram_supported(conn) else "unicode61"
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'chunk_fts'"
        ).fetchone()
        ddl = f"CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, text, tokenize='{desired}')"
        if row is None:
            conn.execute(ddl)
            return desired
        if f"tokenize='{desired}'" in (row["sql"] or ""):
            return desired
        conn.execute("DROP TABLE chunk_fts")
        conn.execute(ddl)
        self._rebuild_fts_rows(conn)
        return desired

    def _fts_trigram_supported(self, conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x, tokenize='trigram')")
            supported = True
        except sqlite3.OperationalError:
            supported = False
        try:
            conn.execute("DROP TABLE IF EXISTS _fts_probe")
        except sqlite3.OperationalError:
            pass
        return supported

    def _rebuild_fts_rows(self, conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM chunk_fts")
        rows = conn.execute("SELECT chunk_id, text FROM chunks").fetchall()
        for row in rows:
            conn.execute("INSERT INTO chunk_fts(chunk_id, text) VALUES (?, ?)", (row["chunk_id"], row["text"]))

    def _reindex_chunks(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT chunk_id, text FROM chunks").fetchall()
        now = utc_now()
        for row in rows:
            conn.execute(
                "UPDATE chunks SET vector_json = ?, updated_at = ? WHERE chunk_id = ?",
                (json_dumps(self.vector_adapter.embed(row["text"])), now, row["chunk_id"]),
            )
        self._rebuild_fts_rows(conn)

    def _reindex_memory_candidates(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT ticket_id, candidate_text FROM memory_candidates").fetchall()
        now = utc_now()
        for row in rows:
            text = row["candidate_text"] or ""
            vector = self.vector_adapter.embed(text)
            conn.execute(
                """
                UPDATE memory_candidates
                SET embedding_adapter = ?, embedding_dimensions = ?, embedding_json = ?,
                    embedding_content_hash = ?, updated_at = ?
                WHERE ticket_id = ?
                """,
                (
                    self.vector_adapter.name,
                    len(vector),
                    json_dumps(vector),
                    content_hash(text.encode("utf-8")),
                    now,
                    row["ticket_id"],
                ),
            )
        self._register_vector_adapter(conn)

    def ingest_path(self, path: str | Path, access_scope: str = "internal", parent_source_id: str | None = None) -> dict[str, Any]:
        root = Path(path)
        files, skipped_sources = self._bounded_source_files(root)
        summary = {
            "db_path": str(self.db_path),
            "sources": [],
            "chunks_written": 0,
            "entities_written": 0,
            "relations_written": 0,
            "idempotent_skips": 0,
            "bytes_read": 0,
            "skipped_sources": skipped_sources,
        }
        with closing(self.connect()) as conn, conn:
            for source_path in files:
                result = self._ingest_file(conn, source_path, access_scope, parent_source_id)
                summary["bytes_read"] += result["bytes_read"]
                if summary["bytes_read"] > MAX_INGEST_TOTAL_BYTES:
                    raise ValueError(f"ontology ingest exceeds {MAX_INGEST_TOTAL_BYTES} total bytes")
                summary["sources"].append(result["source"])
                summary["chunks_written"] += result["chunks_written"]
                summary["entities_written"] += result["entities_written"]
                summary["relations_written"] += result["relations_written"]
                summary["idempotent_skips"] += 1 if result["unchanged"] else 0
        return summary

    def _bounded_source_files(self, root: Path) -> tuple[list[Path], list[dict[str, str]]]:
        """Enumerate regular files without following links or unbounded trees."""

        skipped: list[dict[str, str]] = []
        if root.is_symlink():
            raise ValueError(f"ontology ingest refuses a symlink source: {root}")
        if root.is_file():
            info = root.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"ontology ingest requires a regular file: {root}")
            if info.st_size > MAX_INGEST_FILE_BYTES:
                raise ValueError(f"ontology source exceeds {MAX_INGEST_FILE_BYTES} bytes: {root.name}")
            return [root], skipped
        if not root.is_dir():
            return [], skipped

        maximum_files = (
            MAX_ONTOLOGY_INBOX_FILES
            if root.name == "ontology-inbox" and root.parent.name == ".agentlas"
            else MAX_INGEST_FILES
        )
        files: list[Path] = []
        total_bytes = 0
        stop = False
        for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            relative = current_path.relative_to(root)
            depth = 0 if relative == Path(".") else len(relative.parts)
            allowed_dirs: list[str] = []
            for name in sorted(dirnames):
                candidate = current_path / name
                if name.startswith(".") or candidate.is_symlink() or depth + 1 > MAX_INGEST_DEPTH:
                    skipped.append({"path": str(candidate.relative_to(root)), "reason": "directory_not_allowed"})
                    continue
                allowed_dirs.append(name)
            dirnames[:] = allowed_dirs
            for name in sorted(filenames):
                candidate = current_path / name
                rel = str(candidate.relative_to(root))
                if name.startswith("."):
                    skipped.append({"path": rel, "reason": "hidden_file"})
                    continue
                try:
                    info = candidate.lstat()
                except OSError:
                    skipped.append({"path": rel, "reason": "unreadable"})
                    continue
                if not stat.S_ISREG(info.st_mode):
                    skipped.append({"path": rel, "reason": "non_regular_or_symlink"})
                    continue
                if info.st_size > MAX_INGEST_FILE_BYTES:
                    skipped.append({"path": rel, "reason": "file_too_large"})
                    continue
                if len(files) >= maximum_files:
                    skipped.append({"path": rel, "reason": "file_count_limit"})
                    stop = True
                    break
                if total_bytes + info.st_size > MAX_INGEST_TOTAL_BYTES:
                    skipped.append({"path": rel, "reason": "total_byte_limit"})
                    stop = True
                    break
                files.append(candidate)
                total_bytes += info.st_size
            if stop:
                break
        return files, skipped

    def query(
        self,
        question: str,
        agent_id: str | None = None,
        allowed_scopes: Iterable[str] | None = None,
        limit: int = 5,
        *,
        record_memory: bool = True,
        experience_token_budget: int = DEFAULT_EXPERIENCE_TOKEN_BUDGET,
        experience_top_k: int = DEFAULT_EXPERIENCE_TOP_K,
    ) -> dict[str, Any]:
        requested_scopes = list(allowed_scopes) if allowed_scopes is not None else None
        document_scopes = requested_scopes or ["public", "internal"]
        # An agent's dedicated experience projection is private by default and
        # already exact-agent isolated. Project document privacy keeps the
        # long-standing explicit opt-in boundary above.
        experience_scopes = requested_scopes or (["public", "internal", "private"] if agent_id else ["public", "internal"])
        with closing(self.connect()) as conn, conn:
            chunks = self._search_chunks(conn, question, document_scopes, limit)
            entities = self._related_entities(conn, question, chunks, document_scopes)
            relations = self._relation_edges(conn, entities, chunks, document_scopes)
            experience = (
                self._query_experience(
                    conn,
                    question=question,
                    agent_id=agent_id,
                    allowed_scopes=experience_scopes,
                    token_budget=experience_token_budget,
                    top_k=experience_top_k,
                )
                if agent_id
                else self._empty_experience_result(question, agent_id, experience_token_budget)
            )
            candidates = self._create_memory_candidates(conn, question, chunks, relations) if record_memory else []
            working_memory: list[dict[str, Any]] = []
            if agent_id and record_memory:
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
            "experience_memory": experience,
            "memory_candidate_suggestions": candidates,
            "working_memory": working_memory,
            "vector_adapter": vector_adapter_metadata(self.vector_adapter),
            "search": {
                "fts_tokenizer": self.fts_tokenizer,
                "fusion": "rrf",
                "expanded_queries": self._expansion_cache.get(question, []),
                "rerank_hook_enabled": self.config.rerank_hook is not None,
                "hooks_run_locally": self.config.hooks_run_locally,
                "record_memory": record_memory,
            },
        }

    def ingest_experience(
        self,
        *,
        agent_id: str,
        summary: str,
        tags: Iterable[str] | None = None,
        salience: float = 0.5,
        privacy_scope: str = "private",
        status: str = "active",
        memory_kind: str = "experience",
        source_memory_id: str | None = None,
        source_updated_at: str | None = None,
        source_refs: list[dict[str, Any]] | None = None,
        suggested_scope: str = "agent_repo",
        reason: str = "Rebuildable agent experience projection supplied by its owning runtime.",
        similar_threshold: float = 0.72,
    ) -> dict[str, Any]:
        """Upsert one rebuildable, agent-scoped experience projection.

        This does not bypass the durable-memory guard: the owning runtime stays
        authoritative and this row is a local retrieval projection with
        ``durable_write_enabled=0``.
        """

        agent = agent_id.strip()
        text = " ".join(summary.split())
        if not agent:
            raise ValueError("agent_id is required")
        if not text:
            raise ValueError("summary is required")
        if privacy_scope not in {"public", "internal", "private"}:
            raise ValueError("privacy_scope must be public, internal, or private")
        if not status.strip():
            raise ValueError("status is required")
        if not 0.0 < similar_threshold <= 1.0:
            raise ValueError("similar_threshold must be in (0, 1]")
        normalized_tags = list(
            dict.fromkeys(
                value
                for value in (" ".join(str(tag).split()).lower() for tag in (tags or []))
                if value
            )
        )
        stable_source_id = (source_memory_id or "").strip() or content_hash(text.encode("utf-8"))
        idempotency_key = stable_hash(f"experience:{agent}:{stable_source_id}")
        ticket_id = stable_hash(f"experience-ticket:{idempotency_key}")
        vector = self.vector_adapter.embed(text)
        now = utc_now()
        with closing(self.connect()) as conn, conn:
            self._register_vector_adapter(conn)
            conn.execute(
                """
                INSERT INTO memory_candidates(
                  ticket_id, idempotency_key, query, candidate_text, source_refs_json,
                  reason, confidence, risk, expiry, suggested_scope, status,
                  durable_write_enabled, agent_id, memory_kind, tags_json, salience,
                  privacy_scope, source_memory_id, source_updated_at,
                  embedding_adapter, embedding_dimensions, embedding_json,
                  embedding_content_hash, created_at, updated_at
                ) VALUES (?, ?, '', ?, ?, ?, ?, 'projection', NULL, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticket_id) DO UPDATE SET
                  candidate_text = excluded.candidate_text,
                  source_refs_json = excluded.source_refs_json,
                  reason = excluded.reason,
                  confidence = excluded.confidence,
                  suggested_scope = excluded.suggested_scope,
                  status = excluded.status,
                  agent_id = excluded.agent_id,
                  memory_kind = excluded.memory_kind,
                  tags_json = excluded.tags_json,
                  salience = excluded.salience,
                  privacy_scope = excluded.privacy_scope,
                  source_memory_id = excluded.source_memory_id,
                  source_updated_at = excluded.source_updated_at,
                  embedding_adapter = excluded.embedding_adapter,
                  embedding_dimensions = excluded.embedding_dimensions,
                  embedding_json = excluded.embedding_json,
                  embedding_content_hash = excluded.embedding_content_hash,
                  updated_at = excluded.updated_at
                """,
                (
                    ticket_id,
                    idempotency_key,
                    text,
                    json_dumps(source_refs or []),
                    reason,
                    clamp(salience),
                    suggested_scope,
                    status.strip(),
                    agent,
                    memory_kind.strip() or "experience",
                    json_dumps(normalized_tags),
                    clamp(salience),
                    privacy_scope,
                    stable_source_id,
                    source_updated_at,
                    self.vector_adapter.name,
                    len(vector),
                    json_dumps(vector),
                    content_hash(text.encode("utf-8")),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM memory_candidates WHERE ticket_id = ?", (ticket_id,)).fetchone()
            links = self._link_semantically_similar(
                conn,
                ticket_id=ticket_id,
                agent_id=agent,
                privacy_scope=privacy_scope,
                vector=vector,
                threshold=similar_threshold,
            )
            # The experience relation graph is dormant substrate: benchmarked as no
            # retrieval-recall lift, so it is disabled by default and adds no
            # write-time cost in production. Enable with AGENTLAS_EXPERIENCE_GRAPH=1
            # (same flag that gates the multi-hop retrieval channel).
            entities_written = 0
            if os.environ.get("AGENTLAS_EXPERIENCE_GRAPH", "0") == "1":
                entities_written = self._write_experience_graph(
                    conn, agent_id=agent, ticket_id=ticket_id, text=text, now=now
                )
        return {
            "experience": self._memory_candidate_row(row),
            "similar_links": links,
            "graph_entities": entities_written,
        }

    def _write_experience_graph(
        self, conn: sqlite3.Connection, *, agent_id: str, ticket_id: str, text: str, now: str
    ) -> int:
        """Build the agent-scoped experience relation graph at write-time.

        Idempotent per ticket: a re-ingest of the same ticket does not double-count
        entity mentions or co-occurrence weights. Retrieval stays pure-local — this
        precomputes the edges the multi-hop traversal later walks with no model.
        """
        already = conn.execute(
            "SELECT 1 FROM experience_mentions WHERE agent_id = ? AND ticket_id = ? LIMIT 1",
            (agent_id, ticket_id),
        ).fetchone()
        if already:
            return 0
        entities = extract_experience_entities(text)
        if not entities:
            return 0
        for key, canonical, entity_type in entities:
            conn.execute(
                """
                INSERT INTO experience_entities(
                  agent_id, entity_key, canonical, entity_type, mention_count, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(agent_id, entity_key) DO UPDATE SET
                  mention_count = experience_entities.mention_count + 1,
                  last_seen = excluded.last_seen,
                  canonical = CASE
                    WHEN length(excluded.canonical) > length(experience_entities.canonical)
                    THEN excluded.canonical ELSE experience_entities.canonical END
                """,
                (agent_id, key, canonical, entity_type, now, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO experience_mentions(agent_id, ticket_id, entity_key, weight) VALUES (?, ?, ?, 1.0)",
                (agent_id, ticket_id, key),
            )
        keys = sorted({key for key, _canonical, _type in entities})
        for index, src in enumerate(keys):
            for dst in keys[index + 1 :]:
                conn.execute(
                    """
                    INSERT INTO experience_relations(
                      agent_id, src_key, dst_key, predicate, directed, confidence, extractor, cooccur_count, created_at
                    ) VALUES (?, ?, ?, 'co_occurs_with', 0, 0.3, 'cooccur', 1, ?)
                    ON CONFLICT(agent_id, src_key, dst_key, predicate) DO UPDATE SET
                      cooccur_count = experience_relations.cooccur_count + 1,
                      confidence = MIN(0.9, experience_relations.confidence + 0.05)
                    """,
                    (agent_id, src, dst, now),
                )
        return len(entities)

    def augment_experience_graph_llm(
        self,
        *,
        agent_id: str,
        ticket_id: str,
        entities: Iterable[tuple[str, str]],
        relations: Iterable[tuple[str, str, str]],
        confidence: float = 0.9,
    ) -> dict[str, int]:
        """Overlay LLM-extracted entities + TYPED relations onto an existing
        experience ticket. Write-time only (the model runs during curation, which
        already holds a handle); retrieval never calls a model. Entities are added as
        mentions (higher-recall, coref-resolved than the deterministic pass); typed
        relations become directed ``experience_relations`` edges with ``extractor='llm'``
        and a real predicate, which the multi-hop signal traverses at higher weight
        than co-occurrence. Idempotent per (agent, ticket) for the LLM layer.
        """
        agent = agent_id.strip()
        now = utc_now()
        written_entities = 0
        written_relations = 0
        with closing(self.connect()) as conn, conn:
            for canonical, entity_type in entities:
                key = normalized_key(canonical)
                if not key or len(key) < 2:
                    continue
                conn.execute(
                    """
                    INSERT INTO experience_entities(
                      agent_id, entity_key, canonical, entity_type, mention_count, first_seen, last_seen
                    ) VALUES (?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(agent_id, entity_key) DO UPDATE SET
                      last_seen = excluded.last_seen,
                      entity_type = excluded.entity_type,
                      canonical = CASE WHEN length(excluded.canonical) > length(experience_entities.canonical)
                                       THEN excluded.canonical ELSE experience_entities.canonical END
                    """,
                    (agent, key, normalize_name(canonical), (entity_type or "concept").strip().lower(), now, now),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO experience_mentions(agent_id, ticket_id, entity_key, weight) VALUES (?, ?, ?, 1.5)",
                    (agent, ticket_id, key),
                )
                written_entities += 1
            for subject, predicate, obj in relations:
                src_key = normalized_key(subject)
                dst_key = normalized_key(obj)
                predicate_norm = normalized_key(predicate).replace(" ", "_") or "related_to"
                if not src_key or not dst_key or src_key == dst_key:
                    continue
                conn.execute(
                    """
                    INSERT INTO experience_relations(
                      agent_id, src_key, dst_key, predicate, directed, confidence, extractor, cooccur_count, created_at
                    ) VALUES (?, ?, ?, ?, 1, ?, 'llm', 1, ?)
                    ON CONFLICT(agent_id, src_key, dst_key, predicate) DO UPDATE SET
                      confidence = MAX(experience_relations.confidence, excluded.confidence),
                      extractor = 'llm'
                    """,
                    (agent, src_key, dst_key, predicate_norm[:60], clamp(confidence), now),
                )
                written_relations += 1
        return {"entities": written_entities, "relations": written_relations}

    def _experience_graph_signal(
        self,
        conn: sqlite3.Connection,
        *,
        agent_id: str,
        question: str,
        seed_tickets: list[str],
    ) -> dict[str, float]:
        """Score every experience memory by how strongly it is bridged — through
        shared entities — to the question and to the strongest direct hits. Returned
        as a ``{ticket: signal}`` map for fusion as a third RRF channel alongside
        lexical and vector. Pure-local (no model call).

        The IDF weight is load-bearing: a rare shared entity (the question's specific
        subject) dominates common chatter, so the genuinely connected session ranks
        first among bridged candidates instead of drowning in noise.

        DEFAULT OFF. Measured on LongMemEval (500) and LoCoMo (1,536 QA), a
        deterministic co-occurrence graph gives NO retrieval-recall lift over the
        existing lexical+vector RRF — flat-to-negative at every fusion weight,
        because vector recall already captures the connectivity these benchmarks
        reward. The graph is still *built* at write-time (it fixes the real
        "half-graph" defect — conversational memory had entities but zero relations —
        and is the substrate for the LLM-typed-relation channel, where the research
        expects the actual multi-hop/explainability win). This retrieval fusion is
        retained, opt-in via AGENTLAS_EXPERIENCE_GRAPH=1, for that typed-relation
        follow-up; enabling it with today's untyped co-occurrence edges regresses
        recall, so it stays off in production.
        """
        if os.environ.get("AGENTLAS_EXPERIENCE_GRAPH", "0") != "1":
            return {}
        if not conn.execute(
            "SELECT 1 FROM experience_mentions WHERE agent_id = ? LIMIT 1", (agent_id,)
        ).fetchone():
            return {}
        import math

        total_mem = (
            conn.execute(
                "SELECT COUNT(DISTINCT ticket_id) FROM experience_mentions WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()[0]
            or 1
        )
        # Seeds: the question's own entities (strong anchor, weight 2) plus the
        # entities of the top few direct hits (a hop may start from a session we
        # already trust, weight 1).
        seed_weight: dict[str, float] = {}
        for key, _canonical, _type in extract_experience_entities(question):
            seed_weight[key] = max(seed_weight.get(key, 0.0), 2.0)
        if seed_tickets:
            marks = ",".join("?" * len(seed_tickets))
            for row in conn.execute(
                f"SELECT DISTINCT entity_key FROM experience_mentions WHERE agent_id = ? AND ticket_id IN ({marks})",
                (agent_id, *seed_tickets),
            ):
                key = row["entity_key"]
                seed_weight[key] = max(seed_weight.get(key, 0.0), 1.0)
        # Typed-relation hop: pull in entities linked to a seed by an LLM-typed edge
        # (precise and directional, unlike symmetric co-occurrence). No-op until the
        # LLM channel populates typed relations; this is where a typed graph earns
        # its multi-hop lift that untyped co-occurrence could not.
        if seed_weight:
            seed_keys = list(seed_weight.keys())
            marks = ",".join("?" * len(seed_keys))
            for row in conn.execute(
                f"""SELECT src_key, dst_key, confidence FROM experience_relations
                    WHERE agent_id = ? AND extractor = 'llm'
                      AND (src_key IN ({marks}) OR dst_key IN ({marks}))""",
                (agent_id, *seed_keys, *seed_keys),
            ):
                hop = 0.7 * float(row["confidence"] or 0.9)
                for endpoint in (row["src_key"], row["dst_key"]):
                    if endpoint not in seed_weight:
                        seed_weight[endpoint] = max(seed_weight.get(endpoint, 0.0), hop)
        if not seed_weight:
            return {}
        # IDF per seed; drop hub entities (mentioned in a large fraction of
        # memories) that would bridge everything to everything.
        hub_cap = max(3, int(total_mem * 0.5))
        idf: dict[str, float] = {}
        for key in list(seed_weight):
            document_frequency = conn.execute(
                "SELECT COUNT(*) FROM experience_mentions WHERE agent_id = ? AND entity_key = ?",
                (agent_id, key),
            ).fetchone()[0]
            if 0 < document_frequency <= hub_cap:
                idf[key] = math.log(1.0 + total_mem / document_frequency)
            else:
                del seed_weight[key]
        if not seed_weight:
            return {}
        marks = ",".join("?" * len(seed_weight))
        signal: dict[str, float] = {}
        for row in conn.execute(
            f"SELECT ticket_id, entity_key FROM experience_mentions WHERE agent_id = ? AND entity_key IN ({marks})",
            (agent_id, *seed_weight.keys()),
        ):
            ticket, key = row["ticket_id"], row["entity_key"]
            signal[ticket] = signal.get(ticket, 0.0) + seed_weight[key] * idf[key]
        return signal

    def query_experience(
        self,
        question: str,
        *,
        agent_id: str,
        allowed_scopes: Iterable[str] | None = None,
        token_budget: int = DEFAULT_EXPERIENCE_TOKEN_BUDGET,
        top_k: int = DEFAULT_EXPERIENCE_TOP_K,
    ) -> dict[str, Any]:
        scopes = list(allowed_scopes or ["public", "internal", "private"])
        with closing(self.connect()) as conn:
            return self._query_experience(
                conn,
                question=question,
                agent_id=agent_id,
                allowed_scopes=scopes,
                token_budget=token_budget,
                top_k=top_k,
            )

    def _query_experience(
        self,
        conn: sqlite3.Connection,
        *,
        question: str,
        agent_id: str,
        allowed_scopes: list[str],
        token_budget: int,
        top_k: int,
    ) -> dict[str, Any]:
        if token_budget < 1:
            raise ValueError("token_budget must be at least 1")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        if not allowed_scopes:
            return self._empty_experience_result(question, agent_id, token_budget)
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        status_marks = ", ".join(["?"] * len(ACTIVE_EXPERIENCE_STATUSES))
        rows = conn.execute(
            f"""
            SELECT m.*
            FROM memory_candidates m
            WHERE m.agent_id = ?
              AND m.memory_kind != 'candidate'
              AND m.privacy_scope IN ({scope_marks})
              AND m.status IN ({status_marks})
              AND (m.expiry IS NULL OR m.expiry > ?)
              AND NOT EXISTS (
                SELECT 1
                FROM memory_links ml
                JOIN memory_candidates newer ON newer.ticket_id = ml.from_ticket
                WHERE ml.to_ticket = m.ticket_id
                  AND ml.link_type = 'supersedes'
                  AND newer.agent_id = m.agent_id
                  AND newer.privacy_scope = m.privacy_scope
                  AND newer.status IN ({status_marks})
                  AND (newer.expiry IS NULL OR newer.expiry > ?)
              )
            ORDER BY m.updated_at DESC, m.ticket_id
            """,
            (
                agent_id,
                *allowed_scopes,
                *ACTIVE_EXPERIENCE_STATUSES,
                utc_now(),
                *ACTIVE_EXPERIENCE_STATUSES,
                utc_now(),
            ),
        ).fetchall()
        if not rows:
            return self._empty_experience_result(question, agent_id, token_budget)

        query_tokens = set(tokenize(question))
        query_vector = self.vector_adapter.embed(question)
        scored: list[dict[str, Any]] = []
        for row in rows:
            item = self._memory_candidate_row(row)
            searchable = f"{item['candidate_text']} {' '.join(item['tags'])}"
            memory_tokens = set(tokenize(searchable))
            lexical = len(query_tokens & memory_tokens) / len(query_tokens) if query_tokens else 0.0
            stored_vector = json_loads(row["embedding_json"], [])
            stored_adapter = row["embedding_adapter"]
            if not stored_vector and not stored_adapter:
                # Legacy rows remain readable without mutating during recall.
                stored_vector = self.vector_adapter.embed(row["candidate_text"])
                stored_adapter = self.vector_adapter.name
            compatible = self._vector_adapter_matches(stored_adapter) and len(stored_vector) == len(query_vector)
            semantic = max(0.0, cosine_similarity(query_vector, stored_vector)) if compatible else 0.0
            item["lexical_score"] = round(lexical, 6)
            item["vector_score"] = round(semantic, 6)
            item["token_estimate"] = estimate_tokens(item["candidate_text"])
            scored.append(item)
        best_semantic = max((item["vector_score"] for item in scored), default=0.0)
        semantic_floor = self._minimum_vector_score(MIN_EXPERIENCE_VECTOR_SCORE, question)
        all_scored = scored
        floor_passed = [
            item
            for item in all_scored
            if item["lexical_score"] > 0.0
            or (
                item["vector_score"] >= semantic_floor
                and item["vector_score"] >= best_semantic * VECTOR_RELATIVE_FLOOR
            )
        ]

        # Graph channel (multi-hop): seed from the question plus the top vector hits,
        # then score every memory by IDF-weighted entity bridging. Fused as a third
        # RRF channel below — a memory the direct-similarity floor dropped but that
        # is strongly bridged to a trusted hit can still surface, without the scale
        # problems of injecting an absolute score. When the graph is off or empty the
        # fusion degrades exactly to the original two-channel lexical+vector RRF.
        vector_seed = sorted(floor_passed, key=lambda value: value["vector_score"], reverse=True)[:3]
        graph_signal = self._experience_graph_signal(
            conn,
            agent_id=agent_id,
            question=question,
            seed_tickets=[item["ticket_id"] for item in vector_seed],
        )
        scored = list(floor_passed)
        seen_tickets = {item["ticket_id"] for item in scored}
        for item in all_scored:
            if item["ticket_id"] in graph_signal and item["ticket_id"] not in seen_tickets:
                scored.append(item)
                seen_tickets.add(item["ticket_id"])
        if not scored:
            result = self._empty_experience_result(question, agent_id, token_budget)
            result["eligible_count"] = len(rows)
            return result

        lexical_order = [
            item["ticket_id"]
            for item in sorted(scored, key=lambda value: (value["lexical_score"], value["updated_at"]), reverse=True)
            if item["lexical_score"] > 0.0
        ]
        vector_order = [
            item["ticket_id"]
            for item in sorted(scored, key=lambda value: (value["vector_score"], value["updated_at"]), reverse=True)
            if item["vector_score"] >= semantic_floor
        ]
        graph_order = [
            ticket for ticket, _signal in sorted(graph_signal.items(), key=lambda kv: kv[1], reverse=True)
        ]
        lexical_rank = {ticket: index for index, ticket in enumerate(lexical_order)}
        vector_rank = {ticket: index for index, ticket in enumerate(vector_order)}
        graph_rank = {ticket: index for index, ticket in enumerate(graph_order)}
        graph_weight = float(os.environ.get("AGENTLAS_EXPERIENCE_GRAPH_WEIGHT", "1.0")) if graph_signal else 0.0
        max_rrf = (2.0 + graph_weight) / RRF_K
        for item in scored:
            ticket = item["ticket_id"]
            rrf = (
                1.0 / (RRF_K + lexical_rank.get(ticket, RRF_MISSING_RANK))
                + 1.0 / (RRF_K + vector_rank.get(ticket, RRF_MISSING_RANK))
                + graph_weight / (RRF_K + graph_rank.get(ticket, RRF_MISSING_RANK))
            )
            normalized_rrf = min(1.0, rrf / max_rrf)
            item["rrf_score"] = round(rrf, 6)
            if ticket in graph_signal:
                item["graph_signal"] = round(graph_signal[ticket], 4)
            item["score"] = round((normalized_rrf * 0.85) + (clamp(float(item["salience"])) * 0.15), 6)
        ranked = sorted(
            scored,
            key=lambda item: (item["score"], item["vector_score"], item["updated_at"]),
            reverse=True,
        )
        total_tokens = sum(item["token_estimate"] for item in ranked)
        if total_tokens <= token_budget:
            selected = ranked
            mode = "all_relevant"
        else:
            selected = []
            used = 0
            for item in ranked:
                if len(selected) >= top_k:
                    break
                size = int(item["token_estimate"])
                if used + size <= token_budget:
                    selected.append(item)
                    used += size
            if not selected:
                first = dict(ranked[0])
                first["candidate_text"] = self._truncate_to_token_budget(first["candidate_text"], token_budget)
                first["token_estimate"] = estimate_tokens(first["candidate_text"])
                selected = [first]
            mode = "hybrid_top_k"
        self._attach_memory_links(conn, selected)
        return {
            "query": question,
            "agent_id": agent_id,
            "mode": mode,
            "token_budget": token_budget,
            "total_relevant_tokens": total_tokens,
            "eligible_count": len(rows),
            "relevant_count": len(ranked),
            "selected_count": len(selected),
            "items": selected,
            "governance": {
                "agent_isolation": "exact",
                "allowed_scopes": allowed_scopes,
                "active_statuses": list(ACTIVE_EXPERIENCE_STATUSES),
                "superseded_hidden": True,
            },
            "fusion": "rrf_lexical_cosine_with_salience_prior",
        }

    @staticmethod
    def _empty_experience_result(question: str, agent_id: str | None, token_budget: int) -> dict[str, Any]:
        return {
            "query": question,
            "agent_id": agent_id,
            "mode": "empty",
            "token_budget": token_budget,
            "total_relevant_tokens": 0,
            "eligible_count": 0,
            "relevant_count": 0,
            "selected_count": 0,
            "items": [],
            "governance": {"agent_isolation": "exact", "superseded_hidden": True},
            "fusion": "rrf_lexical_cosine_with_salience_prior",
        }

    @staticmethod
    def _truncate_to_token_budget(text: str, token_budget: int) -> str:
        words = text.split()
        if not words:
            return ""
        limit = max(1, int(token_budget / 1.3))
        return " ".join(words[:limit])

    def _attach_memory_links(self, conn: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
        ids = [item["ticket_id"] for item in items]
        if not ids:
            return
        marks = ", ".join(["?"] * len(ids))
        by_ticket = {ticket: [] for ticket in ids}
        rows = conn.execute(
            f"""
            SELECT * FROM memory_links
            WHERE from_ticket IN ({marks}) OR to_ticket IN ({marks})
            ORDER BY link_type, score DESC
            """,
            (*ids, *ids),
        ).fetchall()
        for row in rows:
            link = self._memory_link_row(row)
            if link["from_ticket"] in by_ticket:
                by_ticket[link["from_ticket"]].append(link)
            if link["to_ticket"] in by_ticket and link["to_ticket"] != link["from_ticket"]:
                by_ticket[link["to_ticket"]].append(link)
        for item in items:
            item["relations"] = by_ticket[item["ticket_id"]]

    def _link_semantically_similar(
        self,
        conn: sqlite3.Connection,
        *,
        ticket_id: str,
        agent_id: str,
        privacy_scope: str,
        vector: list[float],
        threshold: float,
    ) -> list[dict[str, Any]]:
        # Reconcile this row's machine-inferred neighborhood on every upsert.
        # Explicit curator edges have arbitrary reasons and are preserved.
        conn.execute(
            """
            DELETE FROM memory_links
            WHERE link_type = 'similar_to'
              AND (from_ticket = ? OR to_ticket = ?)
              AND (reason LIKE 'local vector cosine %' OR reason LIKE 'token Jaccard %')
            """,
            (ticket_id, ticket_id),
        )
        status_marks = ", ".join(["?"] * len(ACTIVE_EXPERIENCE_STATUSES))
        rows = conn.execute(
            f"""
            SELECT ticket_id, embedding_adapter, embedding_json
            FROM memory_candidates
            WHERE ticket_id != ? AND agent_id = ? AND privacy_scope = ?
              AND memory_kind != 'candidate'
              AND status IN ({status_marks})
            ORDER BY updated_at DESC
            """,
            (ticket_id, agent_id, privacy_scope, *ACTIVE_EXPERIENCE_STATUSES),
        ).fetchall()
        links: list[dict[str, Any]] = []
        for row in rows:
            if not self._vector_adapter_matches(row["embedding_adapter"]):
                continue
            other = json_loads(row["embedding_json"], [])
            if len(other) != len(vector):
                continue
            score = max(0.0, cosine_similarity(vector, other))
            if score < threshold:
                continue
            first, second = sorted((ticket_id, row["ticket_id"]))
            links.append(
                self._write_memory_link(
                    conn,
                    from_ticket=first,
                    to_ticket=second,
                    link_type="similar_to",
                    score=round(score, 6),
                    reason=f"local vector cosine {round(score, 6)} >= threshold {threshold}",
                    require_exists=False,
                )
            )
        return links

    def graph_entity(self, name: str, allowed_scopes: Iterable[str] | None = None) -> dict[str, Any]:
        document_scopes = list(allowed_scopes) if allowed_scopes is not None else ["public", "internal"]
        with closing(self.connect()) as conn, conn:
            entity = self._find_entity(conn, name)
            if entity is None:
                return {"entity": None, "aliases": [], "relations": [], "evidence_chunks": []}
            relations = self._relations_for_entity(conn, entity["entity_id"], document_scopes)
            if not relations:
                # Entity and alias rows are globally deduplicated, so existence
                # alone is not safe to expose. A caller sees an entity only when
                # at least one relation has provenance in an allowed scope.
                return {"entity": None, "aliases": [], "relations": [], "evidence_chunks": []}
            chunk_ids = sorted({relation["evidence_chunk_id"] for relation in relations})
            evidence = self._chunks_by_ids(conn, chunk_ids, document_scopes)
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

    def decide_memory_candidate(
        self,
        ticket_id: str,
        decision: str,
        reason: str,
        target_ticket: str | None = None,
    ) -> dict[str, Any]:
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
            link: dict[str, Any] | None = None
            if target_ticket:
                # Structural replacement: record WHICH ticket supersedes this one,
                # so a newer learning never silently overwrites the old entry. The
                # superseding ticket points at the one it replaces.
                if decision not in {"supersede", "deprecate"}:
                    raise ValueError("target_ticket is only valid with a supersede or deprecate decision")
                link = self._write_memory_link(
                    conn,
                    from_ticket=target_ticket,
                    to_ticket=ticket_id,
                    link_type="supersedes",
                    score=1.0,
                    reason=reason,
                    require_exists=True,
                )
            event_id = stable_hash(f"candidate-event:{ticket_id}:{decision}:{reason}:{target_ticket or ''}:{now}")
            conn.execute(
                "INSERT INTO memory_candidate_events(event_id, ticket_id, decision, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, ticket_id, decision, reason, now),
            )
            conn.execute(
                "UPDATE memory_candidates SET status = ?, updated_at = ? WHERE ticket_id = ?",
                (status_map[decision], now, ticket_id),
            )
            updated = conn.execute("SELECT * FROM memory_candidates WHERE ticket_id = ?", (ticket_id,)).fetchone()
        result = self._memory_candidate_row(updated)
        if link is not None:
            result["link"] = link
        return result

    # ---- Memory Relation Graph -------------------------------------------------
    # Typed edges between candidate tickets. similar_to is machine-detected by
    # local vector cosine; supersedes/contradicts are curator-recorded so
    # replacement and conflict are structural, never guessed or overwritten.
    MEMORY_LINK_TYPES = ("similar_to", "supersedes", "contradicts")

    def relate_memory_candidates(self, threshold: float = 0.72, scan_limit: int = 2000) -> dict[str, Any]:
        if not 0.0 < threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        now = utc_now()
        with closing(self.connect()) as conn, conn:
            rows = conn.execute(
                """
                SELECT ticket_id, agent_id, privacy_scope, candidate_text,
                       embedding_adapter, embedding_json
                FROM memory_candidates
                ORDER BY created_at, ticket_id LIMIT ?
                """,
                (scan_limit,),
            ).fetchall()
            pairs_examined = 0
            links_created = 0
            links_removed = 0
            valid_pairs: set[tuple[str, str]] = set()
            for i in range(len(rows)):
                left = rows[i]
                left_vector = json_loads(left["embedding_json"], [])
                if not left_vector:
                    left_vector = self.vector_adapter.embed(left["candidate_text"])
                for j in range(i + 1, len(rows)):
                    right = rows[j]
                    # Governance prefilter: automatic semantic edges never
                    # bridge agent ownership or privacy boundaries.
                    if left["agent_id"] != right["agent_id"] or left["privacy_scope"] != right["privacy_scope"]:
                        continue
                    pairs_examined += 1
                    right_vector = json_loads(right["embedding_json"], [])
                    if not right_vector:
                        right_vector = self.vector_adapter.embed(right["candidate_text"])
                    left_adapter = left["embedding_adapter"] or self.vector_adapter.name
                    right_adapter = right["embedding_adapter"] or self.vector_adapter.name
                    adapters_match = left_adapter == right_adapter or (
                        self._vector_adapter_matches(left_adapter)
                        and self._vector_adapter_matches(right_adapter)
                    )
                    if not adapters_match or len(left_vector) != len(right_vector):
                        continue
                    score = max(0.0, cosine_similarity(left_vector, right_vector))
                    if score < threshold:
                        continue
                    a, b = sorted((left["ticket_id"], right["ticket_id"]))
                    valid_pairs.add((a, b))
                    reason = f"local vector cosine {round(score, 6)} >= threshold {threshold}"
                    written = self._write_memory_link(
                        conn,
                        from_ticket=a,
                        to_ticket=b,
                        link_type="similar_to",
                        score=round(score, 4),
                        reason=reason,
                        require_exists=False,
                        _now=now,
                    )
                    if written.get("created"):
                        links_created += 1
                    else:
                        conn.execute(
                            "UPDATE memory_links SET score = ?, reason = ? WHERE link_id = ?",
                            (round(score, 4), reason, written["link_id"]),
                        )
            scanned_ids = [row["ticket_id"] for row in rows]
            if scanned_ids:
                marks = ", ".join(["?"] * len(scanned_ids))
                automatic = conn.execute(
                    f"""
                    SELECT link_id, from_ticket, to_ticket
                    FROM memory_links
                    WHERE link_type = 'similar_to'
                      AND from_ticket IN ({marks}) AND to_ticket IN ({marks})
                      AND (reason LIKE 'local vector cosine %' OR reason LIKE 'token Jaccard %')
                    """,
                    (*scanned_ids, *scanned_ids),
                ).fetchall()
                for link in automatic:
                    pair = tuple(sorted((link["from_ticket"], link["to_ticket"])))
                    if pair not in valid_pairs:
                        links_removed += conn.execute(
                            "DELETE FROM memory_links WHERE link_id = ?",
                            (link["link_id"],),
                        ).rowcount
        return {
            "status": "ok",
            "threshold": threshold,
            "relation_basis": "local_vector_cosine",
            "candidates_scanned": len(rows),
            "pairs_examined": pairs_examined,
            "similar_links_created": links_created,
            "similar_links_removed": links_removed,
        }

    def link_memory(self, from_ticket: str, to_ticket: str, link_type: str, reason: str, score: float = 1.0) -> dict[str, Any]:
        if link_type not in self.MEMORY_LINK_TYPES:
            raise ValueError(f"unsupported memory link type: {link_type} (expected one of {self.MEMORY_LINK_TYPES})")
        if from_ticket == to_ticket:
            raise ValueError("cannot link a ticket to itself")
        with closing(self.connect()) as conn, conn:
            return self._write_memory_link(
                conn,
                from_ticket=from_ticket,
                to_ticket=to_ticket,
                link_type=link_type,
                score=clamp(score),
                reason=reason,
                require_exists=True,
            )

    def memory_graph(self, ticket_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn, conn:
            row = conn.execute("SELECT * FROM memory_candidates WHERE ticket_id = ?", (ticket_id,)).fetchone()
            if row is None:
                # Fail loud rather than returning an empty graph that reads as
                # "this ticket has no relations".
                raise KeyError(ticket_id)
            outgoing = [
                self._memory_link_row(link) for link in conn.execute(
                    "SELECT * FROM memory_links WHERE from_ticket = ? ORDER BY link_type, score DESC", (ticket_id,)
                )
            ]
            incoming = [
                self._memory_link_row(link) for link in conn.execute(
                    "SELECT * FROM memory_links WHERE to_ticket = ? ORDER BY link_type, score DESC", (ticket_id,)
                )
            ]
            neighbor_ids = sorted({link["to_ticket"] for link in outgoing} | {link["from_ticket"] for link in incoming})
            neighbors = {}
            if neighbor_ids:
                marks = ", ".join(["?"] * len(neighbor_ids))
                for neighbor in conn.execute(
                    f"SELECT ticket_id, status, candidate_text FROM memory_candidates WHERE ticket_id IN ({marks})",
                    tuple(neighbor_ids),
                ):
                    neighbors[neighbor["ticket_id"]] = {
                        "ticket_id": neighbor["ticket_id"],
                        "status": neighbor["status"],
                        "summary": neighbor["candidate_text"][:160],
                    }
        return {
            "ticket": self._memory_candidate_row(row),
            "outgoing": outgoing,
            "incoming": incoming,
            "neighbors": neighbors,
            "superseded_by": [link["from_ticket"] for link in incoming if link["link_type"] == "supersedes"],
            "supersedes": [link["to_ticket"] for link in outgoing if link["link_type"] == "supersedes"],
        }

    def _write_memory_link(
        self,
        conn: sqlite3.Connection,
        from_ticket: str,
        to_ticket: str,
        link_type: str,
        score: float,
        reason: str,
        require_exists: bool,
        _now: str | None = None,
    ) -> dict[str, Any]:
        endpoints: dict[str, sqlite3.Row] = {}
        for ticket in (from_ticket, to_ticket):
            endpoint = conn.execute(
                "SELECT agent_id, privacy_scope FROM memory_candidates WHERE ticket_id = ?",
                (ticket,),
            ).fetchone()
            if endpoint is None:
                if require_exists:
                    raise KeyError(ticket)
                continue
            endpoints[ticket] = endpoint
        if len(endpoints) == 2:
            left = endpoints[from_ticket]
            right = endpoints[to_ticket]
            if left["agent_id"] != right["agent_id"]:
                raise ValueError("memory links cannot cross agent ownership boundaries")
            if left["privacy_scope"] != right["privacy_scope"]:
                raise ValueError("memory links cannot cross privacy scopes")
        now = _now or utc_now()
        link_id = stable_hash(f"memory-link:{from_ticket}:{to_ticket}:{link_type}")
        created = conn.execute(
            """
            INSERT OR IGNORE INTO memory_links(link_id, from_ticket, to_ticket, link_type, score, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (link_id, from_ticket, to_ticket, link_type, score, reason, now),
        ).rowcount == 1
        row = conn.execute("SELECT * FROM memory_links WHERE link_id = ?", (link_id,)).fetchone()
        result = self._memory_link_row(row)
        result["created"] = created
        return result

    def _memory_link_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "link_id": row["link_id"],
            "from_ticket": row["from_ticket"],
            "to_ticket": row["to_ticket"],
            "link_type": row["link_type"],
            "score": row["score"],
            "reason": row["reason"],
            "created_at": row["created_at"],
        }

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
                for table in ["sources", "chunks", "entities", "relations", "memory_candidates", "memory_links", "working_memory"]
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
            "vector_adapter": vector_adapter_metadata(self.vector_adapter),
            "fts_adapter": {"name": "chunk_fts", "status": "available", "tokenizer": self.fts_tokenizer},
        }

    def backup(self, destination: str | Path) -> dict[str, Any]:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as source, closing(sqlite3.connect(destination)) as target, target:
            source.backup(target)
        return {"status": "ok", "backup_path": str(destination)}

    def export_json(self, destination: str | Path) -> dict[str, Any]:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, list[dict[str, Any]]] = {}
        tables = ["sources", "chunks", "entities", "entity_aliases", "relations", "memory_candidates", "memory_links", "working_memory"]
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
        resolved, raw = self._read_source_snapshot(path)
        checksum = content_hash(raw)
        uri = resolved.as_uri()
        source_id = stable_hash(f"source:{uri}")
        existing = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        if existing and existing["content_hash"] == checksum:
            return {
                "source": self._source_row(existing, unchanged=True),
                "chunks_written": 0,
                "entities_written": 0,
                "relations_written": 0,
                "unchanged": True,
                "bytes_read": len(raw),
            }

        if existing:
            self._delete_source_derivatives(conn, source_id)
            version = int(existing["version"]) + 1
            created_at = existing["created_at"]
        else:
            version = 1
            created_at = utc_now()

        # Parse the exact bytes that were hashed. Parsers are path-based (PDF,
        # Office, HWP, OCR), so a private same-suffix snapshot closes the
        # checksum/parse TOCTOU gap without exposing the original path.
        with tempfile.TemporaryDirectory(prefix="agentlas-ontology-source-") as temp_dir:
            snapshot = Path(temp_dir) / f"source{path.suffix.lower()}"
            snapshot.write_bytes(raw)
            parsed = self.parser_registry.parse(snapshot)
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
            "bytes_read": len(raw),
        }

    def _read_source_snapshot(self, path: Path) -> tuple[Path, bytes]:
        if path.is_symlink():
            raise ValueError(f"ontology ingest refuses a symlink source: {path}")
        resolved_before = path.resolve(strict=True)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"ontology ingest requires a regular file: {path}")
            if before.st_size > MAX_INGEST_FILE_BYTES:
                raise ValueError(f"ontology source exceeds {MAX_INGEST_FILE_BYTES} bytes: {path.name}")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read(MAX_INGEST_FILE_BYTES + 1)
            if len(raw) > MAX_INGEST_FILE_BYTES:
                raise ValueError(f"ontology source exceeds {MAX_INGEST_FILE_BYTES} bytes: {path.name}")
            after = os.fstat(descriptor)
            identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            if identity_before != identity_after or len(raw) != after.st_size:
                raise ValueError(f"ontology source changed while being read: {path.name}")
        finally:
            os.close(descriptor)
        if path.resolve(strict=True) != resolved_before:
            raise ValueError(f"ontology source changed identity while being read: {path.name}")
        return resolved_before, raw

    def _delete_source_derivatives(self, conn: sqlite3.Connection, source_id: str) -> None:
        chunk_ids = [row["chunk_id"] for row in conn.execute("SELECT chunk_id FROM chunks WHERE source_id = ?", (source_id,))]
        for chunk_id in chunk_ids:
            conn.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (chunk_id,))
        conn.execute("DELETE FROM relations WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))

    def _chunk_records(self, records: list[ParsedRecord]) -> list[ParsedRecord]:
        chunks: list[ParsedRecord] = []
        limit = self.config.chunk_token_limit
        overlap = max(0, min(int(limit * self.config.chunk_overlap_ratio), limit - 1))
        step = limit - overlap
        for record in records:
            words = record.text.split()
            if not words:
                continue
            if len(words) <= limit:
                chunks.append(record)
                continue
            start = 0
            while start < len(words):
                part = " ".join(words[start : start + limit])
                span = dict(record.span)
                span["token_start"] = start
                span["token_end"] = min(len(words), start + limit)
                chunks.append(ParsedRecord(part, span, dict(record.metadata)))
                if start + limit >= len(words):
                    break
                start += step
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
        self._register_vector_adapter(conn)
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
                  evidence_chunk_id, source_id, privacy_scope, source_lineage_json, valid_from, valid_to,
                  observed_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, 'active', ?, ?)
                """,
                (
                    relation_id,
                    subject_id,
                    object_id,
                    relation_type,
                    confidence,
                    chunk["chunk_id"],
                    chunk["source_id"],
                    chunk["privacy_scope"],
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
        scope_marks = ", ".join(["?"] * len(scopes))
        pool: dict[str, dict[str, Any]] = {}
        vectors: dict[str, list[float]] = {}
        fts_order: list[str] = []
        for query_text in [question, *self._expanded_queries(question)]:
            match_expr = self._fts_match_expression(query_text)
            if not match_expr:
                continue
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
                    (match_expr, *scopes, limit * 10),
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            for row in rows:
                chunk_id = row["chunk_id"]
                if chunk_id in pool:
                    continue
                item = self._chunk_row(row)
                item["full_text_score"] = 1.0 / (1.0 + abs(float(row["rank"])))
                pool[chunk_id] = item
                vectors[chunk_id] = json_loads(row["vector_json"], [])
                fts_order.append(chunk_id)
        if len(pool) < limit:
            # Recall fallback for queries with no FTS hits (or tiny pools):
            # bounded scan instead of the old unbounded full-corpus pass.
            rows = conn.execute(
                f"""
                SELECT c.*, s.uri AS source_uri, s.source_type
                FROM chunks c JOIN sources s ON s.source_id = c.source_id
                WHERE c.privacy_scope IN ({scope_marks})
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (*scopes, VECTOR_FALLBACK_SCAN_CAP),
            ).fetchall()
            for row in rows:
                chunk_id = row["chunk_id"]
                if chunk_id not in pool:
                    item = self._chunk_row(row)
                    item["full_text_score"] = self._keyword_score(question, row["text"])
                    pool[chunk_id] = item
                    vectors[chunk_id] = json_loads(row["vector_json"], [])
        query_vector = self.vector_adapter.embed(question)
        for chunk_id, item in pool.items():
            item["vector_score"] = max(0.0, cosine_similarity(query_vector, vectors.get(chunk_id, [])))
        best_vector_score = max((item["vector_score"] for item in pool.values()), default=0.0)
        vector_floor = self._minimum_vector_score(MIN_VECTOR_SCORE, question)
        vector_order = sorted(pool, key=lambda chunk_id: pool[chunk_id]["vector_score"], reverse=True)
        fts_rank = {chunk_id: index for index, chunk_id in enumerate(fts_order)}
        vector_rank = {chunk_id: index for index, chunk_id in enumerate(vector_order)}
        relevant: list[dict[str, Any]] = []
        for chunk_id, item in pool.items():
            if (
                chunk_id not in fts_rank
                and item.get("full_text_score", 0.0) <= 0.0
                and (
                    item["vector_score"] < vector_floor
                    or item["vector_score"] < best_vector_score * VECTOR_RELATIVE_FLOOR
                )
            ):
                continue
            item["score"] = round(
                1.0 / (RRF_K + fts_rank.get(chunk_id, RRF_MISSING_RANK))
                + 1.0 / (RRF_K + vector_rank.get(chunk_id, RRF_MISSING_RANK)),
                6,
            )
            relevant.append(item)
        ranked = sorted(relevant, key=lambda item: item["score"], reverse=True)
        ranked = self._apply_rerank_hook(question, ranked, limit)
        return ranked[:limit]

    def _fts_match_expression(self, question: str) -> str | None:
        terms: list[str] = []
        for token in LATIN_TOKEN_PATTERN.findall(question.lower()):
            if len(token) > 2:
                terms.append(token)
        for run in CJK_RUN_PATTERN.findall(question):
            if len(run) >= 2:
                terms.append(run)
        deduped = list(dict.fromkeys(terms))
        if not deduped:
            return None
        return " OR ".join(f'"{term}"' for term in deduped)

    def _expanded_queries(self, question: str) -> list[str]:
        hook = self.config.query_expansion_hook
        if hook is None:
            return []
        cached = self._expansion_cache.get(question)
        if cached is not None:
            return cached
        try:
            raw = hook(question) or []
        except Exception:
            raw = []
        expansions: list[str] = []
        for value in raw:
            text = str(value).strip()
            if text and text != question and text not in expansions:
                expansions.append(text)
            if len(expansions) >= 4:
                break
        self._expansion_cache[question] = expansions
        return expansions

    def _apply_rerank_hook(self, question: str, ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        hook = self.config.rerank_hook
        if hook is None or not ranked:
            return ranked
        window_size = max(limit, self.config.rerank_candidate_limit)
        window = ranked[:window_size]
        if self.config.hooks_run_locally:
            eligible = list(window)
        else:
            # Data-sovereignty gate: chunk text outside cloud_safe_scopes is
            # never handed to a cloud-backed rerank hook; those chunks keep
            # their fused-rank positions.
            eligible = [item for item in window if item["privacy_scope"] in self.config.cloud_safe_scopes]
        if not eligible:
            return ranked
        payload = [{"chunk_id": item["chunk_id"], "text": item["text"]} for item in eligible]
        try:
            preferred = [chunk_id for chunk_id in (hook(question, payload) or []) if isinstance(chunk_id, str)]
        except Exception:
            return ranked
        eligible_ids = {item["chunk_id"] for item in eligible}
        order = [chunk_id for chunk_id in dict.fromkeys(preferred) if chunk_id in eligible_ids]
        order += [item["chunk_id"] for item in eligible if item["chunk_id"] not in order]
        by_id = {item["chunk_id"]: item for item in window}
        reordered = iter(order)
        merged: list[dict[str, Any]] = []
        for item in window:
            if item["chunk_id"] in eligible_ids:
                merged.append(by_id[next(reordered)])
            else:
                merged.append(item)
        return merged + ranked[window_size:]

    def _keyword_score(self, question: str, text: str) -> float:
        query_tokens = set(tokenize(question))
        text_tokens = set(tokenize(text))
        if not query_tokens:
            return 0.0
        return len(query_tokens & text_tokens) / len(query_tokens)

    def _minimum_vector_score(self, default: float, question: str = "") -> float:
        if self.vector_adapter.name == "model2vec_potion_multilingual_128m_int8":
            # Multilingual similarities have a lower, meaningful range than the
            # old English WordPiece + hash96 hybrid. Keep lexical overlap in its
            # separate RRF rank and apply the calibrated semantic noise floor.
            if CJK_RUN_PATTERN.search(question):
                return max(default, MODEL2VEC_CJK_MIN_VECTOR_SCORE)
            return max(default, MODEL2VEC_MIN_VECTOR_SCORE)
        return default

    def _vector_adapter_matches(self, stored_adapter: str | None) -> bool:
        return stored_adapter in {self.vector_adapter.name, self.vector_adapter.identity}

    def _related_entities(
        self,
        conn: sqlite3.Connection,
        question: str,
        chunks: list[dict[str, Any]],
        allowed_scopes: list[str],
    ) -> list[dict[str, Any]]:
        if not allowed_scopes:
            return []
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]
        entity_ids: set[str] = set()
        if chunk_ids:
            chunk_marks = ", ".join(["?"] * len(chunk_ids))
            scope_marks = ", ".join(["?"] * len(allowed_scopes))
            for row in conn.execute(
                f"""
                SELECT r.subject_entity_id, r.object_entity_id
                FROM relations r
                JOIN chunks c ON c.chunk_id = r.evidence_chunk_id
                JOIN sources src ON src.source_id = r.source_id
                WHERE r.evidence_chunk_id IN ({chunk_marks})
                  AND r.privacy_scope IN ({scope_marks})
                  AND c.source_id = r.source_id
                  AND c.privacy_scope = r.privacy_scope
                  AND src.privacy_scope = r.privacy_scope
                """,
                (*chunk_ids, *allowed_scopes),
            ):
                entity_ids.add(row["subject_entity_id"])
                entity_ids.add(row["object_entity_id"])
        for name in extract_entity_names(question):
            entity = self._find_entity(conn, name)
            if entity and self._entity_has_accessible_relation(conn, entity["entity_id"], allowed_scopes):
                entity_ids.add(entity["entity_id"])
        if not entity_ids:
            return []
        marks = ", ".join(["?"] * len(entity_ids))
        rows = conn.execute(f"SELECT * FROM entities WHERE entity_id IN ({marks}) ORDER BY canonical_name", tuple(entity_ids)).fetchall()
        return [self._entity_row(row) for row in rows]

    def _relation_edges(
        self,
        conn: sqlite3.Connection,
        entities: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
        allowed_scopes: list[str],
    ) -> list[dict[str, Any]]:
        if not allowed_scopes:
            return []
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
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        args.extend(allowed_scopes)
        rows = conn.execute(
            f"""
            SELECT r.*, s.canonical_name AS subject, o.canonical_name AS object
            FROM relations r
            JOIN entities s ON s.entity_id = r.subject_entity_id
            JOIN entities o ON o.entity_id = r.object_entity_id
            JOIN chunks c ON c.chunk_id = r.evidence_chunk_id
            JOIN sources src ON src.source_id = r.source_id
            WHERE r.status = 'active' AND ({" OR ".join(clauses)})
              AND r.privacy_scope IN ({scope_marks})
              AND c.source_id = r.source_id
              AND c.privacy_scope = r.privacy_scope
              AND src.privacy_scope = r.privacy_scope
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
        vector = self.vector_adapter.embed(candidate_text)
        self._register_vector_adapter(conn)
        idempotency_key = stable_hash(f"memory-candidate:{question}:{json_dumps(source_refs)}")
        ticket_id = stable_hash(f"ticket:{idempotency_key}")
        now = utc_now()
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_candidates(
              ticket_id, idempotency_key, query, candidate_text, source_refs_json,
              reason, confidence, risk, expiry, suggested_scope, status,
              durable_write_enabled, agent_id, memory_kind, tags_json, salience,
              privacy_scope, embedding_adapter, embedding_dimensions,
              embedding_json, embedding_content_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', 0, '', 'candidate', '[]', ?, ?, ?, ?, ?, ?, ?, ?)
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
                0.5,
                "private" if any(chunk["privacy_scope"] == "private" for chunk in chunks) else "internal",
                self.vector_adapter.name,
                len(vector),
                json_dumps(vector),
                content_hash(candidate_text.encode("utf-8")),
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
        # Nothing relevant was retrieved for this query — do not fabricate a
        # working-memory item from an empty result set (was an IndexError on
        # chunks[0]). An agent only caches memory when retrieval found something,
        # which is what makes ontology grounding selective rather than constant.
        if not chunks:
            return []
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

    def _entity_has_accessible_relation(
        self,
        conn: sqlite3.Connection,
        entity_id: str,
        allowed_scopes: list[str],
    ) -> bool:
        if not allowed_scopes:
            return False
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        row = conn.execute(
            f"""
            SELECT 1
            FROM relations r
            JOIN chunks c ON c.chunk_id = r.evidence_chunk_id
            JOIN sources src ON src.source_id = r.source_id
            WHERE (r.subject_entity_id = ? OR r.object_entity_id = ?)
              AND r.status = 'active'
              AND r.privacy_scope IN ({scope_marks})
              AND c.source_id = r.source_id
              AND c.privacy_scope = r.privacy_scope
              AND src.privacy_scope = r.privacy_scope
            LIMIT 1
            """,
            (entity_id, entity_id, *allowed_scopes),
        ).fetchone()
        return row is not None

    def _relations_for_entity(
        self,
        conn: sqlite3.Connection,
        entity_id: str,
        allowed_scopes: list[str],
    ) -> list[dict[str, Any]]:
        if not allowed_scopes:
            return []
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        rows = conn.execute(
            f"""
            SELECT r.*, s.canonical_name AS subject, o.canonical_name AS object
            FROM relations r
            JOIN entities s ON s.entity_id = r.subject_entity_id
            JOIN entities o ON o.entity_id = r.object_entity_id
            JOIN chunks c ON c.chunk_id = r.evidence_chunk_id
            JOIN sources src ON src.source_id = r.source_id
            WHERE (r.subject_entity_id = ? OR r.object_entity_id = ?)
              AND r.status = 'active'
              AND r.privacy_scope IN ({scope_marks})
              AND c.source_id = r.source_id
              AND c.privacy_scope = r.privacy_scope
              AND src.privacy_scope = r.privacy_scope
            ORDER BY r.confidence DESC, r.observed_at DESC
            """,
            (entity_id, entity_id, *allowed_scopes),
        ).fetchall()
        return [self._relation_row(row) for row in rows]

    def _chunks_by_ids(
        self,
        conn: sqlite3.Connection,
        chunk_ids: list[str],
        allowed_scopes: list[str],
    ) -> list[dict[str, Any]]:
        if not chunk_ids or not allowed_scopes:
            return []
        chunk_marks = ", ".join(["?"] * len(chunk_ids))
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        rows = conn.execute(
            f"""
            SELECT c.*, s.uri AS source_uri, s.source_type
            FROM chunks c JOIN sources s ON s.source_id = c.source_id
            WHERE c.chunk_id IN ({chunk_marks})
              AND c.privacy_scope IN ({scope_marks})
              AND s.privacy_scope = c.privacy_scope
            """,
            (*chunk_ids, *allowed_scopes),
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
            "privacy_scope": row["privacy_scope"],
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
            "agent_id": row["agent_id"],
            "memory_kind": row["memory_kind"],
            "tags": json_loads(row["tags_json"], []),
            "salience": row["salience"],
            "privacy_scope": row["privacy_scope"],
            "source_memory_id": row["source_memory_id"],
            "source_updated_at": row["source_updated_at"],
            "embedding": {
                "adapter": row["embedding_adapter"],
                "dimensions": row["embedding_dimensions"],
                "content_hash": row["embedding_content_hash"],
            },
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


# Conversational text has no lexically-regular relation phrases (the document
# extractor above yields zero), so the experience graph is built from ENTITY
# CO-OCCURRENCE instead: entities that recur together across sessions become the
# bridges multi-hop recall walks. This stopword set keeps generic chatter from
# becoming hub nodes that over-connect the graph into a hairball.
EXPERIENCE_STOPWORDS = frozenset(
    {
        "about", "above", "after", "again", "against", "already", "always", "another",
        "anything", "around", "because", "before", "being", "below", "between", "cannot",
        "could", "doing", "during", "either", "enough", "especially", "every", "everything",
        "first", "friend", "friends", "going", "gonna", "great", "happy", "having", "hello",
        "here", "himself", "house", "however", "instead", "into", "just", "kind", "know",
        "later", "least", "little", "lot", "made", "make", "makes", "many", "maybe", "might",
        "money", "month", "months", "more", "morning", "most", "much", "myself", "never",
        "new", "next", "nice", "night", "nothing", "often", "once", "only", "other", "over",
        "people", "person", "place", "pretty", "probably", "really", "recently", "right",
        "said", "same", "school", "she", "should", "since", "some", "someone", "something",
        "sometimes", "still", "stuff", "such", "sure", "take", "than", "that", "their",
        "them", "then", "there", "these", "they", "thing", "things", "think", "this",
        "those", "though", "through", "time", "today", "together", "tomorrow", "tonight",
        "took", "totally", "under", "until", "very", "want", "wanted", "was", "week",
        "weekend", "weeks", "well", "went", "were", "what", "when", "where", "which",
        "while", "with", "without", "work", "would", "year", "years", "yesterday", "your",
        "yourself",
    }
)


def extract_experience_entities(text: str, limit: int = 16) -> list[tuple[str, str, str]]:
    """Deterministic (LLM-free) entity extraction tuned for conversational memory.

    Returns ``[(entity_key, canonical, entity_type)]``. Proper-noun phrases are the
    strongest cross-session bridges (people, places, products, orgs); salient rare
    content tokens fill in topics that carry no capitalization (caffeine, marathon,
    migraine). Kept fully deterministic so the experience graph — and the multi-hop
    recall built on it — is reproducible and testable without a model.
    """
    from collections import Counter

    seen: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    for phrase in re_find_title_phrases(text):
        key = normalized_key(phrase)
        if not key or len(key) < 3 or key in EXPERIENCE_STOPWORDS:
            continue
        if key not in seen:
            seen[key] = (normalize_name(phrase), "proper")
            order.append(key)
    counts = Counter(
        token
        for token in tokenize(text)
        if len(token) >= 5 and token.isalpha() and token not in EXPERIENCE_STOPWORDS
    )
    for token, _frequency in counts.most_common():
        key = normalized_key(token)
        if not key or key in seen or key in EXPERIENCE_STOPWORDS:
            continue
        seen[key] = (token, "topic")
        order.append(key)
    return [(key, seen[key][0], seen[key][1]) for key in order[:limit]]


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
