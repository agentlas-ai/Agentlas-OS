---
description: Search Agentlas Cloud and Hub agent candidates without invoking.
argument-hint: '<request>'
allowed-tools: Bash, Read, Glob, Grep
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-search


Find matching agents without calling them. Return two sections: my Agentlas
Cloud packages and the public Agentlas Hub.

Raw arguments: `$ARGUMENTS`

## Search

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
for candidate in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/hephaestus}" \
  "${PLUGIN_ROOT:+$PLUGIN_ROOT/bin/hephaestus}" \
  "./bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi
done
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found after app auto-update preflight. See /tmp/hephaestus-app-auto-update.log if it exists." >&2; exit 1; }
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
"$RUNNER" search "$ARGUMENTS" --runtime claude-code --limit 10
```

## Answer Shape

1. Show `sections.cloud.results` first, then `sections.hub.results`.
2. For each candidate include rank, name, slug, description, callable/routing
   status, and why it matched.
3. Do not invoke any agent. If the user wants to run exact agents next, use
   `/hep-call agent-slug-1, agent-slug-2 {context}`.
4. Include `receipt_id` in the final line.

## Examples

```text
/hep-search 시장 리포트 써야 하는데 쓸만한 에이전트 찾아줘
/hep-search find agents for ASO review replies
```
