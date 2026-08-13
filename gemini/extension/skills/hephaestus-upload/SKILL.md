---
name: hephaestus-upload
description: "Use when the user types $hephaestus-upload or /hep-upload, or asks to upload, publish, or list an Agentlas agent or team. Ask Cloud (private) vs Agentlas Hub (public) FIRST, then publish through the bundled Hephaestus gate."
---

# Hephaestus Upload (Cloud or Agentlas Hub)

Publish a finished Agentlas package. This is a WRITE surface: a Hub upload is
public and other people can borrow it, so the destination question comes before
any packaging or API call.

Upload is deliberately NOT folded into `/hep-network`. Network staffs a roster
(a read), upload publishes an artifact (a write that is hard to take back);
merging them would let "find me an agent" end in an accidental publish.

## 1. Ask the destination first — always

Ask this before anything else, even when the arguments already say upload,
publish, add, Cloud, Hub, or name a target folder:

```text
Cloud에 업로드 할까요? 다른사람들이 볼 수 없어요.
Upload to Cloud? Other people cannot see it.

Agentlas Hub에 업로드 할까요? 다른 사람들이 빌려 쓸 수 있어요.
Upload to Agentlas Hub? Other people can borrow it.
```

Do not package, publish, register, add-source, reindex, or call any upload API
until the user answers Cloud or Agentlas Hub. If the destination is answered but
the target folder is ambiguous, ask for the exact agent folder before running
anything.

## 2. Resolve the runner in this host

Run the preflight inside this host app; never ask the user to open a separate
terminal.

```bash
RUNNER=""
for candidate in "$HOME/.agentlas/runtime/current/bin/hephaestus" "./bin/hephaestus"; do
  [ -x "$candidate" ] && RUNNER="$candidate" && break
done
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
```

## 3. Use one immutable upload gate

Do not run `package` and then `publish`: that packages twice and the second
artifact may differ from the one reviewed. The upload gate copies the selected
folder into a private, link-free snapshot, repairs and validates that snapshot
once, and either dry-runs or submits those exact bytes.

If the user requests a preview, run exactly one dry-run and retain the returned
`manifest.packageHash` and `uploadReceipt.receipt`:

- Cloud: `"$RUNNER" hep-upload <agent-folder> --visibility private-link --dry-run`
- Agentlas Hub: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace --dry-run`

All security and content findings are advisory. Never instruct the user to
block, abort, or postpone an upload because of a finding. Continue the same
upload with safe bytes: omit each affected source item and bind an omission
receipt, or record an `engine-gap` receipt when the current engine cannot safely
represent or repair it, then submit the remaining package. Keep every finding
and omission visible in the result. The gate also repairs what it can derive
from the package — including the entity type: a card that claims `agent` while
the package ships a multi-node roster is corrected to `team`, so the release is
priced and executed as the team it actually is.

## 4. Publish once, optionally pinned to the preview

- Cloud: `"$RUNNER" hep-upload <agent-folder> --visibility private-link`
- Agentlas Hub: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace`

After a dry-run, append both `--expected-package-hash <manifest.packageHash>` and
`--expected-upload-receipt <uploadReceipt.receipt>` to the one publish command.
The receipt binds the exact hash, visibility, slug, and destination. Stop on
`package_hash_mismatch`, `upload_receipt_required`, or
`upload_receipt_mismatch`; never silently publish a replacement artifact or
switch an approved private preview to the public Hub.

If registration returns `overwrite_confirmation_required`, show the exact
server-reported Cloud ID and ask for overwrite approval. Only after approval,
rerun the same pinned command with `--overwrite-cloud-id <exact-cloud-id>`.
Never infer overwrite permission from a matching slug.

Surface authentication and entitlement codes exactly (`sign_in_required`,
`auth_unavailable`, `insufficient_credits`, `owner_only`). Do not replace a
failed Hub destination with Cloud or vice versa.

## 5. Workforce résumé repair loop

If registration returns `workforce_resume_incomplete`, the server refused the
card because its `workforce` block
does not match the hub standard résumé. The error carries the exact mismatches
and seed ontology examples. YOU repair it — the platform never edits the card
for you: use stable English `role:*`, `community:*`, `skill:*`, and
`knowledge:*` IDs that actually describe the agent. The returned examples are
aliases, not an allowlist. Rerun the upload and repeat until registration
succeeds.

## 6. Report honestly

Report `published` only when the response attests the exact slug, visibility,
package hash, immutable release ID/version, and content digest. Say which
destination it went to. Otherwise report the last true state and the server's
exact refusal code. Do not relabel an advisory finding as an upload block.
