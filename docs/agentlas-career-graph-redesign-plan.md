# Agentlas Career Graph Redesign Plan

Status: planning proposal
Date: 2026-07-09

## Executive Decision

Keep the current Markdown/JSONL architecture as the source of truth, and layer
**Agentlas Career Graph** on top as a derived machine index.

Do not replace the plain files with a graph. The current repo already has useful
ledger pieces: project memory, Memory Curator tickets, routing receipts, run
journals, code maps, sitemaps, playbook candidates, agent graph routing, and a
local SQLite/FTS runtime. Those files remain the audit trail. The graph reads
them, links them, and produces bounded projections for recall, routing,
playbooks, evolution, and public-safe Hub claims.

The public and product-facing "ontology" concept should still be removed or
demoted. The problem is not the graph primitive; the problem is making generic
"ontology" sound like the core product instead of explaining the concrete user
value: agents build evidence-backed memory from actual work.

The correct move is:

1. Keep Markdown/JSONL/sitemap/code-map/receipts as canonical source files.
2. Add Career Graph as a rebuildable index over those files.
3. Demote `ontology` to an internal graph/search implementation detail.
4. Promote `Agentlas Career Graph` as the product model.
5. Rewire memory, evolution, sitemap, code-map, receipts, and playbooks into one
   evidence-backed projection layer.
6. Keep backward-compatible aliases for one release cycle.

## Replanned Architecture: Ledger First, Graph Second

The architecture should work like this:

```text
Canonical files
  project-soul-memory.md
  memory-log.jsonl
  memory-tickets.jsonl
  curator-decisions.jsonl
  sitemap.json
  code-map/project-map.json
  run journals
  routing/execution receipts
        |
        v
Career Graph ingest
  parse, checksum, normalize, link, verify freshness
        |
        v
Derived graph index
  career-graph.sqlite
  career-graph/nodes.jsonl
  career-graph/edges.jsonl
        |
        v
Bounded projections
  prompt recall
  routing hints
  playbook candidates
  evolution candidates
  public-safe career cards
```

Rules:

- The graph is never the only copy of memory.
- The graph can always be deleted and rebuilt from canonical files.
- If graph freshness fails, the runtime falls back to canonical files.
- A graph result is a lead, not a final truth. Agents must still inspect source
  files or code before making high-impact claims.
- Public Hub projections can only read redacted graph views, never raw local
  ledgers.

## Why The Current Ontology Feels Wrong

The user intent is not "make an enterprise ontology". The intent is:

- agents remember scoped project decisions;
- agents accumulate career and experience across runs;
- repeated failures become playbooks;
- codebase and sitemap knowledge are available before work starts;
- evolution proposals are backed by evidence, not vibe;
- public Hub claims can show useful, redacted career evidence without leaking raw
  local memory.

The current `ontology` name does not communicate that. It sounds like a broad
knowledge graph product and invites claims the current local usage does not yet
support.

## Current System Decomposition

### Project Memory

Current surfaces:

- `.agentlas/project-soul-memory.md`
- `.agentlas/memory-log.jsonl`
- `.agentlas/memory-map.json`
- `.agentlas/memory-tickets.jsonl`
- `.agentlas/curator-decisions.jsonl`
- Desktop memory injection in `electron/memory/context.ts`
- Terminal memory emitter contract in `agentlas_terminal/engine/architecture.data.json`

What works:

- Memory events have scoped kinds such as fact, decision, preference, risk,
  procedure, evidence, deprecation, and conflict.
- The Memory Curator owns durable writes and rejects secrets/raw transcripts.
- Desktop injects project memory, sitemap summaries, code-map summaries, and
  recent curated memory before a run.

Gap:

- These memories are not converted into durable graph nodes and edges.
- Memory-log entries can prove agent experience, but the graph layer does not
  ingest them as career evidence.

### Project Sitemap

Current surfaces:

- `.agentlas/sitemap.json`
- `schemas/sitemap.schema.json`
- Task Bias Curator instructions in Desktop and Terminal
- Hephaestus public package sitemap in `.agentlas/sitemap.json`

What works:

- Sitemap is the intended external state for task-bias control and coverage.
- Desktop can summarize sitemap status into prompt context.

Gap:

- Sitemap nodes mostly remain independent governance state.
- They are not linked to runs, failures, agent versions, code modules, or
  verified output evidence.

### Code Map

Current surfaces:

- `agentlas_desktop/electron/memory/code-map-gen.mjs`
- `.agentlas/code-map/project-map.json`
- `.agentlas/code-map/project-map.md`
- Desktop prompt injection in `electron/memory/context.ts`

What works:

- Code map has modules, entry points, top symbols, module edges, docs, and
  hygiene candidates.
- It is generated per project and injected as a recall layer.
- This is closer to the user's intended "codemap" than the current ontology
  runtime is.

Gap:

- Code map is read as prompt seed only.
- It does not become graph evidence for "this agent worked on this module",
  "this recovery recipe applies to this code surface", or "this package version
  touched these symbols".

### Run Journal And Receipts

Current surfaces:

- `agentlas_cloud/networking/run_journal.py`
- `agentlas_cloud/networking/receipts.py`
- `.agentlas/stormbreaker/journal/*.jsonl`
- `~/.agentlas/networking/ledgers/routing-decisions.jsonl`
- `~/.agentlas/networking/ledgers/executions.jsonl`

What works:

- Run Journal records start, complete, fail, repair, plan, verify, and clarify
  events.
- Receipts store redacted routing decisions, graph paths, allowed-by reasons,
  policy decisions, and memory/playbook candidates.

Gap:

- These are the best career evidence sources, but they are not yet a Career
  Graph ingestion stream.

### Playbooks And Evolution

Current surfaces:

- `agentlas_cloud/networking/playbooks.py`
- `docs/network-agent-personalization-and-plugin-upgrades.md`
- planned stores such as `agent_playbook_cards`, `agent_run_events`,
  `agent_evolution_proposals`

What works:

- The architecture is candidate-first.
- Promoted playbooks and self-evolution proposals are explicitly evidence-gated.
- Public Hub packages are not mutated implicitly.

Gap:

- The public repo has the control-plane concept, but local graph ingestion does
  not yet turn repeated run patterns into typed playbook/evolution graph nodes.

### Ontology Runtime

Current surfaces:

- `ontology/runtime.py`
- `ontology/cli.py`
- `ontology/embeddings.py`
- `bin/ontology`
- `bin/hephaestus ontology`
- `tests/test_ontology_runtime.py`
- `tests/test_memory_graph.py`

What works:

- SQLite schema, FTS/search, local hash-vector fallback, parsers, source lineage,
  chunks, entities, relations, working memory, and memory candidates.
- Direct durable memory writes are blocked.
- Private scope can be excluded.
- Memory candidate dedup/supersede/contradict edges exist.

Gap:

- The runtime currently represents document/source retrieval more than agent
  career.
- Local evidence under `/Users/mason/Documents/Agentlas_F` shows activation
  skeletons and empty source manifests, not a live project-wide ontology DB:
  `ontology-sources.json` files have `sources: []`, and no
  `.agentlas/ontology-runtime.sqlite` was found under the checked tree.

### Agent Ontology Routing

Current surfaces:

- `.agentlas/agent-ontology/*`
- `agentlas_cloud/agent_graph/migrate.py`
- `agentlas_cloud/networking/router.py`
- `agentlas_cloud/networking/pipeline.py`

What works:

- Routing can use card-derived graph paths.
- Pipeline planning can return `agent_ontology_pipeline_graph` and
  `produces_consumes_path`.

Gap:

- In the current Hephaestus package migration report, sitemap edges are still
  unresolved.
- The AO graph is useful for agent/card routing, but it is not a career graph.

### Super Ontology Contracts

Current surfaces:

- `.agentlas/super-ontology-*.json`
- `docs/super-ontology-candidate-contract.md`
- Desktop and Terminal project bootstrap files

What works:

- The contracts encode useful policy concepts: provenance, calibration,
  side-effect containment, identity resolution, temporal state, delegation,
  privacy, and rollback.

Gap:

- The name and file explosion make the product feel over-abstract.
- These should become policy contracts and graph write gates, not a visible
  product promise called "Super Ontology".

## Product Reframe

### Old Public Claim

Agentlas has an ontology runtime.

This is technically defensible but weak. It sounds generic, academic, and easy to
overclaim.

### New Public Claim

Agentlas gives every agent a local Career Graph: a private record of what it has
done, what it learned, where it failed, what fixed it, which project surfaces it
understands, and which claims are proven enough to reuse.

This matches the product better because it turns repeated agent work into an
asset without pretending the system has solved all knowledge representation.

## Proposed Agentlas Career Graph Model

### Core Question

For any agent, team, package, project, or task:

- What did it do?
- What evidence proves it?
- What project/code surface did it affect?
- What failed?
- What recovered it?
- What playbook was promoted?
- What changed in the agent after review?
- What can be safely shown publicly?

### Node Types

- `Agent`
- `AgentVersion`
- `Team`
- `Project`
- `TaskSignature`
- `Run`
- `RunStep`
- `RoutingDecision`
- `ExecutionReceipt`
- `FailureSignature`
- `RecoveryRecipe`
- `PlaybookCandidate`
- `PromotedPlaybook`
- `EvolutionProposal`
- `EvalResult`
- `VerificationGate`
- `MemoryEvent`
- `MemoryTicket`
- `CuratorDecision`
- `SitemapNode`
- `CodeModule`
- `CodeSymbol`
- `SourceChunk`
- `Capability`
- `ToolSurface`
- `HubPackage`
- `PublicCareerClaim`

### Edge Types

- `performed`
- `attempted`
- `planned`
- `verified_by`
- `failed_with`
- `recovered_by`
- `produced`
- `consumed`
- `touched`
- `depends_on`
- `routes_to`
- `has_capability`
- `has_version`
- `derived_from`
- `suggested_memory`
- `promoted_to_memory`
- `suggested_playbook`
- `promoted_to_playbook`
- `proposed_evolution`
- `approved_evolution`
- `supersedes`
- `contradicts`
- `redacted_from`
- `published_as`

### Evidence Envelope

Every graph node and edge that affects memory, evolution, routing, public claims,
or future prompt injection should carry:

- `source_ref`
- `source_span` when available
- `run_id`
- `receipt_id`
- `agent_id`
- `agent_version`
- `project_path_hash`
- `privacy_scope`
- `confidence`
- `status`
- `observed_at`
- `ingested_at`
- `verification_ref`
- `redaction_policy`

## Current-To-New Mapping

| Current artifact | Keep? | New role |
|---|---:|---|
| `.agentlas/project-soul-memory.md` | Yes | Human-readable project memory projection |
| `.agentlas/memory-log.jsonl` | Yes | Career Graph `MemoryEvent` ingestion source |
| `.agentlas/memory-tickets.jsonl` | Yes | `MemoryTicket` candidates |
| `.agentlas/curator-decisions.jsonl` | Yes | `CuratorDecision` nodes |
| `.agentlas/sitemap.json` | Yes | `SitemapNode` source |
| `.agentlas/code-map/project-map.json` | Yes | `CodeModule` and `CodeSymbol` source |
| Run journals | Yes | `Run` and `RunStep` source |
| Routing receipts | Yes | `RoutingDecision` and `ExecutionReceipt` source |
| `agent_graph/*` | Yes | routing graph subsystem, renamed externally |
| `ontology/runtime.py` | Keep internally | source/chunk/search implementation for graph |
| `bin/ontology` | Temporarily | compatibility alias |
| `.agentlas/ontology-runtime.sqlite` | Migrate | `.agentlas/career-graph.sqlite` |
| `.agentlas/ontology-sources.json` | Migrate | `.agentlas/career-graph-sources.json` |
| `.agentlas/ontology-inbox` | Migrate | `.agentlas/career-graph-inbox` |
| `.agentlas/agent-ontology/*` | Rename | `.agentlas/agent-map/*` or `.agentlas/career-graph/agent-map/*` |
| `.agentlas/super-ontology-*` | Demote/rename | `.agentlas/policy-contracts/*` |

## Proposed File Layout

```text
.agentlas/
  career-graph.sqlite
  career-graph.json
  career-graph-sources.json
  career-graph-inbox/
  career-graph/
    nodes.jsonl
    edges.jsonl
    projections/
      project-memory.md
      public-career-card.json
      agent-summary.json
    agent-map/
      agents.jsonl
      capabilities.json
      edges.jsonl
  code-map/
    project-map.json
    project-map.md
  memory-log.jsonl
  memory-tickets.jsonl
  curator-decisions.jsonl
  sitemap.json
  policy-contracts/
    provenance.json
    side-effect-containment.json
    privacy-boundary.json
    calibration.json
```

## Command Surface

New primary commands:

```text
career-graph status
career-graph ingest
career-graph query "what has this agent learned about releases?"
career-graph agent <agent-id>
career-graph project
career-graph public-card <agent-id>
career-graph verify
```

Compatibility commands:

```text
ontology status   -> career-graph status, with deprecation notice
ontology add      -> career-graph sources add
ontology query    -> career-graph query
```

Public docs should not teach `ontology` as the main feature after the rename.

## Ingestion Pipeline

### Phase A: Local Evidence Ingest

Inputs:

- `.agentlas/memory-log.jsonl`
- `.agentlas/memory-tickets.jsonl`
- `.agentlas/curator-decisions.jsonl`
- `.agentlas/sitemap.json`
- `.agentlas/code-map/project-map.json`
- `~/.agentlas/networking/ledgers/routing-decisions.jsonl`
- `~/.agentlas/networking/ledgers/executions.jsonl`
- `.agentlas/stormbreaker/journal/*.jsonl`

Output:

- `career-graph.sqlite`
- compact prompt projection
- public-safe redacted projection

### Phase B: Runtime Hook

When a Desktop/Terminal/Codex run starts:

1. Detect project root.
2. Ensure project memory files.
3. Ensure code map.
4. Ingest changed ledgers into Career Graph.
5. Inject bounded Career Graph projection, not raw graph.

### Phase C: Post-Run Hook

When a run finishes:

1. Write run receipt.
2. Write verification result.
3. Convert Memory Events into candidate nodes.
4. Convert repeated failure/recovery patterns into playbook candidates.
5. Create evolution proposals only as candidates.

## Public Projection

Public Hub must not expose raw memory. It can expose a redacted career card:

```json
{
  "agentId": "web-app-designer",
  "version": "1.2.0",
  "verifiedRuns": 18,
  "domains": ["frontend", "responsive-ui", "mcp-design-workflow"],
  "promotedPlaybooks": [
    "mobile-first QA before publishing",
    "browser screenshot verification after UI edits"
  ],
  "knownFailurePatterns": [
    "overwriting existing design system without inspection"
  ],
  "evidencePolicy": "redacted receipts only"
}
```

This is much stronger than "agent has ontology". It says what the agent has
actually survived and learned.

## What To Delete Or Rename

### Delete From Product Copy

- "Super Ontology" as a visible promise.
- "Ontology Runtime" as the main README feature.
- Claims that imply automatic total project knowledge unless live ingestion is
  proven.

### Keep Internally

- SQLite/FTS/chunk/source lineage/search runtime.
- Memory candidate graph edges.
- Scope/privacy checks.
- Graph path routing.
- Policy contracts, after renaming and grouping.

### Rename

- `ontology` public docs -> `Career Graph`
- `agent ontology` -> `Agent Map` or `Agent Capability Graph`
- `super ontology` -> `Policy Contracts`
- `ontology-runtime.sqlite` -> `career-graph.sqlite`
- `ontology-sources.json` -> `career-graph-sources.json`
- `ontology-inbox` -> `career-graph-inbox`

## Benefits

- Better product story: agents build a private career from real work.
- Clearer user value: reuse of lessons, failures, fixes, and codebase knowledge.
- Stronger Hub marketplace story: users can evaluate agents by evidence, not
  adjectives.
- Fits current architecture: PM Soul, Memory Curator, sitemap, code-map,
  receipts, playbooks, and evolution proposals all become graph inputs.
- Safer than raw memory: public projection can be redacted and evidence-based.
- Less AI-slop: "career graph" explains why memory matters, not just that a graph
  exists.

## Costs And Risks

### New Complexity

The current file-first model is easy to understand: open the Markdown or JSONL
file and inspect the record. A graph layer adds schemas, node ids, edge types,
ingestion jobs, freshness checks, projections, migrations, and query behavior.
That complexity is only worth it if the graph answers relationship questions the
plain files cannot answer cleanly.

### Stale Graph Risk

The biggest technical risk is a stale derived index:

```text
memory-log.jsonl has a new failure record
career-graph ingest did not run
agent queries graph
agent concludes there was no prior failure
```

This is worse than the current architecture. Mitigation requires source
checksums, `last_ingested_at`, stale warnings, and runtime fallback to canonical
files.

### False Edge Risk

A wrong graph edge can be more damaging than a missing note. If the graph links a
failure to the wrong code module or promotes a weak recovery recipe, future
agents may reuse the wrong lesson with confidence. Mitigation requires edge
provenance, confidence labels, curator decisions, and "source required before
action" rules.

### Debugging Burden

Today, debugging memory often means reading one file. With a graph, debugging
requires answering:

- which source file created this node;
- which ingest run created this edge;
- whether the source changed after ingest;
- which projection the agent saw;
- why a query ranked one memory above another.

This needs `career-graph trace <node-or-edge>` from the beginning.

### Performance And Startup Cost

Desktop and Terminal already inject memory every turn. If graph ingest or graph
query runs too aggressively, startup and chat latency can regress. The graph
must be incremental, bounded, and non-blocking except when the user explicitly
runs `career-graph verify`.

### Privacy And Public Projection Risk

The graph links more things together, so a careless export can leak more than a
single memory file would. Public Hub projections must be built from an allowlist
of fields and must exclude raw prompts, private paths, full transcripts,
credentials, customer data, and unredacted failure logs.

### Overfitting To History

Career evidence can improve routing, but it can also trap an agent in past
patterns. A worker that succeeded on one UI stack should not be forced onto every
future UI task. Mitigation requires freshness, task matching, negative evidence,
and an escape hatch for the model to ignore weak historical matches.

### Small Project Overhead

For tiny one-off packages, Markdown-only may be enough. Career Graph should be
lazy or optional until the project has repeated work, multiple agents, Hub
publishing, recurring workflows, or enough memory events to justify indexing.

### Naming Migration

Naming migration still touches many docs, tests, commands, generated packages,
Desktop, Terminal, and Hephaestus. Existing `/ontology` and `bin/ontology` users
need compatibility aliases. Existing tests around ontology must be renamed,
bridged, or kept as internal-runtime tests.

### Marketing Overclaim Risk

If ingestion is not implemented, Career Graph becomes another label. Public
claims must stay conservative until a real project shows nonzero graph nodes,
edges, receipts, memory events, code modules, failure signatures, and promoted
playbook candidates.

## Feasibility

Feasibility is high if staged. This is not a ground-up rewrite.

The existing architecture already has:

- memory events;
- candidate-first curation;
- run journals;
- routing receipts;
- code-map generation;
- sitemap governance;
- graph routing;
- local SQLite graph/search runtime;
- privacy-scope boundaries.

The missing piece is a Career Graph ingestion/projection layer that binds them.

## Migration Plan

### Phase 0: Terminology Freeze

- Update docs and README strategy to say `Agentlas Career Graph`.
- Define `ontology` as legacy/internal wording only.
- Add public copy rule: do not claim live project knowledge unless ingestion proof
  exists.

### Phase 1: Compatibility Layer

- Add `career_graph/` package that imports or wraps the current `ontology`
  runtime.
- Add `bin/career-graph`.
- Keep `bin/ontology` as a deprecation alias.
- Add tests proving alias behavior.

### Phase 2: Schema And Ingest

- Add tables or JSONL schema for `nodes`, `edges`, and `evidence`.
- Implement ingestors for:
  - memory log;
  - memory tickets;
  - curator decisions;
  - sitemap;
  - code map;
  - routing receipts;
  - execution receipts;
  - run journals.

### Phase 3: Desktop/Terminal Runtime Wiring

- Replace `ontology` bootstrap names in Desktop and Terminal with
  `career-graph` names.
- On project attach, run incremental Career Graph ingest after code-map generation.
- Inject a bounded Career Graph projection into prompts.

### Phase 4: Hub Projection

- Export redacted `public-career-card.json`.
- Link public Hub agent pages to verified run counts, promoted playbooks, and
  safe evidence summaries.
- Keep raw local memory private.

### Phase 5: Remove Public Ontology Surface

- Remove README/tutorial focus on ontology.
- Keep legacy command aliases for one release cycle.
- Later remove only after telemetry/support confirms low usage.

## Implementation Status: 2026-07-09

Implemented in this pass:

- `career_graph/` runtime package exists as a rebuildable SQLite index over
  canonical Agentlas files.
- `bin/career-graph` and `bin/hephaestus career-graph ...` expose `status`,
  `ingest`, `query`, `trace`, `verify`, and `public-card`.
- Desktop Hephaestus runner can execute the `career_graph` module.
- Desktop project attach creates Career Graph config/source/inbox files and
  refreshes the graph in the background for the active project.
- Desktop prompt context can include bounded Career Graph source refs.
- Terminal creates the same Career Graph project files, exposes
  `career-graph` commands, and delegates index commands to the real
  `career_graph` runtime instead of routing them through Hub search.
- Terminal REPL exposes `/career-graph`.
- Run journal failures are promoted into `FailureSignature` nodes.
- Routing/execution receipts with `memory_playbook.candidates` are promoted
  into `PlaybookCandidate` nodes.
- `.agentlas/ledgers/agent-evolution-proposals.jsonl` is promoted into
  `EvolutionProposal` nodes.
- Desktop self-evolution proposals append private, content-free lifecycle
  records into that project ledger when `source.projectPath`/`projectRoot`/
  `workspacePath`/`cwd` is available.
- Hub upload packaging reads `.agentlas/public-career-card.json` and includes
  only the redacted aggregate as `manifest.careerGraph` and `bundle.careerGraph`.
- Hub upload packaging auto-generates the public card when a package already has
  Career Graph markers but no card yet.
- Desktop cloud-agent packaging also validates and includes redacted
  `careerGraph` manifests and bundle projections.
- Desktop upload UI renders the redacted Career Graph proof section when the
  package result includes `manifest.careerGraph` or `bundle.careerGraph`.
- Agentlas Hub web registration validates `manifest.careerGraph`/
  `bundle.careerGraph`, persists the sanitized card on
  `manifest.cloudPackage.careerGraph`, and renders it on `/p/[slug]`.
- Marketplace upload blocks unsafe public cards that include raw local paths,
  raw prompts, raw transcripts, or source text.
- Adapter mirrors for Codex/Claude are synchronized through
  `scripts/sync-adapters.sh`.

Still not complete:

- Live deployed Hub URL verification still needs a real uploaded package with a
  `careerGraph` card.
- README and public screenshots are intentionally deferred to the next
  public-facing pass.
- Legacy public `ontology` copy still needs to be demoted in README/tutorials.

## Acceptance Gates

Do not call the redesign done until all gates pass:

- `career-graph verify` reports nonzero nodes and edges for a real project.
- A real Desktop or Terminal run writes a receipt and that receipt appears in the
  Career Graph.
- A real memory-log entry appears as a `MemoryEvent` node.
- A real code module appears as a `CodeModule` node.
- A failed run can produce a `FailureSignature` node.
- A repeated fix can produce a `PlaybookCandidate`.
- Public projection contains no raw prompts, secrets, private paths, or full
  transcripts.
- README no longer sells `ontology` as the core user-facing feature.

## Deferred README And Asset Checklist

Do not edit README in this implementation pass. Track these copy and image
changes for the next public-facing pass:

- Replace the front-page product name with `Agentlas OS`.
- Demote `Hephaestus` to the local engine/runtime name.
- Replace public `ontology` language with `Career Graph` or `Agent Career Graph`.
- Explain Career Graph as a rebuildable index over Markdown, JSONL ledgers,
  sitemap, code map, receipts, and run journals.
- Keep the install prompt simple: install from the GitHub URL, register the
  plugin/marketplace package, enable next-session commands, and turn on global
  routing when supported.
- Remove `Terminal` and `Desktop` warning copy from the install prompt unless
  the user is actually installing those products.
- Expand the `What it builds` tree to include memory, sitemap, code map,
  receipts, run journals, and career graph files.
- Add a `Local first, graph assisted` section that makes the source-of-truth
  boundary explicit.
- Add command examples for `career-graph ingest`, `career-graph status`,
  `career-graph query`, `career-graph public-card`, and `career-graph verify`.
- Keep `ontology` only in a legacy/internal compatibility note.
- Replace screenshots that show the old Product Hunt/early GUI surface.
- Add one architecture image showing canonical files at the bottom and Career
  Graph as the routing/index layer above them.
- Add one Desktop/Terminal image showing an agent receiving a source-backed
  context projection, not a generic graph visualization.
- Add one Hub image showing a redacted public career card, not raw local memory.

## First Useful MVP

The smallest non-fake MVP:

1. `career-graph ingest --project .`
2. It reads:
   - `.agentlas/memory-log.jsonl`
   - `.agentlas/sitemap.json`
   - `.agentlas/code-map/project-map.json`
   - networking routing/execution ledgers when available
3. It writes `.agentlas/career-graph.sqlite`.
4. `career-graph status` shows counts:
   - memory events
   - sitemap nodes
   - code modules
   - symbols
   - routing decisions
   - executions
5. `career-graph query "release failures"` returns evidence-backed results.

This MVP would immediately make the current architecture honest: the graph is not
just a named folder; it is a live index of what the agents have done and learned.

## Final Recommendation

Proceed with a ledger-first Career Graph overlay.

The reason is not marketing alone. The existing system's strongest real assets are
memory logs, code maps, sitemaps, receipts, run journals, and playbook/evolution
candidates. Those are exactly the raw material of an agent career graph, but they
must remain canonical. The graph should be a rebuildable index and projection
layer over those files, not a replacement storage system.

The redesign should preserve the implementation primitives but change the center
of gravity from "knowledge graph about everything" to "evidence graph of agent
work". If the graph becomes stale, opaque, or the only copy of memory, the
redesign has failed.
