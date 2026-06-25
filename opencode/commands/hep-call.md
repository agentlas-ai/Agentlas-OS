---
description: Prepare explicitly named Agentlas Hub or Cloud agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Call


Raw arguments: `$ARGUMENTS`

```bash
RUNNER=""
for c in "$HOME/.agentlas/runtime/current/bin/hephaestus" ./bin/hephaestus; do
  [ -x "$c" ] && RUNNER="$c" && break
done
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
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
"$RUNNER" call "$AGENTS" "$CONTEXT" --runtime opencode
```

For each prepared agent, follow `output.entry_excerpt` and
`output.grounding.directive`. Include `receipt_id` plus every prepared
`execution_id`.
