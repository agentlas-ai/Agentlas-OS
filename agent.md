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
- Install and verification scripts when packaging for reuse.

## Core Rules

- Keep the canonical instructions in `AGENTS.md`.
- Keep adapters thin.
- Run mode classification before routing.
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

## Done Criteria

The generated or packaged output is done only when a user can:

1. see whether it is single-agent, team-builder, or packager output;
2. inspect the visible structure;
3. install it into a project;
4. call it from Codex, Claude Code, or Gemini when requested;
5. see the Agentlas architecture contracts as files;
6. run a verification command without hidden private dependencies.
