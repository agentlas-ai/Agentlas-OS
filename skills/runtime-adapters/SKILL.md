---
name: runtime-adapters
description: "Use when creating Codex, Claude Code, Antigravity, Cursor, or AGENTS.md runtime adapters from one canonical agent core. Use whenever a generated repo needs multiple AI runtimes without duplicating instructions."
---

# Runtime Adapters

## Rules

- `AGENTS.md` is canonical.
- `.claude/`, `.codex/`, `.cursor/`, `antigravity/`, and root `skills/` are thin
  adapters or mirrors.
- `.agentlas/global-commands.json` records the command each adapter exposes.
- Adapter text should point back to `AGENTS.md`.
- Do not claim identical behavior across runtimes. Say the canonical core is
  portable and each adapter maps it into local conventions.

## Required Adapters

- Codex: plugin manifest plus skill and `commands/<slug>.md`.
- Claude Code: command, agent, and skill adapter under `.claude/commands/`.
- Antigravity: `GEMINI.md` plus `antigravity/workflows/<slug>.md`.
- Generic: root `AGENTS.md` with the command alias documented.
