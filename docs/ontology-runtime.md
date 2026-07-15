# Production Ontology Runtime

Hephaestus includes a local-first ontology runtime for turning user-approved
company or personal material into an agent-readable knowledge store.

It is a runtime module, not only a governance contract:

- `ontology/` contains the Python package.
- `bin/ontology` is the executable CLI wrapper.
- `scripts/verify-ontology-runtime.sh` runs the runtime tests and sample corpus.
- `examples/ontology-corpus/` is a public-safe corpus used by verification.

## Activation And Privacy

The safe default is project-local activation. Agentlas Desktop and Agentlas
Terminal create these paths inside the selected project folder:

```text
.agentlas/ontology-runtime.json
.agentlas/ontology-sources.json
.agentlas/ontology-inbox/
.agentlas/ontology-runtime.sqlite
```

Automatic ingestion only reads:

1. files placed in `.agentlas/ontology-inbox/`;
2. paths explicitly registered in `.agentlas/ontology-sources.json`.

It does not scan the user's home folder, sibling projects, Downloads, Desktop,
or other workspaces. Company and personal material should be kept in separate
Agentlas projects unless the user explicitly registers both in the same project.
Private scope is excluded from default query results unless the caller asks for
private scope.

The config policy name is `inbox_and_registered_sources_only`.

Terminal activation:

```bash
agentlas ontology
agentlas ontology add /path/to/company-docs --kind company --scope private
```

Runtime-only activation for development and CI:

```bash
bin/ontology auto .
bin/ontology sources add /path/to/company-docs --project . --kind company --scope private
```

## Local Dashboard

`/hep-build ontology` and `bin/hephaestus ontology` create
`.agentlas/ontology-gui/index.html` inside the active project. The file is a
self-contained dashboard, so it works without a hosted web server.

The dashboard contract is:

- left navigation for overview, graph, sources, query, memory, and commands;
- an Obsidian-style knowledge graph map backed by the runtime counts;
- source search and scope filtering for registered source paths;
- a GraphRAG query builder that copies exact local CLI commands;
- a Memory Candidate Queue that keeps durable memory promotion gated by Memory
  Curator;
- no home-folder scan, no sibling-project scan, and no remote API dependency.

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
| `memory_candidates` | Memory Curator tickets plus rebuildable, agent-scoped experience projections with local embeddings |
| `memory_links` | Typed `similar_to`, `supersedes`, and `contradicts` edges between memory rows |
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
| `.pdf` | parsed through `pdftotext` when installed |
| `.hwpx` | parsed through the first-party HWPX ZIP/XML adapter with paragraph and table spans |
| images and OCR formats | parsed through macOS Vision OCR or Tesseract when available |
| `.hwp` binary | parsed through the first-party HWP5 CFB/BodyText adapter |

Parser code shipped in this package must be owned adapter code or thin wrappers
around explicit local system tools. External parser projects are not vendored
into the public runtime. New office-format support should be implemented as a
first-party adapter with focused fixtures and verification gates.

Registered adapter boundaries do not fake success:

| Case | Runtime status |
|---|---|
| `.xls` / `.hml` before a first-party adapter exists | `unsupported_pending_adapter` |
| `.pdf` without `pdftotext` | `unsupported_pending_adapter` with the missing parser reason |
| encrypted or distribution-protected `.hwp` | `unsupported_pending_adapter` with the parser reason |
| malformed `.hwp` that is not CFB/HWP5 | `parser_error` |
| image OCR without macOS Vision or Tesseract | `unsupported_pending_adapter` with the missing OCR engine reason |
| unknown extensions | `unsupported_pending_adapter` |

Ingestion is idempotent by source URI and content hash. Re-running ingest on
unchanged files does not duplicate chunks, entities, relations, or candidate
tickets. Changed files increment the source version and rebuild derived chunks
and relation evidence for that source.

```bash
bin/ontology ingest examples/ontology-corpus --scope internal
```

## Search And GraphRAG

Full-text search uses SQLite FTS5. Vector search defaults to `auto`, which
selects the verified bundled or installed `potion-base-8M` int8 asset. The
dependency-free runtime reconstructs a normalized 256-dimensional Model2Vec
WordPiece mean, concatenates an equally weighted normalized hash-96 vector for
Korean/CJK and lexical recall, and returns one fixed 352-dimensional vector.

The tracked `agentlas-model2vec-int8-v1` payload is pinned to upstream revision
`bf8b056651a2c21b8d2565580b8569da283cab23`, declares the MIT license, and
verifies every payload SHA-256 plus the combined content identity before use.
Runtime inference uses only Python's standard library. It never imports a model
package, downloads a model, or falls back to a server embedding API. If no
verified local asset exists, `auto` reports a `degraded_fallback` and uses the
deterministic hash-96 adapter. Operators can explicitly select that degraded
path with `--embedding-adapter hash`.

```bash
bin/ontology --embedding-adapter model2vec \
  --local-model-path /path/to/potion-base-8M-int8 \
  --db .agentlas/ontology-runtime.sqlite query "release policy"

python3 -m ontology.model_assets verify /path/to/potion-base-8M-int8
python3 scripts/build-model2vec-asset.py --check
```

`AGENTLAS_MODEL2VEC_PATH` provides a verified asset override.
`AGENTLAS_RUNTIME_HOME/models/model2vec/potion-base-8M-int8` is the installed
runtime location. The reproducible build command downloads only the pinned
upstream build inputs, checks their hashes, emits per-row symmetric int8 data
and float32 little-endian scales, then verifies the release payload. Query-time
code is always offline.

`ontology query` returns more than text chunks:

- relevant chunks;
- source spans and source lineage;
- related entities;
- relation edges;
- evidence chunk refs;
- confidence scores;
- agent-scoped experience recall when `--agent` is provided;
- optional Memory Curator suggestions and Agent Working Memory cache writes
  only when `--record-memory` is explicitly provided on the CLI.

```bash
bin/ontology --db .agentlas/ontology-runtime.sqlite query "Project Helios Memory Curator" --agent verifier
bin/ontology --db .agentlas/ontology-runtime.sqlite query "Project Helios Memory Curator" --agent verifier --record-memory
bin/ontology graph entity "Project Helios"
```

Global options such as `--db`, `--embedding-adapter`, and
`--local-model-path` must precede the subcommand.

## Agent Experience Projection

Each Hub agent can use an isolated
`hub-agents/<normalized-slug>/memory/experience.sqlite`. The v3
`memory_candidates` extension stores the exact agent id, memory kind, tags,
salience prior, privacy scope, source-memory provenance, embedding adapter and
dimensions, vector, and embedding content hash. The owner runtime remains the
source of truth; this SQLite file is a rebuildable local projection and never
sets `durable_write_enabled`.

```bash
bin/ontology --db /path/to/experience.sqlite experience ingest \
  "Use a rollback checklist for every schema migration" \
  --agent hub:release-writer --tag migration --salience 0.8 \
  --source-memory-id desktop-memory-123

bin/ontology --db /path/to/experience.sqlite query \
  "How should I prepare this migration?" --agent hub:release-writer
```

Recall is read-only. Governance filters exact `agent_id`, privacy scope,
active status, expiry, and structural supersession before scoring. Retrieval
then fuses lexical and local cosine ranks with reciprocal-rank fusion and a
bounded salience prior. If all relevant memories fit the token budget, all are
returned; otherwise the runtime returns a budgeted top-k. Automatic graph
inference writes only `similar_to` from local vector cosine.
`supersedes` and `contradicts` remain explicit curator decisions.

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

Agent Working Memory is a cache, not the source of truth. A CLI query stores a
scoped hot-memory item only when `--record-memory` is supplied. The item carries
source refs, confidence, importance, TTL, `last_used_at`, and invalidation
fields. Programmatic callers can make the same choice with `record_memory`.

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
- PDF, HWP, HWPX, DOCX, XLSX, PPTX, and image OCR adapter ingest;
- unsupported adapter status reporting when a required local parser is missing.

## Runtime Boundaries

- HWPX and HWP5 parsing is first-party parser code in this package. HWPX keeps paragraph/table spans; HWP5 reads CFB `FileHeader` plus `BodyText/Section*` streams. Encrypted or distribution-protected HWP files are blocked.
- PDF text parsing depends on `pdftotext`.
- Image OCR uses macOS Vision first and Tesseract when available.
- Vector search is local-only in this package. No API key is required.
- Auto Model2Vec selection accepts only a manifest-verified filesystem asset.
  No query-time model id, network download, hosted embedding, or paid per-user
  embedding path exists. Hash-96 is a visible degraded fallback, not a silent
  replacement for the verified bundled model.
- Entity and relation extraction is deterministic and source-grounded. It does
  not use an LLM to infer hidden facts.
- The local runtime stores user-selected source metadata and chunks in the
  local SQLite database. Do not commit that database to public repos.
