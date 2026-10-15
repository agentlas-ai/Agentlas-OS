---
name: llm-runtime-architecture
description: "Use when designing how one canonical agent core runs across Codex, Claude Code, Antigravity, Cursor, and AGENTS.md-compatible tools."
---

# LLM Runtime Architecture

## Procedure

1. Keep `AGENTS.md` as the canonical behavior contract.
2. For each runtime, name entry point, global command, adapter files, available
   tools, memory access, limitations, and verification command.
3. Keep adapters thin and point them back to the canonical core.
4. Write or repair `.agentlas/global-commands.json` when creating or packaging
   an agent.
5. State unsupported capabilities explicitly.

## Output

Return a runtime matrix with `runtime`, `entry_point`, `global_command`,
`adapter_files`, `memory_access`, `limitations`, and `verification`.
