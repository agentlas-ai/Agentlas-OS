---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
argument-hint: <request, or "ontology">
---

# Hephaestus build surface

Raw arguments: `$ARGUMENTS`

Use the `agentlas-core-engine-meta-agent` skill from the Hephaestus plugin.
`/prompts:hephaestus-build` is the clear build-focused name for the older
`/prompts:hephaestus` prompt.

- If the arguments are `ontology`, resolve the runner exactly as in
  `/prompts:hephaestus-network` and run `"$RUNNER" ontology`.
- Otherwise classify the request as single-agent-builder,
  multi-agent-team-builder, or agentlas-packager per the skill and execute the
  meta-agent procedure on: `$ARGUMENTS`
- Include `global_commands` for the created agent or team in the final
  response.
