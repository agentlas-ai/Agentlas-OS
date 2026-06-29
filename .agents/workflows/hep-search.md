---
description: Search Agentlas Cloud and Hub agent candidates without invoking.
---

# /hep-search

Find matching agents **without calling them**. Return two sections: my Agentlas
Cloud packages first, then the public Agentlas Hub.

The request is the exact text the user typed after `/hep-search`.

## How to run

Run the shell block below **verbatim**, replacing only the `REQUEST` value. The
runner is resolved by **absolute path** — nothing to install, nothing to add to
`PATH`.

> Guardrails: do NOT diagnose `command not found`/`PATH`, do NOT edit
> `~/.zshrc`, and do NOT create/commit/stash/push any git branch or claim you
> did. This workflow changes no source files and invokes no agent. If the runner
> is missing, say so and stop — never fabricate results.

```bash
REQUEST="<replace with the exact text the user typed after /hep-search>"

case "$REQUEST" in
  "<replace"*) echo "REQUEST placeholder not filled — substitute the user's request first." >&2; exit 2 ;;
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
"$RUNNER" search "$REQUEST" --runtime antigravity --limit 10
```

## Answer shape

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

---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요.
업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.
