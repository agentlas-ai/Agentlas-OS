# Agent Experience Asset Contract

Agentlas separates the agent a creator ships from the experience a user earns
while operating it. The portable contract is:

```text
AgentDefinition release + ExperiencePack release = AgentVariant binding
                                      |
                                      +-> RunReceipt evidence
```

The Career Graph may index the receipts, failures, recoveries, and relations,
but it is a rebuildable local index. The user-owned, versioned asset is the
Experience Pack. A graph projection is never the only copy of an experience and
never becomes publishable merely because an LLM inferred an edge.

## Derived Experience Relation Index

Experience ownership and Experience retrieval are separate concerns. The
owned assets remain `ExperiencePack`, `ExperienceItem`, and their evidence
receipts. A relation graph is only a disposable local index over those assets.

The canonical value-free lineage file is:

```text
.agentlas/experience-relations.jsonl
```

Each line follows `schemas/experience-relation-lineage.schema.json`. It may
contain exact asset IDs, exact base-release hashes, hashed project/environment
scope keys, safe task tags, MCP catalog IDs, evidence receipt IDs, and release
lineage. It must never contain an Experience summary or instruction, raw
prompt/transcript, local path, URL, account identifier, secret, credential,
or base-package bytes.

Desktop-local `releaseId` values identify a deterministic relation snapshot;
they do not replace the immutable Experience release identity issued by the
Hub. Relation fingerprints intentionally exclude summary/instruction content
hashes, so low-entropy private text cannot be guessed from this safe lineage
projection. The owned Experience asset remains the content authority.

`career-graph ingest` derives pack-scoped nodes for Pack, Release, Item,
TaskTag, Environment, MCPRequirement, and EvidenceReceipt, plus these useful
relations:

- `exact_base_binding`
- `contains`
- `applies_to_task`
- `applies_in_environment`
- `requires_mcp` / `supports_mcp` / `alternative_mcp`
- `supported_by`
- `supersedes`
- deterministic `similar_by_tag` only inside one Pack release

The index is never an owned or uploaded asset. It may be deleted and rebuilt.
Invalid lineage lines produce a redacted rejection marker rather than copying
their raw payload into the graph. A missing or stale index must fall back to
the canonical Experience records; it must not widen project, environment,
base-release, or Pack scope.

The lineage JSONL is also not AgentDefinition package material. Agentlas source
hashing, Cloud/Hub upload, and Desktop package collection must exclude it so a
user's local Experience history cannot change or leak through the base-agent
artifact. Only the separately sanitized aggregate
`.agentlas/public-career-card.json` may accompany a base package. That base
card excludes Experience-lineage source, node, and edge counts; Experience
reputation and relations belong to the separately uploaded Experience asset.

## Asset Boundaries

## Canonical Wire Conventions

All Web, Desktop, Terminal, and public-core adapters use the following wire
rules. Product stores may normalize them internally, but cross-surface receipts
must return these names and values:

- JSON fields use `camelCase`; enum values use lowercase kebab-case.
- `schemaVersion` is one of the exact `agentlas.<contract>.v1` constants.
- IDs are opaque strings. Consumers compare them exactly and never derive
  ownership or compatibility by parsing a slug or semantic version.
- `agentDefinitionId` is the stable base identity. `releaseId` is an immutable
  materialization of that identity. `version` is display/release metadata, not
  an automatic compatibility range.
- Release references always use `baseAgentReleaseId` or
  `experiencePackReleaseId`; `latest`, same-major, and semver-range matching are
  forbidden in V1 compatibility claims.
- Content hashes use lowercase `sha256:<64 hex>` over UTF-8 canonical JSON
  (`sort_keys=true`, compact separators) or the existing canonical package-hash
  algorithm. Bare hex hashes are accepted only by legacy import adapters and
  are normalized before entering this contract.
- `ExperiencePack.contentHash` covers the canonical promoted item payload and
  MCP requirements, sorted by stable item/requirement id; the manifest hash
  field itself is excluded.
- `AgentVariant.bindingHash` covers exactly
  `{baseAgentReleaseId, experiencePackReleaseId}`.
- `RunReceipt.receiptHash` covers the full canonical receipt except
  `receiptHash` and `signature`.
- Times are RFC 3339 UTC strings. `null` means intentionally absent; an omitted
  required field is invalid.

Although the public name is `AgentDefinition`, its schema represents one
immutable release materialization. Agentlas Web may keep a stable definition
row and separate release rows; the wire object carries both ids so the split is
never lost. `status: draft` is a pre-registration projection with a provisional
release id; it cannot be published, rented, ranked, or cited as immutable
evidence. Once materialized as `active`, that release id and package hash never
change.

### Local source hash and published artifact hash

Newly generated manifests declare
`packageHashVersion: agentlas-package-hash/v2`. This local source hash v2 hashes sorted normalized
package paths plus their exact UTF-8 materialized bytes, prefixed internally by
the hash-version marker. It excludes only mutable wizard evidence:

- `agentlas.json`;
- `.agentlas/security-scan.json`;
- `.agentlas/security-llm-judgment.json`;
- `.agentlas/field-test-report.json`.

`.agentlas/mcp-policy.json` remains included because changing tool capability,
permission, or fallback intent changes the executable base release. Runtime
memory, Experience Packs, and RunReceipts are separate overlays/assets and are
not silently merged into a published base release.

The source hash answers “did executable package intent change before delivery?”
It is not the Agent Cloud bundle identity. Upload keeps the existing
`path-sha256-executable-v2` artifact contract: sorted portable path, per-file
SHA-256, and executable bit. Mutable local scan, LLM-judgment, and field-test
files are not delivered; server review evidence is stored outside the package.

Local manifests encode their source hash as `sha256:<hex>`. Cloud upload keeps
its API-compatible bare-hex artifact hash. For a sanitized public upload, the
delivered bytes and executable flags are authoritative; the registered
AgentDefinition `packageHash` is `sha256:` plus that Cloud artifact hash. Thus a
source hash and an artifact hash are deliberately not compared as equal. The
exact hash-version field must travel with each value, and neither value may be
silently reinterpreted as the other. Manifests without a source hash version
remain legacy local v1 and require explicit migration.

### AgentDefinition

`AgentDefinition` identifies one immutable base-agent release. Its package hash,
entrypoint, capabilities, MCP policy reference, author, visibility, lifecycle,
and third-party experience policy are explicit. Publishing a new base version
creates a new `releaseId`; it never changes an existing release in place.

The full server resource follows
`schemas/agent-definition.schema.json`. Generated packages keep their existing
`agentlas.json`, `.agentlas/agent-card.json`, and
`.agentlas/routing-card.json` files. `agentlas.json.assetContract` announces the
resource type, while Agent Cloud or Hub materializes the server-authoritative
`agentDefinitionId`, `releaseId`, and package hash during registration. This
avoids a circular package hash and does not create a second competing package
manifest.

### ExperiencePack

`ExperiencePack` is owned by the user who accumulated and curated the
experience. That owner may differ from the base agent's author. The pack names
one base definition and an explicit list of compatible base release ids. A
version range, latest tag, slug, or package name is not an exact compatibility
claim.

An Experience Pack contains only experience deltas:

- promoted procedures;
- verified failure recovery;
- environment-specific gotchas;
- useful tool affordances;
- warnings and supersession links;
- public-safe RunReceipt references.

It must set `containsBasePackageMaterial: false`. Base prompts, skills, package
files, raw transcripts, raw user prompts, customer data, local absolute paths,
and credential values are forbidden. Public upload uses an allowlisted,
redacted projection; local diagnostic evidence stays local.

### ExperienceItem

An item starts as `candidate`. Memory Curator or another declared verifier may
promote it after evidence review. Public packs contain promoted, public-safe
items only. Conflicting items are linked or superseded; they are not silently
overwritten.

The runtime retrieves items locally by task and environment. It may select at
most eight items and must keep the total experience projection at or below 800
tokens. The full pack is never injected into a model prompt.

### AgentVariant

`AgentVariant` is a references-only binding:

```json
{
  "baseAgentReleaseId": "agent:sns:release:2.1.0",
  "experiencePackReleaseId": "experience:mason-sns:release:1.0.0",
  "compositionMode": "references-only"
}
```

V1 binds exactly one base release and one experience release. It does not copy
either asset. The deterministic `bindingHash` hashes only those two release
ids. The binding does not transfer ownership of the base package to the
experience owner.

### TasteStyleRelease

Creative work has a separate ontology-chip contract because “the command ran”
does not mean “people preferred the result.” `TasteStyleRelease` stores only
generalized composition, color, typography, motion, pacing, density, imagery,
editing, or spatial-rhythm preferences. It pins exact compatible base releases
and may refer only to preview assets whose public rights and safety review have
passed. It never carries private image/video bytes, embeddings, local paths,
raw outputs, prompts, credentials, or rater identities.

Official evidence comes from `PairwisePreferenceReceipt`. Each receipt records
a randomized left/right comparison, an explicit human choice (including tie or
skip), a hashed anti-Sybil principal, and privacy-safe context tags. An LLM
aesthetic judgment cannot set `source: human` and cannot enter the official
aggregate. Stores must reject duplicate receipt ids, idempotency keys, and
receipt hashes.

Hub surfaces show the rule-aligned count, alternative count, ties, skips,
sample count, distinct raters, and disagreement separately. The contract has no
`successRate`, universal aesthetic score, or blended Experience/Taste ranking.
Small samples remain visibly uncertain instead of displaying a confident 100%.

### AgentLoadout

The user-facing “chip attachment” is an `AgentLoadout`, not a rewritten Agent
package:

```text
exact AgentDefinition release
  + zero or one ExperiencePack release
  + zero or one TasteStyleRelease
  = references-only AgentLoadout
```

At least one chip reference is required. Attachment always carries an explicit
user-consent receipt, activates on the next session, and leaves permission
widening in `ask` mode. Each chip chooses `pinned`, `manual`, or
`verified-compatible` update behavior. Even the last policy may update only to
a verifier-approved release for the same exact base release; it is never a
same-major or “latest” wildcard. A failed update keeps the last known-good
binding, while a security revocation takes precedence and makes the affected
chip dormant or revoked without disabling the base agent.

## RunReceipt And Verified Success

A `RunReceipt` records a privacy-safe task signature, exact asset releases,
environment fingerprint, selected MCPs, triggered skills, model id, outcome,
verification, token use, duration, retries, and side effects.

`metricsEligible: true` is valid only when all of the following hold:

1. the run succeeded;
2. verification verdict is `pass`;
3. method is `automated`, `human`, or `third-party`;
4. the verifier is identified;
5. the receipt has not been accepted before.

Self-report and unverified success may remain in private history but do not
change official success ranking. A receiving store must put unique indexes on
`receiptId`, `idempotencyKey`, and `receiptHash`. The portable
`ReceiptReplayGuard` defines the same duplicate behavior without prescribing a
Web or local database.

The receipt hash is SHA-256 over canonical JSON with `receiptHash` and
`signature` omitted. Portable `RunReceipt` v1 keeps `signature` null-only until
Agentlas defines a verifiable algorithm, key-id, encoding, and trust-root
contract. An arbitrary signature-shaped object is not authority and is not an
escape hatch for prompts, paths, or credentials. A registry may store a
separate server-side attestation over the receipt hash; that attestation still
does not authorize secret or raw-data export.

## Rental Resolution

Resolver ranking is task-specific. A raw global star rating is not sufficient.
Each candidate records:

- conservative verified task success and verified sample size;
- environment and MCP compatibility;
- recency and reputation;
- token, latency, and cost efficiency;
- adverse-effect and staleness penalties.

Use a conservative lower-bound method such as Wilson or a beta-posterior lower
bound so two successes do not rank above a well-tested candidate merely because
they display 100%. The receipt stores the scoring-policy version, all candidate
exclusions, selected variant, and ordered fallbacks.

`selectedVariantId` records the chosen candidate separately. `fallbackOrder`
contains only candidates whose decision is `fallback`, in retry order;
selected, excluded, and unevaluated ids are forbidden. A selected result with
no fallback and an empty `base-only` result both use `fallbackOrder: []`.

If a required MCP or required key is absent, exclude only that variant and
continue evaluating the next candidate. If no variant is compatible, the
resolver may explicitly return `base-only` or `no-compatible-variant`; it must
not fabricate a successful rental.

The portable RentalResolutionReceipt intentionally has no client-supplied
signature field. Web may store authenticated resolver authority separately in
its server-owned receipt envelope; clients cannot create that authority by
adding a signature-shaped object.

## Ownership And Lifecycle

- Agent author and Experience Pack owner are independent principals.
- Uploading a pack does not grant source-download rights to the base package.
- A base update creates a new release; old packs require explicit revalidation.
- When a base definition is deleted, its pack remains owned, while bindings
  become dormant.
- When a pack is withdrawn, new rentals stop. A security withdrawal may revoke
  active use immediately; ordinary withdrawal follows the recorded lease rule.
- Delete, suspend, withdraw, and unpublish are tombstoned state transitions so
  receipts remain auditable.
- Public Agent upload, Experience Pack upload, and Variant binding are separate
  operations and separate receipts. Failure in one does not roll back a
  previously completed operation in another.

## Backward Compatibility

Existing packages without these contracts remain valid. Importers may create a
legacy AgentDefinition projection from the existing package id and hash, but
must not invent an Experience Pack or claim verified success. Existing
`requiredMcp` lists may be migrated into catalog requirements; ambiguous legacy
`mcpServers` entries default to optional so migration does not unexpectedly
block an agent. A package without an Experience Pack runs as a base agent and is
reported as such.

## Portable Experience Bundle v1

`*.agentlas-experience.json` carries only Experience content. It references one
exact base release and never embeds a base package, prompt, transcript, local
path, credential, MCP command/arguments, Variant, or derived relation index.

The canonical wire implementation is
`agentlas_cloud/portable_experience_bundle.py`. It normalizes every string to
NFC, serializes finite JSON numbers with ECMAScript-compatible `-0` and integer
float handling, sorts object keys by Unicode code point, preserves ordered
instructions, and sorts/deduplicates set-like arrays. The shared Python/TypeScript
golden includes decomposed Korean, emoji, Windows-safe backslashes, `1.0`,
`0.5`, and `-0.0`.

Public-safe items and Portable bundles share the deterministic
`agentlas.experience-privacy.v1` boundary. It blocks arbitrary POSIX absolute
paths, any Windows drive path, UNC paths, `~/`, `file://`, relative traversal
(including percent-encoded traversal), email, phone, labeled tenant/workspace/
account/customer/user/client identifiers, IP addresses, and UUIDs. It masks
public `https://` links and the exact `$PROJECT_ROOT` / `$OUTPUT_DIR`
placeholders before path scanning, so normal `input/output` prose is not a
false positive. Exact hashes, canonical asset IDs, receipt IDs, timestamps, and
MCP `setupUrl` values receive exemptions only in their explicit metadata
fields. The shared Python/TypeScript cases are maintained in the private
cross-surface verification suite and are not part of the installable package.

This is a deterministic guard, not full de-identification. Unlabeled names,
postal addresses, uncommon international phone forms, novel encodings, and
indirect identifiers can evade it; publishing still requires curation and
server-side review. Conversely, unusual prose that looks exactly like a host
path or identifier is intentionally rejected and must be rewritten.

Storage is capped at 256 items, 64 MCP requirements, 24 evidence refs per item,
8 instructions per item, 32 task signatures per item, and 3 MiB of canonical
JSON. These storage limits never expand runtime context: retrieval remains a
shared maximum of 8 items and 800 estimated tokens.

Ingest replaces the submitted owner with the authenticated owner, validates the
exact server-stored Cloud artifact and package hash, and commits an owner-private
draft. User attestations remain private history and never become evaluator
verification or rental reputation. The first create uses `If-None-Match: *`;
same idempotency key and bundle hash returns the same receipt, while a different
hash conflicts. Withdrawal changes lifecycle availability only; immutable
bundle bytes, release, items, and receipts remain auditable.

Base-resolution and upload-receipt wire responses use one forward-compatible
`schema` discriminator. The owned Experience bundle itself retains the stricter
`schemaVersion` plus `kind` envelope.

### Activation taxonomy v1

Portable v1 keeps its existing public-ID wire shape, while activation is
stricter than storage. Only `agentlas.task.v1/<slug>` values from the frozen
catalog in `agentlas_cloud/experience_taxonomy_v1.json` can affect ranking or
runtime selection. Runtime profiles map an exact catalog slug or canonical ID;
there is no fuzzy match and no `general` fallback.

Environment constraints use only `agentlas.env.v1/os/<os>`,
`agentlas.env.v1/arch/<arch>`, and `agentlas.env.v1/runtime/<runtime>`. Every
declared constraint must match the actual execution environment. Unknown legacy
task or environment values remain storable for migration, but make only that
item/variant ineligible; the exact base agent remains available.

## Schema Set

- `schemas/agent-definition.schema.json`
- `schemas/experience-pack.schema.json`
- `schemas/experience-item.schema.json`
- `schemas/experience-bundle.schema.json`
- `schemas/experience-upload-receipt.schema.json`
- `schemas/experience-base-resolution.schema.json`
- `schemas/agent-variant.schema.json`
- `schemas/run-receipt.schema.json`
- `schemas/rental-resolution-receipt.schema.json`
- `schemas/mcp-requirement.schema.json`
- `schemas/mcp-policy.schema.json`

The schemas are portable interfaces. Hosted account storage, database indexes,
billing, revenue splits, moderation, and lease charging stay in Agentlas Web.
SQLite, Keychain, system MCP discovery, and GUI state stay in Desktop or the
independent Terminal.
