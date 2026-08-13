---
name: hephaestus-graph
description: "Use when the user types /hep-graph or asks to create, list, inspect, or request a run of an Agentlas automation graph."
---

# Hephaestus Graph

Saved graphs live in the local Agentlas database shared with Agentlas Desktop.
This skill may create, list, inspect, or request a graph run; it does not execute
the graph itself.

## Resolve the independent Agentlas CLI

Use the first executable path:

```bash
CLI=""
for candidate in \
  "$(command -v agentlas 2>/dev/null)" \
  "$HOME/.agentlas/runtime/current/bin/agentlas" \
  "./bin/agentlas"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then CLI="$candidate"; break; fi
done
[ -n "$CLI" ] || { echo "Agentlas CLI not found. Install it with: npm i -g agentlas" >&2; exit 1; }
```

Do not substitute Gemini CLI, Hephaestus routing, or Hub search when the Agentlas
CLI is missing.

## Commands

- No arguments or `list`: run `"$CLI" graph list` and report each graph's
  trigger, step count, and on/off state.
- `show <name>`: run `"$CLI" graph show "<name>"`. Preserve the tree wiring,
  external-effect and ask-first marks, branch sides, repeat edges, verification
  checklist, code steps, and any required input in the summary.
- `new <request>`: run `"$CLI" graph new "<request>"` as an interview. Relay
  every unanswered question and never invent schedule, external-effect,
  repetition, or checklist answers. The final save confirmation is the graph's
  approval. A new graph starts switched off.
- `run <name>`: the user's direct run request is sufficient authority. Do not
  ask for a second approval. Show the graph first; if it requires an input,
  obtain that missing value without inventing it. Then run
  `"$CLI" graph run "<name>" -y`, adding `--input "<value>"` when required.

Report exactly that a run was **requested** and will be picked up by Agentlas
Desktop. Never claim the graph executed. On any non-zero exit, relay the exact
refusal and stop; do not retry with a guess.
