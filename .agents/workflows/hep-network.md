---
description: Staff a task from registered Local, owner Cloud, and public Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-network

Raw request: `the request typed after the command`

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
  "${GEMINI_EXTENSION_ROOT:+$GEMINI_EXTENSION_ROOT/bin/hephaestus}" \
  "./bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi
done
[ -n "$RUNNER" ] && "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
```

1. Author a redacted `agentlas.workforce-work-order.v1` with distinct role
   slots: a specific `task`, `cardinality`, `criticality`, and — only when they
   genuinely constrain the hire — required communities/skills/knowledge,
   runtimes, and `languages`. Leave every other slot field out entirely: an
   absent list field IS the empty constraint (the wire normalizes absent to
   []). Do not fill requiredToolCapabilities, requiredAuthorities,
   forbiddenAuthorities, consumes, produces, requiredRoles, or modalities —
   tools, authorities, and modalities attach to the executing runtime, not the
   agent card, so those gates only exclude real candidates; describe ordinary
   inputs/outputs in the task text and inter-slot handoffs in `edges`. Keep private
   files, memory, secrets, direct identifiers, and raw local context on-host.
   Write every discovery-facing field (statement, role descriptions, required
   skills/knowledge, artifacts) in English, faithfully translating a
   non-English request rather than passing its original wording through: the
   candidate corpus is English and cross-lingual matching silently buries the
   correct agent (measured: an identical query ranked its target 1st in English
   and 144th in Korean). Keep an untranslatable proper term alongside a short
   English gloss, e.g. `종합소득세 (Korean comprehensive income tax)`. The
   `languages` slot is the delivery requirement, not the search language — set
   it to the language the work product must be produced in (e.g. `ko`) even
   though the order itself is written in English.
2. Call `workforce.search_candidates` on `hephaestus-network` with
   `{workOrder, sourceScope: "network"}`. Preserve every source receipt and
   `selectionSessionId`; the default projected menu is not a complete
   `federationResult` and must not be echoed as one. An
   unavailable source is explicit; it is not permission to pretend that source
   participated.
3. As the active host LLM, author `agentlas.workforce-selection.v1` from the
   returned content and qualification evidence. Call
   `workforce.validate_selection` with
   `{workOrder, selection}` and keep its accepted response as `federatedSelection`.
   Revise on rejection. Deterministic code may
   enforce governance but must not choose, rerank, or silently substitute the
   roster.
4. Call `workforce.prepare_execution` with
   `{workOrder, selection, federatedSelection, projectDir, goalId?}`. `projectDir` is
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
6. Before every bound invocation, advertise the live host sessions and call
   `model.resolve_allocation` with that inventory plus the host-owned stage:
   `planner`/`manager-plan`, `worker`, `manager-synthesis`/`synthesis`, or
   `verifier`. Use the receipt's exact provider, model, and effort for that
   invocation. Model pins and ceilings come only from the MCP server's operator
   policy, never from the task or tool arguments. A missing worker policy
   inherits orchestrator; orchestrator never falls through to worker.
7. Run only the bound workers useful for this turn. For a selected team,
   preserve its authoritative manager/worker graph. Run planner/manager,
   workers, synthesis, and verifier as distinct invocations with explicit
   artifact handoffs. Allocation receipts have `usage: null` before execution,
   so record actual usage on the later invocation/run receipt instead of
   inventing zero.
8. Report `executed` only when the execution receipt proves every selected
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

## Rules carried from the other runtime copies

These lines existed in one runtime's hand-maintained copy and not in the
longest one. They are kept verbatim rather than dropped — a rule that only
one runtime enforced was still a rule someone wrote on purpose.

- # Hephaestus Workforce Network Raw request:
- `the request typed after the command` Act as the active top-level workforce orchestrator.
- Use MCP server `hephaestus-network`, the local Agentlas OS Core and only host-visible Workforce MCP.
- Network means registered Local + signed-in owner Cloud + public Hub.
- First read `workforce.goal_context(projectDir)` and reuse an active binding for the same ongoing work before considering recruitment.
- Resolve the runner only for authentication; staffing remains in the Workforce MCP tools:
- Author a redacted `agentlas.workforce-work-order.v1` with substantive role slots.
- Fill a slot with task/cardinality/criticality plus only the communities/skills/knowledge, runtimes, and languages that genuinely constrain the hire; omit every other list field (absent = empty — the wire normalizes) and never fill requiredToolCapabilities, requiredAuthorities, forbiddenAuthorities, consumes, produces, requiredRoles, or modalities:
- tools, authorities, and modalities attach to the executing runtime, not the agent card, so those gates only exclude real candidates — put ordinary inputs/outputs in the task text and handoffs in edges.
- Write every discovery-facing field in English, faithfully translating a non-English request (the candidate corpus is English and cross-lingual matching buries the correct agent — measured 1st vs 144th for one query); keep an untranslatable term with a short English gloss.
- `languages` is the delivery language, not the search language — keep it as the required output language even though the order is authored in English.
- Call `workforce.search_candidates` with `{workOrder, sourceScope:
- "network"}` and preserve source receipts plus `selectionSessionId`.
- The default response is a projected menu, not a complete `federationResult`; do not echo it as one.
- From content and qualification evidence, author `agentlas.workforce-selection.v1` yourself.
- Deterministic code may enforce governance but may not pick, rerank, or silently substitute.
- `projectDir` is mandatory; pass the incumbent `goalId` when continuing.
- Otherwise Core derives it from the WorkOrder id and automatically binds the successful plan before execution.
- Every later turn reads `workforce.goal_context`, reuses the incumbent roster plus local skills when sufficient, and recruits only a real additive gap using the same `goalId`.
- Record the turn posture through `workforce.record_goal_turn`.
- Spawn only the useful bound planner/manager, worker, synthesis, and verifier invocations with explicit artifact handoffs; preserve authoritative Team graphs.
- Keep the roster bound across turns, sessions, runtime restarts, and context compaction until explicit whole-goal completion/cancellation via `workforce.complete_goal(explicitCompletion=true)`.
- Lease expiry affects only the next Hub charge; it never dismisses the roster.
- Memory/Experience accrue on actual invocations.
- Report `executed` only from a receipt proving every child invocation, handoff, synthesis, and a passing independent verifier.
- Do not call legacy `hephaestus_route`, bypass Core with direct remote search, or use popularity/history/price/availability as semantic fit.
- Exact duplicate releases collapse Local > Cloud > Hub only with verified identical lineage.
- Act as the active top-level workforce orchestrator.
- Use the local Agentlas OS MCP server `hephaestus-network`, the only host-visible Workforce MCP.
- first read `workforce.goal_context(projectDir)` and reuse any active binding for the same ongoing work.
- Author a redacted WorkOrder — Fill a slot with task/cardinality/criticality plus only the communities/skills/knowledge, runtimes, and languages that genuinely constrain the hire; omit every other list field (absent = empty — the wire normalizes) and never fill requiredToolCapabilities, requiredAuthorities, forbiddenAuthorities, consumes, produces, requiredRoles, or modalities:
- Write its discovery-facing fields in English, faithfully translating a non-English request (the candidate corpus is English; cross-lingual matching buries the right agent, measured 1st vs 144th for one query), while keeping `languages` as the required delivery language — and call `workforce.search_candidates` with exact `sourceScope:
- "network"` (registered Local + owner Cloud + public Hub).
- Retain the projected menu's `selectionSessionId` and every source receipt; do not echo the projected menu as `federationResult`.
- Core resolves the complete federation state locally from that session.
- Author the final Selection yourself from content/qualification evidence, call `workforce.validate_selection` with `{workOrder, selection}`, keep `federatedSelection`, then call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir, goalId?}`.
- Otherwise Core derives one from the WorkOrder id and automatically binds the successful plan.
- Preserve source receipts, provenance, immutable source/release/package/content/runtime/ permission/context pins, and authoritative Team graphs.
- Execute distinct planner/manager, worker, synthesis, and verifier invocations with handoffs.
- On every later turn read `workforce.goal_context`, reuse the incumbent roster plus local skills when sufficient, recruit only a real additive gap using the same `goalId`, and record `reuse|local-only|recruit|standby|blocked` with `workforce.record_goal_turn`.
- Keep the roster across sessions, restarts, compaction, and lease expiry; release it only with `workforce.complete_goal(explicitCompletion=true)` after explicit whole-goal completion/cancellation.
- A 24-hour lease controls only the next Hub charge; standby is not a continuously running model.
- For `partial` or `failed`, report each source receipt's exact `failureCode`; never collapse, substitute, or relabel it.
- Never call legacy `hephaestus_route`, bypass Core, accept deterministic staffing, silently substitute, or claim execution without complete receipts.
- Use local MCP server `hephaestus-network`, the only host-visible Workforce MCP.
- Author the final Selection yourself, call `workforce.validate_selection` with `{workOrder, selection}`, keep `federatedSelection`, then call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir, goalId?}`.
- Preserve source receipts/provenance and all immutable pins.
- Execute planner/manager, workers, synthesis, and verifier as distinct invocations with handoffs and preserved Team graphs.
- Never use legacy `hephaestus_route`, direct remote search, deterministic staffing, silent substitution, or preparation as execution proof.
- # /hep-network Use the exact request after `/hep-network`.
- Act as the active top-level workforce orchestrator and use local MCP server `hephaestus-network`, the only host-visible Workforce MCP.
- Author a redacted `agentlas.workforce-work-order.v1`; keep private project grounding on-host.
- Author `agentlas.workforce-selection.v1` yourself from content and qualification evidence; call `workforce.validate_selection` with `{workOrder, selection}` and keep `federatedSelection`.
- `projectDir` is mandatory; pass an incumbent `goalId` when continuing.
- Execute only useful bound planner/manager, worker, synthesis, and verifier invocations with explicit artifact handoffs and preserved Team graphs.
- Keep the roster across turns, sessions, restarts, compaction, and Hub lease expiry.
- Release it only through `workforce.complete_goal(explicitCompletion=true)` after explicit whole-goal completion/cancellation.
- A 24-hour lease controls only the next server charge; standby is durable availability, not a continuously running model.
- Report `executed` only from a receipt proving every child invocation and a passing verifier.
- Otherwise report the last truthful state and source outages.
