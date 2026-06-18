# Global Command Contract

Every Agentlas-created or Agentlas-packaged agent must receive a canonical
global command during creation. The command is part of the generated package,
not an optional README note.

## Required Behavior

1. Choose one canonical command from the package slug, for example
   `/research-agent`, `/wedding`, or `/hephaestus`.
2. Write `.agentlas/global-commands.json` with the command, runtime adapters,
   install locations, and post-creation user message template.
3. Add native command files for runtimes that support them.
4. Add adapter command aliases for runtimes whose command model is prompt or
   context-file based.
5. After generating or packaging the agent, tell the user the command for every
   supported runtime before closing the task.

## Required Runtime Surfaces

| Runtime | Required command surface |
| --- | --- |
| Claude Code | `.claude/commands/<slug>.md` plus global install path `~/.claude/commands/<slug>.md` |
| Codex | `codex/plugins/<package-id>/commands/<slug>.md` when packaging a plugin |
| Gemini CLI | `gemini/extension/commands/<slug>.toml` in a Gemini extension plus fallback global install path `~/.gemini/commands/<slug>.toml` |
| Antigravity | `antigravity/workflows/<slug>.md` plus global install path `~/.gemini/antigravity/global_workflows/<slug>.md`, with project fallback `.agents/workflows/<slug>.md` |
| Cursor or AGENTS.md tools | `AGENTS.md` command section and optional `.cursor/` adapter when requested |
| Agentlas terminal | shell entry under `bin/` or documented `agentlas run <slug>` entry |

The same canonical slash command should be used wherever the runtime supports a
slash command. When a runtime does not expose native slash commands, the adapter
must still name the same command and state the exact invocation path.

## Single Agent Rule

Single-agent packages expose one public command for that worker. Extra helper
commands are allowed only when they are specific operational actions such as
`/research-agent refresh`.

## Team Rule

Team packages expose one public command for the orchestrator/HQ. Worker agents
are routed through HQ by default and should not each become separate global
commands unless the user explicitly asks for direct worker invocation.

## Required Post-Creation Message

The final response for a generated or packaged agent must include a
`global_commands` section with at least:

```text
global_commands:
- Claude Code: /<slug> (global file: ~/.claude/commands/<slug>.md)
- Codex: /<slug> (plugin command: codex/plugins/<package-id>/commands/<slug>.md)
- Gemini CLI: /<slug> (extension command: gemini/extension/commands/<slug>.toml; fallback global file: ~/.gemini/commands/<slug>.toml)
- Antigravity: /<slug> (global workflow: ~/.gemini/antigravity/global_workflows/<slug>.md; project workflow: .agents/workflows/<slug>.md)
- Agentlas terminal: <slug> or agentlas run <slug>
```

If a runtime was not generated, say `not generated` and give the reason. Do not
leave the user guessing how to run the agent after creation.

## Hephaestus Network 2.0 additions

Every package now exposes a second canonical command,
`/hephaestus-network <request>` (alias `@Hephaestus <request>`), backed by the
local-first router (`docs/hephaestus-network-2.0.md`). Required surfaces:

- Claude Code: `.claude/commands/hephaestus-network.md` (+ global symlink).
- Codex: `codex/plugins/<package-id>/commands/hephaestus-network.md`.
- Gemini CLI: `gemini/extension/commands/hephaestus-network.toml`
  (+ `~/.gemini/commands/hephaestus-network.toml` fallback).
- Antigravity: `antigravity/workflows/hephaestus-network.md`
  (+ `~/.gemini/antigravity*/global_workflows/`).
- Cursor (no custom slash commands): `cursor/rules/hephaestus.mdc` copied into
  `<project>/.cursor/rules/` — reacts to `/hephaestus*` and `@Hephaestus`.
- Terminal: `Hephaestus "<request>"` is the human-facing alias for
  `bin/hephaestus route "<request>"`; `hephaests-network "<request>"` is the
  standalone Hub-only Network alias.
- Generic AGENTS.md / local-model runtimes: see
  `docs/runtime-fallback-adapters.md`.

Install and upgrade must run `hephaestus network init` (idempotent) so the
global `~/.agentlas/networking/` structure exists before the first routed call.
