# Builder Interview and Research Gate

This is the shipped public runtime contract for `/hep-build`. Read it before
writing or materially repairing an agent package in single, team, or packager
mode. Skip it only for inspection or a trivial adapter-only repair. A user who
requests a minimal scaffold may opt out, but the final receipt must record the
opt-out and must not claim public or marketplace readiness.

The opt-out is machine-readable and fail-closed. Scaffold creates
`.agentlas/build-profile.json` with `profile: standard`. Change it to
`minimal-private` only after the user explicitly requests and confirms the
opt-out, using this complete receipt:

```json
{
  "schemaVersion": "agentlas-build-profile/1.0",
  "profile": "minimal-private",
  "minimalPrivateOptOut": {
    "requestedBy": "user",
    "confirmed": true,
    "reason": "the user's stated reason",
    "publicMarketplaceReady": false
  }
}
```

Missing, malformed, model-selected, or partially filled receipts remain on the
standard contract. `contract verify` may omit only the artifacts explicitly
tagged `optionalWhen: [minimal-private]`; all routing, identity, policy,
adapter, and runtime artifacts remain required. Its receipt must report
`build_profile: minimal-private` and `public_marketplace_ready: false`. A public
or marketplace build must require `public_marketplace_ready: true` and may not
promote or reinterpret a minimal-private receipt.

## Gate 1 — Interview before generation

Do not treat a rough opening prompt as a sufficient specification. Classify the
mode, ask 8–12 high-leverage questions, and continue with focused follow-ups
until these points are explicit:

- whether one agent owns the job or separate roles need independent context,
  permissions, memory, and outputs;
- team role boundaries, sequential versus parallel work, and who synthesizes;
- target user, recurring job, inputs, exact output artifacts, and examples of
  acceptable and unacceptable results;
- domain methods, vocabulary, safety/legal limits, freshness requirements, and
  source policy;
- required and forbidden tools, credentials, paid services, privacy limits,
  confirmation boundaries, and fallback behavior;
- failure, refusal, escalation, rollback, memory, and refresh behavior;
- runtime targets, public command, evaluation cases, rubric, and measurable
  success and stop conditions.

Use the briefing interview engine in `agentlas_cloud/interview/` when present:
start with goal/constraints/done signal, then edges and conflicts, then
contradictions and unverified assumptions. Follow discovered tension rather
than mechanically finishing a wave. The anti-scope, done-signal, and
stop-criterion lenses are mandatory. Preserve the user's own anti-scope words
as routing-card anti-triggers.

After each round, score goal, constraints, success, and context ambiguity. End
only after overall ambiguity is at most 0.2, every dimension clears its floor,
and both conditions hold for two rounds. Every interim risk must become the
next concrete question or a named deferral. Close with a coverage question,
restate the goal in one sentence, and confirm that sentence is sufficient.

If the user cannot answer, propose a conservative default, label it
`assumption`, and ask for confirmation. Never hide an unknown in generated
instructions. For an underspecified team, ask in plain language whether one
expert can own the work end-to-end or multiple experts must divide and combine
it; do not begin generation until the shape is known.

Write `docs/builder-interview.md` and `.agentlas/work-brief.json`
(`schemaVersion: work-brief/1.0`). The Work Brief must contain the one-line
goal, constraints, verifiable acceptance criteria, anti_scope, assumption
ledger with `user|code|memory|research|default` source tags, deferrals,
weighted evaluation principles, exit conditions, and final ambiguity score.

## Gate 2 — Research dossier

Before prompts or operating loops, research and convert sources into design
decisions. For public or marketplace-ready builds use:

- official or primary documentation for the domain and every selected tool;
- at least three comparable agents, repositories, systems, or benchmarks, or
  exact no-match searches plus the nearest useful analogs;
- at least two theory sources for substantial builds: one primary source on
  agent design and one domain-specific academic, standard, legal, textbook, or
  professional source when available;
- current connector/plugin documentation for every proposed integration.

Existing Agentlas packages are comparables, never a substitute for domain
research. Write `docs/research-sources.md` with title, URL or local path, source
type, `verified|memory_derived|inferred|stale_check_needed`, and the concrete
design implication. With no network, use available sources and mark current
facts stale-check-needed. Block public, legal, medical, financial, or
compliance-ready claims until current primary sources are verified.

## Gate 3 — Tool and plugin selection

Inventory the tools, plugins, MCP servers, and host capabilities actually
available. For each required capability compare the selected option with a
rejected alternative when one exists. Record account state, secrets needed,
permission scope, cost, fallback, and smoke test. Reject integrations whose
credentials, account entitlement, permission model, or behavior cannot be
verified. Write `docs/tool-selection.md`.

## Gate 4 — Domain-expert synthesis

Before final role prompts, combine interview evidence, comparables, theory, and
tool review in `docs/domain-expert-synthesis.md`. It must state expertise and
non-goals, accepted and rejected patterns, theory that changed the operating
loop, tool decisions, reasoning/action loop, memory and freshness rules, output
schema, handoffs, refusal/escalation, specialist heuristics, examples,
counterexamples, and derived evaluations. If key answers are missing, return
`needs_clarification`; do not generate a generic agent.

## Gate 5 — Prompt performance contract

Write `docs/prompt-performance-contract.md` for every generated role. Cover
identity and non-goals, operating loop, input/output contracts, tool/plugin
policy, memory/freshness policy, domain heuristics, good and bad examples,
evaluation cases and rubric, escalation/refusal, and trigger/anti-trigger
language. Teams apply this to the orchestrator and every worker. Packager mode
must preserve source behavior while adding missing evidence and contracts.

## Gate 6 — Capability evaluation plan

Write `.agentlas/capability-eval-plan.json`. Public or marketplace-ready builds
need at least 10 positive cases and 5 negative or anti-trigger cases, expected
artifacts and pass criteria, tool smoke checks, and stale-source and
missing-credential cases where relevant. The generated package verifier must
require all interview, research, tool-selection, synthesis, prompt-performance,
and evaluation artifacts unless the package is explicitly a minimal private
scaffold carrying the complete user-confirmed build-profile receipt above.

## Completion receipt

The final `/hep-build` response reports interview status and unresolved
assumptions, research sources, selected and rejected integrations, synthesis,
prompt-performance and evaluation-plan paths, exact verification commands and
results, `build_profile`, `public_marketplace_ready`, and blockers requiring
user input or external account state. A
scaffold, candidate selection, or prepared bundle is not completion evidence.
