# Claude Code Adapter

This file adapts the Agentlas Core Engine Meta-Agent Team for Claude Code.
`AGENTS.md` is canonical; this file stays thin.

## Public Release Boundary

The `Public Release Allowlist (Hard Rule)` in `AGENTS.md` is mandatory.
For public GitHub work, stage only end-user install/runtime files and public
README/LICENSE/CHANGELOG material. Never stage internal docs, research,
benchmarks, tests or fixtures, logs/results, signing or credential material,
environment files, private paths/memory, or unrelated local work. Verify the
staged archive, not the dirty working tree.

## Route

1. Read `AGENTS.md`.
2. Read `.agentlas/mode-map.json`.
3. Use `skills/mode-classification/SKILL.md` to choose the mode.
4. If missing details would change files, adapters, or public/private boundary,
   use `skills/clarify-question-loop/SKILL.md`.
5. Route to one core team member:
   - `agents/10-single-agent-builder/agent.md`;
   - `agents/20-multi-agent-team-builder/agent.md`;
   - `agents/30-agentlas-packager/agent.md`;
   - `agents/40-session-agent-builder/agent.md`.
6. Load only matching `skills/*/SKILL.md`.
7. Use `skills/agentlas-auto-activation/SKILL.md` when local project
   continuity or `.agentlas` activation is part of the output.
8. Keep runtime-specific files as adapters over the canonical core.
9. Use `.agentlas/global-commands.json` to create and report the generated
   global command.

## Use When

- `/meta-agent`
- single agent builder
- agent team builder
- package an existing local or external agent
- Agentlas architecture packaging
- Codex, Claude Code, Gemini, Cursor, or AGENTS.md compatibility
- generated global command routing

## Verification

Run:

```bash
scripts/verify-package.sh
```
