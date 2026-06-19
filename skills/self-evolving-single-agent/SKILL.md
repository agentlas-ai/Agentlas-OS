---
name: self-evolving-single-agent
description: "Use when generating a single installable agent that should keep learning, track sources, refresh research, propose repairs, or improve itself over time without becoming a multi-agent team."
---

# Self-Evolving Single Agent

## Procedure

1. Keep the package as one worker unless the user asks for a team.
2. Run `docs/builder-interview-research-gate.md` before generation: ask an
   8-12 question first batch, research official sources, similar agent
   repositories or comparables, academic/professional theory, and plugin docs,
   compare tool/plugin choices, and write the domain-expert synthesis plus
   prompt-performance contract before creating the worker prompt.
3. Add memory architecture even for the single worker:
   - `.agentlas/memory-map.json`;
   - `.agentlas/vault-references.json`;
   - project memory owned by PM Soul/project owner;
   - Memory Events and Memory Tickets for durable updates.
4. If the task depends on current sources, add a research-refresh command,
   watchlist memory section, references, and optional scheduled workflow.
5. Add `docs/builder-interview.md`, `docs/research-sources.md`,
   `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
   `docs/prompt-performance-contract.md`, and
   `.agentlas/capability-eval-plan.json` unless explicitly creating a minimal
   private scaffold.
6. Make self-evolution proposal-first: draft patches or repair kits, then wait
   for human approval before changing tools, connectors, secrets, or core
   instructions.
7. Add `.agentlas/global-commands.json` and one public global command for the
   worker across Claude Code, Codex, Gemini CLI, generic AGENTS.md, and
   terminal adapters.

## Output

Return `agent_package`, `skills`, `memory_contract`, `refresh_loop`,
`approval_gate`, `global_commands`, and `verification`.
