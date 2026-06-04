---
name: agentlas-core-engine-meta-agent
description: "Use when creating a single Agentlas agent, creating a multi-agent team, or packaging an existing local/external agent into Agentlas architecture. Make sure to use this for /meta-agent-style requests in Codex."
---

# Agentlas Core Engine Meta-Agent

## Procedure

1. Read `AGENTS.md`.
2. Read `.agentlas/mode-map.json`.
3. Run the public mode classifier:
   - package or repair existing material -> `30-agentlas-packager`;
   - multi-role roster/company/HQ -> `20-multi-agent-team-builder`;
   - one worker -> `10-single-agent-builder`.
4. If missing details change files, adapters, or public/private boundaries, ask
   one to five clarify questions before generating.
5. Pick one:
   - `10-single-agent-builder`;
   - `20-multi-agent-team-builder`;
   - `30-agentlas-packager`.
6. Load matching support skills.
7. Emit or repair Agentlas contracts, including `.agentlas` activation seed
   files when local continuity is part of the output.
8. Verify with `scripts/verify-package.sh`.

## Output

Return `status`, `evidence`, `output`, and `blockers`.
