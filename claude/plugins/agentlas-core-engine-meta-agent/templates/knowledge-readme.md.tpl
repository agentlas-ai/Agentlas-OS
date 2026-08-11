# Knowledge

RAG source material for {{PACKAGE_NAME}}, dropped in as files this agent can
retrieve at runtime — not build-time context, not this package's own docs
(those stay in `docs/`).

Supported types (per Agentlas's ontology runtime parser matrix): markdown,
txt, json, csv, docx, xlsx, pptx, pdf, hwpx, hwp5 (OCR fallback). Markdown is
the recommended canonical form; keep original non-markdown source files under
`knowledge/sources/` if you convert them.

This folder is optional. An empty `knowledge/` is a valid, common state — most
agents work from `agent.md` + skills alone.
