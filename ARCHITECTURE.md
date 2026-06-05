# Architecture

Agentlas Core Engine Meta-Agent Team packages the common operating structure
behind Agentlas-style agent creation and packaging as a Markdown-first repo.

## Meta-Agent Team

```text
User request
  -> root meta-agent router
  -> one of:
       10-single-agent-builder
       20-multi-agent-team-builder
       30-agentlas-packager
  -> Agentlas architecture contracts
  -> runtime adapters
  -> verification
```

## Three Core Agents

- `10-single-agent-builder`: creates one installable worker package. It can add
  self-evolution, research refresh, memory architecture, and runtime adapters
  without turning the output into a team.
- `20-multi-agent-team-builder`: creates a team package with orchestrator/HQ,
  PM Soul, Memory Curator, Policy Gate, workers, eval judge, QA/evidence gate,
  handoffs, memory, and runtime adapters.
- `30-agentlas-packager`: takes existing local or external agents/teams and
  repairs them into the Agentlas architecture, including public plugin and
  one-line installer surfaces when requested.

## Canonical Core

The canonical core is runtime-neutral:

- `AGENTS.md`
- `agent.md`
- `docs/source-of-truth.md`
- `docs/runtime-sync-boundaries.md`
- `docs/mode-classifier.md`
- `docs/clarify-question-loop.md`
- `docs/agentlas-auto-activation.md`
- `docs/skill-lifecycle-promotion.md`
- `docs/super-ontology-candidate-contract.md`
- `agents/`
- `modes/`
- `.agents/agentlas-core-engine-meta-agent/agent.md`
- `.agents/skills/*/SKILL.md`
- `.agentlas/mode-map.json`
- `.agentlas/agent-card.json`
- `.agentlas/company-blueprint.json`
- `.agentlas/sitemap.json`
- `.agentlas/memory-map.json`
- `.agentlas/memory-tickets.jsonl`
- `.agentlas/vault-references.json`
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
- `.agentlas/super-ontology-replays.jsonl` in generated packages
- `.agentlas/super-ontology-evidence.jsonl` in generated packages
- `.agentlas/super-ontology-memory-bridge.jsonl` in generated packages
- `schemas/`
- `templates/`

## Public Runtime Contracts

Three runtime behaviors are public contracts here, not private product code:

- Mode classifier: choose `single-agent-creator`, `team-builder`, or
  `agentlas-packager` before generation.
- Clarify question loop: ask one to five package-shaping questions when the
  mode, runtime target, public boundary, tools, or safety constraints are
  unclear.
- `.agentlas` auto-activation: local runtimes may create or merge public
  `.agentlas` seed files after explicit activation or repeated meaningful work
  in the same folder.
- Skill lifecycle registry: generated packages may ship export-only candidate
  skill metadata, trial evidence ledgers, and Curator decision ledgers. Runtime
  first-class recall stays off until local Curator review and workspace policy
  approve it.
- Super Ontology candidate contract: generated packages may ship export-only
  adaptive knowledge governance metadata, open-world coverage, consensus coordination, task coverage, contextual-flow,
  causal-impact metadata, assurance-case metadata, knowledge-homeostasis
  metadata, adversarial-provenance metadata, epistemic-calibration metadata,
  semantic-alignment metadata, resilience-control metadata,
  invariant-verification metadata, observability-telemetry metadata,
  objective-proxy-validity metadata, stakeholder-preference-governance metadata,
  normative-authority-drift metadata, replay ledgers, and promotion
  evidence ledgers. Runtime graph
  writes, cross-context information flows, relation-as-action jumps, broad
  safety claims, stale or desynced knowledge use, hostile-source promotion, and
  uncalibrated answers or writes, unreviewed term/schema/ontology merges, and
  preference-driven writes without stakeholder governance, and stale or
  out-of-scope authority claims
  stay off until shadow/canary replay, rollback, homeostasis review,
  adversarial-provenance review, epistemic-calibration review,
  semantic-alignment review, resilience-control review, invariant-verification
  review, observability-telemetry review, objective-proxy-validity review,
  stakeholder-preference-governance review, normative-authority-drift review, and
  sync review approve a later phase.

## Generated Architecture Components

The following concepts are not separate meta-agent team members. They are
contracts that the three builders generate or repair inside output packages:

- PM Soul or project owner.
- Memory Curator and Memory Tickets.
- Skill lifecycle registry, trial evidence, and Curator promotion decisions.
- Super Ontology candidate contract, open-world coverage, consensus coordination, task coverage, contextual flow, causal
  impact, assurance cases, knowledge homeostasis, adversarial provenance,
  epistemic calibration, semantic alignment, resilience control, invariant verification,
  observability telemetry, objective proxy validity, stakeholder preference
  governance, replay evidence, and
  promotion evidence.
- Sitemap and task bias.
- LLM runtime architecture.
- Policy Gate.
- Eval judge and QA/evidence gate.
- Thin runtime adapters.
- Public-safety and install verification.

## Runtime Adapters

Adapters translate the same core into each runtime:

- Codex: `codex/marketplace.json` and
  `codex/plugins/agentlas-core-engine-meta-agent/`.
- Claude Code: `.claude/commands/`, `.claude/agents/`, `.claude/skills/`.
- Gemini CLI: `GEMINI.md` and `.gemini/GEMINI.md`.
- Generic AGENTS.md tools: root `AGENTS.md`.

Adapters should not contain private logic that is missing from the canonical
core.

## Packaging Flow

```text
existing prompt / agent / team / repo / zip
  -> Agentlas Packager
  -> inspect current structure
  -> classify single-agent or team package
  -> add AGENTS.md canonical core
  -> add .agentlas contracts
  -> add runtime adapters
  -> remove private or unsafe material from public output
  -> verify package
```

## Public Packaging Rule

A public package should look intentional at first glance:

- `README.md` explains the purpose.
- `ARCHITECTURE.md` explains the system.
- `agents/` shows the three meta-agent team roles.
- `modes/` shows the three work modes.
- `skills/` shows reusable procedures.
- `schemas/` makes contracts explicit.
- `scripts/verify-package.sh` proves the package shape.
