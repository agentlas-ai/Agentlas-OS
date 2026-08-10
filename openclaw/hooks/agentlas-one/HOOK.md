---
name: agentlas-one
description: "Harvest Agentlas One memory events from the session that just ended"
homepage: https://github.com/agentlas-ai/Agentlas-OS
metadata:
  {
    "openclaw":
      {
        "emoji": "🧠",
        "events": ["command:new", "command:reset"],
        "install": [{ "id": "agentlas-os", "kind": "local", "label": "Installed by Agentlas OS" }],
      },
  }
---

# Agentlas One Memory Hook

OpenClaw has no session-end event. `/new` and `/reset` are the points where a
session is finished and its transcript stops growing, so the checkpoint runs
there and reads the **previous** session rather than the one starting now.

## What It Does

1. Reads `context.previousSessionEntry.sessionFile` — the transcript of the
   session that just ended.
2. Hands that path to `agentlas-one stop-hook openclaw`.
3. The runtime extracts only `## Memory Events` envelopes the assistant wrote,
   converts them into append-only tickets, and lets the curator decide what
   becomes durable memory.

Raw prompts and transcripts never leave the machine and are never stored; only
the bounded envelopes the worker chose to emit are read.

## Failure Behaviour

Every failure path is silent and non-blocking. A missing runtime, a missing
transcript, or a slow checkpoint must never interrupt an OpenClaw session, so
the handler resolves normally in all of those cases.

## Requirements

Agentlas One must be switched on (`agentlas-one on`). When it is off, the
runtime records `skipped: one_off` and writes nothing.
