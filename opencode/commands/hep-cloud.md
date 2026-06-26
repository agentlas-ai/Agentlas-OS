---
description: Search ONLY the signed-in user's own Agentlas cloud packages (보관함) and route to one.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Cloud routing (my own cloud / 보관함)


Raw arguments: `$ARGUMENTS`

Owner-scoped leg of the three-scope model: search ONLY my own Agentlas cloud
packages (보관함), restorable/owned by me and call-priced at a flat 1 credit.
`/hep-network` searches the public marketplace; plain language searches
local + my cloud + Hub together.

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
    "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus" \
    "$HOME/.codex/plugins/cache/agentlas-core-engine/hephaestus"; do
    newest="$(ls -d "$cache"/*/bin/hephaestus 2>/dev/null | sort -V | tail -1)"
    [ -n "$newest" ] && [ -x "$newest" ] && RUNNER="$newest" && break
  done
fi
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found after app auto-update preflight. See /tmp/hephaestus-app-auto-update.log if it exists." >&2; exit 1; }
# The owner cloud (보관함) requires sign-in.
"$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
"$RUNNER" cloud "$ARGUMENTS" --project .
```

`hephaestus cloud` is shorthand for `hephaestus route "<request>" --scope cloud`
(owner-scoped Hub query; implies `--hub-only`).

2. Act on the returned JSON decision (`scope: "cloud"`):
   - `hub_candidates` — my OWN cloud packages; report them and, on the user's
     pick, invoke that package with the original request (1 credit/call).
   - `clarify` — ask `clarify_question` with the candidates and re-route.
   - `propose_new` — no matching package in my cloud; offer /hep-network
     (public marketplace) or /hep-build (build a new agent).
   - `refuse` — explain `reasons`; do not retry around the guard.

3. Hard rules: never searches the public marketplace or local cards — only the
   authenticated owner's own cloud packages. Actual tool execution follows the
   current host runtime's safety and permission model. Report the routing
   `receipt_id` in the final message.
