# Codex Adapter

Codex plugins expose skills, hooks, MCP, and app metadata. Codex 0.117+
removed the separate custom-prompt slash surface, so Hephaestus exposes the
current Codex product surface in two places:

1. **Plugin skills**: explicitly invoke `$hephaestus-build`,
   `$hephaestus-network`, `$hephaestus-cloud`, or `$hephaestus-storm`.
   Codex may also select them implicitly from plain language.
2. **MCP**: the installer registers the local stdio server
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

The one-command installer registers the shared runtime and adapters. Desktop
startup and Hephaestus commands start a digest-verified, rate-limited update in
the background without delaying the current task. A successful update moves
`~/.agentlas/runtime/current` atomically and reconciles the Codex plugin and
installed skills. An open task keeps its loaded code until the next task or
app restart.

Codex-only manual install:

```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.1.87
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

Start a fresh Codex session after changing the table. The installer refreshes
the owned command and arguments but preserves this operator-owned `env`
subtable across updates. Provider and model values are matched only against the
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

Use plain language for search-only, browser, exact-call, upload, and connect
requests; the installed MCP exposes those tools. `/plugins` shows whether the
Hephaestus plugin is enabled. `/prompts:*` is a legacy Codex 0.116-and-earlier
surface and is not installed on current Codex.

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
