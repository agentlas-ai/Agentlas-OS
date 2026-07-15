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
| Claude Code | automatic | plugin install (commands + `hephaestus-network` skill) + `~/.claude/commands/*.md`; plugin `SessionStart` and `UserPromptSubmit` hooks inject bounded local ontology recall |
| Codex | automatic | `codex plugin add hephaestus@agentlas-core-engine` (skills — plugins cannot register slash commands) + custom prompts `~/.codex/prompts/` → `/prompts:hep-network` + local MCP in `~/.codex/config.toml`; the mirrored plugin hooks use the same point-of-need recall contract |
| Gemini CLI | automatic (partial) | `gemini extensions install …` (commands TOML + skill) + fallback TOML copied to `~/.gemini/commands/` |
| Antigravity | automatic | global workflow copied to `~/.gemini/antigravity*/global_workflows/`; the installer merges a named `agentlas-memory` `PreInvocation` hook into `~/.gemini/config/hooks.json`, returning `injectSteps[].ephemeralMessage` |
| Grok CLI | automatic with passive-hook limit | global `SessionStart`/`UserPromptSubmit` hooks write a bounded workspace-scoped capsule under `~/.agentlas/runtime-memory-context/grok/`. Grok ignores passive-hook stdout, so a managed block in `~/.grok/AGENTS.md` points the model at the exact-workspace capsule; this is not direct dynamic hook injection. |
| Cursor | automatic | commands → `~/.cursor/commands/` (IDE + `agent` CLI), skill → `~/.cursor/skills/` and `~/.agents/skills/`; `cursor/plugin/` is the marketplace-ready plugin bundle; `cursor/rules/hephaestus.mdc` remains the per-project rule fallback |
| OpenCode | automatic | commands → `~/.config/opencode/commands/` → `/hep-network`; skill via `~/.agents/skills`; MCP via `opencode.json` (see `opencode/README.md`). A dependency-free global plugin uses `chat.message` plus `experimental.chat.system.transform`, and preserves the capsule through `experimental.session.compacting`. |
| OpenClaw | automatic | AgentSkills skill → `~/.openclaw/skills` (or `openclaw skills install --global`); invoke `/skill hephaestus-network <request>`; exec-tool gated on `python3` |
| Hermes Agent | automatic | AgentSkills skill → `~/.hermes/skills/`; MCP server in `~/.hermes/config.yaml` (see `hermes/README.md`) |
| Agentlas native | automatic | Agentlas Terminal and the Agentlas app route plain language through native Agentlas/Hephaestus tools. Build, network, cloud, call, upload, search, research, and Stormbreaker behavior are inferred from context. |
| Terminal shell/debug | automatic | `bin/hep-build`, `bin/hep-network`, `bin/hep-cloud`, `bin/hep-search`, `bin/hep-call`, `bin/hep-upload`, `bin/hep-global`, and `bin/hephaestus` — `hep-build "<request>"` builds, `hep-network "<request>"` borrows Hub agents, `hep-cloud "<request>"` uses the signed-in user's cloud packages, `hep-search "<request>"` compares Cloud/Hub candidates, `hep-upload <agent-folder>` asks Cloud-vs-Hub before any upload, `hep-call "agent-a,agent-b" "<context>"` prepares exact agents, and `hep-global install|status|remove` manages the Codex/Claude/Antigravity global prompt router marker block. Lower-level helpers such as `hep-storm` are for automation/debugging or native tool selection, not the visible external command set. |
| Ollama / Gemma / DeepSeek local models | via harness or MCP | `ollama launch <harness>` then use that harness's surface above; or register `hephaestus mcp serve` (stdio MCP, tools `hephaestus_route` / `hephaestus_network_status`); raw API loops use an OpenAI-`tools` function — see `docs/local-models.md` |
| Generic AGENTS.md runtimes | manual fallback | the AGENTS.md command alias section; the runtime reads AGENTS.md and treats `/hep-*` or `@Hephaestus` as the routing contract |

Realistic limits, stated plainly:

- Codex plugins cannot contribute slash commands (loader reads `skills/`,
  `hooks/`, `.mcp.json`, `.app.json` only) — the explicit slash surface is the
  deprecated-but-functional custom prompts dir, namespaced as
  `/prompts:hep-network`.
- Claude Code and Codex receive real hook-provided `additionalContext` on each
  prompt. Antigravity receives an ephemeral pre-invocation step. OpenCode
  receives a system-prompt transform. Grok lifecycle hooks are passive, so its
  adapter can refresh a local capsule but cannot inject hook stdout directly.
- Memory hooks run only when an ancestor project contains a project ontology
  database or a cryptographically verified routing card whose exact agent
  projection exists. They never read a host transcript, call a server embedding
  API, or create Memory Curator tickets. Project recall is `public`/`internal`;
  private experience is eligible only for that verified exact slug and its
  `hub-agents/<slug>/memory/experience.sqlite` projection.
- The capsule has a deterministic digest and is re-injected at point of need;
  equal digests are one context item, and the newest capsule is re-applied
  after compaction. This supplements `AGENTS.md`/`CLAUDE.md` instead of copying
  their policy text.
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
`network init` (also run by the installer). All runtimes reuse the project
ontology plus the same agent-scoped, rebuildable SQLite projections under
`~/.agentlas/networking/hub-agents/`; no runtime owns a divergent memory copy.
The v1.1.36 install verifies the bundled local Model2Vec asset as the primary
352-dimensional hybrid embedding path. If that asset is absent or rejected,
the capsule reports `retrieval=degraded_hash` and uses local hash-96; it never
downloads a model or sends text to a server.
