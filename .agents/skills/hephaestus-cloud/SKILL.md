---
name: hephaestus-cloud
description: "Use when the user types /hep-cloud or asks to find/route to one of THEIR OWN Agentlas cloud packages (보관함, 내 클라우드, 내 보관함, my cloud, my own agents). This is the owner-scoped leg of the three-scope model — it searches ONLY the signed-in user's own cloud packages, not the public marketplace (use hep-network for that) and not local cards. The user's own cloud packages are restorable/owned by them and call-priced at a flat 1 credit."
---

# Hephaestus Cloud Routing (my own cloud / 보관함)

Route the request through the signed-in user's OWN Agentlas cloud packages only.
Never guess an agent yourself when this skill is active — the router/Hub decides.

## 0. Scope rule

`/hep-cloud` is owner-scoped: it queries ONLY the authenticated owner's
own cloud packages (보관함) via the Hub owner filter (`cargo.*`). It does **not**
search the public marketplace and does **not** search local private/plugin
cards.

- The user's own cloud packages are restorable/owned by them, call-priced at a
  flat **1 credit** per call.
- For the public marketplace (others' published, per-call-priced agents), use
  the `hephaestus-network` skill or `/hep-network` / `--hub-only` instead.
- For the combined search (local + own cloud + Hub, each priced by origin), use
  plain-language routing (`hephaestus route`).

## 1. App-host auto-update preflight

When this skill is running inside an app host with a Bash/shell tool (Claude
Code, Codex, Cursor, OpenCode, Gemini, DeepSeek, GLM, Hermes, OpenClaw, Pi, or
Agentlas surfaces), try to repair/update Hephaestus before resolving the
runner. Do this inside the host app; do not ask the user to open a separate
terminal. The preflight is fail-silent: if `curl`, network access, or file
permissions are unavailable, continue with the installed runner.

```bash
if [ "${HEPHAESTUS_APP_AUTO_UPDATE:-1}" != "0" ]; then
  CURRENT_RUNNER="$HOME/.agentlas/runtime/current/bin/hephaestus"
  NEEDS_HEP_UPDATE=1
  if [ -x "$CURRENT_RUNNER" ]; then
    UPDATE_CHECK="$("$CURRENT_RUNNER" update --check 2>/dev/null || true)"
    printf '%s' "$UPDATE_CHECK" | grep -q '"status": "current"' && NEEDS_HEP_UPDATE=0
  fi
  if [ "$NEEDS_HEP_UPDATE" = "1" ] && command -v curl >/dev/null 2>&1; then
    curl -fsSL "${HEPHAESTUS_INSTALL_URL:-https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh}" \
      | HEPHAESTUS_FORCE=1 bash >/tmp/hephaestus-app-auto-update.log 2>&1 || true
  fi
fi
```

If shell execution is unavailable but an Agentlas/Hephaestus MCP tool is
available, prefer the MCP route. If neither shell nor MCP is available, report
that this host cannot mutate the local install from inside chat.

## 2. Resolve the runner

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

If no runner exists after the preflight, report that the app host could not
install or find Hephaestus and include `/tmp/hephaestus-app-auto-update.log`
when available.

If shell execution is unavailable in this harness but MCP is, call the
`agentlas_authenticate` tool first, then call the `hephaestus_cloud_search` tool
from the `hephaestus-network` MCP server instead.

## 3. Agentlas sign-in (required)

The owner cloud is sign-in-gated. Before routing, ensure Agentlas is signed in:

```bash
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
```

This opens the user's default browser only when there is no valid local sign-in
yet, and reuses a saved sign-in silently. For CI/headless checks only, set
`HEPHAESTUS_AUTH_AUTOPOPUP=0` and skip this step.

## 4. Route (owner cloud only)

```bash
"$RUNNER" cloud "<the user's request>" --project .
```

`hephaestus cloud` is shorthand for `hephaestus route "<request>" --scope cloud`
(owner-scoped Hub query; implies `--hub-only`). Via MCP, call
`hephaestus_cloud_search` instead.

## 5. Act on the JSON decision (`scope: "cloud"`)

- `action: "hub_candidates"` — these are the user's OWN cloud packages
  (`hub.results[].slug`, `name`). Report them, and on the user's pick invoke that
  package with the original request (call-priced at 1 credit).
- `action: "clarify"` — ask `clarify_question` with the candidate list and
  re-route with the answer (still cloud-scoped).
- `action: "propose_new"` — no matching package in the user's cloud. Offer to
  search the public marketplace (`/hep-network` / `--hub-only`) or to build
  a new agent via `/hep-build`.
- `action: "refuse"` — explain `reasons` (for example, loop guard). Do not retry.

## 6. Hard rules

- Never report public marketplace agents or local private/plugin cards as if
  they were the user's own cloud packages.
- The router only chooses a package or fetches a BYOM bundle; it does not
  execute payments, deletes, publishes, file writes, or external submissions.
- For actual tool execution, follow the host runtime's safety and permission
  model. Report the routing `receipt_id` in your final message.
