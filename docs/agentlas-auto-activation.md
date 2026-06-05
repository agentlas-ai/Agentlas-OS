# Agentlas Auto-Activation

Agentlas auto-activation is a public contract for local runtimes that want a
project folder to become an Agentlas-aware workspace.

It is not tied to one desktop app. Any local runtime may implement it with its
own storage, as long as it preserves the public behavior below.

## Purpose

When a user repeatedly works in the same folder, the runtime should make project
memory, sitemap/task-bias, PM Soul, and Memory Tickets available automatically.
One-off folders should stay untouched unless the user explicitly activates them.

## Activation Triggers

A runtime may activate when either condition is true:

- explicit activation: the user asks to activate Agentlas for this folder;
- repeated use: the same folder is used for meaningful work more than once.

The repeated-use threshold should be low enough to preserve continuity but not
so low that every temporary folder is modified. A common default is the second
visit.

## Files To Create

Create `.agentlas/` only when activation happens.

Recommended minimum:

```text
.agentlas/
├── project-soul-memory.md
├── sitemap.json
├── memory-map.json
├── memory-tickets.jsonl
├── vault-references.json
├── skill-registry.json
├── skill-trials.jsonl
├── curator-decisions.jsonl
├── super-ontology-contract.json
├── super-ontology-task-coverage.json
├── super-ontology-contextual-flow.json
├── super-ontology-causal-impact.json
├── super-ontology-assurance-case.json
├── super-ontology-knowledge-homeostasis.json
├── super-ontology-replays.jsonl
├── super-ontology-evidence.jsonl
├── super-ontology-memory-bridge.jsonl
└── activation.json
```

If a package already includes `.agentlas/`, merge missing files without
overwriting user content.

## File Contracts

`project-soul-memory.md`

- Stores durable project decisions, constraints, risks, open loops, and current
  operating context.
- Must not store secrets, raw logs, or full transcripts.

`sitemap.json`

- Tracks project surfaces, status, risk, stale areas, evidence, and validation
  needs.
- Used by sitemap/task-bias logic to avoid only working on recent or obvious
  files.

`memory-map.json`

- Explains where memory belongs: user, team, project, agent repo, session, or
  discard.
- Points to sources, not secret values.

`memory-tickets.jsonl`

- Append-only queue of proposed durable memory events.
- Memory Curator reviews, redacts, deduplicates, and routes them.

`vault-references.json`

- References secret names or vault locations.
- Never stores secret values.

`activation.json`

- Public-safe activation metadata: schema version, activated time, runtime name,
  activation reason, and files created.

`skill-registry.json`

- Export-only candidate skill lifecycle metadata. First-class recall must stay
  disabled until local Curator review approves it.

`skill-trials.jsonl` and `curator-decisions.jsonl`

- Append-only ledgers for future trial evidence and Curator decisions. They are
  empty on activation unless a local runtime has real evidence to append.
- In portable packages this may start as `state: "seed"` so a local runtime can
  decide when to activate it.

`super-ontology-contract.json`

- Candidate-only adaptive knowledge governance metadata.
- Keeps `runtimeGraphWriteEnabled` and `zeroErrorClaim` false on export.
- Names the source-intake, evidence-packet, belief-ledger, knowledge-capsule,
  affordance-binding, task-coverage, contextual-flow, causal-impact,
  assurance-case, knowledge-homeostasis, promotion-readiness, replay, and
  sync-review gates.

`super-ontology-task-coverage.json`

- Export-only task coverage seed.
- Requires unknown requests to be classified by task family before graph slices,
  memory handoffs, tool bindings, external writes, physical actions, or training
  actions.
- Keeps runtime promotion disabled until evidence mode, authority, review, and
  rollback are explicit.

`super-ontology-contextual-flow.json`

- Export-only contextual flow seed.
- Requires information flows to name sender, recipient, subject, attribute,
  purpose, authority, transmission principle, retention, and audit references
  before crossing personal, company, customer, public, regulated, agent, memory,
  tool, output, or public-export boundaries.
- Keeps runtime promotion disabled and blocks same-user context joins,
  tool-response oversharing, raw prompt memory, customer-data publication, and
  agent-internal trace exposure.

`super-ontology-causal-impact.json`

- Export-only causal impact seed.
- Requires relation-to-action jumps to name intervention target,
  counterfactual checks, adverse outcomes, observability, reversibility, blast
  radius, and rollback.
- Keeps runtime promotion disabled and blocks correlation-as-causation,
  physical action, training, and multi-agent shared-state writes without
  evidence and review.

`super-ontology-assurance-case.json`

- Export-only assurance case seed.
- Requires broad claims to name required evidence, observed evidence,
  validators, residual risk, blocked shortcuts, and rollback.
- Keeps runtime promotion disabled and treats perfection or zero-error language
  as a rejected overclaim.

`super-ontology-knowledge-homeostasis.json`

- Export-only knowledge health seed.
- Requires stale, contradictory, unsupported, drifting, parser-failed,
  privacy-incident, missing-evidence, user-corrected, or runtime-desynced
  knowledge to name signal, measurement, error budget, control decision,
  Memory Curator policy, public export policy, escalation, and rollback.
- Keeps runtime promotion disabled and blocks critical health signals from
  direct runtime writes.

`super-ontology-replays.jsonl` and `super-ontology-evidence.jsonl`

- Empty append-only ledgers for future shadow/canary/rollback replay and
  promotion evidence.
- They do not make the ontology runtime-active by themselves.

`super-ontology-memory-bridge.jsonl`

- Empty append-only Memory Curator bridge ledger on export.
- Later runtimes may append redacted Memory Ticket bridge candidates only after
  raw prompts, secret values, private paths, and direct durable memory writes
  are blocked.

## Runtime Behavior

After activation, local runtimes should:

1. Read `.agentlas/project-soul-memory.md` before project-level claims.
2. Inject relevant memory context into agent prompts.
3. Ask workers to emit `## Memory Events` only for durable facts.
4. Route those events through Memory Tickets and Memory Curator.
5. Use `sitemap.json` to surface stale or under-validated work.
6. Keep activation idempotent and reversible.

## Safety Rules

- Never activate outside the selected project folder.
- Never overwrite existing `.agentlas` files without explicit approval.
- Never store credentials, API keys, raw logs, full transcripts, cookies,
  private keys, service-account files, or payment material.
- Never silently publish `.agentlas` memory from a private project.
- Keep runtime-specific state in runtime storage, not in public package files.

## Public Package Interaction

Generated or packaged Agentlas repos may include `.agentlas` seed files. A local
runtime that auto-activates the folder should treat those files as starting
contracts, not as private runtime state.
