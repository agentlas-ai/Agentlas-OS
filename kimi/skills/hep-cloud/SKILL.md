---
name: hep-cloud
description: Staff a task only from the signed-in owner's Agent Cloud agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Cloud Workforce

Raw request: `$ARGUMENTS`

Use MCP server `hephaestus-network` and exact `sourceScope: "cloud"`. Author a
redacted `agentlas.workforce-work-order.v1`, call
`workforce.search_candidates` with `{workOrder, sourceScope: "cloud"}` and keep
the source receipt plus `selectionSessionId`; do not echo the projected menu as
a complete `federationResult`. Author the final
`agentlas.workforce-selection.v1` yourself, call
`workforce.validate_selection` with
`{workOrder, selection}`, keep its response as `federatedSelection`, then call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir}`. Require every row to retain source `cloud` plus
its exact release/package/content/runtime/permission/context identity.

Run planner/manager, selected workers, synthesis, and verifier as distinct
invocations with artifact handoffs and preserve Team graphs. Report the exact
finite Core refusal (`source_unauthorized`, `source_forbidden`,
`source_rate_limited`, `insufficient_credits`, `owner_only`, `no_cloud_package`,
`agent_not_found`, `source_not_supported`, or `source_unavailable`) with the
source receipt. Never
search Local or public Hub, invoke legacy routing, accept a deterministic
picker, or treat a prepared bundle as execution proof.
