# Hermes Agent Adapter

Nous Research's Hermes Agent reads AgentSkills-spec skills from
`~/.hermes/skills/`. `scripts/install-all-runtimes.sh` copies the canonical
`skills/hephaestus-network/` there when `~/.hermes` exists.

Manual install:

```bash
mkdir -p ~/.hermes/skills
cp -R skills/hephaestus-network ~/.hermes/skills/
```

For tool-level access (recommended when running local models through Ollama),
register the stdio MCP server in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  hephaestus-network:
    command: ~/.agentlas/runtime/current/bin/hephaestus
    args: [mcp, serve]
```

Then `hephaestus_route` and `hephaestus_network_status` appear as tools, and
the skill instructs the model to use them when shell access is unavailable.

The installed Hermes skills include the app-host auto-update preflight. When
Hermes can run local commands, Hephaestus refreshes
`~/.agentlas/runtime/current` from inside Hermes before resolving the runner.
