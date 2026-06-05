# Agentlas Core Engine Meta-Agent Team

This repository is a portable three-agent meta-agent team. Use it to create or
package Agentlas-compatible single agents and multi-agent teams for Codex,
Claude Code, Gemini CLI, Cursor, and `AGENTS.md`-compatible runtimes.

## Source Of Truth

- Canonical entry point: `AGENTS.md`.
- Architecture ownership rule: `docs/source-of-truth.md`.
- Runtime split and sync boundary: `docs/runtime-sync-boundaries.md`.
- Portable support contracts: `docs/mode-classifier.md`,
  `docs/clarify-question-loop.md`, `docs/agentlas-auto-activation.md`, and
  `docs/skill-lifecycle-promotion.md`.
- Team members: `agents/10-single-agent-builder/agent.md`,
  `agents/20-multi-agent-team-builder/agent.md`, and
  `agents/30-agentlas-packager/agent.md`.
- Mode contracts: `modes/single-agent-creator.md`, `modes/team-builder.md`,
  and `modes/agentlas-packager.md`.
- Portable runtime core: `.agents/agentlas-core-engine-meta-agent/agent.md`.
- Reusable skills: `.agents/skills/*/SKILL.md` and root `skills/*/SKILL.md`.
- Agentlas contracts: `.agentlas/mode-map.json`,
  `.agentlas/agent-card.json`, `.agentlas/company-blueprint.json`,
  `.agentlas/sitemap.json`, `.agentlas/memory-map.json`,
  `.agentlas/memory-tickets.jsonl`, `.agentlas/vault-references.json`, and
  skill lifecycle files emitted in generated packages.
- Public install surfaces: `codex/`, `.claude/`, `.gemini/`, and `scripts/`.

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
4. Inspect current files before making claims. Prefer real files over remembered
   assumptions.
5. Emit or repair the smallest useful Agentlas package.
6. Add the required architecture contracts for the selected mode.
7. Add thin adapters for Codex, Claude Code, Gemini CLI, and optional Cursor.
8. Add `.agentlas` seed files when the generated or packaged output needs local
   continuity; local runtimes may auto-activate them using
   `skills/agentlas-auto-activation/SKILL.md`.
9. Add skill lifecycle metadata using
   `skills/skill-lifecycle-promotion/SKILL.md` when the package contains
   reusable skills.
10. Verify with `scripts/verify-package.sh`.

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
- `blockers`: only blockers that require the user or external state.

Generated or packaged repos must include the relevant subset of:

- visible `agents/` and `skills/` folders;
- `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`;
- `.agentlas/mode-map.json`;
- `.agentlas/agent-card.json`;
- `.agentlas/company-blueprint.json`;
- `.agentlas/memory-map.json`;
- `.agentlas/memory-tickets.jsonl`;
- `.agentlas/vault-references.json`;
- `.agentlas/skill-registry.json`;
- `.agentlas/skill-trials.jsonl`;
- `.agentlas/curator-decisions.jsonl`;
- `.agentlas/super-ontology-contract.json`;
- `.agentlas/super-ontology-replays.jsonl`;
- `.agentlas/super-ontology-evidence.jsonl`;
- runtime adapters and smoke-test docs;
- install or verification scripts;
- public-safety notes if the output is meant for GitHub.

## Mode Rules

`single-agent-creator` produces one installable worker package. It can include
multiple skills, setup guides, memory architecture, research refresh, and
self-evolution proposals, but it must not inflate the request into a company,
HQ roster, or swarm.

`team-builder` produces a multi-role team package. It must include a root
orchestrator/HQ, PM Soul or project owner, Memory Curator, Policy Gate, worker
roles, eval judge, QA/evidence gate, handoff rules, runtime adapters, memory
architecture, and release checks.

`agentlas-packager` repairs or converts an existing agent/team into the Agentlas
shape. It adds canonical core files, `.agentlas` contracts, runtime adapters,
schemas, manifest, install scripts, verification, and public/private cleanup.

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

- Never store secrets, API keys, tokens, private keys, service-account JSON, raw
  logs, or full transcripts in generated repos or memory.
- Do not copy private local research folders into public output.
- Do not call runtime adapters canonical.
- Ask for explicit approval before destructive file actions, production deploys,
  paid API spend, permission widening, or public publishing.
- Public packages must pass `scripts/verify-package.sh` and
  `scripts/public_safety_check.sh` before release.
