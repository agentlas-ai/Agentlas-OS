Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Search


Search Agentlas Cloud and public Hub candidates without invoking agents.

First run the `hephaestus-network` skill's app-host auto-update preflight inside
Cursor; do not ask the user to open a separate terminal. Resolve the runner
(`~/.agentlas/runtime/current/bin/hephaestus`, then `./bin/hephaestus`), run
`"$RUNNER" auth ensure --timeout 180`, then run
`"$RUNNER" search "<request>" --runtime cursor --limit 10`.

Show `cloud` and `hub` sections with rank, name, slug, description,
callable/routing status, why, and `receipt_id`. Do not invoke candidates from
this command.
