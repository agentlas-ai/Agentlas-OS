# Agentlas Core Engine Meta-Agent Team

This repository is a portable three-agent meta-agent team. Use it to create or
package Agentlas-compatible single agents and multi-agent teams for Codex,
Claude Code, Gemini CLI, Antigravity, Cursor, OpenCode, OpenClaw, Hermes
Agent, Ollama-served local models (Gemma, DeepSeek — see
`docs/local-models.md`), and `AGENTS.md`-compatible runtimes.

## Source Of Truth

- Canonical entry point: `AGENTS.md`.
- Architecture ownership rule: `docs/source-of-truth.md`.
- Runtime split and sync boundary: `docs/runtime-sync-boundaries.md`.
- Global command contract: `docs/global-command-contract.md`.
- Production Ontology Runtime: `docs/ontology-runtime.md`, `ontology/`,
  `bin/ontology`, `tests/test_ontology_runtime.py`, and
  `scripts/verify-ontology-runtime.sh`.
- Agentlas Cloud runtime contract: `docs/agentlas-cloud-runtime.md`,
  `agentlas_cloud/`, `schemas/agentlas-manifest.schema.json`, and
  `templates/agentlas.json.tpl`.
- Hephaestus Network 2.0 contract: `docs/hephaestus-network-2.0.md`,
  `docs/runtime-fallback-adapters.md`, `agentlas_cloud/networking/`,
  `schemas/routing-card.schema.json`, `.agentlas/routing-card.json`, and
  `scripts/verify-routing-cards.sh`.
- Stormbreaker robust execution contract: `docs/robustness-protocol.md`,
  `docs/robustness-eval.md`, `schemas/robustness-eval-result.schema.json`,
  `benchmarks/robustness/`, and `scripts/score-robustness-eval.py`.
- Builder quality gate: `docs/builder-interview-research-gate.md`,
  `docs/builder-quality-research-basis.md`,
  `templates/builder-interview.md.tpl`, `templates/research-sources.md.tpl`,
  `templates/tool-selection.md.tpl`, `templates/domain-expert-synthesis.md.tpl`,
  `templates/prompt-performance-contract.md.tpl`, and
  `templates/capability-eval-plan.json.tpl`.
- Portable support contracts: `docs/mode-classifier.md`,
  `docs/clarify-question-loop.md`, `docs/agentlas-auto-activation.md`,
  `docs/local-credential-store.md`, and `docs/skill-lifecycle-promotion.md`.
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
  `.agentlas/local-credentials.map.json`, and skill lifecycle files emitted in
  generated packages.
- Public install surfaces: `codex/`, `.claude/`, `.gemini/`, `antigravity/`, and
  `scripts/`.

Runtime-specific folders are adapters. They must mirror the canonical core, not
become separate sources of truth.

## Operating Loop

1. Run the public mode classifier (`skills/mode-classification/SKILL.md`) and
   classify the request as one of:
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
   smoke-test paths.
5. Inspect current files before making claims. Prefer real files over remembered
   assumptions.
6. Emit or repair the smallest useful Agentlas package.
7. Add the required architecture contracts for the selected mode.
8. Add `docs/builder-interview.md`, `docs/research-sources.md`,
   `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
   `docs/prompt-performance-contract.md`, and
   `.agentlas/capability-eval-plan.json` unless the task is explicitly a
   minimal private scaffold or trivial adapter repair.
9. Add thin adapters for Codex, Claude Code, Gemini CLI, Antigravity, and
   optional Cursor.
10. Assign one canonical global command during creation, write
   `.agentlas/global-commands.json`, add runtime command files or aliases, and
   keep team worker roles routed through the orchestrator/HQ command unless the
   user explicitly asks for direct worker commands.
11. Add `.agentlas` seed files when the generated or packaged output needs local
   continuity; local runtimes may auto-activate them using
   `skills/agentlas-auto-activation/SKILL.md`.
12. Add or repair `agentlas.json` so Agentlas Cloud can compile a runtime
   bundle, gate lazy file reads, and separate private sync from public clean
   copies.
13. Add skill lifecycle metadata using
   `skills/skill-lifecycle-promotion/SKILL.md` when the package contains
   reusable skills.
14. Verify with `scripts/verify-package.sh`.
15. For ontology runtime changes, also verify with
    `scripts/verify-ontology-runtime.sh`.
16. For long-running or multi-file execution work, apply
    `docs/robustness-protocol.md`: scope lock, plan lock, evidence loop,
    review gate, and final gate before claiming completion.

## Hephaestus Network Commands

Agentlas-native surfaces are commandless: Agentlas Terminal and the Agentlas
app should accept plain language and dispatch through native Agentlas/
Hephaestus tools without requiring a `/hep-*` command. External LLM hosts
registered through MCP, plugins, prompts, or command files expose exactly six
explicit commands: `/hep-build`, `/hep-network`, `/hep-cloud`, `/hep-search`,
`/hep-call`, and `/hep-upload` (Codex prompt equivalents use
`/prompts:hep-*`). Stormbreaker, research loadouts, route options, and other
lower-level controls must be selected automatically from context unless the
operator is using a debug/automation shell directly.

`/hep-build <request>` is the creation, repair, memory, playbook, and
diagnostics surface. `/hep-network <request>` (alias
`@Hephaestus <request>`, terminal `hep-network "<request>"`) is the
work-routing surface. `/hep-cloud <request>` uses the signed-in user's own
Agentlas Cloud packages. `/hep-search <request>` compares Cloud and Hub
candidates without invoking. `/hep-call <slugs> <context>` prepares explicitly
named agents. `/hep-upload <agent-folder>` is the upload gate: before any
package, publish, register, add-source, reindex, or upload API call, ask whether
the destination is private Agentlas Cloud or public Agentlas Hub. Route natural
language through the local-first Agent OS router: explicit commands → project
`.agentlas/routing-overrides.json` → local routing cards (`routing_ready`+
only) → redacted Agentlas Hub lookup → propose building a new agent.
Plan-anchored composite requests ("기획부터 구현, QA까지") return `action:
"pipeline"` or Hub stage candidates with a `task_force`: a temporary TF plan
chained by Agent Ontology or card `produces`/`consumes` artifact contracts.
Execute stages through the returned `execution_fabric`, handing artifacts
through `handoff_dir`. Independent packets in the same `parallel_group` may run
concurrently when the host runtime advertises active sessions such as Codex,
Claude, GLM, DeepSeek, Gemini, or local models.
Honor the decision JSON exactly:
ask the `clarify_question` on `clarify`, follow `policy_decision` labels in
Local Operator Mode, never send raw prompts or local memory to the Hub, and
report the routing `receipt_id`. Most policy signals are labels,
`auto_redact`, or `candidate_only`; human approval should be rare and reserved
for real external export, global memory/playbook promotion, or irreversible
host-runtime actions. Generated and packaged repos must include
`.agentlas/routing-card.json` (see `schemas/routing-card.schema.json`); cards
below `routing_ready` are excluded from auto routing.

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
that command to the user after creation.

`team-builder` produces a multi-role team package. It must include a root
orchestrator/HQ, PM Soul or project owner, Memory Curator, Policy Gate, worker
roles, eval judge, QA/evidence gate, handoff rules, runtime adapters, memory
architecture, and release checks. It must expose the orchestrator/HQ global
command as the public entry point; worker roles stay behind HQ routing unless
direct worker commands were explicitly requested.

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
