# Folder Rules (Canonical Placement Rules)

Builder- and gate-facing. Never copied into packages. These rules state, per
package type, exactly which canonical files from `system-agents/` are copied
where, what stays runtime-owned, and what is per-agent domain material.

Resolve `system-agents/` via the engine root - the same `$ENGINE` resolution
as hep-build Step 0 - never via the user's project folder.

## TEAM Packages (OS-resident model — owner decision 2026-08-08)

System members are NOT copied into team packages anymore. The copy model was
measured dead: 0 of 32 live teams carried the canonical body, so every copy
was a divergent rewrite. The runtimes already seed these roles as builtins
(`installed_agents` rows `builtin-agentlas-pm-soul`, `-memory-curator`,
`-task-bias` — desktop `architecture/manifest.ts` + terminal
`architecture.data.json`), and the engine ships the deterministic curator and
judge chokepoints. A team package therefore contains:

| Component | Where it lives |
|---|---|
| PM Soul / Memory Curator / Policy Gate / eval judge | **OS builtins — never inside the package** |
| Their outputs | `.agentlas/memory-map.json`, `.agentlas/memory-tickets.jsonl`, project soul log (package/project-local, never uploaded raw) |
| `system-agents/orchestrator-protocol.md` | verbatim copy (protocol) → `docs/orchestrator-protocol.md` |
| Orchestrator body | team-authored — `agents/00-orchestrator/agent.md` (commands HQs); HQ orchestrators (`01-*`) command workers. Header must state it follows `docs/orchestrator-protocol.md` |

- Builders MUST NOT author `agents/10-pm-soul/`, `20-memory-curator/`,
  `30-policy-gate/`, or `40-eval-qa/` members. `team_shape` no longer requires
  them; a leftover copy from an old package is reported as a strip note and
  removed on the next repackage (team-specific domain rules found inside it
  are promoted into the team's `agentlas.md` context section, not deleted).
- The orchestrator body is the one system role that stays team-specific; the
  protocol file is the canonical part.

## SINGLE Packages

Single-agent packages copy NONE of the four canonical bodies. There is no
team to coordinate, so there is no pm-soul, memory-curator, policy-gate, or
eval-qa member, and the builder must not author substitutes. What a single
package relies on instead:

| Function | What a single package relies on |
|---|---|
| Memory curation | The deterministic always-on runtime curator (every turn, no extra LLM call) applying G1-G5, plus the Memory Ticket ledger `.agentlas/memory-tickets.jsonl` |
| Project continuity | The project soul log instantiated from the PM Soul memory template in the target project |
| Policy | The host PreToolUse hook (tool broker); the package declares needs in `.agentlas/mcp-policy.json`, never enforcement logic |
| Evaluation | `.agentlas/capability-eval-plan.json` as declaration; judging runs in the host judge engine |

## Runtime-Owned (never packaged, any type)

- Policy enforcement logic - the PreToolUse hook is the only chokepoint.
- Judge engine logic (`judgeChecklist`, `EVAL_STUCK`).
- Ontology runtime state.
- Context maps and code maps (project-level, not agent-level).

A package that carries any of these is defective. The packager removes them
and replaces role bodies with the canonical delegation declarations.

## Per-Agent Domain Material (I5 - exempt)

`skills/`, `knowledge/`, `styles/`, `data/`, `scripts/`, and benchmarks are
per-agent domain assets. They are never canonicalized and never
byte-compared. These are supposed to differ between agents; do not "fix"
differences.
