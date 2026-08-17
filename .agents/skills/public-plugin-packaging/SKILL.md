---
name: public-plugin-packaging
description: "Use when packaging an Agentlas agent repo for public GitHub release, Codex plugin submission, Claude adapter distribution, or one-line terminal installation."
---

# Public Plugin Packaging

## Checklist

- `codex/marketplace.json` exists.
- Codex plugin has `.codex-plugin/plugin.json`.
- Codex plugin includes at least one `SKILL.md`.
- Codex plugin includes `commands/<slug>.md` for the package command.
- `.claude/commands/meta-agent.md` exists.
- `.claude/commands/<slug>.md` exists for the package command.
- `.claude/agents/agentlas-core-engine-meta-agent.md` exists.
- `.claude/skills/agentlas-core-engine-meta-agent/SKILL.md` exists.
- `.gemini/commands/<slug>.toml` exists for Gemini CLI custom commands.
- `.agentlas/global-commands.json` exists and final handoff includes
  `global_commands`.
- `scripts/install.sh` supports one-line installation.
- `scripts/verify-package.sh` passes.
- `scripts/public_safety_check.sh` passes.

## Public Boundary

Publish schemas, templates, prompts, and adapters. Do not publish hosted service
secrets, private research notes, raw logs, or local machine paths.
