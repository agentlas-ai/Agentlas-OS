# Hephaestus Network Hub Routing Optimization

Status: design + first hotfix plan  
Date: 2026-06-15  
Owners: Hephaestus Network, Agentlas Hub

## Goal

Make Hub routing fast, low-token, multilingual, and accurate:

- never send raw prompts or local memory to Hub;
- return only the few candidates a model can actually inspect;
- route Korean, English, and mixed queries by semantic intent, not brittle tokens;
- expose trust signals that distinguish real execution quality from static `trustGrade: A`;
- deduplicate auto-generated near-clones before they hit model context;
- ask a clarify question when confidence is low instead of dumping 80+ candidates.

## Current Failures Observed

1. Windows install/runtime self-heal is missing.
   `python3` can be a Microsoft Store stub and cp949 stdout can crash JSON output
   with Unicode text.

2. Tokenizer noise leaks into Hub search.
   Example: `추천좀` was treated as a full token and produced bad bigrams such as
   `천좀`. The Hub query became noisy and wasteful.

3. Hub results are too large.
   The server can return dozens of full objects with `manifestUrl`, long
   taglines, and duplicated near-identical agents. Those fields are not needed
   for routing.

4. Hub search has no successful-response TTL cache on the client.
   Offline cache exists, but repeated successful queries still hit the network.

5. Trust is flat.
   If every candidate is `trustGrade: A` and `installCount: 0`, trust is not a
   ranking signal.

## Hotfixes

Already appropriate for the local runtime:

- Strip Korean sentence/filler suffixes (`좀`, `요`, `죠`, `네`, `까`) during
  tokenization.
- Before sending Hub query tokens, remove Hangul 2-character fragments that are
  substrings of longer Hangul query terms.
- Cap Hub results to top K, default 10.
- Project Hub results to routing-critical fields only:
  `slug`, `name`, `nameEn`, `kind`, `callable`, `routingReady`,
  `routingStatus`, `trustGrade`, `installCount`, plus future live trust fields.
- Cache successful Hub results by redacted query for 10 minutes.
- Rerank returned Hub results by token overlap, callable/routing readiness, and
  verified invocation signals before returning to the model.
- Deduplicate near-identical names before returning.

Server-side matching should also default to `limit=10` and compact results.
Clients can request `verbose=true` only when installing or inspecting details.

## Target Server Architecture

### 0. General Tool Search Architecture

Do not solve routing by adding one-off tokenizer exceptions. Treat Agentlas Hub
as a tool/API retrieval system:

1. **Routing document generation.** Every published agent/team/plugin becomes a
   compact routing document: name, slug, localized descriptions, capabilities,
   trigger examples, anti-triggers, inputs/outputs, runtime kind, and safety
   class. Metadata like `routingReady` and trust grade are ranking priors, never
   lexical relevance fields.
2. **Two candidate generators.**
   - Sparse lexical retrieval (BM25/full-text or corpus-IDF fallback) catches
     exact slug/name/capability matches.
   - Dense multilingual retrieval catches synonyms, Korean/English mixed
     phrasing, and intent wording that does not share literal tokens.
3. **Rank fusion.** Merge sparse and dense result lists with Reciprocal Rank
   Fusion (RRF), so score scales from different systems do not need brittle
   hand tuning.
4. **Second-stage rerank.** Rerank only the top 30-50 candidates using a
   routing-specific scorer: task/capability fit, trigger support, anti-trigger
   penalty, trust telemetry, and runtime availability.
5. **Diversity / dedup.** Use MMR or embedding-cluster representatives so the
   model sees distinct choices, not generated near-clones.
6. **Confidence gate.** If top score is low, margin is small, or evidence comes
   only from weak n-grams/generic terms, return `action: clarify`.
7. **Evaluation loop.** Store multilingual labeled queries and measure Recall@K,
   MRR/NDCG, clarify precision, duplicate reduction, payload bytes, p95 latency,
   and unsafe route rate. New heuristics are only accepted when they improve the
   benchmark, not because they fix one observed string.

Research basis:

- ToolLLM/ToolBench shows large tool libraries need API retrieval plus
  evaluation, not prompt-only guessing.
- Gorilla shows API/tool documentation retrieval reduces wrong API selection and
  hallucinated calls when tool specs change.
- ToolRerank shows that better first-stage retrieval alone is not enough; a
  tool-aware rerank stage improves downstream execution.
- RRF is a robust way to combine independent sparse/dense rankers without
  assuming comparable score scales.
- MMR addresses the exact duplicate/near-clone failure mode by optimizing for
  relevance plus novelty.
- MTEB/MMTEB/MIRACL-style benchmarks imply we must test multilingual retrieval
  explicitly rather than assume one embedding model wins every language/task.

### 1. Agent Registration Embedding Job

On publish or profile update, compute and persist a semantic routing embedding.
Use OpenAI embeddings as a managed baseline:

- default model: `text-embedding-3-small`;
- dimensions: start at 512 or 768 for storage/query speed, benchmark against
  full 1536;
- upgrade candidate: `text-embedding-3-large` at 1024 dims only if Korean/English
  benchmark recall is materially better.

Canonical embedding text:

```text
name: <ko/en name>
slug: <slug>
tagline: <short ko/en tagline>
capabilities: <capability verbs>
trigger examples: <curated examples>
anti triggers: <negative examples>
runtime kind: cloud-callable | install-only | team
```

Persist:

```json
{
  "slug": "agent-slug",
  "embeddingModel": "text-embedding-3-small",
  "embeddingDims": 768,
  "embeddingTextHash": "sha256:...",
  "embedding": [0.01, -0.02],
  "routingTextVersion": 1,
  "indexedAt": "2026-06-15T00:00:00Z"
}
```

The job is idempotent. If `embeddingTextHash` is unchanged, skip API work.

### 2. Vector Store

Use MongoDB Atlas Vector Search first because Agentlas Web already uses Mongo.
It supports vector search beside operational metadata, hybrid search, and
metadata filters. A Postgres/pgvector migration is only worth it if the Hub
store moves to Postgres.

Mongo index:

```js
{
  "fields": [
    { "type": "vector", "path": "routing.embedding", "numDimensions": 768, "similarity": "cosine" },
    { "type": "filter", "path": "status" },
    { "type": "filter", "path": "kind" },
    { "type": "filter", "path": "routingReady" }
  ]
}
```

Query flow:

1. Client sends redacted compact query tokens or short query text.
2. Server normalizes and embeds the query.
3. Vector search gets top 50 candidates with filters.
4. Lexical scorer rescues exact slug/name/capability hits.
5. Dedup clusters candidates.
6. Trust reranker orders the final top 10.
7. If confidence is low or clusters are dispersed, return `clarify` instead of
   `results`.

### 3. Hybrid Ranking Formula

Use a deterministic weighted rank after vector retrieval:

```text
score =
  0.45 * semantic_similarity
+ 0.20 * lexical_overlap
+ 0.15 * task_success_score
+ 0.10 * routing_readiness
+ 0.05 * freshness
+ 0.05 * user_fit_local_hint
- duplicate_penalty
- stale_or_untrusted_penalty
```

`user_fit_local_hint` is privacy-preserving: the client sends local inventory
categories or hashed capability hints, not raw local file paths or memory.

### 4. Trust Signals

Replace flat trust display with route-useful fields:

```json
{
  "trustGrade": "A",
  "evalPassRate": 0.93,
  "verifiedInvocations": 128,
  "lastRoutingSuccessAt": "2026-06-14T12:34:00Z",
  "recentFailureRate": 0.02,
  "rating": 4.7,
  "ratingCount": 18
}
```

Definitions:

- `evalPassRate`: passed benchmark/eval cases divided by executed eval cases.
- `verifiedInvocations`: Hub calls that reached prepared/executed state without
  policy/runtime failure.
- `lastRoutingSuccessAt`: last time the agent was selected and not rejected.
- `recentFailureRate`: failures in a rolling 7 or 30 day window.
- `rating`: explicit user feedback only, separate from implicit success.

Ranking should prefer "12 successful routes for this task family" over static
"trust A".

### 5. Dedup / Clustering

Dedup should happen before the response:

- cluster by embedding similarity >= 0.92;
- also cluster by normalized name/slug signatures for generated variants;
- choose representative by trust score, callable status, eval pass rate, and
  freshness;
- return `clusterSize` and `alsoMatched` only in verbose/debug mode.

The model should see 8-10 distinct choices, not 81 variants.

### 6. Clarify Loop

Return a clarify action when:

- top score is below threshold;
- top two clusters are within margin;
- the top 10 span unrelated capability clusters;
- query contains generic words only (`추천`, `agent`, `feature`, `new`);
- no candidate has both semantic and lexical support.

Response shape:

```json
{
  "action": "clarify",
  "question": "어떤 작업을 맡길 에이전트를 찾고 있나요?",
  "options": [
    {"label": "새 에이전트 만들기", "hint": "meta-agent / builder"},
    {"label": "기존 에이전트 실행", "hint": "runtime bundle"},
    {"label": "Hub에서 플러그인 찾기", "hint": "tool/plugin discovery"}
  ],
  "receiptId": "..."
}
```

### 7. Client Personalization

Keep personalization local-first:

- client computes local inventory capability tokens;
- Hub receives only coarse hints, for example
  `["finance-analysis", "korean-docs", "app-store-ops"]`;
- client reranks Hub top 10 using local complementarity:
  "things that complete the user's current stack";
- no local agent names, paths, memory, or private card text are sent by default.

### 8. Cost Model

Using OpenAI `text-embedding-3-small` at $0.02 per 1M tokens:

- 10,000 agents * 800 routing tokens = 8M tokens ~= $0.16 one-time index cost.
- 1,000,000 monthly queries * 24 tokens = 24M tokens ~= $0.48/month.

Embedding cost is not the bottleneck. The real constraints are vector index
quality, result compression, cache hit rate, and trust telemetry.

### 9. 100k Network Call Estimate

Current production topology for Hub calls:

- `hephaestus route` runs local routing first.
- Hub fallback calls `https://agentlas.cloud/api/mcp/v1` only with redacted
  routing keywords.
- `agentlas.cloud` is the Railway `agentlas-web` service.
- public marketplace data is stored in MongoDB Atlas.
- model execution remains BYOK/BYOM for invoked agents; the Hub search path
  should not call an LLM.

For 100,000 total Hub search calls in a month, the marginal bill should be
small if responses stay compact and Mongo caching works:

| Cost line | Driver | 100k call estimate |
| --- | --- | --- |
| Railway CPU | request CPU time | usually well under $1 unless each request does heavy DB work |
| Railway memory | active service wall time | base service cost dominates; roughly a GB-month class charge if warm all month |
| Railway egress | compact JSON response bytes | 100k * 2-8KB ~= 0.2-0.8GB, only cents at $0.05/GB |
| MongoDB Atlas | cluster tier, reads, vector/search capacity | likely the real scaling line; current cache avoids a DB read on every repeated query |
| OpenAI embeddings | only if semantic query embedding is enabled | 100k * 24 tokens = 2.4M tokens ~= $0.05 |
| LLM generation | invoked agent runtime | $0 on Agentlas server when BYOK/BYOM; user's host/runtime pays |

For 100,000 users, use `network_calls = users * calls_per_user`. The breakpoints:

- 100k total calls/month: existing Railway minimum + Atlas base tier likely
  dominates; per-call increment is near-zero.
- 1M total calls/month: still not an LLM-cost problem; watch Mongo latency,
  response payload bytes, and cache hit rate.
- 10M+ calls/month: add Redis/edge cache for public catalog search, precomputed
  semantic vectors, and separate search capacity before increasing app
  replicas.

## Rollout Plan

Phase 0: runtime hotfix

- tokenizer suffix strip;
- Hub top-K projection;
- successful TTL cache;
- local rerank/dedup;
- Windows `doctor` + UTF-8 output.

Phase 1: Hub API contract

- `marketplace.search_agents({ q, limit, verbose })`;
- default compact result shape;
- response includes `total`, `limit`, and optional `clarify`.

Phase 2: trust telemetry

- record verified invocation events;
- compute rolling success/failure counters;
- expose trust fields in compact results.

Phase 3: semantic index

- embed on publish/update;
- create MongoDB Vector Search index;
- add vector + lexical hybrid query endpoint;
- run shadow mode beside current lexical scorer.

Phase 4: evaluation gate

- multilingual benchmark suite with ko/en/mixed queries;
- metrics: top1, top3, MRR, clarify correctness, duplicate cluster reduction,
  payload bytes, p95 latency, cache hit rate;
- promote semantic ranker only when it beats lexical baseline and keeps
  payload under target.

## Acceptance Targets

- Hub response payload p50 < 8KB and p95 < 15KB for search.
- Default result count <= 10.
- Duplicate cluster reduction >= 80% on generated-agent batches.
- Korean/English/mixed top3 recall >= 0.90 on benchmark.
- Low-confidence ambiguous queries return clarify instead of >10 results.
- Repeated identical query within 10 minutes performs zero network calls from
  local runtime.
- Windows doctor detects Store stub `python3` and writes a working shim when a
  real Python launcher exists.

## References Checked

- ToolRerank: https://arxiv.org/html/2403.06551v1
- ToolLLM / ToolBench: https://arxiv.org/abs/2307.16789
- Gorilla API retrieval: https://arxiv.org/abs/2305.15334
- Reciprocal Rank Fusion: https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/
- MongoDB hybrid search / RRF: https://www.mongodb.com/docs/atlas/atlas-search/tutorial/hybrid-search/
- MMR diversity reranking: https://www.cs.cmu.edu/~jgc/publication/The_Use_MMR_Diversity_Based_LTMIR_1998.pdf
- MTEB embedding benchmark: https://aclanthology.org/2023.eacl-main.148/
- MMTEB multilingual embedding benchmark: https://openreview.net/forum?id=zl3pfz4VCV
- OpenAI embeddings guide: https://developers.openai.com/api/docs/guides/embeddings
- OpenAI `text-embedding-3-small`: https://developers.openai.com/api/docs/models/text-embedding-3-small
- OpenAI `text-embedding-3-large`: https://developers.openai.com/api/docs/models/text-embedding-3-large
- MongoDB Vector Search: https://www.mongodb.com/docs/vector-search/
- pgvector HNSW/IVFFlat: https://github.com/pgvector/pgvector
