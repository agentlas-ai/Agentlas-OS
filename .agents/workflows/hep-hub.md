---
description: Staff a task only from public Agentlas Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-hub

Raw request: `the request typed after the command`

Use the local Agentlas OS MCP server `hephaestus-network` and call the
Workforce tools with exact `sourceScope: "hub"`. This is public Hub only; it
must not add registered Local or owner Cloud candidates.

## First decide which of the two shapes this is

**One named agent.** The argument names a single agent — a slug, or an
unmistakable name with no task described around it (`ktx-book`,
`use ktx-book`). The user is asking to *use that agent*, not to have a team
staffed, so do not make them sit through a staffing ceremony to get there:

1. Find that exact agent with `hephaestus_search`. If nothing matches
   the name, say so and stop — never substitute a different agent for the one
   they asked for.
2. Before preparing anything, tell them in plain words:
   - what the agent does, from its own card;
   - what it will need from them. Read `prerequisites`, `envRequirements` and
     `mcpServers` off the card. If all three are empty, **say that the card
     declares nothing** rather than implying it needs nothing — plenty of
     agents want a login they never wrote down, and the user should hear that
     before they start, not when the run stops to ask;
3. Ask for whatever it needs, then prepare and run it, keeping the exact
   release pins below.

Skip the ceremony, never the pins: the prepared release must still carry source
`hub`, the exact release, package hash, content digest, runtime bundle,
permission policy, and context digest.

**A job to be done.** The argument describes work rather than naming an agent.
Staff it:

1. Author a redacted `agentlas.workforce-work-order.v1`; private project
   grounding stays on-host.
2. Call `workforce.search_candidates` with
   `{workOrder, sourceScope: "hub"}` and keep the complete response as
   `federationResult`, including the Hub source receipt and the projected
   menu's `selectionSessionId`. Do not echo the projected menu back as
   `federationResult` — Core resolves the complete federation state locally
   from that session.
3. Author the final `agentlas.workforce-selection.v1` as the active host LLM,
   then call `workforce.validate_selection` with
   `{workOrder, selection}` and keep the response as `federatedSelection`. Revise on
   rejection; do not accept a
   deterministic picker or unrelated fallback.
4. Call `workforce.prepare_execution` with
   `{workOrder, selection, federatedSelection, projectDir}`. Require every
   selected row to remain pinned to source `hub`, exact release, package hash,
   content digest, runtime bundle, permission policy, and context digest.
5. Execute distinct planner/manager, worker, synthesis, and verifier calls with
   explicit artifact handoffs. Preserve packaged Team graphs.

## Recurring Hub use

Public Hub packages are free to discover and call. Recurring work still uses
the host's model, API keys, permissions, and scheduled execution capacity.
Explain those prerequisites and obtain the user's scheduling instruction.
Do not quote or purchase a retired Hub lease. The exact release remains bound
to the goal until explicit completion or cancellation.

If the Hub source is unavailable or refuses the call, report its exact refusal;
do not silently search Local or Cloud. Core owns the Hub upstream transport;
do not expose a direct remote `agentlas` MCP alongside it. A prepared roster
is not proof of execution.

For a `partial` or `failed` result, report each source receipt's exact
`failureCode`. Never collapse several receipts into one, substitute a different
code, or relabel the outcome.
