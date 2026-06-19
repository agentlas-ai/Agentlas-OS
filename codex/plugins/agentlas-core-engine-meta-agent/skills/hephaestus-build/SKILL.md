---
name: hephaestus-build
description: "Use when the user types /prompts:hephaestus-build, mentions @Hephaestus for build work, asks to create a single Agentlas agent, create a multi-agent team, or package an existing local/external agent into Agentlas architecture."
---

# Hephaestus Build

## Procedure

1. Treat this as the public Codex build surface. Do not expose or ask the user
   to invoke the older internal support skill names.
2. Read `AGENTS.md` and `.agentlas/mode-map.json` when they exist in the
   current workspace.
3. Run the public mode classifier:
   - package or repair existing material -> `30-agentlas-packager`;
   - multi-role roster/company/HQ -> `20-multi-agent-team-builder`;
   - one worker -> `10-single-agent-builder`.
4. Run the Builder Interview and Research Gate from
   `docs/builder-interview-research-gate.md` before writing substantial package
   files:
   - ask an 8-12 question first batch when the request is vague;
   - continue follow-ups until target user, tasks, inputs, outputs, examples,
     tools/plugins, memory, failure modes, and evals are clear;
   - research official or primary docs, similar agent repositories or
     comparables, GitHub examples, academic/professional theory, and
     tool/plugin docs;
   - compare selected and rejected tools/plugins with permission, secret,
     fallback, and smoke-test notes;
   - synthesize domain-expert behavior from interview answers, comparable
     agents/repos, theory, and tool choices;
   - write `docs/builder-interview.md`, `docs/research-sources.md`,
     `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
     `docs/prompt-performance-contract.md`, and
     `.agentlas/capability-eval-plan.json`.
5. If missing narrow details still change files, adapters, or public/private
   boundaries, ask one to five clarify questions before generating.
6. Pick one:
   - `10-single-agent-builder`;
   - `20-multi-agent-team-builder`;
   - `30-agentlas-packager`.
7. Load matching support skills.
8. Emit or repair Agentlas contracts, including `.agentlas` activation seed
   files and `.agentlas/global-commands.json` when local continuity is part of
   the output.
9. Add the generated command to Claude Code, Codex, Gemini CLI, generic
   AGENTS.md, and terminal adapters. For teams, expose the orchestrator/HQ
   command and route workers through HQ unless direct worker commands were
   requested.
10. Verify with `scripts/verify-package.sh`.

## Output

Return `status`, `evidence`, `output`, `global_commands`, `interview_research`,
and `blockers`.
