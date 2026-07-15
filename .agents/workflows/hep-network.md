---
description: Staff and run a task from the Agentlas Hub Workforce Ontology.
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-network

Use the exact user request after `/hep-network`. The active host LLM is the
temporary orchestrator; Hub supplies the workforce menu.

1. Create a redacted `agentlas.workforce-work-order.v1` with substantive role
   slots and explicit skills, MCP tools, artifacts, runtime/language/authority,
   cardinality, and handoff/review edges. Keep private project context local.
2. Call `workforce.search_candidates`. Do not use the legacy lexical router or
   popularity/history signals.
3. Read content/eval evidence and, as the active host LLM, create
   `agentlas.workforce-selection.v1` with exact release assignments, reasons,
   alternatives, and collaboration graph.
4. Call `workforce.validate_selection`; revise on rejection and never silently
   substitute.
5. Call `workforce.prepare_execution`; require exact release/package/content
   hashes and directive bundles for all selected workers.
6. Execute distinct manager/planner, worker, synthesis, and verifier model
   invocations with explicit artifact handoffs and preserve nested Team graphs.

Do not report execution from a route, bundle, or process exit. A passing
receipt needs planner parse success with no fallback, every child invocation,
synthesis, and verifier verdict. Otherwise state the last truthful lifecycle
state.
