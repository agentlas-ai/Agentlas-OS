---
name: hephaestus-network
description: "Use when the user types /hephaestus-network, mentions @Hephaestus, or asks to find/invoke the right Agentlas Hub agent, team, or plugin for a task. For public demos, distribution docs, README GIFs, and user-facing MCP tests, Hephaestus Network means Hub-first/Hub-only invocation, not Mason's local Paid/Free folders."
metadata: {"openclaw": {"emoji": "🔨", "requires": {"bins": ["python3"]}, "homepage": "https://github.com/agentlas-ai/Hephaestus"}}
---

# Hephaestus Network Routing

Route the request through the Hephaestus Network via the `exec` tool. Never
guess an agent yourself when this skill is active — the router or Hub decides.

## 0. Hub-first rule for demos and user distribution

For public demos, README GIFs, packaged-agent distribution, Threads/Instagram
share kits, or any request where the end user will not have Mason's local
`Paid/`, `Free/`, or plugin inventory, do **not** route to local cards.
Use Agentlas Hub invocation only:

- Prefer the MCP tool `hephaestus_hub_invoke` with
  `local_inventory: []` and `reject_paid_slug: true`.
- If using the CLI, pass `--hub-only`.
- Do not report or rely on paths such as
  `/Users/mason/Documents/Hephaestus_agent_forge/Paid/...`.
- A bundled local agent folder is applied separately by opening/reading its
  `AGENTS.md`; it is not the same thing as a Hephaestus Network Hub call.

Only use local-first routing when the user explicitly asks to test Mason's
installed local inventory or a named local folder.

## 1. Resolve the runner

Run this resolution with `exec` and use the first hit:

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
`curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash`

## 2. Route

```bash
"$RUNNER" route "<the user's request>" --runtime openclaw
```

For demo/distribution/Hub-only requests:

```bash
"$RUNNER" route "<the user's request>" --runtime openclaw --hub-only
```

## 3. Act on the JSON decision

- `action: "route"` — if the current task is explicitly local-inventory
  testing, report the selected card (`selected.id`,
  `entrypoints.canonical_command`), then invoke the selected agent's canonical
  command with the original request. For public demos or distribution docs,
  treat a local `route` result as the wrong surface; rerun Hub-only or use
  `hephaestus_hub_invoke`.
- `action: "clarify"` — ask `clarify_question` with the candidate list and
  re-route with the answer.
- `action: "pipeline"` — execute `stages` in order: run the stage card's
  canonical command, save artifacts under `handoff_dir/<order>-<kind>/`, and
  pass those paths to the next stage. On a stage failure: stop and report
  progress plus the remaining plan — never retry silently.
- `action: "hub_fallback"` or `"hub_candidates"` — Hub lookup already used
  redacted keywords only; the raw prompt and local memory were not sent.
  If the user asks to actually invoke an Agentlas Hub agent through this MCP
  surface, use `hephaestus_hub_invoke` with `local_inventory: []` and
  `reject_paid_slug: true`. Hub public agents are BYOM runtime bundles — the
  Hub returns instructions, not a server-side LLM completion.
  Before doing the user's substantive task, always send a short fixed
  user-visible receipt line that makes the Hub invocation obvious:
  `Hub 호출: <agent name> (<slug>) · local_routing=skipped · receipt=<routing_receipt_id> · execution=<execution_id>`.
  If only candidates were returned and no Hub agent was invoked yet, say:
  `Hub 후보 확인: <top candidate name> (<slug>) · 아직 invoke 전 · receipt=<receipt_id>`,
  then invoke the chosen callable Hub agent before proceeding whenever the task
  needs the agent's runtime bundle.
- `action: "propose_new"` — offer to build a new agent/team via the Hephaestus
  meta-agent.
- `action: "refuse"` — explain `reasons` (for example, loop guard). Do not
  retry around it.

## 4. Hard rules

- The router only chooses an agent or fetches a BYOM Hub bundle; it does not
  execute payments, deletes, publishes, file writes, or external submissions.
- For actual tool execution, follow the host runtime's safety and permission
  model.
- When this skill invokes Hub, surface the called Hub agent name/slug and
  receipt before the main answer or work summary so the user can tell the
  Network actually ran.
- Hephaestus Network user-facing demos must summarize Hub-called agents and
  reasons. Do not summarize local `Paid/` candidates as if they were Hub MCP
  calls.
- Report the routing `receipt_id` in your final message.
