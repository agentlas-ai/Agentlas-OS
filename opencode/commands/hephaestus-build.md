---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
---

# Hephaestus build surface

Raw arguments: `$ARGUMENTS`

Use the `hephaestus-network` skill's runner resolution. If the arguments are
`ontology`, run `"$RUNNER" ontology`. Otherwise classify the request as
single-agent-builder, multi-agent-team-builder, or agentlas-packager, execute
the meta-agent procedure on `$ARGUMENTS`, and include `global_commands` for
the created agent or team in the final response.

Before writing substantial package files, run the Builder Interview and
Research Gate from `docs/builder-interview-research-gate.md`: ask an 8-12
question first batch when the request is vague, continue follow-ups until the
functional brief is clear, research official sources, similar agent
repositories or comparables, academic/professional theory, and plugin docs,
compare selected and rejected tools/plugins, synthesize domain-expert behavior,
and create `docs/builder-interview.md`, `docs/research-sources.md`,
`docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
`docs/prompt-performance-contract.md`, and `.agentlas/capability-eval-plan.json`.
Include `interview_research` evidence in the final response.

This is the clearer build-focused name for the older Hephaestus command.
