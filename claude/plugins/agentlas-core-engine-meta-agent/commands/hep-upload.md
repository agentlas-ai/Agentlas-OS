---
description: Upload an Agentlas agent after asking Cloud vs Hub first.
argument-hint: '<agent folder or request>'
allowed-tools: Bash, Read, Glob, Grep
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-upload


Raw arguments:
`$ARGUMENTS`

Always ask the destination question before doing anything else, even if the
arguments already say upload, publish, add, Cloud, Hub, or a target folder:

```text
Cloud에 업로드 할까요? 다른사람들이 볼 수 없어요.
Upload to Cloud? Other people cannot see it.

Agentlas Hub에 업로드 할까요? 다른 사람들이 빌려 쓸 수 있어요.
Upload to Agentlas Hub? Other people can borrow it.
```

Do not package, publish, register, add-source, reindex, or call an upload API
until the user answers Cloud or Agentlas Hub.

After the user chooses a destination, run the app-host auto-update preflight
inside this host app and resolve the runner. Do not ask the user to open a
separate terminal:

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
for candidate in "$HOME/.agentlas/runtime/current/bin/hephaestus" "./bin/hephaestus"; do
  [ -x "$candidate" ] && RUNNER="$candidate" && break
done
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found after app auto-update preflight. See /tmp/hephaestus-app-auto-update.log if it exists." >&2; exit 1; }
```

Before any upload, use the resolved Hephaestus runtime gate. It must validate
the package without assuming any private local checkout:

- Cloud/private-link: `"$RUNNER" package <agent-folder> --visibility private-link`
- Agentlas Hub/marketplace: `"$RUNNER" package <agent-folder> --visibility marketplace`

For Hub upload, the bundled gate blocks missing or generic `publicProfile`, bad
`routing-card.json`, missing package hashes, static security blockers, and
packages that exceed the public bundle limits.

After the user chooses:

- Cloud: upload as the signed-in owner's private Cloud package. Prefer
  `"$RUNNER" publish <agent-folder> --visibility private-link`.
- Agentlas Hub: publish to the public marketplace through the same bundled
  Hephaestus gate. Prefer
  `"$RUNNER" publish <agent-folder> --visibility marketplace`.

When running through a non-interactive host without a TTY, do not call the
question-only gate again after the user has answered. Use one explicit command:

- Cloud: `"$RUNNER" hep-upload <agent-folder> --visibility private-link`
- Agentlas Hub: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace`

If the destination is answered but the target folder is ambiguous, ask for the
exact agent folder before running any upload.
