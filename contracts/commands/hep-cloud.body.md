Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-cloud

Raw request: `{{ARGS}}`

Act as the temporary top-level workforce orchestrator. Use the local Agentlas
OS MCP server `hephaestus-network` and call the Workforce tools with exact
`sourceScope: "cloud"`. This command may search only packages owned by the
signed-in Agentlas account. It must not add Local or public Hub candidates.

Before the first Cloud source call, reuse the installed Agentlas sign-in.
Resolve the runner in this order and use it only for authentication; the host
LLM still performs staffing through the Workforce MCP tools:

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

1. Author a redacted `agentlas.workforce-work-order.v1`; private project
   grounding stays on-host.
2. Call `workforce.search_candidates` with
   `{workOrder, sourceScope: "cloud"}`. Preserve the Cloud source receipt and
   `selectionSessionId`; the projected menu is not a complete
   `federationResult` and must not be echoed as one.
3. Author the final `agentlas.workforce-selection.v1` as the active host LLM,
   then call `workforce.validate_selection` with
   `{workOrder, selection}` and keep the response as `federatedSelection`. Revise on
   rejection; do not accept a
   deterministic picker or unrelated fallback.
4. Call `workforce.prepare_execution` with
   `{workOrder, selection, federatedSelection, projectDir}`. Require every
   selected row to remain pinned to source `cloud`, exact release, package
   hash, content digest, runtime bundle, permission policy, and context digest.
5. Execute distinct planner/manager, worker, synthesis, and verifier calls with
   explicit artifact handoffs. Preserve packaged Team graphs.

Report the exact finite Core refusal—such as `source_unauthorized`,
`source_forbidden`, `source_rate_limited`, `insufficient_credits`, `owner_only`,
`no_cloud_package`, `agent_not_found`, `source_not_supported`, or
`source_unavailable`—with the source receipt. Do not silently search Local or Hub,
call a legacy route, or expose a direct remote `agentlas` MCP alongside Core.
A prepared roster is not proof of execution.

## Rules carried from the other runtime copies

These lines existed in one runtime's hand-maintained copy and not in the
longest one. They are kept verbatim rather than dropped — a rule that only
one runtime enforced was still a rule someone wrote on purpose.

- # Hephaestus Cloud Workforce Raw request:
- `{{ARGS}}` Use MCP server `hephaestus-network` and exact `sourceScope:
- Author a redacted `agentlas.workforce-work-order.v1`, call `workforce.search_candidates` with `{workOrder, sourceScope:
- "cloud"}` and keep the source receipt plus `selectionSessionId`; do not echo the projected menu as a complete `federationResult`.
- Author the final `agentlas.workforce-selection.v1` yourself, call `workforce.validate_selection` with `{workOrder, selection}`, keep its response as `federatedSelection`, then call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir}`.
- Require every row to retain source `cloud` plus its exact release/package/content/runtime/permission/context identity.
- Run planner/manager, selected workers, synthesis, and verifier as distinct invocations with artifact handoffs and preserve Team graphs.
- Report the exact finite Core refusal (`source_unauthorized`, `source_forbidden`, `source_rate_limited`, `insufficient_credits`, `owner_only`, `no_cloud_package`, `agent_not_found`, `source_not_supported`, or `source_unavailable`) with the source receipt.
- Never search Local or public Hub, invoke legacy routing, accept a deterministic picker, or treat a prepared bundle as execution proof.
- Use local MCP server `hephaestus-network` with exact `sourceScope:
- Author a redacted WorkOrder; call `workforce.search_candidates` with `{workOrder, sourceScope:
- Retain the projected menu's `selectionSessionId` and every source receipt; do not echo the projected menu as `federationResult`.
- Core resolves the complete federation state locally from that session.
- Author the host-LLM Selection; call `workforce.validate_selection` with `{workOrder, selection}`; keep `federatedSelection`; call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir}`; and execute distinct planner/manager, workers, synthesis, and verifier while retaining source `cloud` and all immutable pins.
- For `partial` or `failed`, report each source receipt's exact `failureCode`; never collapse, substitute, or relabel it.
- Never search Local or public Hub, use legacy routing, accept deterministic staffing, or claim execution from a prepared roster.
- # /hep-cloud Use local MCP server `hephaestus-network` and exact `sourceScope:
- "cloud"` for the request after `/hep-cloud`.
- Author the final host-LLM Selection; call `workforce.validate_selection` with `{workOrder, selection}` and keep `federatedSelection`; then call `workforce.prepare_execution` with `{workOrder, selection, federatedSelection, projectDir}`.
- Retain source `cloud` and every immutable pin; execute planner/manager, workers, synthesis, and verifier as distinct invocations.
- Never search Local or public Hub, call legacy routing, accept a deterministic picker, or claim execution from preparation alone.
