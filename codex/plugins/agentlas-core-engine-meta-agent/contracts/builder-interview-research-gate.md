<!-- prompt-module: {"id":"os.builder.interview-research-contract","revision":2,"stability":"versioned-content","changeTriggers":["release"],"channel":"tool-result"} -->

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

## Gate 1 — Assess existing context before generation

Do not treat a rough opening prompt as a sufficient specification. First use the
actual request, existing conversation, authorized files, existing agents,
available tool results and research to classify the mode and assess these points.
If they already settle the material decisions, ask zero additional questions.
Otherwise ask only questions about real material gaps; 8–12 questions are
appropriate only when that many distinct material gaps actually remain. Label
conservative assumptions, and do not imply they are confirmed by the user:

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

### Assess coverage; score only when actually measured

When the interview engine actually measures an ambiguity vector, its four
dimensions and weights are:

| dimension | weight | reaches 1.0 when |
|---|---|---|
| goal clarity | 0.35 | the outcome is stated as a concrete artifact or decision, not a topic |
| constraint clarity | 0.25 | scope, anti-scope, authority, and non-negotiables are explicit |
| success criteria | 0.25 | acceptance is checkable by someone other than the author |
| context clarity | 0.15 | existing material, audience, cadence, and environment are known |

`ambiguity = 1 - Σ(clarity_i × weight_i)`. For an actual measured vector, report
the vector and total, not a fabricated score. Use a real unresolved gap to
choose any follow-up; do not create rounds or a coverage question merely to
meet a count. A measured score above 0.2 is not ready. Record a genuine override
and the measured ambiguity when one exists; do not invent either.

For a context-based Work Brief set `metadata.inputBasis` to `context` and put
the assessment under `metadata.contextAssessment`, matching
`schemas/build-context-assessment.schema.json`. Goal, constraints, success and
context must each have one coverage entry; link supported entries to real source
IDs, mark assumptions, and list only material questions in `materialGaps`.
Validate it with `contract context-assess --input <assessment.json>`: proceed
only on a valid `sufficient` claim; `needs_input` asks its listed questions,
and `unverified`, invalid output or cancellation is not sufficient. The host
must match IDs and source kinds against the inputs actually supplied. This
validator checks shape, not meaning or access: report `caller_claim`, source
verification `unverified`, and host witness `not_checked` when they have not
been independently observed. Do not invent a score, interview, user answer,
receipt, model execution, or approval. This context route is standard, not a
minimal-private opt-out; independent research, quality, permission, registration
and publication gates still apply.

If the user cannot answer, propose a conservative default and label it
`assumption`; ask for confirmation when the unresolved decision materially
requires it. Never hide an unknown in generated
instructions. For an underspecified team, ask in plain language whether one
expert can own the work end-to-end or multiple experts must divide and combine
it; do not begin generation until the shape is known.

### Question transport is a channel, not a UI

The ask fence (`<<agentlas-ask>>`) is a wire format, and the Agentlas Desktop
bottom sheet is only one renderer of it. Before the first batch, detect the
surface and pick the strongest channel available, in this order:

1. **Agentlas Desktop renderer** — emit the fence; the desktop renders its
   question sheet (existing behavior).
2. **A synchronous question tool** — `ask_user` when Agentlas provides it, or the
   host's own equivalent (Claude Code's `AskUserQuestion`). These block until the
   person answers, so the interview can continue in the same turn. Batch the
   questions per call with concrete options; free-text answers must stay possible.
   If such a tool reports that nobody can answer, treat that as a real signal —
   do not substitute a default and carry on as if the person had chosen.
3. **Plain conversational host** (a CLI or chat surface with no structured
   tool) — render the batch as a numbered markdown list with lettered options
   and wait for the reply. Never leave a raw `<<agentlas-ask>>` fence in a
   surface that cannot render it.
4. **Unattended run** (automation, graph, headless) — do not ask. Stop with a
   `NEEDS-INPUT:` line describing exactly what is missing, per the runner
   contract.

Degrading a channel is acceptable; hiding the degradation is not. When the
host records the interview receipt it should also record which channel carried
the exchange, so a plugin-surface interview is not mistaken for a desktop one.

### The interview record is written by the host, not by you

`docs/builder-interview.md` and the work brief's `source: user` tags are YOUR
claim that an interview happened. They are not independent evidence of it.

When an interview actually occurs, only the host may write
`.agentlas/interview-receipt.json` from the exchange it actually transported:

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
it. `answersReceived: 0` does not establish an answered interview. Missing host
witness must remain explicitly unverified, but does not itself require repeating
questions whose answers are already available. If a material question remains
and no actual question transport can deliver it, return needs-input and stop.
Never synthesize a receipt or minimal-private opt-out to continue.

Write `docs/builder-interview.md` and `.agentlas/work-brief.json`
(`schemaVersion: work-brief/1.0`). The Work Brief must contain the one-line
goal, constraints, verifiable acceptance criteria, anti_scope, assumption
ledger with `user|code|memory|research|default` source tags, deferrals,
weighted evaluation principles and exit conditions. Include the final ambiguity
score only when actually measured, or the context assessment described above.
The required interview document records source provenance and assumptions; it
must not claim that unasked questions were asked or answered.

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
drop the capability just because no server appeared.

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

### Length discipline for the generated worker's instructions

- Start with the smallest instruction that fully defines the behavior: identity
  and non-goals, judgment the data cannot carry, workflow, limits, output.
  Minimal is not short; do not cut context the agent needs.
- Move everything checkable (numbers, tables, allow-lists, schemas, decision
  tables) into package files the agent reads (`knowledge/*.json`,
  `contracts/*.json`) and cite them by id. Do not paste them into the
  instruction.
- Add a line to the instruction only for a failure you observed, and record that
  failure as a case in `.agentlas/capability-eval-plan.json`.
- Keep approval gates, refusals and destructive-action limits in the
  instruction.
- Remove or shorten an existing line only after a real-model comparison of the
  same tasks before and after.

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
