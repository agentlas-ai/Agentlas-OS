---
description: Set or show which model runs the orchestrator and which runs the workers.
argument-hint: <orchestrator=tier worker=tier>
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

Set or show which model runs the orchestrator and which runs the workers.

Raw request: `$ARGUMENTS`

A role split only saves anything when the roles actually run on different
models. Before this policy existed the allocator had nothing to read, so every
worker inherited the orchestrator's frontier model and a five-worker fan-out
billed five frontier runs to do work a cheap model finishes.

## Read the request

- No arguments, or `show`/`status` → report the current policy and stop.
- `clear`/`reset` → remove the policy and stop.
- Otherwise the request is one or more `role=value` pairs.

`role` is `orchestrator` or `worker`. `value` is either a tier
(`economy`, `balanced`, `frontier`) — read as a ceiling — or an exact model id
from the live host inventory, read as a pin. An empty value drops that role
back to inherited.

## Apply it

Run the host command and report exactly what it prints:

```
hep-orch <role=value> [<role=value>...]
```

Do not edit `~/.agentlas/one/model-policy.json` by hand and do not export
`AGENTLAS_MODEL_ALLOCATION_POLICY_JSON` on the user's behalf. The environment
variable is the operator override and outranks this file; say so if it is set,
because the policy the user just wrote will not be the one in force.

## Which hosts can actually act on it

The policy is read on every host, but only a host that can run a worker as a
separate invocation can put two different models to work at once.

- **Claude Code** spawns real subagents and takes a model per subagent, so an
  orchestrator/worker split runs as written — this is the only host where the
  split is verified end to end today.
- **Codex, Gemini/Antigravity, Cursor, OpenCode** have no subagent of their own.
  One model plays every role in sequence. The allocation receipt is still
  produced and the ceiling still applies to what that model may request, but a
  worker tier does not put a second, cheaper model on the machine.

Say which of the two the current host is when you report. A user who set
`worker=economy` on a sequential host has a correct policy and no second model;
letting that read as a cost split would be a lie the receipt does not tell.

## What it changes

- `model.resolve_allocation` reads this policy before every role-split
  invocation and clamps or pins that stage accordingly. A worker ceiling
  rejects a frontier request with `tier_clamped_by_cost_policy` — that is the
  policy working, not a failure to route.
- A missing worker policy inherits orchestrator; orchestrator never falls
  through to worker.
- The Agentlas One status line shows the active split, so the user can see the
  setting is in force instead of assuming it.

## Report honestly

State the resulting policy in one line, and name the ceiling that will bite
first. If the user pinned a model id, say plainly that a pin is only executable
while that exact model is in the host's live inventory — a pin to a model this
machine cannot reach leaves the stage unresolved rather than silently
downgrading it.

Recommend a split only from what the tasks actually need: mechanical fan-out
(collect, transform, verify a known rule) belongs on `economy`, while planning,
judgement, and final synthesis stay high. Do not promise a cost saving you have
not measured — the saving is real only when the workers were genuinely doing
mechanical work.
