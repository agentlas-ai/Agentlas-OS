---
description: Search Agentlas Cloud and Hub candidates without invoking agents.
argument-hint: <request>
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Search


Raw arguments: `$ARGUMENTS`

Codex plugins cannot register slash commands, so this custom prompt is the
explicit entrypoint: `/prompts:hep-search`.

1. Resolve the runner:

```bash
RUNNER=""
for c in "$HOME/.agentlas/runtime/current/bin/hephaestus" ./bin/hephaestus; do
  [ -x "$c" ] && RUNNER="$c" && break
done
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
"$RUNNER" search "$ARGUMENTS" --runtime codex --limit 10
```

2. Present the JSON as two sections:
   - `cloud`: my own Agentlas Cloud packages.
   - `hub`: public Agentlas Hub marketplace.

3. Include rank, name, slug, description, callable/routing status, and why.
   Do not invoke agents from this prompt. Use `/prompts:hep-call` next
   when the user names exact slugs.
