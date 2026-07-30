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

## 3. Validate through the bundled gate

The gate must validate the package without assuming any private local checkout:

- Cloud / private-link: `"$RUNNER" package <agent-folder> --visibility private-link`
- Agentlas Hub / marketplace: `"$RUNNER" package <agent-folder> --visibility marketplace`

For a Hub upload the gate blocks a missing or generic `publicProfile`, an invalid
`routing-card.json`, missing package hashes, static security blockers, and
bundles over the public size limits. It repairs what it can derive from the
package rather than refusing — including the entity type: a card that claims
`agent` while the package ships a multi-node roster is corrected to `team`, so
the release is priced and executed as the team it actually is.

## 4. Publish

- Cloud: `"$RUNNER" publish <agent-folder> --visibility private-link`
- Agentlas Hub: `"$RUNNER" publish <agent-folder> --visibility marketplace`

On a non-interactive host with no TTY, do not call the question-only gate again
after the user has answered. Use one explicit command:

- Cloud: `"$RUNNER" hep-upload <agent-folder> --visibility private-link`
- Agentlas Hub: `"$RUNNER" hep-upload <agent-folder> --visibility marketplace`

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

Report `published` only when registration actually succeeded, and say which
destination it went to. Otherwise report the last true state — `validated`,
`blocked`, or `failed` — with the server's exact refusal code.
