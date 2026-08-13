---
name: hephaestus-network
description: "Use when the user asks OpenClaw to staff a durable goal from registered Local, owner Cloud, and public Hub agents or teams. The active host LLM chooses the exact roster, which remains goal-bound until explicit completion."
metadata: {"openclaw": {"emoji": "🔨", "requires": {"bins": ["python3"]}, "homepage": "https://github.com/agentlas-ai/Agentlas-OS"}}
---

# Hephaestus Agent Workforce Network

The active host LLM is the per-turn orchestrator. Local Core federates registered
Local, owner Cloud, and public Hub content and
qualification evidence, exact immutable releases, and BYOM directives; it does
not select the final team or run a server-side LLM.

1. Create a redacted `agentlas.workforce-work-order.v1` with substantive role
   slots, skills/knowledge, MCP tools, artifacts, runtime/language/authority,
   cardinality, and handoff/review edges. Keep private context local.
2. Call local Core `workforce.search_candidates` with `sourceScope="network"`.
   Keep source receipts and `selectionSessionId`; do not echo the projected menu
   as a complete federation result.
3. As the host LLM, author `agentlas.workforce-selection.v1` from exact content
   and eval evidence. Do not use lexical top-1, popularity, ratings, history,
   revenue, or local callability as semantic fit.
4. Call `workforce.validate_selection` with WorkOrder and Selection only, revise
   on rejection, then call `workforce.prepare_execution` with the accepted
   Selection, `federatedSelection`, and mandatory `projectDir`. Require exact release version, package hash,
   content digest, and directive bundle; never silently substitute.
5. Bind the prepared plan to the stable current goal/task id with
   `workforce.bind_goal`. On every later turn read `workforce.goal_context`,
   reuse the incumbent roster plus local skills when sufficient, recruit only
   a real additive gap, and record the posture with
   `workforce.record_goal_turn`.
6. Before each bound planner/manager, worker, synthesis, or verifier call,
   advertise the host's real sessions and call `model.resolve_allocation` with
   the host-owned stage. Use the exact provider/model/effort receipt. Pins and
   ceilings come only from `AGENTLAS_MODEL_ALLOCATION_POLICY_JSON`; missing
   worker policy inherits orchestrator. `usage: null` before invocation is not
   worker-execution proof.
7. Run only useful bound manager/planner, workers, synthesis, and verifier as
   distinct model invocations with explicit artifact handoffs and nested Team
   graphs. Validate the resulting evidence with the bounded local-only
   `workforce.validate_execution_receipt`; validation neither runs workers nor
   creates a receipt.

Keep the roster across turns, sessions, restarts, compaction, and lease expiry.
Release it only with `workforce.complete_goal(explicitCompletion=true)` after
explicit whole-goal completion/cancellation. A 24-hour lease controls only the
next Hub charge; standby is durable availability, not a continuously running
model. Memory/Experience accrue on actual invocations.

If this OpenClaw host cannot call the Workforce MCP tools or create separate child
invocations, report the last truthful state instead of calling the legacy
router. Execution success requires planner parse success without fallback,
every child/handoff receipt, synthesis, and a passing verifier.
