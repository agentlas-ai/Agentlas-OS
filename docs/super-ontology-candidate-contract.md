# Super Ontology Candidate Contract

The Super Ontology contract is a public-safe seed for adaptive knowledge
governance. It is not a claim that one ontology can perfectly cover every
future situation.

## Files

Generated or packaged repos may include:

```text
.agentlas/
  super-ontology-contract.json
  super-ontology-task-coverage.json
  super-ontology-contextual-flow.json
  super-ontology-causal-impact.json
  super-ontology-assurance-case.json
  super-ontology-replays.jsonl
  super-ontology-evidence.jsonl
  super-ontology-memory-bridge.jsonl
```

`super-ontology-contract.json`

- Describes the allowed ontology pipeline: source intake, evidence packets,
  belief ledger, knowledge capsules, affordance binding, task coverage,
  promotion readiness, replay drills, and rollback.
- Must set `runtimeGraphWriteEnabled` to `false` on export.
- Must set `zeroErrorClaim` to `false`.
- Must stay candidate-only until local runtime policy, shadow/canary replay,
  rollback, and sync review approve a later phase.

`super-ontology-replays.jsonl`

- Append-only shadow, canary, rollback, and sync-review replay evidence.
- Empty on export.
- Runtime agents may append records later only after the local Memory Curator,
  PM Soul, or architecture sync owner approves the evidence boundary.

`super-ontology-evidence.jsonl`

- Append-only promotion evidence rows.
- Empty on export.
- Evidence must identify the proof key, target surface, status, and summary
  without storing private logs, local paths, credentials, or raw source content.

`super-ontology-memory-bridge.jsonl`

- Append-only Memory Curator bridge candidates.
- Empty on export; the public core repo may carry a public-safe seed row for
  schema visibility.
- Rows must keep `durable_write_enabled=false` until Memory Curator, Policy
  Gate, PM Soul, or architecture sync review accepts the ticket.
- Rows must not store raw prompts, secret values, private paths, full
  transcripts, or direct durable memory writes.

`super-ontology-task-coverage.json`

- Public-safe task-family coverage seed.
- Requires requests to be classified as read, draft, transform, analyze, plan,
  coordinate, execute, repair, personalize, regulated, multimodal, physical,
  software, finance/compliance, or education/coaching work before action.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks write, publish, execute, physical, and training tasks unless evidence
  mode, authority, review, and rollback are explicit.

`super-ontology-contextual-flow.json`

- Public-safe contextual-flow seed.
- Requires information flows to name source context, target context, sender,
  recipient, subject, attribute, transmission principle, purpose, authority,
  sensitivity, retention, controls, and audit references.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks same-user cross-context joins, tool responses treated as need-to-know,
  raw prompt or transcript memory writes, public output after private handoff,
  customer-data publication without consent, regulated training without delete
  path, and agent-internal traces in user output.

`super-ontology-causal-impact.json`

- Public-safe causal-impact seed.
- Requires state-changing work to name causal claim type, intervention target,
  expected outcomes, adverse outcomes, counterfactual checks, observability,
  reversibility, blast radius, blocked write surfaces, and rollback.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks correlation-as-causation, relation-as-permission, autonomous physical
  control, training without consent/delete path, and multi-agent writes without
  ordered handoff.

`super-ontology-assurance-case.json`

- Public-safe claim/evidence seed.
- Requires broad claims about coverage, memory safety, action safety,
  promotion readiness, red-team follow-up, or sync integrity to name required
  evidence, observed evidence, validators, residual risk, blocked shortcuts,
  and rollback.
- Keeps `runtimePromotionAllowed=false` on export.
- Treats literal perfection or zero-error language as a rejected overclaim, not
  a release state.

## Default State

Every exported Super Ontology contract starts as:

```text
state = candidate
runtimeGraphWriteEnabled = false
zeroErrorClaim = false
shadowRequired = true
canaryRequiredForMixedContext = true
rollbackRequired = true
taskCoverageRequired = true
contextualFlowRequired = true
causalImpactRequired = true
assuranceCaseRequired = true
memoryCuratorBridgeRequired = true
directDurableMemoryWritesBlocked = true
```

The package can be searched, reviewed, and replayed. It cannot write official
knowledge, mutate runtime memory, or authorize tools by itself.

## Required Pipeline

The public contract names these layers:

1. source intake,
2. evidence packet,
3. belief ledger,
4. knowledge capsule,
5. affordance action binding,
6. task coverage contract,
7. causal impact contract,
8. assurance case contract,
9. Agentlas integration contract,
10. Memory Curator bridge,
11. promotion readiness,
12. promotion replay drill,
13. architecture sync review.

## Hard Stops

Automatic promotion is blocked when:

- a candidate claims zero-error or universal completeness;
- a raw source would write directly into an ontology;
- a graph edge joins forbidden personal/company/public contexts;
- a downstream agent receives the whole graph instead of a task capsule;
- a tool call lacks argument provenance or user authority;
- a requested task family, affordance type, evidence mode, or rollback path is
  missing;
- a relation would be treated as causation, action permission, or intervention
  authority without counterfactual checks, blast radius, observability, and
  rollback;
- a broad claim lacks an assurance case, observed evidence, validator, residual
  risk, or rollback plan;
- AppBridge is treated as source of truth;
- a candidate bypasses the Memory Curator bridge and writes durable memory
  directly;
- a memory candidate stores raw prompt, private path, or secret-like material;
- rollback is missing;
- live shadow/canary evidence is missing for runtime behavior.

## Runtime Boundary

Public core defines the contract. Hosted Web may emit it in ZIP exports.
Desktop and terminal may seed it locally, but only as candidate metadata until
local policy approves a later phase.

This contract came from the Super Ontology Architect research. Treat it as
evaluation and governance infrastructure first. Do not claim production
omniscience or first-class runtime behavior from export metadata alone.
