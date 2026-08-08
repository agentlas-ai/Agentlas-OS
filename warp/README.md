# Warp Adapter

Warp's agent reads the project `AGENTS.md` natively (the Linux Foundation
AGENTS.md standard), so the canonical routing instructions need no
Warp-specific copy.

The Warp-native surface is workflows. `scripts/install-all-runtimes.sh`
copies `workflows/hep-network.yaml` to `~/.warp/workflows/`, which surfaces
`hep-network` in Warp's command palette and workflow search. The workflow
shells out to the installed `hep-network` command (`~/.local/bin/hep-network`).

Manual install:

```bash
mkdir -p ~/.warp/workflows
cp warp/workflows/hep-network.yaml ~/.warp/workflows/
```

Warp manages MCP servers in-app, not in an editable config file. If you add
one there, register only the local `hephaestus-network` entry:
`~/.agentlas/runtime/current/bin/hephaestus mcp serve`. It is the only
host-visible Workforce MCP; Core owns Cloud/Hub upstream calls.
