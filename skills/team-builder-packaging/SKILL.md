---
name: team-builder-packaging
description: "Use when generating or auditing a multi-role agent team package with orchestrator, PM Soul, Memory Curator, Policy Gate, workers, eval, QA, handoffs, and runtime adapters."
---

# Team Builder Packaging

## Procedure

1. Start with the orchestrator/HQ.
2. Run `docs/builder-interview-research-gate.md` before writing the roster:
   ask an 8-12 question first batch, research official sources, similar agent
   repositories or comparables, academic/professional theory, and plugin docs,
   compare tool/plugin choices, and write the domain-expert synthesis plus
   prompt-performance contract.
3. Add PM Soul or project owner.
4. Add Memory Curator and Memory Ticket handoff.
5. Add Policy Gate, eval judge, and QA/evidence gate.
6. Add workers only for real domain ownership proved by interview or research.
7. Add `docs/builder-interview.md`, `docs/research-sources.md`,
   `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
   `docs/prompt-performance-contract.md`, and
   `.agentlas/capability-eval-plan.json` unless explicitly creating a minimal
   private scaffold.
8. Encode handoff and return contracts.
9. Emit one orchestrator/HQ global command in `.agentlas/global-commands.json`
   and runtime command files. Do not expose worker commands unless requested.
10. Emit runtime adapters and package verification.

## Output

Return `team_topology`, `nodes`, `edges`, `memory_architecture`, `gates`,
`runtime_adapters`, `global_commands`, and `verification`.
