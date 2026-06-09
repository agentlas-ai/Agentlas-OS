# Single-Agent Creator

## Purpose

Create one installable Agentlas worker package. The package may include multiple
skills, commands, setup guides, memory contracts, runtime adapters, and
self-evolution proposals, but it is still one worker.

## Required Structure

- `AGENTS.md` as the canonical cross-runtime entry point.
- `.agents/<agent-id>/agent.md` for the worker contract.
- `.agents/skills/<skill-id>/SKILL.md` for reusable capabilities.
- `.agentlas/agent-card.json`.
- `.agentlas/company-blueprint.json` with `single-agent` topology unless the
  user explicitly asks for a team.
- `.agentlas/memory-map.json` and `.agentlas/vault-references.json`.
- `.agentlas/global-commands.json` with one public command for the worker.
- `memory/<slug>-memory.md` or `.agentlas/project-soul-memory.md` for project
  memory owned by PM Soul/project owner.
- Thin adapters for Codex, Claude Code, Gemini CLI, Antigravity, Cursor, and
  generic `AGENTS.md` tools.
- Runtime command files or aliases for Claude Code, Codex, Gemini CLI,
  Antigravity, generic AGENTS.md tools, and terminal use.

## Self-Evolution Rule

Self-evolving means proposal-first improvement:

- keep a watchlist or research-refresh command when the task requires current
  sources or ongoing learning;
- write repair kits, diffs, or recommendations;
- require human approval before widening tools, adding connectors, changing
  secrets, or editing the agent's own core instructions.

## Do Not

- Do not invent HQ, company, swarm, or multi-agent roster for a normal single
  worker request.
- Do not remove memory architecture just because the package is single-agent.
- Do not allow autonomous self-modification without explicit approval.
- Do not finish without reporting `global_commands` to the user.
