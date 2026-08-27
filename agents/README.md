# Agents

These are the four visible public team roles. Each role has a single
`agent.md` contract that can be read by humans or adapted by a runtime.

The runtime-neutral source is mirrored under `.agents/` for tools that discover
portable agent folders.

## Roles

- `10-single-agent-builder`: creates one installable self-evolving worker
  package.
- `20-multi-agent-team-builder`: creates a multi-role team package with
  orchestrator, PM Soul, memory, policy, eval, QA, and runtime adapters.
- `30-agentlas-packager`: converts existing local or external agents/teams into
  the Agentlas architecture and prepares Codex, Claude, local install, or public
  release packaging.
- `40-session-agent-builder`: converts explicitly exported sessions into an
  owner-reviewed reusable Agentlas agent or team candidate.

PM Soul, Memory Curator, global command registry, runtime adapters,
sitemap/task-bias, policy, and eval are required architecture components inside
generated or packaged outputs. They are not extra members of this meta-agent
team.
