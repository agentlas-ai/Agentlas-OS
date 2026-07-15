---
description: Staff and run a task from the Agentlas Hub Workforce Ontology.
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

Act as the temporary top-level LLM orchestrator. Build a redacted
`agentlas.workforce-work-order.v1`, call `workforce.search_candidates`, choose
the final exact roster from content/eval evidence, validate it with
`workforce.validate_selection`, and pin it with
`workforce.prepare_execution`. Never use legacy lexical/popularity/history
routing or silent substitution. Execute planner, each selected worker,
synthesis, and verifier as distinct invocations with artifact handoffs. A
prepared bundle is not proof of execution; require child receipts, successful
structured planning with no fallback, and a passing verifier.
