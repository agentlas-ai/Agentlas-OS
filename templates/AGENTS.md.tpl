# {{TEAM_NAME}} Instructions

Use this repo as a portable agent team.

## Source Of Truth

- `AGENTS.md` is canonical.
- Runtime adapters are thin.
- `.agentlas/global-commands.json` is the global command registry.
- Durable memory goes through `.agentlas/memory-tickets.jsonl`.

## Team

{{TEAM_ROLES}}

## Output Contract

Return status, evidence, output, global_commands, and blockers.

## Global Command

Canonical command: `/{{COMMAND_SLUG}}`

Expose this command in Claude Code, Codex, Gemini CLI, Antigravity, generic
AGENTS.md tools, and terminal adapters. For teams, this command routes to
orchestrator/HQ.
