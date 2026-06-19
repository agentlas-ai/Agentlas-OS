---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
argument-hint: <request, or "ontology">
---

# Hephaestus build surface

Raw arguments: `$ARGUMENTS`

Use the `agentlas-core-engine-meta-agent` skill from the Hephaestus plugin.
Expose `/prompts:hephaestus-build` as the public Codex build prompt next to
`/prompts:hephaestus-network` and `/prompts:hephaestus-cloud`.

- If the arguments are `ontology`, resolve the runner exactly as in
  `/prompts:hephaestus-network` and run `"$RUNNER" ontology`.
- Otherwise classify the request as single-agent-builder,
  multi-agent-team-builder, or agentlas-packager per the skill and execute the
  meta-agent procedure on: `$ARGUMENTS`.
- Before writing substantial package files, run the Builder Interview and
  Research Gate from `docs/builder-interview-research-gate.md`: ask an 8-12
  question first batch when the request is vague, continue follow-ups until the
  functional brief is clear, research official sources, similar agent
  repositories or comparables, academic/professional theory, and plugin docs,
  compare selected and rejected tools/plugins, synthesize domain-expert
  behavior, and create `docs/builder-interview.md`,
  `docs/research-sources.md`, `docs/tool-selection.md`,
  `docs/domain-expert-synthesis.md`, `docs/prompt-performance-contract.md`,
  and `.agentlas/capability-eval-plan.json`.
- Include `global_commands` for the created agent or team in the final
  response, plus `interview_research` evidence.
