# Cursor Adapter

Since Cursor 2.5, plugins (`.cursor-plugin/plugin.json`) bundle commands,
skills, and rules. This adapter provides both the plugin layout and loose
files:

- `plugin/` — Cursor plugin: `/hep-build`, `/hep-network`, `/hep-local`,
  `/hep-cloud`, and `/hep-hub` commands + the `hephaestus-network` and
  `hephaestus-cloud` skills + the routing rule.
- `rules/hephaestus.mdc` — standalone rule for projects that copy rules
  directly into `.cursor/rules/`.

`scripts/install-all-runtimes.sh` installs the global surfaces:

- commands → `~/.cursor/commands/`
- skill → `~/.cursor/skills/hephaestus-network/` (and `~/.agents/skills/`,
  which Cursor also reads)

Manual install:

```bash
mkdir -p ~/.cursor/commands ~/.cursor/skills
cp cursor/plugin/commands/hep-build.md cursor/plugin/commands/hep-network.md cursor/plugin/commands/hep-local.md cursor/plugin/commands/hep-cloud.md cursor/plugin/commands/hep-hub.md ~/.cursor/commands/
cp -R skills/hephaestus-network ~/.cursor/skills/
cp -R skills/hephaestus-cloud ~/.cursor/skills/
```

The Cursor CLI (`agent`) reads the same rules, skills, AGENTS.md, and
`~/.cursor/mcp.json`. The installer registers only local
`hephaestus-network`, whose public staffing tools are
`workforce.search_candidates`, `workforce.validate_selection`, and
`workforce.prepare_execution`. It removes an old direct `agentlas` entry so
the host cannot bypass Core's federation/privacy boundary. See
`docs/local-models.md`.

Automatic updates are off by default. Run `hephaestus features on auto-update`
to enable them, or `hephaestus update` to update manually.
