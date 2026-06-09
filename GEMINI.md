# Gemini CLI Adapter

This is a thin Gemini CLI adapter for the Agentlas Core Engine Meta-Agent Team.
`AGENTS.md` is the canonical source of truth.

Google Antigravity shares the `~/.gemini/` home with the Gemini CLI and also
auto-loads this file and `AGENTS.md`. Its `/hephaestus` slash command ships as
an Antigravity workflow under `antigravity/` (see `antigravity/README.md`).

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
9. Use `.agentlas/global-commands.json` for generated command routing and final
   user handoff.

## Default Behavior

Create or package portable Markdown-first Agentlas agents and teams with
Codex, Claude Code, Gemini, Antigravity, Cursor, and AGENTS.md adapters.

## Global Command

This package exposes `/hephaestus` for Gemini CLI through
`gemini/extension/commands/hephaestus.toml`, with a fallback user command at
`.gemini/commands/hephaestus.toml`. For Antigravity the same command ships as a
workflow at `antigravity/workflows/hephaestus.md` (global install target
`~/.gemini/antigravity/global_workflows/hephaestus.md`; project fallback
`.agents/workflows/hephaestus.md`). Generated agents must receive their own
Gemini extension command, Antigravity workflow, and a matching
`.agentlas/global-commands.json` entry.
