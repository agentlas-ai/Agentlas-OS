---
name: skill-lifecycle-promotion
description: "Use when adding or auditing Agentlas skill lifecycle metadata, skill-registry.json, trial evidence, Curator promotion decisions, or first-class skill promotion gates."
---

# Skill Lifecycle Promotion

Use this skill when a generated or packaged Agentlas repo needs governed skill
promotion metadata.

## Procedure

1. Add `.agentlas/skill-registry.json` as an export-only candidate registry.
2. Add empty `.agentlas/skill-trials.jsonl` and
   `.agentlas/curator-decisions.jsonl`.
3. Keep every skill at `tier: candidate` on export.
4. Keep `runtimeFirstClassRecallEnabled: false` unless a local Curator later
   approves promotion.
5. Add success predicates and situation tags for every skill.
6. Separate `## Memory Events` from `## Skill Trial Events`.
7. Treat LLM rubric review as weak evidence only.
8. Block promotion when authority separation, sealed holdouts, replayability, or
   rollback evidence is missing.
9. Include false-accept, blind-spot, and drift terms in any durable-error budget.

## Output

Return:

- registry files added or checked;
- promotion tier status;
- evidence gaps;
- rollback/quarantine status;
- residual risks.
