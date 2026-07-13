Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Stormbreaker loop


Drive everything typed after this command through the **Stormbreaker Loop** —
Hephaestus' force-robust, verifier-first execution loop. Unlike a one-shot answer
or a generic parallel fan-out, Stormbreaker routes the goal to real Agentlas
specialists, structures the work as a dependency-ordered pipeline fabric, drives
each work packet as a hardened goal loop (it does not stall, run away, or claim
false success), and refuses to report success without evidence. Also triggered by
`@Hephaestus storm <goal>`. Use it for loop-worthy work: apps, sites, agents,
automations, debugging, multi-step research, data/report generation — anything
with files, tools, tests, or external verification. Trivial questions should be
answered directly, not stormed.

## Core-owned Goal + UltraCode harness

Every result includes `execution_harness`. Apply
`execution_harness.system_prompt` verbatim before planning or executing packets,
retain its `prompt_sha256`, and never redefine Goal mode or UltraCode mode in
this Cursor adapter. Pass live session JSON with
`AGENTLAS_SESSION_INVENTORY` when available; otherwise use Core's explicit
`host:primary` fallback.

Follow the `hephaestus-network` skill exactly to resolve the runner: first run
its app-host auto-update preflight inside Cursor (no separate terminal prompt to
the user), then use `~/.agentlas/runtime/current/bin/hephaestus`,
`./bin/hephaestus`, then the newest Claude/Codex plugin cache copy (first
executable wins). Run `"$RUNNER" auth ensure --timeout 180` first so the browser
sign-in opens on first use and existing Agentlas saved sign-ins are reused
silently, then materialize the execution fabric for THIS goal by running
`"$RUNNER" hep-storm "<goal>" --research-evidence --runtime cursor` in the
terminal. No `--executor-command`: in an agentic runtime **you are the
executor** — the engine hands you the verified plan and you carry each packet out
with Cursor's own tools. `--research-evidence` grounds plan/research packets with
Research Engine receipts.

## Branch on the route decision

Read `route_decision.action` (or `route_action`) from the JSON and branch —
Stormbreaker only auto-materializes a full fabric for a **pipeline**; the other
actions still start a storm, just with the workforce the router chose:

- **`pipeline`** — the result carries the `execution_fabric` (`packets`,
  `parallel_groups`, `sessions`, `resume_policy`), per-packet `write_scope` and
  `goal`/verifier, a `pipeline_id`, a `journal` path, and `final_gate` criteria.
  Run the full Stormbreaker Loop below.
- **`clarify`** — the goal is ambiguous. Ask `clarify_question` with the candidate
  list as ONE batch, then re-run `"$RUNNER" hep-storm "<refined goal>"
  --runtime cursor`. This is the scope-lock ambiguity gate; do not guess past it.
- **`route`** (single card) — a one-agent storm: borrow and run that card attached
  to this project, then still apply the verify → repair → final-gate steps.
- **`hub_fallback` / `hub_candidates`** — Hub lookup used redacted keywords only.
  If an `execution` block lists `recommended_agents`, borrow each in stage order
  via `"$RUNNER" hep-call "<agent>" "<goal>" --project .` and run them attached to
  this repo; otherwise report candidates and offer `/hep-build`.
- **`propose_new`** — no fit exists; offer to build one via `/hep-build`.
- **`refuse`** — explain `reasons` (e.g. loop guard) and stop. Do not retry around
  it.

## Run the Stormbreaker Loop over the fabric

Execute the goal to completion under this protocol. **Do not stop to ask for
confirmation** — this is a force-robust run. Only halt when the goal is verified,
or you are genuinely blocked by auth, payment, policy, a missing secret/tool, or a
required user approval.

1. **scope-lock** — Restate the goal as one sentence and lock to it. Check the
   route decision's failure-memory. Only if the goal is too ambiguous to decompose
   safely, ask ONE batch of 3–5 questions (what NOT to do / smallest version /
   done signal / dependencies), then proceed. If it is already specific, ask
   nothing.
2. **issue contract** — Write the acceptance criteria: the concrete, checkable
   done-signal for each packet and for the whole goal. These become the loop's
   stop criteria.
3. **plan-lock** — Adopt the fabric's `parallel_groups` and `depends_on` ordering
   as the plan. Open a visible goal ledger: packet, owner, verification gate,
   status, resume point.
4. **act** — Execute the next unblocked group, running independent packets in the
   group concurrently where Cursor supports it. When a packet's `card` names an
   Agentlas specialist, borrow and run it attached to this project via
   `"$RUNNER" hep-call "<card>" "<goal>" --project .` rather than role-playing it.
   Write artifacts to each packet's `write_scope`.
5. **verify** — A packet passes only when its verifier passes (a packet with a
   `loop.goal_command` is met when that command exits 0; an artifact packet is met
   when its acceptance check passes). "It ran" is never success.
6. **bounded repair/retry** — On a concrete validation failure, repair and re-run
   that packet — bounded. Honor the goal-loop budget: tolerate transient failures
   with backoff, stop a packet as `stalled` after consecutive no-progress
   iterations, and never exceed its iteration ceiling. A resumed run continues from
   the journal, it does not restart.
7. **final-gate** — Report success only if the fabric's final gate clears
   (`can_report_success`). Run the evidence/security gate on produced artifacts.

Keep visible progress concise: what was attempted, what was **verified**, and
exactly where to resume if blocked. Never expose hidden reasoning — show progress,
evidence, decisions, and final status only.

## Loop invariants (why this beats a one-shot loop)

- **Don't break (안 끊기게):** a transient packet failure is journaled and retried
  with backoff, not fatal. Only a genuine streak of hard failures stops the run.
- **Don't run away:** a hard iteration ceiling plus stall detection — measured
  no-progress stops the loop as `stalled` instead of spinning.
- **Keep the goal until done (될 때까지):** the loop reports `reached_goal` only
  when the verifier proves it. No bare "it ran" ever counts.
- **Survive a hard stop:** every packet is a journal step, so a killed run resumes
  its numbering from the journal instead of colliding or restarting from zero.

## Hard rules (no fake pass)

- **No fake pass.** If the engine is unavailable, an account/tool/connector/browser
  session is missing, or a gate did not run, report the run as **blocked or
  unverified with the exact next step** — never as complete. A scheduled or
  materialized run is not proof that an external action succeeded.
- The router only chooses agents and fetches BYOM bundles; actual tool execution
  follows Cursor's runtime safety and permission model.
- Report the `receipt_id`, `pipeline_id`, and `journal` path in your final message
  so the run is auditable and resumable.
