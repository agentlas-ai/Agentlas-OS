---
description: Staff a task only from public Agentlas Hub agents.
argument-hint: '<request>'
allowed-tools: Bash, Read, Glob, Grep
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-hub

Raw request: `$ARGUMENTS`

Act as the temporary top-level workforce orchestrator. Use the local Agentlas
OS MCP server `hephaestus-network` and call the Workforce tools with exact
`sourceScope: "hub"`. This is public Hub only; it must not add registered Local
or owner Cloud candidates.

1. Author a redacted `agentlas.workforce-work-order.v1`; private project
   grounding stays on-host.
2. Call `workforce.search_candidates` with
   `{workOrder, sourceScope: "hub"}` and keep the complete response as
   `federationResult`, including the Hub source receipt.
3. Author the final `agentlas.workforce-selection.v1` as the active host LLM,
   then call `workforce.validate_selection` with
   `{workOrder, selection}` and keep the response as `federatedSelection`. Revise on
   rejection; do not accept a
   deterministic picker or unrelated fallback.
4. Call `workforce.prepare_execution` with
   `{workOrder, selection, federatedSelection, projectDir}`. Require every
   selected row to remain pinned to source `hub`, exact release, package hash,
   content digest, runtime bundle, permission policy, and context digest.
5. Execute distinct planner/manager, worker, synthesis, and verifier calls with
   explicit artifact handoffs. Preserve packaged Team graphs.

If the Hub source is unavailable or refuses the call, report its exact refusal;
do not silently search Local or Cloud. Core owns the Hub upstream transport;
do not expose a direct remote `agentlas` MCP alongside it. A prepared roster
is not proof of execution.

## Rules carried from the other runtime copies

These lines existed in one runtime's hand-maintained copy and not in the
longest one. They are kept verbatim rather than dropped — a rule that only
one runtime enforced was still a rule someone wrote on purpose.

- `$ARGUMENTS` Use MCP server `hephaestus-network` and exact `sourceScope:
- Author a redacted `agentlas.workforce-work-order.v1`, call `workforce.search_candidates` with `{workOrder, sourceScope:
- Author the final `agentlas.workforce-selection.v1` yourself, call `workforce.validate_selection` with `{workOrder, selection}`, keep its response as `federatedSelection`, then call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir}`.
- Require every row to retain source `hub` plus its exact release/package/content/runtime/permission/context identity.
- Run planner/manager, selected workers, synthesis, and verifier as distinct invocations with artifact handoffs and preserve Team graphs.
- If Hub refuses or is unavailable, report the exact source receipt.
- Never search Local or Cloud, bypass Core with direct remote search, accept a deterministic picker, or treat a prepared bundle as execution proof.
- Use local MCP server `hephaestus-network` with exact `sourceScope:
- Author a redacted WorkOrder; call `workforce.search_candidates` with `{workOrder, sourceScope:
- Retain the projected menu's `selectionSessionId` and every source receipt; do not echo the projected menu as `federationResult`.
- Core resolves the complete federation state locally from that session.
- Author the host-LLM Selection; call `workforce.validate_selection` with `{workOrder, selection}`; keep `federatedSelection`; call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir}`; and execute distinct planner/manager, workers, synthesis, and verifier while retaining source `hub` and all immutable pins.
- For `partial` or `failed`, report each source receipt's exact `failureCode`; never collapse, substitute, or relabel it.
- Never search Local or Cloud, bypass Core, accept deterministic staffing, or claim execution from a prepared roster.
- # /hep-hub Use local MCP server `hephaestus-network` and exact `sourceScope:
- Author the final host-LLM Selection; call `workforce.validate_selection` with `{workOrder, selection}` and keep `federatedSelection`; then call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir}`.
- Retain source `hub` and every immutable pin; execute planner/manager, workers, synthesis, and verifier as distinct invocations.
