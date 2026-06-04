---
name: mode-classification
description: "Use before routing a /meta-agent request to choose single-agent-creator, team-builder, or agentlas-packager from the user's wording and available files."
---

# Mode Classification

Pick one Agentlas meta-agent mode before generating or repairing files.

## Procedure

1. Inspect the user request and any provided path, repo, ZIP, prompt, or agent
   files.
2. If existing material is being converted, repaired, cleaned, imported, or
   released, choose `agentlas-packager`.
3. Else if the request needs a roster, HQ, departments, debate, policy, eval,
   QA, handoffs, or parallel ownership, choose `team-builder`.
4. Else choose `single-agent-creator`.
5. If the choice changes the output and the request is ambiguous, run the
   clarify question loop instead of guessing.

## Return

Return the selected mode and one short reason. Then route to the matching
builder.

## Reference

See `docs/mode-classifier.md`.
