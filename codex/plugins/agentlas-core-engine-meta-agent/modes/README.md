# Modes

The meta-agent has four work modes. Choose one before designing files.

- `single-agent-creator`: one installable worker package.
- `team-builder`: a multi-role agent team package.
- `agentlas-packager`: convert or repair existing local/external agents and
  teams into Agentlas architecture.
- `session-agent-builder`: convert explicitly exported session sources into a
  reviewed reusable agent or team candidate.

The mode map is `.agentlas/mode-map.json`.

All modes must emit `.agentlas/global-commands.json` and return
`global_commands` after generation so the user knows how to run the new agent.
