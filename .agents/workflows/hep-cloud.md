---
description: Use signed-in owner-scoped Agentlas Cloud packages through Hephaestus.
---

# /hep-cloud

Search **only the signed-in user's own Agentlas cloud packages** (보관함) and
route the request to one of them. This is the owner-scoped leg of the
three-scope model:

- `/hep-cloud <request>` — my OWN cloud packages only (보관함), call-priced at a
  flat 1 credit.
- `/hep-network <request>` — the public Agentlas Hub marketplace (others'
  published agents), each priced by its own per-call price.
- plain language / `@Hephaestus` — local + my cloud + Hub together.

The request is the exact text the user typed after `/hep-cloud`.

## How to run

Run the shell block below **verbatim**, replacing only the `REQUEST` value. The
runner is resolved by **absolute path** — nothing to install, nothing to add to
`PATH`.

> Guardrails: do NOT diagnose `command not found`/`PATH`, do NOT edit
> `~/.zshrc`, and do NOT create/commit/stash/push any git branch or claim you
> did. This workflow changes no source files. If the runner is missing, say so
> and stop — never fabricate a fix or a run.

```bash
REQUEST="<replace with the exact text the user typed after /hep-cloud>"

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
# The owner cloud (보관함) requires sign-in; ensure a reusable Agentlas session.
"$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
"$RUNNER" cloud "$REQUEST" --project .
```

`hephaestus cloud` is shorthand for `hephaestus route "<request>" --scope cloud`
(owner-scoped Hub query; implies `--hub-only`).

## Act on the JSON decision (`scope: "cloud"`)

- `action: "hub_candidates"` — these are my OWN cloud packages. Report them
  (`hub.results[].slug`, `name`) and, on the user's pick, invoke that package
  with the original request (call-priced at 1 credit).
- `action: "clarify"` — ask `clarify_question` with the candidate list and
  re-run the block with the answer (still cloud-scoped).
- `action: "propose_new"` — no matching package exists in my cloud. Offer to
  search the public marketplace with `/hep-network`, or to build a new agent via
  `/hep-build`.
- `action: "refuse"` — explain `reasons` (e.g. loop guard); do not retry.

Hard rules: this command never searches the public marketplace or local cards —
only the authenticated owner's own cloud packages. Report the routing
`receipt_id` in your final message.

## Examples

```text
/hep-cloud turn these meeting notes into a weekly report
/hep-cloud 내 보관함에서 이 작업에 맞는 에이전트 찾아줘
```

---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요.
업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.
