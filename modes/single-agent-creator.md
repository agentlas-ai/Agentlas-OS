# Single-Agent Creator

## Purpose

Create one installable Agentlas worker package. The package may include multiple
skills, commands, setup guides, memory contracts, runtime adapters, and
self-evolution proposals, but it is still one worker.

## Required Structure

- `AGENTS.md` as the canonical cross-runtime entry point.
- `.agents/<agent-id>/agent.md` for the worker contract.
- `.agents/skills/<skill-id>/SKILL.md` for reusable capabilities.
- `docs/builder-interview.md` from the pre-generation interview.
- `docs/research-sources.md` with official/GitHub/academic or professional
  sources and design implications.
- `docs/tool-selection.md` with selected and rejected tools/plugins,
  permission boundaries, fallbacks, and smoke tests.
- `docs/domain-expert-synthesis.md` combining interview answers, similar
  agent/repository research, academic or professional theory, and tool choices
  into specialist behavior.
- `docs/prompt-performance-contract.md` for the worker and each reusable skill.
- `.agentlas/capability-eval-plan.json` with positive and anti-trigger cases.
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

## Builder Quality Rule

Run `docs/builder-interview-research-gate.md` before generation. Ask an 8-12
question first batch and keep asking follow-ups until the worker's real job,
inputs, outputs, examples, tools, memory policy, failure modes, and evaluation
rubric are clear. Research official sources, similar agents or repositories,
academic/professional theory, and plugin docs before writing the worker prompt.
The single agent must be useful even when the user's initial request was vague.

## Do Not

- Do not invent HQ, company, swarm, or multi-agent roster for a normal single
  worker request.
- Do not remove memory architecture just because the package is single-agent.
- Do not allow autonomous self-modification without explicit approval.
- Do not ship a prompt-only worker without interview, research, tool-selection,
  domain-expert-synthesis, prompt-performance, and capability-eval artifacts
  unless it is explicitly a minimal private scaffold.
- Do not finish without reporting `global_commands` to the user.
