# Google Antigravity Adapter

Thin adapter that registers the three Hephaestus commands in [Google Antigravity](https://antigravity.google).
`AGENTS.md` at the repository root is the canonical source of truth; this folder
only carries the Antigravity-specific command surface.

## What Antigravity already reads

Antigravity natively loads, with no extra setup:

- `AGENTS.md` — cross-tool project rules and routing (canonical).
- `GEMINI.md` — Antigravity/Gemini context file.
- `.agents/skills/` — the reusable Agentlas skills.

## What this adapter adds

Antigravity registers a Markdown file in a `workflows/` directory as a chat
slash command. Hephaestus ships the three workflows at two scopes:

| Scope | File | Effect |
| --- | --- | --- |
| Global | `~/.gemini/antigravity/global_workflows/hep-*.md` | `/hep-build`, `/hep-network`, and `/hep-cloud` in **every** Antigravity workspace. Installed by `scripts/install-all-runtimes.sh`. |
| Project | `.agents/workflows/hep-*.md` | The same three commands when this repo (or any project carrying the package) is open. Ships in the repo. |

`antigravity/workflows/hep-build.md`,
`antigravity/workflows/hep-network.md`, and
`antigravity/workflows/hep-cloud.md` are the canonical workflow bodies;
the locations above mirror them (global install + in-repo project copy), the
same way the Gemini adapter ships both extension commands and
`~/.gemini/commands` fallbacks.

## Install

From an OS terminal (not the Antigravity chat box):

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

The installed `/hep-*` workflows include the app-host auto-update preflight.
When Antigravity can run local shell commands, Hephaestus refreshes
`~/.agentlas/runtime/current` and existing workflow/skill surfaces from inside
Antigravity before resolving the runner.

Then reopen Antigravity and type `/hep-build`, `/hep-network`,
or `/hep-cloud`. Antigravity shares the `~/.gemini/` home with the
Gemini CLI, so this install also keeps the Gemini extension and commands in
sync.

Optional global router prompt block:

```bash
hep-global install --target antigravity
```

This appends a managed Hephaestus block to `~/.gemini/GEMINI.md`, which
Antigravity shares with Gemini CLI. After that, ordinary Antigravity prompts use
the same fallback order as the other global-router hosts: Network first, Cloud
second, local agents third, and local host skills last. Status lines should name
the final agents or skills, not `hep-network`.
