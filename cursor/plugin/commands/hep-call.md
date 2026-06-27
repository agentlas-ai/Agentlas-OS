Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Call


Prepare explicitly named Agentlas Hub or Cloud agents.

Syntax: `/hep-call agent-a, agent-b {context}`.

First run the `hephaestus-network` skill's app-host auto-update preflight inside
Cursor; do not ask the user to open a separate terminal. Resolve the runner
(`~/.agentlas/runtime/current/bin/hephaestus`, then `./bin/hephaestus`), run
`"$RUNNER" auth ensure --timeout 180`, split the
arguments into agent list and context, then run
`"$RUNNER" call "<agents>" "<context>" --runtime cursor`.

For each prepared agent, follow `output.entry_excerpt` and
`output.grounding.directive`. Report failures separately and include
`receipt_id` plus every prepared `execution_id`.
