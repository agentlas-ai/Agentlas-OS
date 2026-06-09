# Single Agent Builder

## Mission

Create one installable Agentlas worker package. The output may include multiple
skills, setup guides, memory contracts, runtime adapters, research refresh, and
self-evolution proposals, but it remains a single agent package.

## Use When

- The user asks for one agent, helper, worker, specialist, or personal tool.
- The agent may need several skills but does not need a roster or team topology.
- The user asks for self-evolving, keeps-learning, latest/current research, or
  periodic refresh behavior.

## Must Include

- `AGENTS.md` as canonical core.
- `.agents/<agent-id>/agent.md` or equivalent single worker contract.
- `.agents/skills/<skill-id>/SKILL.md` for reusable capabilities.
- `.agentlas/agent-card.json`.
- `.agentlas/company-blueprint.json` with `single-agent` topology unless the
  user explicitly asks for a team.
- `.agentlas/memory-map.json`, `.agentlas/memory-tickets.jsonl`, and
  `.agentlas/vault-references.json`.
- Runtime adapters for requested targets.
- `.agentlas/global-commands.json`.
- One canonical global command for the worker, with matching Claude Code,
  Codex, Gemini CLI, Antigravity, generic AGENTS.md, and terminal command
  surfaces whenever those adapters are generated.

## Global Command Rule

Choose the command from the generated package slug, for example
`/research-agent`. Add the command while creating the package. Do not finish
without telling the user the command for each runtime in `global_commands`.

## Self-Evolution Rule

Self-evolution is proposal-first. The agent may collect sources, keep a
watchlist, generate repair kits, and propose patches. Human approval is required
before widening tools, adding connectors, changing secrets, or editing the
agent's own core instructions.

## Output

Return `status`, `evidence`, `output`, and `blockers`, plus the generated single
agent path, verification command, and `global_commands`.
