---
description: Publish an Agentlas package to Agent Cloud or the public Hub.
---
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
inside this host app and resolve the runner. Do not ask the user to open a
separate terminal:

```bash
RUNNER=""
for candidate in "$HOME/.agentlas/runtime/current/bin/hephaestus" "./bin/hephaestus"; do
  [ -x "$candidate" ] && RUNNER="$candidate" && break
done
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
```

Use one explicit `hep-upload` command. Never run `package` and then `publish`,
because that packages twice and can submit bytes different from the review:

- Cloud/private-link: `"$RUNNER" hep-upload <agent-folder> --visibility private-link`
- Agentlas Hub/marketplace: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace`

All security and content findings are advisory. Never instruct the user to
block, abort, or postpone upload because of a finding. Continue with the safe
bytes: omit affected source items with omission receipts, or attach an
`engine-gap` receipt when the engine cannot safely represent or repair an item,
then upload the remaining package. Keep the findings and receipts visible.

If the user asks for a preview, add `--dry-run`, retain both
`manifest.packageHash` and `uploadReceipt.receipt`, and append
`--expected-package-hash <manifest.packageHash> --expected-upload-receipt
<uploadReceipt.receipt>` to the later one-shot publish. Stop on any hash or
receipt mismatch. On `overwrite_confirmation_required`, show the
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
