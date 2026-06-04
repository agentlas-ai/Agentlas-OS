# Gemini CLI Adapter

This is a thin Gemini CLI adapter for the Agentlas Core Engine Meta-Agent Team.
`AGENTS.md` is the canonical source of truth.

## Startup

1. Read `AGENTS.md`.
2. Read `.agents/agentlas-core-engine-meta-agent/agent.md`.
3. Read `.agentlas/mode-map.json`.
4. Use `.agents/skills/mode-classification/SKILL.md` to choose the mode.
5. If missing details would change files, adapters, or public/private boundary,
   use `.agents/skills/clarify-question-loop/SKILL.md`.
6. Route to one core team member:
   - `10-single-agent-builder`;
   - `20-multi-agent-team-builder`;
   - `30-agentlas-packager`.
7. Use `.agents/skills/agentlas-auto-activation/SKILL.md` when local project
   continuity or `.agentlas` activation is part of the output.
8. Use `.agentlas/memory-map.json` for memory routing.

## Default Behavior

Create or package portable Markdown-first Agentlas agents and teams with
Codex, Claude Code, Gemini, Cursor, and AGENTS.md adapters.
