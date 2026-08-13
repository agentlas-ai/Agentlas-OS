---
description: Staff a task only from public Agentlas Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-hub

Use local MCP server `hephaestus-network` and exact `sourceScope: "hub"` for
the request after `/hep-hub`. Author a redacted WorkOrder, call
`workforce.search_candidates` with `{workOrder, sourceScope: "hub"}`. Retain
the projected menu's `selectionSessionId` and every source receipt; do not echo
the projected menu as `federationResult`. Core resolves the complete federation
state locally from that session. Author the final host-LLM Selection; call
`workforce.validate_selection` with
`{workOrder, selection}` and keep `federatedSelection`; then call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir}`. Retain
source `hub` and every immutable pin; execute planner/manager, workers,
synthesis, and verifier as distinct invocations.

For `partial` or `failed`, report each source receipt's exact `failureCode`;
never collapse, substitute, or relabel it. Never
search Local or Cloud, bypass Core with direct remote search, accept a
deterministic picker, or claim execution from preparation alone.
