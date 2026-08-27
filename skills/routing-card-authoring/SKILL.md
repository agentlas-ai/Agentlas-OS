---
name: routing-card-authoring
description: "Use whenever a build emits or repairs .agentlas/routing-card.json — the shared card contract for the single-agent builder, the team builder, and the packager. States what belongs in every field, which fields the hub can actually match on, and which fields silently break matching when a sentence leaks into them."
---

# Routing Card Field Spec — what goes in every field, and where it lands

One card, four builders. `10-single-agent-builder`, `20-multi-agent-team-builder`,
`30-agentlas-packager`, and `40-session-agent-builder` differ in what they
assemble, but the routing card is the same artifact with the same rules in all
four. This file is the reference
they share, and `templates/routing-card.example.json` is a complete card that
passes `schemas/routing-card.schema.json`.

## Why the fields behave the way they do

Every rule below was measured against the live corpus on 2026-07-30
(492 workforce profiles, 253 stored manifests). The two facts that decide
everything else:

1. **Only two columns can be compared between a work order and a card.**
   `communities` (422 of 492 populated, 105 distinct) and `skills` (492 of 492,
   1,969 distinct). Everything else is either declared by almost nobody
   (`roles` 6, `tools` 10, `knowledge` 0, `forbiddenAuthorities` 0), or declared
   by everyone with the same value (`runtimes` 14 distinct over 492 profiles,
   `languages` exactly 2, `modalities` exactly 1) — neither can separate
   candidates.
2. **The real matching is sentence-to-sentence.** The slot's `task` text is
   compared semantically against the card's `summary`. A card whose summary
   names its actual deliverable outranks a card with a perfect id list.

So the card has two jobs, and mixing them is the classic defect: **short ids
for retrieval, whole sentences for judgement.** A sentence that leaks into an
id field becomes a slug nothing else can ever match — measured: 8,973 distinct
`outputs` values across the corpus, 0% shared by two agents.

## Field table

Columns: what the field is for · what the hub does with it · what to write.

### Identity and display

| Field | Hub use | What to write |
|---|---|---|
| `schemaVersion` | none | Exactly `"routing-card/2.0"`. |
| `card_version` | none | Semver of this card's content, bumped when you edit it. |
| `id` | identity | `local/<package-slug>` before upload. |
| `canonical_id` | identity | Stable cross-registry id when one exists, else omit. |
| `type` | hard filter (`entityKind`) | `"agent"`, `"team"`, or `"plugin"`. A team means an orchestrator owns workers; do not label a single worker a team. |
| `name` / `name_ko` | display + lexical retrieval | The job title a human would search for. Not a product pun. |
| `aliases` | lexical retrieval | Other phrasings a requester might type, including Korean. Cheap and safe to add. |
| `supersedes` | lineage | Ids this card replaces. |

### The sentences that actually win matches

| Field | Hub use | What to write |
|---|---|---|
| `summary` (≤240 chars) | **semantic ranking against the slot task** — the single highest-value field | One sentence: what it does, what the requester ends up holding, and the one boundary that matters. Name the deliverable in the words a requester would use. Do not list technologies for their own sake. |
| `summary_ko` | display + Korean retrieval | Faithful Korean of `summary`. |
| `description` | semantic ranking | 2–4 sentences: when to use it, what the deliverable contains, and what it explicitly does not do. This is where "does not implement" or "does not run migrations" belongs. |
| `trigger_examples` | semantic ranking (strong) | 6+ real sentences a requester would actually type, 3 Korean and 3 English. Write the request, not a feature name. |
| `anti_triggers` | negative ranking | 4+ sentences that look adjacent but must NOT route here. This is how a design agent stops absorbing implementation work. |
| `known_failure_cases` | honesty, read by the host LLM | What the agent degrades to when an input is missing. Sentences, whole. |

### Short-id fields (open semantic concepts — never sentences)

| Field | Hub use | What to write |
|---|---|---|
| `capabilities` | → `skills` column, lexical + semantic retrieval | 4–8 ids in `verb_object` snake_case (`design_backend_services`). Schema enforces the pattern. These become open `skill:*` graph concepts. Seed aliases may normalize familiar terms, but no finite list owns what an agent is allowed to know or do. |
| `domains` | lexical retrieval | 2–5 broad area words. |
| `required_inputs` / `optional_inputs` | compatibility display | Canonical interfaces live in `contracts/intake.schema.json`. Only stable `name`/`id` values may project to ontology IDs; descriptions and JSON types never do. |
| `input_notes` | not read by matching | Free-text lines explaining each input, for humans and for the executing model. |
| `consumes` / `produces` | compatibility display | Canonical interfaces live in `contracts/intake.schema.json` and `contracts/output.schema.json`. When present, use short stable `kind` IDs only. |
| `supported_runtimes` | packaging metadata | Do not emit it as agent identity. Runtime adapters and prepare-time execution policy own compatibility. |
| `required_plugins` | → `tools` column | `{id, min_permissions}` for a facility the worker itself must invoke. Almost no card declares tools; state the requirement vendor-free and keep the package usable without it. |

### The workforce block — open-world semantic résumé fields

`workforce` is defined in `schemas/routing-card.schema.json` and is what the hub
reads. The snapshot `agentlas_cloud/workforce/ontology_v1.json`
(`awo:2026-07-15.2`) supplies seed aliases, parent relations and compatibility
mappings. It is not an allowlist. When no seed concept fits, author a faithful
English namespaced ID; the Hub embeds it and connects it to the ontology graph.

| Field | Hub use | What to write |
|---|---|---|
| `workforce.communities` | semantic scope + strong ranking signal | 1–5 open `community:*` professional-domain ids. Reuse a seed alias when it fits; otherwise author the real community. |
| `workforce.skills` | semantic ranking | 3–12 open `skill:*` verb-object capability ids that actually distinguish this agent. They are not a fixed dictionary. |
| `workforce.knowledge` | ranking | `knowledge:*` ids. You may omit it: the compiler now derives one id per `knowledge/*.md` file the package ships (file stem → `knowledge:<stem>`), which is why the column existed with 0 producers until 2026-07-30. |
| `workforce.roles` | semantic ranking | 0–4 open `role:*` professional-responsibility ids. `[]` is honest when the card already expresses the work better through its summary and skills. |
| `workforce.languages` | delivery metadata, never an identity/callability gate | Languages the work product can genuinely be delivered in. Listing translation does not count. `[]` is allowed when unknown. |
| `workforce.modalities` | runtime/input metadata, never an identity/callability gate | Declare only non-text media the agent genuinely consumes or emits. Ordinary text reasoning may use `[]`. |

### Safety, cost and operations (not matching inputs)

| Field | Hub use | What to write |
|---|---|---|
| `risk_profile.tier` | display, governance | `low` / `medium` / `high`. |
| `risk_profile.capabilities_at_risk` | display, governance | Enum: `file_write`, `cloud_call`, `payment`, `publish`, `delete`, `private_data_export`, `external_tool`. It never becomes semantic authority identity. |
| `approval_requirements` | → `authorities` column | Same vocabulary; what a human must approve. |
| `approval_scope` | runtime policy | `{grant, ttl_seconds}`. |
| `memory_behavior` | runtime policy | `{reads, writes, exports_to_cloud}` — required object. |
| `data_access` | runtime policy | `{reads, writes, exports}` path classes. |
| `cloud_delegation_policy` | runtime policy | `never` / `ask` / `allowed_with_grant`. |
| `cost_hints` | display | `{model_calls, paid_api}`. |
| `entrypoints` | execution | `{canonical_command, agent, terminal}`. |
| `benchmark_fixtures` | quality | Path to `.agentlas/routing-benchmarks.jsonl`. |
| `locale_coverage` | display only | `{primary, ready, partial}` for marketplace copy. It must never project into workforce languages. |
| `routing_status` | **gate** | `draft` → `searchable` → `candidate` → `routing_ready` → `trusted`. Only a card with real triggers, a real summary and a filled workforce block should claim `routing_ready`. |
| `routing_status_reason` | gate | Why it is not ready, when it is not. |
| `card_quality_score`, `quality`, `integrity`, `source`, `stale`, `updated_at`, `agent_card_ref` | pipeline-owned | Leave to lint, publish and the hub. Do not hand-author scores. |

## Checklist a builder can run

1. `summary` names the deliverable in a requester's words, under 240 chars.
2. 6+ `trigger_examples` (3 ko / 3 en) and 4+ `anti_triggers`, all real sentences.
3. `capabilities`: 4–8 `verb_object` ids, checked against community aliases for
   accidental pulls (`contract` → legal, and similar).
4. **No `description` inside `required_inputs`, `optional_inputs`, `consumes`
   or `produces`.** Explanations go in `input_notes` / `description` /
   `known_failure_cases`.
5. `workforce.communities`, `skills`, `roles`, and `knowledge` use stable open
   English IDs. Seed aliases are reusable examples, never an allowlist.
6. `risk_profile.capabilities_at_risk` lists only real risks.
7. `routing_status` is honest.
8. Validate: the card parses against `schemas/routing-card.schema.json`.

## Verified end to end

`templates/routing-card.example.json` was compiled through the live hub
compiler (`compileExactOwnerPrivateWorkforceProfile`) on 2026-07-30. Result:

```
communities  [4] backend-engineering, database-engineering, legal*, software-engineering
skills       [9] api-design, software-architecture, data-modeling + 6 from capabilities
knowledge    [2] api-contract-checklist, database-schema-patterns   (from knowledge/*.md)
inputs       [5] requirement-brief, load-profile, service-context, stack-constraints, text*
outputs      [3] api-contract, data-model, decision-record
runtimes     [4] claude-code, codex, gemini-cli, terminal
languages    [2] en, ko          modalities [1] text
roles        [2] backend-engineer, software-architect
authorities  [1] file-write      forbiddenAuthorities []
```

The same card written with sentences inside `produces`/`required_inputs`
produced `outputs [6]` and `inputs [10]` full of unmatchable slugs like
`artifact:architecture-decision-record-naming-the-chosen-component-boundaries-and-…`.
That is the difference this spec exists to hold.

Two known compiler leaks are visible above and are not the author's fault:
`legal*` (community alias "contract review") and `artifact:text*` (the `type`
value of an input becoming a concept). Fix them in the compiler, not by
contorting the card.
