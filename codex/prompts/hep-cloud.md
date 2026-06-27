---
description: Search ONLY the signed-in user's own Agentlas cloud packages (보관함) and route to one.
argument-hint: <natural-language request>
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Cloud routing (my own cloud / 보관함)


Raw arguments: `$ARGUMENTS`

Owner-scoped leg of the three-scope model. `/hep-cloud` searches ONLY my
own Agentlas cloud packages (restorable/owned by me, call-priced at a flat 1
credit). `/hep-network` searches the public marketplace; plain language
searches local + my cloud + Hub together. Codex plugins cannot register slash
commands, so this custom prompt is the explicit entrypoint
(`/prompts:hep-cloud`); the same contract is available implicitly via the
`hephaestus-cloud` skill.

1. Resolve the runner — first executable wins:

```bash
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
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
# The owner cloud (보관함) requires sign-in.
"$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
"$RUNNER" cloud "$ARGUMENTS" --project .
```

`hephaestus cloud` is shorthand for `hephaestus route "<request>" --scope cloud`
(owner-scoped Hub query; implies `--hub-only`).

2. Act on the returned JSON decision (`scope: "cloud"`):
   - `hub_candidates` — these are my OWN cloud packages. Report them, and on the
     user's pick invoke that package with the original request (1 credit/call).
   - `clarify` — ask `clarify_question` with the candidates and re-route.
   - `propose_new` — no matching package in my cloud; offer `/hep-network`
     (public marketplace) or `/hep-build` (build a new agent).
   - `refuse` — explain `reasons`; do not retry around the guard.

3. Hard rules: never searches the public marketplace or local cards — only the
   authenticated owner's own cloud packages. Actual tool execution follows the
   host runtime's safety and permission model. Report the routing `receipt_id`.
