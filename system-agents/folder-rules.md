# Folder Rules (Canonical Placement Rules)

Builder- and gate-facing. Never copied into packages. These rules state, per
package type, exactly which canonical files from `system-agents/` are copied
where, what stays runtime-owned, and what is per-agent domain material.

Resolve `system-agents/` via the engine root - the same `$ENGINE` resolution
as hep-build Step 0 - never via the user's project folder.

## TEAM Packages

| Canonical source | Copy mode | Destination in package |
|---|---|---|
| `system-agents/pm-soul.md` | verbatim copy | `agents/10-pm-soul/agent.md` |
| `system-agents/memory-curator.md` | verbatim copy | `agents/20-memory-curator/agent.md` |
| `system-agents/policy-gate.md` | verbatim copy | `agents/30-policy-gate/agent.md` |
| `system-agents/eval-qa.md` | verbatim copy | `agents/40-eval-qa/agent.md` |
| `system-agents/orchestrator-protocol.md` | verbatim copy (protocol) | `docs/orchestrator-protocol.md` |
| Orchestrator body | team-authored | `agents/00-orchestrator/agent.md` (or the team's HQ path); its header must state it follows `docs/orchestrator-protocol.md` |

- The gate byte-compares each copied file above its `## Team Context
  (editable)` marker against the canonical source. Team-specific content goes
  only in that section.
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
