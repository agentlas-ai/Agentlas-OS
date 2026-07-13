# Source Of Truth

This repository is the public architecture and foldering source of truth for
Agentlas Core Engine Meta-Agent packages.

It also owns the public [Agent Trust contract](agent-trust-contract.md): an
agent is a portable, owner-scoped, inspectable, restorable asset rather than a
disposable program or one-vendor chat setting. Product-specific Web, Desktop,
Terminal, and account implementations must mirror that contract without moving
their private implementation into this repository.

It defines the portable contract that hosted services, desktop apps, terminal
tools, and runtime adapters should mirror when they create, repair, import, or
publish Agentlas-compatible agents and teams.

## Ownership

This repository owns:

- the three-mode meta-agent team contract;
- public mode classification and clarify question contracts;
- visible public foldering for generated Agentlas packages;
- `.agentlas` contracts;
- public `.agentlas` auto-activation contract for local runtimes;
- public global command contract for generated and packaged agents;
- public AgentDefinition, ExperiencePack, AgentVariant, RunReceipt, rental
  resolution, and MCP requirement/policy contracts;
- public parent-AI model allocation decision and prompt-free allocation receipt
  contracts; hosts own exact provider execution but must enforce these bounds;
- public skill lifecycle registry contract for export-only candidate metadata;
- public runtime adapters;
- public-safe schemas, templates, and verification scripts.

Runtime-specific implementations may own execution details such as hosted model
provider routing, billing, account state, local app storage, desktop activation,
or private deployment configuration. Those details should mirror this public
architecture contract but should not be copied into this public repo unless they
are intentionally public-safe.

## Canonical Modes

- `single-agent-creator`: creates one installable self-evolving worker package.
- `team-builder`: creates a multi-role team package with orchestrator/HQ, PM
  Soul, Memory Curator, Policy Gate, workers, eval, QA/evidence gate, handoffs,
  memory, and runtime adapters.
- `agentlas-packager`: repairs or converts an existing prompt, agent, team,
  repo, or ZIP into the Agentlas architecture.

The canonical mode map lives at `.agentlas/mode-map.json`.

## Canonical Files

These files are the public contract surface:

- `AGENTS.md`
- `README.md`
- `ARCHITECTURE.md`
- `docs/source-of-truth.md`
- `docs/agent-trust-contract.md`
- `docs/runtime-sync-boundaries.md`
- `docs/mode-classifier.md`
- `docs/clarify-question-loop.md`
- `docs/global-command-contract.md`
- `docs/agentlas-auto-activation.md`
- `docs/local-credential-store.md`
- `docs/agent-experience-assets.md`
- `docs/mcp-build-resolution.md`
- `docs/model-allocation.md`
- `docs/skill-lifecycle-promotion.md`
- `docs/super-ontology-candidate-contract.md`
- `.agentlas/mode-map.json`
- `.agentlas/agent-card.json`
- `.agentlas/company-blueprint.json`
- `.agentlas/sitemap.json`
- `.agentlas/global-commands.json`
- `.agentlas/memory-map.json`
- `.agentlas/memory-tickets.jsonl`
- `.agentlas/vault-references.json`
- `.agentlas/local-credentials.map.json`
- `.agentlas/mcp-policy.json`
- `.agentlas/activation.json`
- `.agentlas/skill-registry.json` in generated packages
- `.agentlas/skill-trials.jsonl` in generated packages
- `.agentlas/curator-decisions.jsonl` in generated packages
- `.agentlas/super-ontology-contract.json` in generated packages
- `.agentlas/super-ontology-open-world-coverage.json` in generated packages
- `.agentlas/super-ontology-consensus-coordination.json` in generated packages
- `.agentlas/super-ontology-task-coverage.json` in generated packages
- `.agentlas/super-ontology-contextual-flow.json` in generated packages
- `.agentlas/super-ontology-causal-impact.json` in generated packages
- `.agentlas/super-ontology-assurance-case.json` in generated packages
- `.agentlas/super-ontology-knowledge-homeostasis.json` in generated packages
- `.agentlas/super-ontology-adversarial-provenance.json` in generated packages
- `.agentlas/super-ontology-epistemic-calibration.json` in generated packages
- `.agentlas/super-ontology-semantic-alignment.json` in generated packages
- `.agentlas/super-ontology-resilience-control.json` in generated packages
- `.agentlas/super-ontology-invariant-verification.json` in generated packages
- `.agentlas/super-ontology-observability-telemetry.json` in generated packages
- `.agentlas/super-ontology-objective-proxy-validity.json` in generated packages
- `.agentlas/super-ontology-stakeholder-preference-governance.json` in generated packages
- `.agentlas/super-ontology-normative-authority-drift.json` in generated packages
- `.agentlas/super-ontology-side-effect-containment.json` in generated packages
- `.agentlas/super-ontology-source-lineage-version.json` in generated packages
- `.agentlas/super-ontology-entity-identity-resolution.json` in generated packages
- `.agentlas/super-ontology-temporal-state-transition.json` in generated packages
- `.agentlas/super-ontology-capability-delegation-authority.json` in generated packages
- `.agentlas/super-ontology-privacy-confidentiality-boundary.json` in generated packages
- `.agentlas/super-ontology-strategic-incentive-compatibility.json` in generated packages
- `.agentlas/super-ontology-reflexive-feedback-stability.json` in generated packages
- `.agentlas/super-ontology-replays.jsonl` in generated packages
- `.agentlas/super-ontology-evidence.jsonl` in generated packages
- `.agentlas/super-ontology-memory-bridge.jsonl` in generated packages
- `agents/10-single-agent-builder/agent.md`
- `agents/20-multi-agent-team-builder/agent.md`
- `agents/30-agentlas-packager/agent.md`
- `modes/single-agent-creator.md`
- `modes/team-builder.md`
- `modes/agentlas-packager.md`
- `.agents/agentlas-core-engine-meta-agent/agent.md`
- `skills/`
- `.agents/skills/`
- `schemas/`
- `schemas/gateway-channel.schema.json`
- `schemas/local-credentials-map.schema.json`
- `schemas/agent-definition.schema.json`
- `schemas/experience-pack.schema.json`
- `schemas/experience-item.schema.json`
- `schemas/experience-relation-lineage.schema.json`
- `schemas/agent-variant.schema.json`
- `schemas/run-receipt.schema.json`
- `schemas/model-allocation-decision.schema.json`
- `schemas/model-allocation-receipt.schema.json`
- `schemas/mcp-requirement.schema.json`
- `schemas/mcp-policy.schema.json`
- `schemas/rental-resolution-receipt.schema.json`
- `docs/hephaestus-agentlas-gateway-architecture.md`
- `templates/`
- `templates/gateway-channel.json.tpl`
- `templates/local-credentials.map.json.tpl`
- `templates/mcp-policy.json.tpl`
- experience asset and receipt templates under `templates/`
- runtime adapters under `codex/`, `.claude/`, `.gemini/`, and `claude/`
- global command adapters under `.claude/commands/`,
  `codex/plugins/*/commands/`, and `gemini/extension/commands/`, with optional
  `.gemini/commands/` fallback files
- `scripts/verify-package.sh`
- `scripts/public_safety_check.sh`

Adapters are mirrors of the canonical core. Do not make an adapter the only
place where a core architecture rule exists.

## Update Rule

Update this document in the same change set when any of these public contracts
change:

- meta-agent modes or routing;
- mode auto-detection rules;
- clarify question loop;
- generated package folder layout;
- `.agentlas` schemas or required files;
- gateway channel contracts, templates, or verification rules;
- `.agentlas` global command registry or generated command surfaces;
- `.agentlas` auto-activation contract;
- agent experience asset identity, ownership, exact-release binding, receipt,
  ranking, MCP resolution, and value-free derived relation-lineage contracts;
- `.agentlas` skill lifecycle registry contract;
- `.agentlas` Super Ontology open-world coverage, consensus coordination, task coverage, contextual flow, causal impact,
  assurance case, knowledge homeostasis, adversarial provenance, epistemic
  calibration, semantic alignment, resilience control, invariant verification,
  observability telemetry, objective proxy validity, stakeholder preference
  governance, normative authority drift, side-effect containment, source
  lineage version, entity identity resolution, temporal state transition, and
  capability delegation authority, privacy confidentiality boundary, and
  strategic incentive compatibility contracts;
- Memory Curator, Memory Tickets, PM Soul, sitemap, task-bias, self-evolution,
  policy, eval, or QA/evidence contracts;
- runtime adapter shape;
- install, import, export, or verification behavior;
- public/private cleanup rules.

## Synced Public Runtime Contracts

The following behaviors are public contracts in this repo:

- mode auto-detection;
- Agent Trust ownership, portability, public/private, restore, and execution
  boundaries;
- clarify question loop;
- `.agentlas` local auto-activation.
- `.agentlas/global-commands.json` with final `global_commands` handoff.
- export-only skill lifecycle metadata with candidate tier, trial ledgers, and
  Curator decision ledgers.
- exact-release AgentDefinition/ExperiencePack/AgentVariant identities, verified
  replay-safe receipts, and system-global-first MCP resolution policy.

The following remain implementation-specific and must not be copied here as
product code:

- hosted web billing, accounts, workspaces, sessions, credit limits, database
  state, OAuth storage, and server routes;
- desktop or terminal SQLite schema, keychain, app windows, IPC, runner
  detection, App Factory, Tool Factory, automation scheduler, or local surface
  registry.

After changing this repository, run:

```bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Do not publish a release when either script fails.

## Public Boundary

This repo must not include production credentials, customer data, private local
research notes, raw logs, full transcripts, hosted billing code, private
deployment configuration, or machine-specific operator paths.

When packaging an external or local agent for public release, remove private
material before committing, exporting, or publishing.
