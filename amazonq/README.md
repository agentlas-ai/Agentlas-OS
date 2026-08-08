# Amazon Q Adapter

Amazon Q Developer CLI reads the project `AGENTS.md` natively (the Linux
Foundation AGENTS.md standard), so the canonical routing instructions need no
Q-specific copy.

The only Q-native global surface is MCP. `scripts/install-all-runtimes.sh`
registers the local stdio server merge-safely in `~/.aws/amazonq/mcp.json`
(the installer writes the absolute runner path and preserves every unrelated
server):

```json
{
  "mcpServers": {
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
