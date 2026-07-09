# Agentlas Career Graph Implementation Handoff

Date: 2026-07-09
Status: implementation wired across engine, desktop, terminal, and Agentlas web;
not final public README pass

## Intent

This change moves the project from a vague public "ontology" story toward a
ledger-first Agentlas Career Graph:

- Markdown, JSONL, sitemap, code map, receipts, run journals, and proposal
  ledgers remain the source of truth.
- Career Graph is a rebuildable local SQLite index over those files.
- Agents use the graph as a source-routing layer, then inspect canonical files.
- Public Hub and Desktop upload flows receive only a redacted aggregate career
  card, never raw local paths, prompts, transcripts, source text, or secrets.

## Main Changes

### Hephaestus Engine

- Added `career_graph/` runtime and `bin/career-graph`.
- Added `bin/hephaestus career-graph ...` dispatch.
- Added ingest/query/trace/verify/public-card commands.
- Added source ingestion for:
  - project memory;
  - memory logs and curator decisions;
  - sitemap;
  - code map;
  - run journals;
  - routing and execution receipts;
  - agent evolution proposal ledgers.
- Added derived node promotion:
  - `FailureSignature`;
  - `PlaybookCandidate`;
  - `EvolutionProposal`.
- Added redacted `.agentlas/public-career-card.json`.
- Added upload packaging validation and auto-generation for public cards.

### Desktop

- Added `career_graph` module support in the Hephaestus runner.
- Project attach now creates Career Graph config/source/inbox files.
- Active project invocation refreshes Career Graph in the background.
- Prompt context can include bounded Career Graph source refs.
- Agent self-evolution proposals append content-free lifecycle events to
  `.agentlas/ledgers/agent-evolution-proposals.jsonl` when project path metadata
  is available.
- Desktop cloud-agent packaging validates and includes redacted `careerGraph`.
- Desktop upload UI renders a Career Graph proof section when present.

### Terminal

- Added `career-graph` command surface and REPL alias.
- `career-graph ingest/query/verify/trace/public-card` delegates to the real
  Career Graph runtime instead of Hub search.
- Terminal status lists the evolution proposal ledger as a canonical source.

### Agentlas Hub Web

- Cloud-agent registration accepts `manifest.careerGraph` or
  `bundle.careerGraph`, validates it as a redacted public card, and persists it
  on `manifest.cloudPackage.careerGraph`.
- Registration rejects unsafe cards that omit privacy false flags or contain
  local absolute path patterns.
- Hosted public profile route `/p/[slug]` renders the redacted Career Graph
  proof through the existing `EntityDetail` `afterSections` slot when present.

### Adapter Mirrors

- `scripts/sync-adapters.sh` copies `career_graph/` and `bin/career-graph` into
  the Claude and Codex plugin mirrors.

## Current Verification

Run from `/Users/mason/Documents/Agentlas_F/agentlas_desktop/Hephaestus`:

```bash
scripts/verify-package.sh
scripts/sync-adapters.sh --check
python3 -m pytest tests/test_career_graph_runtime.py tests/test_upload.py
git diff --check
```

Run from `/Users/mason/Documents/Agentlas_F/agentlas_desktop`:

```bash
npm run typecheck
npm run test:cloud-agent-package
node scripts/smoke-renderer-ui.cjs --logic-only
git diff --check
```

Run from `/Users/mason/Documents/Agentlas_F/agentlas_terminal`:

```bash
node --check engine/agentlas.cjs
node --check engine/agentlas-parity.cjs
node --check engine/agentlas-input.cjs
node --check engine/agentlas-repl.cjs
node --check engine/agentlas-i18n.cjs
git diff --check
```

Run from `/Users/mason/Documents/Agentlas_F/agentlas/AgentsAtlas/app`:

```bash
npm run typecheck
git diff --check -- src/types.ts src/app/api/cloud-agents/v1/register/route.ts 'src/app/p/[slug]/page.tsx'
```

## Known Boundaries

- Hosted Agentlas Hub web code is wired, but the live deployed URL still needs
  verification with a package that includes `careerGraph`.
- README and screenshot changes are intentionally deferred. See
  `docs/agentlas-career-graph-redesign-plan.md` for the copy and image checklist.
- Worktrees contain unrelated or earlier uncommitted changes. Stage by file,
  not by whole repo, unless you intentionally want to include those changes.
- Do not treat `ontology` as removed. It is still present as an internal/legacy
  runtime and should be demoted publicly later rather than deleted abruptly.

## Suggested Commit Split

1. Hephaestus Career Graph engine and upload guards.
2. Desktop Career Graph project wiring and upload UI proof.
3. Terminal Career Graph command surface.
4. Agentlas Hub web registration persistence and `/p/[slug]` proof rendering.
5. Documentation handoff and README-change checklist.
