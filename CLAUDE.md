# Claude Code Adapter

This file adapts the Agentlas Core Engine Meta-Agent Team for Claude Code.
`AGENTS.md` is canonical; this file stays thin.

## Route

1. Read `AGENTS.md`.
2. Read `.agentlas/mode-map.json`.
3. Use `skills/mode-classification/SKILL.md` to choose the mode.
4. If missing details would change files, adapters, or public/private boundary,
   use `skills/clarify-question-loop/SKILL.md`.
5. Route to one core team member:
   - `agents/10-single-agent-builder/agent.md`;
   - `agents/20-multi-agent-team-builder/agent.md`;
   - `agents/30-agentlas-packager/agent.md`.
6. Load only matching `skills/*/SKILL.md`.
7. Use `skills/agentlas-auto-activation/SKILL.md` when local project
   continuity or `.agentlas` activation is part of the output.
8. Keep runtime-specific files as adapters over the canonical core.

## Use When

- `/meta-agent`
- single agent builder
- agent team builder
- package an existing local or external agent
- Agentlas architecture packaging
- Codex, Claude Code, Gemini, Cursor, or AGENTS.md compatibility

## Verification

Run:

```bash
scripts/verify-package.sh
```
