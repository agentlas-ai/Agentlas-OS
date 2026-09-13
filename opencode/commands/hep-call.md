---
description: Prepare explicitly named Agentlas Hub or Cloud agents.
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.
# /hep-call

Call the exact agents named by the user. This prepares BYOM runtime bundles and
receipts; your own model still performs the actual model/tool execution.

Syntax: `/hep-call agent-a, agent-b {context}`. The text before `{` is the
agent list; the text inside braces is the context. If braces are omitted, the
first token is the agent list and the rest is context.

## If the user wants it to keep running

A Hub call is charged **every time it runs** — the 24-hour auto-lease was
retired 2026-08-18, so paying once does not make the next call free. A job that
wakes on a schedule pays on every wake-up: a five-minute watcher is 288 calls a
day.

When the request is a standing or recurring one, call
`hephaestus.quote_agent_lease` for the named agent **before the first run**. It
answers in one shot — per-day price, total for the days considered, the
workspace's current balance, and the shortfall plus a top-up link when the
balance is short. Show all of it in one message and **ask how many days they
want**; do not choose for them. Only then call
`hephaestus.purchase_agent_lease` — a confirmed purchase needs `confirm: true`,
the chosen `days`, the `confirmationToken`, the `expectedPerDayCredits` and
`expectedTotalCredits` from the quote, and a stable `idempotencyKey`, or it is
refused.

Never buy a lease the user did not agree to. On `insufficient_credits`, say how
short they are and give the top-up link instead of asking them to approve a
purchase that cannot go through. On `leaseOffered: false` the creator set no
per-day price and it is genuinely not for sale — say so and quote the per-call
cost instead.

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
3. If `status: "insufficient_credits"`, tell the user the credits `needed` vs.
   `have` and point to `upgrade`; do NOT run the agent.
4. If an agent fails for any other reason, continue with prepared agents and
   clearly list each failure with its `status`.
5. NEVER substitute for a blocked, failed, or metered agent by reading its local
   source files and role-playing the persona yourself. A Hub agent runs only
   through the server's metered bundle; if it did not return `prepared`, report
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
