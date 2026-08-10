# OpenCode Adapter

OpenCode reads three Hephaestus surfaces — all installed by
`scripts/install-all-runtimes.sh`:

1. **Commands** — `commands/*.md` here are copied to
   `~/.config/opencode/commands/`, giving `/hep-build`,
   `/hep-network`, `/hep-local`, `/hep-cloud`, and `/hep-hub` in the OpenCode
   TUI.
2. **Skills** — OpenCode natively loads `~/.agents/skills/hephaestus-network/`
   and `~/.agents/skills/hephaestus-cloud/`, so routing also triggers
   implicitly via the `skill` tool.
3. **MCP** — for tool-level access (works with any model, including local
   Ollama models), register the stdio server in `opencode.json`:

```json
{
  "mcp": {
    "hephaestus-network": {
      "type": "local",
      "command": ["~/.agentlas/runtime/current/bin/hephaestus", "mcp", "serve"],
      "enabled": true
    }
  }
}
```

`hephaestus-network` is the only host-visible Workforce MCP. It exposes
`workforce.search_candidates`, `workforce.validate_selection`, and
`workforce.prepare_execution`; Core owns Cloud/Hub upstream calls. The
installer removes an old direct `agentlas` entry to prevent duplicate tools
from bypassing local federation and privacy governance.

The installed `/hep-*` OpenCode commands include the app-host auto-update
preflight. When OpenCode can run local shell commands, Hephaestus refreshes
`~/.agentlas/runtime/current` and existing adapters from inside the app before
resolving the runner.

Manual install without the one-touch script:

```bash
mkdir -p ~/.config/opencode/commands
cp opencode/commands/hep-build.md opencode/commands/hep-network.md opencode/commands/hep-local.md opencode/commands/hep-cloud.md opencode/commands/hep-hub.md ~/.config/opencode/commands/
mkdir -p ~/.agents/skills
cp -R skills/hephaestus-network ~/.agents/skills/
cp -R skills/hephaestus-cloud ~/.agents/skills/
```

## Agentlas One session checkpoint

`plugins/agentlas-memory.js` does two jobs: it injects the bounded ontology
capsule into the system prompt, and it runs the Agentlas One memory checkpoint
when a session ends.

OpenCode never hands a plugin a transcript path, so the checkpoint passes the
assistant text it already holds to the runtime as `assistant_texts` instead of
a file. Collection does not depend on event names: the role arrives on
`message.updated` and the text on `message.part.updated`, linked only by
`messageID`, so assistant ownership is inherited by message id. `session.idle`
is the single event name the plugin relies on.

Only text the assistant wrote is collected — an envelope a user pastes into a
prompt is never harvested. Measured against OpenCode 1.18.16.
