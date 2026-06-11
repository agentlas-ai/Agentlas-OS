# /korean-docs

Raw arguments: `$ARGUMENTS`

Read the bundled `SKILL.md` of this plugin, then handle the request with the
kordoc engine:

- No arguments → ask which Korean document to read, fill, compare, or patch.
- A file path → parse it to markdown (`kordoc <file> --silent`) and summarize:
  document type, headings, tables, and any `needsOcr`/quality warnings.
- `fill <template> ...` → run the form-fill flow (`--dry-run` first, then
  fill and report which fields were applied or skipped).
- `patch <original> <edited.md>` → format-preserving round-trip patch; always
  surface `skipped[]` and the verification report.
- `compare <a> <b>` → block-level diff presented as 신구대조표.

Resolve the kordoc runtime per the SKILL.md resolution order. Reply in the
user's language (Korean documents usually mean Korean replies).
