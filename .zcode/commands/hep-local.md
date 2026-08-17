---
description: Staff a task only from Agentlas agents registered on this machine.
argument-hint: '<request>'
allowed-tools: Bash, Read, Glob, Grep
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-local

Raw request: `$ARGUMENTS`

Act as the temporary top-level workforce orchestrator. Use the local Agentlas
OS MCP server `hephaestus-network` and call the Workforce tools with exact
`sourceScope: "local"`. This command searches only the reconciled registered
Local inventory; it must not add owner Cloud or public Hub candidates.

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
