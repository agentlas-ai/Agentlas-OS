# Agentlas Core Engine Meta-Agent Team

Use root `GEMINI.md` and canonical `AGENTS.md`. This folder exists so Gemini CLI
imports can preserve the same adapter shape as Claude and Codex.

The public route is: mode classification, clarify questions when needed, then
one of the three core builders. Use `.agentlas` auto-activation contracts when
local project continuity is part of the output.

Gemini CLI command files live in the packaged `gemini/extension/commands/`
folder, with optional fallback user commands under `.gemini/commands/`. This
package exposes `/hep-build`, `/hep-network`, and `/hep-cloud`; generated
packages must expose their own command and
report it in `global_commands`.
