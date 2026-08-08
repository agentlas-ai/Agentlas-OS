# Amp Adapter

Sourcegraph Amp reads the project `AGENTS.md` natively (the Linux Foundation
AGENTS.md standard), so the canonical routing instructions need no
Amp-specific copy.

The only Amp-native global surface is MCP. `scripts/install-all-runtimes.sh`
registers the local stdio server merge-safely in `~/.config/amp/settings.json`
(the installer writes the absolute runner path and preserves every unrelated
setting):

```json
{
  "amp.mcpServers": {
    "hephaestus-network": {
      "command": "~/.agentlas/runtime/current/bin/hephaestus",
      "args": ["mcp", "serve"]
    }
  }
}
```

`hephaestus-network` is the only host-visible Workforce MCP. It exposes
`workforce.search_candidates`, `workforce.validate_selection`, and
`workforce.prepare_execution`; Core owns Cloud/Hub upstream calls.
