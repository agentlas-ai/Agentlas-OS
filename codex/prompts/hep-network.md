---
description: Staff a task from registered Local, owner Cloud, and public Hub agents.
argument-hint: <natural-language request>
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Workforce Network

Raw request: `$ARGUMENTS`

Act as the active top-level workforce orchestrator. Use MCP server
`hephaestus-network`, the local Agentlas OS Core and only host-visible
Workforce MCP. Core reaches Cloud and Hub through its internal upstream client.
Network means registered
Local + signed-in owner Cloud + public Hub.

The user does not need to say `goal`. First read
`workforce.goal_context(projectDir)` and reuse an active binding for the same
ongoing work before considering recruitment.

Before the first Cloud or Hub source call, reuse the installed Agentlas
sign-in. Resolve the runner only for authentication; staffing remains in the
Workforce MCP tools:

```bash
RUNNER=""
for candidate in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  "./bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi
done
[ -n "$RUNNER" ] && "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
```

1. Author a redacted `agentlas.workforce-work-order.v1` with substantive role
   slots, skills/knowledge/MCP capabilities, artifacts, runtimes, languages,
   authorities, cardinality, and collaboration edges. Private grounding stays
   local. Write every discovery-facing field in English, faithfully translating
   a non-English request (the candidate corpus is English and cross-lingual
   matching buries the correct agent — measured 1st vs 144th for one query);
   keep an untranslatable term with a short English gloss. `languages` is the
   delivery language, not the search language — keep it as the required output
   language even though the order is authored in English.
2. Call `workforce.search_candidates` with
   `{workOrder, sourceScope: "network"}` and keep the response as
   `federationResult`. Preserve source receipts and provenance; unavailable
   sources remain explicit.
3. From content and qualification evidence, author
   `agentlas.workforce-selection.v1` yourself. Call
   `workforce.validate_selection` with
   `{workOrder, selection}` and keep its response as `federatedSelection`. Revise on
   rejection. Deterministic code may
   enforce governance but may not pick, rerank, or silently substitute.
4. Call `workforce.prepare_execution` with
   `{workOrder, selection, federatedSelection, projectDir, goalId?}` and require
   exact source, release, package/content, runtime-bundle, permission, and
   context pins for every selected row. `projectDir` is mandatory; pass the
   incumbent `goalId` when continuing. Otherwise Core derives it from the
   WorkOrder id and automatically binds the successful plan before execution.
5. Every later turn reads `workforce.goal_context`, reuses the incumbent roster
   plus local skills when sufficient, and recruits only a real additive gap
   using the same `goalId`. Record the turn posture through
   `workforce.record_goal_turn`.
6. Before every bound invocation, advertise the live host sessions and call
   `model.resolve_allocation` with that inventory plus the host-owned stage:
   `planner`/`manager-plan`, `worker`, `manager-synthesis`/`synthesis`, or
   `verifier`. Use the receipt's exact provider, model, and effort for that
   invocation. Model pins and ceilings come only from the MCP server's operator
   policy, never from the task or tool arguments. A missing worker policy
   inherits orchestrator; orchestrator never falls through to worker.
7. Spawn only the useful bound planner/manager, worker, synthesis, and verifier
   invocations with explicit artifact handoffs; preserve authoritative Team
   graphs. Allocation receipts have `usage: null` before execution, so record
   actual usage on the later invocation/run receipt instead of inventing zero.

Keep the roster bound across turns, sessions, runtime restarts, and context
compaction until explicit whole-goal completion/cancellation via
`workforce.complete_goal(explicitCompletion=true)`. Lease expiry affects only
the next Hub charge; it never dismisses the roster. Standby is durable
availability, not a continuously running model. Memory/Experience accrue on
actual invocations.

Report `executed` only from a receipt proving every child invocation, handoff,
synthesis, and a passing independent verifier. Otherwise report the last
truthful state. Do not call legacy `hephaestus_route`, bypass Core with direct
remote search, or use popularity/history/price/availability as semantic fit.
Exact duplicate releases collapse Local > Cloud > Hub only with verified
identical lineage.
