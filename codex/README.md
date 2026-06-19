# Codex Adapter

Codex plugins CANNOT register slash commands — the loader reads only
`skills/`, `hooks/`, `.mcp.json`, and `.app.json` from a plugin (no
`commands/` or `prompts/` directory exists in the plugin spec). Hephaestus
therefore exposes one clear Codex product surface in three places:

1. **Skills** (in the plugin): `hephaestus-build`, `hephaestus-network`, and
   `hephaestus-cloud`. Invoke with a `$` mention, browse with `/skills`, or let
   Codex trigger them implicitly from the description.
2. **Custom prompts** (explicit slash surface): `codex/prompts/*.md` are
   copied to `~/.codex/prompts/` by the installer and appear as
   `/prompts:hephaestus-build`, `/prompts:hephaestus-network`, and
   `/prompts:hephaestus-cloud`, with power-user prompts
   `/prompts:hephaestus-search` and `/prompts:hephaestus-call`. Top-level
   files only — Codex ignores subdirectories there.
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
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.7.10/scripts/install-all-runtimes.sh | bash
```

Codex-only manual install:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.7.10
codex plugin add hephaestus@agentlas-core-engine
mkdir -p ~/.codex/prompts
cp codex/prompts/hephaestus-build.md codex/prompts/hephaestus-network.md codex/prompts/hephaestus-cloud.md codex/prompts/hephaestus-search.md codex/prompts/hephaestus-call.md ~/.codex/prompts/
```

The OS-terminal Codex CLI command is singular: `codex plugin`, not
`codex plugins`. Inside the Codex app, use `/plugins` to browse installed
plugins; do not run `/plugin marketplace add` inside the app.

## Use

Open or restart Codex and type:

```text
/prompts:hephaestus-build create a support operations agent
/prompts:hephaestus-network find me an agent for app store reviews
/prompts:hephaestus-cloud use my saved finance analyst agent
/prompts:hephaestus-search find agents for market report research
/prompts:hephaestus-call market-researcher, report-writer {draft a market report brief}
$hephaestus-network   (skill mention; skill picker should show only the three public Hephaestus skills)
```

If an older install still shows `agentlas-meta-agent`, `mode-classification`,
`clarify-question-loop`, or other internal support names, rerun the one-touch
installer above and restart Codex.

After meta-agent generation, the final handoff must include `global_commands`
for the created agent or team. For teams, that command routes to the
orchestrator/HQ.

Local validation from this repository:

```bash
python3 -m json.tool codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json >/dev/null
```
