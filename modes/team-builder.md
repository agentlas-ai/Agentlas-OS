# Team Builder

## Purpose

Create an installable multi-role agent team package. The team behaves like a
small operating system, not a loose list of prompts.

## Required Team Layers

- Orchestrator/HQ for intake, routing, sequencing, and final synthesis.
- PM Soul or project owner for intent, decisions, risks, evidence, and open
  loops.
- Memory Curator for source-map-first routing, redaction, deduplication,
  conflict handling, and future searchability.
- Policy Gate for dangerous actions, secret boundaries, budget/tool changes,
  and public/private release decisions.
- Worker roles for domain work.
- Eval judge and QA/evidence gate before final handoff.
- Runtime Adapter Engineer for Codex, Claude Code, Gemini CLI, Antigravity,
  Cursor, and generic `AGENTS.md` surfaces.
- Global Command Registry for one orchestrator/HQ command across runtimes.
- Builder Interview and Research Gate artifacts:
  `docs/builder-interview.md`, `docs/research-sources.md`,
  `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
  `docs/prompt-performance-contract.md`, and
  `.agentlas/capability-eval-plan.json`.

## Required Contracts

- Handoff brief: `from`, `to`, `intent`, `context`, `constraints`,
  `allowed_tools`, `required_output`, `return_to`, `risk`, `budget`.
- Return contract: `status`, `evidence`, `output`, `blockers`.
- Memory Events emitted by workers after substantial work.
- Memory Tickets wrapped by runtime/orchestrator before Memory Curator review.
- PM Soul owns project memory. Policy Gate controls shared team-memory
  promotion.
- `.agentlas/global-commands.json` owns the public team command. Worker roles
  route through orchestrator/HQ unless the user explicitly requested direct
  worker commands.

## Builder Quality Rule

Run `docs/builder-interview-research-gate.md` before generation. Ask an 8-12
question first batch and keep asking follow-ups until the team's mission,
worker boundaries, handoff artifacts, examples, tools/plugins, memory policy,
safety gates, and evaluation rubric are clear. Research official sources,
similar agents or repositories, academic/professional theory, and plugin docs
before writing role prompts. Add a worker only when interview or research
evidence shows a real ownership boundary.

## Do Not

- Do not collapse a requested team into one helper.
- Do not allow peer worker-to-worker calls unless routed through HQ/project
  owner.
- Do not ship a team package without eval, QA/evidence, policy, and memory
  architecture.
- Do not ship a generic HQ roster without interview, research, tool-selection,
  domain-expert-synthesis, prompt-performance, and capability-eval artifacts
  unless it is explicitly a minimal private scaffold.
- Do not finish without reporting the orchestrator/HQ command in
  `global_commands`.
