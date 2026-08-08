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
