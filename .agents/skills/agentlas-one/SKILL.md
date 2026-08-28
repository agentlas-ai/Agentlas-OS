---
name: agentlas-one
description: "Use when the user types /agentlas-one on|off, /agentlas one on|off, or asks to enable/disable the persistent personal agent mode."
---

# Agentlas One (/agentlas-one)

Persistent personal agent operating mode control. The agent's name is whatever the
owner chose (`agentlas-one name <name>`); it is never fixed in this document.
Toggle via `/agentlas-one on` or `/agentlas-one off`.

## Commands

These are the verbs the runner actually accepts (`bin/agentlas-one`). Anything not
listed here does not exist — do not invent one.

- `install` — put the runner on PATH and wire the status line.
- `on [name]` / `off` — enable or disable the persistent mode.
- `name <name>` — rename the agent. This never turns it on.
- `status [--runtimes|--drift]` — what is installed and what drifted.
- `uninstall [--purge]` — remove every footprint (a restore archive is written first).
- `seed` / `memory` / `curate` — the drawer: create it, read it, run the curator.
- `remember <text>` — hand one learning to the curator (it decides, not you).
- `chips` / `promote <id> [reason]` / `reject <id> [reason]` — experience chips.
- `coverage` — how much of the drawer recall actually reaches a session.
- `orch <sub>` — orchestration helpers.
- `statusline` / `stop-hook` — host integration entry points; not typed by hand.
