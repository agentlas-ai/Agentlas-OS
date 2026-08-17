# Grok Build Adapter

xAI's [Grok Build](https://docs.x.ai/build/overview) CLI is Claude Code
marketplace-compatible: it reads `.claude-plugin/marketplace.json` and the
plugin's `commands/` directory the same way Claude Code does, alongside its
own `.grok/` conventions. This repo does not need a separate
`grok/commands/` tree — the canonical command bodies at
`claude/plugins/agentlas-core-engine-meta-agent/commands/hep-*.md` and
`agentlas-*.md` are already the Grok surface. Duplicating them here would
create a second copy that can drift from the Claude one; `AGENTS.md` at the
repo root stays the single canonical source per command.

This folder only carries what is genuinely Grok-specific:

- `agentlas-memory-rule.md` — the memory/recall rule Grok reads.
- `hooks/agentlas-memory.json` — the `SessionStart`/`UserPromptSubmit` memory
  hook wiring (`--host grok`).

## Install / update

```bash
grok marketplace add https://github.com/agentlas-ai/Agentlas-OS
grok plugin install hephaestus@agentlas-core-engine
```

If you added the marketplace before, Grok pins the commit it first saw —
new commands (like `/agentlas-build`) will not appear until you refresh:

```bash
grok marketplace update agentlas-core-engine
```

`/hep-build`, `/hep-network`, `/hep-storm`, `/hep-cloud`, `/hep-search`,
`/hep-browser`, `/hep-call`, `/hep-upload`, `/hep-connect`, `/agentlas`, and
the `/agentlas-<verb>` aliases all come from the same plugin source Claude
Code uses — no Grok-only build step is required.
