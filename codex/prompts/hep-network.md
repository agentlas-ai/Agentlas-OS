---
description: Staff and run a task from the Agentlas Hub Workforce Ontology.
argument-hint: <natural-language request>
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Agent Workforce Network

Raw request: `$ARGUMENTS`

Act as the temporary top-level orchestrator. Hub supplies a workforce menu; the
active Codex model makes the final staffing decision. Do not call the legacy
lexical router.

Before the first Hub MCP call, reuse the installed sign-in if the runner is
available: `"$HOME/.agentlas/runtime/current/bin/hephaestus" auth ensure --timeout 180`.
This is authentication only; do not call the legacy `route` command.

1. Build a redacted `agentlas.workforce-work-order.v1` with real role slots and
   explicit skills, MCP tools, artifacts, runtimes, languages, authorities,
   cardinality, and handoff/review edges. Private project grounding stays local.
2. Call Agentlas Hub MCP `workforce.search_candidates` with `{workOrder}`.
   Candidate retrieval is content-only. Popularity, ratings, history, revenue,
   and local availability must not decide semantic fit.
3. Read the candidate contracts and author an
   `agentlas.workforce-selection.v1` yourself with
   `decisionAuthor.kind="host_llm"`, the actual model id, exact release
   assignments, alternatives, reasons, and collaboration graph.
4. Call `workforce.validate_selection`. If rejected or a role is uncovered,
   revise/expand; never use an unrelated or deterministic fallback.
5. Call `workforce.prepare_execution`. Require the accepted exact roster to be
   pinned by release version, package hash, and content digest with a BYOM
   directive bundle for every worker. No silent substitution.
6. Spawn distinct manager/planner, worker, synthesis, and verifier invocations,
   preserve artifact handoffs, and honor an authoritative nested Team graph.

A candidate list or prepared bundle is not execution. Report completion only
when the execution receipt proves structured planner output with no fallback,
each child invocation and handoff, synthesis, and a passing verifier. Otherwise
state the last truthful state: `selected`, `prepared`, `blocked`, or `failed`.
