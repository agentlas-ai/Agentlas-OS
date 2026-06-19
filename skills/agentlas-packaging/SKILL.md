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
5. Add or repair the global command across Claude Code, Codex, Gemini CLI,
   generic AGENTS.md tools, and terminal adapters.
6. Remove secrets, raw logs, private local notes, and unsafe public paths.
7. Run package verification and public-safety checks before release.

## Output

Return `classification`, `repaired_files`, `agentlas_contracts_added`,
`runtime_adapters`, `global_commands`, `verification`, and `blockers`.
