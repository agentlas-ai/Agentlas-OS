---
description: Staff a task only from public Agentlas Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

Use local MCP server `hephaestus-network` with exact `sourceScope: "hub"`.
Author a redacted WorkOrder; call `workforce.search_candidates` with
`{workOrder, sourceScope: "hub"}`. Retain the projected menu's
`selectionSessionId` and every source receipt; do not echo the projected menu
as `federationResult`. Core resolves the complete federation state locally from
that session. Author the host-LLM Selection; call `workforce.validate_selection` with
`{workOrder, selection}`; keep `federatedSelection`; call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir}`; and execute distinct planner/manager, workers,
synthesis, and verifier while retaining source `hub` and all immutable pins.
For `partial` or `failed`, report each source receipt's exact `failureCode`;
never collapse, substitute, or relabel it. Never search
Local or Cloud, bypass Core, accept deterministic staffing, or claim execution
from a prepared roster.
