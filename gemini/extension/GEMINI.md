# Hephaestus Gemini Extension

Public GitHub release work must follow the canonical `Public Release Allowlist
(Hard Rule)` in the repository `AGENTS.md`: publish only end-user
install/runtime files and public README/LICENSE/CHANGELOG material; never
publish internal docs, research, benchmarks, tests/fixtures, results/logs,
signing/credentials, environment files, private paths/memory, or unrelated
local work.

Use Hephaestus, the Agentlas Core Engine Meta-Agent, when the user wants to
create one Agentlas agent, create a multi-agent team, package an existing agent,
or open the local ontology GUI.

Generated or packaged agents must include `.agentlas/global-commands.json` and
the final response must include `global_commands`.

Agentlas Workforce continuity is mandatory, not an explicit goal-mode feature.
At the start of every nontrivial project turn call
`workforce.goal_context({projectDir})`. Reuse an active exact roster plus local
skills when sufficient; recruit only a real gap. Every
`workforce.prepare_execution` call must include `projectDir` and the incumbent
`goalId` when continuing; Core derives one when absent and automatically binds
the successful plan. Keep it across turns, sessions, restarts, compaction, and
lease expiry. Release only after explicit whole-goal completion/cancellation
through `workforce.complete_goal(explicitCompletion=true)`.
