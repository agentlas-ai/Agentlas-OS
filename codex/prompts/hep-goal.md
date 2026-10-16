---
description: Add a plan tree and KPI check to the host /goal for long, measurable goals.
argument-hint: <goal>
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-goal

Adds a plan tree to the host's own `/goal`: a shape for the goal, strategies and tactics, and a KPI reading that says whether the plan is working. The host goal still decides when the work is done; this only keeps the plan and the numbers honest.

## Pick the shape first

Run `hep-goal schema` once and follow the field lists it prints. Then choose:

- **single_tactic** (short work with one clear check: a bug, a test, a file): store it with `hep-goal start` and stop using this command. From here it is exactly the host `/goal`.
- **tactic_list** (several known steps): store the steps with `done_when` for each.
- **mission_tree** (long work with a number the owner named: followers, revenue, signups): store the objective, the diagnosis of the biggest obstacle, the key results, strategies and tactics.

A target is only a number the owner wrote in the goal text, and an owner boundary needs a quote from it. The store refuses anything else, so do not invent them.

## Run it

1. `hep-goal start --goal-text "<the owner's exact text>" --json <draft>` stores the plan and prints the goal id.
2. Before each turn, `hep-goal context --goal-id <id>` prints a short block (empty means say nothing about the plan). Work the tactics it names.
3. When you read a KPI, record it: `hep-goal kpi-sample --goal-id <id>` with the value, the time, the **source** and a short **evidence** quote. A second reading from a different tool (`reobserved`) makes it verified. Without a source and evidence it is refused.
4. When the context says a review is due, `hep-goal review --goal-id <id>` shows the table and the strategies. Answer with one `shift` (`hold`, `pivot`, `double_down` or `escalate_owner`) that cites sample ids.
5. If it reports an owner hold, tell the owner the three numbers it names (current, needed per day, observed per day) and wait. Do not re-plan until they answer; then `hep-goal owner-answer`.

## Limits that always apply

- Pass `--key <unique text>` on any call you may repeat, so a retry cannot write twice.
- These commands change only the goal's own files. They never change permissions, payments or any outside service.
- Mode is `AGENTLAS_GOAL_STRATEGY` = `shadow` (default: store and measure, inject nothing, apply no shift), `on` or `off`. Report which mode is in force.
- Readings come from what you actually observed. Never write a number you did not read.
