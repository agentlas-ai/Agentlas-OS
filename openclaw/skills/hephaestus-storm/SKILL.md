---
name: hephaestus-storm
description: "Use when the user types /hep-storm, mentions @Hephaestus storm, or asks to force-robustly drive a loop-worthy goal (apps, sites, agents, automations, debugging, multi-step research, data/report generation) to a verified finish. Stormbreaker routes the goal to real Agentlas specialists, materializes a dependency-ordered pipeline fabric, and runs a verifier-first loop that does not stall, run away, or claim false success. Trivial questions are answered directly, not stormed."
metadata: {"openclaw": {"emoji": "🔨", "requires": {"bins": ["python3"]}, "homepage": "https://github.com/agentlas-ai/Agentlas-OS"}}
---

Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Stormbreaker Loop

Drive a goal through the **Stormbreaker Loop** — Hephaestus' force-robust,
verifier-first execution loop. Unlike a one-shot answer or a generic parallel
fan-out, Stormbreaker **routes the goal to real Agentlas specialists**, structures
the work as a dependency-ordered pipeline fabric, drives each work packet as a
**hardened goal loop** (it does not stall, run away, or claim false success), and
**refuses to report success without evidence**. Route this request through the
Stormbreaker engine via the `exec` tool. Never guess an agent yourself when this
skill is active — the router decides the workforce.

Use it for loop-worthy work: apps, sites, agents, automations, debugging,
multi-step research, data/report generation — anything with files, tools, tests,
or external verification. Trivial questions should be answered directly, not
stormed. Also triggered by `@Hephaestus storm <goal>`.

## Core-owned Goal + UltraCode harness

Every result includes `execution_harness`. Apply
`execution_harness.system_prompt` verbatim before planning or executing packets,
retain its `prompt_sha256`, and never redefine Goal mode or UltraCode mode in
this adapter. Pass live session JSON with `AGENTLAS_SESSION_INVENTORY` when the
host provides it; otherwise use Core's explicit `host:primary` fallback.

## 1. Resolve the runner and materialize the execution fabric

The Stormbreaker engine routes the goal and materializes a pipeline fabric
(packets, parallel groups, dependency gates, goal loops, a final gate, and a
resumable journal). In an agentic runtime **you are the executor** — the engine
gives you the verified plan; you carry it out with your own tools.

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
`curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash`

Ensure Agentlas is signed in, then route + materialize the pipeline fabric for
THIS goal. No `--executor-command`: the host model (you) executes each packet
natively. `--research-evidence` grounds plan/research packets with Research
Engine receipts.

```bash
if [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
FABRIC="$("$RUNNER" hep-storm "<the user's goal>" --research-evidence)"
printf '%s\n' "$FABRIC"
```

`auth ensure` opens the user's default browser only when there is no valid local
Agentlas sign-in yet; if a saved sign-in exists it silently reuses it. For
CI/headless checks only, set `HEPHAESTUS_AUTH_AUTOPOPUP=0` and skip it.

Read `route_decision.action` (or `route_action`) and branch — Stormbreaker only
auto-materializes a full fabric for a **pipeline**; other actions still start a
storm, just with the workforce the router chose:

- **`pipeline`** — the result carries the `execution_fabric` (`packets`,
  `parallel_groups`, `sessions`, `resume_policy`), per-packet `write_scope` and
  `goal`/verifier, a `pipeline_id`, a `journal` path, and `final_gate` criteria.
  Run the full loop in §2.
- **`clarify`** — the goal is ambiguous. Ask `clarify_question` with the candidate
  list as ONE batch, then re-run `"$RUNNER" hep-storm "<refined goal>" --research-evidence`.
  This is the scope-lock ambiguity gate; do not guess past it.
- **`route`** (single card) — a one-agent storm: borrow and run that card attached
  to this project, then still apply the verify → repair → final-gate steps.
- **`hub_fallback` / `hub_candidates`** — Hub lookup used redacted keywords only.
  If an `execution` block lists `recommended_agents`, borrow each in stage order
  via `"$RUNNER" hep-call "<agent>" "<goal>" --project .` and run them attached to
  this repo; otherwise report candidates and offer `/hep-build`.
- **`propose_new`** — no fit exists; offer to build one via `/hep-build`.
- **`refuse`** — explain `reasons` (e.g. loop guard) and stop. Do not retry around
  it.

## 2. Run the Stormbreaker Loop over the fabric

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
   group concurrently (delegate where the runtime supports it). When a packet's
   `card` names an Agentlas specialist, **borrow and run it attached to this
   project** via `"$RUNNER" hep-call "<card>" "<goal>" --project .` rather than
   role-playing it. Write artifacts to each packet's `write_scope`.
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

## 3. Loop invariants (why this beats a one-shot loop)

- **Don't break (안 끊기게):** a transient packet failure is journaled and retried
  with backoff, not fatal. Only a genuine streak of hard failures stops the run.
- **Don't run away:** a hard iteration ceiling plus stall detection — measured
  no-progress stops the loop as `stalled` instead of spinning.
- **Keep the goal until done (될 때까지):** the loop reports `reached_goal` only
  when the verifier proves it. No bare "it ran" ever counts.
- **Survive a hard stop:** every packet is a journal step, so a killed run resumes
  its numbering from the journal instead of colliding or restarting from zero.

## 4. Hard rules

- **No fake pass.** If the engine is unavailable, an account/tool/connector/browser
  session is missing, or a gate did not run, report the run as **blocked or
  unverified with the exact next step** — never as complete. A scheduled or
  materialized run is not proof that an external action succeeded.
- The router only chooses agents and fetches BYOM bundles. Actual tool execution
  follows this runtime's own safety and permission model.
- Report the `receipt_id`, `pipeline_id`, and `journal` path in your final message
  so the run is auditable and resumable.

## Examples

```text
/hep-storm ship a working waitlist landing page with a verified signup flow
/hep-storm 이 리포 결제 버그를 재현 PoC까지 만들어서 고치고 회귀 테스트로 검증해줘
@Hephaestus storm turn this research question into a cited report with evidence
```
