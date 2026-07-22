# Agentlas Core Engine Meta-Agent Team

## Repository Constitution: Local Main Only

This repository uses one canonical development line: the local `main` branch
in the canonical Agentlas OS checkout.

- Make every source change and commit directly on local `main`.
- Do not create feature, release, backup, agent-named, or temporary branches.
- Do not create Git worktrees. Use an external recovery directory or a verified
  Git bundle when a safety snapshot is required.
- Before editing, confirm the canonical checkout is on `main`, inspect status,
  fetch remote refs, and inspect `main...origin/main`. A GUI "Pull origin"
  button is not permission to pull or merge blindly.
- If local `main` is dirty, preserve it with a reviewed checkpoint commit before
  reconciling remote changes on that same branch.
- Push only `main` and intentional release tags. Do not publish side branches.

## Public Release Allowlist (Hard Rule)

Before any commit, push, tag, release, or upload to a public GitHub repository,
construct and review an explicit allowlist. Public source and release artifacts
may contain only files required for an end user to install and run the product,
plus public-facing `README`, `LICENSE`, and `CHANGELOG` material.

Never publish internal design or research documents, plans, benchmarks,
benchmark prompts or results, tests, fixtures, test data, scores, logs,
screenshots, signing material, certificates, credentials, environment files,
operator notes, private paths, local memory, or recovery artifacts. Run tests
and benchmarks only in local/private temporary storage or private CI; publish
neither their inputs nor their artifacts. Existing unrelated local work must
remain unstaged.

For a public release, do not use a blanket `git add -A`. Stage the allowlist
explicitly, inspect `git diff --cached --name-only` and the staged archive
manifest, scan the staged content for secrets/private paths, and stop the
release if any excluded class appears. A passing test does not authorize
publishing the test.

This repository is a portable three-agent meta-agent team. Use it to create or
package Agentlas-compatible single agents and multi-agent teams for Codex,
Claude Code, Gemini CLI, Antigravity, Cursor, OpenCode, OpenClaw, Hermes
Agent, Ollama-served local models (Gemma, DeepSeek — see
`docs/local-models.md`), and `AGENTS.md`-compatible runtimes.

## Source Of Truth

- Canonical entry point: `AGENTS.md`.
- Architecture ownership rule: `docs/source-of-truth.md`.
- Runtime split and sync boundary: `docs/runtime-sync-boundaries.md`.
- Third-party plugin contribution boundary: `CONTRIBUTING.md` and
  `PLUGIN_CONTRIBUTIONS.md`.
- Global command contract: `docs/global-command-contract.md`.
- Production Ontology Runtime: `docs/ontology-runtime.md`, `ontology/`,
  `bin/ontology`, and `scripts/verify-ontology-runtime.sh`.
- Agentlas Cloud runtime contract: `docs/agentlas-cloud-runtime.md`,
  `agentlas_cloud/`, `schemas/agentlas-manifest.schema.json`, and
  `templates/agentlas.json.tpl`.
- Hephaestus Network 2.0 contract: `docs/hephaestus-network-2.0.md`,
  `docs/runtime-fallback-adapters.md`, `agentlas_cloud/networking/`,
  `schemas/routing-card.schema.json`, `.agentlas/routing-card.json`, and
  `scripts/verify-routing-cards.sh`.
- Stormbreaker robust execution contract: `docs/robustness-protocol.md`,
  `docs/robustness-eval.md`, and `schemas/robustness-eval-result.schema.json`.
- Canonical Stormbreaker Goal + UltraCode harness:
  `docs/stormbreaker-goal-ultracode-harness.md`,
  `agentlas_cloud/networking/stormbreaker_harness.py`, and
  `schemas/stormbreaker-goal-ultracode-harness.schema.json`.
- Builder quality gate: `docs/builder-interview-research-gate.md`,
  `docs/builder-quality-research-basis.md`,
  `templates/builder-interview.md.tpl`, `templates/research-sources.md.tpl`,
  `templates/tool-selection.md.tpl`, `templates/domain-expert-synthesis.md.tpl`,
  `templates/prompt-performance-contract.md.tpl`, and
  `templates/capability-eval-plan.json.tpl`.
- Portable support contracts: `docs/mode-classifier.md`,
  `docs/clarify-question-loop.md`, `docs/agentlas-auto-activation.md`,
  `docs/local-credential-store.md`, and `docs/skill-lifecycle-promotion.md`.
- Agent experience and MCP contracts: `docs/agent-experience-assets.md`,
  `docs/mcp-build-resolution.md`, the matching `schemas/*.schema.json`
  files, `.agentlas/mcp-policy.json`, and
  `scripts/verify-experience-assets-contract.sh`.
- Team members: `agents/10-single-agent-builder/agent.md`,
  `agents/20-multi-agent-team-builder/agent.md`, and
  `agents/30-agentlas-packager/agent.md`.
- Mode contracts: `modes/single-agent-creator.md`, `modes/team-builder.md`,
  and `modes/agentlas-packager.md`.
- Portable runtime core: `.agents/agentlas-core-engine-meta-agent/agent.md`.
- Reusable skills: `.agents/skills/*/SKILL.md` and root `skills/*/SKILL.md`.
- Agentlas contracts: `.agentlas/mode-map.json`,
  `.agentlas/agent-card.json`, `.agentlas/company-blueprint.json`,
  `.agentlas/sitemap.json`, `.agentlas/global-commands.json`,
  `.agentlas/memory-map.json`,
  `.agentlas/memory-tickets.jsonl`, `.agentlas/vault-references.json`,
  `.agentlas/local-credentials.map.json`, `.agentlas/mcp-policy.json`, and skill
  lifecycle files emitted in generated packages.
- Public install surfaces: `codex/`, `.claude/`, `.gemini/`, `antigravity/`, and
  `scripts/`.

Runtime-specific folders are adapters. They must mirror the canonical core, not
become separate sources of truth.

## Third-Party Plugin Boundary

Third-party services and optional provider integrations belong in independently
installable Agentlas plugins, not in Agentlas Core. This includes search APIs,
model providers, hosted browsers, data sources, SaaS connectors, payment
providers, and vendor-specific MCP servers.

Reject a provider contribution when it requires provider-specific changes to
Core registries, CLI provider maps, default or full loadouts, credential maps,
doctor or profile logic, ranking policy, network allowlists, or generated
runtime mirrors. An existing built-in integration is legacy precedent, not
permission to duplicate that wiring for another provider.

An acceptable third-party plugin must be independently installable,
upgradeable, disableable, and removable; activate only by explicit user choice;
declare capabilities, authentication, network hosts, operations, and privacy
effects without embedding credential values; and fail safely when unavailable.
Installing or removing it must not require a Core patch.

Core changes are considered only for a provider-neutral, versioned extension
contract that serves multiple independent plugins or enforces a Core invariant.
Propose that contract separately from any vendor implementation. Do not use a
vendor PR to introduce both the extension point and its first provider. Follow
`PLUGIN_CONTRIBUTIONS.md` for the submission and review checklist.

## Generated Instruction Language

All generated or repaired agent instruction files must be written in English.
This includes `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `agent.md`, role cards,
skills, workflow/command adapters, runtime prompts, handoff contracts, return
contracts, and package docs that are read as operating instructions.

Korean and other languages are allowed only for user-facing public copy,
localized marketplace fields, trigger examples, and sample user inputs. If the
source material or the user's request is written in Korean, translate the agent
behavior into English before writing runtime instructions.

## Operating Loop

1. Run the public mode classifier (`skills/mode-classification/SKILL.md`) and
   classify the request by independent ownership boundaries, not keywords. If
   existing material is being converted, repaired, cleaned, imported, or
   released, route to packager first. Otherwise count roles that independently
   own memory/context, tools/permissions, and success criteria; one boundary is
   single-agent, two or more plus routing/synthesis/produces-consumes handoff is
   team-builder. If the boundary is unclear, clarify before generation instead
   of guessing. Classify the request as one of:
   - create one single agent;
   - create a multi-agent team;
   - package or repair an existing local/external agent or team.
2. If required details would change the package, run the clarify loop
   (`skills/clarify-question-loop/SKILL.md`) before generating files.
3. Route to exactly one core team member:
   - `10-single-agent-builder`;
   - `20-multi-agent-team-builder`;
   - `30-agentlas-packager`.
4. Run the Builder Interview and Research Gate
   (`docs/builder-interview-research-gate.md`) before writing substantial
   generated package files. Ask an 8-12 question first batch when the request is
   vague, continue follow-ups until the functional brief is clear, research
   official sources, similar agent repositories or comparables,
   academic/professional theory, and plugin documentation, then select
   tools/plugins only after checking permissions, secrets, alternatives, and
   smoke-test paths. If single-agent vs team shape is unclear, the first batch
   must ask in plain language: "이 일을 한 명의 전문가가 처음부터 끝까지 맡으면
   되나요, 아니면 조사/분석/검토처럼 여러 전문가가 나눠 맡고 마지막에
   합쳐야 하나요?" Do not expose internal labels like ownership boundary,
   memory/context, synthesis, or produces/consumes to non-technical users.
5. Inspect current files before making claims. Prefer real files over remembered
   assumptions.
6. Emit or repair the smallest useful Agentlas package.
7. Add the required architecture contracts for the selected mode.
8. Add `docs/builder-interview.md`, `docs/research-sources.md`,
   `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
   `docs/prompt-performance-contract.md`, and
   `.agentlas/capability-eval-plan.json` unless the task is explicitly a
   minimal private scaffold or trivial adapter repair.
9. Before writing generated agent instructions, enforce the Generated
   Instruction Language policy: write runtime instructions in English, even
   when the source brief is Korean.
10. Add thin adapters for Codex, Claude Code, Gemini CLI, Antigravity, and
   optional Cursor.
11. Assign one canonical global command during creation, write
   `.agentlas/global-commands.json`, add runtime command files or aliases, and
   keep team worker roles routed through the orchestrator/HQ command unless the
   user explicitly asks for direct worker commands.
12. Add `.agentlas` seed files when the generated or packaged output needs local
   continuity; local runtimes may auto-activate them using
   `skills/agentlas-auto-activation/SKILL.md`.
13. Add or repair `agentlas.json` so Agentlas Cloud can compile a runtime
    bundle, gate lazy file reads, and separate private sync from public clean
    copies. Seed `.agentlas/mcp-policy.json` only when missing: resolve the
    system-global registry first, ask once for the selected set, load selected
    tool schemas and triggered skills only, and isolate each MCP failure.
14. Add skill lifecycle metadata using
   `skills/skill-lifecycle-promotion/SKILL.md` when the package contains
   reusable skills.
15. For generated or repaired packages, run
    `scripts/verify-team-package.sh <generated-package-root>` before the final
    report. If it fails, do not report `completed`; fix the shape by collapsing
    to a valid single-agent package or adding orchestrator/HQ plus company
    topology.
16. Verify with `scripts/verify-package.sh`.
17. For ontology runtime changes, also verify with
    `scripts/verify-ontology-runtime.sh`.
18. For long-running or multi-file execution work, apply
    `docs/robustness-protocol.md`: scope lock, plan lock, evidence loop,
    review gate, and final gate before claiming completion.

## Hephaestus Network Commands

Agentlas-native surfaces are commandless: Agentlas Terminal and the Agentlas
app should accept plain language and dispatch through native Agentlas/
Hephaestus tools without requiring a `/hep-*` command. External LLM hosts
registered through MCP, plugins, prompts, or command files expose the core
commands `/hep-build`, `/hep-network`, `/hep-local`, `/hep-cloud`, `/hep-hub`,
`/hep-search`, `/hep-call`, and `/hep-upload` (Codex prompt equivalents use
`/prompts:hep-*`). Stormbreaker, research loadouts, route options, and other
lower-level controls must be selected automatically from context unless the
operator is using a debug/automation shell directly.

`/hep-build <request>` is the creation, repair, memory, playbook, and
diagnostics surface. `/hep-network <request>` (alias
`@Hephaestus <request>`, terminal `hep-network "<request>"`) is the
Agent Workforce Ontology staffing surface across Local, Cloud, and Hub.
`/hep-local`, `/hep-cloud`, and `/hep-hub` use exactly one source each and
never widen scope. The active host LLM creates a redacted work order, calls
the local `hephaestus-network` MCP tool `workforce.search_candidates` with
`sourceScope`, preserves its complete response as `federationResult`, chooses
the exact roster, calls `workforce.validate_selection` with that result, then
passes both `federationResult` and `federatedSelection` to
`workforce.prepare_execution`. It then runs distinct
worker/synthesis/verifier invocations. Do not expose a second remote `agentlas`
MCP on hosts that can run local Core: Core reaches Cloud and Hub through its
internal upstream client, and duplicate `workforce.*` tools would bypass the
federation and privacy boundary. Deterministic code enforces hard constraints
but never picks the final team. The standalone shell
aliases can only report `host_llm_required`; the old card router is an explicit
`HEPHAESTUS_LEGACY_ROUTER=1` compatibility/debug surface.
`/hep-search <request>` compares Cloud and Hub
candidates without invoking. `/hep-call <slugs> <context>` prepares explicitly
named agents. `/hep-upload <agent-folder>` is the upload gate: before any
package, publish, register, add-source, reindex, or upload API call, ask whether
the destination is private Agentlas Cloud or public Agentlas Hub.

Workforce candidate retrieval uses roles, skills, knowledge, MCP/tool
capabilities, artifact contracts, runtimes, languages, authority, entity kind,
and evidence levels. It never uses installs, ratings, revenue, invocation
history, or local callability as semantic fit. Selection and preparation pin
immutable release, package hash, and content digest; unavailable posts remain
explicit and substitution requires a new host-LLM decision. Never send raw
prompts or local memory to Hub. A selection or prepared BYOM bundle is not an
execution receipt: completion requires planner parse success without fallback,
distinct child invocations, artifact handoffs, synthesis, and an independent
passing verifier. Generated and packaged repos must include
`.agentlas/routing-card.json` (see `schemas/routing-card.schema.json`); cards
compile into immutable workforce profiles and lifecycle events.

`hep-global install` is a shell utility, not a task command: it installs a
managed Hephaestus Global Router marker block into `~/.codex/AGENTS.md` and
`~/.claude/CLAUDE.md`, and `~/.gemini/GEMINI.md` for Antigravity/Gemini. That
block makes ordinary host prompts use Network federation unless an exact
Local, Cloud, or Hub scope was requested. Exact-scope commands never silently
widen when a source is unavailable, a workforce MCP call is rejected, or no
qualified slot coverage exists. If a source is blocked by credits,
entitlement, availability, or fit, the host reports that exact boundary.
Status lines must
name final workers, not
router commands: `사용 에이전트:`/`Agents used:` for agents and
`사용 스킬:`/`Skills used:` only for final skill fallbacks.
`hep-global status` reports the managed block state; `hep-global remove`
removes only the marker block and leaves the user's surrounding prompt file
intact.

Hephaestus Network chooses the agent, team, plugin, or Hub bundle. Hephaestus
Stormbreaker governs execution after that route is selected: it requires scope
locking, issue-contract extraction, failure-memory checks, verifier-first
planning, a parallel session fabric for pipeline work, bounded evidence loops,
review gates, outcome ledgers, and a final completion gate for substantial
work. Pipeline success is blocked until every required execution packet is
passing or the run is explicitly reported as blocked.

## Team Roles

- `10-single-agent-builder`: one installable self-evolving worker package.
- `20-multi-agent-team-builder`: multi-role team package with orchestrator/HQ,
  PM Soul, Memory Curator, Policy Gate, eval, QA, handoffs, memory, and runtime
  adapters.
- `30-agentlas-packager`: package or repair existing local/external agents and
  teams into Agentlas architecture for local use, Agentlas import, Codex plugin
  use, Claude adapter use, or open-source release.

PM Soul, Memory Curator, runtime adapters, sitemap/task-bias, policy, eval, and
verification are generated architecture components. They are not extra members
of this meta-agent team.

## Output Contract

When asked to create, repair, or package an agent repo, return:

- `status`: completed, blocked, or needs_clarification.
- `evidence`: files inspected, commands run, and verification result.
- `output`: generated path, changed files, or exact design.
- `global_commands`: Claude Code, Codex, Gemini CLI, Antigravity, generic
  AGENTS.md, and terminal commands from `.agentlas/global-commands.json`.
- `interview_research`: interview status, unresolved assumptions, similar
  agent/repository research, academic or professional theory basis,
  selected/rejected tools or plugins, domain-expert synthesis,
  prompt-performance contract, and capability-eval plan.
- `blockers`: only blockers that require the user or external state.

Generated or packaged repos must include the relevant subset of:

- visible `agents/` and `skills/` folders;
- `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`;
- `.agentlas/mode-map.json`;
- `.agentlas/agent-card.json`;
- `.agentlas/company-blueprint.json`;
- `.agentlas/global-commands.json`;
- `agentlas.json`;
- `docs/builder-interview.md`;
- `docs/research-sources.md`;
- `docs/tool-selection.md`;
- `docs/domain-expert-synthesis.md`;
- `docs/prompt-performance-contract.md`;
- `.agentlas/capability-eval-plan.json`;
- `.agentlas/memory-map.json`;
- `.agentlas/memory-tickets.jsonl`;
- `.agentlas/vault-references.json`;
- `.agentlas/local-credentials.map.json` plus `.env.example`, `signing/README.md`,
  and `credentials/README.md` when local credentials are required;
- `.agentlas/mcp-policy.json` with catalog-id-only requirements, value-free
  credential metadata, and no server command, args, endpoint, or key value;
- `.agentlas/skill-registry.json`;
- `.agentlas/skill-trials.jsonl`;
- `.agentlas/curator-decisions.jsonl`;
- `.agentlas/super-ontology-contract.json`;
- `.agentlas/super-ontology-open-world-coverage.json`;
- `.agentlas/super-ontology-consensus-coordination.json`;
- `.agentlas/super-ontology-task-coverage.json`;
- `.agentlas/super-ontology-contextual-flow.json`;
- `.agentlas/super-ontology-causal-impact.json`;
- `.agentlas/super-ontology-assurance-case.json`;
- `.agentlas/super-ontology-knowledge-homeostasis.json`;
- `.agentlas/super-ontology-adversarial-provenance.json`;
- `.agentlas/super-ontology-epistemic-calibration.json`;
- `.agentlas/super-ontology-semantic-alignment.json`;
- `.agentlas/super-ontology-resilience-control.json`;
- `.agentlas/super-ontology-invariant-verification.json`;
- `.agentlas/super-ontology-observability-telemetry.json`;
- `.agentlas/super-ontology-objective-proxy-validity.json`;
- `.agentlas/super-ontology-stakeholder-preference-governance.json`;
- `.agentlas/super-ontology-normative-authority-drift.json`;
- `.agentlas/super-ontology-side-effect-containment.json`;
- `.agentlas/super-ontology-source-lineage-version.json`;
- `.agentlas/super-ontology-entity-identity-resolution.json`;
- `.agentlas/super-ontology-temporal-state-transition.json`;
- `.agentlas/super-ontology-capability-delegation-authority.json`;
- `.agentlas/super-ontology-privacy-confidentiality-boundary.json`;
- `.agentlas/super-ontology-strategic-incentive-compatibility.json`;
- `.agentlas/super-ontology-reflexive-feedback-stability.json`;
- `.agentlas/super-ontology-replays.jsonl`;
- `.agentlas/super-ontology-evidence.jsonl`;
- `.agentlas/super-ontology-memory-bridge.jsonl`;
- runtime adapters and smoke-test docs;
- global command adapter files such as `.claude/commands/<slug>.md`,
  `codex/plugins/<package-id>/commands/<slug>.md`, and
  `gemini/extension/commands/<slug>.toml` with optional
  `.gemini/commands/<slug>.toml` fallback;
- production ontology runtime code, CLI, tests, and sample corpus when the
  package needs local-first knowledge storage, search, GraphRAG, Memory Curator
  bridge tickets, or Agent Working Memory;
- install or verification scripts;
- public-safety notes if the output is meant for GitHub.

Cloud-ready packages must pass the local setup wizard contract: `agentlas.json`
exists, the Hephaestus security scan is `PASS` or reviewable `WARN`, the
runtime bundle compiles from manifest allowlists, and denied paths never expose
secret-like values.

## Mode Rules

`single-agent-creator` produces one installable worker package. It can include
multiple skills, setup guides, memory architecture, research refresh, and
self-evolution proposals, but it must not inflate the request into a company,
HQ roster, or swarm. It must expose one global command for the worker and report
that command to the user after creation. It must not emit multiple loose worker
`agent.md` files; that is a team shape and requires HQ/topology.

`team-builder` produces a multi-role team package. It must include a root
orchestrator/HQ, PM Soul or project owner, Memory Curator, Policy Gate, worker
roles, eval judge, QA/evidence gate, handoff rules, runtime adapters, memory
architecture, and release checks. It must expose the orchestrator/HQ global
command as the public entry point; worker roles stay behind HQ routing unless
direct worker commands were explicitly requested. Team packages must pass
`scripts/verify-team-package.sh <package-root>` before completion.

`agentlas-packager` repairs or converts an existing agent/team into the Agentlas
shape. It adds canonical core files, `.agentlas` contracts, runtime adapters,
schemas, manifest, install scripts, global command registry, verification, and
public/private cleanup.

## Memory Preflight

Before substantial work:

1. Read `.agentlas/memory-map.json` if present.
2. Load only task-relevant memory.
3. Label remembered facts as `verified`, `memory_derived`, `inferred`, or
   `stale_check_needed`.
4. Re-check drift-prone facts against current files or sources.

Workers may emit `## Memory Events`. The runtime or orchestrator wraps those
events into Memory Tickets before durable curation.

Skills may also emit `## Skill Trial Events`. Those events are lifecycle
evidence for candidate/trial/first-class review and must not be mixed with
Memory Events. Generated packages keep all skills at `candidate` tier until a
local Curator approves promotion.

## Safety Rules

- Never store secrets, API keys, tokens, key material, credential file contents,
  raw logs, or full transcripts in generated repos or memory.
- Never copy a base agent prompt, skill, package file, raw prompt, customer
  record, or credential into an Experience Pack. Variant bindings use exact
  release references only, and official success accepts verified replay-safe
  RunReceipts only.
- Real credential values may be saved only in local gitignored project stores
  (`.env`, `.env.local`, `signing/`, `credentials/`) or a local keychain/vault.
  Generated public packages may include only placeholders, guide files, and a
  value-free `.agentlas/local-credentials.map.json`.
- Generated project memory must keep a `Local Credential Index (read first)`
  section near the top. For deploy, release, store, billing, auth, API, or
  cloud work, check that section and `.agentlas/local-credentials.map.json`
  before reporting missing credentials.
- Do not copy private local research folders into public output.
- Do not call runtime adapters canonical.
- Ask for explicit approval before destructive file actions, production deploys,
  paid API spend, permission widening, or public publishing.
- Public packages must pass `scripts/verify-package.sh` and
  `scripts/public_safety_check.sh` before release.
