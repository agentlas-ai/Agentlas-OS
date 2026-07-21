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
   `/prompts:hep-build`, `/prompts:hep-network`, `/prompts:hep-local`,
   `/prompts:hep-cloud`, and `/prompts:hep-hub`, with power-user prompts
   `/prompts:hep-search`, `/prompts:hep-call`, `/prompts:hep-upload`, and
   `/prompts:hep-connect`.
   Top-level
   files only — Codex ignores subdirectories there.
3. **MCP**: the installer registers the local stdio server
   (`hephaestus mcp serve`) as `mcp_servers.hephaestus-network` in
   `~/.codex/config.toml`. It is the only host-visible Workforce MCP and
   exposes `workforce.search_candidates`, `workforce.validate_selection`, and
   `workforce.prepare_execution`. Core performs authenticated Cloud/Hub calls
   internally; do not also register a direct remote `agentlas` MCP.

## Install

On a fresh Mac, install Apple Command Line Tools first if `git` is
unavailable:

```bash
xcode-select --install
git --version
```

One-command install or update for every supported runtime:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

Optional global router prompt block:

```bash
hep-global install --target codex
```

This appends a managed Hephaestus block to `~/.codex/AGENTS.md`, so ordinary
Codex prompts use Network federation unless the request explicitly names
Local, Cloud, or Hub. Exact scopes never widen. If a requested source is
blocked by credits, entitlement, availability, or fit, Codex reports that
boundary. Codex should announce final workers as `Agents used: ...` in English
contexts or `사용 에이전트: ...` in Korean contexts, not as `hep-network`. Use
`hep-global remove --target codex` to remove only that managed block.

Codex global router commands:

| Command | What it does |
| --- | --- |
| `hep-global install --target codex` | Install or refresh only `~/.codex/AGENTS.md`. |
| `hep-global status --target codex` | Check whether the Codex router block is installed. |
| `hep-global remove --target codex` | Remove only the managed Codex router block. |
| `hep-global install --target codex --dry-run` | Preview the Codex edit without writing files. |
| `hep-global install --target codex --no-backup` | Edit without writing a timestamped backup. |
| `hephaestus global install --target codex` | Same command through the main runner. |
| `~/.agentlas/runtime/current/bin/hephaestus global status --target codex` | Use the installed runtime directly when `hep-global` is not on `PATH`. |

To enable this during one-command install:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | HEPHAESTUS_INSTALL_GLOBAL_ROUTER=1 bash
```

Inside the Codex app, `/prompts:hep-build`, `/prompts:hep-network`,
`/prompts:hep-local`, `/prompts:hep-cloud`, `/prompts:hep-hub`,
`/prompts:hep-search`, `/prompts:hep-browser`, `/prompts:hep-call`,
`/prompts:hep-upload`, and `/prompts:hep-connect` first run the app-host auto-update preflight when Codex
has local command execution. That preflight refreshes
`~/.agentlas/runtime/current` and installed prompt/plugin surfaces without
asking the user to open a separate terminal. If this Codex install is too old to
contain the preflight, run the one-command installer once or refresh the plugin
from the plugin manager.

Codex-only manual install:

```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.1.53
codex plugin add hephaestus@agentlas-core-engine
mkdir -p ~/.codex/prompts
cp codex/prompts/hep-build.md codex/prompts/hep-network.md codex/prompts/hep-local.md codex/prompts/hep-cloud.md codex/prompts/hep-hub.md codex/prompts/hep-search.md codex/prompts/hep-browser.md codex/prompts/hep-call.md codex/prompts/hep-upload.md codex/prompts/hep-connect.md ~/.codex/prompts/
```

The OS-terminal Codex CLI command is singular: `codex plugin`, not
`codex plugins`. Inside the Codex app, use `/plugins` to browse installed
plugins; do not run `/plugin marketplace add` inside the app.

## Use

Open or restart Codex and type:

```text
/prompts:hep-build create a support operations agent
/prompts:hep-network find me an agent for app store reviews
/prompts:hep-local use only agents registered on this machine
/prompts:hep-cloud use my saved finance analyst agent
/prompts:hep-hub find only public Hub agents for accessibility QA
/prompts:hep-search find agents for market report research
/prompts:hep-browser https://example.com
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
