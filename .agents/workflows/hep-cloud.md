---
description: Staff a task only from the signed-in owner's Agent Cloud agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-cloud

Use local MCP server `hephaestus-network` and exact `sourceScope: "cloud"` for
the request after `/hep-cloud`. Author a redacted WorkOrder, call
`workforce.search_candidates` with `{workOrder, sourceScope: "cloud"}` and keep
`federationResult`; author the final host-LLM Selection; call
`workforce.validate_selection` with
`{workOrder, selection}` and keep `federatedSelection`; then call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir}`. Retain
source `cloud` and every immutable pin; execute planner/manager, workers,
synthesis, and verifier as distinct invocations.

If owner authentication or Cloud is unavailable, report `source_unavailable`
with the Core receipt. Never search Local or public Hub, call legacy routing,
accept a deterministic picker, or claim execution from preparation alone.
