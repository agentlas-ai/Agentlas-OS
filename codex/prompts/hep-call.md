---
description: Prepare explicitly named Agentlas Hub or Cloud agents.
argument-hint: 'agent-a, agent-b {context}'
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.
# /hep-call

Call the exact agents named by the user. This prepares BYOM runtime bundles and
receipts; your own model still performs the actual model/tool execution.

Syntax: `/hep-call agent-a, agent-b {context}`. The text before `{` is the
agent list; the text inside braces is the context. If braces are omitted, the
first token is the agent list and the rest is context.

## If the user wants it to keep running

Public Hub agent calls are free. Explain that scheduled work still uses the
host's own model, API keys, permissions, and runtime capacity. Do not quote or
purchase a retired Hub lease.

## How to run

Run the shell block below **verbatim**, replacing only the `RAW` value with the
exact text the user typed after `/hep-call`. The runner is resolved by
**absolute path** — nothing to install, nothing to add to `PATH`.

> Guardrails: do NOT diagnose `command not found`/`PATH`, do NOT edit
> `~/.zshrc`, and do NOT create/commit/stash/push any git branch or claim you
> did. This workflow changes no source files. If the runner is missing, say so
> and stop — never fabricate a run.

```bash
RAW="<replace with the exact text the user typed after /hep-call, e.g. agent-a, agent-b {context}>"

case "$RAW" in
  "<replace"*) echo "RAW placeholder not filled — substitute the user's request first." >&2; exit 2 ;;
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
  "$RUNNER" auth ensure >/dev/null 2>&1 || true
fi
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
"$RUNNER" call "$AGENTS" "$CONTEXT" --runtime "${AGENTLAS_HOST_RUNTIME:-terminal}"
```

## Answer shape

1. Report each requested agent slug and status.
2. If `status: "prepared"`, use the returned `output.entry_excerpt` and
   `output.grounding.directive` as the agent's runtime instructions.
3. If a legacy server returns `status: "insufficient_credits"`, do not run the
   agent or suggest a top-up. Report that the server has not switched to the
   free Hub contract.
4. If an agent fails for any other reason, continue with prepared agents and
   clearly list each failure with its `status`.
5. NEVER substitute for a blocked or failed agent by reading its local
   source files and role-playing the persona yourself. A Hub agent runs only
   through the server's pinned bundle; if it did not return `prepared`, report
   why — never fabricate a run.
6. Include the top-level `receipt_id` and every prepared `execution_id`.

## Examples

```text
/hep-call market-researcher, report-writer {시장 리포트 초안 만들어줘}
/hep-call cloud:my-finance-agent {이 리포트 리스크 검토}
```

---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요.
업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.
