---
name: hephaestus-network
description: "Use when the user asks OpenClaw to staff a task from Agentlas Hub agents or teams. The active host LLM chooses from the Agent Workforce Ontology."
metadata: {"openclaw": {"emoji": "🔨", "requires": {"bins": ["python3"]}, "homepage": "https://github.com/agentlas-ai/Agentlas-OS"}}
---

# Hephaestus Agent Workforce Network

The active host LLM is the temporary orchestrator. Hub supplies content and
qualification evidence, exact immutable releases, and BYOM directives; it does
not select the final team or run a server-side LLM.

1. Create a redacted `agentlas.workforce-work-order.v1` with substantive role
   slots, skills/knowledge, MCP tools, artifacts, runtime/language/authority,
   cardinality, and handoff/review edges. Keep private context local.
2. Call Hub MCP `workforce.search_candidates`.
3. As the host LLM, author `agentlas.workforce-selection.v1` from exact content
   and eval evidence. Do not use lexical top-1, popularity, ratings, history,
   revenue, or local callability as semantic fit.
4. Call `workforce.validate_selection`, revise on rejection, then call
   `workforce.prepare_execution`. Require exact release version, package hash,
   content digest, and directive bundle; never silently substitute.
5. Run manager/planner, each worker, synthesis, and verifier as distinct model
   invocations with explicit artifact handoffs and nested Team graphs.

If this OpenClaw host cannot call the three MCP tools or create separate child
invocations, report the last truthful state instead of calling the legacy
router. Execution success requires planner parse success without fallback,
every child/handoff receipt, synthesis, and a passing verifier.
