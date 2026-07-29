---
description: Staff a task from registered Local, owner Cloud, and public Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

Act as the active top-level workforce orchestrator. Use local MCP server
`hephaestus-network`, the only host-visible Workforce MCP. Core owns its
Cloud/Hub upstream calls. The user does not need to say `goal`: first read
`workforce.goal_context(projectDir)` and reuse any active binding for the same
ongoing work. Author a redacted
WorkOrder — write its discovery-facing fields in English, faithfully translating
a non-English request (the candidate corpus is English; cross-lingual matching
buries the right agent, measured 1st vs 144th for one query), while keeping
`languages` as the required delivery language — and call
`workforce.search_candidates` with exact
`sourceScope: "network"` (registered Local + owner Cloud + public Hub), keeping
the response as `federationResult`. Author the final Selection yourself, call
`workforce.validate_selection` with
`{workOrder, selection}`, keep `federatedSelection`, then call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir, goalId?}`. `projectDir` is
mandatory; pass the incumbent `goalId` when continuing. Otherwise Core derives
one from the WorkOrder id and automatically binds the successful plan. Preserve
source receipts/provenance and all
immutable pins. Execute planner/manager, workers, synthesis, and verifier as
distinct invocations with handoffs and preserved Team graphs.
On every later turn read `workforce.goal_context`, reuse
the incumbent roster plus local skills when sufficient, recruit only a real
additive gap using the same `goalId`, and record the posture with
`workforce.record_goal_turn`. Keep
the roster across sessions, restarts, compaction, and lease expiry; release it
only with `workforce.complete_goal(explicitCompletion=true)` after explicit
whole-goal completion/cancellation. A 24-hour lease controls only the next Hub
charge; standby is not a continuously running model.
Never use legacy
`hephaestus_route`, direct remote search, deterministic staffing, silent
substitution, or preparation as execution proof.
