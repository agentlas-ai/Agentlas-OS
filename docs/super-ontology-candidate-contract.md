# Super Ontology Candidate Contract

The Super Ontology contract is a public-safe seed for adaptive knowledge
governance. It is not a claim that one ontology can perfectly cover every
future situation.

## Files

Generated or packaged repos may include:

```text
.agentlas/
  super-ontology-contract.json
  super-ontology-open-world-coverage.json
  super-ontology-task-coverage.json
  super-ontology-contextual-flow.json
  super-ontology-causal-impact.json
  super-ontology-assurance-case.json
  super-ontology-knowledge-homeostasis.json
  super-ontology-adversarial-provenance.json
  super-ontology-epistemic-calibration.json
  super-ontology-semantic-alignment.json
  super-ontology-resilience-control.json
  super-ontology-invariant-verification.json
  super-ontology-replays.jsonl
  super-ontology-evidence.jsonl
  super-ontology-memory-bridge.jsonl
```

`super-ontology-contract.json`

- Describes the allowed ontology pipeline: source intake, evidence packets,
  belief ledger, knowledge capsules, affordance binding, open-world coverage,
  task coverage,
  promotion readiness, replay drills, and rollback.
- Must set `runtimeGraphWriteEnabled` to `false` on export.
- Must set `zeroErrorClaim` to `false`.
- Must stay candidate-only until local runtime policy, shadow/canary replay,
  rollback, and sync review approve a later phase.

`super-ontology-replays.jsonl`

- Append-only shadow, canary, rollback, and sync-review replay evidence.
- Empty on export.
- Runtime agents may append records later only after the local Memory Curator,
  PM Soul, or architecture sync owner approves the evidence boundary.

`super-ontology-evidence.jsonl`

- Append-only promotion evidence rows.
- Empty on export.
- Evidence must identify the proof key, target surface, status, and summary
  without storing private logs, local paths, credentials, or raw source content.

`super-ontology-memory-bridge.jsonl`

- Append-only Memory Curator bridge candidates.
- Empty on export; the public core repo may carry a public-safe seed row for
  schema visibility.
- Rows must keep `durable_write_enabled=false` until Memory Curator, Policy
  Gate, PM Soul, or architecture sync review accepts the ticket.
- Rows must not store raw prompts, secret values, private paths, full
  transcripts, or direct durable memory writes.

`super-ontology-open-world-coverage.json`

- Public-safe open-world coverage seed.
- Requires new world, task signal, modality, fault model, authority state, and
  write-surface combinations to stay candidate-only until fixture pressure,
  shadow replay, owner review, and sync review lower or approve authority.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks proposal/deck examples from being treated as proof that every future
  task is covered.

`super-ontology-task-coverage.json`

- Public-safe task-family coverage seed.
- Requires requests to be classified as read, draft, transform, analyze, plan,
  coordinate, execute, repair, personalize, regulated, multimodal, physical,
  software, finance/compliance, or education/coaching work before action.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks write, publish, execute, physical, and training tasks unless evidence
  mode, authority, review, and rollback are explicit.

`super-ontology-contextual-flow.json`

- Public-safe contextual-flow seed.
- Requires information flows to name source context, target context, sender,
  recipient, subject, attribute, transmission principle, purpose, authority,
  sensitivity, retention, controls, and audit references.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks same-user cross-context joins, tool responses treated as need-to-know,
  raw prompt or transcript memory writes, public output after private handoff,
  customer-data publication without consent, regulated training without delete
  path, and agent-internal traces in user output.

`super-ontology-causal-impact.json`

- Public-safe causal-impact seed.
- Requires state-changing work to name causal claim type, intervention target,
  expected outcomes, adverse outcomes, counterfactual checks, observability,
  reversibility, blast radius, blocked write surfaces, and rollback.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks correlation-as-causation, relation-as-permission, autonomous physical
  control, training without consent/delete path, and multi-agent writes without
  ordered handoff.

`super-ontology-assurance-case.json`

- Public-safe claim/evidence seed.
- Requires broad claims about coverage, memory safety, action safety,
  promotion readiness, red-team follow-up, or sync integrity to name required
  evidence, observed evidence, validators, residual risk, blocked shortcuts,
  and rollback.
- Keeps `runtimePromotionAllowed=false` on export.
- Treats literal perfection or zero-error language as a rejected overclaim, not
  a release state.

`super-ontology-knowledge-homeostasis.json`

- Public-safe knowledge-health seed.
- Requires stale, contradictory, unsupported, drifting, parser-failed,
  privacy-incident, missing-evidence, user-corrected, or runtime-desynced
  knowledge to name signal, measurement window, error budget, affected surface,
  control decision, escalation, evidence, Memory Curator policy, public export
  policy, and rollback.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks overrun budgets from continuing silently, critical cases from runtime
  writes, privacy incidents from public export, AppBridge routes from becoming
  source-write authority, and stale claims from becoming current truth.

`super-ontology-adversarial-provenance.json`

- Public-safe hostile-source provenance seed.
- Requires arbitrary uploads, web pages, emails, chats, tool responses,
  connector results, recalled memories, public repos, media assets, AppBridge
  routes, generated artifacts, and datasets to name claimed authority,
  provenance evidence, integrity checks, instruction policy, retrieval policy,
  memory policy, tool policy, promotion decision, forbidden shortcuts, and
  rollback.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks prompt injection from becoming instruction, poisoned sources from
  becoming memory, forged provenance from becoming trusted source, tool-output
  tampering from becoming action, route output from becoming source-write
  authority, and stale trusted-source replay from becoming current truth.

`super-ontology-epistemic-calibration.json`

- Public-safe uncertainty and abstention seed.
- Requires arbitrary future work to name context type, claim type, uncertainty
  source, epistemic state, calibration signal, confidence band, risk tier,
  allowed output, required controls, blocked shortcuts, evidence refs, research
  basis, memory policy, tool policy, public export policy, and rollback.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks missing evidence as complete answer, conflicting sources as current
  truth, low retrieval relevance as confident answer, noisy OCR as ontology
  class, model disagreement as consensus, inconclusive tool output as action,
  uncalibrated route sync, and wide judge intervals in regulated answers.

`super-ontology-semantic-alignment.json`

- Public-safe semantic alignment seed.
- Requires proposed glossary, schema, ontology, relation, hierarchy,
  entity-resolution, source-system merge, memory-merge, release-sync, or no-match
  decisions to name relation type, scope, ambiguity, semantic evidence,
  structural evidence, lexical evidence, negative evidence, validation checks,
  owner controls, blocked shortcuts, change policy, and rollback.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks same label as same meaning, embedding similarity as exact match,
  close-match as transitive truth, generated label as ontology class, OCR label
  as property alignment, AppBridge route as source ontology edit,
  same-individual without stable identifier, unit label without compatibility,
  source conflict as memory merge, and no-match promoted to weak match.

`super-ontology-resilience-control.json`

- Public-safe degraded-operation and self-adaptive control seed.
- Requires degraded operation to name control-loop phase, degradation signal,
  hazard type, operating mode, control decision, trigger threshold, observed
  evidence, feedback channels, controls, blocked shortcuts, Memory Curator
  policy, sync policy, and rollback.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks validator disagreement as graph write, retrieval drift as current
  answer, semantic regression as memory merge, provenance gap as tool authority,
  Memory Curator backlog as direct memory write, tool error spike as unbounded
  retry, unknown task as normal execution, context-flow violation as public
  export, sync drift as release surface, degraded parser as ontology class,
  rollback failure as runtime promotion, and AppBridge route as emergency-stop
  bypass.

`super-ontology-invariant-verification.json`

- Public-safe runtime-verification and temporal-invariant seed.
- Requires event streams such as source intake, evidence packets, belief
  updates, semantic alignment, resilience mode, memory tickets, graph writes,
  tool calls, public exports, route sync, release seeds, rollback, and
  emergency stop to be checked by explicit monitors before runtime writes.
- Keeps `runtimePromotionAllowed=false` on export.
- Blocks memory writes without curator-ticket invariants, graph writes without
  evidence invariants, tool actions without authority invariants, public export
  without contextual-flow invariants, route sync without source-contract
  invariants, rollback without observed feedback, emergency-stop bypass,
  unordered multi-agent writes, and non-idempotent replay mutation.

## Default State

Every exported Super Ontology contract starts as:

```text
state = candidate
runtimeGraphWriteEnabled = false
zeroErrorClaim = false
shadowRequired = true
canaryRequiredForMixedContext = true
rollbackRequired = true
openWorldCoverageRequired = true
unknownCombinationRuntimeWritesBlocked = true
uncoveredModalityRuntimeWritesBlocked = true
taskCoverageRequired = true
contextualFlowRequired = true
causalImpactRequired = true
assuranceCaseRequired = true
knowledgeHomeostasisRequired = true
adversarialProvenanceRequired = true
epistemicCalibrationRequired = true
semanticAlignmentRequired = true
resilienceControlRequired = true
invariantVerificationRequired = true
memoryCuratorBridgeRequired = true
directDurableMemoryWritesBlocked = true
untrustedSourceRuntimeWritesBlocked = true
uncalibratedRuntimeWritesBlocked = true
highAuthorityAlignmentReviewRequired = true
unreviewedSemanticRuntimeWritesBlocked = true
degradedRuntimeWritesBlocked = true
emergencyStopBypassBlocked = true
runtimeInvariantWritesBlocked = true
forbiddenTransitionBlocked = true
```

The package can be searched, reviewed, and replayed. It cannot write official
knowledge, mutate runtime memory, or authorize tools by itself.

## Required Pipeline

The public contract names these layers:

1. source intake,
2. evidence packet,
3. belief ledger,
4. knowledge capsule,
5. affordance action binding,
6. open-world coverage contract,
7. task coverage contract,
8. contextual flow contract,
9. causal impact contract,
10. assurance case contract,
11. knowledge homeostasis contract,
12. adversarial provenance contract,
13. epistemic calibration contract,
14. semantic alignment contract,
15. resilience control contract,
16. invariant verification contract,
17. Agentlas integration contract,
18. Memory Curator bridge,
19. promotion readiness,
20. promotion replay drill,
21. architecture sync review.

## Hard Stops

Automatic promotion is blocked when:

- a candidate claims zero-error or universal completeness;
- a raw source would write directly into an ontology;
- a graph edge joins forbidden personal/company/public contexts;
- a downstream agent receives the whole graph instead of a task capsule;
- a tool call lacks argument provenance or user authority;
- a proposal/deck fixture is treated as proof that all future work is covered;
- a new world, task, modality, fault, authority, or write-surface combination
  would proceed without open-world fixture pressure, shadow replay, owner
  review, or sync review;
- a requested task family, affordance type, evidence mode, or rollback path is
  missing;
- a relation would be treated as causation, action permission, or intervention
  authority without counterfactual checks, blast radius, observability, and
  rollback;
- a broad claim lacks an assurance case, observed evidence, validator, residual
  risk, or rollback plan;
- a knowledge health signal overruns its error budget but still continues;
- a critical homeostasis row would allow direct runtime writes;
- a privacy incident would public-export or write memory without quarantine;
- stale, parser-failed, or runtime-desynced knowledge would be treated as
  current operational truth;
- prompt injection, poisoned source, spoofed citation, forged provenance,
  hidden OCR text, tool-output tampering, or stale trusted-source replay would
  become retrieval, memory, tool, or public seed authority;
- missing evidence, conflicting sources, stale evidence, low retrieval
  relevance, model disagreement, or unknown epistemic state would become a
  confident answer, graph write, tool action, memory write, or public artifact;
- a regulated answer, financial estimate, scientific claim, physical action, or
  route sync has an uncalibrated confidence band or wide judge interval;
- a same label, similar embedding, generated label, OCR label, route label,
  abbreviation, or unit label would become an exact/equivalent/same-individual
  relation, graph edge, memory merge, or public artifact without scope,
  validation, owner review, diff, and rollback;
- validator disagreement, retrieval drift, semantic regression, provenance
  gaps, Memory Curator backlog, tool error spikes, unknown task families,
  context-flow violations, sync drift, degraded parser/sensor signals, rollback
  failure, or emergency-stop bypass would keep nominal graph, memory, tool,
  route, release, or public-artifact authority;
- memory writes, graph writes, tool calls, public exports, route sync, release
  seeds, rollback, or emergency-stop transitions bypass their event-stream
  invariants;
- an AppBridge route output would be treated as source-write authority;
- a release artifact lacks SLSA or in-toto style provenance;
- AppBridge is treated as source of truth;
- a candidate bypasses the Memory Curator bridge and writes durable memory
  directly;
- a memory candidate stores raw prompt, private path, or secret-like material;
- rollback is missing;
- live shadow/canary evidence is missing for runtime behavior.

## Runtime Boundary

Public core defines the contract. Hosted Web may emit it in ZIP exports.
Desktop and terminal may seed it locally, but only as candidate metadata until
local policy approves a later phase.

This contract came from the Super Ontology Architect research. Treat it as
evaluation and governance infrastructure first. Do not claim production
omniscience or first-class runtime behavior from export metadata alone.
