---
name: hephaestus-cloud
description: "Use when the user types /hep-cloud or asks to staff from THEIR OWN Agentlas cloud packages (보관함, 내 클라우드, 내 보관함, my cloud, my own agents). This exact source scope searches only the signed-in owner's Cloud inventory, never public Hub or registered Local inventory."
metadata: {"openclaw": {"emoji": "🔨", "requires": {"bins": ["python3"]}, "homepage": "https://github.com/agentlas-ai/Agentlas-OS"}}
---

# Hephaestus Cloud Routing (my own cloud / 보관함)

Route the request through the signed-in user's OWN Agentlas cloud packages only.
The active host LLM remains the staffing decision-maker; Cloud supplies a
content menu and exact BYOM releases.

## 0. Scope rule

`/hep-cloud` is owner-scoped: it queries ONLY the authenticated owner's
own cloud packages (보관함) through Core's typed `sourceScope: "cloud"`. It does **not**
search the public marketplace and does **not** search local private/plugin
cards.

- The user's own Cloud packages are restorable/owned by them. Entitlement,
  lease, and charged credits are server-authoritative; do not hard-code a price.
- For the public marketplace only, use `/hep-hub` (`sourceScope: "hub"`).
- For the combined Local + own Cloud + public Hub menu, use `/hep-network`
  (`sourceScope: "network"`).

Each unpinned Cloud discovery goes to the owner-scoped source for its current
menu; a successful client cache entry must not hide a newly published,
replaced, or removed package. Once the host validates and prepares a choice,
the exact Cloud release remains pinned for that execution.

## 1. Resolve the runner

Run this resolution in a shell and use the first hit:

```bash
RUNNER=""
for c in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  ./bin/hephaestus
do [ -x "$c" ] && RUNNER="$c" && break; done
if [ -z "$RUNNER" ]; then
  for cache in \
    "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus" \
    "$HOME/.codex/plugins/cache/agentlas-core-engine/hephaestus"; do
    newest="$(ls -d "$cache"/*/bin/hephaestus 2>/dev/null | sort -V | tail -1)"
    [ -n "$newest" ] && [ -x "$newest" ] && RUNNER="$newest" && break
  done
fi
```

If no runner exists, tell the user to run the one-touch installer:
`curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash`

If shell execution is unavailable but the local `hephaestus-network` MCP is
available, use the typed Workforce sequence in section 3. If that server cannot
advertise owner-Cloud search plus exact bundle fetch, report
`source_not_supported`; never fall back to the legacy cargo search path.

## 1.5 Core project first-contact contract

The `cloud ... --project .` call below is a trusted plugin contact. Agentlas
Core must synchronously create or repair the same private project soul memory,
code map, ontology runtime, CareerGraph, and full `.agentlas/` ignore block used
by every other host. If bootstrap is blocked, stop rather than querying Cloud
without the project architecture. The adapter never owns a second seed format.

## 2. Agentlas sign-in (required)

The owner cloud is sign-in-gated. Before routing, ensure Agentlas is signed in:

```bash
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
```

This opens the user's default browser only when there is no valid local sign-in
yet, and reuses a saved sign-in silently. For CI/headless checks only, set
`HEPHAESTUS_AUTH_AUTOPOPUP=0` and skip this step.

## 3. Staff from owner Cloud only

In an MCP-capable host, author the complete redacted WorkOrder, then call the
actual local Core tools in this order:

```text
workforce.search_candidates(sourceScope="cloud")
workforce.validate_selection(workOrder=..., selection=...)
workforce.prepare_execution(workOrder=..., selection=..., federatedSelection=..., projectDir=..., goalId=activeGoalId?)
workforce.validate_execution_receipt(receipt=..., executionPlan=..., toolInventory=...)
```

The host LLM authors the final Selection. If the deployed owner-Cloud Workforce
source contract is absent, report `source_not_supported`; do not silently query
public Hub or legacy cargo search. A shell without an active host LLM can only
report that orchestration is required.

The default search response is a projected menu. Preserve its Cloud source
receipt and `selectionSessionId`, but do not echo it as a complete
`federationResult`; Core resolves the full pinned result by session. Receipt
validation is local and read-only and cannot create execution evidence.

## 4. Act on the typed result (`scope: "cloud"`)

Preserve the Cloud source receipt, source selection session, candidate-set
digest, release id, package hash, and content digest. Validate and prepare in
local Core; never send the federated wrapper back to remote validation.

## 5. Hard rules

- Never report public marketplace agents or local private/plugin cards as if
  they were the user's own cloud packages.
- Deterministic Core validates governance and immutable pins but never chooses
  the roster. The active host LLM chooses from content evidence.
- For actual tool execution, follow the host runtime's safety and permission
  model. Report the exact source receipt plus `selectionReceiptId`,
  `preparationReceiptId`, and validated execution receipt status when present.
