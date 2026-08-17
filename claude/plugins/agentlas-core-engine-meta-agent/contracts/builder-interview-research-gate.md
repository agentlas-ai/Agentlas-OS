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

### Every question is derived, never templated

A fixed question list is not an interview. If the same batch would be sent for
"plan a resort's mid-term management strategy" and for "tidy my inbox", the
batch is measuring nothing and the answers cannot make the agent specialist.
Before writing a batch, restate what the request ALREADY settles, then ask only
about what it leaves open. A question whose answer is already in the request, or
whose wording would be identical for any other agent, is a defect: drop it and
ask the next real unknown instead.

Ground every question in the request's own subject matter. Use the domain's
vocabulary, name the actual artifacts and decisions the agent will handle, and
offer options that are concrete choices in THAT domain rather than abstract
categories. Where the domain has known method families, ask which one applies;
where it has known failure modes, ask which ones matter here.

### Score, then let the score choose the next questions

After each round, score four dimensions from 0.0 to 1.0 and combine them:

| dimension | weight | reaches 1.0 when |
|---|---|---|
| goal clarity | 0.35 | the outcome is stated as a concrete artifact or decision, not a topic |
| constraint clarity | 0.25 | scope, anti-scope, authority, and non-negotiables are explicit |
| success criteria | 0.25 | acceptance is checkable by someone other than the author |
| context clarity | 0.15 | existing material, audience, cadence, and environment are known |

`ambiguity = 1 - Σ(clarity_i × weight_i)`. Score deterministically (a fixed low
temperature) so the same answers reproduce the same number; report the vector,
never a bare total. **The lowest-scoring dimension decides what the next batch
asks about** — questions follow the gap, not a checklist order, and a dimension
already at its floor gets no further questions.

Continue until overall ambiguity is at most 0.2, every dimension clears its
floor, and both hold for two consecutive rounds. Every interim risk must become
the next concrete question or a named deferral. Close with one coverage
question, restate the goal in one sentence, and confirm that sentence is
sufficient. Record the final vector and total in the Work Brief; a build that
cannot show its dimension scores did not run this gate.

Stop early only on an explicit user override, and record the override and the
ambiguity it stopped at.

If the user cannot answer, propose a conservative default, label it
`assumption`, and ask for confirmation. Never hide an unknown in generated
instructions. For an underspecified team, ask in plain language whether one
expert can own the work end-to-end or multiple experts must divide and combine
it; do not begin generation until the shape is known.

### The interview record is written by the host, not by you

`docs/builder-interview.md` and the work brief's `source: user` tags are YOUR
claim that an interview happened. They are not evidence of it. Measured
2026-08-17: three packages carried `source: "user"` assumptions and a fully
written interview document, and their owner had never been asked a single
question — the model that skipped the interview also wrote the record saying it
had not.

So the host writes `.agentlas/interview-receipt.json` from the exchange it
actually transported:

```json
{
  "schemaVersion": "agentlas.interview-receipt/1.0",
  "observedBy": "<host id>",
  "batchesAsked": 2,
  "answersReceived": 2,
  "recordedAt": "<iso8601>"
}
```

Never write, edit, or fabricate this file — a host that sees you author it must
treat the build as unverified. A batch counts as asked only when the host parsed
real questions out of your turn, and as answered only when a human turn followed
it. `answersReceived: 0` means no interview happened, whatever the documents say,
and a standard-profile build in that state is `blocked`, not `completed`. A
`minimal-private` build carrying the complete user-confirmed opt-out receipt is
the only exception.

A host with no question transport cannot satisfy this gate by asking in prose:
add the transport, or declare the build minimal-private and say so in the receipt.

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

### A plugin without an MCP server is a skill, not a failure

Some Hub plugins ship skills instead of a server. Their manifest says so:
`mcp: []` with `architecture.packageShape.mcpReference: "none"` and
`skills: "bundled"`. There is nothing to connect, so connecting is not the test.

Bundle them as package skills and record them in `docs/tool-selection.md` with the
same permission/fallback notes as any other capability. Never report them as a
failed or unavailable connection, never invent an MCP server for them, and never
drop the capability just because no server appeared — measured 2026-08-17:
Documents, Presentations and Spreadsheets were approved by the user, had no server
by design, and the build reported "Failed · 3", losing three approved capabilities
and telling the user the product was broken.

Read `agents[].intent` and `capabilities` from the manifest for what the skill
actually does; do not restate the marketing tagline as behavior.

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
