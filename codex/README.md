# Codex Adapter

Codex plugins CANNOT register slash commands — the loader reads only
`skills/`, `hooks/`, `.mcp.json`, and `.app.json` from a plugin (no
`commands/` or `prompts/` directory exists in the plugin spec). Hephaestus
therefore exposes three Codex surfaces:

1. **Skills** (in the plugin): `hephaestus-network`,
   `agentlas-core-engine-meta-agent`, and the supporting skills. Invoke with a
   `$` mention (`$hephaestus-network`), browse with `/skills`, or let Codex
   trigger them implicitly from the description.
2. **Custom prompts** (explicit slash surface): `codex/prompts/*.md` are
   copied to `~/.codex/prompts/` by the installer and appear as
   `/prompts:hephaestus` and `/prompts:hephaestus-network`. Top-level files
   only — Codex ignores subdirectories there.
3. **MCP**: the installer registers the local stdio server
   (`hephaestus mcp serve`) as `mcp_servers.hephaestus-network` in
   `~/.codex/config.toml`, exposing the `hephaestus_route` and
   `agentlas_authenticate` tools. First use opens the browser sign-in if the
   local Agentlas sign-in is not ready yet.

## Install

On a fresh Mac, install Apple Command Line Tools first if `git` is
unavailable:

```bash
xcode-select --install
git --version
```

One-command install or update for every supported runtime:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.6.1/scripts/install-all-runtimes.sh | bash
```

Codex-only manual install:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.6.1
codex plugin add hephaestus@agentlas-core-engine
cp codex/prompts/*.md ~/.codex/prompts/
```

The OS-terminal Codex CLI command is singular: `codex plugin`, not
`codex plugins`. Inside the Codex app, use `/plugins` to browse installed
plugins; do not run `/plugin marketplace add` inside the app.

## Use

Open or restart Codex and type:

```text
/prompts:hephaestus-network find me an agent for app store reviews
/prompts:hephaestus ontology
$hephaestus-network   (skill mention; implicit triggering also works)
```

If an older install still shows `agentlas-meta-agent`, rerun the one-touch
installer above.

After meta-agent generation, the final handoff must include `global_commands`
for the created agent or team. For teams, that command routes to the
orchestrator/HQ.

Local validation from this repository:

```bash
python3 -m json.tool codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json >/dev/null
```
