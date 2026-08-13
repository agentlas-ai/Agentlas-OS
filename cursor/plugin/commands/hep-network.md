---
description: Staff a task from registered Local, owner Cloud, and public Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

Act as the active top-level workforce orchestrator. Use the local Agentlas
OS MCP server `hephaestus-network`, the only host-visible Workforce MCP. Core
owns its Cloud/Hub upstream calls.
The user does not need to say `goal`: first read
`workforce.goal_context(projectDir)` and reuse any active binding for the same
ongoing work.
Author a redacted WorkOrder — Fill a slot with task/cardinality/criticality plus only the communities/skills/knowledge, runtimes, and languages that genuinely constrain the hire; omit every other list field (absent = empty — the wire normalizes) and never fill requiredToolCapabilities, requiredAuthorities, forbiddenAuthorities, consumes, produces, requiredRoles, or modalities: tools, authorities, and modalities attach to the executing runtime, not the agent card, so those gates only exclude real candidates — put ordinary inputs/outputs in the task text and handoffs in edges. Write its discovery-facing fields in English,
faithfully translating a non-English request (the candidate corpus is English;
cross-lingual matching buries the right agent, measured 1st vs 144th for one
query), while keeping `languages` as the required delivery language — and call
`workforce.search_candidates` with exact
`sourceScope: "network"` (registered Local + owner Cloud + public Hub). Retain
the projected menu's `selectionSessionId` and every source receipt; do not echo
the projected menu as `federationResult`. Core resolves the complete federation
state locally from that session. Author the final Selection yourself from
content/qualification evidence, call `workforce.validate_selection` with
`{workOrder, selection}`, keep `federatedSelection`, then call
`workforce.prepare_execution` with
`{workOrder, selection, federatedSelection, projectDir, goalId?}`. `projectDir` is
mandatory; pass the incumbent `goalId` when continuing. Otherwise Core derives
one from the WorkOrder id and automatically binds the successful plan. Preserve
source receipts, provenance, immutable source/release/package/content/runtime/
permission/context pins, and authoritative Team graphs. Execute distinct
planner/manager, worker, synthesis, and verifier invocations with handoffs.
On every later turn read `workforce.goal_context`, reuse
the incumbent roster plus local skills when sufficient, recruit only a real
additive gap using the same `goalId`, and record
`reuse|local-only|recruit|standby|blocked` with
`workforce.record_goal_turn`. Keep the roster across sessions, restarts,
compaction, and lease expiry; release it only with
`workforce.complete_goal(explicitCompletion=true)` after explicit whole-goal
completion/cancellation. A 24-hour lease controls only the next Hub charge;
standby is not a continuously running model.
For `partial` or `failed`, report each source receipt's exact `failureCode`;
never collapse, substitute, or relabel it. Never call legacy `hephaestus_route`, bypass Core, accept deterministic
staffing, silently substitute, or claim execution without complete receipts.
