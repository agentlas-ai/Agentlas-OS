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
9b. Declare the execution graph in `manifest.json`. This is what the Hub runtime
   reads to build the team; a package that omits it is published, charged for as
   a team, and can never be called:

   ```json
   {
     "entrypoints": { "orchestrator": "agents/00-orchestrator/agent.md" },
     "roster": ["agents/10-<role>/agent.md", "agents/20-<role>/agent.md"]
   }
   ```

   Write both keys explicitly. The runtime also accepts older spellings
   (`entrypoint`, `orchestrator`, `entry`; `workers`, `members`, `team`) and can
   derive the roster from `agents/<name>/agent.md`, but relying on that leaves
   the team's shape implicit and it drifts. Note that `entry` in `agentlas.json`
   is the PACKAGE entrypoint, not the team manager — never reuse it for that.
10. Emit runtime adapters and package verification.
11. Run `scripts/verify-team-package.sh <package-root>` before reporting
    `completed`. If it fails, do not hand off a result; correct the package by
    adding an orchestrator/HQ plus company-blueprint topology or by collapsing
    it to a valid single-agent package.

## Output

Return `team_topology`, `nodes`, `edges`, `memory_architecture`, `gates`,
`runtime_adapters`, `global_commands`, and `verification`.
