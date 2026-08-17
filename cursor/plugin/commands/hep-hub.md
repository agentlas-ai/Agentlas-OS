Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-hub

Raw request: `the request typed after the command`

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
