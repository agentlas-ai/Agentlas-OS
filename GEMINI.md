# Gemini CLI Adapter

This is a thin Gemini CLI adapter for the Agentlas Core Engine Meta-Agent Team.
`AGENTS.md` is the canonical source of truth.

## Public Release Boundary

The `Public Release Allowlist (Hard Rule)` in `AGENTS.md` is mandatory.
For public GitHub work, stage only end-user install/runtime files and public
README/LICENSE/CHANGELOG material. Never stage internal docs, research,
benchmarks, tests or fixtures, logs/results, signing or credential material,
environment files, private paths/memory, or unrelated local work. Verify the
staged archive, not the dirty working tree.

Google Antigravity shares the `~/.gemini/` home with the Gemini CLI and also
auto-loads this file and `AGENTS.md`. Its `/hep-build`,
`/hep-network`, `/hep-local`, `/hep-cloud`, and `/hep-hub` slash commands ship as
Antigravity workflows under `antigravity/` (see `antigravity/README.md`).

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
   - `30-agentlas-packager`;
   - `40-session-agent-builder`.
7. Use `.agents/skills/agentlas-auto-activation/SKILL.md` when local project
   continuity or `.agentlas` activation is part of the output.
8. Use `.agentlas/memory-map.json` for memory routing.
9. Use `.agentlas/global-commands.json` for generated command routing and final
   user handoff.

## Default Behavior

Create or package portable Markdown-first Agentlas agents and teams with
Codex, Claude Code, Gemini, Antigravity, Cursor, and AGENTS.md adapters.

## Global Command

This package exposes `/hep-build`, `/hep-network`, `/hep-local`,
`/hep-cloud`, and `/hep-hub` for Gemini CLI through
`gemini/extension/commands/hep-*.toml`, with fallback user commands at
`.gemini/commands/hep-*.toml`. For Antigravity the same commands ship as
workflows at `antigravity/workflows/hep-*.md` (global install target
`~/.gemini/antigravity/global_workflows/hep-*.md`; project fallback
`.agents/workflows/hep-*.md`). Generated agents must receive their own
Gemini extension command, Antigravity workflow, and a matching
`.agentlas/global-commands.json` entry.

The extension exposes one Workforce MCP, local `hephaestus-network`. Network
federates registered Local, owner Cloud, and public Hub; the other three
commands are exact single-source scopes and never widen. Core performs remote
upstream calls internally, so the extension must not also expose a direct
`agentlas` MCP with duplicate `workforce.*` tools.
