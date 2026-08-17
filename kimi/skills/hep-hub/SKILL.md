---
name: hep-hub
description: Staff a task only from public Agentlas Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Hub Workforce

Raw request: `$ARGUMENTS`

Use MCP server `hephaestus-network` and exact `sourceScope: "hub"`. Author a
redacted `agentlas.workforce-work-order.v1`, call
`workforce.search_candidates` with `{workOrder, sourceScope: "hub"}` and keep
the response as `federationResult`. Author the final
`agentlas.workforce-selection.v1` yourself, call
`workforce.validate_selection` with
`{workOrder, selection}`, keep its response as `federatedSelection`, then call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir}`. Require every row to retain source `hub` plus
its exact release/package/content/runtime/permission/context identity.

Run planner/manager, selected workers, synthesis, and verifier as distinct
invocations with artifact handoffs and preserve Team graphs. If Hub refuses or
is unavailable, report the exact source receipt. Never search Local or Cloud,
bypass Core with direct remote search, accept a deterministic picker, or treat
a prepared bundle as execution proof.
