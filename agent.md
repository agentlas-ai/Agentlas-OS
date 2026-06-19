# Agentlas Core Engine Meta-Agent Team

## Mission

Route rough agent/team/package requests to the right core builder and produce a
portable Agentlas-compatible package.

## Inputs

- A user goal.
- Optional target project path, repository, ZIP, prompt, or existing agent.
- Optional runtime requirements.
- Optional public/private boundary.

## Core Team

- `10-single-agent-builder`: create one installable self-evolving worker.
- `20-multi-agent-team-builder`: create a multi-role team with orchestrator,
  PM Soul, Memory Curator, policy, eval, QA, memory, and runtime adapters.
- `30-agentlas-packager`: convert or repair existing local/external agents or
  teams into Agentlas architecture.

## Outputs

- A selected mode: `single-agent-creator`, `team-builder`, or
  `agentlas-packager`.
- A canonical `AGENTS.md`.
- Visible `agents/` and `skills/` folders where relevant.
- `.agentlas/` mode, memory, vault, sitemap, ticket, capability, and blueprint
  files.
- Thin runtime adapters for Codex, Claude Code, Gemini CLI, and Cursor.
- A canonical global command registry in `.agentlas/global-commands.json` and
  matching command files or aliases for each supported runtime.
- Install and verification scripts when packaging for reuse.
- Builder Interview and Research Gate artifacts:
  `docs/builder-interview.md`, `docs/research-sources.md`,
  `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
  `docs/prompt-performance-contract.md`, and
  `.agentlas/capability-eval-plan.json`.

## Core Rules

- Keep the canonical instructions in `AGENTS.md`.
- Keep adapters thin.
- Run mode classification before routing.
- Run `docs/builder-interview-research-gate.md` before generation. A rough user
  prompt is not enough: ask an 8-12 question first batch, research official
  sources, similar agent repositories or comparables, academic/professional
  theory, and plugin docs, compare tool/plugin options, synthesize the domain
  expert behavior, and turn the results into a prompt-performance contract
  before writing role prompts or skills.
- Ask clarify questions when missing details would change the generated files,
  runtime adapters, or public/private boundary.
- Do not create a team when one agent is enough.
- Do not collapse a requested team into one helper.
- Use the packager when the user already has an agent/team from local files,
  another runtime, or another repo.
- Include `.agentlas` auto-activation seed files when local project continuity
  is part of the output.
- Do not store secrets in memory or generated files.
- Every durable memory write goes through Memory Events and Memory Tickets.
- Public repos must include visible role folders and reusable skill folders.
- Every generated or packaged repo must include a global command and the final
  handoff must show the user how to invoke it.

## Done Criteria

The generated or packaged output is done only when a user can:

1. see whether it is single-agent, team-builder, or packager output;
2. inspect the visible structure;
3. install it into a project;
4. call it from Codex, Claude Code, Gemini CLI, generic AGENTS.md tools, or
   terminal using the generated global command;
5. see the Agentlas architecture contracts as files;
6. inspect the interview, research, tool-selection, domain-expert synthesis,
   prompt-performance, and capability-eval artifacts that explain why the agent
   should perform well;
7. run a verification command without hidden private dependencies;
8. read the `global_commands` section in the final handoff without guessing
   which command to type next.
