from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse

from .embeddings import (
    CJK_RUN_PATTERN,
    LATIN_TOKEN_PATTERN,
    VectorAdapter,
    cosine_similarity,
    encode_vector,
    select_vector_adapter,
    tokenize,
    vector_adapter_metadata,
)
from . import entities as entity_layer
from . import graph_spread
from .parsers import ParsedRecord, SourceParserRegistry
from .utils import clamp, content_hash, estimate_tokens, json_dumps, json_loads, normalize_name, normalized_key, stable_hash, utc_now


SCHEMA_VERSION = 4
DEFAULT_DB_PATH = Path(".agentlas/ontology-runtime.sqlite")
MAX_INGEST_FILES = 1_000
MAX_ONTOLOGY_INBOX_FILES = 80
MAX_INGEST_FILE_BYTES = 16 * 1024 * 1024
MAX_INGEST_TOTAL_BYTES = 128 * 1024 * 1024
MAX_INGEST_DEPTH = 12
MAX_QUERY_RESULTS = 100
MAX_EXPERIENCE_SCAN_ROWS = 5_000
MAX_STORAGE_IMPORT_BYTES = 128 * 1024 * 1024
STORAGE_TABLES = (
    "sources",
    "source_lineage",
    "chunks",
    "entities",
    "entity_aliases",
    "relations",
    "memory_candidates",
    "memory_candidate_events",
    "memory_links",
    "working_memory",
    "experience_entities",
    "experience_mentions",
    "experience_relations",
)

# Hybrid document and governed experience retrieval both expose hard local
# scan budgets. Experience results report partial status when the deterministic
# newest-first candidate window is truncated.
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
# Graph spread (Personalized PageRank, stage 4) defaults, chosen by measurement
# (recall-repair plan §12, 2026-09-23). Multi-hop set: 21 questions whose answer
# shares no content word with the question, 774-memory haystack from this repo's
# commit history + real ledger/code map. Single-hop guard: LongMemEval-S, 100
# questions, One path.
#   seeds=5 d=0.85 w=2.0 admit=5: multi-hop hit@10 0/21 -> 21/21; single-hop
#   recall@5 96% -> 96% (seed block is untouchable), recall@10 99% -> 98%.
#   seeds=3 lifted multi-hop hit@5 (0 -> 10/21) but cost single-hop @5 (96 -> 93);
#   damping 0.5 or weight 1.0 left most file/co-edit hops below rank 10.
DEFAULT_PPR_DAMPING = 0.85
DEFAULT_PPR_WEIGHT = 2.0
PPR_SEED_COUNT = 5
PPR_ADMITTED = 5
PPR_MIN_RELATIVE_MASS = 0.01
ACTIVE_EXPERIENCE_STATUSES = (
    "active",
    "accepted",
    "approved",
    "approved_pending_curator",
    "promoted",
)


# Relations since the code-aware entity layer (2026-09-23). Additive to schema
# 4, so SCHEMA_VERSION stays 4: every installed reader checks
# ``max(version) == SCHEMA_VERSION`` exactly (read-only open raises otherwise)
# and a bump also forces a full re-embed of every chunk. What changed:
#   basis          where the edge came from (entities.BASIS_*); correlation and
#                  ledger edges are never causal.
#   evidence_ref   the non-chunk evidence of structural edges (code-map
#                  snapshotId, contact ledger).
#   evidence_chunk_id / source_id may be NULL, but only for code_map/ledger
#                  edges; every other edge still proves itself with a chunk.
# Older readers inner-join chunks on evidence_chunk_id, so they simply never
# see the NULL-evidence rows.
RELATIONS_TABLE_DDL = """
                CREATE TABLE {if_not_exists}{table} (
                  relation_id TEXT PRIMARY KEY,
                  subject_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                  object_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                  relation_type TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  evidence_chunk_id TEXT REFERENCES chunks(chunk_id) ON DELETE CASCADE,
                  source_id TEXT REFERENCES sources(source_id) ON DELETE CASCADE,
                  privacy_scope TEXT NOT NULL DEFAULT 'private',
                  source_lineage_json TEXT NOT NULL,
                  valid_from TEXT,
                  valid_to TEXT,
                  observed_at TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  basis TEXT NOT NULL DEFAULT 'asserted',
                  evidence_ref TEXT,
                  UNIQUE(subject_entity_id, object_entity_id, relation_type, evidence_chunk_id)
                );
"""
RELATION_COLUMNS = (
    "relation_id",
    "subject_entity_id",
    "object_entity_id",
    "relation_type",
    "confidence",
    "evidence_chunk_id",
    "source_id",
    "privacy_scope",
    "source_lineage_json",
    "valid_from",
    "valid_to",
    "observed_at",
    "status",
    "created_at",
    "updated_at",
    "basis",
    "evidence_ref",
)
ENTITY_LAYER_ADAPTER = "entity_layer"
# Structural (code map / ledger) edges describe the project's own code, which
# is internal to the project: never public, never elevated to private-only.
STRUCTURAL_SCOPE = "internal"
CODE_ENTITY_TYPES = frozenset(
    {"file", "doc", "path", "symbol", "command", "env_var", "key", "code_id", "package", "version"}
)
MAX_RELATION_EDGES = 20
# RRF weight of the entity channel when the question named no code token and
# linked only through a word-split phrase ("research decision"). Measured on
# the desktop known-item control: at full weight one plain-prose sentence lost
# its own chunk from the top 5.
WORDS_SEED_WEIGHT = 0.5
# RRF weight of the entity channel against the lexical and vector channels
# (1.0 each). The measured value of this layer is mostly the relation lines;
# at 1.0 the extra channel displaced known items as often as it rescued them.
ENTITY_CHANNEL_WEIGHT = 0.5
MAX_ENTITY_CHANNEL = 20
ENTITY_CHANNEL_CANDIDATES = 200


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
    read_only: bool = False
    # Project whose contact ledger and code map feed co_edited/references edges
    # into experience graph spread. Default: the directory holding .agentlas/
    # when the database lives there; otherwise no project edges.
    graph_project_root: Path | str | None = None


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
        # Whether this database carries the code-aware entity layer. A
        # read-only open of a database no writer has upgraded yet still
        # answers queries, just without the entity channel.
        self._entity_layer_ready = False
        self._code_index: entity_layer.CodeIndex | None = None
        if self.config.read_only:
            if not self.db_path.is_file():
                raise FileNotFoundError(f"ontology runtime database does not exist: {self.db_path}")
            self._load_read_only_state()
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.migrate()

    def connect(self) -> sqlite3.Connection:
        if self.config.read_only:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.db_path)
            # Default (rollback-journal) mode makes a writer's transaction take
            # an exclusive lock that blocks every reader for its duration. The
            # UserPromptSubmit hook opens a fresh read-only connection on every
            # prompt, so a concurrent writer (auto-update, another session, a
            # background index refresh) stalls it for as long as that write
            # takes — measured as the dominant source of multi-second hook
            # latency, not raw Python cost. WAL lets readers see a consistent
            # snapshot without waiting on writers at all. It is a one-time,
            # persistent, file-level setting, so only the writable connection
            # needs to request it.
            conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # A bounded wait beats the sqlite3 default (fail immediately with
        # "database is locked"); 5s matches WorkforceGoalStore's existing
        # sqlite3.connect(timeout=5) convention elsewhere in this codebase.
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _load_read_only_state(self) -> None:
        with closing(self.connect()) as conn:
            version = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"ontology schema {version!r} requires migration to {SCHEMA_VERSION}; open writable once first"
                )
            row = conn.execute(
                "SELECT config_json FROM runtime_adapters WHERE name = 'chunk_fts'"
            ).fetchone()
            if row is not None:
                self.fts_tokenizer = str(json_loads(row["config_json"], {}).get("tokenizer") or "unicode61")
            self._entity_layer_ready = self._has_entity_layer(conn)

    @staticmethod
    def _has_entity_layer(conn: sqlite3.Connection) -> bool:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('entity_mentions', 'entity_keys')"
            )
        }
        columns = {row[1] for row in conn.execute("PRAGMA table_info(relations)")}
        return tables == {"entity_mentions", "entity_keys"} and {"basis", "evidence_ref"} <= columns

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

                """
                + RELATIONS_TABLE_DDL.format(table="relations", if_not_exists="IF NOT EXISTS ")
                + """

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

                -- Graph-spread neighborhood (stage 4, Personalized PageRank).
                -- Machine-derived, rebuildable, never curator-authored: the
                -- nearest neighbors each memory saw in the cosine scan that
                -- ingest already runs (>= 0.55, 5 per node, the desktop
                -- memory_relation_edges contract). relation_type is stored so
                -- correlation edges are never read as causal ones.
                CREATE TABLE IF NOT EXISTS experience_graph_edges (
                  agent_id TEXT NOT NULL,
                  src_ticket TEXT NOT NULL REFERENCES memory_candidates(ticket_id) ON DELETE CASCADE,
                  dst_ticket TEXT NOT NULL REFERENCES memory_candidates(ticket_id) ON DELETE CASCADE,
                  relation_type TEXT NOT NULL,
                  weight REAL NOT NULL,
                  basis TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY (agent_id, src_ticket, dst_ticket, relation_type)
                );
                CREATE INDEX IF NOT EXISTS idx_exp_graph_dst ON experience_graph_edges(agent_id, dst_ticket);
                """
            )
            self._ensure_memory_candidate_columns(conn)
            self._ensure_entity_layer_schema(conn)
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
            self._upsert_runtime_adapter(
                conn,
                name="chunk_fts",
                kind="fts",
                status="available",
                config_json=json_dumps({"tokenizer": self.fts_tokenizer}),
            )
            for name, status in self.parser_registry.adapter_statuses():
                self._upsert_runtime_adapter(
                    conn, name=name, kind="parser", status=status, config_json="{}"
                )
            self._entity_layer_ready = self._has_entity_layer(conn)

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
    def _ensure_entity_layer_schema(conn: sqlite3.Connection) -> None:
        """Idempotent, in-place upgrade to the code-aware entity layer.

        Keeps every existing row. The only non-additive step is relaxing
        ``relations.evidence_chunk_id`` / ``source_id`` to NULL-able, which
        SQLite can only do by rebuilding the table; it runs once (the
        NOT NULL flag is the marker), inside a savepoint, and copies every row.
        """

        info = {row["name"]: row for row in conn.execute("PRAGMA table_info(relations)")}
        needs_rebuild = bool(info) and (
            int(info["evidence_chunk_id"]["notnull"]) == 1 or int(info["source_id"]["notnull"]) == 1
        )
        if needs_rebuild:
            # A trigger or view naming the table would break the rename (and
            # this schema defines none): leave the table as it is, fail open.
            dependents = [
                row["name"]
                for row in conn.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type IN ('trigger', 'view') AND sql IS NOT NULL"
                )
                if re.search(r"\brelations\b", row["sql"] or "")
            ]
            if not dependents:
                copy = [name for name in RELATION_COLUMNS if name in info]
                conn.execute("SAVEPOINT entity_layer_relations")
                try:
                    conn.execute("DROP TABLE IF EXISTS relations__entity_layer")
                    conn.execute(RELATIONS_TABLE_DDL.format(table="relations__entity_layer", if_not_exists=""))
                    columns = ", ".join(copy)
                    conn.execute(
                        f"INSERT INTO relations__entity_layer({columns}) SELECT {columns} FROM relations"
                    )
                    conn.execute("DROP TABLE relations")
                    conn.execute("ALTER TABLE relations__entity_layer RENAME TO relations")
                    conn.execute("RELEASE entity_layer_relations")
                except sqlite3.DatabaseError:
                    conn.execute("ROLLBACK TO entity_layer_relations")
                    conn.execute("RELEASE entity_layer_relations")
                    raise
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(relations)")}
        if "basis" not in existing:
            conn.execute("ALTER TABLE relations ADD COLUMN basis TEXT NOT NULL DEFAULT 'asserted'")
        if "evidence_ref" not in existing:
            conn.execute("ALTER TABLE relations ADD COLUMN evidence_ref TEXT")
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject_entity_id);
            CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object_entity_id);
            CREATE INDEX IF NOT EXISTS idx_relations_evidence ON relations(evidence_chunk_id);
            CREATE INDEX IF NOT EXISTS idx_relations_basis ON relations(basis);

            -- entity <-> chunk. An entity lives while it is mentioned OR related
            -- (was: related only, which pruned every mention-only name). role
            -- 'self' marks the document entity of the chunk's own source.
            CREATE TABLE IF NOT EXISTS entity_mentions (
              entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
              chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
              source_id TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'mention',
              PRIMARY KEY (entity_id, chunk_id)
            );
            CREATE INDEX IF NOT EXISTS idx_entity_mentions_chunk ON entity_mentions(chunk_id);

            -- Question-linking keys (many entities may share one: "runtime.py").
            -- entity_aliases.normalized_alias is globally UNIQUE and keeps its
            -- job (exact lookup for graph_entity); these are the linker's.
            CREATE TABLE IF NOT EXISTS entity_keys (
              key TEXT NOT NULL,
              entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
              kind TEXT NOT NULL,
              PRIMARY KEY (key, entity_id)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS idx_entity_keys_entity ON entity_keys(entity_id);
            """
        )

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
        structural = ", ".join(f"'{basis}'" for basis in entity_layer.STRUCTURAL_BASES)
        # Chunk-evidenced rows (index range on evidence_chunk_id, so the many
        # structural rows are never visited on this every-open pass) ...
        conn.execute(
            """
            UPDATE relations
            SET privacy_scope = 'private'
            WHERE evidence_chunk_id IS NOT NULL
              AND privacy_scope != 'private'
              AND (
               privacy_scope NOT IN ('public', 'internal', 'private')
               OR NOT EXISTS (
                 SELECT 1
                 FROM chunks c
                 JOIN sources s ON s.source_id = c.source_id
                 WHERE c.chunk_id = relations.evidence_chunk_id
                   AND c.source_id = relations.source_id
                   AND c.privacy_scope = relations.privacy_scope
                   AND s.privacy_scope = relations.privacy_scope
               ))
            """
        )
        # ... and evidence-less rows that are not structural: unprovable.
        conn.execute(
            f"""
            UPDATE relations SET privacy_scope = 'private'
            WHERE evidence_chunk_id IS NULL AND basis NOT IN ({structural}) AND privacy_scope != 'private'
            """
        )
        # Structural edges have no chunk to prove a scope with; they are the
        # project's own code facts, pinned to one scope (an older writer that
        # does not know them fails them closed to private — undo only that).
        conn.execute(
            f"""
            UPDATE relations SET privacy_scope = ?
            WHERE evidence_chunk_id IS NULL AND basis IN ({structural}) AND privacy_scope != ?
            """,
            (STRUCTURAL_SCOPE, STRUCTURAL_SCOPE),
        )

    def _register_vector_adapter(self, conn: sqlite3.Connection) -> None:
        metadata = vector_adapter_metadata(self.vector_adapter)
        self._upsert_runtime_adapter(
            conn,
            name=self.vector_adapter.name,
            kind="vector",
            status=self.vector_adapter.status,
            config_json=json_dumps(metadata),
        )

    @staticmethod
    def _upsert_runtime_adapter(
        conn: sqlite3.Connection,
        *,
        name: str,
        kind: str,
        status: str,
        config_json: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO runtime_adapters(name, kind, status, config_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              kind = excluded.kind,
              status = excluded.status,
              config_json = excluded.config_json,
              updated_at = excluded.updated_at
            WHERE runtime_adapters.kind != excluded.kind
               OR runtime_adapters.status != excluded.status
               OR runtime_adapters.config_json != excluded.config_json
            """,
            (name, kind, status, config_json, utc_now()),
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
                (json_dumps(encode_vector(self.vector_adapter.embed(row["text"]))), now, row["chunk_id"]),
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
                    json_dumps(encode_vector(vector)),
                    content_hash(text.encode("utf-8")),
                    now,
                    row["ticket_id"],
                ),
            )
        # Neighborhoods were measured in the old vector space.
        conn.execute("DELETE FROM experience_graph_edges WHERE relation_type = 'similar_to'")
        self._register_vector_adapter(conn)

    def ingest_path(
        self,
        path: str | Path,
        access_scope: str = "internal",
        parent_source_id: str | None = None,
        *,
        refresh_graph: bool = True,
    ) -> dict[str, Any]:
        """Ingest a file or directory.

        ``refresh_graph=False`` skips the corpus-level entity refresh (code map,
        ledger, co-occurrence) for callers that ingest many single files in a
        row and call :meth:`refresh_entity_graph` once at the end.
        """
        root = Path(path)
        synchronize_directory = root.is_dir() and not root.is_symlink()
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
            "deleted_sources": [],
            "scan": {
                "complete": not any(
                    item.get("reason") in {"file_count_limit", "total_byte_limit"}
                    for item in skipped_sources
                ),
                "truncated": any(
                    item.get("reason") in {"file_count_limit", "total_byte_limit"}
                    for item in skipped_sources
                ),
            },
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
            if synchronize_directory:
                summary["deleted_sources"] = self._delete_missing_sources_under_root(conn, root, files)
            if refresh_graph:
                summary["entity_graph"] = self._refresh_entity_graph_guarded(conn)
            self._prune_orphan_entities(conn)
        return summary

    @staticmethod
    def _path_from_file_uri(uri: str) -> Path | None:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            return None
        return Path(unquote(parsed.path))

    @staticmethod
    def _file_content_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 256), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _stale_source_rows(self, conn: sqlite3.Connection) -> list[dict[str, str]]:
        stale: list[dict[str, str]] = []
        for row in conn.execute(
            "SELECT source_id, uri, display_name, content_hash FROM sources ORDER BY source_id"
        ):
            path = self._path_from_file_uri(str(row["uri"] or ""))
            if path is None:
                continue
            if path.is_symlink() or not path.is_file():
                stale.append(
                    {
                        "source_id": str(row["source_id"]),
                        "uri": str(row["uri"]),
                        "display_name": str(row["display_name"]),
                        "reason": "source_deleted",
                    }
                )
                continue
            try:
                current_hash = self._file_content_hash(path)
            except OSError:
                stale.append(
                    {
                        "source_id": str(row["source_id"]),
                        "uri": str(row["uri"]),
                        "display_name": str(row["display_name"]),
                        "reason": "source_unreadable",
                    }
                )
                continue
            if current_hash != str(row["content_hash"] or ""):
                stale.append(
                    {
                        "source_id": str(row["source_id"]),
                        "uri": str(row["uri"]),
                        "display_name": str(row["display_name"]),
                        "reason": "source_changed",
                    }
                )
        return stale

    @staticmethod
    def _stale_source_error(stale_sources: list[dict[str, str]]) -> str:
        reasons = {item.get("reason") for item in stale_sources}
        return "ontology_sources_deleted" if reasons == {"source_deleted"} else "ontology_sources_changed"

    def _delete_missing_sources_under_root(
        self,
        conn: sqlite3.Connection,
        root: Path,
        current_files: list[Path],
    ) -> list[dict[str, str]]:
        root_resolved = root.resolve()
        current = {path.resolve() for path in current_files}
        deleted: list[dict[str, str]] = []
        for row in conn.execute("SELECT source_id, uri, display_name FROM sources ORDER BY source_id"):
            path = self._path_from_file_uri(str(row["uri"] or ""))
            if path is None:
                continue
            try:
                path.relative_to(root_resolved)
            except ValueError:
                continue
            if path in current or path.exists() or path.is_symlink():
                continue
            source_id = str(row["source_id"])
            self._delete_source_derivatives(conn, source_id)
            conn.execute(
                "DELETE FROM source_lineage WHERE parent_source_id = ? OR child_source_id = ?",
                (source_id, source_id),
            )
            conn.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
            deleted.append(
                {
                    "source_id": source_id,
                    "uri": str(row["uri"]),
                    "display_name": str(row["display_name"]),
                }
            )
        return deleted

    @staticmethod
    def _prune_orphan_entities(conn: sqlite3.Connection) -> None:
        """Drop entities nothing refers to any more.

        An entity is kept while it is mentioned by a chunk OR related to
        another entity. Relation-only survival (the old rule) deleted every
        name a document merely mentioned, which is exactly what question
        linking needs.
        """
        has_mentions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'entity_mentions'"
        ).fetchone()
        mention_clause = (
            " AND NOT EXISTS (SELECT 1 FROM entity_mentions m WHERE m.entity_id = entities.entity_id)"
            if has_mentions
            else ""
        )
        conn.execute(
            "DELETE FROM entities WHERE "
            "NOT EXISTS (SELECT 1 FROM relations WHERE subject_entity_id = entities.entity_id) "
            "AND NOT EXISTS (SELECT 1 FROM relations WHERE object_entity_id = entities.entity_id)"
            + mention_clause
        )

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
        record_memory: bool = False,
        experience_token_budget: int = DEFAULT_EXPERIENCE_TOKEN_BUDGET,
        experience_top_k: int = DEFAULT_EXPERIENCE_TOP_K,
    ) -> dict[str, Any]:
        if limit < 1 or limit > MAX_QUERY_RESULTS:
            return {
                "status": "error",
                "error": f"limit must be between 1 and {MAX_QUERY_RESULTS}",
                "query": question,
                "chunks": [],
            }
        if experience_token_budget < 1:
            return {
                "status": "error",
                "error": "invalid_experience_token_budget",
                "detail": "experience_token_budget must be at least 1",
                "query": question,
                "chunks": [],
            }
        if experience_top_k < 1:
            return {
                "status": "error",
                "error": "invalid_experience_top_k",
                "detail": "experience_top_k must be at least 1",
                "query": question,
                "chunks": [],
            }
        requested_scopes = list(allowed_scopes) if allowed_scopes is not None else None
        document_scopes = requested_scopes or ["public", "internal"]
        # An agent's dedicated experience projection is private by default and
        # already exact-agent isolated. Project document privacy keeps the
        # long-standing explicit opt-in boundary above.
        experience_scopes = requested_scopes or (["public", "internal", "private"] if agent_id else ["public", "internal"])
        with closing(self.connect()) as conn, conn:
            stale_sources = self._stale_source_rows(conn)
            if stale_sources:
                return {
                    "status": "stale_index",
                    "error": self._stale_source_error(stale_sources),
                    "query": question,
                    "stale_sources": stale_sources,
                    "chunks": [],
                    "related_entities": [],
                    "relation_edges": [],
                    "experience_memory": self._empty_experience_result(
                        question, agent_id, experience_token_budget
                    ),
                    "memory_candidate_suggestions": [],
                    "working_memory": [],
                }
            seeds: dict[str, float] = {}
            entity_scores: dict[str, float] = {}
            entity_chunks: list[str] = []
            entity_report: dict[str, Any] = {"active": False}
            if self._entity_layer_ready:
                try:
                    seeds = self._link_question_entities(conn, question, document_scopes)
                    entity_scores = self._entity_channel(conn, seeds, document_scopes)
                except sqlite3.Error as exc:  # entity layer is an extra channel; never a gate
                    seeds, entity_scores = {}, {}
                    entity_report = {"active": False, "error": type(exc).__name__}
            chunks = self._search_chunks(
                conn,
                question,
                document_scopes,
                limit,
                entity_scores=entity_scores,
                entity_weight=ENTITY_CHANNEL_WEIGHT * max(seeds.values(), default=0.0),
                entity_order_out=entity_chunks,
            )
            if self._entity_layer_ready and "error" not in entity_report:
                entity_report = {"active": bool(entity_chunks), "seeds": len(seeds), "chunks": len(entity_chunks)}
            entities = self._related_entities(
                conn, question, chunks, document_scopes, seeds if self._entity_layer_ready else None
            )
            relations = self._relation_edges(
                conn, entities, chunks, document_scopes, seeds=seeds, entity_chunks=entity_chunks
            )
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
            "status": (
                "partial"
                if experience.get("scan", {}).get("truncated") is True
                else "ok"
            ),
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
                "entity_channel": entity_report,
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
                    json_dumps(encode_vector(vector)),
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
            LIMIT ?
            """,
            (
                agent_id,
                *allowed_scopes,
                *ACTIVE_EXPERIENCE_STATUSES,
                utc_now(),
                *ACTIVE_EXPERIENCE_STATUSES,
                utc_now(),
                MAX_EXPERIENCE_SCAN_ROWS + 1,
            ),
        ).fetchall()
        scan_truncated = len(rows) > MAX_EXPERIENCE_SCAN_ROWS
        rows = rows[:MAX_EXPERIENCE_SCAN_ROWS]
        if not rows:
            result = self._empty_experience_result(question, agent_id, token_budget)
            result["scan"] = {
                "budget": MAX_EXPERIENCE_SCAN_ROWS,
                "rows": 0,
                "truncated": scan_truncated,
            }
            result["status"] = "partial" if scan_truncated else "ok"
            return result

        query_tokens = set(tokenize(question))
        query_vector = self.vector_adapter.embed(question)
        scored: list[dict[str, Any]] = []
        stored_vectors: dict[str, list[float]] = {}
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
            if compatible:
                stored_vectors[item["ticket_id"]] = stored_vector
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
        # Graph spread (stage 4): Personalized PageRank from the direct hits over
        # the free edges (similar_to, mentions_file, co_edited, references). When
        # it runs it IS the graph channel — the entity signal above, if enabled,
        # becomes extra seed mass rather than a second graph channel. When there
        # is no graph around the seeds it returns nothing and the fusion below is
        # exactly the channels that ran before it existed.
        ppr_signal, graph_report = self._experience_ppr_signal(
            conn,
            agent_id=agent_id,
            all_scored=all_scored,
            floor_passed=floor_passed,
            stored_vectors=stored_vectors,
            semantic_floor=semantic_floor,
            entity_signal=graph_signal,
            top_k=top_k,
        )
        if ppr_signal:
            graph_signal = ppr_signal
        scored = list(floor_passed)
        seen_tickets = {item["ticket_id"] for item in scored}
        for item in all_scored:
            if item["ticket_id"] in graph_signal and item["ticket_id"] not in seen_tickets:
                scored.append(item)
                seen_tickets.add(item["ticket_id"])
        if not scored:
            result = self._empty_experience_result(question, agent_id, token_budget)
            result["eligible_count"] = len(rows)
            result["scan"] = {
                "budget": MAX_EXPERIENCE_SCAN_ROWS,
                "rows": len(rows),
                "truncated": scan_truncated,
            }
            result["status"] = "partial" if scan_truncated else "ok"
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
        if ppr_signal:
            # Already in channel order: the seed block first, then what the walk reached.
            graph_order = list(ppr_signal)
        else:
            graph_order = [
                ticket for ticket, _signal in sorted(graph_signal.items(), key=lambda kv: kv[1], reverse=True)
            ]
        lexical_rank = {ticket: index for index, ticket in enumerate(lexical_order)}
        vector_rank = {ticket: index for index, ticket in enumerate(vector_order)}
        graph_rank = {ticket: index for index, ticket in enumerate(graph_order)}
        if ppr_signal:
            graph_weight = self._env_float("AGENTLAS_EXPERIENCE_PPR_WEIGHT", DEFAULT_PPR_WEIGHT)
        elif graph_signal:
            graph_weight = self._env_float("AGENTLAS_EXPERIENCE_GRAPH_WEIGHT", 1.0)
        else:
            graph_weight = 0.0
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
            "status": "partial" if scan_truncated else "ok",
            "query": question,
            "agent_id": agent_id,
            "mode": mode,
            "token_budget": token_budget,
            "total_relevant_tokens": total_tokens,
            "eligible_count": len(rows),
            "relevant_count": len(ranked),
            "selected_count": len(selected),
            "items": selected,
            "scan": {
                "budget": MAX_EXPERIENCE_SCAN_ROWS,
                "rows": len(rows),
                "truncated": scan_truncated,
            },
            "governance": {
                "agent_isolation": "exact",
                "allowed_scopes": allowed_scopes,
                "active_statuses": list(ACTIVE_EXPERIENCE_STATUSES),
                "superseded_hidden": True,
            },
            "fusion": "rrf_lexical_cosine_with_salience_prior",
            "graph": graph_report,
        }

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        try:
            value = float(os.environ.get(name, "") or default)
        except ValueError:
            return default
        return value if math.isfinite(value) and value >= 0 else default

    def _experience_ppr_signal(
        self,
        conn: sqlite3.Connection,
        *,
        agent_id: str,
        all_scored: list[dict[str, Any]],
        floor_passed: list[dict[str, Any]],
        stored_vectors: dict[str, list[float]],
        semantic_floor: float,
        entity_signal: dict[str, float],
        top_k: int,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        """Personalized PageRank over free edges, as ``({ticket: mass}, report)``.

        Seeds are the direct hits (top lexical+vector RRF); the walk spreads
        their mass over similar_to / mentions_file / co_edited / references and
        the tickets it reaches become the third RRF channel. Every failure is
        fail-open: ``({}, report)`` and recall proceeds on its other channels.
        """
        report: dict[str, Any] = {"channel": "ppr", "active": False}
        if os.environ.get("AGENTLAS_EXPERIENCE_PPR", "1") == "0":
            report["reason"] = "disabled"
            return {}, report
        if not floor_passed and not entity_signal:
            report["reason"] = "no-seeds"
            return {}, report
        import time as _time

        started = _time.perf_counter()
        try:
            signal, details = self._experience_ppr_signal_unguarded(
                conn,
                agent_id=agent_id,
                all_scored=all_scored,
                floor_passed=floor_passed,
                stored_vectors=stored_vectors,
                semantic_floor=semantic_floor,
                entity_signal=entity_signal,
                top_k=top_k,
            )
        except Exception as exc:  # noqa: BLE001 — recall must never depend on the graph
            report["reason"] = f"error:{type(exc).__name__}"
            return {}, report
        report.update(details)
        report["active"] = bool(signal)
        report["ms"] = round((_time.perf_counter() - started) * 1000, 2)
        return signal, report

    def _graph_project_root(self) -> Path | None:
        configured = getattr(self.config, "graph_project_root", None)
        if configured:
            return Path(configured).expanduser()
        parent = self.db_path.parent
        if parent.name == ".agentlas":
            return parent.parent
        return None

    def _experience_ppr_signal_unguarded(
        self,
        conn: sqlite3.Connection,
        *,
        agent_id: str,
        all_scored: list[dict[str, Any]],
        floor_passed: list[dict[str, Any]],
        stored_vectors: dict[str, list[float]],
        semantic_floor: float,
        entity_signal: dict[str, float],
        top_k: int,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        eligible = {item["ticket_id"]: item for item in all_scored}
        # Seeds: the same two-channel RRF the fusion uses, top PPR_SEED_COUNT.
        lexical_order = [
            item["ticket_id"]
            for item in sorted(floor_passed, key=lambda value: (value["lexical_score"], value["updated_at"]), reverse=True)
            if item["lexical_score"] > 0.0
        ]
        vector_order = [
            item["ticket_id"]
            for item in sorted(floor_passed, key=lambda value: (value["vector_score"], value["updated_at"]), reverse=True)
            if item["vector_score"] >= semantic_floor
        ]
        seed_score: dict[str, float] = {}
        for order in (lexical_order, vector_order):
            for index, ticket in enumerate(order):
                seed_score[ticket] = seed_score.get(ticket, 0.0) + 1.0 / (RRF_K + index)
        seed_count = max(1, int(self._env_float("AGENTLAS_EXPERIENCE_PPR_SEEDS", PPR_SEED_COUNT)))
        seeds = dict(sorted(seed_score.items(), key=lambda kv: (-kv[1], kv[0]))[:seed_count])
        if entity_signal:
            peak = max(entity_signal.values()) or 1.0
            top_seed = max(seeds.values(), default=1.0 / RRF_K)
            for ticket, value in entity_signal.items():
                if ticket in eligible:
                    seeds[ticket] = seeds.get(ticket, 0.0) + 0.5 * top_seed * value / peak
        if not seeds:
            return {}, {"reason": "no-seeds"}

        graph = graph_spread.TypedGraph()
        node = graph_spread.TICKET_PREFIX

        # similar_to: stored neighborhoods (ingest-time) + curator-era links.
        has_neighbors: set[str] = set()
        try:
            for row in conn.execute(
                "SELECT src_ticket, dst_ticket, weight FROM experience_graph_edges "
                "WHERE agent_id = ? AND relation_type = 'similar_to'",
                (agent_id,),
            ):
                src, dst = row["src_ticket"], row["dst_ticket"]
                has_neighbors.add(src)
                if src != dst and src in eligible and dst in eligible:
                    graph.add(node + src, node + dst, "similar_to", float(row["weight"]))
        except sqlite3.OperationalError:
            pass  # read-only database from before the table existed
        for row in conn.execute(
            "SELECT from_ticket, to_ticket, score FROM memory_links WHERE link_type = 'similar_to'"
        ):
            src, dst = row["from_ticket"], row["to_ticket"]
            if src in eligible and dst in eligible:
                graph.add(node + src, node + dst, "similar_to", float(row["score"] or 0.0))
        # Seeds indexed before neighborhoods were stored: find theirs now, from
        # vectors this query already decoded. Bounded to the seeds.
        missing = [ticket for ticket in seeds if ticket not in has_neighbors and ticket in stored_vectors]
        computed_on_the_fly = 0
        if missing:
            units = {
                ticket: unit
                for ticket, vector in stored_vectors.items()
                for unit in (graph_spread.unit_vector(vector),)
                if unit is not None
            }
            for ticket in missing:
                own = units.get(ticket)
                if own is None:
                    continue
                neighbors = sorted(
                    (
                        (score, other)
                        for other, unit in units.items()
                        if other != ticket
                        for score in (graph_spread.dot(own, unit),)
                        if score >= graph_spread.SIMILAR_EDGE_THRESHOLD
                    ),
                    key=lambda pair: (-pair[0], pair[1]),
                )[: graph_spread.SIMILAR_EDGE_PER_NODE]
                for score, other in neighbors:
                    graph.add(node + ticket, node + other, "similar_to", score)
                computed_on_the_fly += 1

        # Files: what each memory names, joined through the project's ledger
        # (co_edited) and code map (references).
        root = self._graph_project_root()
        code_map = graph_spread.code_map_edges(root)
        units_edited = graph_spread.co_edit_units(root)
        known_files: set[str] = set(code_map.get("files") or ())
        for unit in units_edited:
            known_files |= unit
        resolver = graph_spread.FileResolver(root, known_files)
        definitions = code_map.get("definitions") or {}
        files_by_ticket: dict[str, set[str]] = {}
        tickets_by_file: dict[str, set[str]] = {}
        for ticket, item in eligible.items():
            mentions = {
                resolver.resolve(mention)
                for mention in graph_spread.extract_file_mentions(item["candidate_text"], item.get("source_refs"))
            }
            mentions |= graph_spread.symbol_files(item["candidate_text"], definitions)
            if mentions:
                files_by_ticket[ticket] = mentions
                for path in mentions:
                    tickets_by_file.setdefault(path, set()).add(ticket)
        # A file named by a large share of memories bridges everything to everything.
        hub_cap = max(8, int(len(eligible) * 0.05))
        linked_files = {path for path, tickets in tickets_by_file.items() if len(tickets) <= hub_cap}
        for ticket, paths in files_by_ticket.items():
            for path in paths & linked_files:
                graph.add(node + ticket, graph_spread.FILE_PREFIX + path, "mentions_file")
        if linked_files and units_edited:
            pair_weight: dict[tuple[str, str], float] = {}
            for unit in units_edited:
                shared = sorted(unit & linked_files)
                if len(shared) < 2:
                    continue
                breadth = 1.0 if len(unit) <= graph_spread.MAX_SESSION_FILES else graph_spread.MAX_SESSION_FILES / len(unit)
                for index, left in enumerate(shared):
                    for right in shared[index + 1 :]:
                        pair_weight[(left, right)] = pair_weight.get((left, right), 0.0) + breadth
            for (left, right), count in pair_weight.items():
                graph.add(
                    graph_spread.FILE_PREFIX + left,
                    graph_spread.FILE_PREFIX + right,
                    "co_edited",
                    count / (count + 1.0),
                )
        dependencies = code_map.get("dependencies") or {}
        for path in linked_files:
            for target in dependencies.get(path, ()):  # file-level def/ref edge
                if target in linked_files:
                    graph.add(graph_spread.FILE_PREFIX + path, graph_spread.FILE_PREFIX + target, "references")

        details: dict[str, Any] = {
            "seeds": len(seeds),
            "nodes": graph.node_count,
            "edges": dict(sorted(graph.edge_counts.items())),
            "relation_types": {
                name: {"causal": spec["causal"], "basis": spec["basis"]}
                for name, spec in graph_spread.RELATION_TYPES.items()
                if name in graph.edge_counts
            },
            "seed_neighbors_computed": computed_on_the_fly,
        }
        seed_nodes = {node + ticket: weight for ticket, weight in seeds.items()}
        if not any(seed in graph.adjacency for seed in seed_nodes):
            details["reason"] = "seeds-unconnected"
            return {}, details
        damping = self._env_float("AGENTLAS_EXPERIENCE_PPR_DAMPING", DEFAULT_PPR_DAMPING)
        damping = min(0.95, damping)
        rank = graph_spread.personalized_pagerank(graph.adjacency, seed_nodes, damping=damping)
        details["damping"] = damping
        tickets = {
            key[len(node):]: value
            for key, value in rank.items()
            if key.startswith(node) and value > 0 and key[len(node):] in eligible
        }
        # Channel order: the seed block first, in its own order, then the
        # strongest few tickets the walk reached. Seeds are the direct hits, so
        # they keep the lead they earned — measured: ranking seeds by their PPR
        # mass or leaving them out of the channel let their neighbors overtake
        # them and single-hop recall@5 fell from 96% to 11-45% (LongMemEval-S,
        # 100 questions). With the seed block kept intact, the walk can only
        # fill the slots right after the direct hits, never displace them.
        # RRF is rank-based, so a long tail of weakly reached nodes would all get
        # near-equal credit; only the top few by mass (and at least a fraction of
        # the top seed's mass) enter.
        seed_order = [ticket for ticket, _weight in sorted(seeds.items(), key=lambda kv: (-kv[1], kv[0]))]
        seed_peak = max((tickets.get(ticket, 0.0) for ticket in seeds), default=0.0)
        min_mass = seed_peak * self._env_float("AGENTLAS_EXPERIENCE_PPR_MIN_RELATIVE", PPR_MIN_RELATIVE_MASS)
        reached = sorted(
            (ticket for ticket, value in tickets.items() if ticket not in seeds and value >= min_mass),
            key=lambda ticket: (-tickets[ticket], ticket),
        )
        limit = max(1, int(self._env_float("AGENTLAS_EXPERIENCE_PPR_ADMIT", PPR_ADMITTED)))
        if not reached:
            details["reason"] = "nothing-reached"
            return {}, details
        signal: dict[str, float] = {}
        for ticket in seed_order:
            signal[ticket] = round(tickets.get(ticket, 0.0), 6)
        for ticket in reached[:limit]:
            signal[ticket] = round(tickets[ticket], 6)
        details["reached"] = len(reached)
        details["admitted"] = min(len(reached), limit)
        return signal, details

    @staticmethod
    def _empty_experience_result(question: str, agent_id: str | None, token_budget: int) -> dict[str, Any]:
        return {
            "status": "ok",
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
        neighbors: list[tuple[float, str]] = []
        for row in rows:
            if not self._vector_adapter_matches(row["embedding_adapter"]):
                continue
            other = json_loads(row["embedding_json"], [])
            if len(other) != len(vector):
                continue
            score = max(0.0, cosine_similarity(vector, other))
            if score >= graph_spread.SIMILAR_EDGE_THRESHOLD:
                neighbors.append((score, row["ticket_id"]))
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
        # The graph-spread neighborhood comes out of this same scan for free.
        self._write_similar_neighbors(conn, agent_id=agent_id, ticket_id=ticket_id, neighbors=neighbors)
        return links

    @staticmethod
    def _write_similar_neighbors(
        conn: sqlite3.Connection,
        *,
        agent_id: str,
        ticket_id: str,
        neighbors: list[tuple[float, str]],
        now: str | None = None,
    ) -> int:
        """Replace this ticket's own nearest-neighbor edges (top 5, >= 0.55).

        Edges are stored once per unordered pair; a pair another ticket chose
        survives until that ticket is re-scanned. Returns edges written.
        """
        conn.execute(
            """
            DELETE FROM experience_graph_edges
            WHERE agent_id = ? AND src_ticket = ? AND relation_type = 'similar_to'
            """,
            (agent_id, ticket_id),
        )
        chosen = sorted(neighbors, key=lambda pair: (-pair[0], pair[1]))[: graph_spread.SIMILAR_EDGE_PER_NODE]
        stamp = now or utc_now()
        # Self-row marks "scanned" so a memory with no neighbor above the
        # threshold is not rescanned on every query. Weight 0, never an edge.
        conn.execute(
            """
            INSERT INTO experience_graph_edges(
              agent_id, src_ticket, dst_ticket, relation_type, weight, basis, created_at
            ) VALUES (?, ?, ?, 'similar_to', 0, 'neighborhood_scanned', ?)
            """,
            (agent_id, ticket_id, ticket_id, stamp),
        )
        for score, other in chosen:
            conn.execute(
                """
                INSERT INTO experience_graph_edges(
                  agent_id, src_ticket, dst_ticket, relation_type, weight, basis, created_at
                ) VALUES (?, ?, ?, 'similar_to', ?, 'vector_cosine', ?)
                ON CONFLICT(agent_id, src_ticket, dst_ticket, relation_type) DO UPDATE SET
                  weight = excluded.weight, created_at = excluded.created_at
                """,
                (agent_id, ticket_id, other, round(float(score), 6), stamp),
            )
        return len(chosen)

    def backfill_experience_graph(
        self,
        *,
        agent_id: str | None = None,
        only_missing: bool = True,
        budget_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Build the similar_to neighborhood for memories indexed before it existed.

        Rows ingested after this table was added already carry their edges;
        older rows get them here. O(n^2) cosine in pure python, so it is meant
        for idle/background time (dreaming, index refresh), bounded by
        ``budget_seconds`` and resumable: ``only_missing`` skips tickets that
        already chose their neighbors.
        """
        import time as _time

        deadline = _time.monotonic() + budget_seconds if budget_seconds else None
        status_marks = ", ".join(["?"] * len(ACTIVE_EXPERIENCE_STATUSES))
        processed = 0
        written = 0
        partial = False
        with closing(self.connect()) as conn, conn:
            params: list[Any] = [*ACTIVE_EXPERIENCE_STATUSES]
            agent_clause = ""
            if agent_id is not None:
                agent_clause = "AND agent_id = ?"
                params.append(agent_id)
            rows = conn.execute(
                f"""
                SELECT ticket_id, agent_id, privacy_scope, embedding_adapter, embedding_json
                FROM memory_candidates
                WHERE memory_kind != 'candidate' AND status IN ({status_marks}) {agent_clause}
                ORDER BY agent_id, ticket_id
                """,
                params,
            ).fetchall()
            done: set[str] = set()
            if only_missing:
                done = {
                    row[0]
                    for row in conn.execute(
                        "SELECT DISTINCT src_ticket FROM experience_graph_edges WHERE relation_type = 'similar_to'"
                    )
                }
            groups: dict[tuple[str, str], list[tuple[str, list[float]]]] = {}
            for row in rows:
                if not self._vector_adapter_matches(row["embedding_adapter"]):
                    continue
                unit = graph_spread.unit_vector(json_loads(row["embedding_json"], []))
                if unit is None:
                    continue
                groups.setdefault((row["agent_id"], row["privacy_scope"]), []).append((row["ticket_id"], unit))
            now = utc_now()
            for (group_agent, _scope), members in groups.items():
                for ticket, unit in members:
                    if ticket in done:
                        continue
                    if deadline is not None and _time.monotonic() >= deadline:
                        partial = True
                        break
                    neighbors = [
                        (score, other)
                        for other, other_unit in members
                        if other != ticket
                        for score in (graph_spread.dot(unit, other_unit),)
                        if score >= graph_spread.SIMILAR_EDGE_THRESHOLD
                    ]
                    written += self._write_similar_neighbors(
                        conn, agent_id=group_agent, ticket_id=ticket, neighbors=neighbors, now=now
                    )
                    processed += 1
                if partial:
                    break
        return {"status": "partial" if partial else "ok", "processed": processed, "edges_written": written}

    def graph_entity(self, name: str, allowed_scopes: Iterable[str] | None = None) -> dict[str, Any]:
        document_scopes = list(allowed_scopes) if allowed_scopes is not None else ["public", "internal"]
        with closing(self.connect()) as conn, conn:
            stale_sources = self._stale_source_rows(conn)
            if stale_sources:
                return {
                    "status": "stale_index",
                    "error": self._stale_source_error(stale_sources),
                    "stale_sources": stale_sources,
                    "entity": None,
                    "aliases": [],
                    "relations": [],
                    "evidence_chunks": [],
                }
            entity = self._find_entity(conn, name)
            if entity is None:
                return {"status": "ok", "entity": None, "aliases": [], "relations": [], "evidence_chunks": []}
            relations = self._relations_for_entity(conn, entity["entity_id"], document_scopes)
            mention_ids: list[str] = []
            if self._entity_layer_ready and document_scopes:
                scope_marks = ", ".join(["?"] * len(document_scopes))
                mention_ids = [
                    row["chunk_id"]
                    for row in conn.execute(
                        f"""
                        SELECT m.chunk_id FROM entity_mentions m
                        JOIN chunks c ON c.chunk_id = m.chunk_id
                        JOIN sources s ON s.source_id = c.source_id
                        WHERE m.entity_id = ? AND c.privacy_scope IN ({scope_marks})
                          AND s.privacy_scope = c.privacy_scope
                        ORDER BY m.chunk_id LIMIT 10
                        """,
                        (entity["entity_id"], *document_scopes),
                    )
                ]
            if not relations and not mention_ids:
                # Entity and alias rows are globally deduplicated, so existence
                # alone is not safe to expose. A caller sees an entity only when
                # a relation or a mention has provenance in an allowed scope.
                return {"status": "ok", "entity": None, "aliases": [], "relations": [], "evidence_chunks": []}
            chunk_ids = sorted(
                {relation["evidence_chunk_id"] for relation in relations if relation["evidence_chunk_id"]}
                | set(mention_ids)
            )
            evidence = self._chunks_by_ids(conn, chunk_ids, document_scopes)
            aliases = [
                row["alias"]
                for row in conn.execute("SELECT alias FROM entity_aliases WHERE entity_id = ? ORDER BY alias", (entity["entity_id"],))
            ]
        return {"status": "ok", "entity": entity, "aliases": aliases, "relations": relations, "evidence_chunks": evidence}

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
            if self._entity_layer_ready:
                counts["entity_mentions"] = conn.execute("SELECT count(*) FROM entity_mentions").fetchone()[0]
            migration = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            unsupported = conn.execute(
                "SELECT count(*) FROM sources WHERE parser_status = 'unsupported_pending_adapter'"
            ).fetchone()[0]
            stale_sources = self._stale_source_rows(conn)
        direct_write_blocked = False
        try:
            self.write_durable_memory("verify", {"probe": True})
        except DirectDurableMemoryWriteBlocked:
            direct_write_blocked = True
        status = (
            "pass"
            if integrity == "ok"
            and migration == SCHEMA_VERSION
            and direct_write_blocked
            and not stale_sources
            else "fail"
        )
        return {
            "status": status,
            "schema_version": migration,
            "integrity_check": integrity,
            "counts": counts,
            "unsupported_pending_adapters": unsupported,
            "stale_sources": stale_sources,
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
        tables = list(STORAGE_TABLES)
        with closing(self.connect()) as conn, conn:
            for table in tables:
                data[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
        destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "ok", "export_path": str(destination), "tables": tables}

    def import_json(self, source: str | Path) -> dict[str, Any]:
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise ValueError("ontology import requires a regular JSON file")
        if source.stat().st_size > MAX_STORAGE_IMPORT_BYTES:
            raise ValueError(f"ontology import exceeds {MAX_STORAGE_IMPORT_BYTES} bytes")
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("ontology import must be a JSON object")
        unknown_tables = sorted(set(data) - set(STORAGE_TABLES))
        missing_tables = sorted(set(STORAGE_TABLES) - set(data))
        if unknown_tables or missing_tables:
            raise ValueError(
                f"ontology import table set mismatch; unknown={unknown_tables}, missing={missing_tables}"
            )
        total_rows = 0
        imported_counts: dict[str, int] = {}
        with closing(self.connect()) as conn, conn:
            table_columns = {
                table: [str(row["name"]) for row in conn.execute(f'PRAGMA table_info("{table}")')]
                for table in STORAGE_TABLES
            }
            for table in STORAGE_TABLES:
                rows = data[table]
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError(f"ontology import table {table} must be a list of objects")
                allowed = set(table_columns[table])
                # Exports written before the entity layer carry relations
                # without basis/evidence_ref; they default like the migration.
                optional = {"basis": entity_layer.BASIS_ASSERTED, "evidence_ref": None} if table == "relations" else {}
                for row in rows:
                    for column, default in optional.items():
                        if column in allowed and column not in row:
                            row[column] = default
                    if set(row) != allowed:
                        raise ValueError(
                            f"ontology import columns for {table} do not match runtime schema"
                        )
                total_rows += len(rows)
                if total_rows > 1_000_000:
                    raise ValueError("ontology import exceeds 1000000 rows")

            for table in reversed(STORAGE_TABLES):
                conn.execute(f'DELETE FROM "{table}"')
            for table in STORAGE_TABLES:
                rows = data[table]
                if not rows:
                    imported_counts[table] = 0
                    continue
                keys = table_columns[table]
                placeholders = ", ".join(["?"] * len(keys))
                columns = ", ".join(f'"{key}"' for key in keys)
                for row in rows:
                    conn.execute(
                        f'INSERT INTO "{table}"({columns}) VALUES ({placeholders})',
                        tuple(row[key] for key in keys),
                    )
                imported_counts[table] = len(rows)
            self._rebuild_fts_rows(conn)
            # Entity mentions/keys are derived, not exported: the next ingest
            # re-extracts every imported chunk.
            conn.execute("DELETE FROM runtime_adapters WHERE name = ?", (ENTITY_LAYER_ADAPTER,))
            foreign_key_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if foreign_key_issues or integrity != "ok":
                raise ValueError("ontology import failed database integrity verification")
        return {
            "status": "ok",
            "import_path": str(source),
            "tables": list(STORAGE_TABLES),
            "rows": imported_counts,
        }

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
            document = entity_layer.document_path(raw[:600].decode("utf-8", errors="ignore"), path.name)
            field_chunks: list[dict[str, Any]] = []
            for index, record in enumerate(self._chunk_records(parsed.records), start=0):
                chunk = self._write_chunk(conn, source_id, index, record, access_scope, lineage)
                chunks_written += 1 if chunk["inserted"] else 0
                entity_result = self._extract_and_write_graph(conn, chunk["chunk"], record, document=document)
                entities_written += entity_result["entities_written"]
                relations_written += entity_result["relations_written"]
                if (record.span or {}).get("kind") == "json_path":
                    field_chunks.append(chunk["chunk"])
            entity_result = self._write_declared_object_relations(conn, field_chunks)
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
                json_dumps(encode_vector(vector)),
                now,
                now,
            ),
        ).rowcount == 1
        conn.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (chunk_id,))
        conn.execute("INSERT INTO chunk_fts(chunk_id, text) VALUES (?, ?)", (chunk_id, record.text))
        row = conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return {"inserted": inserted, "chunk": self._chunk_row(row)}

    def _extract_and_write_graph(
        self,
        conn: sqlite3.Connection,
        chunk: dict[str, Any],
        record: ParsedRecord | None = None,
        *,
        document: str | None = None,
    ) -> dict[str, int]:
        """Per-chunk entity extraction: typed code mentions + declared fields.

        Corpus-level edges (code map, ledger, co-occurrence) are not written
        here; :meth:`refresh_entity_graph` derives them once per ingest.
        """
        entities_written = 0
        relations_written = 0
        text = chunk["text"]
        if self._entity_layer_ready:
            code = self._project_code_index()
            document = document or str(chunk.get("source_id") or "document")
            doc_type = "file" if document in code.mapped else "doc"
            doc_id, doc_new = self._ensure_code_entity(conn, doc_type, document)
            entities_written += 1 if doc_new else 0
            rows = [(doc_id, chunk["chunk_id"], chunk["source_id"], "self")]
            for entity_type, name, in_code in entity_layer.extract_mentions_with_context(text, code):
                entity_id, created = self._ensure_code_entity(conn, entity_type, name)
                entities_written += 1 if created else 0
                if entity_id != doc_id:
                    # role 'code': named only inside a fenced block — linkable,
                    # but not counted as prose co-occurrence.
                    role = "code" if in_code else "mention"
                    rows.append((entity_id, chunk["chunk_id"], chunk["source_id"], role))
            conn.executemany(
                "INSERT OR IGNORE INTO entity_mentions(entity_id, chunk_id, source_id, role) VALUES (?, ?, ?, ?)",
                rows,
            )
        # Declared record fields (JSON/CSV/spreadsheet/frontmatter: name/team +
        # owner/depends_on) are data, not prose; they stay. English sentence
        # verb patterns ("A depends on B") are not extracted any more.
        for subject, relation_type, obj, confidence in extract_declared_relations(text):
            subject_id, subject_new = self._ensure_entity(conn, subject)
            object_id, object_new = self._ensure_entity(conn, obj)
            entities_written += 1 if subject_new else 0
            entities_written += 1 if object_new else 0
            relations_written += self._insert_relation(
                conn,
                subject_id,
                object_id,
                relation_type,
                confidence,
                basis=entity_layer.BASIS_DECLARED,
                chunk=chunk,
            )
        return {"entities_written": entities_written, "relations_written": relations_written}

    def _write_declared_object_relations(
        self, conn: sqlite3.Connection, field_chunks: list[dict[str, Any]]
    ) -> dict[str, int]:
        """JSON objects are parsed one field per record (``$.team: X``), so a
        declared ``team``/``owner``/``depends_on`` triple never shares a chunk.
        Group sibling fields by their parent path; the evidence of each
        relation is the chunk of the field that declares it."""
        entities_written = relations_written = 0
        groups: dict[str, list[dict[str, Any]]] = {}
        for chunk in field_chunks:
            json_path = str((chunk.get("source_span") or {}).get("path") or "")
            parent = json_path.rsplit(".", 1)[0] if "." in json_path else json_path
            groups.setdefault(parent, []).append(chunk)
        for chunks in groups.values():
            if len(chunks) < 2:
                continue
            by_field: dict[str, dict[str, Any]] = {}
            for chunk in chunks:
                field = str((chunk.get("source_span") or {}).get("path") or "").rsplit(".", 1)[-1]
                by_field.setdefault(field, chunk)
            text = "\n".join(chunk["text"] for chunk in chunks)
            for subject, relation_type, obj, confidence in extract_declared_relations(text):
                evidence = by_field.get("depends_on" if relation_type == "depends_on" else "owner") or chunks[0]
                subject_id, subject_new = self._ensure_entity(conn, subject)
                object_id, object_new = self._ensure_entity(conn, obj)
                entities_written += int(subject_new) + int(object_new)
                relations_written += self._insert_relation(
                    conn, subject_id, object_id, relation_type, confidence,
                    basis=entity_layer.BASIS_DECLARED, chunk=evidence,
                )
        return {"entities_written": entities_written, "relations_written": relations_written}

    def _insert_relation(
        self,
        conn: sqlite3.Connection,
        subject_id: str,
        object_id: str,
        relation_type: str,
        confidence: float,
        *,
        basis: str,
        chunk: dict[str, Any] | None = None,
        evidence_ref: str | None = None,
    ) -> int:
        if subject_id == object_id:
            return 0
        now = utc_now()
        if chunk is not None:
            relation_id = stable_hash(f"relation:{subject_id}:{relation_type}:{object_id}:{chunk['chunk_id']}")
            values = (
                relation_id, subject_id, object_id, relation_type, confidence,
                chunk["chunk_id"], chunk["source_id"], chunk["privacy_scope"],
                json_dumps(chunk.get("source_lineage") or {}), now, now, now, basis, evidence_ref,
            )
        else:
            if basis not in entity_layer.STRUCTURAL_BASES:
                raise ValueError("only code_map/ledger relations may omit an evidence chunk")
            relation_id = stable_hash(f"relation:{subject_id}:{relation_type}:{object_id}:{basis}")
            values = (
                relation_id, subject_id, object_id, relation_type, confidence,
                None, None, STRUCTURAL_SCOPE,
                json_dumps({"basis": basis}), now, now, now, basis, evidence_ref,
            )
        return conn.execute(
            """
            INSERT OR IGNORE INTO relations(
              relation_id, subject_entity_id, object_entity_id, relation_type, confidence,
              evidence_chunk_id, source_id, privacy_scope, source_lineage_json, valid_from, valid_to,
              observed_at, status, created_at, updated_at, basis, evidence_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, 'active', ?, ?, ?, ?)
            """,
            values,
        ).rowcount

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
        if not inserted:
            existing = conn.execute("SELECT entity_id FROM entities WHERE canonical_name = ?", (canonical,)).fetchone()
            if existing is not None:
                entity_id = existing["entity_id"]
        conn.execute(
            "INSERT OR IGNORE INTO entity_aliases(alias, normalized_alias, entity_id, created_at) VALUES (?, ?, ?, ?)",
            (canonical, key, entity_id, now),
        )
        if self._entity_layer_ready:
            conn.executemany(
                "INSERT OR IGNORE INTO entity_keys(key, entity_id, kind) VALUES (?, ?, ?)",
                [(canonical.lower(), entity_id, "exact"), (key, entity_id, "words")] if key else [],
            )
        return entity_id, inserted

    def _ensure_code_entity(self, conn: sqlite3.Connection, entity_type: str, name: str) -> tuple[str, bool]:
        """Entity by exact canonical name (code names are case-sensitive)."""

        row = conn.execute(
            "SELECT entity_id, entity_type FROM entities WHERE canonical_name = ?", (name,)
        ).fetchone()
        if row is not None:
            # A name first seen as a bare code id becomes a symbol once the
            # code map defines it.
            if entity_type in ("symbol", "file") and row["entity_type"] in ("code_id", "path", "doc", "concept"):
                conn.execute(
                    "UPDATE entities SET entity_type = ?, updated_at = ? WHERE entity_id = ?",
                    (entity_type, utc_now(), row["entity_id"]),
                )
            return row["entity_id"], False
        entity_id = stable_hash(f"entity:{entity_type}:{name}")
        now = utc_now()
        inserted = conn.execute(
            """
            INSERT OR IGNORE INTO entities(entity_id, canonical_name, entity_type, status, confidence, created_at, updated_at)
            VALUES (?, ?, ?, 'active', 0.9, ?, ?)
            """,
            (entity_id, name, entity_type, now, now),
        ).rowcount == 1
        key = normalized_key(name)
        if key:
            conn.execute(
                "INSERT OR IGNORE INTO entity_aliases(alias, normalized_alias, entity_id, created_at) VALUES (?, ?, ?, ?)",
                (name, key, entity_id, now),
            )
        conn.executemany(
            "INSERT OR IGNORE INTO entity_keys(key, entity_id, kind) VALUES (?, ?, ?)",
            [(value, entity_id, kind) for value, kind in entity_layer.entity_keys(entity_type, name)],
        )
        return entity_id, inserted

    # --- corpus-level entity graph -------------------------------------------

    def _project_code_index(self) -> entity_layer.CodeIndex:
        payload = graph_spread.code_map_edges(self._graph_project_root())
        snapshot = str(payload.get("snapshotId") or "") if payload else ""
        cached = self._code_index
        if cached is None or cached.snapshot_id != snapshot or (not snapshot and cached.available != bool(payload)):
            cached = entity_layer.CodeIndex(payload)
            self._code_index = cached
        return cached

    def refresh_entity_graph(self) -> dict[str, Any]:
        """Re-derive code-map, ledger and co-occurrence edges when their inputs
        changed (and re-extract every chunk once per extractor version)."""

        if self.config.read_only:
            raise RuntimeError("refresh_entity_graph requires a writable runtime")
        with closing(self.connect()) as conn, conn:
            report = self._refresh_entity_graph_guarded(conn)
            self._prune_orphan_entities(conn)
        return report

    def _refresh_entity_graph_guarded(self, conn: sqlite3.Connection) -> dict[str, Any]:
        """Fail-open wrapper: a broken code map or ledger never fails an ingest."""

        if not self._entity_layer_ready:
            return {"status": "skipped", "reason": "entity_layer_unavailable"}
        conn.execute("SAVEPOINT entity_graph_refresh")
        try:
            report = self._refresh_entity_graph(conn)
        except Exception as exc:  # noqa: BLE001 - document retrieval must not depend on the graph
            conn.execute("ROLLBACK TO entity_graph_refresh")
            conn.execute("RELEASE entity_graph_refresh")
            return {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        conn.execute("RELEASE entity_graph_refresh")
        return report

    def _entity_graph_state(self, conn: sqlite3.Connection) -> dict[str, Any]:
        row = conn.execute(
            "SELECT config_json FROM runtime_adapters WHERE name = ?", (ENTITY_LAYER_ADAPTER,)
        ).fetchone()
        return json_loads(row["config_json"], {}) if row is not None else {}

    def _refresh_entity_graph(self, conn: sqlite3.Connection) -> dict[str, Any]:
        import time as _time

        started = _time.perf_counter()
        state = self._entity_graph_state(conn)
        root = self._graph_project_root()
        code = self._project_code_index()
        ledger_version = graph_spread._file_version(root / graph_spread.CONTACT_LEDGER_RELATIVE) if root else None
        report: dict[str, Any] = {"status": "ok", "extractor": entity_layer.EXTRACTOR_VERSION}
        reextract = state.get("extractor") != entity_layer.EXTRACTOR_VERSION
        if reextract:
            report["reextracted_chunks"] = self._reextract_all_chunks(conn)
        structural_key = f"{code.snapshot_id}|{list(ledger_version) if ledger_version else ''}"
        if reextract or state.get("structural") != structural_key:
            report["structural"] = self._write_structural_edges(conn, code, root)
        signature = list(conn.execute("SELECT count(*), coalesce(max(rowid), 0) FROM entity_mentions").fetchone())
        signature.append(conn.execute("SELECT count(*) FROM chunks").fetchone()[0])
        if reextract or state.get("mentions") != signature or "structural" in report:
            report["co_occurs"] = self._write_cooccurrence_edges(conn)
        report["seconds"] = round(_time.perf_counter() - started, 3)
        new_state = {
            "schema": "ontology-entity-layer.v1",
            "extractor": entity_layer.EXTRACTOR_VERSION,
            "structural": structural_key,
            "mentions": signature,
            "code_map_snapshot": code.snapshot_id,
        }
        if new_state != state:
            self._upsert_runtime_adapter(
                conn,
                name=ENTITY_LAYER_ADAPTER,
                kind="graph",
                status="available",
                config_json=json_dumps(new_state),
            )
        report["changed"] = sorted(key for key in ("reextracted_chunks", "structural", "co_occurs") if key in report)
        return report

    def _reextract_all_chunks(self, conn: sqlite3.Connection) -> int:
        """One-time (per extractor version) backfill of every stored chunk."""

        conn.execute("DELETE FROM entity_mentions")
        bases = ", ".join(f"'{basis}'" for basis in entity_layer.EXTRACTED_BASES)
        conn.execute(f"DELETE FROM relations WHERE basis IN ({bases})")
        documents: dict[str, str] = {}
        for row in conn.execute(
            """
            SELECT c.source_id, c.text, s.display_name
            FROM chunks c JOIN sources s ON s.source_id = c.source_id
            WHERE c.chunk_index = 0
            """
        ):
            documents[row["source_id"]] = entity_layer.document_path(row["text"], row["display_name"])
        count = 0
        rows = conn.execute(
            "SELECT chunk_id, source_id, text, privacy_scope, source_lineage_json, source_span_json "
            "FROM chunks ORDER BY source_id, chunk_index"
        ).fetchall()
        field_chunks: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            chunk = {
                "chunk_id": row["chunk_id"],
                "source_id": row["source_id"],
                "text": row["text"],
                "privacy_scope": row["privacy_scope"],
                "source_lineage": json_loads(row["source_lineage_json"], {}),
                "source_span": json_loads(row["source_span_json"], {}),
            }
            self._extract_and_write_graph(conn, chunk, document=documents.get(row["source_id"]))
            if chunk["source_span"].get("kind") == "json_path":
                field_chunks.setdefault(row["source_id"], []).append(chunk)
            count += 1
        for chunks in field_chunks.values():
            self._write_declared_object_relations(conn, chunks)
        return count

    def _write_structural_edges(
        self,
        conn: sqlite3.Connection,
        code: entity_layer.CodeIndex,
        root: Path | None,
    ) -> dict[str, int]:
        structural = ", ".join(f"'{basis}'" for basis in entity_layer.STRUCTURAL_BASES)
        conn.execute(f"DELETE FROM relations WHERE basis IN ({structural}) AND evidence_chunk_id IS NULL")
        counts = {"defined_in": 0, "imported_by": 0, "read_by": 0, "co_edited": 0}
        if code.available:
            snapshot_ref = f"code-map:{code.snapshot_id}" if code.snapshot_id else "code-map"
            for low in sorted(code.definitions):
                files = code.definitions[low]
                name = code.symbol_case.get(low, low)
                if not entity_layer.code_shaped_name(name) or len(files) > entity_layer.DEFINITION_MAX_FILES:
                    continue
                symbol_id, _ = self._ensure_code_entity(conn, "symbol", name)
                for path in files:
                    file_id, _ = self._ensure_code_entity(conn, "file", path)
                    counts["defined_in"] += self._insert_relation(
                        conn, symbol_id, file_id, "defined_in", 0.95,
                        basis=entity_layer.BASIS_CODE_MAP, evidence_ref=snapshot_ref,
                    )
            for dependency, importer, relation in code.edges:
                if relation != "imports":
                    continue
                # {from: X, to: Y, relation: imports} means Y imports X.
                dependency_id, _ = self._ensure_code_entity(conn, "file", dependency)
                importer_id, _ = self._ensure_code_entity(conn, "file", importer)
                counts["imported_by"] += self._insert_relation(
                    conn, dependency_id, importer_id, "imported_by", 0.9,
                    basis=entity_layer.BASIS_CODE_MAP, evidence_ref=snapshot_ref,
                )
            if root is not None:
                # The code map indexes identifiers, not string literals, so
                # "which code reads AGENTLAS_X" had no edge (measured 1/3).
                scan_ref = f"code-scan:{code.snapshot_id}" if code.snapshot_id else "code-scan"
                for name, files in sorted(entity_layer.scan_env_reads(root, code.mapped).items()):
                    env_id, _ = self._ensure_code_entity(conn, "env_var", name)
                    for path in sorted(files)[:25]:
                        file_id, _ = self._ensure_code_entity(conn, "file", path)
                        counts["read_by"] += self._insert_relation(
                            conn, env_id, file_id, "read_by", 0.9,
                            basis=entity_layer.BASIS_CODE_SCAN, evidence_ref=scan_ref,
                        )
        pairs = entity_layer.co_edit_pairs(graph_spread.co_edit_units(root), graph_spread.MAX_SESSION_FILES)
        for (left, right), units in sorted(pairs.items()):
            if units < entity_layer.CO_EDIT_MIN_UNITS:
                continue
            left_id, _ = self._ensure_code_entity(conn, "file" if left in code.mapped else "path", left)
            right_id, _ = self._ensure_code_entity(conn, "file" if right in code.mapped else "path", right)
            counts["co_edited"] += self._insert_relation(
                conn, left_id, right_id, "co_edited", round(min(1.0, units / 5.0), 3),
                basis=entity_layer.BASIS_LEDGER, evidence_ref=f"contact-ledger:{units}-units",
            )
        return counts

    def _write_cooccurrence_edges(self, conn: sqlite3.Connection) -> int:
        conn.execute("DELETE FROM relations WHERE basis = ?", (entity_layer.BASIS_CORRELATION,))
        by_scope: dict[str, dict[str, set[str]]] = {}
        entity_type: dict[str, str] = {}
        for row in conn.execute(
            """
            SELECT m.chunk_id, m.entity_id, e.entity_type, c.privacy_scope
            FROM entity_mentions m
            JOIN entities e ON e.entity_id = m.entity_id
            JOIN chunks c ON c.chunk_id = m.chunk_id
            WHERE m.role = 'mention'
            """
        ):
            by_scope.setdefault(row["privacy_scope"], {}).setdefault(row["chunk_id"], set()).add(row["entity_id"])
            entity_type[row["entity_id"]] = row["entity_type"]
        chunk_totals = {
            row[0]: row[1] for row in conn.execute("SELECT privacy_scope, count(*) FROM chunks GROUP BY privacy_scope")
        }
        written = 0
        for scope, chunk_entities in sorted(by_scope.items()):
            edges = entity_layer.cooccurrence_edges(
                chunk_entities, entity_type, total_chunks=chunk_totals.get(scope)
            )
            evidence = {chunk_id for *_rest, chunk_id in edges}
            chunks: dict[str, dict[str, Any]] = {}
            evidence_list = sorted(evidence)
            for index in range(0, len(evidence_list), 500):
                part = evidence_list[index : index + 500]
                marks = ", ".join(["?"] * len(part))
                for row in conn.execute(
                    f"SELECT chunk_id, source_id, privacy_scope, source_lineage_json FROM chunks WHERE chunk_id IN ({marks})",
                    tuple(part),
                ):
                    chunks[row["chunk_id"]] = {
                        "chunk_id": row["chunk_id"],
                        "source_id": row["source_id"],
                        "privacy_scope": row["privacy_scope"],
                        "source_lineage": json_loads(row["source_lineage_json"], {}),
                    }
            for left, right, npmi, chunk_id in edges:
                chunk = chunks.get(chunk_id)
                if chunk is None:
                    continue
                written += self._insert_relation(
                    conn, left, right, "co_occurs", npmi,
                    basis=entity_layer.BASIS_CORRELATION, chunk=chunk,
                )
        return written

    def _search_chunks(
        self,
        conn: sqlite3.Connection,
        question: str,
        scopes: list[str],
        limit: int,
        entity_scores: dict[str, float] | None = None,
        entity_weight: float = 1.0,
        entity_order_out: list[str] | None = None,
    ) -> list[dict[str, Any]]:
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
        # Third channel: chunks that mention the question's entities or their
        # one-hop neighbours (code-map definitions, importers, co-edits). Its
        # own order breaks entity-score ties by text relevance — a known item
        # that names a common entity must not lose to an arbitrary chunk id
        # (measured on holdout known-item samples). Entity-only chunks never
        # join the lexical/vector ranks, so those two channels are unchanged.
        entity_rank: dict[str, int] = {}
        if entity_scores:
            extra: dict[str, dict[str, Any]] = {}
            missing = [chunk_id for chunk_id in entity_scores if chunk_id not in pool]
            for index in range(0, len(missing), 400):
                part = missing[index : index + 400]
                marks = ", ".join(["?"] * len(part))
                for row in conn.execute(
                    f"""
                    SELECT c.*, s.uri AS source_uri, s.source_type
                    FROM chunks c JOIN sources s ON s.source_id = c.source_id
                    WHERE c.chunk_id IN ({marks}) AND c.privacy_scope IN ({scope_marks})
                      AND s.privacy_scope = c.privacy_scope
                    """,
                    (*part, *scopes),
                ):
                    item = self._chunk_row(row)
                    item["full_text_score"] = 0.0
                    item["vector_score"] = max(
                        0.0, cosine_similarity(query_vector, json_loads(row["vector_json"], []))
                    )
                    extra[row["chunk_id"]] = item
            candidates = [chunk_id for chunk_id in entity_scores if chunk_id in pool or chunk_id in extra]
            ordered = sorted(
                candidates,
                key=lambda chunk_id: (
                    -round(entity_scores[chunk_id], 9),
                    fts_rank.get(chunk_id, RRF_MISSING_RANK),
                    -(pool.get(chunk_id) or extra[chunk_id])["vector_score"],
                    chunk_id,
                ),
            )[:MAX_ENTITY_CHANNEL]
            for index, chunk_id in enumerate(ordered):
                entity_rank[chunk_id] = index
                if chunk_id not in pool:
                    pool[chunk_id] = extra[chunk_id]
            if entity_order_out is not None:
                entity_order_out.extend(ordered)
        relevant: list[dict[str, Any]] = []
        for chunk_id, item in pool.items():
            if (
                chunk_id not in fts_rank
                and chunk_id not in entity_rank
                and item.get("full_text_score", 0.0) <= 0.0
                and (
                    item["vector_score"] < vector_floor
                    or item["vector_score"] < best_vector_score * VECTOR_RELATIVE_FLOOR
                )
            ):
                continue
            item["score"] = round(
                1.0 / (RRF_K + fts_rank.get(chunk_id, RRF_MISSING_RANK))
                + 1.0 / (RRF_K + vector_rank.get(chunk_id, RRF_MISSING_RANK))
                + (entity_weight / (RRF_K + entity_rank[chunk_id]) if chunk_id in entity_rank else 0.0),
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

    def _relation_scope_sql(self, scope_marks: str) -> tuple[str, str]:
        """(joins, predicate) that admit a relation only with proven scope.

        Chunk-evidenced edges must agree with their chunk and source (as
        always). Structural code-map/ledger edges have no chunk; they are
        admitted by their pinned scope alone.
        """
        if not self._entity_layer_ready:
            joins = (
                "JOIN chunks c ON c.chunk_id = r.evidence_chunk_id "
                "JOIN sources src ON src.source_id = r.source_id"
            )
            predicate = (
                f"r.privacy_scope IN ({scope_marks}) AND c.source_id = r.source_id "
                "AND c.privacy_scope = r.privacy_scope AND src.privacy_scope = r.privacy_scope"
            )
            return joins, predicate
        structural = ", ".join(f"'{basis}'" for basis in entity_layer.STRUCTURAL_BASES)
        joins = (
            "LEFT JOIN chunks c ON c.chunk_id = r.evidence_chunk_id "
            "LEFT JOIN sources src ON src.source_id = r.source_id"
        )
        predicate = (
            f"r.privacy_scope IN ({scope_marks}) AND ("
            f"(r.evidence_chunk_id IS NULL AND r.basis IN ({structural}))"
            " OR (c.chunk_id IS NOT NULL AND c.source_id = r.source_id"
            " AND c.privacy_scope = r.privacy_scope AND src.privacy_scope = r.privacy_scope))"
        )
        return joins, predicate

    def _link_question_entities(
        self,
        conn: sqlite3.Connection,
        question: str,
        allowed_scopes: list[str],
    ) -> dict[str, float]:
        """Question -> entity seeds ``{entity_id: weight}``.

        Code-shaped tokens (``_ . /``, camelCase, CONSTANT_CASE, /commands) are
        matched exactly against entity keys, a partial path by unique suffix,
        and the word-split keys ("graph spread") as whole word n-grams, so an
        English sentence reaches a code name. Plain words are not linked on
        their own (over-linking). Korean questions link through the ASCII
        names they contain. Declared entities ("Project Helios") still link by
        their exact name.
        """
        if not allowed_scopes or not self._entity_layer_ready:
            return {}
        ordered: "dict[str, float]" = {}

        def add(entity_id: str, weight: float) -> None:
            if entity_id not in ordered:
                ordered[entity_id] = weight

        word_text = question
        for token in entity_layer.question_tokens(question):
            low = token.lower()
            candidates = list(dict.fromkeys([low, low.rstrip("()"), low.rstrip(".")]))
            marks = ", ".join(["?"] * len(candidates))
            rows = conn.execute(
                f"SELECT entity_id FROM entity_keys WHERE key IN ({marks}) AND kind != 'words' ORDER BY entity_id",
                tuple(candidates),
            ).fetchall()
            for row in rows:
                add(row["entity_id"], 1.0)
            if rows:
                # A linked name is not also a phrase: "ensure_access_token"
                # must not link `_access_token` through "access token".
                word_text = word_text.replace(token, " | ")
            if not rows and "/" in low.strip("/"):
                suffix = low.strip("/").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                hits = conn.execute(
                    "SELECT entity_id FROM entities WHERE entity_type IN ('file', 'doc', 'path') "
                    "AND lower(canonical_name) LIKE ? ESCAPE '\\' LIMIT 2",
                    ("%/" + suffix,),
                ).fetchall()
                if len(hits) == 1:
                    add(hits[0]["entity_id"], 1.0)
        grams = [
            gram
            for segment in word_text.split("|")
            for gram in entity_layer.question_word_ngrams(segment)
        ]
        for index in range(0, len(grams), 200):
            part = grams[index : index + 200]
            marks = ", ".join(["?"] * len(part))
            for row in conn.execute(
                f"SELECT entity_id FROM entity_keys WHERE key IN ({marks}) AND kind = 'words' ORDER BY entity_id",
                tuple(part),
            ):
                # An English phrase that happens to spell a code name is weaker
                # evidence than the code name itself.
                add(row["entity_id"], WORDS_SEED_WEIGHT)
        for phrase in re_find_title_phrases(question):
            words = phrase.split()
            # "Project Helios Memory Curator" names two declared entities.
            spans = [phrase] + [
                " ".join(words[start : start + size])
                for size in range(len(words) - 1, 1, -1)
                for start in range(0, len(words) - size + 1)
            ]
            for name in spans:
                entity = self._find_entity(conn, name)
                # Title-Case prose names only declared entities: "Agentlas Hub"
                # in a sentence is not the /agentlas-hub command (measured: that
                # loose match displaced a known-item answer).
                if entity is not None and entity["entity_type"] not in CODE_ENTITY_TYPES:
                    add(entity["entity_id"], 1.0)
        if not ordered:
            return {}
        ids = list(ordered)[: entity_layer.MAX_LINK_SEEDS * 3]
        marks = ", ".join(["?"] * len(ids))
        kinds = {
            row["entity_id"]: row["entity_type"]
            for row in conn.execute(f"SELECT entity_id, entity_type FROM entities WHERE entity_id IN ({marks})", tuple(ids))
        }
        frequency = {
            row[0]: row[1]
            for row in conn.execute(
                f"SELECT entity_id, count(*) FROM entity_mentions WHERE entity_id IN ({marks}) GROUP BY entity_id",
                tuple(ids),
            )
        }
        total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0] or 1
        seeds: dict[str, float] = {}
        for entity_id in ids:
            kind = kinds.get(entity_id)
            if kind is None:
                continue
            # A name in >5% of chunks discriminates nothing (a hub), unless it
            # is a code definition or file the question named.
            if frequency.get(entity_id, 0) > 0.05 * total and kind not in ("symbol", "file"):
                continue
            if not self._entity_accessible(conn, entity_id, allowed_scopes):
                continue
            seeds[entity_id] = ordered[entity_id]
            if len(seeds) >= entity_layer.MAX_LINK_SEEDS:
                break
        return seeds

    def _entity_accessible(self, conn: sqlite3.Connection, entity_id: str, allowed_scopes: list[str]) -> bool:
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        if self._entity_layer_ready:
            row = conn.execute(
                f"""
                SELECT 1 FROM entity_mentions m
                JOIN chunks c ON c.chunk_id = m.chunk_id
                JOIN sources s ON s.source_id = c.source_id
                WHERE m.entity_id = ? AND c.privacy_scope IN ({scope_marks}) AND s.privacy_scope = c.privacy_scope
                LIMIT 1
                """,
                (entity_id, *allowed_scopes),
            ).fetchone()
            if row is not None:
                return True
        return self._entity_has_accessible_relation(conn, entity_id, allowed_scopes)

    def _seed_relation_rows(
        self,
        conn: sqlite3.Connection,
        seeds: Iterable[str],
        allowed_scopes: list[str],
        limit: int = 400,
    ) -> list[sqlite3.Row]:
        seed_ids = list(seeds)
        if not seed_ids or not allowed_scopes:
            return []
        marks = ", ".join(["?"] * len(seed_ids))
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        joins, predicate = self._relation_scope_sql(scope_marks)
        return conn.execute(
            f"""
            SELECT r.*, s.canonical_name AS subject, o.canonical_name AS object
            FROM relations r
            JOIN entities s ON s.entity_id = r.subject_entity_id
            JOIN entities o ON o.entity_id = r.object_entity_id
            {joins}
            WHERE r.status = 'active'
              AND (r.subject_entity_id IN ({marks}) OR r.object_entity_id IN ({marks}))
              AND {predicate}
            ORDER BY r.confidence DESC, r.relation_id
            LIMIT ?
            """,
            (*seed_ids, *seed_ids, *allowed_scopes, limit),
        ).fetchall()

    def _entity_channel(
        self,
        conn: sqlite3.Connection,
        seeds: dict[str, float],
        allowed_scopes: list[str],
    ) -> dict[str, float]:
        """Chunks scored by the seeds and their one-hop neighbours.

        Seed weight 1; a neighbour gets 0.5 x relation-type weight x edge
        confidence (floor 0.3). A chunk scores sum(weight / (1 + 0.1 * df)).
        """
        if not seeds or not allowed_scopes or not self._entity_layer_ready:
            return {}
        weights: dict[str, float] = dict(seeds)
        for row in self._seed_relation_rows(conn, seeds, allowed_scopes):
            other = row["object_entity_id"] if row["subject_entity_id"] in seeds else row["subject_entity_id"]
            hop = 0.5 * entity_layer.HOP_WEIGHT.get(row["relation_type"], 0.3) * max(float(row["confidence"]), 0.3)
            if hop > weights.get(other, 0.0):
                weights[other] = hop
        ids = list(weights)[:600]
        marks = ", ".join(["?"] * len(ids))
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        rows = conn.execute(
            f"""
            SELECT m.entity_id, m.chunk_id FROM entity_mentions m
            JOIN chunks c ON c.chunk_id = m.chunk_id
            JOIN sources s ON s.source_id = c.source_id
            WHERE m.entity_id IN ({marks}) AND c.privacy_scope IN ({scope_marks}) AND s.privacy_scope = c.privacy_scope
            """,
            (*ids, *allowed_scopes),
        ).fetchall()
        frequency: dict[str, int] = {}
        for row in rows:
            frequency[row["entity_id"]] = frequency.get(row["entity_id"], 0) + 1
        score: dict[str, float] = {}
        for row in rows:
            entity_id = row["entity_id"]
            score[row["chunk_id"]] = score.get(row["chunk_id"], 0.0) + weights[entity_id] / (
                1.0 + 0.1 * frequency[entity_id]
            )
        ranked = sorted(score, key=lambda chunk_id: (-score[chunk_id], chunk_id))[:ENTITY_CHANNEL_CANDIDATES]
        return {chunk_id: score[chunk_id] for chunk_id in ranked}

    def _related_entities(
        self,
        conn: sqlite3.Connection,
        question: str,
        chunks: list[dict[str, Any]],
        allowed_scopes: list[str],
        seeds: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        if not allowed_scopes:
            return []
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]
        entity_ids: set[str] = set(seeds or {})
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
                LIMIT 200
                """,
                (*chunk_ids, *allowed_scopes),
            ):
                entity_ids.add(row["subject_entity_id"])
                entity_ids.add(row["object_entity_id"])
        if seeds is None:
            for name in re_find_title_phrases(question):
                entity = self._find_entity(conn, name)
                if entity and self._entity_has_accessible_relation(conn, entity["entity_id"], allowed_scopes):
                    entity_ids.add(entity["entity_id"])
        if not entity_ids:
            return []
        marks = ", ".join(["?"] * len(entity_ids))
        rows = conn.execute(
            f"SELECT * FROM entities WHERE entity_id IN ({marks}) ORDER BY canonical_name LIMIT 50", tuple(entity_ids)
        ).fetchall()
        return [self._entity_row(row) for row in rows]

    def _relation_edges(
        self,
        conn: sqlite3.Connection,
        entities: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
        allowed_scopes: list[str],
        seeds: dict[str, float] | None = None,
        entity_chunks: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Relation lines for the answer context, most useful and most varied
        first: edges of the question's own entities, then edges evidenced by
        the retrieved chunks, interleaved one relation type at a time (the
        desktop renders the first six)."""
        if not allowed_scopes:
            return []
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        joins, predicate = self._relation_scope_sql(scope_marks)
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        def take(rows: Iterable[sqlite3.Row], rank_base: int) -> None:
            for offset, row in enumerate(rows):
                if row["relation_id"] in seen:
                    continue
                seen.add(row["relation_id"])
                item = self._relation_row(row)
                item["_rank"] = rank_base + offset
                candidates.append(item)

        if seeds:
            take(self._seed_relation_rows(conn, seeds, allowed_scopes, limit=200), 0)
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]
        fallback_ids = [entity["entity_id"] for entity in entities] if not seeds else []
        clauses: list[str] = []
        args: list[Any] = []
        if chunk_ids:
            clauses.append(f"r.evidence_chunk_id IN ({', '.join(['?'] * len(chunk_ids))})")
            args.extend(chunk_ids)
        if fallback_ids:
            marks = ", ".join(["?"] * len(fallback_ids))
            clauses.append(f"(r.subject_entity_id IN ({marks}) OR r.object_entity_id IN ({marks}))")
            args.extend(fallback_ids)
            args.extend(fallback_ids)
        if clauses:
            take(
                conn.execute(
                    f"""
                    SELECT r.*, s.canonical_name AS subject, o.canonical_name AS object
                    FROM relations r
                    JOIN entities s ON s.entity_id = r.subject_entity_id
                    JOIN entities o ON o.entity_id = r.object_entity_id
                    {joins}
                    WHERE r.status = 'active' AND ({" OR ".join(clauses)})
                      AND {predicate}
                    ORDER BY r.confidence DESC, r.observed_at DESC, r.relation_id
                    LIMIT 100
                    """,
                    (*args, *allowed_scopes),
                ).fetchall(),
                10_000,
            )
        if seeds and self._entity_layer_ready:
            candidates.extend(self._mention_lines(conn, seeds, entity_chunks or [], allowed_scopes))
        if not self._entity_layer_ready:
            candidates.sort(key=lambda item: (-float(item["confidence"]), item["_rank"]))
            chosen = candidates[:MAX_RELATION_EDGES]
        else:
            # The question's own entities first (interleaved by type), then
            # edges that merely sit in the retrieved chunks.
            own = [item for item in candidates if item["_rank"] < 10_000]
            chosen = entity_layer.round_robin(own, MAX_RELATION_EDGES)
            if len(chosen) < MAX_RELATION_EDGES:
                rest = [item for item in candidates if item["_rank"] >= 10_000]
                chosen += entity_layer.round_robin(rest, MAX_RELATION_EDGES - len(chosen))
        for item in chosen:
            item.pop("_rank", None)
        return chosen

    def _mention_lines(
        self,
        conn: sqlite3.Connection,
        seeds: dict[str, float],
        entity_chunks: list[str],
        allowed_scopes: list[str],
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        """"<document> --mentions--> <entity>" lines, synthesized from
        entity_mentions (no stored relation row): which document talks about
        the entity the question named."""
        out: list[dict[str, Any]] = []
        pairs: set[tuple[str, str]] = set()
        if not entity_chunks:
            return out
        seed_ids = list(seeds)
        seed_marks = ", ".join(["?"] * len(seed_ids))
        scope_marks = ", ".join(["?"] * len(allowed_scopes))
        for rank, chunk_id in enumerate(entity_chunks):
            if len(out) >= limit:
                break
            rows = conn.execute(
                f"""
                SELECT m.entity_id, m.role, e.canonical_name, c.source_id, c.privacy_scope, c.source_lineage_json
                FROM entity_mentions m
                JOIN entities e ON e.entity_id = m.entity_id
                JOIN chunks c ON c.chunk_id = m.chunk_id
                JOIN sources s ON s.source_id = c.source_id
                WHERE m.chunk_id = ? AND (m.role = 'self' OR m.entity_id IN ({seed_marks}))
                  AND c.privacy_scope IN ({scope_marks}) AND s.privacy_scope = c.privacy_scope
                """,
                (chunk_id, *seed_ids, *allowed_scopes),
            ).fetchall()
            document = next((row for row in rows if row["role"] == "self"), None)
            if document is None:
                continue
            for row in rows:
                if row["role"] == "self" or row["entity_id"] == document["entity_id"]:
                    continue
                if (document["entity_id"], row["entity_id"]) in pairs:
                    continue
                pairs.add((document["entity_id"], row["entity_id"]))
                relation_id = stable_hash(f"mention:{document['entity_id']}:{row['entity_id']}:{chunk_id}")
                out.append(
                    {
                        "relation_id": relation_id,
                        "subject_entity_id": document["entity_id"],
                        "object_entity_id": row["entity_id"],
                        "subject": document["canonical_name"],
                        "object": row["canonical_name"],
                        "relation_type": "mentions",
                        "confidence": 1.0,
                        "evidence_chunk_id": chunk_id,
                        "source_id": row["source_id"],
                        "privacy_scope": row["privacy_scope"],
                        "source_lineage": json_loads(row["source_lineage_json"], {}),
                        "valid_from": None,
                        "valid_to": None,
                        "observed_at": None,
                        "status": "active",
                        "basis": "structure",
                        "evidence_ref": None,
                        "_rank": rank,
                    }
                )
                break
        return out

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
                json_dumps(encode_vector(vector)),
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
        joins, predicate = self._relation_scope_sql(scope_marks)
        row = conn.execute(
            f"""
            SELECT 1
            FROM relations r
            {joins}
            WHERE (r.subject_entity_id = ? OR r.object_entity_id = ?)
              AND r.status = 'active'
              AND {predicate}
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
        joins, predicate = self._relation_scope_sql(scope_marks)
        rows = conn.execute(
            f"""
            SELECT r.*, s.canonical_name AS subject, o.canonical_name AS object
            FROM relations r
            JOIN entities s ON s.entity_id = r.subject_entity_id
            JOIN entities o ON o.entity_id = r.object_entity_id
            {joins}
            WHERE (r.subject_entity_id = ? OR r.object_entity_id = ?)
              AND r.status = 'active'
              AND {predicate}
            ORDER BY r.confidence DESC, r.observed_at DESC, r.relation_id
            LIMIT 500
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
            "basis": row["basis"] if "basis" in row.keys() else entity_layer.BASIS_ASSERTED,
            "evidence_ref": row["evidence_ref"] if "evidence_ref" in row.keys() else None,
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


def extract_declared_relations(text: str) -> list[tuple[str, str, str, float]]:
    """Relations a record declares in fields (``name``/``team`` + ``owner`` /
    ``depends_on``): JSON, CSV and spreadsheet rows, YAML-ish frontmatter.

    Prose sentence patterns ("A depends on B", "A owns B") were dropped on
    2026-09-23: measured 4/15 precise on real project documents, and the
    survivors were a truncated "Core owns Cloud" and a test fixture's
    fictional company.
    """
    relations: list[tuple[str, str, str, float]] = []
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
