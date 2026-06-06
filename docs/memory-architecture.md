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
