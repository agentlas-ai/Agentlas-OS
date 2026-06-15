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

`/hephaestus ontology` and `bin/hephaestus ontology` create
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

Full-text search uses SQLite FTS5. Vector search uses the `local_hashing`
adapter: a deterministic hashed bag-of-words vector that works without provider
keys and without sending source text to a remote service.

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
- PDF, HWP, HWPX, DOCX, XLSX, PPTX, and image OCR adapter ingest;
- unsupported adapter status reporting when a required local parser is missing.

## Runtime Boundaries

- HWPX and HWP5 parsing is first-party parser code in this package. HWPX keeps paragraph/table spans; HWP5 reads CFB `FileHeader` plus `BodyText/Section*` streams. Encrypted or distribution-protected HWP files are blocked.
- PDF text parsing depends on `pdftotext`.
- Image OCR uses macOS Vision first and Tesseract when available.
- Vector search is local-only in this package. No API key is required.
- Entity and relation extraction is deterministic and source-grounded. It does
  not use an LLM to infer hidden facts.
- The local runtime stores user-selected source metadata and chunks in the
  local SQLite database. Do not commit that database to public repos.
