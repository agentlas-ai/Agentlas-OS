# Changelog

## Unreleased

## v0.7.20 - 2026-06-22

- Aligned Hub-facing language around Agents, Teams, and Plugins so public
  surfaces show invocation credits separately from downloadable packages.
- Kept local `trusted` routing-card behavior as the local-first Network
  trust path while keeping upload and Hub publication security review as a
  separate gate.
- Removed Mason-local package bucket label leakage from routing docs,
  benchmarks, adapter skills, CLI tier choices, ontology contracts, and
  mirrored runtime packages.
- Tightened public safety scanning so real `/Users/...` and `/Volumes/...`
  local paths are still blocked without flagging the redaction regex literals
  used by the runtime itself.

## v0.7.19 - 2026-06-21

- Fixed one-touch installer Python shim recursion: installer now rejects
  `~/.agentlas/runtime/current/bin/python3` as a Python candidate, prefers real
  system Python paths, removes stale shims before writing new ones, and replaces
  a malformed `runtime/current` directory with the intended symlink.
- Made user-facing install docs versionless: paste-to-AI prompts now point to
  the GitHub repository/latest instructions, and terminal examples use the
  `main` one-touch installer instead of release-pinned install URLs.
- Added deterministic GUI shortcut launch for Hub-distributed packages:
  `/hep-network startup` now restores the Startup Founder Studio cloud package
  and launches its packaged GUI even when Mason's local `private` folder is not
  present.
- Changed Network MCP/GUI shortcut defaults to ignore local `private` and `restricted`
  routing cards. Local routing is now an explicit operator/debug escape hatch
  only, via `allow_local_routing`, `--allow-local`, or `--local-first`.
- Changed the raw `hephaestus route` CLI default to Hub-only as well; local
  cards require the hidden `--allow-local-routing` debug flag.
- Added the `hephaestus local-gui` runtime command and wired `/hep-network`
  surfaces to use it before falling back to plain candidate routing for GUI
  shortcuts.
- Renamed the visible command surface to the short `/hep-*` family across app,
  web/docs, terminal, and runtime adapters: `/hep-build`, `/hep-network`,
  `/hep-cloud`, `/hep-search`, `/hep-call`, and `/hep-upload`.
- Added `/hep-upload` and `hep-upload`, which always ask Cloud-private vs
  Agentlas-Hub-public before any package, publish, register, or upload action.
- Updated installer/sync/verification contracts so new runtime installs expose
  the short command names and prune stale `/hephaestus-*` command files.

## v0.7.11 - 2026-06-19

- Added the Stormbreaker auto-runner for Hephaestus Network pipeline decisions:
  routed `execution_fabric` packets can now be dispatched, journaled, recorded
  in execution receipts, and final-gated by the local runner.
- Added the terminal `hep-storm` command for explicit background packet
  execution. Background runs write result, stdout, stderr, and decision files
  under `.agentlas/stormbreaker/background/<run_id>/`.
- Let terminal `hep-network` auto-start Stormbreaker for runnable
  pipeline fabrics while preserving `--plan-only` as the routing-only escape
  hatch.
- Added executor adapter options for real runtime/session binding:
  `--executor-command`, `--execute-card-commands`, `--session-inventory`,
  `--max-workers`, and per-packet `--timeout`.
- Documented the elastic-but-bounded worker model: Hephaestus may use advertised
  Codex, Claude, GLM, DeepSeek, Gemini, or local session lanes, but it does not
  create an unbounded sub-agent swarm or bypass dependency joins/final gates.
- Added focused tests for successful packet execution, failure blocking,
  background result writing, route auto-run, non-pipeline skip behavior, and the
  `bin/hep-storm` terminal command.

## v0.7.10 - 2026-06-19

- Added the Builder Interview and Research Gate for `/hep-build`.
  Substantial single-agent, team-builder, and packager runs must now ask an
  8-12 question first batch before generating behavior.
- Made similar-agent/repository research and academic or professional theory
  research part of the minimum build contract, with no-match evidence required
  when direct comparables or domain-specific theory are unavailable.
- Added the domain-expert synthesis artifact so interview answers,
  comparable-agent research, theory, and tool/plugin selection are converted
  into concrete specialist prompt behavior before final role prompts are
  written.
- Added reusable templates for builder interviews, research dossiers,
  tool/plugin selection, domain-expert synthesis, prompt-performance contracts,
  and capability evaluation plans.
- Added `scripts/verify-builder-quality-contract.sh` and wired it into package
  verification so command adapters and builder docs cannot silently drop the
  interview/research/theory/synthesis requirements.
- Included the local GUI shortcut routing update so eligible Hub-only MCP
  routes can open local GUI surfaces instead of falling through generic routing.

## v0.7.9 - 2026-06-18

- Hardened installer command refresh for Claude, Codex, Gemini, Antigravity,
  Cursor, and OpenCode: stale command files and old symlinks are removed before
  the current command files are copied.
- This prevents older autocomplete entries such as `0-7-4` or retired
  `agentlas-*` support commands from surviving after an update.

## v0.7.8 - 2026-06-18

- Restored Super Ontology candidate-only sync invariants for consensus
  coordination and capability delegation authority: both remain AO
  runtime-enforced seed contracts, but public seeds cannot self-promote into
  runtime authority.
- `agentlas-architecture-sync` now passes again across public core, Web,
  Desktop/terminal, AppBridge, and Super Ontology candidate checks.

## v0.7.7 - 2026-06-18

- Added multilingual intent expansion for `/hep-search`, so broad
  Korean prompts such as "시장 리포트 써야 하는데 쓸만한 에이전트 찾아줘"
  retry with high-signal market/research/report tokens when the Hub asks for
  clarification or returns no candidates.
- Search sections now report fallback metadata and still include candidate
  descriptions and per-agent `why` explanations without invoking agents.

## v0.7.6 - 2026-06-18

- Added power-user `/hep-search` and `/hep-call` surfaces across
  Claude, Codex prompts, Gemini, Antigravity, Cursor, OpenCode, terminal, and
  the local MCP server.
- `hep-search` returns separate top-10 sections for the signed-in
  user's Agentlas Cloud packages and the public Agentlas Hub without invoking
  any agent.
- `hep-call` prepares exactly named Hub/cloud agent slugs as BYOM
  runtime bundles and writes receipts; the host runtime still owns execution.
- Clarified that `/hep-build ontology` is the local project
  knowledge/memory map, not the Hub marketplace search.
- Hardened the one-touch installer to prune stale visible command files,
  typo-command remnants, and old `0-7-4`/`0.7.4` plugin cache folders.

## v0.7.5 - 2026-06-18

- Moved the README first-run path to the top: copy-paste install prompt first,
  then the three commands, then example prompts.
- Updated the Agentlas web Hephaestus landing hero so the first visible product
  explanation is the three-command model: create, borrow, share.
- Pruned stale visible command surfaces from fresh installs and updates:
  `/hephaestus` and `/prompts:hephaestus` are no longer installed as chat
  autocomplete entries.
- Locked the Claude connector to command-only exposure: exactly
  `hep-build`, `hep-network`, and `hep-cloud`. This
  prevents broad root-folder scans from showing version folders such as
  `0-7-4`, and prevents duplicate command+skill entries for the same names.
- Tightened the installer to clear stale Claude/Codex plugin caches before
  reinstalling, so older internal skills such as `mode-classification` or
  `team-builder-packaging` stop appearing after a refresh and app restart.

## v0.7.3 - 2026-06-18

- Added the clearer three-command user surface:
  `/hep-build` for creation, `/hep-network` for borrowing public
  Hub agents, and `/hep-cloud` for using agents saved or shared through
  Agentlas Cloud. Legacy `/hephaestus` remains as a build alias.

## v0.7.2 - 2026-06-18

- Implemented the 0.7.2 Agent OS router surface: decisions now include
  `agent_os_router`, `task_force`, Local Operator `policy_decision`, and
  candidate-first `memory_playbook` metadata in both responses and receipts.
- Added Hub stage-wise temporary TF planning for composite Hub-only
  `/hep-network` requests while preserving the existing `hub_candidates`
  action for caller compatibility.
- Wired pipeline planning to prefer Agent Ontology `produces`/`consumes` graph
  paths when available, falling back to routing-card artifact contracts.
- Added a Memory/Playbook control-plane registry and candidate queues under the
  local networking home; the router still cannot write durable/global memory
  directly.
- Added terminal aliases `hephaestus hep-network` and the typo-tolerant
  `hephaestus hep-network` for the two-command user surface.
- Added the Stormbreaker execution fabric for Hephaestus Network `pipeline`
  decisions: required work packets, dependency groups, session hints, resume
  policy, and a final gate that blocks success until all required packets pass.
- Let MCP and CLI route callers pass a host session inventory so runtimes can
  schedule pipeline packets across active Codex, Claude, GLM, DeepSeek, Gemini,
  or local model sessions without moving execution into the router.
- Extended execution receipts with optional `pipeline_id`, `packet_id`,
  `session_id`, `parallel_group`, and parent receipt metadata.

## v0.7.1 - 2026-06-18

- Added the A2A Agent Card boundary: import external Agent Cards as pending
  alignment proposals, export public-safe cards at
  `/.well-known/agent-card.json`, and keep private/local fields out of public
  cards.
- Added caller-aware routing gates through CLI `route --caller` and MCP
  `hephaestus_route.caller_id`/`caller`, so agent-to-agent calls can be denied
  before a route is selected.
- Hardened A2A input handling: malformed JSON returns structured errors,
  non-object cards are rejected, and oversized skill lists are bounded.
- Made `ao lint` and `ao diff` return non-zero exits on invalid graphs or drift
  so CI and release gates cannot silently pass.
- Documented the architecture-sync handoff alongside the A2A upgrade and kept
  the broader ontology roadmap out of the release claim.

## v0.7.0 - 2026-06-16

- Published Hephaestus Stormbreaker as the robust execution contract with the
  v2 loop: scope lock, issue contract, failure memory, verifier-first plan,
  bounded evidence loop, adversarial review gate, outcome ledger, and final
  gate.
- Kept public benchmark claims inside the verified local operational robustness
  boundary.
