---
description: Create, list, inspect, or request a run of an Agentlas automation graph.
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-graph

Treat the text after `/hep-graph` as one of: `new <request>`, `list`,
`show <name>`, or `run <name>`. Saved graphs live in the local Agentlas database
shared with Agentlas Desktop. This workflow requests work from the independent
Agentlas CLI; it must not substitute Gemini CLI, Hephaestus routing, or Hub
search.

## Resolve the Agentlas CLI

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

## Behavior

- No arguments or `list`: run `"$CLI" graph list` and report trigger, step
  count, and on/off state. Do not invent missing graphs.
- `show <name>`: run `"$CLI" graph show "<name>"` and preserve the tree wiring,
  external-effect and ask-first marks, branch sides, repeat edges, verification
  checklist, code steps, and required input.
- `new <request>`: run the CLI interview. Relay every unanswered question and
  never invent schedule, external-effect, repetition, or checklist answers.
  The final save confirmation is the graph's approval. New graphs start off.
- `run <name>`: the direct command is authority to request the run; do not ask
  for a second approval. Show it first. If a value is required, obtain that
  missing input without guessing, then run `"$CLI" graph run "<name>" -y`
  with `--input "<value>"` when needed.

The CLI only requests execution from Agentlas Desktop. Report **requested**, not
executed. On non-zero exit, relay the exact refusal and stop.
