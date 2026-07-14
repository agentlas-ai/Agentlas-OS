---
name: hephaestus-storm
description: "Use when the user types /hep-storm, says @Hephaestus storm <goal>, or asks to drive a goal to verified completion through a force-robust Stormbreaker loop. Stormbreaker routes the goal to real Agentlas specialists, materializes a dependency-ordered pipeline fabric, and runs each work packet as a verifier-first hardened loop that does not stall, run away, or claim false success. Use it for loop-worthy work — apps, sites, agents, automations, debugging, multi-step research, data/report generation. Trivial questions are answered directly, not stormed."
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Stormbreaker Loop

Drive a goal through the **Stormbreaker Loop** — Hephaestus' force-robust,
verifier-first execution loop. Unlike a one-shot answer or a generic parallel
fan-out, Stormbreaker **routes the goal to real Agentlas specialists**, structures
the work as a dependency-ordered pipeline fabric, drives each work packet as a
**hardened goal loop** (it does not stall, run away, or claim false success), and
**refuses to report success without evidence**. Never guess an agent yourself when
this skill is active — the router or Hub decides the workforce.

## Core-owned Goal + UltraCode harness

Every `hep-storm` result includes `execution_harness`. Before planning or
executing any packet, apply `execution_harness.system_prompt` **verbatim** and
retain its `prompt_sha256` in the goal ledger. This adapter must never redefine,
summarize, or replace Goal mode or UltraCode mode with host-local wording. The
adapter owns invocation only; Agentlas Core owns the execution protocol.

If the host exposes live Codex, Claude Code, Gemini, local-model, or other
sessions, provide their JSON array through `AGENTLAS_SESSION_INVENTORY` or
`--session-inventory`. If it does not, accept Core's explicit `host:primary`
fallback; never invent a model ID or claim unavailable parallel workers.

With no external executor, the runner intentionally returns `status:
materialized` and `final_gate.can_report_success: false`. That is the host's
signal to execute the returned packets with its native tools; it is not a
failure and must never be rewritten as completion.

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

## 1.5 Core project first-contact contract

Every `hep-storm` call is a trusted plugin contact. Before routing or
materializing packets, Agentlas Core synchronously creates or repairs the
canonical private project soul memory, code map, ontology runtime, CareerGraph,
and merge-only `.gitignore` block for all of `.agentlas/`. A blocked bootstrap
receipt blocks the storm. The adapter must not substitute host-local files or a
second bootstrap implementation.

## 2. Agentlas sign-in

Before routing, ensure Agentlas is signed in:

```bash
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
```

This opens the user's default browser only when there is no valid local
Agentlas sign-in yet. If a saved sign-in already exists, it silently reuses it.
For CI/headless checks only, set `HEPHAESTUS_AUTH_AUTOPOPUP=0` and skip this step.

## 3. Route and materialize the execution fabric

The Stormbreaker engine routes the goal and materializes a pipeline fabric
(packets, parallel groups, dependency gates, goal loops, a final gate, and a
resumable journal). In an agentic runtime **you are the executor** — the engine
gives you the verified plan; you carry it out with your own tools. No
`--executor-command`: the host model (you) executes each packet natively.
`--research-evidence` grounds plan/research packets with Research Engine receipts.

```bash
FABRIC="$("$RUNNER" hep-storm "<the user's goal>" --research-evidence --runtime "${AGENTLAS_HOST_RUNTIME:-agent-skills}")"
printf '%s\n' "$FABRIC"
```

## 4. Branch on the route decision

Read `route_decision.action` (or `route_action`) and branch — Stormbreaker only
auto-materializes a full fabric for a **pipeline**; other actions still start a
storm, just with the workforce the router chose:

- **`pipeline`** — the result carries the `execution_fabric` (`packets`,
  `parallel_groups`, `sessions`, `resume_policy`), per-packet `write_scope` and
  `goal`/verifier, a `pipeline_id`, a `journal` path, and `final_gate` criteria.
  Run the full loop in §5.
- **`clarify`** — the goal is ambiguous. Ask `clarify_question` with the candidate
  list as ONE batch, then re-run `"$RUNNER" hep-storm "<refined goal>"`. This is
  the scope-lock ambiguity gate; do not guess past it.
- **`route`** (single card) — a one-agent storm: borrow and run that card attached
  to this project, then still apply the verify → repair → final-gate steps.
- **`hub_fallback` / `hub_candidates`** — Hub lookup used redacted keywords only.
  If an `execution` block lists `recommended_agents`, borrow each in stage order
  via `"$RUNNER" hep-call "<agent>" "<goal>" --project .` and run them attached to
  this repo; otherwise report candidates and offer `/hep-build`.
- **`propose_new`** — no fit exists; offer to build one via `/hep-build`.
- **`refuse`** — explain `reasons` (e.g. loop guard) and stop. Do not retry around
  it.

## 5. Run the Stormbreaker Loop over the fabric

Execute the goal to completion under this protocol. **Do not stop to ask for
confirmation** — this is a force-robust run. Only halt when the goal is verified,
or you are genuinely blocked by auth, payment, policy, a missing secret/tool, or
a required user approval.

1. **scope-lock** — Restate the goal as one sentence and lock to it. Check the
   route decision's failure-memory. If (and only if) the goal is too ambiguous to
   decompose safely, ask ONE batch of 3–5 questions (what NOT to do / smallest
   version / done signal / dependencies), then proceed. If it is already specific,
   ask nothing.
2. **issue contract** — Write the acceptance criteria: the concrete, checkable
   done-signal for each packet and for the whole goal. These become the loop's
   stop criteria.
3. **plan-lock** — Adopt the fabric's `parallel_groups` and `depends_on` ordering
   as the plan. Open a **visible goal ledger**: packet, owner, verification gate,
   status, resume point.
4. **act** — Execute the next unblocked group. Run independent packets in the
   group concurrently (delegate with the Task tool where the runtime supports it).
   When a packet's `card` names an Agentlas specialist, **borrow and run it
   attached to this project** via `"$RUNNER" hep-call "<card>" "<goal>" --project .`
   rather than role-playing it. Write artifacts to each packet's `write_scope`.
5. **verify** — A packet passes only when its verifier passes (a packet with a
   `loop.goal_command` is met when that command exits 0; an artifact packet is met
   when its acceptance check passes). "It ran" is never success.
6. **bounded repair/retry** — On a concrete validation failure, repair and re-run
   that packet — bounded. Honor the goal-loop budget: tolerate transient failures
   with backoff, stop a packet as `stalled` after consecutive no-progress
   iterations, and never exceed its iteration ceiling. A resumed run continues
   from the journal, it does not restart.
7. **final-gate** — Report success only if the fabric's final gate clears
   (`can_report_success`). Run the evidence/security gate on produced artifacts.

Keep visible progress concise: what was attempted, what was **verified**, and
exactly where to resume if blocked. Never expose hidden reasoning — show
progress, evidence, decisions, and final status only.

## 6. Loop invariants (why this beats a one-shot loop)

- **Don't break (안 끊기게):** a transient packet failure is journaled and retried
  with backoff, not fatal. Only a genuine streak of hard failures stops the run.
- **Don't run away:** a hard iteration ceiling plus stall detection — measured
  no-progress stops the loop as `stalled` instead of spinning.
- **Keep the goal until done (될 때까지):** the loop reports `reached_goal` only
  when the verifier proves it. No bare "it ran" ever counts.
- **Survive a hard stop:** every packet is a journal step, so a killed run resumes
  its numbering from the journal instead of colliding or restarting from zero.

## 7. Hard rules

- **No fake pass.** If the engine is unavailable, an account/tool/connector/browser
  session is missing, or a gate did not run, report the run as **blocked or
  unverified with the exact next step** — never as complete. A scheduled or
  materialized run is not proof that an external action succeeded.
- The router only chooses agents and fetches BYOM bundles. Actual tool execution
  follows this runtime's own safety and permission model (Claude Code, Codex,
  Cursor, etc.).
- Report the `receipt_id`, `pipeline_id`, and `journal` path in your final message
  so the run is auditable and resumable.
