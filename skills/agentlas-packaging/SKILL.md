---
name: agentlas-packaging
description: "Use when converting, repairing, or packaging an existing local or external agent/team into Agentlas architecture for local install, Agentlas import, Codex plugin use, Claude adapter use, or open-source release."
---

# Agentlas Packaging

## Procedure

1. Inspect the existing source: prompt, repo, ZIP, runtime folder, skill, command,
   or generated agent package.
2. Classify it as single-agent, team-builder, or mixed/unclear.
3. Run `docs/builder-interview-research-gate.md` when the source behavior,
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
   `routing_ready` without the block. Use ONLY the pinned ontology
   (`agentlas_cloud/workforce/ontology_v1.json`, awo:2026-07-15.2):
   - `roles`: 0-2 `role:*` ids, only when the agent genuinely performs that
     professional role — most niche agents fit none, and `[]` is honest;
   - `communities`: 1-3 `community:*` ids the work belongs to;
   - `modalities`: what it consumes/produces (`text` alone for text-only);
   - `languages`: languages it actually works in (public v1 language ids).
   Never invent ids outside the pinned vocabulary; the lint rejects them.
6. Add or repair the global command across Claude Code, Codex, Gemini CLI,
   generic AGENTS.md tools, and terminal adapters.
7. Remove secrets, raw logs, private local notes, and unsafe public paths.
8. Run `scripts/verify-team-package.sh <package-root>` after repair. If it
   fails, correct the package shape before any final handoff.
9. Run package verification and public-safety checks before release.

## Output

Return `classification`, `repaired_files`, `agentlas_contracts_added`,
`runtime_adapters`, `global_commands`, `verification`, and `blockers`.
