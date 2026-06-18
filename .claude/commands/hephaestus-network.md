# /hephaestus-network

Route a natural-language request through the Hephaestus Network local-first
router. Also triggered by `@Hephaestus <request>` in chat.

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
"$RUNNER" route "$ARGUMENTS" --runtime claude-code
```

2. Act on the returned JSON decision:
   - `action: "route"` — report the selected card (`selected.id`, `entrypoints.canonical_command`).
     Then invoke the selected agent's canonical command with the original
     request.
   - `action: "clarify"` — ask `clarify_question` with the candidate list and re-route with the answer.
   - `action: "pipeline"` — a multi-team plan (e.g. PRD → build → QA). Execute
     `stages` in order: run that stage card's canonical command, save its artifacts under
     `handoff_dir/<order>-<kind>/`, and pass those paths to the next stage.
     On a stage failure: stop and report progress plus the remaining plan —
     never retry silently.
   - `action: "hub_fallback"` or `"hub_candidates"` — Hub lookup used redacted
     keywords only; the raw prompt and local memory were not sent.
   - `action: "propose_new"` — offer to build a new agent/team via `/hephaestus-build`.
   - `action: "refuse"` — explain `reasons` (for example, loop guard). Do not retry around it.

3. Hard rules: the router only chooses an agent or fetches a BYOM Hub bundle.
   Actual tool execution follows the current host runtime's safety and
   permission model. Report the routing `receipt_id` in your final message.

## Examples

```text
/hephaestus-network turn these meeting notes into a weekly report
/hephaestus-network 이 작업에 맞는 에이전트 찾아줘
@Hephaestus draft a launch plan for my product
```
