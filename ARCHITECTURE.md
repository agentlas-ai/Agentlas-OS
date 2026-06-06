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
- `docs/local-credential-store.md`
- `docs/skill-lifecycle-promotion.md`
- `docs/ontology-runtime.md`
- `docs/super-ontology-candidate-contract.md`
- `agents/`
- `modes/`
- `ontology/`
- `bin/ontology`
- `tests/test_ontology_runtime.py`
- `scripts/verify-ontology-runtime.sh`
- `examples/ontology-corpus/`
- `.agents/agentlas-core-engine-meta-agent/agent.md`
- `.agents/skills/*/SKILL.md`
- `.agentlas/mode-map.json`
- `.agentlas/agent-card.json`
- `.agentlas/company-blueprint.json`
- `.agentlas/sitemap.json`
- `.agentlas/memory-map.json`
- `.agentlas/memory-tickets.jsonl`
- `.agentlas/vault-references.json`
- `.agentlas/local-credentials.map.json` in generated local packages that need
  credentials
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
- Local credential store: local runtimes may materialize real values in
  gitignored project `.env`, `signing/`, and `credentials/` files, while public
  packages and memory keep only value-free names, paths, and stale-check rules.
  Project memory must place a `Local Credential Index (read first)` section near
  the top so release, deploy, store, billing, auth, API, and cloud work checks
  local credential locations before reporting a missing key.
- Skill lifecycle registry: generated packages may ship export-only candidate
  skill metadata, trial evidence ledgers, and Curator decision ledgers. Runtime
  first-class recall stays off until local Curator review and workspace policy
  approve it.
- Super Ontology candidate contract: generated packages may ship export-only
  adaptive knowledge governance metadata, coverage seeds, replay ledgers, and
  promotion evidence ledgers. Public exports keep graph writes value-free and
  candidate-only. In local operator mode, promotion gates are project, folder,
  owner, evidence, and rollback organization rules, not a generic security stop
  sign. Local promotion can proceed when those structures are named; public
  release claims still need replay, rollback, and sync evidence.
- Production Ontology Runtime: the public core includes a local-first runtime
  package that ingests supported files into SQLite, FTS5, deterministic local
  vectors, source-lineaged chunks, ontology entities and relations, GraphRAG
  query responses, Memory Curator candidate tickets, and Agent Working Memory
  cache entries. The runtime parses text, Markdown, JSON, CSV, DOCX, XLSX,
  PPTX, PDF text, HWPX, and OCR images when the local OCR engine is available.
  It blocks direct durable-memory writes and records missing external parsers as
  `unsupported_pending_adapter` instead of pretending success.

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
  governance, strategic incentive compatibility, reflexive feedback stability,
  replay evidence, and
  promotion evidence.
- Sitemap and task bias.
- LLM runtime architecture.
- Policy Gate.
- Eval judge and QA/evidence gate.
- Thin runtime adapters.
- Local-first ontology runtime.
- Public-safety and install verification.

## Runtime Adapters

Adapters translate the same core into each runtime:

- Codex: `codex/marketplace.json` and
  `codex/plugins/agentlas-core-engine-meta-agent/`.
- Claude Code: `.claude/commands/`, `.claude/agents/`, `.claude/skills/`.
- Gemini CLI: `GEMINI.md` and `.gemini/GEMINI.md`.
- Generic AGENTS.md tools: root `AGENTS.md`.
- Ontology CLI: `bin/ontology` runs the local-first storage/search/graph/memory
  runtime from a shell.

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
