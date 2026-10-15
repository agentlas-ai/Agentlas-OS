---
description: Run {{TEAM_NAME}} inside Google Antigravity. AGENTS.md is canonical.
---

# /{{COMMAND_SLUG}}

Run **{{TEAM_NAME}}** inside this Antigravity workspace. `AGENTS.md` at the
repository root is the canonical source of truth; this workflow is only a thin
Antigravity command surface over it.

The text the user typed after `/{{COMMAND_SLUG}}` is the request. It may be empty
or a concrete task for this agent or team.

## Route

1. Read `AGENTS.md` (canonical) and the agent or orchestrator contract under
   `.agents/`.
2. Read `.agentlas/global-commands.json` plus any `.agentlas/` contracts the task
   needs (memory map, company blueprint, policy gate).
3. For a team package, enter through the orchestrator/HQ and route worker roles
   through it. For a single-agent package, run the worker directly.
4. Do the smallest useful unit of work, then verify with
   `scripts/verify-package.sh` when the package ships one.
5. Return `status`, `evidence`, `output`, `global_commands`, and `blockers`.
   The `global_commands` section must list the exact Claude Code, Codex,
   Antigravity, generic `AGENTS.md`, and terminal commands from
   `.agentlas/global-commands.json`.

## What Antigravity already loads

Antigravity natively reads `AGENTS.md`, `GEMINI.md`, and `.agents/skills/` with
no extra setup, so keep behavior in those canonical files and keep this workflow
thin.

## Install scope

`antigravity/workflows/{{COMMAND_SLUG}}.md` is the canonical workflow body. It is
mirrored at two scopes:

| Scope | File | Effect |
| --- | --- | --- |
| Global | `~/.gemini/antigravity/global_workflows/{{COMMAND_SLUG}}.md` | `/{{COMMAND_SLUG}}` in **every** Antigravity workspace. |
| Project | `.agents/workflows/{{COMMAND_SLUG}}.md` | `/{{COMMAND_SLUG}}` whenever this repo is open. Ships in the package. |

Antigravity keeps its data under `~/.gemini/` (`antigravity/`, `antigravity-ide/`),
so the global workflow path above lives there.
