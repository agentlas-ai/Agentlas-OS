---
description: Staff a task from registered Local, owner Cloud, and public Hub agents.
argument-hint: '<request>'
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-network

Raw request: `$ARGUMENTS`

You are the active top-level workforce orchestrator. Use the local Agentlas
OS MCP server named `hephaestus-network`, the only host-visible Workforce MCP.
Core reaches Cloud and Hub through its internal upstream client. Network means all registered
Local agents, the signed-in owner's Cloud agents, and public Hub agents.

Before every unpinned discovery, Core refreshes the current safe snapshot for
each active registered Local source. A changed Local folder therefore becomes a
new candidate release in this search without requiring `network reindex`; the
selected and prepared release remains immutable after that discovery.

The user does not need to say `goal`. First call `workforce.goal_context` for
the current project, passing `knownRevisions` with any `goalId -> rosterRevision`
pairs already in this conversation so unchanged goals come back as one line. If
it returns an active binding for this ongoing work, reuse that exact roster and
`goalId` before considering recruitment. If it returns `pendingExecution`, those
releases were prepared and never run: either run them now or say so plainly —
preparation is not delivery, and the session-end checkpoint reports the same
fact to the user.

Before the first Cloud or Hub source call, reuse the installed Agentlas
sign-in. Resolve the runner in this order and use it only for authentication;
the host LLM still performs staffing through the Workforce MCP tools:

```bash
RUNNER=""
for candidate in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/hephaestus}" \
  "${PLUGIN_ROOT:+$PLUGIN_ROOT/bin/hephaestus}" \
  "${GEMINI_EXTENSION_ROOT:+$GEMINI_EXTENSION_ROOT/bin/hephaestus}" \
  "./bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi
done
[ -n "$RUNNER" ] && "$RUNNER" auth ensure >/dev/null 2>&1 || true
```

1. Call `workforce.preflight_work_order` with a compact draft: `taskBrief`,
   one `roles` entry per materially distinct responsibility, and `edges` by
   1-based role ordinal. Core compiles the exact redacted
   `agentlas.workforce-work-order.v1`, generates every transaction/slot/artifact
   id, fills omitted arrays, validates the privacy boundary and returns a
   one-hour `workOrderRef`. Write required skills as plain English phrases when
   no ontology id is obvious — Core normalizes them and reports each rewrite as
   `normalizedConcepts`. Give each role a specific `task`, `cardinality`,
   `criticality`, and — only when they
   genuinely constrain semantic fit — required communities/roles/skills/
   knowledge. The title, task, publisher summary, and sample request sentences
   remain the primary fit evidence. Execution requirements are a separate
   contract: include `requiredToolCapabilities`, required/forbidden authorities,
   runtimes, languages, or modalities only when the requested action genuinely
   requires the host to prove them. They do not rank or exclude semantic
   candidates; Core carries them unchanged into the ExecutionContext, where the
   host must bind its actual tool inventory and permission receipt. Leave every
   unconstrained list absent (the wire normalizes absent to `[]`). Keep
   `consumes`/`produces` absent and describe ordinary inputs/outputs in the task
   text and inter-slot handoffs in `edges`. An edge
   is a declaration of handoff and never a qualification requirement. Only
   semantic communities, roles, skills, and knowledge explicitly required by
   the task may narrow menu fit. Tool capability, authority, runtime, language,
   and modality fields never filter or rank that menu; they remain post-selection
   execution proof. Hand-off
   edges must be acyclic: a review or feedback edge that points back to an
   earlier slot is rejected as `task_force_cycle:<the loop path>` — model review
   as a forward hand-off to the reviewer, not a back-edge (measured 2026-08-19:
   a researcher→research→quality-engineer order with a `reviews` back-edge was
   refused, and because edges live inside the WorkOrder the repair changed
   `workOrderDigest` and forced the whole three-source federation to run again).
   Keep the default `selectionPolicy.maximumCandidatesPerSlot` at 30 unless a
   measured recall need justifies widening it (the schema allows up to 100),
   and NEVER shrink it merely to save tokens: the menu is ordered by
   `canonical_identity_no_rerank`, not by fit — federation performs no scoring
   by design — so truncating the candidate count discards candidates
   arbitrarily, not worst-first. Measured 2026-08-19: the only domain-fit
   candidate for each of three slots sat at ordinals 13-17 behind twelve
   unrelated agents, so a cap of 8 would have made the order un-staffable.
   Token savings come from the menu's compact per-row projection, never from
   fewer rows. In the returned menu, `candidateOrdinal` restarts at 1
   inside every slot — it is a per-slot position, not a running number across
   the menu. Keep private
   files, memory, secrets, direct identifiers, and raw local context on-host.
   Write every discovery-facing natural-language field (statement, role
   descriptions, required skills/knowledge) in English, faithfully translating a
   non-English request rather than passing its original wording through: the
   candidate corpus is English and cross-lingual matching silently buries the
   correct agent (measured: an identical query ranked its target 1st in English
   and 144th in Korean). Keep an untranslatable proper term alongside a short
   English gloss, e.g. `종합소득세 (Korean comprehensive income tax)`. The
   `languages` slot is the delivery requirement, not the search language — set
   it to the language the work product must be produced in (e.g. `ko`) even
   though the order itself is written in English.
2. Call `workforce.search_candidates` on `hephaestus-network` with
   `{workOrderRef, sourceScope: "network"}`. Preserve every source receipt and
   `selectionSessionId`; the default projected menu is not a complete
   `federationResult` and must not be echoed as one. An
   unavailable source is explicit; it is not permission to pretend that source
   participated.
2b. For a multi-slot search, call it with `shortlist: true`. The response then
   carries summary cards (ordinal, name, entityKind, communities, one summary,
   `callable`, `missingMandatory`, and `publisherTriggerMatch` when the
   publisher's own trigger sentences match this request) instead of full
   dossiers — measured 40,873B -> 10,087B for one 20-candidate slot. Narrow to
   the candidates worth a closer look, then call `workforce.expand_candidates`
   with `{selectionSessionId, candidates:[{slotId, candidateOrdinal}]}` and
   **decide from those full cards**, never from the summary alone. Keep the
   shortlist generous (six to eight per slot): the summary is for discarding
   the obviously wrong, not for picking the winner.
3. As the active host LLM, decide the staffing from the returned content and
   qualification evidence, then call `workforce.validate_selection` with
   `{decision}`: `selectionSessionId`, `decisionAuthor` (your real model id),
   and one `assignments` row per post naming the candidate by its per-slot
   `candidateOrdinal` with `reasonCodes`. Core loads the pinned menu and the
   pinned WorkOrder from that session, supplies the candidate-set digest and the
   arrays that are empty in a normal decision, and compiles the exact
   `agentlas.workforce-selection.v1`. Keep the accepted response's
   `federatedSelectionDigest`. Revise on rejection. Deterministic code may
   enforce governance but must not choose, rerank, or silently substitute the
   roster. An accepted result may still carry `unmetRequirementCount` — that is
   not a rejection, but read `selectionValidation.unmetRequirements` and either
   accept the gap deliberately or reselect. Never report an accepted validation
   as if nothing were unmet.
4. Call `workforce.prepare_execution` with
   `{selection, federatedSelectionDigest, projectDir, goalId?, fullDossier: false}`.
   `projectDir` is mandatory. Pass the incumbent `goalId` when continuing;
   otherwise Core joins this project's incumbent active automatic goal, and
   opens a new one only when there is none. Core must automatically
   bind a successful preparation before execution, so continuity cannot be
   skipped because no explicit goal mode was requested.
   `fullDossier: false` requests the projected response
   (`projection: "prepare.v2"`): `executionRoster` rows carry identifiers and
   digests, and each worker's `directiveBundle`/`executionGraph` is shipped
   once per `contentDigest` in top-level `bundleContents` — resolve a row's
   content by its `contentDigest` there (a same-agent-two-slots roster would
   otherwise repeat the bundle byte-identically). The bound preparation stores
   the unprojected original. Omitting the flag returns legacy self-contained
   rows — the compatible default for machine verifiers that recompute
   `bundleDigest` over whole rows and update independently of the runtime.
   Require each worker to retain its exact source plus release, package hash,
   content digest, runtime-bundle digest, permission policy, and execution
   context pins. Recompute digests and fail closed on drift.
5. On later turns call `workforce.goal_context` first: reuse the incumbent
   roster plus local skills when sufficient; recruit only a real gap and pass
   the same `goalId` to preparation so new releases append. Record
   `reuse|local-only|recruit|standby|blocked` with
   `workforce.record_goal_turn`.
6. Before every bound invocation, advertise the live host sessions and call
   `model.resolve_allocation` with that inventory plus the host-owned stage:
   `planner`/`manager-plan`, `worker`, `manager-synthesis`/`synthesis`, or
   `verifier`. Use the receipt's exact provider, model, and effort for that
   invocation. Model pins and ceilings come only from the MCP server's operator
   policy, never from the task or tool arguments. A missing worker policy
   inherits orchestrator; orchestrator never falls through to worker.
   Each advertised session carries `session_id`, `model`, `provider`, and —
   when the host knows them — `tier`, `supported_efforts`, and `context_window`.
   Send what the host actually reports and never invent a field: an omitted
   context window is assumed at a conservative floor and the receipt says so
   (`inventory_context_window_assumed`), whereas a fabricated one would be read
   as measured. Operators set the orchestrator/worker policy with
   `hep-orch orchestrator=<tier|model> worker=<tier|model>`.
7. Run only the bound workers useful for this turn. For a selected team,
   preserve its authoritative manager/worker graph. Run planner/manager,
   workers, synthesis, and verifier as distinct invocations with explicit
   artifact handoffs. Allocation receipts have `usage: null` before execution,
   so record actual usage on the later invocation/run receipt instead of
   inventing zero.
8. Report `executed` only when the execution receipt proves every selected
   invocation, handoff, synthesis, and an independent passing verifier.
   Otherwise report the last truthful state: `selected`, `prepared`,
   `source_unavailable`, `blocked`, or `failed`. For `partial` or `failed`,
   report each source receipt's exact `failureCode`: never collapse several
   receipts into one, substitute a different code, or relabel the outcome.

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

The roster remains bound across turns, sessions, restarts, and context
compaction until the whole goal is explicitly completed/cancelled through
`workforce.complete_goal(explicitCompletion=true)`. A Hub lease only controls
whether the next real borrow is charged; it never ends the goal binding.
Standby is durable availability, not a continuously running model.
Memory Curator/Experience continue on actual worker invocations only.

Do not call legacy `hephaestus_route`, register or use direct remote search as a substitute
for Core federation, or use popularity/history/price/local availability as
semantic fit. Exact duplicate releases may collapse Local > Cloud > Hub only
when Core returns verified identical lineage; a name or slug match is not
enough. Name the actual workers in the result.
