# Memory Architecture

The meta-agent team uses a ticketed memory model and also requires generated or
packaged outputs to use the same model.

## In This Meta-Agent Package

- `project`: product intent, decisions, acceptance criteria, and open loops.
  Owners: `10-single-agent-builder` or `20-multi-agent-team-builder`, depending
  on selected mode.
- `agent_repo`: repo architecture facts and packaging conventions. Owner:
  `30-agentlas-packager`.
- `sitemap`: graph, task bias, and concept coverage. Owner:
  `30-agentlas-packager`.
- `team_memory`: shared reusable lessons. Owner: `30-agentlas-packager`.
- `session`: temporary events and tickets. Owner: root `AGENTS.md` runtime.

## In Generated Team Packages

Team Builder must generate PM Soul, Memory Curator, Memory Tickets, Policy Gate,
and clear promotion paths.

```text
worker observation
  -> ## Memory Events
  -> Memory Ticket JSONL
  -> Memory Curator review
  -> PM Soul or agent_repo update
  -> Policy Gate approval for shared team memory
```

## Network Memory / Playbook Control Plane

The Agentlas OS v1.1.33 Network contract keeps the per-agent `.agentlas` memory
architecture, but treats those files as scoped memory roots rather than
isolated notebooks.
The router does not write durable memory directly. It emits:

- `memory_playbook.applied`: playbooks that informed this route;
- `memory_playbook.candidates`: reusable routing, TF, failure, or release
  patterns that may be promoted later;
- `policy_decision`: Local Operator labels such as `auto_redact` or
  `candidate_only`.

The global networking home seeds:

```text
~/.agentlas/networking/memory/playbook-registry.json
~/.agentlas/networking/memory/playbook-candidates.jsonl
~/.agentlas/networking/memory/memory-events.jsonl
```

External Hub agents and third-party model sessions are proposal sources only.
Durable or global promotion still goes through Memory Curator, PM Soul, or a
Policy Gate owner with evidence and rollback notes.

## In Generated Single-Agent Packages

Single Agent Builder must still include memory architecture:

- project memory owned by PM Soul/project owner;
- a top `Local Credential Index (read first)` section in project memory for
  local credential location hints;
- Memory Events for durable learning;
- Memory Tickets before durable writes;
- vault references and local credential maps as references only, never values;
- proposal-first self-evolution.

## Ticket Fields

- `id`
- `timestamp`
- `sourceAgent`
- `scope`
- `trustLabel`
- `summary`
- `evidence`
- `action`
- `status`

Do not store secrets, raw credentials, full transcripts, private logs, or
customer data in any memory scope. Real values may live in local gitignored
project files described by `docs/local-credential-store.md`; memory stores only
env names, owner, project, local relative path, and stale-check metadata.

For deploy, release, store, billing, auth, API, or cloud work, memory users must
read the top project credential index and `.agentlas/local-credentials.map.json`
before concluding that credentials are absent.

## Governed Agent Experience Projection

Project-document knowledge and agent experience use the same local
`OntologyRuntime`, embedding contract, and relation schema, but they do not
share an authority boundary or a database:

```text
current project documents
  -> <project>/.agentlas/ontology-runtime.sqlite

owner-runtime agent learning
  -> ~/.agentlas/networking/hub-agents/<normalized-slug>/memory/experience.sqlite
```

The owner runtime remains authoritative for agent learning. The per-agent
SQLite file is a rebuildable, read-only-at-recall projection; it is not a new
durable-memory writer. Borrowed-agent invocation resolves the normalized slug
to that exact projection and calls the ontology query path instead of
concatenating an untyped nest file. Project documents are queried separately,
so untrusted agent identity cannot widen project or experience scope.

Experience retrieval follows a fixed order:

1. Enforce exact `agent_id`, caller-allowed privacy scope, active status,
   expiry, and valid same-agent/same-scope `supersedes` edges.
2. Score every remaining row lexically and by cosine, then apply the lexical or
   semantic relevance gates. There is no pre-ranking recency cap that can hide
   older eligible evidence.
3. Rank the relevant candidate text plus tags lexically and rank its local
   embedding by cosine similarity. Fuse the two rankings with reciprocal-rank
   fusion, then apply a bounded salience prior (`85%` fused relevance, `15%`
   salience).
4. Return every relevant memory when the total fits the context token budget.
   When it does not fit, return the highest-ranked items that fit the budget
   and top-k limit.

The v1.1.33 primary embedding path is the manifest-verified, bundled
`potion-base-8M` int8 Model2Vec asset: normalized semantic-256 plus normalized
hash-96, for a fixed 352-dimensional local vector. It runs in process and
offline. A missing or rejected asset does not trigger a download or hosted API;
the runtime fails open to hash-96 and reports the degraded state explicitly.

Host recall remains a delivery adapter, not a memory authority. The local hook
queries project documents and an exact verified agent projection separately,
never reads the host transcript, performs no Memory Curator write, redacts
common credential patterns, bounds the resulting capsule, and excludes native
policy files already loaded by the host. Claude Code/Codex, Antigravity,
OpenCode, and Grok have different delivery guarantees; see
[`runtime-memory-hooks.md`](runtime-memory-hooks.md) rather than assuming one
generic injection mechanism.

## Memory Relation Graph

Durable memory is a graph, not a flat list. The local ontology runtime links
Memory Curator candidate tickets with typed edges so the "conflict/deprecate,
never silent overwrite" rule is enforced by structure instead of convention.

Edge types:

- `similar_to`: machine-detected semantic similarity between two rows, scored
  by local vector cosine only after exact agent/privacy governance filtering.
  Automatic experience links never cross an agent or privacy scope.
- `supersedes`: a newer ticket replaces an older one. Recorded as an edge from
  the newer ticket to the one it retires, so the retired entry stays visible with
  a pointer to what replaced it.
- `contradicts`: two tickets make conflicting claims and need a curator decision.

Commands (all local, no model calls):

```text
ontology memory dedup [--threshold 0.72]     # link locally vector-similar rows
ontology memory decide <ticket> supersede --target <newer> --reason "..."
ontology memory graph <ticket>               # ticket + incoming/outgoing edges
ontology memory link <from> <to> <type> --reason "..."
```

`ontology memory graph` fails loud on an unknown ticket id rather than returning
an empty graph that would read as "no relations". `verify` reports a
`memory_links` count alongside the other table counts. Automatic inference is
limited to `similar_to`; only an explicit curator action may create
`supersedes` or `contradicts`.
