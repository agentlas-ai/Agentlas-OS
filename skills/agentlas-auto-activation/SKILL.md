---
name: agentlas-auto-activation
description: "Use when adding or auditing local runtime behavior that turns a project folder into an Agentlas-aware workspace with .agentlas memory and sitemap files."
---

# Agentlas Auto-Activation

Use this skill when a local runtime should activate Agentlas project continuity
for a folder.

## Procedure

1. Activate only on explicit user request or repeated meaningful work in the
   same folder.
2. Create `.agentlas/` only inside the selected project folder.
3. Add missing seed files without overwriting existing user content.
4. Inject relevant project memory into future agent prompts.
5. Ask workers to emit `## Memory Events` only for durable facts.
6. Route Memory Events through Memory Tickets and Memory Curator.
7. Use sitemap/task-bias state to avoid stale or unvalidated surfaces.

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

## Safety

Never store secrets, raw logs, full transcripts, cookies, private keys, service
accounts, or payment material in `.agentlas`.

## Reference

See `docs/agentlas-auto-activation.md`.
