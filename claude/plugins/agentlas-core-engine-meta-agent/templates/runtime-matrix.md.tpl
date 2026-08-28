# Runtime Matrix

| Runtime | Registered syntax / Global Command | Live executor/action | Adapter Files | Memory Access | Verification |
| --- | --- | --- | --- | --- | --- |
| Codex | /{{COMMAND_SLUG}} | {{codex_entry}} | {{codex_files}} | {{codex_memory}} | {{codex_verify}} |
| Claude Code | /{{COMMAND_SLUG}} | {{claude_entry}} | {{claude_files}} | {{claude_memory}} | {{claude_verify}} |
| Gemini CLI | /{{COMMAND_SLUG}} | {{gemini_entry}} | {{gemini_files}} | {{gemini_memory}} | {{gemini_verify}} |
| Antigravity | /{{COMMAND_SLUG}} | antigravity/workflows/{{COMMAND_SLUG}}.md | antigravity/workflows/, .agents/workflows/ | Reads AGENTS.md and .agentlas/ contracts | scripts/verify-package.sh |
| Generic | /{{COMMAND_SLUG}} identity in AGENTS.md | Host interprets AGENTS.md; no installed executable is implied | AGENTS.md | local project files | scripts/verify-package.sh |

All runtimes share the same behavior-quality artifacts:
`docs/builder-interview.md`, `docs/research-sources.md`,
`docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
`docs/prompt-performance-contract.md`, and
`.agentlas/capability-eval-plan.json`.
