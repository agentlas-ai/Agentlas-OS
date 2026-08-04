---
description: List saved Agentlas automation graphs and request one to run.
argument-hint: '[list | show <name> | run <name>]'
allowed-tools: Bash, Read
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-graph

Saved automation graphs live in the local Agentlas database, shared with the
desktop app. This command reads that database and can ask for a graph to run.

Raw arguments: `$ARGUMENTS`

**What this command can and cannot do.** It lists graphs, shows what a graph
does, and *requests* a run. It does not execute the graph — the desktop app is
what runs it. Say that plainly when you report back; do not tell the user their
automation ran.

## Locate the CLI

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

## List

With no arguments, or with `list`:

```bash
"$CLI" graph list
```

Report each graph with its trigger kind (schedule or input), step count, and
whether it is on. If nothing is saved, say so and point at the desktop app's
Graph page — do not invent graphs.

## Show

With `show <name>`:

```bash
"$CLI" graph show "<name>"
```

The output is a tree, not a list — indentation is the wiring. Relay it as
wiring, because on a surface with no canvas this is the only way the user can
see where a graph branches. Four marks must survive into your summary:
a step that **changes something outside**, a step that **asks first**,
a branch's `[yes]`/`[no]` sides, and a `↩ back to …` line (a repeat).
If the graph starts from a value the user provides, the output says so —
carry that into the summary too.

## Run

With `run <name>`:

1. Run `"$CLI" graph show "<name>"` first and show the user what the graph
   does, including any step that changes something outside.
2. Ask the user to confirm. Never skip this — requesting a run is an
   outward-facing action on the user's behalf.
   - A scheduled graph: ask "run it now?".
   - A graph that starts from a value (`graph show` says so): ask the user for
     that value in their own words. Do not invent one, and do not reuse an
     example from the graph — an automation started from a value you made up
     produces work the user never asked for.
3. Only after an explicit yes:

```bash
"$CLI" graph run "<name>" -y
```

If the graph starts from a value, pass it — without it the CLI refuses,
because a graph run with a blank value silently produces something else:

```bash
"$CLI" graph run "<name>" -y --input "<the value the user gave>"
```

Report exactly what the CLI reported: the run was **requested**, the desktop app
picks it up within a minute while open, and a closed app runs it on next open.
If the CLI refuses because the automation is switched off, relay that refusal
and its reason rather than retrying.

## Failure

If the CLI exits non-zero, show its message verbatim and stop. Do not
substitute a guess about why, and do not retry a run request.
