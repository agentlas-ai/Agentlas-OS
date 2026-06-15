# Hephaestus Robustness Protocol

Hephaestus Robustness Protocol is a global operating protocol for coding
agents. It is not a model, standalone agent, skill, leaked prompt, or
Hephaestus Network routing card.

The protocol sits above local agents, Hub bundles, skills, and tools. Its job
is to make long-running work harder to abandon, harder to falsely declare done,
and easier to recover after context loss or a failed verification pass.

## Research Sources

The protocol distills recurring patterns from public agent harnesses and local
research notes:

- Superpowers: approval before implementation, TDD, subagent execution, review,
  and verification-before-completion.
- GSD Core: discuss, plan, execute, verify, ship phase loops with fresh-context
  executors and durable state files.
- LazyCodex / oh-my-claudecode / Gajae-Code: interview, consensus planning,
  goal ledgers, replay artifacts, bounded loops, and completion gates.
- FableCodex / Fable-style operating protocol repos: requirements ledgers,
  evidence checkpoints, final verification gates, and model-aware delegation.
- NightWatch-style recorders: logs are claims; independent replay or artifact
  checks are stronger proof.

These are used as engineering precedents, not as private system prompts or
vendor behavior clones.

## Protocol State

Every substantial task should move through these states:

1. `scope_lock`
   - Restate the exact task, owner repo, mutation boundary, and non-goals.
   - Clarify before mutation when a missing answer would change files, costs,
     security posture, or public release state.

2. `plan_lock`
   - Produce a short staged plan for risky or multi-file work.
   - Define the verification command, expected artifact, and final exit gate
     before implementation begins.

3. `evidence_loop`
   - Execute one bounded change batch at a time.
   - After each failure, record the failing evidence, change one hypothesis, and
     retry within a declared cap.
   - Tests are evidence, not the whole definition of done.

4. `review_gate`
   - Check scope drift, destructive changes, unrelated file edits, secret
     exposure, and unsupported claims.
   - For high-risk work, run a reviewer path or independent verification script.

5. `final_gate`
   - Do not finish unless required checks passed, blockers are empty or clearly
     reported, artifacts exist, and the final answer separates verified facts
     from remaining risk.

## Risk Tiers

| Tier | Examples | Required Gate |
| --- | --- | --- |
| `low` | single doc edits, read-only analysis | scope lock + final gate |
| `medium` | scripts, tests, package docs, local-only automation | plan lock + evidence loop |
| `high` | release, auth, private data, publishing, destructive changes | explicit approval + review gate |

## Bounded Retry

Robustness is not infinite looping. A failed verification may retry only when
there is new evidence and a narrower hypothesis.

Default caps:

- Same verification failure: 2 retries.
- Whole task loop: 3 rounds.
- External-state blockers: stop after evidence shows the same blocker twice.

When a cap is hit, report the blocker and the last evidence instead of
inventing success.

## Completion Contract

A final answer may claim completion only when all are true:

- Task scope is satisfied.
- Required files/artifacts exist.
- Verification commands ran or the reason they could not run is explicit.
- Failed checks are not hidden behind wording like "should work".
- Public or user-facing outputs passed the relevant safety gate.
- Follow-up work is framed as optional improvement, not required completion.

## Relationship To Hephaestus Network

Hephaestus Network chooses agents and Hub bundles. The Robustness Protocol
governs execution after a route is selected, and also governs native Codex runs
when no agent or skill is used.

This makes it suitable for three-way evaluation:

1. native runtime with no added protocol;
2. Hephaestus Network routing and agent calls;
3. Hephaestus Network plus Robustness Protocol gates.
