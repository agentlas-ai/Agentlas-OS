---
description: Route a request through the public Agentlas Hub via Hephaestus Network.
argument-hint: <natural-language request>
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Network routing


Raw arguments: `$ARGUMENTS`

Codex plugins cannot register slash commands, so this custom prompt is the
explicit entrypoint (`/prompts:hep-network`). The same contract is also
available implicitly via the `hephaestus-network` skill.

1. Resolve the runner — first executable wins:

```bash
if [ "${HEPHAESTUS_APP_AUTO_UPDATE:-1}" != "0" ]; then
  CURRENT_RUNNER="$HOME/.agentlas/runtime/current/bin/hephaestus"
  NEEDS_HEP_UPDATE=1
  if [ -x "$CURRENT_RUNNER" ]; then
    UPDATE_CHECK="$("$CURRENT_RUNNER" update --check 2>/dev/null || true)"
    printf '%s' "$UPDATE_CHECK" | grep -q '"status": "current"' && NEEDS_HEP_UPDATE=0
  fi
  if [ "$NEEDS_HEP_UPDATE" = "1" ] && command -v curl >/dev/null 2>&1; then
    curl -fsSL "${HEPHAESTUS_INSTALL_URL:-https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh}" \
      | HEPHAESTUS_FORCE=1 bash >/tmp/hephaestus-app-auto-update.log 2>&1 || true
  fi
fi

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
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found after app auto-update preflight. See /tmp/hephaestus-app-auto-update.log if it exists." >&2; exit 1; }
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
DECISION="$("$RUNNER" route "$ARGUMENTS" --runtime codex)"
printf '%s\n' "$DECISION"

# Deterministic GUI auto-launch (Network surface). Exact GUI shortcuts such as
# `startup` restore the Hub cloud package and launch its packaged GUI. Local
# private/restricted shortcut cards are ignored unless an operator explicitly enables
# local debug routing. Disable with HEPHAESTUS_GUI_AUTOLAUNCH=0.
if [ "${HEPHAESTUS_GUI_AUTOLAUNCH:-1}" != "0" ]; then
  GUI_SHORTCUT="$($RUNNER local-gui "$ARGUMENTS" --detach --quiet-not-found 2>/dev/null || true)"
  [ -n "$GUI_SHORTCUT" ] && printf '%s
' "$GUI_SHORTCUT"
fi
```

2. Act on the returned JSON decision:
   - `route` — report the selected card, then invoke the selected agent's
     canonical command with the original request.
   - `clarify` — ask `clarify_question` with the candidates and re-route.
   - `pipeline` — execute `stages` in order, save artifacts under
     `handoff_dir/<order>-<kind>/`, pass paths forward; on a stage failure stop
     and report — never retry silently.
   - `hub_fallback` / `hub_candidates` — Hub lookup used redacted keywords only;
     the raw prompt and local memory were not sent. If `$RUNNER local-gui` printed
     `source: "hub_cloud_package"` for a GUI shortcut such as `startup`, report
     that the Hub package was restored and the GUI is opening; do not stop at
     “candidate only.”
   - `propose_new` — offer to build a new agent/team via `/hep-build`.
   - `refuse` — explain `reasons`; do not retry around the guard.

3. Hard rules: the router only chooses an agent or fetches a BYOM Hub bundle.
   Actual tool execution follows the current host runtime's safety and
   permission model. Report the routing `receipt_id` in the final message.
