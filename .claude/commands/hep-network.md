---
description: Borrow public Agentlas Hub agents through Hephaestus Network.
argument-hint: '<request>'
allowed-tools: Bash, Read, Glob, Grep
---

# /hep-network

Route a natural-language request through the public Agentlas Hub via
Hephaestus Network. Local Paid/Free cards are ignored by default. Also triggered
by `@Hephaestus <request>` in chat.

Raw arguments: `$ARGUMENTS`

## Route

1. Find the first executable Hephaestus runner:

```bash
RUNNER=""
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
for candidate in \
  "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/hephaestus}" \
  "${CODEX_PLUGIN_ROOT:+$CODEX_PLUGIN_ROOT/bin/hephaestus}" \
  "${PLUGIN_ROOT:+$PLUGIN_ROOT/bin/hephaestus}" \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  "./bin/hephaestus" \
  "./claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus"
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
DECISION="$("$RUNNER" route "$ARGUMENTS" --runtime claude-code)"
printf '%s\n' "$DECISION"

# Deterministic GUI auto-launch (Network surface). Exact GUI shortcuts such as
# `startup` restore the Hub cloud package and launch its packaged GUI. Local
# Paid/Free shortcut cards are ignored unless an operator explicitly enables
# local debug routing. Disable with HEPHAESTUS_GUI_AUTOLAUNCH=0.
if [ "${HEPHAESTUS_GUI_AUTOLAUNCH:-1}" != "0" ]; then
  GUI_SHORTCUT="$($RUNNER local-gui "$ARGUMENTS" --detach --quiet-not-found 2>/dev/null || true)"
  [ -n "$GUI_SHORTCUT" ] && printf '%s
' "$GUI_SHORTCUT"
fi
```

2. Act on the returned JSON decision:
   - `action: "route"` — the block above ALREADY auto-launched the GUI if the
     selected card is a local GUI agent (look for `{"gui_autolaunch": "opened"}`
     in the output). Report the selected card (`selected.id`,
     `entrypoints.canonical_command`), tell the user the GUI is opening in the
     browser, then act on the canonical command with the original request. If the
     GUI is the whole interaction (no concrete task given), just confirm it opened.
   - `action: "clarify"` — ask `clarify_question` with the candidate list and re-route with the answer.
   - `action: "pipeline"` — a multi-team plan (e.g. PRD → build → QA). Execute
     `stages` in order: run that stage card's canonical command, save its artifacts under
     `handoff_dir/<order>-<kind>/`, and pass those paths to the next stage.
     On a stage failure: stop and report progress plus the remaining plan —
     never retry silently.
   - `action: "hub_fallback"` or `"hub_candidates"` — Hub lookup used redacted
     keywords only; the raw prompt and local memory were not sent. If `$RUNNER local-gui`
     printed `source: "hub_cloud_package"` for a GUI shortcut such as `startup`,
     report that the Hub package was restored and the GUI is opening; do not stop
     at “candidate only.”
   - `action: "propose_new"` — offer to build a new agent/team via `/hep-build`.
   - `action: "refuse"` — explain `reasons` (for example, loop guard). Do not retry around it.

3. Hard rules: the router only chooses an agent or fetches a BYOM Hub bundle.
   Actual tool execution follows the current host runtime's safety and
   permission model. Report the routing `receipt_id` in your final message.

## Examples

```text
/hep-network turn these meeting notes into a weekly report
/hep-network 이 작업에 맞는 에이전트 찾아줘
@Hephaestus draft a launch plan for my product
```
