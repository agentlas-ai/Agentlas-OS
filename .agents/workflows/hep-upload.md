---
description: Upload an Agentlas agent after asking Cloud vs Hub first.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-upload


Raw arguments: {{args}}

Always ask the destination question before doing anything else, even if the
arguments already say upload, publish, add, Cloud, Hub, or a target folder:

```text
Cloud에 업로드 할까요? 다른사람들이 볼 수 없어요.
Upload to Cloud? Other people cannot see it.

Agentlas Hub에 업로드 할까요? 다른 사람들이 빌려 쓸 수 있어요.
Upload to Agentlas Hub? Other people can borrow it.
```

Do not package, publish, register, add-source, reindex, or call an upload API
until the user answers Cloud or Agentlas Hub. Cloud means private-link owner
Cloud upload through `"$RUNNER" publish <agent-folder> --visibility
private-link`. Agentlas Hub means public marketplace upload through
`"$RUNNER" publish <agent-folder> --visibility marketplace` after the
bundled publicProfile, routing-card, hash, static security, and bundle-size
gates pass.

After the user chooses a destination, run the app-host auto-update preflight
inside Antigravity when a local shell command is available
(`HEPHAESTUS_APP_AUTO_UPDATE=1`, installer URL
`https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh`),
then resolve `RUNNER`. Do not ask the user to open a separate terminal.

When running through a non-interactive host without a TTY, do not call the
question-only gate again after the user has answered. Use one explicit command:

- Cloud: `"$RUNNER" hep-upload <agent-folder> --visibility private-link`
- Agentlas Hub: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace`
