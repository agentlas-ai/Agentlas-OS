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
| Global | `~/.gemini/antigravity/global_workflows/hephaestus-*.md` | `/hephaestus-build`, `/hephaestus-network`, and `/hephaestus-cloud` in **every** Antigravity workspace. Installed by `scripts/install-all-runtimes.sh`. |
| Project | `.agents/workflows/hephaestus-*.md` | The same three commands when this repo (or any project carrying the package) is open. Ships in the repo. |

`antigravity/workflows/hephaestus-build.md`,
`antigravity/workflows/hephaestus-network.md`, and
`antigravity/workflows/hephaestus-cloud.md` are the canonical workflow bodies;
the locations above mirror them (global install + in-repo project copy), the
same way the Gemini adapter ships both extension commands and
`~/.gemini/commands` fallbacks.

## Install

From an OS terminal (not the Antigravity chat box):

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.7.10/scripts/install-all-runtimes.sh | bash
```

Then reopen Antigravity and type `/hephaestus-build`, `/hephaestus-network`,
or `/hephaestus-cloud`. Antigravity shares the `~/.gemini/` home with the
Gemini CLI, so this install also keeps the Gemini extension and commands in
sync.
