# Runtime Matrix

| Runtime | Entry Point | Global Command | Adapter Files | Memory Access | Verification |
| --- | --- | --- | --- | --- | --- |
| Codex | {{codex_entry}} | /{{COMMAND_SLUG}} | {{codex_files}} | {{codex_memory}} | {{codex_verify}} |
| Claude Code | {{claude_entry}} | /{{COMMAND_SLUG}} | {{claude_files}} | {{claude_memory}} | {{claude_verify}} |
| Gemini CLI | {{gemini_entry}} | /{{COMMAND_SLUG}} | {{gemini_files}} | {{gemini_memory}} | {{gemini_verify}} |
| Antigravity | antigravity/workflows/{{COMMAND_SLUG}}.md | /{{COMMAND_SLUG}} | antigravity/workflows/, .agents/workflows/ | Reads AGENTS.md and .agentlas/ contracts | scripts/verify-package.sh |
| Generic | AGENTS.md | /{{COMMAND_SLUG}} | AGENTS.md | local project files | scripts/verify-package.sh |

All runtimes share the same behavior-quality artifacts:
`docs/builder-interview.md`, `docs/research-sources.md`,
`docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
`docs/prompt-performance-contract.md`, and
`.agentlas/capability-eval-plan.json`.
