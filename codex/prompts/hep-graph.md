---
description: Build an Agentlas automation by describing it, list saved ones, or request a run.
argument-hint: '[new <what you want> | list | show <name> | run <name>]'
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

## New — build one by talking it through

With `new <what they want>` (or when the user describes an automation they want and no
saved graph matches), run the CLI's interview. **It asks the user things it must not decide
for them** — when it runs, whether a step goes outside, how many times a repeat may run.

The CLI reads answers from stdin, one per line. So: run it once with no answers to see the
first questions, relay them to the user **in their own words**, get their answers, then run
it again with every answer so far:

```bash
printf '%s\n' "<answer 1>" "<answer 2>" "y" | "$CLI" graph new "<what they want>"
```

Rules that matter here:

- **Never invent an answer.** If the user has not said when it runs, ask them — do not pick
  a time. The whole point of the interview is that these come from the person.
- The interview **proposes a grading checklist** for steps that repeat until good enough
  (what must exist / what must not appear). Relay those items so the user can confirm or
  edit them — they are the pass/fail criteria, and the person should see them before saving.
- If the user does not know or says you decide, pass that through verbatim
  (`알아서 해주세요` / `you decide`). The CLI then takes the most conservative option and
  says what it chose. Do not decide on their behalf yourself.
- The last line must be `y` to save. Until then nothing is written.
- It is created **switched off**. Say so, and relay the two commands the CLI prints
  (`graph show` to look it over, `automation on` to turn it on).
- If the CLI stops with "answer 를 받지 못해 멈췄습니다" / "Stopped without an answer to",
  it needed one more answer. Relay that exact question to the user and run again with the
  fuller list. Do not retry with a guess.

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
see where a graph branches. These marks must survive into your summary:
a step that **changes something outside**, a step that **asks first**,
a branch's `[yes]`/`[no]` sides, a `↩ back to …` line (a repeat),
a **checklist** under a verification step (the `· [must] / [must not]` lines —
those items are exactly what the result is graded on), and a **code** step
(a script the AI wrote runs there, not a model prompt).
If the graph starts from a value the user provides, the output says so —
carry that into the summary too.

## Run

With `run <name>`, the user's direct command is the authority to request that
run. Do not ask for a second yes: graph approval is captured when the graph is
created, and adding another confirmation here makes an approved automation
needlessly stall.

1. Run `"$CLI" graph show "<name>"` first and report what the graph does,
   including any step that changes something outside.
2. If the graph starts from a value (`graph show` says so), require that value
   from the user in their own words. This is missing execution input, not an
   approval prompt. Do not invent one or reuse an example from the graph.
3. Request the run immediately once all required input is present:

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

## Rules carried from the other runtime copies

These lines existed in one runtime's hand-maintained copy and not in the
longest one. They are kept verbatim rather than dropped — a rule that only
one runtime enforced was still a rule someone wrote on purpose.

- # Hephaestus Graph Saved automation graphs live in the local Agentlas database, shared with the desktop app.
- # /hep-graph Treat the text after `/hep-graph` as one of:
- `new <request>`, `list`, `show <name>`, or `run <name>`.
- This workflow requests work from the independent Agentlas CLI; it must not substitute Gemini CLI, Hephaestus routing, or Hub search.
- ## Resolve the Agentlas CLI ```bash CLI="" for candidate in \ "$(command -v agentlas 2>/dev/null)" \ "$HOME/.agentlas/runtime/current/bin/agentlas" \ "./bin/agentlas" do if [ -n "$candidate" ] && [ -x "$candidate" ]; then CLI="$candidate"; break; fi done [ -n "$CLI" ] || { echo "Agentlas CLI not found.
- npm i -g agentlas" >&2; exit 1; } ``` ## Behavior - No arguments or `list`:
- run `"$CLI" graph list` and report trigger, step count, and on/off state.
- run `"$CLI" graph show "<name>"` and preserve the tree wiring, external-effect and ask-first marks, branch sides, repeat edges, verification checklist, code steps, and required input.
- Relay every unanswered question and never invent schedule, external-effect, repetition, or checklist answers.
- The final save confirmation is the graph's approval.
- the direct command is authority to request the run; do not ask for a second approval.
- If a value is required, obtain that missing input without guessing, then run `"$CLI" graph run "<name>" -y` with `--input "<value>"` when needed.
- The CLI only requests execution from Agentlas Desktop.
- On non-zero exit, relay the exact refusal and stop.
