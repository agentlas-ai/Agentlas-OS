---
name: hephaestus-build
description: "Use when the user types /prompts:hep-build, mentions @Hephaestus for build work, asks to create a single Agentlas agent, create a multi-agent team, or package an existing local/external agent into Agentlas architecture."
---

# Hephaestus Build

## Procedure

1. Treat this as the public Codex build surface. Do not expose or ask the user
   to invoke the older internal support skill names.
2. Read `AGENTS.md` and `.agentlas/mode-map.json` when they exist in the
   current workspace.
3. Run the public mode classifier by independent ownership boundaries, not by
   keywords such as "team":
   - package or repair existing material -> `30-agentlas-packager`;
   - one independently owned context/tools/success standard ->
     `10-single-agent-builder`;
   - two or more roles with separate context, permissions, success standards,
     handoff, or synthesis needs -> `20-multi-agent-team-builder`.
   If the shape is unclear, ask before generating. The user-facing question
   must be plain language, for example: "이 일을 한 명의 전문가가 처음부터 끝까지
   맡으면 되나요, 아니면 조사/분석/검토처럼 여러 전문가가 나눠 맡고 마지막에
   합쳐야 하나요?" Do not expose internal labels such as `single-agent`,
   `team-builder`, ownership boundary, memory/context, synthesis, or
   produces/consumes.
4. Run the Builder Interview and Research Gate from
   `docs/builder-interview-research-gate.md` before writing substantial package
   files:
   - ask an 8-12 question first batch when the request is vague;
   - continue follow-ups until target user, tasks, inputs, outputs, examples,
     role count, separated tools or permissions, final merge needs, execution
     order, memory, failure modes, and evals are clear;
   - phrase shape questions in everyday language. Ask who handles which part,
     whether each role needs different files/accounts/tools, whether someone
     must merge the result, and whether work can run at the same time or must
     pass from one person to the next;
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
8. Write all generated or repaired runtime agent instructions in English:
   `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `agent.md`, skills, workflow/command
   adapters, runtime prompts, handoff contracts, return contracts, and
   operating docs. Translate Korean or other-language source material into
   English agent behavior. Localized public copy, routing trigger examples, and
   sample user inputs may use the target user language.
9. Emit or repair Agentlas contracts, including `.agentlas` activation seed
   files and `.agentlas/global-commands.json` when local continuity is part of
   the output.
10. Add the generated command to Claude Code, Codex, Gemini CLI, generic
   AGENTS.md, and terminal adapters. For teams, expose the orchestrator/HQ
   command and route workers through HQ unless direct worker commands were
   requested.
11. Run `scripts/verify-team-package.sh <generated-package-root>` for generated
    or repaired packages. If it fails, do not report completion; collapse the
    output to a single-agent package or add the required orchestrator/HQ and
    team contracts.
12. Verify with `scripts/verify-package.sh`.

## Output

Return `status`, `evidence`, `output`, `global_commands`, `interview_research`,
and `blockers`.
