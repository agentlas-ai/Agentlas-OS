# Codex Adapter

Codex plugins CANNOT register slash commands — the loader reads only
`skills/`, `hooks/`, `.mcp.json`, and `.app.json` from a plugin (no
`commands/` or `prompts/` directory exists in the plugin spec). Hephaestus
therefore exposes one clear Codex product surface in three places:

1. **Compatibility skills** (in the plugin): `hephaestus-build`,
   `hephaestus-network`, and `hephaestus-cloud`. Codex may trigger them
   implicitly from the description.
2. **Custom prompts** (explicit slash surface): `codex/prompts/*.md` are
   copied to `~/.codex/prompts/` by the installer and appear as
   `/prompts:hep-build`, `/prompts:hep-network`, and
   `/prompts:hep-cloud`, with power-user prompts
   `/prompts:hep-search`, `/prompts:hep-call`, `/prompts:hep-upload`, and
   `/prompts:hep-connect`.
   Top-level
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
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```

Inside the Codex app, `/prompts:hep-build`, `/prompts:hep-network`,
`/prompts:hep-cloud`, `/prompts:hep-search`, `/prompts:hep-call`,
`/prompts:hep-upload`, and `/prompts:hep-connect` first run the app-host auto-update preflight when Codex
has local command execution. That preflight refreshes
`~/.agentlas/runtime/current` and installed prompt/plugin surfaces without
asking the user to open a separate terminal. If this Codex install is too old to
contain the preflight, run the one-command installer once or refresh the plugin
from the plugin manager.

Codex-only manual install:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v1.1.4
codex plugin add hephaestus@agentlas-core-engine
mkdir -p ~/.codex/prompts
cp codex/prompts/hep-build.md codex/prompts/hep-network.md codex/prompts/hep-cloud.md codex/prompts/hep-search.md codex/prompts/hep-call.md codex/prompts/hep-upload.md codex/prompts/hep-connect.md ~/.codex/prompts/
```

The OS-terminal Codex CLI command is singular: `codex plugin`, not
`codex plugins`. Inside the Codex app, use `/plugins` to browse installed
plugins; do not run `/plugin marketplace add` inside the app.

## Use

Open or restart Codex and type:

```text
/prompts:hep-build create a support operations agent
/prompts:hep-network find me an agent for app store reviews
/prompts:hep-cloud use my saved finance analyst agent
/prompts:hep-search find agents for market report research
/prompts:hep-call market-researcher, report-writer {draft a market report brief}
/prompts:hep-upload ./agents/customer-support-hq
/prompts:hep-connect Telegram for Marketing Agent Team
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
