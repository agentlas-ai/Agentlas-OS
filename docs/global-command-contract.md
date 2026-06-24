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

Hephaestus has two user-facing surfaces:

- **Agentlas native:** Agentlas Terminal and the Agentlas app accept plain
  language. Native Agentlas/Hephaestus tools infer whether the request needs
  build, network, cloud, call, upload, search, research, or Stormbreaker
  behavior.
- **External LLM hosts:** Claude Code, Codex, Gemini CLI, Antigravity, Cursor,
  OpenCode, and similar plugin/MCP/prompt hosts expose exactly six explicit
  user commands. Stormbreaker, research loadouts, and lower-level route options
  are attached automatically from context.

External LLM hosts expose these commands:

- `/hep-build <request>` — create, repair, or package agents and teams.
- `/hep-network <request>` — borrow public Hub agents into a temporary
  task force.
- `/hep-cloud <request>` — use agents saved or shared through the
  signed-in user's Agentlas Cloud.
- `/hep-search <request>` — compare Cloud and Hub candidates without invoking.
- `/hep-call <slugs> <context>` — prepare explicitly named Hub/cloud agents.
- `/hep-upload <agent-folder>` — ask Cloud-vs-Hub before any upload action.

Network routing is backed by the local-first router
(`docs/hephaestus-network-2.0.md`). Fresh installs expose only the six external
commands above. `hep-storm` and other lower-level controls may remain available
to native tools, MCP tool selection, automation, and debugging, but they are not
part of the visible external command set. Stormbreaker packet auto-run is
available through the runner when routing returns a runnable `execution_fabric`
and `--plan-only` is not present. Required visible external surfaces:

- Claude Code: `.claude/commands/hep-build.md`,
  `.claude/commands/hep-network.md`, `.claude/commands/hep-cloud.md`,
  `.claude/commands/hep-search.md`, `.claude/commands/hep-call.md`, and
  `.claude/commands/hep-upload.md` (+ global copies).
- Codex: `codex/prompts/hep-build.md`,
  `codex/prompts/hep-network.md`, `codex/prompts/hep-cloud.md`,
  `codex/prompts/hep-search.md`, `codex/prompts/hep-call.md`, and
  `codex/prompts/hep-upload.md`.
- Gemini CLI: `gemini/extension/commands/hep-build.toml`,
  `hep-network.toml`, `hep-cloud.toml`, `hep-search.toml`, `hep-call.toml`,
  and `hep-upload.toml` (+ `~/.gemini/commands/` fallbacks).
- Antigravity: `antigravity/workflows/hep-build.md`,
  `hep-network.md`, `hep-cloud.md`, `hep-search.md`, `hep-call.md`, and
  `hep-upload.md`
  (+ `~/.gemini/antigravity*/global_workflows/`).
- Cursor: command files under `cursor/plugin/commands/hep-*.md`, with
  `cursor/rules/hephaestus.mdc` as the per-project fallback — reacts to
  the six `/hep-*` commands and `@Hephaestus`.
- Terminal shell/debug: `hep-build "<request>"` is the build alias,
  `hep-network "<request>"` is the standalone Hub-only Network alias,
  `hep-cloud "<request>"` is the cloud/share surface, `hep-search` compares
  Cloud/Hub candidates, `hep-call` prepares exact named agents, and
  `hep-upload <agent-folder>` asks Cloud-vs-Hub first. Native Agentlas Terminal
  should prefer plain language over exposing these as required commands.
  `hep-storm` is a lower-level automation helper.
- Generic AGENTS.md / local-model runtimes: see
  `docs/runtime-fallback-adapters.md`.

Install and upgrade must run `hephaestus network init` (idempotent) so the
global `~/.agentlas/networking/` structure exists before the first routed call.
