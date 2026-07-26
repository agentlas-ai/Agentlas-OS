---
description: Staff a task from registered Local, owner Cloud, and public Hub agents.
argument-hint: '<request>'
allowed-tools: Bash, Read, Glob, Grep
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-network

Raw request: `$ARGUMENTS`

You are the active top-level workforce orchestrator. Use the local Agentlas
OS MCP server named `hephaestus-network`, the only host-visible Workforce MCP.
Core reaches Cloud and Hub through its internal upstream client. Network means all registered
Local agents, the signed-in owner's Cloud agents, and public Hub agents.

The user does not need to say `goal`. First call `workforce.goal_context` for
the current project. If it returns an active binding for this ongoing work,
reuse that exact roster and `goalId` before considering recruitment.

Before the first Cloud or Hub source call, reuse the installed Agentlas
sign-in. Resolve the runner in this order and use it only for authentication;
the host LLM still performs staffing through the Workforce MCP tools:

```bash
RUNNER=""
for candidate in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/hephaestus}" \
  "${PLUGIN_ROOT:+$PLUGIN_ROOT/bin/hephaestus}" \
  "./bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi
done
[ -n "$RUNNER" ] && "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
```

1. Author a redacted `agentlas.workforce-work-order.v1` with distinct role
   slots, required skills/knowledge/MCP capabilities, artifacts, runtimes,
   languages, authorities, cardinality, and collaboration edges. Keep private
   files, memory, secrets, direct identifiers, and raw local context on-host.
2. Call `workforce.search_candidates` on `hephaestus-network` with
   `{workOrder, sourceScope: "network"}` and keep the complete response as
   `federationResult`. Preserve every source receipt and provenance row. An
   unavailable source is explicit; it is not permission to pretend that source
   participated.
3. As the active host LLM, author `agentlas.workforce-selection.v1` from the
   returned content and qualification evidence. Call
   `workforce.validate_selection` with
   `{workOrder, candidateSet: federationResult.candidateSet, selection,
   federationResult}` and keep its accepted response as `federatedSelection`.
   Revise on rejection. Deterministic code may
   enforce governance but must not choose, rerank, or silently substitute the
   roster.
4. Call `workforce.prepare_execution` with
   `{workOrder, candidateSet: federationResult.candidateSet, selection,
   federationResult, federatedSelection, projectDir, goalId?}`. `projectDir` is
   mandatory. Pass the incumbent `goalId` when continuing; otherwise Core
   derives one from the WorkOrder id. Core must automatically bind a successful
   preparation before execution, so continuity cannot be skipped because no
   explicit goal mode was requested.
   Require each worker to retain its exact source plus release, package hash,
   content digest, runtime-bundle digest, permission policy, and execution
   context pins. Recompute digests and fail closed on drift.
5. On later turns call `workforce.goal_context` first: reuse the incumbent
   roster plus local skills when sufficient; recruit only a real gap and pass
   the same `goalId` to preparation so new releases append. Record
   `reuse|local-only|recruit|standby|blocked` with
   `workforce.record_goal_turn`.
6. Run only the bound workers useful for this turn. For a selected team,
   preserve its authoritative manager/worker graph. Run planner/manager,
   workers, synthesis, and verifier as distinct invocations with explicit
   artifact handoffs.
7. Report `executed` only when the execution receipt proves every selected
   invocation, handoff, synthesis, and an independent passing verifier.
   Otherwise report the last truthful state: `selected`, `prepared`,
   `source_unavailable`, `blocked`, or `failed`.

The roster remains bound across turns, sessions, restarts, and context
compaction until the whole goal is explicitly completed/cancelled through
`workforce.complete_goal(explicitCompletion=true)`. A 24-hour Hub lease only
controls whether the next real borrow is charged; it never ends the goal
binding. Standby is durable availability, not a continuously running model.
Memory Curator/Experience continue on actual worker invocations only.

Do not call legacy `hephaestus_route`, register or use direct remote search as a substitute
for Core federation, or use popularity/history/price/local availability as
semantic fit. Exact duplicate releases may collapse Local > Cloud > Hub only
when Core returns verified identical lineage; a name or slug match is not
enough. Name the actual workers in the result.
