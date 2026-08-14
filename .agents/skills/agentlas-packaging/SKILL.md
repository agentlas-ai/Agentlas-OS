---
name: agentlas-packaging
description: "Use when converting, repairing, or packaging an existing local or external agent/team into Agentlas architecture for local install, Agentlas import, Codex plugin use, Claude adapter use, or open-source release."
---

# Agentlas Packaging

## Procedure

1. Inspect the existing source: prompt, repo, ZIP, runtime folder, skill, command,
   or generated agent package.
2. Classify it as single-agent, team-builder, or mixed/unclear.
3. Run `contracts/builder-interview-research-gate.md` when the source behavior,
   target user, tools/plugins, output artifacts, or evaluation bar are unclear.
   Packaging must not turn a shallow prompt into a polished but weak package.
   When the gate runs, research official sources, similar agent repositories or
   comparables, academic/professional theory, and plugin docs before changing
   the source behavior.
4. Preserve useful behavior while adding Agentlas contracts:
   - `AGENTS.md`;
   - `docs/builder-interview.md`;
   - `docs/research-sources.md`;
   - `docs/tool-selection.md`;
   - `docs/domain-expert-synthesis.md`;
   - `docs/prompt-performance-contract.md`;
   - `.agentlas/capability-eval-plan.json`;
   - `.agentlas/agent-card.json`;
   - `.agentlas/company-blueprint.json`;
   - `.agentlas/mode-map.json`;
   - `.agentlas/memory-map.json`;
   - `.agentlas/memory-tickets.jsonl`;
   - `.agentlas/vault-references.json`;
   - `.agentlas/global-commands.json`;
   - runtime adapters;
   - verification scripts.
5. Author the workforce résumé block on the routing card (`workforce` on
   `.agentlas/agent-card.json` / the marketplace routing card). The hub
   Workforce search matches on exactly these fields; a card without them is
   invisible to every WorkOrder that uses them, and `card lint` blocks
   `routing_ready` without the block. Use the versioned ontology graph contract
   (`agentlas_cloud/workforce/ontology_v1.json`, awo:2026-07-15.2) for seed
   aliases and relation semantics, never as an allowlist:
   - `roles`: 0-4 open `role:*` professional-responsibility ids;
   - `communities`: 1-5 open `community:*` professional-domain ids;
   - `skills`: 3-12 open `skill:*` verb-object capability ids;
   - `knowledge`: open `knowledge:*` domain/method ids backed by the package;
   - `modalities`: optional non-text input/output metadata;
   - `languages`: optional genuine delivery languages, never listing locales.
   New well-formed semantic IDs are valid graph concepts and must not be
   rejected merely because the seed snapshot has not seen them before.
6. Add or repair the global command across Claude Code, Codex, Gemini CLI,
   generic AGENTS.md tools, and terminal adapters.
7. Remove secrets, raw logs, private local notes, and unsafe public paths.
8. Run `scripts/verify-team-package.sh <package-root>` after repair. If it
   fails, correct the package shape before any final handoff.
9. Run package verification and public-safety checks before release.

## Output

Return `classification`, `repaired_files`, `agentlas_contracts_added`,
`runtime_adapters`, `global_commands`, `verification`, and `blockers`.
