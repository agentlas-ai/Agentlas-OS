---
name: agentlas-auto-activation
description: "Use when local runtime continuity should create or maintain .agentlas files for a project folder."
---

# Agentlas Auto-Activation

Activate only on explicit user request or repeated meaningful work in the same
folder. Create `.agentlas/` only inside that folder and never overwrite existing
user content without approval.

Minimum files:

- `.agentlas/project-soul-memory.md`
- `.agentlas/sitemap.json`
- `.agentlas/memory-map.json`
- `.agentlas/memory-tickets.jsonl`
- `.agentlas/vault-references.json`
- `.agentlas/activation.json`

Never store secrets, raw logs, full transcripts, cookies, private keys, service
accounts, or payment material in `.agentlas`.
