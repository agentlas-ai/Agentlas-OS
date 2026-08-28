---
description: Staff a task only from Agentlas agents registered on this machine.
argument-hint: '<request>'
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-local

Raw request: `$ARGUMENTS`

Act as the temporary top-level workforce orchestrator. Use the local Agentlas
OS MCP server `hephaestus-network` and call the Workforce tools with exact
`sourceScope: "local"`. Before every unpinned discovery, Core refreshes the
current safe snapshot for each active registered Local source, creating a new
release when the source folder changed. This command searches only that
registered Local inventory; it must not add owner Cloud or public Hub
candidates. A prepared or goal-bound selection remains pinned to its exact
release. `network reindex` rebuilds the card cache but is not the release
refresh mechanism, and a new source still requires explicit registration.

1. Author a redacted `agentlas.workforce-work-order.v1`; private project
   grounding stays on-host.
2. Call `workforce.search_candidates` with
   `{workOrder, sourceScope: "local"}` and keep the complete response as
   `federationResult`, including its local registry receipt.
3. Author the final `agentlas.workforce-selection.v1` as the active host LLM,
   then call `workforce.validate_selection` with
   `{workOrder, selection}` and keep the response as `federatedSelection`. Revise on
   rejection; do not accept a
   deterministic picker or unrelated fallback.
4. Call `workforce.prepare_execution` with
   `{workOrder, selection, federatedSelection, projectDir}`. Require every
   selected row to remain pinned to source `local`, exact package/content
   identity, runtime bundle, permission policy, and context digest.
5. Execute distinct planner/manager, worker, synthesis, and verifier calls with
   explicit artifact handoffs. Preserve packaged Team graphs.

If the local Core MCP or registered inventory is unavailable, report
`source_unavailable`; do not silently search Cloud or Hub. A prepared roster is
not proof of execution.

## Rules carried from the other runtime copies

These lines existed in one runtime's hand-maintained copy and not in the
longest one. They are kept verbatim rather than dropped — a rule that only
one runtime enforced was still a rule someone wrote on purpose.

- # Hephaestus Local Workforce Raw request:
- `$ARGUMENTS` Use MCP server `hephaestus-network` and exact `sourceScope:
- Author a redacted `agentlas.workforce-work-order.v1`, call `workforce.search_candidates` with `{workOrder, sourceScope:
- Author the final `agentlas.workforce-selection.v1` yourself, call `workforce.validate_selection` with `{workOrder, selection}`, keep its response as `federatedSelection`, then call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir}`.
- Require every row to retain source `local` plus its exact package/content/runtime/permission/context identity.
- Run planner/manager, selected workers, synthesis, and verifier as distinct invocations with artifact handoffs and preserve Team graphs.
- If Core or the registered Local inventory is unavailable, report `source_unavailable`.
- Never search Cloud or Hub, accept a deterministic picker, or treat a prepared bundle as execution proof.
- Use local MCP server `hephaestus-network` with exact `sourceScope:
- Author a redacted WorkOrder; call `workforce.search_candidates` with `{workOrder, sourceScope:
- Retain the projected menu's `selectionSessionId` and every source receipt; do not echo the projected menu as `federationResult`.
- Core resolves the complete federation state locally from that session.
- Author the host-LLM Selection; call `workforce.validate_selection` with `{workOrder, selection}`; keep `federatedSelection`; call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir}`; and execute distinct planner/manager, workers, synthesis, and verifier while retaining source `local` and all immutable pins.
- For `partial` or `failed`, report each source receipt's exact `failureCode`; never collapse, substitute, or relabel it.
- Never search Cloud or Hub, accept deterministic staffing, or claim execution from a prepared roster.
- # /hep-local Use local MCP server `hephaestus-network` and exact `sourceScope:
- "local"` for the request after `/hep-local`.
- Author the final host-LLM Selection; call `workforce.validate_selection` with `{workOrder, selection}` and keep `federatedSelection`; then call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir}`.
- Retain source `local` and every immutable pin; execute planner/manager, workers, synthesis, and verifier as distinct invocations.
- Never search Cloud or Hub, accept a deterministic picker, or claim execution from preparation alone.
