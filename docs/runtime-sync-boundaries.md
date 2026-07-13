# Runtime Sync Boundaries

This document explains what belongs in this public core repo, what belongs only
in hosted web products, and what belongs only in local desktop or terminal
runtimes.

The public core repo is meant for people who download an open-source Agentlas
meta-agent team and use it anywhere: Codex-compatible apps, Claude-compatible
apps, Gemini-style CLIs, Hermes-style local runtimes, OpenClo or Antigravity
style tools, Cursor-like editors, and any runtime that can read `AGENTS.md`.

## Public Core

Public core owns the portable contract:

- the three modes: `single-agent-creator`, `team-builder`,
  `agentlas-packager`;
- visible package foldering;
- `.agentlas` contracts;
- local credential store contract for gitignored `.env`, `signing/`, and
  `credentials/` materialization, plus value-free borrowed-agent credential
  request metadata such as provider, env name, allowed host, scope, and broker
  mode;
- AgentDefinition, ExperiencePack, ExperienceItem, AgentVariant, RunReceipt,
  RentalResolutionReceipt, MCPRequirement, and value-free MCP policy schemas;
- global command registry and post-creation command handoff;
- Memory Tickets, PM Soul, Memory Curator, sitemap/task-bias, policy, eval, QA,
  and runtime adapter rules;
- skill lifecycle registry, trial evidence, and Curator promotion decision
  contracts;
- Super Ontology candidate contract, open-world coverage, consensus coordination, task coverage, contextual flow, causal
  impact, assurance case, knowledge homeostasis, adversarial provenance, source
  lineage version, entity identity resolution, temporal state transition,
  capability delegation authority, privacy confidentiality boundary, strategic
  incentive compatibility, replay evidence, and promotion evidence contracts;
- public-safe schemas, templates, docs, skills, and verification scripts.

Public core should be runnable as a Markdown-first agent team. It should not
require Agentlas Web accounts, Agentlas Desktop storage, or private deployment
state.

## Shared Contracts

These concepts may appear in public core, hosted web, and local runtimes. The
public core contract is the public version they should all mirror:

| Contract | Public core | Hosted web | Desktop/terminal |
|---|---|---|---|
| Mode names | canonical | mirrors | mirrors |
| Mode auto-detection | public rule | may implement in code | may implement in code |
| Clarify question loop | public rule | may store sessions and meter usage | may run locally |
| Generated folder layout | canonical | emits ZIPs | installs or imports |
| Global commands | canonical `.agentlas/global-commands.json` and command files | emits command registry and install hints | may install global commands locally |
| `.agentlas` memory files | canonical | emits in exports | creates/maintains locally |
| Local credential store | value-free public contract | may emit placeholders only | may store real values in gitignored local files or local keychain/vault |
| Borrowed-agent credential request | provider/env/host/scope/broker metadata only | may render setup guidance without values | owns secure GUI, OS vault/keychain, and any host-bound broker implementation |
| Agent/experience assets | canonical identities, exact release bindings, lifecycle, privacy, and receipt schemas | owns account storage, publication, moderation, ranking, leases, and revenue | owns local capture, curation, private packs, and execution receipts |
| MCP resolution | system-global-first, catalog-id-only, one-pass consent, failure isolation, and token-budget contract | may own catalog metadata and compatibility projections | owns registry discovery, key presence, process connection, smoke tests, and UI state |
| Model allocation | owns provider-neutral parent-AI decision and prompt-free receipt schemas | may enforce account cost ceilings and exact hosted inventory | owns actual model inventory, explicit pins, effort support, context/tool compatibility, and per-child execution |
| `.agentlas` skill lifecycle files | canonical export contract | emits candidate registry and empty ledgers | may merge locally as candidate metadata |
| `.agentlas` Super Ontology files | canonical candidate contract | emits candidate contract and empty replay/evidence ledgers | may seed locally as candidate metadata |
| PM Soul / Memory Curator | generated role contract | may package into exports | may ship built-in agents |
| Sitemap/task-bias | generated contract | may package into exports | may maintain local project state |
| Runtime adapters | public adapters | emitted in ZIPs | used to invoke local runners |
| Verification | public scripts | may run before export/publish | may run before local install |

## Web-Only Implementation

Hosted web products may own implementation details that should not be copied into
this public repo:

- account, workspace, invite, and session logic;
- billing, subscriptions, credits, top-up wallets, and spend limits;
- hosted model provider keys and provider-cost telemetry;
- rate limits and abuse controls;
- database storage for drafts, profiles, jobs, scans, governance approvals, and
  usage events;
- private OAuth flows, encrypted token storage, and compliance exports;
- public marketplace approval workflow;
- server routes that turn prompts into saved drafts or ZIP downloads.

Public core can document compatible contracts, but it must not include hosted
SaaS billing, customer data, production credentials, private deployment config,
or account-state implementation.

## Desktop And Terminal-Only Implementation

Local desktop and terminal runtimes may own local execution details that should
not be copied into this public repo as product code:

- local SQLite or app database schema;
- keychain, vault, cookie, or local session storage;
- runtime detection for Claude, Codex, Gemini, BYOK, Ollama, or other local
  runners;
- Electron IPC, windows, menus, updater, renderer state, and app registry;
- local App Factory and Tool Factory implementation;
- filesystem materialization of installed agents;
- filesystem materialization of project-local credential files;
- secure credential-entry GUI, OS keychain/vault brokering, credential preview
  masking, and any separate process/daemon that enforces host-bound credential
  attachment;
- automation scheduler and local surface registry.

Public core can define public activation and package contracts. Local runtimes
choose how to store and execute them.

## Public Sync Additions

The following formerly runtime-owned behaviors are now public contracts:

1. Mode auto-detection: see `docs/mode-classifier.md` and
   `skills/mode-classification/SKILL.md`.
2. Clarify question loop: see `docs/clarify-question-loop.md` and
   `skills/clarify-question-loop/SKILL.md`.
3. `.agentlas` auto-activation: see `docs/agentlas-auto-activation.md` and
   `skills/agentlas-auto-activation/SKILL.md`.
4. Local credential store and borrowed-agent credential request metadata: see
   `docs/local-credential-store.md`.
5. Global commands: see `docs/global-command-contract.md`. Generated and
   packaged agents must include `.agentlas/global-commands.json`, runtime
   command files or aliases, and a final `global_commands` handoff.
6. Skill lifecycle promotion metadata: see
   `docs/skill-lifecycle-promotion.md` and
   `skills/skill-lifecycle-promotion/SKILL.md`.
7. Super Ontology candidate metadata: see
   `docs/super-ontology-candidate-contract.md`.
   Its open-world coverage seed, consensus-coordination seed, task coverage seed, contextual-flow seed, causal-impact seed,
   assurance-case seed, knowledge-homeostasis seed, adversarial-provenance seed,
   epistemic-calibration seed, semantic-alignment seed, resilience-control seed,
   observability-telemetry seed, objective-proxy-validity seed,
   stakeholder-preference-governance seed, normative-authority-drift seed,
   side-effect-containment seed, source-lineage-version seed,
   entity-identity-resolution seed, temporal-state-transition seed,
   capability-delegation-authority seed, privacy-confidentiality-boundary seed,
   strategic-incentive-compatibility seed, reflexive-feedback-stability seed,
   and Memory Curator bridge ledger are candidate-only: task coverage
   classifies requested work before action, contextual flow blocks unsafe
   boundary crossings, causal impact blocks relation-as-intervention jumps,
   assurance cases block unsupported broad claims, knowledge homeostasis blocks
   stale or desynced knowledge from continuing silently, adversarial provenance
   blocks hostile or unverified sources from becoming retrieval, memory, tool,
   or public-seed authority, epistemic calibration blocks missing evidence,
   conflict, stale evidence, low retrieval relevance, and model disagreement
   from becoming confident answers or runtime writes, and the bridge keeps
   semantic alignment blocks same-label, similar-embedding, OCR, generated-label,
   route-label, and high-authority `same_as` shortcuts from becoming graph or
   memory changes without scope, evidence, owner review, diff, and rollback.
   Resilience control blocks degraded validators, retrieval drift, tool errors,
   parser/sensor degradation, Memory Curator backlog, sync drift, rollback
   failures, and emergency-stop bypasses from keeping nominal write authority.
   Invariant verification blocks memory, graph, tool, public-export, route,
   release, rollback, and emergency-stop transitions unless event order,
   authority, evidence, consent, idempotency, and observed recovery invariants
   pass.
   Source lineage version blocks drafts, exported PDFs, summaries,
   translations, redacted copies, stale connector caches, chunks, embeddings,
   Memory Curator notes, and superseded runtime contracts from becoming graph,
   memory, public, training, tool, or route authority without source/version
   lineage, owner, span, audit, and rollback evidence.
   Objective proxy validity blocks metric movement, benchmark scores, approval
   rates, ontology edge counts, reward deltas, and green dashboards from being
   treated as real success unless construct validity, countermetrics,
   stakeholder review, gaming probes, and rollback are present.
   Strategic incentive compatibility blocks self-reports, KPI movement,
   commission reports, manager approvals, vendor claims, customer ratings,
   benchmark scores, agent votes, cost-saving claims, compliance attestations,
   access requests, hidden affiliations, social pressure, strategic silence,
   and collusive quorums from becoming truth or write authority without
   incentive evidence, independent verification, collusion checks, mechanism
   constraints, appeal, audit, and rollback.
   The bridge keeps direct durable memory writes blocked until Curator, Policy,
   PM Soul, or sync review approves a later phase.
8. Agent experience asset and MCP build contracts: see
   `docs/agent-experience-assets.md` and `docs/mcp-build-resolution.md`. Base
   agents and user-owned experience are separate releases; a Variant binds one
   exact release of each without copying content. RunReceipt replay protection
   and independent verification gate official success. MCP packages may name
   catalog capabilities and value-free credential metadata, never server
   commands, endpoints, or credential values.
   `.agentlas/experience-relations.jsonl` is a separate local Experience
   lineage source for a rebuildable relation index. Public Core and Desktop
   base-agent packagers exclude it from AgentDefinition source/delivery hashes
   and bundles; only the redacted aggregate public Career Graph card may cross
   that base-package boundary.
9. Parent-AI model allocation: see `docs/model-allocation.md`. Deterministic
   host code may validate, clamp, and translate a decision, but must not infer
   task difficulty from hardcoded request keywords. Missing or invalid parent
   decisions preserve the current host model with an explicit fallback receipt;
   they never silently fan every child out to a flagship model.

These are contract-level syncs. They do not move hosted billing, account state,
private storage, or local Electron implementation into public core.

## Rule Of Thumb

If the behavior helps any runtime create better Agentlas packages, put the
contract here. If the behavior depends on one company's accounts, payments,
server state, key storage, app windows, or local database, keep only a public
interface here and leave the implementation in that runtime.
