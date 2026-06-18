# Agent OS Build Status (Phases 0–6)

Build record for the Agent OS redesign (`docs/agent-os-redesign.md`). All phases
have a delivered, verified core. Gate: `bash scripts/ao-gate.sh` = `ao lint`
(valid) + `ao diff` (idempotent, clean) + `pytest` (**123 passed**).

## Delivered per phase

| Phase | Core delivered | Module(s) | CLI | Verified |
| --- | --- | --- | --- | --- |
| **0** Foundation | `ao diff`/`ao lint` hard local gate (non-zero exit on invalid/drift); `owns_scope → MemoryScope` materialized from `memory-map`; `produces`/`consumes` authored → Artifact graph; **pipeline planner** over produces/consumes | `migrate.py`, `query.plan_pipeline_ao`, `scripts/ao-gate.sh` | `ao pipeline <artifact>` | 5 MemoryScope + 6 owns_scope edges; 5 artifacts; `release-bundle` → 3-stage chain |
| **1** Kernel | 2 super-ontology seeds promoted `export_only → runtime_enforced`, linked to live grammar axioms; kernel loader + enforcement verifier | `kernel.py` | `ao kernel` | `verify_enforcement` = 2/2 fully enforced (state + axiom present) |
| **2** Ontology Pack + OKF | installable Pack manifest (hash, kernel status); **OKF v0.1 round-trip** (Markdown bundle, frontmatter+links), redaction-safe | `agentos.build_pack`, `okf.py` | `ao pack`, `ao okf export/import` | 21-node round-trip lossless; private fields never leak |
| **3** Memory (frontier) | **bi-temporal** store: valid-time vs ingestion-time; **supersede-not-delete**; deprecate; valid-time queries | `memory.py` | — (library) | supersede keeps old; `active_at` window correct |
| **4** Network | queryable **A2A registry** with identity blocks; `can_invoke` gate = **alignment AND verified identity** | `a2a.build_a2a_registry`, `a2a.can_invoke_external` | `ao a2a registry` | 5 agents; gate rejects unless both true |
| **5** Cross-runtime | **Knowledge Catalog descriptor** over OKF bundle; declared supported runtimes; value-free export | `catalog.py` | `ao catalog` | 22-file bundle; claude-code/codex/gemini-cli listed |
| **6** Agent OS surface | **OS kernel-module map** with live status (6/6 live); **factory inheritance contract** | `agentos.os_surface`, `agentos.factory_contract` | `ao os` | all_live=True; inherited contract 9 items |

## Full CLI surface

```
ao lint | migrate | graph | query | plan | pipeline | diff | reachable
ao a2a import | export | registry
ao okf export | import
ao kernel | pack | os | catalog
```

## Collaboration note

Codex was invoked for implementation but the local `codex exec` build runs hung
on stdin (workspace-write), so the phase cores were implemented directly and
Codex was used for read-only adversarial cross-verification (the mode that ran
reliably). The robustness protocol gained a `parallel_session_fabric` phase for
multi-session scheduling during this work.

## Honest remaining depth (not claimed as done)

- Desktop GUI absorption: the old ontology dashboard is now positioned as a
  Knowledge/Memory panel, but the native Desktop Agent OS console remains a
  product follow-up.
- Real execution memory promotion: router receipts now emit candidate-first
  Memory/Playbook metadata, but durable/global promotion still belongs to
  Memory Curator / PM Soul evidence review.
- Karpathy-style ingest loop is documented as the pack-build *method* (Phase 2);
  the executable ingest is a follow-up.
- Bi-temporal store is in-memory; persistence into the ontology runtime + a
  LoCoMo-style recall/latency benchmark is the Phase 3 frontier follow-up.
- A2A identity is structural (`verified=false`); signed-card verification is the
  decision-3 prerequisite before external mesh exposure.
