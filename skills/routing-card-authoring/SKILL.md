---
name: routing-card-authoring
description: "Use whenever a build emits or repairs .agentlas/routing-card.json — the shared card contract for the single-agent builder, the team builder, and the packager. States what belongs in every field, which fields the hub can actually match on, and which fields silently break matching when a sentence leaks into them."
---

# Routing Card Field Spec — what goes in every field, and where it lands

One card, three builders. `10-single-agent-builder`, `20-multi-agent-team-builder`
and `30-agentlas-packager` differ in what they assemble, but the routing card is
the same artifact with the same rules in all three. This file is the reference
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

### Short-id fields (retrieval vocabulary — never sentences)

| Field | Hub use | What to write |
|---|---|---|
| `capabilities` | → `skills` column, lexical + semantic retrieval | 4–8 ids in `verb_object` snake_case (`design_backend_services`). Schema enforces the pattern. These become `skill:*` ids even when they are not in the pinned ontology — that is intended for retrieval, and it is why the corpus has 1,969 distinct skills. **Beware alias collisions**: `community:legal`'s alias list contains "contract review", so `author_api_contracts` pulled `community:legal` onto a pure backend card in a measured run. Prefer the plainest domain verb. |
| `domains` | lexical retrieval | 2–5 broad area words. |
| `required_inputs` / `optional_inputs` | → `inputs` column | `{name, type}` only. **Do not write `description` here** — the compiler feeds `name`, `type`, `id` and `description` all into the id field, so one sentence becomes one unmatched slug (and `type: "text"` becomes `artifact:text`). Put the explanation in `input_notes`. |
| `input_notes` | not read by matching | Free-text lines explaining each input, for humans and for the executing model. |
| `consumes` | → `inputs` column | `{kind, required}` only, `kind` in short snake_case (`requirement_brief`). No description. |
| `produces` | → `outputs` column | `{kind, path_hint}` only, `kind` in short snake_case (`decision_record`, `api_contract`, `data_model`). No description. Prefer the 7 published artifact ids when one fits: `api-spec`, `codebase_change`, `decision-record`, `source-code`, `team-result`, `worker-result`, `unavailable-deliverable`. |
| `supported_runtimes` | → `runtimes` column | Which adapter files the package actually ships. Note: this is packaging metadata, not capability, and 14 distinct values across 492 profiles means it separates almost nothing — fill it truthfully and expect no ranking benefit. |
| `required_plugins` | → `tools` column | `{id, min_permissions}` for a facility the worker itself must invoke. Almost no card declares tools; state the requirement vendor-free and keep the package usable without it. |

### The workforce block — the only fields a work order can hard-match

`workforce` is not yet in `schemas/routing-card.schema.json` (it passes because
`additionalProperties: true`) but it IS what the hub reads. Use ONLY ids from
the pinned ontology `agentlas_cloud/workforce/ontology_v1.json`
(`awo:2026-07-15.2`). An invented id is silently unmatchable.

| Field | Hub use | What to write |
|---|---|---|
| `workforce.communities` | **hard match + strongest ranking weight** | 1–3 `community:*` ids from the 25 published. The job family boundary. Get this right before anything else — it is the one axis that both sides populate. |
| `workforce.skills` | ranking | 2–4 `skill:*` ids from the 23 published, when one genuinely fits. Free-form expertise stays in `capabilities`. |
| `workforce.knowledge` | ranking | `knowledge:*` ids. You may omit it: the compiler now derives one id per `knowledge/*.md` file the package ships (file stem → `knowledge:<stem>`), which is why the column existed with 0 producers until 2026-07-30. |
| `workforce.roles` | ranking | 0–2 `role:*` ids from the 15 published, only when the agent truly performs that professional role. `[]` is honest and common (6 of 492 declare any). |
| `workforce.languages` | ranking | Languages the work product can be produced in, from the 13 public ids. |
| `workforce.modalities` | ranking | `text` unless it genuinely consumes or emits image/audio/video. |

### Safety, cost and operations (not matching inputs)

| Field | Hub use | What to write |
|---|---|---|
| `risk_profile.tier` | display, governance | `low` / `medium` / `high`. |
| `risk_profile.capabilities_at_risk` | ⚠️ **leaks into the `authorities` column** | Enum: `file_write`, `cloud_call`, `payment`, `publish`, `delete`, `private_data_export`, `external_tool`. Declare only what the agent really does. This is the honest source of the 230 distinct `authorities` values in the corpus — the column is a risk echo, not a permission grant, and search no longer hard-filters on it (2026-07-30). |
| `approval_requirements` | → `authorities` column | Same vocabulary; what a human must approve. |
| `approval_scope` | runtime policy | `{grant, ttl_seconds}`. |
| `memory_behavior` | runtime policy | `{reads, writes, exports_to_cloud}` — required object. |
| `data_access` | runtime policy | `{reads, writes, exports}` path classes. |
| `cloud_delegation_policy` | runtime policy | `never` / `ask` / `allowed_with_grant`. |
| `cost_hints` | display | `{model_calls, paid_api}`. |
| `entrypoints` | execution | `{canonical_command, agent, terminal}`. |
| `benchmark_fixtures` | quality | Path to `.agentlas/routing-benchmarks.jsonl`. |
| `locale_coverage` | → `languages` column | `{primary, ready, partial}`. This is listing-translation coverage, and it is why `languages` holds exactly `en`/`ko` corpus-wide. |
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
5. `workforce.communities` is 1–3 pinned ids and is the job family, not a wish.
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
