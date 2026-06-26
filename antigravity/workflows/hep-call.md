Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-call


Prepare explicitly named Agentlas Hub or Cloud agents.

Syntax: `/hep-call agent-a, agent-b {context}`.

1. Run the app-host auto-update preflight inside Antigravity when a local shell
   command is available (`HEPHAESTUS_APP_AUTO_UPDATE=1`, installer URL
   `https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh`).
   Do not ask the user to open a separate terminal.
2. Resolve the runner: `~/.agentlas/runtime/current/bin/hephaestus` first, then
   `./bin/hephaestus`.
3. Ensure sign-in: `hephaestus auth ensure --timeout 180`.
4. Split the argument before `{` as the agent list and the text inside braces
   as context. If braces are omitted, treat the first token as the agent list.
5. Run: `hephaestus call "<agents>" "<context>" --runtime antigravity`.
6. For each prepared agent, follow `output.entry_excerpt` and
   `output.grounding.directive`. Report failed agents separately.
7. Include the top-level `receipt_id` and every prepared `execution_id`.
