---
description: Staff a task only from public Agentlas Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-hub

Use local MCP server `hephaestus-network` and exact `sourceScope: "hub"` for
the request after `/hep-hub`. Author a redacted WorkOrder, call
`workforce.search_candidates` with `{workOrder, sourceScope: "hub"}` and keep
`federationResult`; author the final host-LLM Selection; call
`workforce.validate_selection` with
`{workOrder, selection}` and keep `federatedSelection`; then call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir}`. Retain
source `hub` and every immutable pin; execute planner/manager, workers,
synthesis, and verifier as distinct invocations.

If Hub refuses or is unavailable, report its exact source receipt. Never
search Local or Cloud, bypass Core with direct remote search, accept a
deterministic picker, or claim execution from preparation alone.
