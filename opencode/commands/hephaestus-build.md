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

This is the clearer build-focused name for the older `/hephaestus` command.
