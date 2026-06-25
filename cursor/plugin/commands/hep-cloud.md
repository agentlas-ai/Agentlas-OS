Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Cloud routing (my own cloud / 보관함)


Search ONLY the signed-in user's own Agentlas cloud packages (보관함) and route
the request to one of them. Follow the `hephaestus-cloud` skill exactly: resolve
the runner (`~/.agentlas/runtime/current/bin/hephaestus`, then `./bin/hephaestus`,
then the newest Claude/Codex plugin cache copy), run
`"$RUNNER" auth ensure --timeout 180` first (the owner cloud requires sign-in;
the browser opens only on first use and saved sign-ins are reused silently),
then run `"$RUNNER" cloud "<request>" --project .` in the terminal
(`cloud` is shorthand for `route "<request>" --scope cloud`; owner-scoped Hub
query, implies `--hub-only`), then act on the JSON decision (`scope: "cloud"`):
hub_candidates (my OWN cloud packages — report and, on the user's pick, invoke
at 1 credit/call) / clarify / propose_new (offer /hep-network for the
public marketplace, or /hep-build to build new) / refuse. This never searches
the public marketplace or local cards. The router only chooses a package or
fetches a BYOM bundle; actual tool execution follows Cursor's runtime safety and
permission model. Report the routing `receipt_id`.
