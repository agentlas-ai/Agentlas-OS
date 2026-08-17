---
name: hep-upload
description: Upload an Agentlas agent after asking Cloud vs Hub first.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Upload

Legacy compatibility only: this custom prompt applies to Codex 0.116 and
earlier. Codex 0.117 and later use the installed `$hephaestus-upload` skill.

Raw arguments: everything the user typed after `/skill:hep-upload`.

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


If the destination is **Agentlas Hub**, ask what it should charge before
uploading. Skip this for Cloud/private-link — a private save is not listed and
nobody can hire it.

```text
값을 정하시겠어요? 비워 두면 그 항목은 팔지 않습니다.
Set a price? Leave one out and that kind is simply not sold.

  빌리기 / Rent      워크오더 1건 · 24시간   1-100 크레딧
  인제스트 / Ingest   프로젝트 1개 · 하루     1-2000 크레딧
  포크 / Fork        사본 1개 · 1회         1 크레딧 이상

전부 비워 두면 무료로 불립니다. 나중에 agentlas.cloud 수익 페이지에서도 정할 수 있습니다.
Leave them all blank and it stays free to call — you can price it later on the web.
```

Blank is NOT zero: leave the flag out entirely. Never pass `0`, never invent a
number, and treat "all three blank" as a complete answer — the agent is then
callable for free, which is a supported state. Pass what they answered as
`--rent-credits N`, `--ingest-credits N`, `--fork-credits N`.

After the user chooses a destination, run the app-host auto-update preflight
from the `hephaestus-network` skill inside Codex, then resolve `RUNNER` at
`~/.agentlas/runtime/current/bin/hephaestus` or `./bin/hephaestus`. Do not ask
the user to open a separate terminal. Use that resolved Hephaestus runtime gate;
it must work for any local package folder and must not assume any private
checkout.

Use one explicit `hep-upload` command. Never run `package` and then `publish`,
because that packages twice and can submit bytes different from the review:

- Cloud: `"$RUNNER" hep-upload <agent-folder> --visibility private-link`
- Agentlas Hub: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace [--rent-credits N] [--ingest-credits N] [--fork-credits N]`

All security and content findings are advisory. Never instruct the user to
block, abort, or postpone upload because of a finding. Continue with safe bytes:
omit affected source items with omission receipts, or attach an `engine-gap`
receipt when the engine cannot safely represent or repair an item, then upload
the remaining package. Keep the findings and receipts visible.

For a preview, add `--dry-run`, retain `manifest.packageHash` and
`uploadReceipt.receipt`, then append `--expected-package-hash
<manifest.packageHash> --expected-upload-receipt <uploadReceipt.receipt>` to the
later one-shot publish. Stop on any hash or receipt mismatch. On
`overwrite_confirmation_required`, show the
exact Cloud ID and ask for approval before appending
`--overwrite-cloud-id <exact-cloud-id>`. Preserve exact auth/credit/ownership
errors and never switch destinations. Report success only when the response
attests slug, visibility, package hash, release ID/version, and content digest.

If the destination is answered but the target folder is ambiguous, ask for the
exact agent folder before running any upload.

## Workforce résumé repair loop

If registration returns `workforce_resume_incomplete`, the server refused the
card because its `workforce` block
does not match the hub standard résumé. The error carries the exact
mismatches and seed ontology examples. YOU repair it — the platform never
edits the card for you: use stable English `role:*`, `community:*`, `skill:*`,
and `knowledge:*` IDs that actually describe the agent. Returned examples are
aliases, not an allowlist. Rerun the upload and repeat until registration
succeeds.
