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
