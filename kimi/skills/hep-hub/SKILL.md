---
name: hep-hub
description: Staff a task only from public Agentlas Hub agents.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-hub

Raw request: `$ARGUMENTS`

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
   - what it costs: the per-call price, and the lease price when it has one.
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

## What it costs to keep something running

A Hub borrow is charged **every time it runs**. Paying once does not make the
next call free — the 24-hour auto-lease was retired on 2026-08-18. The only
things that ride at 0 credits are an agent this workspace owns and an
explicitly purchased **장기대여 / long-term lease** of 1-30 days.

That is invisible for a single task and brutal for anything that wakes on a
schedule: a five-minute watcher runs 288 times a day, so an agent priced at 3
credits a call costs 864 credits a day to keep alive. Read the real figures for
the agent in hand rather than reusing that one.

So when the work keeps running — a watcher, a poller, a daily report, anything
the user describes with "계속", "매일", "~할 때마다", "every N minutes":

1. **Before preparing anything**, call `hephaestus.quote_agent_lease` for the
   agent. It answers in one shot: the per-day price, the total for the days
   being considered, this workspace's current balance, and — when the balance
   falls short — how short and where to top up.
2. Put all of it in **one message** to the user, in their language:

   ```text
   계속 감시하려면 장기대여가 필요합니다.
     호출당        <perCallCredits> 크레딧  (5분마다면 하루 288번 = <288 x perCallCredits> 크레딧)
     장기대여      하루 <perDayCredits> 크레딧
     현재 크레딧   <balance.remainingCredits>
   며칠 대여할까요?
   ```

   Every number there comes from the quote. Do not carry an example figure over
   from this page — prices differ per agent, and a wrong number quoted
   confidently is worse than no number.

   **며칠인지 물어라.** 일수를 대신 고르지 마라.
3. Only after they answer, call `hephaestus.purchase_agent_lease`. A confirmed
   purchase is refused unless it carries **all** of these, so send them
   together: `confirm: true`, the `days` they chose, the `confirmationToken`,
   the `expectedPerDayCredits` and `expectedTotalCredits` exactly as the quote
   returned them, and a stable `idempotencyKey` you reuse on any retry. Never
   buy a lease the user did not agree to.
4. If the quote says `insufficient_credits`, do **not** ask them to approve a
   purchase that cannot go through. Say how short they are and give the top-up
   link it returned. If it says `leaseOffered: false`, the creator set no
   per-day price and the lease is genuinely not for sale — say that, quote the
   per-call cost, and let them decide. Never invent a number.

You may also set the role slot's `engagement` to `recurring` or `standing` with
`expectedCallsPerDay` when you can estimate it. That is a hint for the record,
not the source of the numbers: ask `prepare_execution` for a `costAdvisory`
only if your host tolerates extra fields on the plan, and take the numbers from
the quote tool otherwise.

Beyond what the agent itself needs, ask only about the lease: a one-shot call
needs no extra question.

If the Hub source is unavailable or refuses the call, report its exact refusal;
do not silently search Local or Cloud. Core owns the Hub upstream transport;
do not expose a direct remote `agentlas` MCP alongside it. A prepared roster
is not proof of execution.

For a `partial` or `failed` result, report each source receipt's exact
`failureCode`. Never collapse several receipts into one, substitute a different
code, or relabel the outcome.
