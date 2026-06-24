# Runtime registration and fallback adapters

How `/hep-build`, `/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, and
`/hep-upload` get registered per external LLM runtime, and what to do where
automatic command registration is not possible. Agentlas Terminal and the
Agentlas app are native surfaces: users should be able to describe the task in
plain language without typing a Hephaestus command.

Two universal surfaces underpin everything (installed by the one-touch
installer):

- **Runtime home** — `~/.agentlas/runtime/current/bin/hephaestus` is the
  runtime-neutral runner every adapter resolves first.
- **Universal skill** — `~/.agents/skills/hephaestus-network/SKILL.md`
  (AgentSkills spec) is read natively by Codex, OpenCode, OpenClaw, Cursor,
  and Crush.

| Runtime | Registration | Mechanism |
|---------|--------------|-----------|
| Claude Code | automatic | plugin install (commands + `hephaestus-network` skill) + `~/.claude/commands/*.md` |
| Codex | automatic | `codex plugin add hephaestus@agentlas-core-engine` (skills — plugins cannot register slash commands) + custom prompts `~/.codex/prompts/` → `/prompts:hep-network` + local MCP in `~/.codex/config.toml` |
| Gemini CLI | automatic (partial) | `gemini extensions install …` (commands TOML + skill) + fallback TOML copied to `~/.gemini/commands/` |
| Antigravity | automatic | global workflow copied to `~/.gemini/antigravity*/global_workflows/` |
| Cursor | automatic | commands → `~/.cursor/commands/` (IDE + `agent` CLI), skill → `~/.cursor/skills/` and `~/.agents/skills/`; `cursor/plugin/` is the marketplace-ready plugin bundle; `cursor/rules/hephaestus.mdc` remains the per-project rule fallback |
| OpenCode | automatic | commands → `~/.config/opencode/commands/` → `/hep-network`; skill via `~/.agents/skills`; MCP via `opencode.json` (see `opencode/README.md`) |
| OpenClaw | automatic | AgentSkills skill → `~/.openclaw/skills` (or `openclaw skills install --global`); invoke `/skill hephaestus-network <request>`; exec-tool gated on `python3` |
| Hermes Agent | automatic | AgentSkills skill → `~/.hermes/skills/`; MCP server in `~/.hermes/config.yaml` (see `hermes/README.md`) |
| Agentlas native | automatic | Agentlas Terminal and the Agentlas app route plain language through native Agentlas/Hephaestus tools. Build, network, cloud, call, upload, search, research, and Stormbreaker behavior are inferred from context. |
| Terminal shell/debug | automatic | `bin/hep-build`, `bin/hep-network`, `bin/hep-cloud`, `bin/hep-search`, `bin/hep-call`, `bin/hep-upload`, and `bin/hephaestus` — `hep-build "<request>"` builds, `hep-network "<request>"` borrows Hub agents, `hep-cloud "<request>"` uses the signed-in user's cloud packages, `hep-search "<request>"` compares Cloud/Hub candidates, `hep-upload <agent-folder>` asks Cloud-vs-Hub before any upload, and `hep-call "agent-a,agent-b" "<context>"` prepares exact agents. Lower-level helpers such as `hep-storm` are for automation/debugging or native tool selection, not the visible external command set. |
| Ollama / Gemma / DeepSeek local models | via harness or MCP | `ollama launch <harness>` then use that harness's surface above; or register `hephaestus mcp serve` (stdio MCP, tools `hephaestus_route` / `hephaestus_network_status`); raw API loops use an OpenAI-`tools` function — see `docs/local-models.md` |
| Generic AGENTS.md runtimes | manual fallback | the AGENTS.md command alias section; the runtime reads AGENTS.md and treats `/hep-*` or `@Hephaestus` as the routing contract |

Realistic limits, stated plainly:

- Codex plugins cannot contribute slash commands (loader reads `skills/`,
  `hooks/`, `.mcp.json`, `.app.json` only) — the explicit slash surface is the
  deprecated-but-functional custom prompts dir, namespaced as
  `/prompts:hep-network`.
- Cursor command files are plain Markdown with no templating; arguments typed
  after the command are appended to the prompt automatically.
- AGENTS.md-only runtimes still cannot register slash commands — the fallback
  is an instructions file, copied per project.
- Local model runtimes vary; the universal contract is: (1) read AGENTS.md or
  the skill, (2) call `hephaestus route` (shell) or `hephaestus_route` (MCP),
  (3) honor the decision JSON. The router does not execute tools; host runtime
  permissions apply when an agent actually acts.
- If command registration fails anywhere, the terminal shell/debug form works:
  `hep-build "<request>"`, `hep-network "<request>"`, or
  `hep-cloud "<request>"`.

First-use memory behavior: whichever runtime calls the router first triggers
`network init` (also run by the installer). All later calls from any runtime
reuse the same `~/.agentlas/networking/` — one local memory map, no per-runtime
copies.
