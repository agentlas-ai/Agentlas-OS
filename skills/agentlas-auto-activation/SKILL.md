---
name: agentlas-auto-activation
description: "Use when adding or auditing local runtime behavior that turns a project folder into an Agentlas-aware workspace with .agentlas memory and sitemap files."
---

# Agentlas Auto-Activation

Use this skill when a local runtime should activate Agentlas project continuity
for a folder.

## Procedure

1. On the first meaningful host contact, call
   `hephaestus project ensure --project <folder>` from Agentlas Core.
2. Never create project state in the user's home directory or filesystem root.
3. Install the managed privacy `.gitignore` block before local memory/indexes.
4. Add missing seed files, ontology/career indexes, and the bounded code map
   without overwriting existing user content.
5. Inject relevant project memory into future agent prompts.
6. Ask workers to emit `## Memory Events` only for durable facts.
7. Route Memory Events through Memory Tickets and Memory Curator.
8. Use sitemap/task-bias state to avoid stale or unvalidated surfaces.

## Minimum Files

- `.agentlas/project-soul-memory.md`
- `.agentlas/sitemap.json`
- `.agentlas/memory-map.json`
- `.agentlas/memory-tickets.jsonl`
- `.agentlas/vault-references.json`
- `.agentlas/skill-registry.json`
- `.agentlas/skill-trials.jsonl`
- `.agentlas/curator-decisions.jsonl`
- `.agentlas/activation.json`
- `.agentlas/code-map/project-map.json`
- `.agentlas/ontology-runtime.json`
- `.agentlas/ontology-runtime.sqlite`
- `.agentlas/career-graph.json`
- `.agentlas/career-graph.sqlite`

## Safety

Never store secrets, raw logs, full transcripts, cookies, private keys, service
accounts, or payment material in `.agentlas`.

If private files were already tracked before activation, report them as
`trackedSensitivePaths`; never mutate the user's Git index automatically.

## Reference

See `docs/agentlas-auto-activation.md`.
