---
description: Staff a task only from Agentlas agents registered on this machine.
argument-hint: <natural-language request>
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Local Workforce

Raw request: `$ARGUMENTS`

Use MCP server `hephaestus-network` and exact `sourceScope: "local"`. Author a
redacted `agentlas.workforce-work-order.v1`, call
`workforce.search_candidates` with `{workOrder, sourceScope: "local"}` and keep
the response as `federationResult`. Author the final
`agentlas.workforce-selection.v1` yourself, call
`workforce.validate_selection` with
`{workOrder, selection}`, keep its response as `federatedSelection`, then call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir}`. Require every row to retain source `local` plus
its exact package/content/runtime/permission/context identity.

Run planner/manager, selected workers, synthesis, and verifier as distinct
invocations with artifact handoffs and preserve Team graphs. If Core or the
registered Local inventory is unavailable, report `source_unavailable`. Never
search Cloud or Hub, accept a deterministic picker, or treat a prepared bundle
as execution proof.
