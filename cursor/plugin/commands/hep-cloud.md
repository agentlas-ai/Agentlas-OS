Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-cloud

Raw request: `the request typed after the command`

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
