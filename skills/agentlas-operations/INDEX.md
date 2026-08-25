# Agentlas 도구 색인 (자동 생성 — 손으로 편집 금지)

생성원: `agentlas_cloud/mcp_stdio.py` TOOLS (27개). 재생성: `python3 scripts/generate-ops-skill-index.py`.

| 도구 | 요지 |
|---|---|
| `agentlas_tool_search` | Find the TOOL for a concrete action, not the plugin for a topic. |
| `hephaestus_route` | Legacy compatibility/debug card router. |
| `model.resolve_allocation` | Resolve one host-owned invocation stage to an orchestrator or worker model using the operator's provider-neutral role policy. |
| `hephaestus_cloud_search` | Legacy compatibility/debug owner-cargo router. |
| `hephaestus_search` | Power-user search: return top Agentlas Cloud (owner packages) and public Hub candidates side by side without invoking any agent. |
| `hephaestus_call` | Prepare explicitly named Agentlas Hub/cloud agents. |
| `hephaestus_network_status` | Report Hephaestus Network state: card counts, benchmark state, auto-routing gate. |
| `agentlas_authenticate` | Open the user's browser for a one-time Agentlas Google/sign-in flow, store the local signed-in state under ~/.agentlas/auth, and reuse it fo |
| `agentlas_auth_status` | Report whether this machine already has a reusable Agentlas sign-in for Hephaestus Hub calls. |
| `hephaestus_hub_invoke` | Prepare an exact Agentlas Hub public agent through the Hephaestus Network surface. |
| `workforce.preflight_work_order` | Compile a compact semantic staffing draft into an exact, privacy-checked agentlas.workforce-work-order.v1 and pin it locally behind a one-ho |
| `workforce.search_candidates` | Search the Agent Workforce Ontology with a locally preflighted WorkOrder reference. |
| `workforce.expand_candidates` | Return the full candidate cards for a shortlist, after a shortlist=true search. |
| `workforce.validate_selection` | Validate a team selected by the calling host LLM against an exact candidate set. |
| `workforce.prepare_execution` | Fetch BYOM runtime bundles only for an already accepted exact roster. |
| `workforce.validate_execution_receipt` | Read-only validation of one host-produced execution receipt against the exact prepared plan and a private local tool-inventory snapshot. |
| `workforce.bind_goal` | Bind an already prepared exact Workforce roster to one durable host goal. |
| `workforce.goal_context` | Read the current account- and project-scoped durable Workforce roster. |
| `workforce.goal_runtime` | Load the exact locally cached prepared plans for an active account/project goal. |
| `workforce.record_goal_turn` | Record the host LLM's content-free per-turn choice: reuse the bound roster, use local skills only, recruit a real gap, remain on standby, or |
| `workforce.complete_goal` | Release a durable Workforce binding only after an explicit host/user goal completion or cancellation. |
| `context.refresh` | Explicitly build one complete content-addressed project Context Map snapshot. |
| `context.locate` | Locate exact project symbols, definitions, and reverse references in the local dependency map. |
| `context.refs` | Return every bounded local backlink for one exact symbol. |
| `context.slice` | Build the minimal dependency-selected Context Slice for a resolved task. |
| `context.impact` | Trace changed files or symbols through reverse references and module dependencies. |
| `context.verify` | Completion gate: fail closed while any impacted file is neither changed, reviewed, nor explicitly waived. |
