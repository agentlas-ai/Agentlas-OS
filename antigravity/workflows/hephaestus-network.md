# /hephaestus-network

Route a natural-language request through the Hephaestus Network local-first
router (routing cards → local agents/teams/plugins → Hub fallback). Also
triggered by `@Hephaestus <request>`.

## Engine resolution

Use the first executable found:

1. `~/.agentlas/runtime/current/bin/hephaestus` (runtime-neutral install)
2. `./bin/hephaestus` (workspace copy)
3. `~/.claude/plugins/cache/agentlas-core-engine/hephaestus/*/bin/hephaestus` (newest, sort -V)
4. `${CODEX_HOME:-~/.codex}/plugins/cache/agentlas-core-engine/hephaestus/*/bin/hephaestus` (newest, sort -V)
5. `./claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus`

## Steps

1. Run `"$RUNNER" auth ensure --timeout 180` first. It opens the user's default
   browser only on first use; existing Agentlas saved sign-ins are reused
   silently.
2. Run `"$RUNNER" route "<request>" --runtime antigravity` and parse the JSON.
3. Act on `action`:
   - `route` — report the selected card and canonical command; if
     present, invoke it with the original request.
   - `clarify` — ask the `clarify_question` with candidates, then re-route.
   - `pipeline` — a multi-team plan (PRD → build → QA). Execute `stages` in
     order, save artifacts under
     `handoff_dir/<order>-<kind>/`, pass paths to the next stage; on failure
     stop and report — never retry silently.
   - `hub_fallback` / `hub_candidates` — Hub lookup used redacted keywords only;
     the raw prompt and local memory were not sent.
   - `propose_new` — offer to build a new agent/team via `/hephaestus-build`.
   - `refuse` — explain `reasons`; do not work around the loop guard or
     equivalent technical guard.
4. Hard rules: the router only chooses an agent or fetches a BYOM Hub bundle.
   Actual tool execution follows the current host runtime's safety and
   permission model. Include the routing `receipt_id` in the final answer.
