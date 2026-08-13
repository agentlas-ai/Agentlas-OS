---
name: hephaestus-cloud
description: "Use when the user types /hep-cloud or asks to staff from THEIR OWN Agentlas cloud packages (보관함, 내 클라우드, 내 보관함, my cloud, my own agents). This exact source scope searches only the signed-in owner's Cloud inventory, never public Hub or registered Local inventory."
metadata: {"openclaw": {"emoji": "🔨", "requires": {"bins": ["python3"]}, "homepage": "https://github.com/agentlas-ai/Agentlas-OS"}}
---

# Hephaestus Cloud Routing (my own cloud / 보관함)

Staff the request from the signed-in user's OWN Agentlas Cloud packages only.
The active host LLM makes the final selection from Core's content menu; Core
validates and pins it but never decides the roster.

## 0. Scope rule

`/hep-cloud` is owner-scoped: it queries ONLY the authenticated owner's Cloud
inventory. It does **not** search public Hub or registered Local inventory.
Entitlement and credits remain server-authoritative; never hard-code a price.
Use `sourceScope="network"` for the combined Local + Cloud + Hub menu.

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

If shell execution is unavailable but MCP is available, use the typed Workforce
tools from the `hephaestus-network` MCP server. Authentication may be established
with `agentlas_authenticate`; do not substitute legacy cloud search for staffing.

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

Use local Core's typed sequence:

```text
workforce.search_candidates(sourceScope="cloud")
workforce.validate_selection(workOrder=..., selection=...)
workforce.prepare_execution(workOrder=..., selection=..., federatedSelection=..., projectDir=...)
workforce.validate_execution_receipt(receipt=..., executionPlan=..., toolInventory=...)
```

Preserve the Cloud source receipt and `selectionSessionId`; do not echo the
projected search menu as a complete federation result. Core resolves the full
pinned session. Legacy `hephaestus_cloud_search` is an explicitly gated debug
surface, not an owner-Cloud staffing fallback.

## 4. Act on typed receipts

The host LLM selects from content evidence. Preserve exact source session,
release, package/content hashes, selection receipt, and preparation receipt.
Report finite refusal codes such as `source_unauthorized`,
`insufficient_credits`, `owner_only`, `no_cloud_package`, or `agent_not_found`
exactly; never collapse them to `source_unavailable`.

## 5. Hard rules

- Never report public marketplace agents or local private/plugin cards as if
  they were the user's own cloud packages.
- Deterministic Core validates and pins; it never chooses the roster.
- For actual tool execution, follow the host runtime's safety and permission
  model. Receipt validation is local and read-only and does not execute workers.
