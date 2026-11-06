# Codex Adapter

**Preview limitation:** Standalone namespace host integration and updater are incomplete; automatic host registration and adapter updates are not yet available.

Codex plugins expose skills, hooks, MCP, and app metadata. Codex 0.117+
removed the separate custom-prompt slash surface, so Hephaestus exposes the
current Codex product surface in two places:

1. **Plugin skills**: explicitly invoke `$hephaestus-build`,
   `$hephaestus-network`, `$hephaestus-cloud`, `$hephaestus-upload`,
   `$hephaestus-storm`.
   Codex may also select them implicitly from plain language.
2. **MCP**: a manually configured local stdio server
   (`hephaestus mcp serve`) can be exposed as `mcp_servers.hephaestus-network` in
   `~/.codex/config.toml`. It is the host-visible Workforce MCP and
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

Prepare the standalone runtime preview:

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
blocked by entitlement, availability, or fit, Codex reports that
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
| `~/.agentlas/os-bin/agentlas-os global status --target codex` | Use the installed runtime directly when `hep-global` is not on `PATH`. |

The preview installer does not enable this block automatically.

The standalone installer currently prepares an isolated runtime namespace.
Automatic Codex adapter registration and reconciliation are not yet available.

Codex-only manual install:

```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref os-v1.2.86
codex plugin add hephaestus@agentlas-core-engine
```

The OS-terminal Codex CLI command is singular: `codex plugin`, not
`codex plugins`. Inside the Codex app, use `/plugins` to browse installed
plugins; do not run `/plugin marketplace add` inside the app.

## Orchestrator and worker models

Codex launches the Hephaestus MCP as its own child process. Put role-specific
model policy in that server's explicit `env` table; setting the variable only
on the outer Codex shell is not a portable contract.

```toml
[mcp_servers.hephaestus-network]
command = "hephaestus"
args = ["mcp", "serve"]

[mcp_servers.hephaestus-network.env]
AGENTLAS_MODEL_ALLOCATION_POLICY_JSON = '{"orchestrator":{"pinnedProvider":"codex","pinnedModelId":"gpt-5.6-sol","maxTier":"frontier","maxEffort":"max"},"worker":{"pinnedProvider":"codex","pinnedModelId":"gpt-5.3-codex-spark","maxTier":"economy","maxEffort":"medium"}}'
```

Start a fresh Codex session after changing the table. Automatic config reconciliation is not available in the preview. Provider and model values are matched only against the
host's advertised live inventory. To select an Ollama or other local worker,
pin that inventory's exact provider/model pair instead; a pin does not install
or launch a missing runtime.

## Use

Open or restart Codex and type:

```text
$hephaestus-build create a support operations agent
$hephaestus-network find me an agent for app store reviews
$hephaestus-network use only agents registered on this machine
$hephaestus-cloud use my saved finance analyst agent
$hephaestus-network use only public Hub agents for accessibility QA
$hephaestus-storm finish and verify this release goal
```

Use plain language for search-only, browser, exact-call, and upload
requests; the installed MCP exposes those tools. `/plugins` shows whether the
Hephaestus plugin is enabled. `/prompts:*` is a legacy Codex 0.116-and-earlier
surface and is not installed on current Codex.

Older host commands and plugin caches may remain; this preview installer does not migrate them automatically.

After meta-agent generation, the final handoff must include `global_commands`
for the created agent or team. For teams, that command routes to the
orchestrator/HQ.

Local validation from this repository:

```bash
python3 -m json.tool codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json >/dev/null
```
