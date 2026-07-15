---
description: Staff and run a task from the Agentlas Hub Workforce Ontology.
argument-hint: '<request>'
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-network

Raw request: `$ARGUMENTS`

You are the temporary top-level workforce orchestrator. Hub provides the menu;
you make the final staffing decision. Do not run the legacy lexical route.

Before the first Hub MCP call, reuse the installed Agentlas sign-in. Resolve
the first existing runner in this order and call `auth ensure`; do not call its
legacy route command:

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

1. Convert the task into a redacted `agentlas.workforce-work-order.v1` with
   distinct role slots, required roles/skills/knowledge/MCP tools,
   input-output artifacts, runtimes, languages, authorities, cardinality, and
   collaboration edges. Keep private files, memory, secrets, and raw local
   context on this host.
2. Call Hub MCP `workforce.search_candidates` with `{workOrder}`. Inspect exact
   semantic/eval evidence and release/package/content hashes. Never use
   popularity, ratings, invocations, or local availability as semantic fit.
3. As the active host LLM, author `agentlas.workforce-selection.v1` with
   `decisionAuthor.kind="host_llm"`, the real model id, exact assignments,
   handoff graph, alternatives, and reasons. Call
   `workforce.validate_selection` with `{workOrder,candidateSet,selection}`.
   Re-plan if rejected; do not accept a deterministic substitute.
4. Call `workforce.prepare_execution` with the accepted validation receipt.
   Require `agentlas.workforce-execution-plan.v3`, status `prepared`, and an
   exact pinned `executionRoster`; every row must declare
   `agentlas.workforce-runtime-bundle-digest.v2`, which the host recomputes
   before execution. Fail closed on release/hash/directive drift or missing
   directives. Never silently substitute.
5. Run manager/planner, each selected worker, synthesis, and verifier as
   distinct model invocations using the prepared directive bundles and
   explicit artifact handoffs. Honor nested Team execution graphs.

Do not call the run complete unless the joined execution receipt includes
planner parse success with no fallback, each worker's invocation and handoff,
synthesis, and a passing verifier. If this host cannot create distinct child
invocations, report `prepared, not executed`. Name the actual workers and keep
`selected`, `prepared`, and `executed` states separate.
