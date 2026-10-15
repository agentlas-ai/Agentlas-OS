# Google Antigravity Adapter

Thin adapter that registers the Hephaestus command set in [Google Antigravity](https://antigravity.google).
`AGENTS.md` at the repository root is the canonical source of truth; this folder
only carries the Antigravity-specific command surface.

## What Antigravity already reads

Antigravity natively loads, with no extra setup:

- `AGENTS.md` — cross-tool project rules and routing (canonical).
- `GEMINI.md` — Antigravity context file.
- `.agents/skills/` — the reusable Agentlas skills.

## What this adapter adds

Antigravity registers a Markdown file in a `workflows/` directory as a chat
slash command. Hephaestus ships the staffing workflows at two install scopes:

| Scope | File | Effect |
| --- | --- | --- |
| Global | `~/.gemini/antigravity/global_workflows/hep-*.md` | `/hep-build` plus `/hep-network`, `/hep-local`, `/hep-cloud`, and `/hep-hub` in **every** Antigravity workspace. Installed by `scripts/install-all-runtimes.sh`. |
| Project | `.agents/workflows/hep-*.md` | The same commands when this repo (or any project carrying the package) is open. Ships in the repo. |

`antigravity/workflows/hep-build.md`,
`antigravity/workflows/hep-network.md`, and
`antigravity/workflows/hep-local.md`, `hep-cloud.md`, and `hep-hub.md` are the
canonical staffing workflow bodies;
the locations above mirror them (global install + in-repo project copy).

## Install

From an OS terminal (not the Antigravity chat box):

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

The installed `/hep-*` workflows include the app-host auto-update preflight.
When Antigravity can run local shell commands, Hephaestus refreshes
`~/.agentlas/runtime/current` and existing workflow/skill surfaces from inside
Antigravity before resolving the runner.

Then reopen Antigravity and type `/hep-build`, `/hep-network`, `/hep-local`,
`/hep-cloud`, or `/hep-hub`. Antigravity keeps its data under `~/.gemini/`, so
the global workflows above live there. Gemini CLI is no longer a supported host;
the installer removes the extension and commands an older install left behind.

Optional global router prompt block:

```bash
hep-global install --target antigravity
```

This appends a managed Hephaestus block to `~/.gemini/GEMINI.md`, which
Antigravity reads. After that, ordinary Antigravity prompts use
the same Workforce contract as the other global-router hosts: Network
federates Local + Cloud + Hub, while exact Local, Cloud, and Hub requests never
widen. Status lines should name the final agents or skills, not `hep-network`.

The installer exposes only local MCP `hephaestus-network` on this local-OS
host. It removes an old direct `agentlas` MCP entry so duplicate
`workforce.*` tools cannot bypass Core's federation and privacy governance.
