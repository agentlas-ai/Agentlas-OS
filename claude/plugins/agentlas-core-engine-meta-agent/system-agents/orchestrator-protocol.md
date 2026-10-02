# Orchestrator Protocol (Canonical - Protocol Only)

This file is the command covenant every team orchestrator must follow. The
orchestrator's body stays team-authored; its header must state that it follows
this protocol. Builders copy this file verbatim into the team package at
`docs/orchestrator-protocol.md` so the reference resolves offline. A gate
byte-compares everything above the `## Team Context (editable)` marker against
`system-agents/orchestrator-protocol.md`.

## 1. Worker-Call Contract

- All worker calls route through the orchestrator/HQ. No peer
  worker-to-worker calls unless routed through HQ or the project owner.
- Every worker call carries a handoff brief (section 2). No worker starts
  from loose prose.
- Workers receive task-scoped context only - never the whole project memory.
- Workers never write durable memory directly; they return proposed memory
  updates (section 3), curated by PM Soul and the Memory Curator.

## 2. Handoff Brief Format

Every brief carries these fields (from the PM Soul handoff template):

- Task
- Specialist Needed / Why This Specialist
- Relevant Project Context
- Files To Inspect
- Constraints
- Scope Boundary
- Output Contract
- Acceptance Checks
- Return Schema
- Memory Update Needed After Completion

Briefs are compact and sufficient: enough to act, nothing irrelevant.

## 3. Return Contract

Every worker returns, in structure, not prose:

- Findings
- Output
- Risks
- Verification (what was actually checked, with evidence)
- Proposed Memory Update

The orchestrator's own final report returns `status`, `evidence`, `output`,
and `blockers`.

## 4. Failure Handling

- Runtime failures travel as typed markers (for example `RunnerFailure`),
  never as prose-only descriptions. Prose may accompany a marker; it never
  replaces one.
- Never rewrite, summarize away, or humanize a machine failure marker: the
  marker is what downstream logic keys on.
- A worker that failed is reported failed. Do not synthesize around a missing
  return as if it succeeded.

## 5. Synthesis Rules

- Synthesize only from actual worker returns; attribute each claim to the
  worker that produced it.
- A staffing selection or a prepared bundle is not proof that a worker ran;
  only an execution receipt is. Never present preparation as execution.
- Conflicting worker returns are surfaced as conflicts, not silently
  averaged.
- Quality judgment is delegated to the eval-qa declaration and the host judge
  engine (no self-grading).

## 6. Stop Conditions

Stop and report when any of these holds:

- All acceptance checks pass under the declared eval-qa checklist.
- A blocker requires a human decision (approval, permission widening,
  unresolved conflict) - escalate; do not guess.
- The same failure repeats without a changed plan - stop retrying; report
  the typed failure.

Report `completed` only with zero open blockers and judged acceptance.

## 7. Boundaries

- Enforcement of tool policy belongs to the host PreToolUse hook via the
  policy-gate declaration; the orchestrator never enforces or simulates it.
- The orchestrator plans, routes, synthesizes, and reports. It does not
  perform specialist work that a declared worker owns.

## Team Context (editable)

Everything above this line is canonical and byte-compared by the gate. This
section is the only editable region. Builders may note here the team's
orchestrator file path, its worker roster, and any team-specific routing
order - none of which may weaken a rule above.
