# Evals

This is the agent-level eval surface named in the Agentlas package layout.

The actual eval data lives at `.agentlas/capability-eval-plan.json` and
`.agentlas/routing-benchmarks.jsonl`, not in this folder. That split is
deliberate, not an oversight: moving those two files under `evals/` was tried
once, no generation path ever wrote them to the new location, and every
package silently failed the required-artifact check on the path alone while
the file sat unmoved at `.agentlas/`. Duplicating the data here instead of
pointing to it would reopen the same drift.

- `.agentlas/capability-eval-plan.json` — positive/negative prompts with pass
  criteria.
- `.agentlas/routing-benchmarks.jsonl` — routing benchmark cases (route +
  reject, ko + en), what the routing-card lint reads.

Edit those two files. This README is the only thing that belongs in
`evals/`.
