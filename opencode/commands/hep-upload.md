Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-upload


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
from the `hephaestus-network` skill inside OpenCode, then resolve `RUNNER` at
`~/.agentlas/runtime/current/bin/hephaestus` or `./bin/hephaestus`. Do not ask
the user to open a separate terminal.

Never run `package` and then `publish`; that packages twice. Use one immutable
gate:

- Cloud: `"$RUNNER" hep-upload <agent-folder> --visibility private-link`
- Agentlas Hub: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace`

All security and content findings are advisory. Never instruct the user to
block, abort, or postpone upload because of a finding. Continue with safe bytes:
omit affected source items with omission receipts, or attach an `engine-gap`
receipt when the engine cannot safely represent or repair an item, then upload
the remaining package. Keep the findings and receipts visible.

For a preview, add `--dry-run`, retain `manifest.packageHash` and
`uploadReceipt.receipt`, then append `--expected-package-hash
<manifest.packageHash> --expected-upload-receipt <uploadReceipt.receipt>` to the
later publish. Stop on any hash or receipt mismatch. On
`overwrite_confirmation_required`, show the exact
Cloud ID and ask for approval before appending
`--overwrite-cloud-id <exact-cloud-id>`. Preserve exact auth/credit/ownership
errors and never switch destinations. Report success only when the response
attests slug, visibility, package hash, release ID/version, and content digest.
