# Super Ontology Candidate Contract

The Super Ontology contract is a public-safe seed for adaptive knowledge
governance. It is not a claim that one ontology can perfectly cover every
future situation.

## Files

Generated or packaged repos may include:

```text
.agentlas/
  super-ontology-contract.json
  super-ontology-replays.jsonl
  super-ontology-evidence.jsonl
```

`super-ontology-contract.json`

- Describes the allowed ontology pipeline: source intake, evidence packets,
  belief ledger, knowledge capsules, affordance binding, promotion readiness,
  replay drills, and rollback.
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

## Default State

Every exported Super Ontology contract starts as:

```text
state = candidate
runtimeGraphWriteEnabled = false
zeroErrorClaim = false
shadowRequired = true
canaryRequiredForMixedContext = true
rollbackRequired = true
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
6. Agentlas integration contract,
7. promotion readiness,
8. promotion replay drill,
9. architecture sync review.

## Hard Stops

Automatic promotion is blocked when:

- a candidate claims zero-error or universal completeness;
- a raw source would write directly into an ontology;
- a graph edge joins forbidden personal/company/public contexts;
- a downstream agent receives the whole graph instead of a task capsule;
- a tool call lacks argument provenance or user authority;
- AppBridge is treated as source of truth;
- rollback is missing;
- live shadow/canary evidence is missing for runtime behavior.

## Runtime Boundary

Public core defines the contract. Hosted Web may emit it in ZIP exports.
Desktop and terminal may seed it locally, but only as candidate metadata until
local policy approves a later phase.

This contract came from the Super Ontology Architect research. Treat it as
evaluation and governance infrastructure first. Do not claim production
omniscience or first-class runtime behavior from export metadata alone.
