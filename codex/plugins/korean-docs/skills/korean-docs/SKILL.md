---
name: korean-docs
description: "Use whenever the user works with Korean documents — HWP, HWPX, HWPML, 공문서, 한글 문서, government/office files, Korean PDFs/XLS/DOCX — to read them as markdown, compare versions, fill 양식 (forms), or write edits back with the original formatting preserved."
---

# Korean Document Reading & Writing (kordoc)

This plugin gives agents first-class Korean document ability via the kordoc
engine (vendored at `vendor/kordoc`, MIT). It parses HWP 3.x/5.x, HWPX,
HWPML, PDF, XLS, XLSX, DOCX into markdown with 99.9%+ text recall and exact
table reproduction, and writes changes back without touching the original
formatting.

## Runtime resolution

Resolve the kordoc runner in this order, then reuse it for every call:

1. `$KORDOC_BIN` if set.
2. `node <repo>/vendor/kordoc/dist/cli.js` if the vendored package is built.
3. `kordoc` on PATH.
4. `npx -y kordoc` (zero-install; downloads from npm — confirm with the user
   once per session before first use).

If MCP tools named `parse_document`, `parse_table`, `parse_form`, `fill_form`,
`compare_documents`, `parse_metadata`, `parse_pages`, or `detect_format` are
already connected (kordoc MCP server from this plugin's `.mcp.json`), prefer
them over shelling out.

## Reading (문서 → 마크다운)

```bash
kordoc <file> --silent                 # markdown to stdout (format auto-detected)
kordoc <file> --format json --silent   # full ParseResult JSON (blocks, tables, metadata)
kordoc <file> -p 1-3 --silent          # page/section range only
```

- Tables (병합 셀, 중첩표 포함) arrive as markdown tables — read them as data,
  do not re-OCR.
- PDF results include `pageQuality`/`needsOcr` signals in JSON mode; if
  `needsOcr` is true, tell the user the text layer is broken instead of
  guessing.
- Old HWP 3.x (1996–2002) and 배포용/DRM documents: kordoc decodes johab and
  distribution-encrypted files; if it refuses, report the reason verbatim.

## Writing (마크다운 → 문서, 서식 보존)

- **Edit an existing document** (서식 1바이트도 보존): parse to markdown, make
  the textual edits, then
  `kordoc patch <original.hwpx|.hwp> <edited.md> -o <out>` — only changed
  paragraph/cell text is replaced; unsupported edits are reported in
  `skipped[]`, never silently applied. Always relay `skipped[]` to the user.
- **Fill a form/양식** (신청서, 보고서 템플릿):
  `kordoc fill <template.hwpx> -f '성명=홍길동,연락처=010-...' -o <out.hwpx>`
  (or `-j fields.json`). Use `--dry-run` first to list detected fields.
- **New document from markdown**: use the library API
  `import { markdownToHwpx } from "kordoc"` in a small Node script when the
  user needs a fresh HWPX (themes via `HwpxTheme`).

## Comparing (신구대조)

`compare_documents` (MCP) or the library `compare()` diff two documents at
block level — works across formats (HWP vs HWPX). Summarize as a 신구대조표:
변경 전 / 변경 후 / 비고.

## Ontology ingestion

The Hephaestus ontology runtime already routes `.hwp/.hwpx/.hml/.pdf/.docx/
.xls/.xlsx` through this engine (`ontology/kordoc_adapter.py`). To index
Korean documents: `bin/hephaestus ontology add <path>` — no extra steps.

## Guardrails

- Never send document contents to external services; kordoc runs locally.
- Respect `KORDOC_DISABLE=1` (adapter off) and never auto-run `npx` without
  the session-level confirmation above.
- Report parse failures with kordoc's Korean error message as-is; do not
  fabricate document text.
