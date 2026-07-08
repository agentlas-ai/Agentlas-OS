---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
argument-hint: <request, or "ontology">
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus build surface


Raw arguments: `$ARGUMENTS`

Use the `agentlas-core-engine-meta-agent` skill from the Hephaestus plugin.
Expose `/prompts:hep-build` as the public Codex build prompt next to
`/prompts:hep-network` and `/prompts:hep-cloud`.

- If the arguments are `ontology`, resolve the runner exactly as in
  `/prompts:hep-network` and run `"$RUNNER" ontology`.
- Otherwise classify the request as single-agent-builder,
  multi-agent-team-builder, or agentlas-packager by independent ownership
  boundaries and execute the meta-agent procedure on: `$ARGUMENTS`. If
  single↔multi is unclear, ask first in plain language: "이 일을 한 명의
  전문가가 처음부터 끝까지 맡으면 되나요, 아니면 조사/분석/검토처럼 여러
  전문가가 나눠 맡고 마지막에 합쳐야 하나요?" Do not expose internal labels
  like ownership boundary, memory/context, synthesis, or produces/consumes.
- Before writing substantial package files, run the Builder Interview and
  Research Gate from `docs/builder-interview-research-gate.md`: ask an 8-12 Follow the briefing interview engine (`agentlas_cloud/interview/`): lens-table questions (anti_scope/done_signal/stop_criterion required), stop only at ambiguity <= 0.2 with dimension floors met for 2 consecutive rounds, then a coverage check and a one-sentence goal restate; also write `.agentlas/work-brief.json` (work-brief/1.0) so `cards migrate` derives triggers/anti-triggers from the user's confirmed answers.
  question first batch when the request is vague, continue follow-ups until the
  functional brief is clear, research official sources, similar agent
  repositories or comparables, academic/professional theory, and plugin docs,
  compare selected and rejected tools/plugins, synthesize domain-expert
  behavior, and create `docs/builder-interview.md`,
  `docs/research-sources.md`, `docs/tool-selection.md`,
  `docs/domain-expert-synthesis.md`, `docs/prompt-performance-contract.md`,
  and `.agentlas/capability-eval-plan.json`.
- Write all generated or repaired runtime agent instructions in English:
  `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `agent.md`, skills, workflow/command
  adapters, runtime prompts, handoff contracts, return contracts, and operating
  docs. Translate Korean or other-language source material into English agent
  behavior. Localized marketplace copy, routing trigger examples, and sample
  user inputs may use the target user language.
- After creating or repairing a package, run
  `scripts/verify-team-package.sh <package-root>`. If it fails, do not report
  `completed`; correct the shape by collapsing to a valid single-agent package
  or adding orchestrator/HQ plus company-blueprint topology.
- Include `global_commands` for the created agent or team in the final
  response, plus `interview_research` evidence.
- If a package was created/repaired in the current workspace, register it to
  local discovery immediately: run `./bin/hephaestus cards migrate . --tier local
  --overwrite` (or the same `hephaestus` runner in cache if local binary is
  unavailable), and include migration result in `evidence`.

If runtime discovery migration isn't needed, still validate that the package has
`./.agentlas/routing-card.json` and include that local-card artifact in `evidence`
when skipping migration.
