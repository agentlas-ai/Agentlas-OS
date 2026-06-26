Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-search


Search Agentlas Cloud and Hub candidates without invoking an agent.

1. Run the app-host auto-update preflight inside Antigravity when a local shell
   command is available (`HEPHAESTUS_APP_AUTO_UPDATE=1`, installer URL
   `https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh`).
   Do not ask the user to open a separate terminal.
2. Resolve the runner: `~/.agentlas/runtime/current/bin/hephaestus` first, then
   `./bin/hephaestus`.
3. Ensure sign-in: `hephaestus auth ensure --timeout 180`.
4. Run: `hephaestus search "<request>" --runtime antigravity --limit 10`.
5. Show `cloud` results first and `hub` results second. Include rank, name,
   slug, description, callable/routing status, why, and `receipt_id`.
6. Do not execute any candidate from this workflow.
