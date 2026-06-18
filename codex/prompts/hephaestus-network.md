---
description: Route a request through the Hephaestus Network local-first router (cards, Hub fallback).
argument-hint: <natural-language request>
---

# Hephaestus Network routing

Raw arguments: `$ARGUMENTS`

Codex plugins cannot register slash commands, so this custom prompt is the
explicit entrypoint (`/prompts:hephaestus-network`). The same contract is also
available implicitly via the `hephaestus-network` skill.

1. Resolve the runner — first executable wins:

```bash
RUNNER=""
for c in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  ./bin/hephaestus
do [ -x "$c" ] && RUNNER="$c" && break; done
if [ -z "$RUNNER" ]; then
  for cache in \
    "${CODEX_HOME:-$HOME/.codex}/plugins/cache/agentlas-core-engine/hephaestus" \
    "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus"; do
    newest="$(ls -d "$cache"/*/bin/hephaestus 2>/dev/null | sort -V | tail -1)"
    [ -n "$newest" ] && [ -x "$newest" ] && RUNNER="$newest" && break
  done
fi
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
"$RUNNER" route "$ARGUMENTS" --runtime codex
```

2. Act on the returned JSON decision:
   - `route` — report the selected card, then invoke the selected agent's
     canonical command with the original request.
   - `clarify` — ask `clarify_question` with the candidates and re-route.
   - `pipeline` — execute `stages` in order, save artifacts under
     `handoff_dir/<order>-<kind>/`, pass paths forward; on a stage failure stop
     and report — never retry silently.
   - `hub_fallback` / `hub_candidates` — Hub lookup used redacted keywords only;
     the raw prompt and local memory were not sent.
   - `propose_new` — offer to build a new agent/team via `/hephaestus-build`.
   - `refuse` — explain `reasons`; do not retry around the guard.

3. Hard rules: the router only chooses an agent or fetches a BYOM Hub bundle.
   Actual tool execution follows the current host runtime's safety and
   permission model. Report the routing `receipt_id` in the final message.
