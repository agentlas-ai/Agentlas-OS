# Agentlas Auto-Activation

Agentlas auto-activation is a public contract for local runtimes that want a
project folder to become an Agentlas-aware workspace.

It is not tied to one desktop app. Agentlas Core owns the canonical bootstrap;
trusted writable Desktop and Terminal sessions, plus explicit activation from
other hosts, call that same Core command instead of implementing divergent
seeders. Passive search, read-only work, and MCP discovery do not write project
state by default.

## Purpose

When a trusted Agentlas host begins writable work in a real project, or the
user explicitly activates the folder, the runtime makes project memory,
sitemap/task-bias, PM Soul, Memory Tickets, local ontology indexes, and a
bounded code map available. Unsafe roots such as the user's home directory and
filesystem root remain untouched.

## Activation Triggers

A runtime activates when either condition is true:

- explicit activation: the user runs `hephaestus project ensure --project
  <folder>` or a native host invokes the equivalent Core operation;
- trusted writable first contact: a native host opts in to automatic bootstrap,
  supplies an allowed project root, and the folder contains a recognized
  workspace marker.

Search, call, route, and Storm commands remain passive unless the caller passes
`--ensure-project` or the host explicitly enables
`AGENTLAS_PROJECT_BOOTSTRAP_AUTO=1`. MCP has a separate, default-off
`AGENTLAS_MCP_PROJECT_BOOTSTRAP_AUTO=1` gate. Automatic activation also requires
`AGENTLAS_PROJECT_BOOTSTRAP_ALLOWED_ROOTS` and a workspace marker, so an
untrusted prompt argument cannot opt itself in.

Core installs the managed privacy `.gitignore` block before writing local
memory or indexes, creates only missing files, and never overwrites project
content without approval.

## Files To Create

Create `.agentlas/` only when activation happens.

Recommended minimum:

```text
.agentlas/
├── project-soul-memory.md
├── sitemap.json
├── memory-map.json
├── memory-tickets.jsonl
├── vault-references.json
├── local-credentials.map.json
├── skill-registry.json
├── skill-trials.jsonl
├── curator-decisions.jsonl
├── super-ontology-contract.json
├── super-ontology-open-world-coverage.json
├── super-ontology-consensus-coordination.json
├── super-ontology-task-coverage.json
├── super-ontology-contextual-flow.json
├── super-ontology-causal-impact.json
├── super-ontology-assurance-case.json
├── super-ontology-knowledge-homeostasis.json
├── super-ontology-adversarial-provenance.json
├── super-ontology-epistemic-calibration.json
├── super-ontology-semantic-alignment.json
├── super-ontology-resilience-control.json
├── super-ontology-invariant-verification.json
├── super-ontology-observability-telemetry.json
├── super-ontology-objective-proxy-validity.json
├── super-ontology-stakeholder-preference-governance.json
├── super-ontology-normative-authority-drift.json
├── super-ontology-side-effect-containment.json
├── super-ontology-source-lineage-version.json
├── super-ontology-entity-identity-resolution.json
├── super-ontology-temporal-state-transition.json
├── super-ontology-capability-delegation-authority.json
├── super-ontology-privacy-confidentiality-boundary.json
├── super-ontology-strategic-incentive-compatibility.json
├── super-ontology-reflexive-feedback-stability.json
├── super-ontology-replays.jsonl
├── super-ontology-evidence.jsonl
├── super-ontology-memory-bridge.jsonl
└── activation.json

.env.example
signing/
└── README.md
credentials/
└── README.md
```

If a package already includes `.agentlas/`, merge missing files without
overwriting user content.

## File Contracts

`project-soul-memory.md`

- Stores durable project decisions, constraints, risks, open loops, and current
  operating context.
- Must keep `Local Credential Index (read first)` near the top so deploy,
  release, store, billing, auth, API, and cloud work can find local credential
  locations before ordinary project notes.
- Must not store secrets, raw logs, or full transcripts.

`sitemap.json`

- Tracks project surfaces, status, risk, stale areas, evidence, and validation
  needs.
- Used by sitemap/task-bias logic to avoid only working on recent or obvious
  files.

`memory-map.json`

- Explains where memory belongs: user, team, project, agent repo, session, or
  discard.
- Points to sources, not secret values.

`memory-tickets.jsonl`

- Append-only queue of proposed durable memory events.
- Memory Curator reviews, redacts, deduplicates, and routes them.

`vault-references.json`

- References secret names or vault locations.
- Never stores secret values.
- May reference borrowed-agent credential request ids, but only as value-free
  vault pointers.

`local-credentials.map.json`

- Indexes project-local `.env`, `signing/`, and `credentials/` material.
- Stores env names, provider names, relative file paths, owner, and stale-check
  instructions.
- For borrowed agents/plugins, may also store value-free request metadata:
  allowed host, scope, setup URL, input mode, save target, and broker mode.
- Never stores scalar credential values or credential file contents.
- Does not prove host binding unless the local runtime actually uses a separate
  host-bound broker instead of child-process environment injection.
- Must be checked with the top project-soul credential index before an agent
  concludes that a credential is missing.

`.env.example`, `signing/README.md`, `credentials/README.md`

- Prepare a local credential store without committing real values.
- `.env`, `.env.local`, `signing/*`, and `credentials/*` must be ignored by git.

`activation.json`

- Public-safe activation metadata: schema version, activated time, runtime name,
  activation reason, and files created.

`skill-registry.json`

- Export-only candidate skill lifecycle metadata. First-class recall must stay
  disabled until local Curator review approves it.

`skill-trials.jsonl` and `curator-decisions.jsonl`

- Append-only ledgers for future trial evidence and Curator decisions. They are
  empty on activation unless a local runtime has real evidence to append.
- In portable packages this may start as `state: "seed"` so a local runtime can
  decide when to activate it.

`super-ontology-contract.json`

- Candidate-only adaptive knowledge governance metadata.
- Keeps `runtimeGraphWriteEnabled` and `zeroErrorClaim` false on export.
- Adds operator-managed local promotion metadata: local promotion gates are
  project, folder, owner, evidence, and rollback organization checks, not a
  generic security stop sign. Public exports remain value-free.
- Names the source-intake, evidence-packet, belief-ledger, knowledge-capsule,
  affordance-binding, open-world-coverage, consensus-coordination, task-coverage, contextual-flow, causal-impact,
  assurance-case, knowledge-homeostasis, adversarial-provenance,
  epistemic-calibration, semantic-alignment, resilience-control,
  invariant-verification, observability-telemetry, objective-proxy-validity,
  stakeholder-preference-governance,
  normative-authority-drift,
  side-effect-containment,
  strategic-incentive-compatibility,
  reflexive-feedback-stability,
  promotion-readiness, replay, and sync-review gates.

`super-ontology-open-world-coverage.json`

- Export-only open-world coverage seed.
- Treats new world/task/modality/fault/authority/write-surface combinations as
  candidate-only until fixture pressure, shadow replay, owner review, and sync
  review lower or approve authority.
- Blocks proposal/deck examples from being treated as proof that all future
  work is covered.

`super-ontology-consensus-coordination.json`

- Export-only consensus coordination seed.
- Keeps agent agreement, majority vote, debate, model-judge approval,
  distributed replica merge, and cross-runtime sync from becoming write
  authority without independent evidence, veto, owner/policy review, sync
  review, invariants, and rollback.

`super-ontology-task-coverage.json`

- Export-only task coverage seed.
- Requires unknown requests to be classified by task family before graph slices,
  memory handoffs, tool bindings, external writes, physical actions, or training
  actions.
- Keeps runtime promotion disabled until evidence mode, authority, review, and
  rollback are explicit.

`super-ontology-contextual-flow.json`

- Export-only contextual flow seed.
- Requires information flows to name sender, recipient, subject, attribute,
  purpose, authority, transmission principle, retention, and audit references
  before crossing personal, company, customer, public, regulated, agent, memory,
  tool, output, or public-export boundaries.
- Keeps runtime promotion disabled and blocks same-user context joins,
  tool-response oversharing, raw prompt memory, customer-data publication, and
  agent-internal trace exposure.

`super-ontology-causal-impact.json`

- Export-only causal impact seed.
- Requires relation-to-action jumps to name intervention target,
  counterfactual checks, adverse outcomes, observability, reversibility, blast
  radius, and rollback.
- Keeps runtime promotion disabled and blocks correlation-as-causation,
  physical action, training, and multi-agent shared-state writes without
  evidence and review.

`super-ontology-assurance-case.json`

- Export-only assurance case seed.
- Requires broad claims to name required evidence, observed evidence,
  validators, residual risk, blocked shortcuts, and rollback.
- Keeps runtime promotion disabled and treats perfection or zero-error language
  as a rejected overclaim.

`super-ontology-knowledge-homeostasis.json`

- Export-only knowledge health seed.
- Requires stale, contradictory, unsupported, drifting, parser-failed,
  privacy-incident, missing-evidence, user-corrected, or runtime-desynced
  knowledge to name signal, measurement, error budget, control decision,
  Memory Curator policy, public export policy, escalation, and rollback.
- Keeps runtime promotion disabled and blocks critical health signals from
  direct runtime writes.

`super-ontology-adversarial-provenance.json`

- Export-only hostile-source provenance seed.
- Requires uploads, web pages, emails, chats, tool responses, connector results,
  memory recalls, public repos, media assets, AppBridge route outputs,
  generated artifacts, and datasets to name source channel, attack vector,
  trust boundary, claimed authority, observed artifact, provenance evidence,
  integrity checks, instruction policy, retrieval policy, memory policy, tool
  policy, promotion decision, controls, forbidden shortcuts, and rollback.
- Keeps runtime promotion disabled and blocks prompt injection, poisoning,
  forged provenance, spoofed citations, hidden OCR instructions, tampered tool
  output, stale trusted-source replay, and unsigned release artifacts from
  becoming retrieval, memory, tool, or public seed authority.

`super-ontology-epistemic-calibration.json`

- Export-only uncertainty and abstention seed.
- Requires unknown work to name context type, claim type, uncertainty source,
  epistemic state, calibration signal, confidence band, risk tier, allowed
  output, evidence refs, memory policy, tool policy, public export policy, and
  rollback before answers, memory writes, tool actions, route sync, or public
  artifacts.
- Keeps runtime promotion disabled and blocks missing evidence, conflicting
  sources, low retrieval relevance, stale policies, noisy OCR, inconclusive
  tool output, model disagreement, wide judge intervals, and uncalibrated route
  sync from becoming confident answers or graph writes.

`super-ontology-semantic-alignment.json`

- Export-only term, schema, ontology, entity, relation, and glossary alignment
  seed.
- Requires proposed matches to name source context, artifact type, source term,
  target term, alignment intent, candidate relation, scope, ambiguity, semantic
  evidence, structural evidence, lexical evidence, negative evidence,
  validation checks, owner/curator controls, change policy, and rollback.
- Keeps runtime promotion disabled and blocks same labels, embedding similarity,
  generated labels, OCR labels, AppBridge route labels, source conflicts,
  missing unit compatibility, missing direction checks, and no-match cases from
  becoming graph or memory changes.

`super-ontology-resilience-control.json`

- Export-only degraded-operation and self-adaptive control seed.
- Requires degraded operation to name control-loop phase, signal, hazard,
  operating mode, control decision, trigger threshold, feedback, controls,
  blocked shortcuts, Memory Curator policy, sync policy, and rollback.
- Keeps runtime promotion disabled and blocks validator disagreement, retrieval
  drift, semantic regression, provenance gaps, curator backlog, tool error
  spikes, unknown tasks, context-flow violations, sync drift, degraded parsers,
  rollback failure, and emergency-stop bypass from becoming graph, memory, tool,
  route, release, or public-artifact authority.

`super-ontology-invariant-verification.json`

- Export-only runtime invariant seed.
- Requires event streams and temporal constraints to be checked before memory,
  graph, tool, public export, route sync, release, rollback, or emergency-stop
  authority.
- Keeps runtime promotion disabled and blocks direct memory writes, graph writes
  without evidence, tool actions without authority, public export without
  contextual-flow approval, route sync without source-contract verification,
  unobserved rollback, emergency-stop bypass, unordered multi-agent writes, and
  non-idempotent replay mutation.

`super-ontology-observability-telemetry.json`

- Export-only traceability and audit seed.
- Requires trace id, span id, correlation id when crossing surfaces,
  source/evidence refs, authority and decision state, redaction and retention
  policy, audit sink, snapshots where relevant, rollback refs, alert refs, and
  sample size before state-changing events can be considered.
- Keeps runtime promotion disabled and blocks writes without trace ids, memory
  tickets without span lineage, tool actions without audit receipts, public
  exports with stale metrics, route sync without correlation ids, release seeds
  when audit sinks are down, suppressed degraded-mode alerts, unrecorded shadow
  replays, repair without before/after snapshots, and unobservable runtime
  writes.

`super-ontology-objective-proxy-validity.json`

- Export-only objective/proxy validity seed.
- Requires metric-driven optimization to name the real construct, proxy metric,
  stakeholder map, countermetric, validity evidence, gaming probe, and rollback
  before graph, memory, tool, route, release, or public writes can treat metric
  movement as success.
- Keeps runtime promotion disabled and blocks approval rate, open rate,
  benchmark score, test pass rate, ontology edge count, self-judge score,
  short-term profit, green dashboards, and reward deltas from becoming write
  authority without construct validity and anti-gaming evidence.

`super-ontology-stakeholder-preference-governance.json`

- Export-only stakeholder preference governance seed.
- Requires preference-driven work to name stakeholder roles, preference
  sources, authority scope, affected parties, conflict type, aggregation rule,
  dissent capture, appeal path, review owner, consent or rights vetoes, and
  rollback before graph, memory, personalization, tool, route, release, public,
  training, customer-message, financial, hiring, health, physical, or
  runtime-policy writes can treat a preference as legitimate authority.

`super-ontology-normative-authority-drift.json`

- Export-only normative authority drift seed.
- Requires policy-like, law-like, contract-like, license-like, consent-like,
  retention-like, emergency-exception, or professional-guideline sources to
  name primary source, effective date, jurisdiction scope, authority owner,
  precedence, review owner, exception expiry where relevant, audit trail, and
  rollback before write authority.
- Keeps runtime promotion disabled and blocks stale policy, wrong jurisdiction,
  draft policy, superseded contract, expired consent, translation mismatch,
  license conflict, cross-border transfer gaps, emergency exceptions without
  expiry, and legal/compliance claims without review from becoming write
  authority.

`super-ontology-side-effect-containment.json`

- Export-only side-effect containment seed.
- Requires sends, payments, deletes, releases, cloud permission changes,
  database writes, training updates, route sync, scheduled jobs, physical
  actions, and legal/compliance commitments to name dry-run, idempotency,
  approval, transaction, compensation, cancellation, receipt, audit, and
  rollback evidence before execution.
- Keeps runtime promotion disabled and blocks preview-as-send, dry-run as
  committed, non-idempotent retries, irreversible actions without approval,
  release without rollback, partial failure without saga state, physical action
  without safety interlock, and scheduled action without cancellation.

`super-ontology-source-lineage-version.json`

- Export-only source lineage and version seed.
- Requires drafts, exported PDFs, summaries, translations, redacted copies,
  spreadsheet tabs, connector caches, chunks, embeddings, memory notes, and
  superseded runtime contracts to name source URI, checksum or content hash,
  version/revision, derivation chain, parent refs, authority owner,
  transformation log, span, audit, and rollback before promotion.
- Keeps runtime promotion disabled and blocks filename-as-version,
  final-folder-as-current-source, PDF export as primary source, summary as
  primary source, stale cache as current record, chunk without source span,
  embedding hit without artifact version, Memory fact without lineage, public
  export without lineage evidence, graph edge without derivation chain, and
  superseded source to runtime write.

`super-ontology-entity-identity-resolution.json`

- Export-only entity identity resolution seed.
- Requires names, aliases, domains, phone numbers, CRM ids, employee ids,
  redacted identifiers, external URIs, embedding clusters, and LLM-generated
  canonical labels to remain candidate-only until canonical id, source-system
  namespace, source span, disambiguating evidence, negative evidence, temporal
  validity, privacy basis, owner review, merge/split policy, audit, and
  rollback exist.
- Keeps runtime promotion disabled and blocks ambiguous identity merges,
  public identity leakage, cross-tenant id collisions, stale aliases, recycled
  ids, relationship edges without endpoint identity, and memory notes as
  identity authority.

`super-ontology-temporal-state-transition.json`

- Export-only temporal state transition seed.
- Keeps runtime promotion disabled and blocks current snapshots, missing valid
  time, missing transaction time, local timestamps as global order, spreadsheet
  row order as event order, LLM summaries as event logs, late events, future
  effective policies as current, expired states, deleted nodes without
  tombstones, non-idempotent replays, materialized views as source of truth,
  projections without version, recurring events without rules, timezone-free
  deadlines, stale caches, partial failures, scheduled jobs without receipts,
  memory facts without validity intervals, and graph edges without temporal
  bounds.

`super-ontology-capability-delegation-authority.json`

- Export-only capability delegation authority seed.
- Keeps runtime promotion disabled and blocks role/group/OAuth scope/API key,
  service account, session cookie, tool schema, cached decision, broad
  approval, and child-agent token shortcuts from becoming graph, memory,
  public, training, tool, route, scheduled, permission, financial, release,
  customer-output, or physical authority.
- Requires actor identity, agent identity, user intent, task id, workflow step,
  delegation chain, parent capability, resource id, operation, scope, purpose,
  caveats, consent or owner approval, policy decision/version, revocation
  check, audit trace, rollback snapshot, and post-action verification where
  needed.

`super-ontology-privacy-confidentiality-boundary.json`

- Export-only privacy/confidentiality boundary seed.
- Keeps runtime promotion disabled and blocks PII, secrets, HR notes, legal
  privilege, personal diary context, customer decks, connector caches,
  screenshots, embeddings, and inferred sensitive attributes from becoming
  graph, memory, public, training, tool, route, customer-output,
  personalization, retrieval, or analytics authority.
- Requires data classification, sensitivity label, source span, subject
  category, owner/controller, purpose, audience, legal or confidentiality
  basis, minimization, redaction, retention, transfer, public/training flags,
  access policy decision, audit trace, breach owner, and rollback evidence
  where needed.

`super-ontology-strategic-incentive-compatibility.json`

- Export-only strategic incentive compatibility seed.
- Keeps runtime promotion disabled and blocks self-reports, KPI movement,
  commissions, approvals, customer ratings, benchmark scores, agent votes,
  vendor claims, cost-saving claims, compliance attestations, access requests,
  social or family pressure, hidden affiliations, strategic silence, and
  collusive quorums from becoming graph, memory, public, training, tool,
  route, release, financial, hiring, policy, customer-output, analytics,
  evaluation, or personalization authority.
- Requires principal, agent, private information, objective function, payoff or
  reward model, conflict disclosure, strategic behavior hypothesis,
  truthfulness check, audit sample, independent verification, collusion check,
  mechanism constraint, counter-incentive, appeal path, audit trace, rollback,
  monitoring, and residual incentive risk where needed.

`super-ontology-reflexive-feedback-stability.json`

- Export-only reflexive feedback stability seed.
- Keeps runtime promotion disabled and blocks post-intervention observations,
  recommendation effects, generated artifacts, dashboard movement, repeated
  retrieval, route distributions, market responses, agent self-scores, social
  contagion, scheduler replays, and user adaptation from becoming graph,
  memory, public, training, tool, route, release, financial, hiring, policy,
  customer-output, analytics, evaluation, physical-action, or personalization
  authority.
- Requires intervention id, pre-intervention baseline, feedback path, time lag,
  holdout or counterfactual, real-world anchor, synthetic-data ratio, stability
  margin, damping or rate limit, saturation bound, externality map, affected
  stakeholders, monitoring trace, stop condition, rollback, owner review, and
  residual feedback risk where needed.

`super-ontology-replays.jsonl` and `super-ontology-evidence.jsonl`

- Empty append-only ledgers for future shadow/canary/rollback replay and
  promotion evidence.
- They do not make the ontology runtime-active by themselves.

`super-ontology-memory-bridge.jsonl`

- Empty append-only Memory Curator bridge ledger on export.
- Later runtimes may append redacted Memory Ticket bridge candidates only after
  raw prompts, secret values, private paths, and direct durable memory writes
  are blocked.

## Runtime Behavior

After activation, local runtimes should:

1. Read `.agentlas/project-soul-memory.md` before project-level claims.
2. Inject relevant memory context into agent prompts.
3. Ask workers to emit `## Memory Events` only for durable facts.
4. Route those events through Memory Tickets and Memory Curator.
5. Use `sitemap.json` to surface stale or under-validated work.
6. Keep activation idempotent and reversible.

## Safety Rules

- Never activate outside an explicitly selected or host-allowed project root.
- Never treat passive search, read-only execution, or an MCP request as write
  consent.
- Never overwrite existing `.agentlas` files without explicit approval.
- Never store credentials, API keys, raw logs, full transcripts, cookies,
  private keys, service-account files, or payment material.
- Never silently publish `.agentlas` memory from a private project.
- Keep runtime-specific state in runtime storage, not in public package files.

## Public Package Interaction

Generated or packaged Agentlas repos may include `.agentlas` seed files. A local
runtime that activates the folder should treat those files as starting
contracts, not as private runtime state.
