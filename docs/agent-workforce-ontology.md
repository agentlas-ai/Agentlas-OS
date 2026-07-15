# Agent Workforce Ontology

Status: implementation contract, 2026-07-16.

Canonical menu: `awo:2026-07-15.2`.

Raw `agentlas_cloud/workforce/ontology_v1.json` SHA-256:
`d6d30d45fe8d35fb785e165d1e80c6471a72436f0160c3933c21d4a31bf2fb32`.
Core, Hub, Desktop, Terminal, and AppBridge clients must pin both values and
fail closed on drift. The reviewed singular `payment` alias belongs only to
`community:payments-engineering`; general `security` belongs only to
`community:security-engineering`. These aliases expand controlled-vocabulary
recall and do not restore the retired lexical/R1 staffing path.

## Purpose

Agentlas treats Hub, Cloud, and local packages as a workforce rather than a
ranked list of prompt files. A host LLM creates the temporary task force. The
ontology supplies job analysis, qualified candidate sets, executable package
contracts, and validation. It never makes the final staffing decision.

The contract addresses the observed baseline failure in which a request to
research and implement a workforce ontology was routed to
`agentlas-desktop-hub-export-smoke-20260628-final` as one specialist. The
baseline receipt is `619f95e119ce4f7e`.

## Research mapping

The model borrows structure, not employment claims, from established workforce
standards:

- OPM job analysis links work tasks to the competencies and resources required
  to perform them. Agentlas maps this to `WorkItem -> RoleSlot -> Requirement`.
  <https://www.opm.gov/policy-data-oversight/assessment-and-selection/job-analysis/>
- O*NET separates worker requirements from occupational requirements and
  occupation-specific tasks. Agentlas separates immutable worker supply from
  per-request work demand. <https://www.onetcenter.org/content.html>
- NICE uses Task, Knowledge, and Skill statements to compose Work Roles and
  competency areas. Agentlas adds tool, artifact, runtime, and authority
  requirements needed by software agents.
  <https://www.nist.gov/nice/framework>
- ESCO provides versioned, multilingual occupation and skill concepts, aliases,
  broader relations, and occupation-skill relations addressed by stable URIs.
  Agentlas can import those URIs but owns a smaller agent-specific extension
  namespace. <https://esco.ec.europa.eu/en/structure-esco-downloadable-datasets>
- W3C ORG distinguishes an abstract Role, an unfilled Post, and a Membership
  that binds an Agent to a Role in an organization. Agentlas maps these to
  `Role`, `RoleSlot`, and `TaskForceAssignment`.
  <https://www.w3.org/TR/vocab-org/>
- SKOS supplies stable concept schemes, labels, broader/narrower relations, and
  explicit crosswalks; PROV-O supplies derivation and attribution; SHACL
  supplies graph-shape validation; ODRL supplies machine-readable authority
  and prohibition expressions. Agentlas uses these patterns without claiming
  that a package declaration is verified performance.
  <https://www.w3.org/TR/skos-reference/>
  <https://www.w3.org/TR/prov-o/>
  <https://www.w3.org/TR/shacl/>
  <https://www.w3.org/TR/odrl-model/>

## Non-negotiable decision boundary

```text
user task
  -> host LLM job analysis and role slots
  -> Hub MCP ontology candidate retrieval
  -> deterministic hard eligibility and contract validation
  -> rank-free candidate cards with fit evidence
  -> host LLM chooses ideal task force
  -> host validates executable overlays and substitutions
  -> Agentlas execution fabric runs distinct workers and handoffs
  -> independent verifier and completion receipt
```

Deterministic code may:

- parse and normalize public package contracts;
- enforce release, entitlement, permission, tool, runtime, input/output, and
  authority constraints;
- retrieve a broad, diverse, content-matched candidate set;
- verify that an LLM decision uses candidates from that set and covers every
  mandatory role slot;
- reject an invalid or unsafe decision.

Deterministic code must not:

- select the final top-1 agent or task force;
- silently replace an unavailable worker with an unrelated callable worker;
- use invocation count, installs, ratings, revenue, popularity, or historical
  success to determine community membership or semantic fit;
- remove a zero-history release merely because it has no usage evidence;
- flatten a packaged team into one prompt when it declares an execution graph.

## Demand model: the job to be staffed

`WorkOrder` is created by the host LLM and contains one or more `RoleSlot`
records. A slot is the equivalent of an unfilled W3C ORG Post. It exists before
any package is selected.

Each role slot can declare:

- task and deliverable summary;
- required and optional role/community URIs;
- skills, knowledge, and capability atoms;
- required MCP/tool capabilities, never secret values;
- consumed and produced artifact kinds;
- runtime, language, modality, and environment constraints;
- required authority and forbidden side effects;
- collaboration edges such as `reportsTo`, `handsOffTo`, and `reviews`;
- cardinality, criticality, and whether a packaged team is allowed.

The raw user prompt and private project context remain in the host. The Hub
receives a redacted task brief and structured requirements only.

Top-level `forbiddenCommunities` and per-slot `excludedCommunities` are explicit
incompatibility or prohibition boundaries. They are not the closed-world
complement of the desired role families. Workforce profiles are deliberately
multi-community, so a valid backend/payment release may also belong to broader
software engineering, database, security, or other legitimately co-occurring
communities. The host LLM must not exhaustively forbid every unused, broader,
adjacent, or co-occurring community, and the typed adapter must never generate
such a complement on its behalf.

## Supply model: the worker available for staffing

An `AgentDefinition` is a stable identity. An `AgentRelease` is immutable. A
`WorkforceProfile` is a reproducible projection of one release from:

- `agent.md`, `AGENTS.md`, and team topology;
- `agentlas.json` and runtime bundle metadata;
- `.agentlas/routing-card.json`;
- `.agentlas/mcp-policy.json` and MCP requirements;
- declared inputs, outputs, permissions, runtimes, languages, and risk;
- structural evaluation assertions with source and fixture provenance.

The profile distinguishes:

1. `capabilityAssertions`: what the package declares or a structural fixture
   directly proves;
2. `qualificationEvidence`: static validation, schema checks, fixture/eval
   evidence, and external attestations;
3. `operationalOverlay`: callability, installability, entitlement, available
   host tools, and credentials;
4. `performanceHistory`: usage and outcome observations.

Only the first three may participate in eligibility. Performance history is a
separate observation surface and is always excluded from community membership,
candidate retrieval, and staffing fit. It may be audited after the staffing
decision, but cannot reorder or remove content-fit candidates.

`declared`, `checked`, `demonstrated`, and `attested` are different evidence
levels. A work order may set a minimum evidence level for required skills and
tools. This must not be confused with `availableNow`, which belongs only to the
operational overlay.

## Ontology graph

Core node kinds:

```text
OccupationCommunity  WorkRole  Skill  Knowledge  ToolCapability
ArtifactKind         Authority Runtime Language EvalAssertion
AgentDefinition      AgentRelease TeamPattern OntologyContribution
```

Core relations:

```text
broaderThan / narrowerThan / relatedTo / aliasOf
roleRequiresSkill / roleRequiresKnowledge / roleRequiresTool
roleConsumes / roleProduces / roleRequiresAuthority
releaseOf / supersedes / memberOfCommunity / canPerformRole
hasSkill / hasKnowledge / hasToolCapability
consumes / produces / requiresAuthority / supportsRuntime
qualifiedBy / declaresTeamPattern / complements
```

Community membership is multi-valued and content-derived. A backend/payment
agent can belong to software engineering, backend engineering, payments, and
database communities simultaneously. Community votes or popularity never
create membership. Every inferred edge records its source release, rule/model
version, confidence band, and evidence refs.

Unknown terms do not make a release disappear. They produce an
`unmappedConcept` plus an ontology contribution proposal. The release remains
retrievable by its structured skills and tools until the community vocabulary
is reviewed.

## Community governance

The shared vocabulary changes through versioned contributions:

- propose concept, alias, broader/narrower edge, role requirement, split,
  merge, or deprecation;
- validate identifier uniqueness, cycles, contradictory boundaries, source
  lineage, and affected release count;
- review with a diff and replay corpus;
- publish a new immutable ontology version;
- rebuild projections from release sources and lifecycle events;
- retain aliases and tombstones so old receipts remain explainable.

Community governance is not a routing popularity contest. Votes can prioritize
review, but only evidence-bearing accepted contributions change the graph.

## Candidate retrieval

Retrieval runs in two layers.

### 1. Hard eligibility

A candidate is excluded only for an explicit reason code such as:

- inactive, withdrawn, deleted, or superseded release;
- wrong entity kind or missing authoritative team graph;
- missing mandatory capability, tool, artifact, runtime, language, or
  authority contract;
- forbidden side-effect or permission conflict;
- package integrity, entitlement, or security failure.

Community mismatch alone is not a hard exclusion when direct skill/tool
evidence satisfies the role. This preserves open-world recall.

An explicit match against `forbiddenCommunities` or `excludedCommunities` is a
hard exclusion. Because membership is multi-valued, forbidding a broad parent
or legitimate adjacent community can exclude the exact specialist requested by
another field. These boundaries therefore express known incompatibility or a
real prohibition only; absence from the desired-family list never implies
exclusion.

### 2. Content retrieval

The bounded set is the union of:

- exact concept/URI and alias matches;
- lexical/BM25 matches over public contract fields;
- semantic vector neighbors over the same content-only fields;
- bounded graph expansion through role, skill, tool, artifact, and community
  edges;
- diversity quotas so one crowded community cannot consume the full window.

The response is grouped by role slot. It contains fit evidence and missing
optional coverage, not a winner. Numeric retrieval signals are internal recall
diagnostics and are not exposed as a total staffing score.

## Host-LLM selection protocol

Every supported host uses the same typed adapter contract. The adapter owns MCP
transport; it is not a second planner or staffing authority.

1. The host LLM emits one complete, direct
   `agentlas.workforce-work-order.v1` object.
2. The typed host adapter type-checks that object and invokes the fixed
   `workforce.search_candidates` tool with the WorkOrder unchanged. It may
   reject an incomplete object, but it must not normalize fields, insert
   defaults, or add, remove, or relax requirements.
3. `workforce.search_candidates` returns a selection session, ontology version,
   candidate-set digest, role-slot cards, and coverage gaps.
4. When bounded coverage-gap codes show an unfilled role slot, the same active
   host LLM may emit a refined, complete, direct WorkOrder whose only new input
   is those codes, then the adapter repeats `workforce.search_candidates`. The
   refined WorkOrder and repeat search remain auditable and must retain the
   ontology version and redaction boundary. The host LLM may correct an
   exclusion it previously inferred when a gap code exposes that conflict, but
   it must preserve every prohibition explicitly stated by the user. The typed
   adapter may validate this distinction but must not rewrite either class.
5. The host LLM emits one direct `agentlas.workforce-selection.v1` object with
   assignments, collaboration/handoff edges, alternatives considered, and
   short reason codes.
6. The adapter invokes `workforce.validate_selection` with the exact WorkOrder,
   candidate set, and Selection. Only after acceptance does it invoke
   `workforce.prepare_execution` with those same objects and the validation
   receipt.
7. The validator confirms provenance, hard eligibility, required coverage,
   cycles, cardinality, and candidate-set membership. It validates; it never
   chooses.
8. Preparation resolves exact immutable BYOM releases and returns separate
   `idealTeam`, `executableTeam`, `unfilledPosts`, and `substitutions`.
   Substitution requires another host-LLM decision.
9. The execution fabric emits manager, worker, handoff, synthesis, verifier,
   and completion receipts.

The host LLM is never asked to wrap either direct object in a ceremonial MCP or
JSON-RPC tool-call envelope. Tool names and transport arguments are fixed by
the typed adapter. This keeps staffing semantics with the host LLM while
avoiding extra JSON nesting that is especially fragile for smaller local
models.

Every accepted selection states `decisionAuthor.kind = host_llm` and records
the host model identifier, candidate-set digest, ontology version, and selected
release IDs. Raw prompts and private context are forbidden in the receipt.

The three callable Hub MCP tools are therefore exactly:

```text
workforce.search_candidates
workforce.validate_selection
workforce.prepare_execution
```

`workforce.search_candidates` is content-only and read-only. A bounded replay
after an ambiguous transport response reuses the exact WorkOrder arguments and
deterministic selection-session material, and every attempt is audited. The
transport-level JSON-RPC request ID need not be reused. Such a replay must not
fabricate or relax the WorkOrder. `workforce.validate_selection` and
`workforce.prepare_execution` are never replayed automatically; ambiguous
outcomes fail closed and require an explicit host-controlled recovery flow.

There is deliberately no `workforce.pick_best`. Candidate retrieval may be
implemented deterministically, but final staffing belongs to the active host
LLM. Preparation fails closed if any selected release, package hash, content
digest, entitlement, or callable overlay has changed.

## Lifecycle and projection

Public staffing state changes only through idempotent events:

```text
definition.created
release.published
release.superseded
release.withdrawn
release.restored
release.deleted
ontology.version.published
projection.rebuilt
```

Editing a draft has no public effect. Publishing an edit creates a new immutable
release, compiles a new profile, updates the active head, and supersedes the old
release atomically. Delete creates a tombstone; it never erases receipt
lineage. Replaying the event log must reproduce the same active heads, nodes,
edges, and candidate-set digests.

Embedding generation is asynchronous and versioned. A missing or stale vector
must not make a release unsearchable; exact, lexical, and graph retrieval remain
available. Re-indexing is idempotent and projection lag is observable.

## Storage decision

MongoDB remains the Web/Hub source of truth because Agentlas already relies on
its ownership, release, billing, and transaction boundaries. It stores immutable
releases, lifecycle events, ontology nodes/edges, projection heads, and
short-lived selection sessions. MongoDB supports recursive `$graphLookup` and
pre-filtered `$vectorSearch`, but it is not an ontology reasoner or a dedicated
graph database.

The graph/vector layer is therefore a rebuildable projection behind a store
interface. The first production implementation uses Mongo collections plus
Atlas Search/Vector Search and bounded application-side graph expansion. This
avoids a dual-write authority split. A Neo4j/Aura read projection becomes
appropriate only when measured catalog size, path depth, or p95 query latency
exceeds a recorded migration threshold. Mongo remains the release/event
authority even then.

Local Core uses JSONL/SQLite-compatible projections and the identical public
contracts; it never receives hosted account, billing, credential, or private
workspace state.

## Required evaluation

Routing quality and execution quality are separate suites.

Routing suite:

- Zero-History Optimal Top-1 and Top-K recall;
- popularity/history permutation invariance;
- mandatory role, skill, tool, artifact, and authority recall;
- excluded-department intrusion (for example travel in a coding TF);
- candidate-order permutation stability of the host-LLM decision;
- add/edit/supersede/withdraw/delete/rebuild correctness;
- multilingual alias, open-world, and ontology-version drift cases;
- ideal-versus-executable team gap and explicit substitution behavior.

Execution suite:

- distinct top-level leader, packaged manager, worker, synthesis, and verifier
  invocations;
- exact BYOM release and tool/permission binding;
- artifact handoff and dependency validation;
- bounded retry and independent task verifier;
- Qwen and a frontier model under the same safe, difficult benchmark harness;
- no architecture-success claim when only a route, bundle, overlay, or process
  exit is observed.

## Release gates

A release may claim Agent Workforce Ontology support only when:

- the public schemas and lifecycle replay pass;
- Hub MCP returns content-only candidate sets with no history contribution;
- a host LLM produces and validates a multi-role selection;
- at least one real multi-agent run emits joined selection, worker, handoff,
  verifier, and completion receipts;
- cross-platform contract fixtures match in Core, Web, Desktop, Terminal, and
  AppBridge;
- the cold-start, poison, difficult benchmark, and Qwen comparison gates pass.
