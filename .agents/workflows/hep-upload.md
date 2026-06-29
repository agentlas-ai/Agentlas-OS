---
description: Upload an Agentlas agent after asking Cloud vs Hub first.
---

# /hep-upload

Upload an Agentlas agent package. The argument is the exact text the user typed
after `/hep-upload` — usually an agent folder, possibly empty.

> Guardrails: do NOT diagnose `command not found`/`PATH`, do NOT edit
> `~/.zshrc`, and do NOT create/commit/stash/push any git branch or claim you
> did. If the runner is missing, say so and stop — never fabricate an upload.

## Step 1 — Ask the destination first

Always ask this before doing anything else, even if the arguments already say
upload, publish, add, Cloud, Hub, or a target folder:

```text
Cloud에 업로드 할까요? 다른사람들이 볼 수 없어요.
Upload to Cloud? Other people cannot see it.

Agentlas Hub에 업로드 할까요? 다른 사람들이 빌려 쓸 수 있어요.
Upload to Agentlas Hub? Other people can borrow it.
```

Do not package, publish, register, add-source, reindex, or call any upload API
until the user answers **Cloud** or **Agentlas Hub**. If the destination is
answered but the target folder is ambiguous, ask for the exact agent folder
before running anything.

## Step 2 — Resolve the runner

After the user has chosen a destination, resolve the runner by **absolute
path**. Do not ask the user to open a separate terminal.

```bash
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
"$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
echo "RUNNER=$RUNNER"
```

## Step 3 — Validate, then publish

Validate the package through the bundled Hephaestus gate before any upload (it
must validate without assuming a private local checkout):

- Cloud / private-link: `"$RUNNER" package <agent-folder> --visibility private-link`
- Agentlas Hub / marketplace: `"$RUNNER" package <agent-folder> --visibility marketplace`

For Hub upload, the gate blocks missing or generic `publicProfile`, a bad
`routing-card.json`, missing package hashes, static security blockers, and
packages over the public bundle limits.

After the user chooses, publish:

- **Cloud** (private, owner-only): `"$RUNNER" publish <agent-folder> --visibility private-link`
- **Agentlas Hub** (public, borrowable): `"$RUNNER" publish <agent-folder> --visibility marketplace`

On a non-interactive host without a TTY, do not re-run the question-only gate
after the user has answered. Use one explicit command instead:

- Cloud: `"$RUNNER" hep-upload <agent-folder> --visibility private-link`
- Agentlas Hub: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace`

---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요.
업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.
