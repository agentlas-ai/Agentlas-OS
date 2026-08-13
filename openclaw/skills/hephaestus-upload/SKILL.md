---
name: hephaestus-upload
description: "Use when the user asks to upload or publish an Agentlas agent or team. Ask Cloud private vs Agentlas Hub public FIRST, then use the bundled immutable upload gate."
metadata: {"openclaw": {"emoji": "🔨", "requires": {"bins": ["python3"]}, "homepage": "https://github.com/agentlas-ai/Agentlas-OS"}}
---

# Hephaestus Upload (Cloud or Agentlas Hub)

This is a WRITE surface. Ask the destination before packaging, publishing,
registering, reindexing, or calling an upload API:

```text
Cloud에 업로드 할까요? 다른사람들이 볼 수 없어요.
Upload to Cloud? Other people cannot see it.

Agentlas Hub에 업로드 할까요? 다른 사람들이 빌려 쓸 수 있어요.
Upload to Agentlas Hub? Other people can borrow it.
```

If the destination is known but the package folder is ambiguous, ask for the
exact folder. Never infer or switch the destination.

## Resolve the runner

```bash
RUNNER=""
for candidate in "$HOME/.agentlas/runtime/current/bin/hephaestus" "./bin/hephaestus"; do
  [ -x "$candidate" ] && RUNNER="$candidate" && break
done
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
```

## Preview and publish one immutable artifact

Never run `package` and then `publish`; use one snapshotting gate:

- Cloud: `"$RUNNER" hep-upload <agent-folder> --visibility private-link`
- Agentlas Hub: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace`

For a preview, add `--dry-run` and retain both `manifest.packageHash` and
`uploadReceipt.receipt`. The later publish must append:

```text
--expected-package-hash <manifest.packageHash> --expected-upload-receipt <uploadReceipt.receipt>
```

All security and content findings are advisory. Never instruct the user to
block, abort, or postpone upload because of a finding. Continue with safe bytes:
omit affected source items with omission receipts, or attach an `engine-gap`
receipt when the engine cannot safely represent or repair an item, then upload
the remaining package. Keep the findings and receipts visible.

The receipt binds the hash, visibility, slug, and destination. Stop on
`package_hash_mismatch`, `upload_receipt_required`, or
`upload_receipt_mismatch`.

On `overwrite_confirmation_required`, show the exact server-reported Cloud ID
and ask for approval. Only after approval append
`--overwrite-cloud-id <exact-cloud-id>` to the same pinned command. Never infer
overwrite authority from a matching slug.

Preserve exact authentication, credit, ownership, and destination refusal
codes. Report success only when the server attests the exact slug, visibility,
package hash, immutable release ID/version, and content digest.
