
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.
# /hep-call

Call the exact agents named by the user. This prepares BYOM runtime bundles and
receipts; your own model still performs the actual model/tool execution.

Syntax: `/hep-call agent-a, agent-b {context}`. The text before `{` is the
agent list; the text inside braces is the context. If braces are omitted, the
first token is the agent list and the rest is context.

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
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
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
"$RUNNER" call "$AGENTS" "$CONTEXT" --runtime antigravity
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

## Rules carried from the other runtime copies

These lines existed in one runtime's hand-maintained copy and not in the
longest one. They are kept verbatim rather than dropped — a rule that only
one runtime enforced was still a rule someone wrote on purpose.

- This prepares BYOM runtime bundles and receipts; Claude still performs the actual model/tool execution.
- `the request typed after the command` ## Call ```bash RUNNER="" for candidate in \ "$HOME/.agentlas/runtime/current/bin/hephaestus" \ "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/hephaestus}" \ "${PLUGIN_ROOT:+$PLUGIN_ROOT/bin/hephaestus}" \ "./bin/hephaestus" do if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi done [ -n "$RUNNER" ] || { echo "Hephaestus runtime not found.
- Sign-in is automatic — if a call still reports an auth/sign-in status, relay it and stop.
- Include `receipt_id` and each prepared `execution_id`.
- `the request typed after the command` Codex plugins cannot register slash commands, so this custom prompt is the explicit entrypoint:
- Resolve the runner and prepare the named agents:
- ```bash RUNNER="" for c in "$HOME/.agentlas/runtime/current/bin/hephaestus" ./bin/hephaestus; do [ -x "$c" ] && RUNNER="$c" && break done [ -n "$RUNNER" ] || { echo "Hephaestus runtime not found.
- For each prepared agent, follow its returned `output.entry_excerpt` and `output.grounding.directive`.
- The Hub returns BYOM instructions; Codex executes with the current model and permission model.
- Report failures separately and include the top-level `receipt_id` plus every prepared agent `execution_id`.
- # Hephaestus Call Prepare explicitly named Agentlas Hub or Cloud agents.
- First run the `hephaestus-network` skill's app-host auto-update preflight inside Cursor; do not ask the user to open a separate terminal.
- Resolve the runner (`~/.agentlas/runtime/current/bin/hephaestus`, then `./bin/hephaestus`), run `"$RUNNER" auth ensure --timeout 180`, split the arguments into agent list and context, then run `"$RUNNER" call "<agents>" "<context>" --runtime cursor`.
- For each prepared agent, follow `output.entry_excerpt` and `output.grounding.directive`.
- Report failures separately and include `receipt_id` plus every prepared `execution_id`.
- `the request typed after the command` ```bash RUNNER="" for c in "$HOME/.agentlas/runtime/current/bin/hephaestus" ./bin/hephaestus; do [ -x "$c" ] && RUNNER="$c" && break done [ -n "$RUNNER" ] || { echo "Hephaestus runtime not found.
- Include `receipt_id` plus every prepared `execution_id`.
