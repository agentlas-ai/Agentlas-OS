# /hephaestus-cloud

Search ONLY the signed-in user's own Agentlas cloud packages (보관함) and route
the request to one of them. Owner-scoped leg of the three-scope model:
`/hephaestus-cloud` = my own cloud (restorable/owned, call-priced at a flat 1
credit); `/hephaestus-network` = the public marketplace; plain language /
`@Hephaestus` = local + my cloud + Hub together.

## Engine resolution

Use the first executable found:

1. `~/.agentlas/runtime/current/bin/hephaestus` (runtime-neutral install)
2. `./bin/hephaestus` (workspace copy)
3. `~/.claude/plugins/cache/agentlas-core-engine/hephaestus/*/bin/hephaestus` (newest, sort -V)
4. `${CODEX_HOME:-~/.codex}/plugins/cache/agentlas-core-engine/hephaestus/*/bin/hephaestus` (newest, sort -V)
5. `./claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus`

## Steps

1. Run `"$RUNNER" auth ensure --timeout 180` first. The owner cloud requires
   sign-in; this opens the user's default browser only on first use and reuses
   saved sign-ins silently.
2. Run `"$RUNNER" cloud "<request>" --project .` and parse the JSON.
   (`cloud` is shorthand for `route "<request>" --scope cloud`; owner-scoped Hub
   query, implies `--hub-only`.)
3. Act on `action` (`scope: "cloud"`):
   - `hub_candidates` — my OWN cloud packages. Report them and, on the user's
     pick, invoke that package with the original request (1 credit/call).
   - `clarify` — ask the `clarify_question` with candidates, then re-route.
   - `propose_new` — no matching package in my cloud; offer /hephaestus-network
     (public marketplace) or /hephaestus (build a new agent).
   - `refuse` — explain `reasons`; do not work around the loop guard.
4. Hard rules: never searches the public marketplace or local cards — only the
   authenticated owner's own cloud packages. Actual tool execution follows the
   current host runtime's safety and permission model. Include the routing
   `receipt_id` in the final answer.
