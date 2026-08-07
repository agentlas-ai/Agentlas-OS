# Ontology-Backed Agent

## Purpose

Create an agent whose answers must be grounded in a local document corpus:
retrieval-first, source-cited generation backed by the local-first ontology
runtime (SQLite + FTS5 trigram + local vectors + GraphRAG + Memory Curator).
This mode composes with `single-agent-creator` or `team-builder`; it sets
`ontology_backed: true` on top of the base mode instead of replacing it.

## Use When

- The request depends on knowledge search over user documents (company docs,
  past proposals, contracts, quotes, manuals).
- The request asks for evidence-based or citation-attached generation
  (제안서/계약서/견적서, reports, briefs).
- The corpus includes HWPX, docx, pdf, xlsx, pptx, or OCR-image sources.

## Required Structure (added on top of the base mode)

- Activate `bin/ontology` for the generated package: seed
  `.agentlas/ontology-sources.json` and `.agentlas/ontology-inbox/`.
- The generated `agent.md` must state a retrieval-first workflow:
  query GraphRAG first (`bin/ontology query`), then generate, and attach a
  source ref (source_id + span) to every claim that came from the corpus.
- Inject contracts by rule, not blanket: resolve the task traits against
  `.agentlas/contract-injection-map.json` and inject only matching contracts
  plus the baseline. Record the resolved list in the generated
  `.agentlas/injected-contracts.json`.
- Set `loop_policy` (none / self-correct / verified) from the risk tier in the
  injection map. External writes or sends force `verified`.
- When `loop_policy` is `verified`, generate a verifier that runs in a separate
  context from the drafting agent (no self-grading) and checks citation
  presence and source-span consistency.

## Data Sovereignty

- The local ontology DB stays in the project (`.agentlas/ontology-runtime.sqlite`).
- Chunks with `privacy_scope` private/confidential must never be passed to
  cloud LLM hooks (query expansion / rerank) or to the cloud Hub MCP; they are
  served only through local paths. The runtime enforces this gate; the
  generated agent must not work around it.

## Loop Policy

- `none`: single execution for simple one-shot tasks. No loop overhead.
- `self-correct`: execute, grade against environment criteria, retry; for
  complex or long-running drafting tasks.
- `verified`: self-correct plus a separate-context verifier and the
  `side-effect-containment` human gate before any submission or send.

## Do Not

- Do not blanket-inject all 26 governance contracts into one agent.
- Do not let the drafting agent grade its own output when `loop_policy` is
  `verified`.
- Do not send private/confidential scope chunk text to cloud LLM hooks.
- Do not skip `bin/ontology verify` in the generated package's verification.
