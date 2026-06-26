---
name: hephaestus-network
description: "Use when the user types /hep-network, mentions @Hephaestus, or asks to find/invoke the right Agentlas Hub agent, team, or plugin for a task. For public demos, distribution docs, README GIFs, and user-facing MCP tests, Hephaestus Network means Hub-first/Hub-only invocation, not developer-local private scope folders."
---

# Hephaestus Network Routing

Route the request through the Hephaestus Network. Never guess an agent yourself
when this skill is active — the router or Hub decides.

## 0. Hub-first rule for demos and user distribution

For public demos, README GIFs, packaged-agent distribution, Threads/Instagram
share kits, or any request where the end user will not have developer-local
`private`, `restricted`, or plugin inventory, do **not** route to local cards.
Use Agentlas Hub invocation only:

- Prefer the MCP tool `hephaestus_hub_invoke` with
  `local_inventory: []` and `hub_only: true`.
- If using the CLI, pass `--hub-only`.
- Do not report or rely on machine-local private scope folder paths.
- A bundled local agent folder is applied separately by opening/reading its
  `AGENTS.md`; it is not the same thing as a Hephaestus Network Hub call.

Only use local debug routing when the user explicitly asks to test this machine's
installed local inventory or a named local folder.

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
`agentlas_authenticate` tool first, then call the `hephaestus_route` tool from
the `hephaestus-network` MCP server instead.

## 3. Agentlas sign-in

Before routing, ensure Agentlas is signed in:

```bash
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
```

This opens the user's default browser only when there is no valid local
Agentlas sign-in yet. If a saved sign-in already exists, it silently reuses
it. Do not ask the user to copy values or understand sign-in internals.
For CI/headless checks only, set `HEPHAESTUS_AUTH_AUTOPOPUP=0`
and skip this step.

## 4. Route

```bash
"$RUNNER" route "<the user's request>" --runtime "<this runtime's name>"
```

For demo/distribution/Hub-only requests:

```bash
"$RUNNER" route "<the user's request>" --runtime "<this runtime's name>" --hub-only
```

## 5. Act on the JSON decision

- `action: "route"` — if the current task is explicitly local-inventory
  testing, report the selected card (`selected.id`,
  `entrypoints.canonical_command`), then invoke the selected agent's canonical
  command with the original request. If
  `entrypoints.canonical_command` is null but `entrypoints.agent` and
  `selected.source` are present, use `selected.source/entrypoints.agent` as the
  AGENTS.md runtime entrypoint: read it, follow its routing rules, and report
  that AGENTS fallback path. For public demos or distribution docs, treat a
  local `route` result as the wrong surface; rerun Hub-only or use
  `hephaestus_hub_invoke`.
- `action: "clarify"` — ask `clarify_question` with the candidate list and
  re-route with the answer.
- `action: "pipeline"` — a multi-team plan. Execute `stages` in order: run the
  stage card's canonical command, save artifacts under
  `handoff_dir/<order>-<kind>/`, pass those paths to the next stage. On a stage
  failure: stop and report progress plus the remaining plan — never retry
  silently. If `task_force` or `execution_fabric` is present, use it as the
  Stormbreaker packet schedule; parallel groups can be dispatched across active
  Codex, Claude, GLM, DeepSeek, Gemini, or local sessions when the host has
  them. The local product runner is `hep-storm`; attach real runtime
  sessions with `--executor-command`, or use the default mode only to
  materialize auditable handoff artifacts. Terminal `hephaestus-network`
  auto-runs only when the route decision includes a runnable execution fabric;
  use `--plan-only` for route-only output.
- `action: "hub_fallback"` or `"hub_candidates"` — Hub lookup already used
  redacted keywords only; the raw prompt and local memory were not sent.
  If the user explicitly asks to avoid all local agents/cards, pass
  `hub_only: true` to the MCP tool or `--hub-only` to the CLI so local
  private/restricted cards are skipped entirely.
  If the user asks to actually invoke an Agentlas Hub agent through this MCP
  surface, use `hephaestus_hub_invoke` with `local_inventory: []` and
  `hub_only: true`. This tool still skips local routing; it calls Hub MCP (`marketplace.search_agents`,
  `agentlas.get_runtime_bundle`, `agentlas.resolve_plugins`) and writes a
  Hephaestus execution receipt. Hub public agents are BYOM runtime bundles —
  the Hub returns instructions, not a server-side LLM completion.
  Before doing the user's substantive task, always send a short fixed
  user-visible receipt line that makes the Hub invocation obvious:
  `Hub 호출: <agent name> (<slug>) · local_routing=skipped · receipt=<routing_receipt_id> · execution=<execution_id>`.
  If only candidates were returned and no Hub agent was invoked yet, do not stop
  at candidate reporting when the request is a GUI shortcut such as `startup`.
  First run `hephaestus local-gui "<request>" --detach --quiet-not-found`; this
  restores the Hub cloud package and launches the packaged GUI. It does not
  inspect local private shortcut cards unless operator debug routing is
  explicitly enabled. For non-GUI tasks, invoke the chosen
  callable Hub agent before proceeding whenever the task needs the agent's
  runtime bundle. For composite Hub-only requests,
  `task_force.stages[]` may already contain stage-level Hub candidates; treat
  that as the temporary TF shortlist, not as a request to ask the user about
  every stage.
- `action: "propose_new"` — offer to build a new agent/team via the Hephaestus
  builder (`/hep-build`).
- `action: "refuse"` — explain `reasons` (for example, loop guard). Do not
  retry around it.

Always honor `policy_decision` in Local Operator Mode. Most decisions are
`allow`, `allow_with_label`, `auto_redact`, or `candidate_only`; do not create a
human approval loop for ordinary local work. Ask only when the host runtime is
about to perform a real external export, global memory/playbook promotion, or
irreversible publish/delete/payment/submit action.

## 5. Hard rules

- The router only chooses an agent or fetches a BYOM Hub bundle; it does not
  execute payments, deletes, publishes, file writes, or external submissions.
- For actual tool execution, follow the host runtime's safety and permission
  model (Claude Code, Codex, Cursor, etc.).
- When this skill invokes Hub, surface the called Hub agent name/slug and
  receipt before the main answer or work summary so the user can tell the
  Network actually ran.
- Hephaestus Network user-facing demos must summarize Hub-called agents and
  reasons. Do not summarize local `private` candidates as if they were Hub MCP
  calls.
- Report the routing `receipt_id` in your final message.
