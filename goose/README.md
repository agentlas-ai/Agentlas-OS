# goose Adapter

Block's goose reads the project `AGENTS.md` natively (the Linux Foundation
AGENTS.md standard), so the canonical routing instructions need no
goose-specific copy.

The only goose-native global surface is the MCP extension table. For
tool-level Workforce access, register the local stdio server in
`~/.config/goose/config.yaml`:

```yaml
extensions:
  hephaestus-network:
    enabled: true
    type: stdio
    cmd: ~/.agentlas/runtime/current/bin/hephaestus
    args: [mcp, serve]
    timeout: 300
```

`hephaestus-network` is the only host-visible Workforce MCP. It exposes
`workforce.search_candidates`, `workforce.validate_selection`, and
`workforce.prepare_execution`; Core owns Cloud/Hub upstream calls.

`scripts/install-all-runtimes.sh` writes this extension only when
`~/.config/goose/config.yaml` does not exist yet. An existing YAML config is
never rewritten by the installer — add the block above manually (or via
`goose configure`).

## Agentlas One session checkpoint

`plugins/agentlas-one/hooks/hooks.json` is installed to
`~/.agents/plugins/agentlas-one/`, the user-scoped goose plugin location. goose
uses the same hook manifest shape as Claude Code, so the pack declares a single
`SessionEnd` command.

goose reports `session_id` and `working_dir` but no transcript path, so the
runtime resolves the session file under `~/.local/share/goose/sessions/`. That
directory layout was confirmed on goose 1.45.0; the file format itself has not
been verified against a live session, and an unreadable or unfamiliar file
harvests nothing rather than guessing. `agentlas-one off` removes the plugin.
