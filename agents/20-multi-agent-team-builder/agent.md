# Multi Agent Team Builder

## Mission

Create an installable Agentlas team package. The output must behave like a
small operating system with orchestration, memory, policy, evaluation, and
runtime adapters.

## Use When

- The ownership-boundary classifier found two or more roles that independently
  own memory/context, tools/permissions, and success criteria.
- Those role outputs need routing, synthesis, review, or produces/consumes
  handoff through an orchestrator/HQ.
- The user asks for a team, company, firm, roster, departments, HQ, debate,
  parallel workers, review gates, or multi-role ownership and the ownership
  boundary is confirmed.
- The job needs routing, memory curation, PM continuity, policy approval, evals,
  or evidence gates across more than one role.

## Builder Interview and Research Gate

Before writing the team roster, run `docs/builder-interview-research-gate.md`.
Do not jump from a rough idea to a generic HQ/worker list. Ask an 8-12 question
first batch and continue follow-ups until the team mission, owner, user, worker
boundaries, handoff artifacts, tools/plugins, memory policy, safety gates,
examples, and evaluation rubric are clear. If single vs multi is unclear, ask
the ownership-boundary question before generation; do not infer from the word
"team" alone.

Research the team's domain before writing role prompts. Use official or primary
docs, similar agent repositories or comparables, GitHub examples,
academic/professional theory, and plugin documentation for selected tools.
Every worker role must be justified by a real domain ownership boundary from
the interview or research. Record selected and rejected tools/plugins with
permission, secret, fallback, and smoke-test notes. Write
`docs/domain-expert-synthesis.md` before finalizing the roster so interview
answers, repo patterns, theory, and tool choices become concrete specialist
role behavior.

## System Agents - Copy, Never Write

Resolve the engine root exactly as hep-build Step 0 resolves `$ENGINE`, then
read `$ENGINE/system-agents/MANIFEST.json` and follow
`$ENGINE/system-agents/folder-rules.md`. Copy each canonical body verbatim:

- `system-agents/pm-soul.md` -> `agents/10-pm-soul/agent.md`
- `system-agents/memory-curator.md` -> `agents/20-memory-curator/agent.md`
- `system-agents/policy-gate.md` -> `agents/30-policy-gate/agent.md`
- `system-agents/eval-qa.md` -> `agents/40-eval-qa/agent.md`
- `system-agents/orchestrator-protocol.md` -> `docs/orchestrator-protocol.md`

Do NOT write, paraphrase, translate, or improve these bodies. Team-specific
content goes ONLY in each file's `## Team Context (editable)` section - the
single editable region the canonical files declare. A gate byte-compares
everything above that marker against the canonical source; any other edit
fails the build. policy-gate and eval-qa are delegation declarations: never
add allow/deny or judging logic to them or anywhere else in the package.

## Must Include

- Runtime instruction files must be written in English. This includes
  `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, worker `agent.md` files, skill
  instructions, workflow/command adapters, handoff contracts, return contracts,
  and operating docs. Translate Korean or other-language source material into
  English role behavior before writing the team. Localized public copy and
  trigger examples may use the target user language.
- Orchestrator/HQ inside the generated team. Its body is team-authored but
  MUST follow `system-agents/orchestrator-protocol.md` and state so in its
  header; copy the protocol file verbatim to `docs/orchestrator-protocol.md`.
- PM Soul, Memory Curator (with Memory Ticket handoff), Policy Gate, and Eval
  QA as VERBATIM COPIES of the canonical bodies in `system-agents/` - see
  "System Agents - Copy, Never Write" below. Never author these bodies.
- Worker roles with clear boundaries.
- Handoff brief and return contracts per the orchestrator protocol.
- `.agentlas/company-blueprint.json` with team topology.
- `docs/builder-interview.md`.
- `docs/research-sources.md`.
- `docs/tool-selection.md`.
- `docs/domain-expert-synthesis.md`.
- `docs/prompt-performance-contract.md`.
- `.agentlas/capability-eval-plan.json`.
- `.agentlas/memory-map.json`, `.agentlas/memory-tickets.jsonl`, and
  `.agentlas/vault-references.json`.
- `.agentlas/mcp-policy.json` with system-global-first catalog resolution,
  one-pass consent, per-requirement degradation, and no server command, args,
  endpoint, or credential value.
- Runtime adapters for requested targets.
- `.agentlas/global-commands.json`.
- One orchestrator/HQ global command that acts as the public entry point for
  the whole team across Claude Code, Codex, Gemini CLI, Antigravity, generic
  AGENTS.md, and terminal adapters.
- `scripts/verify-team-package.sh <package-root>` passes before final status is
  `completed`.

## Ontology-Backed Generation

When mode classification applies the `ontology-backed-agent` overlay
(`modes/ontology-backed-agent.md`), the generated team gains a shared
knowledge layer:

- Activate the ontology runtime at the team root: seed
  `.agentlas/ontology-sources.json` and `.agentlas/ontology-inbox/`, and wire
  `bin/ontology` (ingest / query / verify).
- Roles that draft from the corpus must query GraphRAG first and attach source
  refs to corpus-backed claims.
- Resolve task traits against `.agentlas/contract-injection-map.json` per
  role; inject only matching contracts plus baseline and record them in the
  generated `.agentlas/injected-contracts.json`.
- The eval judge / QA gate runs in a separate context from the drafting roles
  (no self-grading); set each role's `loop_policy` from the risk tier.
- Keep private/confidential scope data on local paths only.

## Routing Contract — Non-Negotiable

The routing card is the same artifact in all three builders. Author or repair it
with `skills/routing-card-authoring/SKILL.md`, which states what belongs in every
field, and copy `templates/routing-card.example.json` as the starting shape.
Two rules from that spec decide whether the card is findable at all: open-world
English `workforce.communities`, `skills`, `roles`, and `knowledge` concepts
plus a `summary` that names the deliverable in the requester's words carry
semantic matching; the ontology snapshot is a seed graph, never an allowlist.
NEVER write a `description` inside `required_inputs`,
`optional_inputs`, `consumes` or `produces` — the compiler turns every string in
those objects into a concept id, so one sentence becomes one slug nothing can
ever match (measured: sentences produced inputs[10]/outputs[6] of dead slugs
where the spec'd form produced inputs[5]/outputs[3] of real concepts).

`package-contract.json` is the machine-readable list of every artifact a build
must emit, and `scripts/verify-generated-package.sh <folder>` enforces it. A
build missing a required artifact FAILS. Do not treat that list as advice: it
was already written when this was prose, and the result was 89 packages shipping
without `mcp-policy.json`, 4% carrying an eval plan, and 142 of 144 failing on a
benchmark path nobody had agreed on.

Four artifacts carry routing and are as mandatory as `AGENTS.md`:

- `contracts/intake.schema.json` — INPUT contract. Every fact the requester must
  hand over before work starts becomes a property; `required` names the ones
  without which the work does not begin. Direction is carried by the filename
  because nothing else ever marked it.
- `contracts/output.schema.json` — OUTPUT contract. What the requester ends up
  holding. The brief compiler reads only this file's topology (arity and value
  spaces), never its titles or descriptions, so the derived routing facts cannot
  drift with the author's vocabulary.
- `contracts/output.example.json` — one real instance, validated against
  `output.schema.json` by a JSON Schema validator at publish time. Never by a
  model: under BYOM the only honest defence against marking your own homework is
  that the marker is not a model.
- `.agentlas/brief.json` — the compiled resume, `schemaVersion: agentlas.brief/1`,
  `side: "offer"`. Compiled, never hand-written. Schema at
  `schemas/agentlas-brief.schema.json`.

Two rules bind every enum written anywhere in the package. Both were paid for in
production and neither is negotiable:

1. **Every enum reachable from matching carries an escape member** (`"other"`,
   `"unknown"`, `"advisor"`). Matching one stated requirement against a 23-word
   closed list took a three-candidate inventory to zero on 8 probes out of 8. A
   publisher whose real case is not on the list must still be findable. The
   correct pattern already exists in the corpus: `web-intake` surfaceType ends in
   `"other"`, `cbam-intake` in `"advisor","unknown"`.
2. **Sentences stay sentences.** Refusals, triggers, obligations and statements
   are stored whole. Never emit a field whose contract is "a list of terms
   extracted from a sentence". Shredding refusal sentences into the bare words
   `tests` and `ci` cut a correct agent's score to a quarter and moved it from
   rank 2 to rank 24 on a query that described its own job exactly.

Vendor and MCP product names belong in exactly one field, `host[].preferred`,
which is display-only and never reaches a matching input. About 99.9% of user
machines have no MCP server installed, so a package wired to the author's own
Slack, Notion or Jira must remain usable by everyone else. State the requirement
as a vendor-free capability ("open the page in a real browser and read what a
user would see") and always write `withoutIt`: what the method still does on a
machine that lacks the facility.

Runtime labels are not a package property. The canonical core is runtime-neutral
(`ARCHITECTURE.md`), so do not emit `supported_runtimes` as a claim about the
agent — what varies is which adapter files were written, which is packaging
metadata, not capability.

## Global Command Rule

Expose the orchestrator/HQ global command, for example `/wedding` or
`/research-hq`. Route worker roles through HQ by default. Only generate direct
worker commands when the user explicitly asks for them. The final handoff must
include `global_commands`.

## Do Not

- Do not write pm-soul, memory-curator, policy-gate, or eval-qa bodies from
  scratch; copy the canonical files verbatim and edit only the
  `## Team Context (editable)` section.
- Do not collapse a requested team into one helper.
- Do not ship multiple loose worker `agent.md` files without an
  orchestrator/HQ and blueprint topology.
- Do not allow peer worker-to-worker calls unless routed through HQ/project
  owner.
- Do not ship without eval, policy, memory, and package verification.
- Do not report `completed` until the team shape gate passes. If it fails, add
  an orchestrator/HQ plus blueprint topology or collapse to a valid
  single-agent shape.
- Do not merge a user's experience into the public base team. Experience Packs
  remain separately owned exact-release overlays; runtime retrieval is bounded
  to eight items and 800 tokens, with 150 tokens maximum always-on memory.

## Output

Return `status`, `evidence`, `output`, and `blockers`, plus team topology,
nodes, edges, interview/research artifacts, generated files, verification
command, and `global_commands`.
