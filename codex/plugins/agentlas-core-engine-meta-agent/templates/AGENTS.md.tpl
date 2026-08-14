# {{TEAM_NAME}} Instructions

Use this repo as a portable agent team.

## Source Of Truth

- `AGENTS.md` is canonical.
- Runtime adapters are thin.
- `.agentlas/global-commands.json` is the global command registry.
- Durable memory goes through `.agentlas/memory-tickets.jsonl`.
- Agent behavior quality is governed by `docs/builder-interview.md`,
  `docs/research-sources.md`, `docs/tool-selection.md`,
  `docs/domain-expert-synthesis.md`, `docs/prompt-performance-contract.md`, and
  `.agentlas/capability-eval-plan.json`.

## Builder Interview And Research

Before changing the agent's core behavior, ask enough interview questions to
clarify target user, recurring tasks, inputs, outputs, examples, tools/plugins,
memory policy, failure modes, and evaluation. Research official sources,
similar agent repositories or comparables, academic/professional theory, and
plugin docs, compare selected and rejected tools or plugins, write
`docs/domain-expert-synthesis.md`, and update the prompt-performance contract
before editing role prompts or skills.

## Team

{{TEAM_ROLES}}

## Output Contract

Return status, evidence, output, global_commands, interview_research, and
blockers.

## Global Command

Canonical command: `/{{COMMAND_SLUG}}`

Expose this command in Claude Code, Codex, Gemini CLI, Antigravity, generic
AGENTS.md tools, and terminal adapters. For teams, this command routes to
orchestrator/HQ.
