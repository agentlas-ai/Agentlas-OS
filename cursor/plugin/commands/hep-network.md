---
description: Staff and run a task from the Agentlas Hub Workforce Ontology.
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

For the user's request, act as the temporary top-level LLM orchestrator. Create
a redacted `agentlas.workforce-work-order.v1`, then call Hub MCP
`workforce.search_candidates`, make the final content/evidence-based selection
yourself, call `workforce.validate_selection`, and finally
`workforce.prepare_execution`. Do not use the legacy lexical router,
popularity/history ranking, or silent substitution. Pin exact release version,
package hash, and content digest. Run planner, distinct selected workers,
synthesis, and verifier with artifact handoffs. Claim execution only with
joined child invocation receipts, planner parse success without fallback, and
a passing verifier.
