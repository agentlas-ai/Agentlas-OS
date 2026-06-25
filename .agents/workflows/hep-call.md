Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-call


Prepare explicitly named Agentlas Hub or Cloud agents.

Syntax: `/hep-call agent-a, agent-b {context}`.

1. Resolve the runner: `~/.agentlas/runtime/current/bin/hephaestus` first, then
   `./bin/hephaestus`.
2. Ensure sign-in: `hephaestus auth ensure --timeout 180`.
3. Split the argument before `{` as the agent list and the text inside braces
   as context. If braces are omitted, treat the first token as the agent list.
4. Run: `hephaestus call "<agents>" "<context>" --runtime antigravity`.
5. For each prepared agent, follow `output.entry_excerpt` and
   `output.grounding.directive`. Report failed agents separately.
6. Include the top-level `receipt_id` and every prepared `execution_id`.
