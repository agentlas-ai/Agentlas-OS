---
description: Staff a task only from Agentlas agents registered on this machine.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

Use local MCP server `hephaestus-network` with exact `sourceScope: "local"`.
Author a redacted WorkOrder; call `workforce.search_candidates` with
`{workOrder, sourceScope: "local"}`. Retain the projected menu's
`selectionSessionId` and every source receipt; do not echo the projected menu
as `federationResult`. Core resolves the complete federation state locally from
that session. Author the host-LLM Selection; call `workforce.validate_selection` with
`{workOrder, selection}`; keep `federatedSelection`; call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir}`; execute distinct planner/manager, workers,
synthesis, and verifier while retaining source `local` and every immutable
pin. For `partial` or `failed`, report each source receipt's exact `failureCode`;
never collapse, substitute, or relabel it. Never search Cloud or Hub, accept deterministic staffing,
or claim execution from preparation.
