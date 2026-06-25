# Changelog

## Unreleased

## v0.7.25 - 2026-06-25

- **Self-contained `/hep-upload`.** Cloud and Hub uploads now use the bundled
  Hephaestus package/publish runtime instead of any private local checkout or
  external publish script. Hub uploads run through
  `bin/hephaestus publish <agent-folder> --visibility marketplace`; private
  Cloud uploads use `--visibility private-link`.
- **Public upload gates moved into Hephaestus.** The bundled uploader now
  validates marketplace `publicProfile` copy, `routing-card/2.0` readiness,
  static security, bundle size limits, and the server-compatible package hash
  before registration.
- **Routing-card hash repair.** Auto-migrated routing cards now get
  `agent_card_ref.content_hash` and `source.package_hash` instead of null
  placeholders, and the bundled meta-agent card is promoted to
  `routing_ready` with benchmark fixtures.

## v0.7.24 - 2026-06-25

- **Silent runtime auto-update.** `hep-network`, `hep-build`, `hep-search`,
  `hep-call`, and related slash/prompt command paths now start a fail-silent
  background update check at most once per day. If a newer GitHub release is
  available, Hephaestus installs it under `~/.agentlas/runtime/<version>` and
  moves `~/.agentlas/runtime/current` without blocking the user command.
- **Installed adapter refresh.** Runtime updates now refresh already-installed
  Claude, Codex, Gemini, Antigravity, Cursor, OpenCode, and AgentSkills
  command/skill adapters from the release tarball. Missing runtimes are left
  alone, so an update does not install tools the user never set up.
- **Opt-out remains explicit.** Auto-update is on by default for non-developer
  installs. Set `HEPHAESTUS_AUTO_UPDATE=0` to disable it; the existing
  `HEPHAESTUS_UPDATE_CHECK=0` switch is still respected.

## v0.7.23 - 2026-06-25

- **Agentlas native vs external LLM command boundary.** Agentlas Terminal and
  the Agentlas app are documented as plain-language native surfaces: users
  describe the task and the native Agentlas/Hephaestus tools choose the path.
  External LLM hosts keep the explicit six-command surface:
  `/hep-build`, `/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, and
  `/hep-upload`. Stormbreaker, research loadouts, and lower-level route options
  are attached by context instead of becoming more commands to memorize.
- **Agentlas Research Engine phase-0 core.** Added the public-safe research
  engine contract, CLI surfaces, and docs for detachable loadouts (`auto`,
  `safe`, `public-web`, `social`, `browser`, `full`, and `recommended`), with
  dependency-free built-in cartridges, SSRF-safe readers, receipt ledgers,
  search/read/gather/plan/status/proofs/verify flows, and credential guidance
  that exposes env names and setup commands without printing secret values.
- **Detachable public-page reader inspired by insane-search.** The adaptive
  `read.insane_fetch` cartridge is mounted only through `public-web`, `social`,
  `browser`, `full`, or explicit allow-lists. It records bounded route evidence
  for direct reads, Reddit RSS, Jina Reader fallback, metadata/feed parsing, and
  login/paywall hard stops, while keeping `insane-search` as a reader
  cartridge reference rather than the whole research engine.
- **Stormbreaker research evidence integration.** Stormbreaker packets can now
  attach research receipts, preflight files, readiness snapshots, capability
  summaries, recommendation metadata, and compact evidence-quality/coverage
  signals. The `recommended` research loadout resolves per packet from the
  original user request, so planning packets can choose `public-web` for public
  social/page research without mounting official social APIs or browser modules
  by default.

## v0.7.22 - 2026-06-24

- **Memory Relation Graph.** The local ontology runtime now links Memory Curator
  candidate tickets with typed edges (`similar_to`, `supersedes`, `contradicts`)
  so durable memory is a graph, not a flat list. `ontology memory dedup` scores
  candidate tickets by token overlap and records `similar_to` edges for near
  duplicates; `ontology memory decide <ticket> supersede --target <newer>` makes
  replacement structural by writing a `supersedes` edge from the newer ticket to
  the one it retires, so a new learning never silently overwrites an older one;
  `ontology memory graph <ticket>` returns a ticket with its incoming/outgoing
  edges and fails loud on an unknown ticket instead of returning an empty graph;
  `ontology memory link` records an edge by hand. `verify` now reports
  `memory_links`.
- **Stormbreaker Run Journal.** Long-horizon runs can write an append-only step
  ledger (start then complete/fail) so an interrupted run resumes instead of
  restarting. `agentlas-cloud stormbreaker journal status` reports the completed
  steps to skip and the first step to resume from; a loop guard trips a hard stop
  when one step keeps restarting without completing; `stormbreaker journal repair`
  seals interrupted (dangling) steps so a resumed run retries them rather than
  losing them; `stormbreaker journal verify` checks ledger integrity. Pure local,
  deterministic, no model calls.
- **Stormbreaker verifier-first gate and clarification interrupt.** A step can
  declare how it will be checked (`plan_step`) and record the result
  (`verify_step`); a step that completes without a passing check is reported as
  `unverified`. Ambiguity is recorded as a clarification request that marks the
  run `blocked` until it is resolved, so the run pauses instead of guessing.
  `agentlas-cloud stormbreaker journal gate` returns one ok/blockers verdict that
  refuses to call a run done while anything is dangling, looping, failed,
  awaiting an answer, or completed-but-unverified, so an agent cannot claim
  success before the checks pass.

## v0.7.21 - 2026-06-22

- Added the public value-free credential request contract for borrowed
  agents and plugins: provider, env name, allowed hosts, allowed operations,
  scope, setup URL, input mode, save target, and broker mode may be indexed
  without storing secret values.
- Clarified that `brokerMode: host-bound-broker` requires a real local
  process/IPC boundary, while `runtime-env-injection` remains a compatibility
  path and must not be represented as full broker isolation.
- Updated auto-activation, source-of-truth, runtime boundary, schema, and
  project-memory templates so local Desktop/terminal runtimes own secure GUI,
  OS keychain/vault storage, masked previews, and future host-bound broker
  enforcement.

## v0.7.20 - 2026-06-22

- Aligned Hub-facing language around Agents, Teams, and Plugins so public
  surfaces show invocation credits separately from downloadable packages.
- Kept local `trusted` routing-card behavior as the local-first Network
  trust path while keeping upload and Hub publication security review as a
  separate gate.
- Removed developer-local package bucket label leakage from routing docs,
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
  and launches its packaged GUI even when the developer's local `private` folder is not
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
