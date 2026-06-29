---
description: Route a request through the public Agentlas Hub via Hephaestus Network.
---

# /hep-network

Route the user's request through the Hephaestus Network local-first router
(routing cards → local agents/teams/plugins → public Agentlas Hub fallback).
Also triggered by `@Hephaestus <request>`.

The request is the exact text the user typed after `/hep-network`.

## How to run

Run the shell block below **verbatim**, replacing only the `REQUEST` value with
the user's exact request text. The block resolves the Hephaestus runner by
**absolute path** and runs it — there is nothing to install and nothing to add
to `PATH`.

> Guardrails — do NOT do any of these. They are not how this workflow works and
> have caused fabricated reports before:
> - Do NOT diagnose `command not found` or `PATH`, and do NOT edit `~/.zshrc`.
>   The runner is resolved by absolute path inside the block.
> - Do NOT create, commit, stash, or push any git branch, and do NOT claim you
>   did. This workflow changes no source files.
> - If the runner is genuinely missing, say so and stop. Never fabricate a fix
>   or a run.

```bash
REQUEST="<replace with the exact text the user typed after /hep-network>"

case "$REQUEST" in
  "<replace"*) echo "REQUEST placeholder not filled — substitute the user's request first." >&2; exit 2 ;;
esac

RUNNER=""
for candidate in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  "./bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi
done
if [ -z "$RUNNER" ]; then
  for cache in "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus" \
               "${CODEX_HOME:-$HOME/.codex}/plugins/cache/agentlas-core-engine/hephaestus"; do
    newest="$(ls -d "$cache"/*/bin/hephaestus 2>/dev/null | sort -V | tail -1)"
    if [ -n "$newest" ] && [ -x "$newest" ]; then RUNNER="$newest"; break; fi
  done
fi
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
DECISION="$("$RUNNER" route "$REQUEST" --runtime antigravity)"
printf '%s\n' "$DECISION"

# Deterministic GUI auto-launch. A GUI shortcut such as `startup` restores the
# Hub cloud package and launches its packaged GUI. Disable with
# HEPHAESTUS_GUI_AUTOLAUNCH=0.
if [ "${HEPHAESTUS_GUI_AUTOLAUNCH:-1}" != "0" ]; then
  GUI_SHORTCUT="$("$RUNNER" local-gui "$REQUEST" --detach --quiet-not-found 2>/dev/null || true)"
  [ -n "$GUI_SHORTCUT" ] && printf '%s\n' "$GUI_SHORTCUT"
fi
```

## Act on the JSON decision

- `action: "route"` — report the selected card (`selected.id`,
  `entrypoints.canonical_command`). If the block printed
  `{"gui_autolaunch": "opened"}`, tell the user the GUI is opening, then act on
  the canonical command with the request.
- `action: "clarify"` — ask `clarify_question` with the candidate list, then
  re-run the block with the answer.
- `action: "pipeline"` — a multi-team plan (e.g. PRD → build → QA). Execute
  `stages` in order, save artifacts under `handoff_dir/<order>-<kind>/`, pass the
  paths to the next stage; on a stage failure stop and report — never retry
  silently.
- `action: "hub_fallback"` / `"hub_candidates"` — Hub lookup used redacted
  keywords only; the raw prompt and local memory were not sent. If the decision
  carries an `execution` block (`mode: "byom_local_grounded"`), FOLLOW IT: for
  each `execution.recommended_agents` entry (in stage order) borrow the agent and
  run it LOCALLY with
  `"$RUNNER" hep-call "<agent>" "<request>" --project .`, attaching this repo's
  codebase + memory per `grounding.directive` before producing output. Do NOT
  call agents context-less in the cloud, and do NOT skip the network to improvise
  a local answer yourself. If `execution` is absent, report the candidates and
  offer `/hep-build`.
- `action: "propose_new"` — offer to build a new agent/team via `/hep-build`.
- `action: "refuse"` — explain `reasons` (e.g. loop guard); do not work around it.

Report the routing `receipt_id` in your final message.

## Examples

```text
/hep-network turn these meeting notes into a weekly report
/hep-network 이 작업에 맞는 에이전트 찾아줘
@Hephaestus draft a launch plan for my product
```

---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요.
업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.
