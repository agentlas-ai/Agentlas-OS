---
description: Prepare explicitly named Agentlas Hub or Cloud agents.
argument-hint: 'agent-a, agent-b {context}'
allowed-tools: Bash, Read, Glob, Grep
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-call


Call the exact agents named by the user. This prepares BYOM runtime bundles and
receipts; Claude still performs the actual model/tool execution.

Raw arguments: `$ARGUMENTS`

## Call

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
RAW="$ARGUMENTS"
if printf '%s' "$RAW" | grep -q '{'; then
  AGENTS="${RAW%%\{*}"
  CONTEXT="${RAW#*\{}"
  CONTEXT="${CONTEXT%\}}"
else
  AGENTS="${RAW%% *}"
  CONTEXT="${RAW#* }"
fi
AGENTS="$(printf '%s' "$AGENTS" | sed 's/[[:space:]]*$//')"
CONTEXT="$(printf '%s' "$CONTEXT" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
"$RUNNER" call "$AGENTS" "$CONTEXT" --runtime claude-code
```

## Answer Shape

1. Report each requested agent slug and status.
2. If `status: "prepared"`, use the returned `output.entry_excerpt` and
   `output.grounding.directive` as the agent's runtime instructions.
3. If `status: "insufficient_credits"`, tell the user the credits `needed` vs.
   `have` and point to `upgrade`; do NOT run the agent. Sign-in is automatic — if
   a call still reports an auth/sign-in status, relay it and stop.
4. If an agent fails for any other reason, continue with prepared agents and
   clearly list each failure with its `status`.
5. NEVER substitute for a blocked, failed, or metered agent by reading its local
   source files and role-playing the persona yourself. A Hub agent runs only
   through the server's metered bundle; if it did not return `prepared`, report
   why — never fabricate a run.
6. Include `receipt_id` and each prepared `execution_id`.

## Examples

```text
/hep-call market-researcher, report-writer {시장 리포트 초안 만들어줘}
/hep-call cloud:my-finance-agent {이 리포트 리스크 검토}
```
