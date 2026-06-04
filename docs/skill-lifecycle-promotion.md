# Skill Lifecycle Promotion

Agentlas packages may include skill lifecycle metadata, but runtime promotion is
off by default. The contract exists so Curators can review evidence before a
skill becomes a fast-path behavior.

## Files

Generated or packaged repos may include:

```text
.agentlas/
  skill-registry.json
  skill-trials.jsonl
  curator-decisions.jsonl
```

`skill-registry.json`

- Lists skills/playbooks, situation tags, candidate tier, niches, capacity,
  predicates, rollback requirements, and error-budget terms.
- Must set `runtimeFirstClassRecallEnabled` to `false` on export.
- Must not overwrite a workspace's existing first-class registry.

`skill-trials.jsonl`

- Append-only execution, replay, holdout, shadow, or canary evidence.
- Empty on export.
- Each future record must identify skill version, control version, predicate
  version, producer authority, validator authority, replayability, and holdout
  contamination status.

`curator-decisions.jsonl`

- Append-only Curator lifecycle decisions.
- Empty on export.
- Curator decisions can reject, approve next phase, approve first-class,
  rollback, or require human review.

## Default State

Every exported skill starts as:

```text
tier = candidate
runtimeFirstClassRecallEnabled = false
curatorQuarantineRequired = true
```

The package can be searched and audited. It cannot make itself first-class.

## Hard Stops

Automatic promotion is blocked when:

- the patch changes permission, credential, payment, legal, medical, financial,
  public-posting, destructive-file, or irreversible-side-effect behavior;
- the patch author and validator are the same authority;
- the holdout set was visible to the patch author;
- rollback cannot restore the prior version;
- blind-spot or drift error is unknown for a risky workflow;
- the effective durable-error budget is exhausted.

## Evidence Rule

LLM-written explanations are weak evidence. They can route review but cannot
approve first-class promotion by themselves.

Promotion evidence must prefer:

- executable assertions;
- tool checks;
- sealed holdout replay;
- patched-vs-control shadow comparison;
- low-risk canary with rollback;
- human/owner approval for risk or criticality.

## Skill File Contract

`SKILL.md` may contain two separate event blocks:

- `## Memory Events`: durable memory candidates for Memory Curator.
- `## Skill Trial Events`: execution evidence for skill lifecycle review.

Do not mix them. Memory admission and skill promotion have different trust
boundaries.

## Runtime Boundary

Public core defines the contract. Hosted Web may emit it in ZIP exports.
Desktop and terminal may activate or merge it locally, but only as candidate
metadata until the local Curator and workspace policy approve a later phase.
