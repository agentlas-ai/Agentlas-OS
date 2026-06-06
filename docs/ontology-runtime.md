# Production Ontology Runtime

Hephaestus includes a local-first ontology runtime for turning user-approved
company or personal material into an agent-readable knowledge store.

It is a runtime module, not only a governance contract:

- `ontology/` contains the Python package.
- `bin/ontology` is the executable CLI wrapper.
- `scripts/verify-ontology-runtime.sh` runs the runtime tests and sample corpus.
- `examples/ontology-corpus/` is a public-safe corpus used by verification.

## Storage Model

The default storage adapter is SQLite at `.agentlas/ontology-runtime.sqlite`.
The runtime creates the schema with migrations in `schema_migrations`.

Core tables:

| Table | Purpose |
|---|---|
| `sources` | Source archive metadata, checksum, source type, parser status, version, privacy scope, lineage pointers |
| `source_lineage` | Parent/derived source edges |
| `chunks` | Chunk text, source span, token estimate, checksum, source lineage, local vector |
| `chunk_fts` | SQLite FTS5 full-text index |
| `entities` / `entity_aliases` | Canonical graph entities and aliases |
| `relations` | Graph edges with relation type, confidence, evidence chunk, valid/observed time, status |
| `memory_candidates` | Memory Curator candidate tickets only |
| `memory_candidate_events` | approve/reject/quarantine/supersede/deprecate review events |
| `working_memory` | Agent-scoped hot cache with TTL, confidence, importance, source refs, invalidation reason |
| `runtime_adapters` | Parser/vector adapter registry and availability status |

SQLite backup/export/import commands are available:

```bash
bin/ontology storage backup .ontology-runtime/backups/runtime.sqlite
bin/ontology storage export .ontology-runtime/export.json
bin/ontology storage import .ontology-runtime/export.json
```

## Ingestion

Supported local parsers:

| Format | Status |
|---|---|
| `.txt` | parsed |
| `.md` / `.markdown` | parsed |
| `.json` | parsed into JSON-path records |
| `.csv` | parsed row by row |
| `.docx` | parsed through the OpenXML text adapter |
| `.xlsx` | parsed through the OpenXML sheet adapter |
| `.pptx` | parsed through the OpenXML slide adapter |

Registered adapter boundaries that do not fake success:

| Format | Runtime status |
|---|---|
| `.pdf` | `unsupported_pending_adapter` |
| `.hwp` / `.hwpx` | `unsupported_pending_adapter` |
| images and OCR formats | `unsupported_pending_adapter` |
| unknown extensions | `unsupported_pending_adapter` |

Ingestion is idempotent by source URI and content hash. Re-running ingest on
unchanged files does not duplicate chunks, entities, relations, or candidate
tickets. Changed files increment the source version and rebuild derived chunks
and relation evidence for that source.

```bash
bin/ontology ingest examples/ontology-corpus --scope internal
```

## Search And GraphRAG

Full-text search uses SQLite FTS5. Vector search uses the `local_hashing`
adapter by default: a deterministic hashed bag-of-words vector that works
without provider keys. Hosted embeddings, pgvector, Qdrant, or other vector
stores can replace it behind the adapter boundary.

`ontology query` returns more than text chunks:

- relevant chunks;
- source spans and source lineage;
- related entities;
- relation edges;
- evidence chunk refs;
- confidence scores;
- Memory Curator candidate ticket suggestions;
- optional Agent Working Memory cache writes when `--agent` is provided.

```bash
bin/ontology query "Project Helios Memory Curator" --agent verifier
bin/ontology graph entity "Project Helios"
```

## Memory Curator Bridge

The ontology runtime cannot write durable memory directly. Calling the runtime
durable-memory write path raises `DirectDurableMemoryWriteBlocked`.

Instead, GraphRAG results create candidate tickets in `memory_candidates`.
Each ticket includes source refs, reason, confidence, risk, expiry,
suggested scope, status, and `durable_write_enabled=false`.

Review states are explicit:

```bash
bin/ontology memory candidates
bin/ontology memory decide <ticket-id> approve --reason "Curator accepted source-backed project fact"
bin/ontology memory decide <ticket-id> quarantine --reason "Needs source owner review"
```

Approval records a review event and changes ticket status, but still does not
write durable memory. A Memory Curator runtime owns the later durable promotion.

## Agent Working Memory

Agent Working Memory is a cache, not the source of truth. Querying with
`--agent` stores a scoped hot-memory item with source refs, confidence,
importance, TTL, `last_used_at`, and invalidation fields.

```bash
bin/ontology working-memory read --agent verifier
bin/ontology working-memory prune --agent verifier
```

Pruning marks expired items as `expired` and low-importance items as `evicted`.
The cache always carries source refs back to chunks or graph edges.

## Verification

Run:

```bash
scripts/verify-ontology-runtime.sh
scripts/verify-package.sh
scripts/public_safety_check.sh
```

The runtime verification covers:

- unit and integration tests;
- end-to-end sample ingest/query/graph/memory-cache flow;
- idempotency;
- source lineage;
- TTL eviction;
- privacy scope filtering;
- direct durable-memory write prevention;
- unsupported adapter status reporting.

## Current Limits

- PDF, HWP, image, and OCR adapters are registered as pending and report
  `unsupported_pending_adapter`.
- The default vector adapter is deterministic and local. It is suitable for
  provider-free operation, but hosted embeddings or vector databases should be
  configured for large semantic corpora.
- Entity and relation extraction is deterministic and source-grounded. It does
  not use an LLM to infer hidden facts.
- The local runtime stores user-selected source metadata and chunks in the
  local SQLite database. Do not commit that database to public repos.
