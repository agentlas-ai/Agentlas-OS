---
description: Staff a task from registered Local, owner Cloud, and public Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-network

Use the exact request after `/hep-network`. Act as the active top-level
workforce orchestrator and use local MCP server `hephaestus-network`, the only
host-visible Workforce MCP. Core owns its Cloud/Hub upstream calls. Network means
registered Local + signed-in owner Cloud + public Hub.

The user does not need to say `goal`. First read
`workforce.goal_context(projectDir)` and reuse an active binding for the same
ongoing work before considering recruitment.

1. Author a redacted `agentlas.workforce-work-order.v1`; keep private project
   grounding on-host.
2. Call `workforce.search_candidates` with
   `{workOrder, sourceScope: "network"}` and keep the response as
   `federationResult`, retaining all source receipts and provenance.
3. Author `agentlas.workforce-selection.v1` yourself from content and
   qualification evidence; call `workforce.validate_selection` with
   `{workOrder, candidateSet: federationResult.candidateSet, selection,
   federationResult}` and keep `federatedSelection`. Revise on rejection.
4. Call `workforce.prepare_execution` with
   `{workOrder, candidateSet: federationResult.candidateSet, selection,
   federationResult, federatedSelection, projectDir, goalId?}` and require exact source, release,
   package/content, runtime, permission, and context pins.
   `projectDir` is mandatory; pass an incumbent `goalId` when continuing.
   Otherwise Core derives one from the WorkOrder id and automatically binds the
   successful plan before execution.
5. On every later turn read `workforce.goal_context`, reuse the incumbent
   roster plus local skills when sufficient, recruit only a real additive gap
   using the same `goalId`, and record the turn posture with
   `workforce.record_goal_turn`.
6. Execute only useful bound planner/manager, worker, synthesis, and verifier
   invocations with explicit artifact handoffs and preserved Team graphs.

Keep the roster across turns, sessions, restarts, compaction, and Hub lease
expiry. Release it only through
`workforce.complete_goal(explicitCompletion=true)` after explicit whole-goal
completion/cancellation. A 24-hour lease controls only the next server charge;
standby is durable availability, not a continuously running model.

Report `executed` only from a receipt proving every child invocation and a
passing verifier. Otherwise report the last truthful state and source outages.
Do not call legacy `hephaestus_route`, bypass Core with direct remote search,
accept a deterministic picker, or use popularity/history/price/availability as
semantic fit.
