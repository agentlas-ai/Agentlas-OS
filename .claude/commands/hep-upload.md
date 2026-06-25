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

Before any upload, use the bundled Hephaestus runtime gate. It must validate
the package without assuming any private local checkout:

- Cloud/private-link: `bin/hephaestus package <agent-folder> --visibility private-link`
- Agentlas Hub/marketplace: `bin/hephaestus package <agent-folder> --visibility marketplace`

For Hub upload, the bundled gate blocks missing or generic `publicProfile`, bad
`routing-card.json`, missing package hashes, static security blockers, and
packages that exceed the public bundle limits.

After the user chooses:

- Cloud: upload as the signed-in owner's private Cloud package. Prefer
  `bin/hephaestus publish <agent-folder> --visibility private-link`.
- Agentlas Hub: publish to the public marketplace through the same bundled
  Hephaestus gate. Prefer
  `bin/hephaestus publish <agent-folder> --visibility marketplace`.

If the destination is answered but the target folder is ambiguous, ask for the
exact agent folder before running any upload.
