# Hephaestus Stormbreaker Robustness Protocol

Hephaestus Stormbreaker is the public name for the Hephaestus Robustness
Protocol. It is a global operating protocol for coding agents. It is not a
model, standalone agent, skill, leaked prompt, or Hephaestus Network routing
card.

The protocol sits above local agents, Hub bundles, skills, and tools. Its job
is to make long-running work harder to abandon, harder to falsely declare done,
and easier to recover after context loss or a failed verification pass.

The strongest current claim is operational robustness, not raw benchmark
correctness. Local scorecards show Stormbreaker leading native Codex and a
baseline Hephaestus Network arm on process-aware robustness metrics.

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
- Reflexion (<https://arxiv.org/abs/2303.11366>): failed checks become verbal
  failure memory for later attempts.
- Self-Refine (<https://arxiv.org/abs/2303.17651>): feedback and refinement
  form a bounded test-time improvement loop without model retraining.
- SWE-agent / Agent-Computer Interface
  (<https://arxiv.org/abs/2405.15793>): agent-computer interface design
  matters; agents need stable navigation, edit, diff, and test surfaces.
- Localize-then-repair pipelines (<https://arxiv.org/abs/2407.01489>): a fixed
  localize -> repair -> validate ordering, with reproduction and regression
  tests as the final verification phase rather than self-report.
- AST-grounded context retrieval (<https://arxiv.org/abs/2404.05427>): an
  iterative structured code-search loop grounds each edit in a real code
  observation before any patch.
- Observation-grounded action loops (<https://arxiv.org/abs/2210.03629>): every
  plan revision is tied to a fresh external observation, which reduces
  hallucinated or assumed steps.
- Plan-then-solve decomposition (<https://arxiv.org/abs/2305.04091>): enumerate
  every requirement up front, then execute, to defend against silently skipped
  steps.
- Repo-scale change-impact planning (<https://arxiv.org/abs/2309.12499>):
  analyze the dependent sites a change forces so multi-file edits do not skip
  required locations.
- Resume-journal harnesses: a durable, plan-anchored progress state plus history
  rehydration lets a fresh context continue a long task without restarting; and
  health is proven by executing a probe (pass / broken / missing), not by a
  presence check.

These are used as engineering precedents, not as private system prompts or
vendor behavior clones. Patterns are borrowed as structure and capability only,
never as another project's name, branding, or authorship.

## Protocol State

Every substantial task should move through these states:

1. `scope_lock`
   - Restate the exact task, owner repo, mutation boundary, and non-goals.
   - Clarify before mutation when a missing answer would change files, costs,
     security posture, or public release state.

2. `issue_contract`
   - Extract behavior that must change, behavior that must not change, files
     likely in scope, public checks, and issue-implied edge classes.
   - Treat this as the bridge between a natural-language request and verifier
     evidence.

3. `failure_memory`
   - Check the task against public-safe failure classes before patching:
     Unicode normalization, length limits, migration/defaulting, retry timing,
     atomic writes, parser edge cases, time/date APIs, package metadata gaps,
     and unsupported README claims.
   - This is not private-oracle leakage; it is a reusable checklist built from
     observed failure modes.

4. `research_probe`
   - Read-only research before planning. No mutations during this state.
   - Two evidence streams: (i) codebase localization — narrow from file to
     class/function to the exact edit-site, grounded in grep/AST observations,
     not assumption; (ii) external research — fetch docs, specs, or issue
     context when the task needs facts the repo does not contain.
   - Output is a research artifact: every intended plan item must cite at least
     one concrete observation (a file:line, a search hit, a fetched doc). No
     plan step without an observation.
   - Tier gate: lightweight for `low`/`medium`; mandatory external research for
     `high`.

5. `verifier_first_plan`
   - Produce a short staged plan for risky or multi-file work, consuming the
     `research_probe` artifact: each plan item is anchored to a localized
     edit-site and cites an observation.
   - Enumerate every requirement from `issue_contract` up front so the plan
     provably covers the whole task; for multi-file work, list the dependent
     sites a change forces (change-impact) so none is silently skipped.
   - Define the verification command, expected artifact, and final exit gate
     before implementation begins.

6. `parallel_session_fabric`
   - When a Hephaestus Network decision returns `action: "pipeline"`, attach a
     Stormbreaker execution fabric: required work packets, dependency groups,
     model/session hints, handoff paths, and the final-gate packet list.
   - The host runtime may advertise active sessions such as Codex, Claude, GLM,
     DeepSeek, Gemini, or local models. Stormbreaker can then spread independent
     packets across those sessions, while keeping mutating work behind host
     approvals and privacy rules.
   - Parallelism is allowed only across packets whose dependencies are already
     satisfied. A dependent packet cannot start until its `parallel_group` join
     policy is satisfied.
   - The fabric is a scheduling contract, not a remote execution bypass:
     external sessions receive stage contracts, artifact paths, and redacted
     receipt metadata only; raw local memory and private prompts stay local
     unless the host runtime has an explicit export approval.

7. `persistence_directive`
   - Proceed continuously through the remaining plan items until every
     contracted requirement is satisfied or a declared Bounded Retry cap is hit.
   - Do not yield at the first sign of uncertainty — research or deduce the most
     reasonable in-scope next step and continue.
   - Do not interrupt the active task for side-quests (version checks, unrelated
     cleanup, optional polish). Record them as follow-ups in the
     `outcome_ledger`; never raise the same reminder twice.
   - The run may end only at `final_gate` or a reported Bounded Retry cap —
     never merely because output grew long or a context window is near its
     limit.

8. `evidence_loop`
   - Execute one bounded change batch at a time.
   - After each failure, record the failing evidence, change one hypothesis, and
     retry within a declared cap.
   - Tests are evidence, not the whole definition of done.

9. `review_gate`
   - Check scope drift, destructive changes, unrelated file edits, secret
     exposure, and unsupported claims.
   - Run an adversarial plan-vs-implementation check (ideally fresh-context,
     seeing only the diff and the plan/criteria): is every contracted
     requirement implemented, every listed edge class tested, nothing
     out-of-scope changed?
   - For high-risk work, run a reviewer path or independent verification script.

10. `outcome_ledger`
   - Maintain a live, plan-anchored resume journal, updated after each
     `evidence_loop` batch — not only at the end. Each requirement / plan item
     carries `status: pending | in_progress | passing | blocked` plus its
     verifying evidence (command + artifact). Task "done" = every item
     `passing`.
   - On nearing a context limit, compact into the journal preserving decisions,
     open items, and the next non-`passing` item, then continue. A fresh context
     rehydrates by reading the journal plus recent history and resuming the
     highest-priority non-`passing` item. State lives outside the context
     window — this is the anti-cutoff mechanism.
   - Record failed attempts, unresolved risks, and follow-up gates so
     continuation after context loss is possible.

11. `final_gate`
   - Do not finish unless required checks passed, blockers are empty or clearly
     reported, artifacts exist, and the final answer separates verified facts
     from remaining risk.
   - An artifact existing is not proof it works: execute the verifier and
     classify pass / broken / missing — do not assert from presence. Prefer
     reproduction plus regression checks passing over self-report; self-critique
     is the fallback gate only when no executable verifier exists.
   - For multi-file work, confirm the plan's change-impact list was fully
     addressed — no required site silently skipped.
   - For pipeline work, success is blocked until every
     `execution_fabric.required_packet_ids` entry is `passing`. A blocked packet
     may produce a blocked final report, but never a success claim.

## Risk Tiers

| Tier | Examples | Required Gate |
| --- | --- | --- |
| `low` | single doc edits, read-only analysis | scope lock + final gate |
| `medium` | scripts, tests, package docs, local-only automation | plan lock + evidence loop |
| `high` | release, auth, private data, publishing, destructive changes | explicit approval + review gate |

## Bounded Retry

Robustness is not infinite looping. A failed verification may retry only when
there is new evidence and a narrower hypothesis. The `persistence_directive`
pushes the run forward through the plan toward completion, but it never
overrides these caps: persistence means not abandoning the task mid-plan, not
retrying a failed verification beyond its cap.

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
3. Hephaestus Network plus Stormbreaker gates.
