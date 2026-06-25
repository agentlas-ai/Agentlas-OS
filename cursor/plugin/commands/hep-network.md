Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Network routing


Route everything typed after this command through the Hephaestus Network
local-first router. Follow the `hephaestus-network` skill exactly: resolve the
runner (`~/.agentlas/runtime/current/bin/hephaestus`, then `./bin/hephaestus`,
then the newest Claude/Codex plugin cache copy), run
`"$RUNNER" auth ensure --timeout 180` first so the browser sign-in opens on
first use and existing Agentlas saved sign-ins are reused silently, then run
`"$RUNNER" route "<request>" --runtime cursor` in the terminal, then act on the
JSON decision (route / clarify / pipeline / hub_fallback / propose_new /
refuse). Before reporting a GUI shortcut such as `startup`, run
`"$RUNNER" local-gui "<request>" --detach --quiet-not-found`: this opens a
local GUI when the source folder exists, and on another machine restores the Hub
cloud package before launching its packaged GUI. The router only chooses an
agent or fetches a BYOM Hub bundle; actual tool execution follows Cursor's
runtime safety and permission model. Report the routing `receipt_id`.
