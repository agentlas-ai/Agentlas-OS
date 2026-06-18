# Changelog

## Unreleased

- No unreleased changes yet.

## v0.7.2 - 2026-06-18

- Implemented the 0.7.2 Agent OS router surface: decisions now include
  `agent_os_router`, `task_force`, Local Operator `policy_decision`, and
  candidate-first `memory_playbook` metadata in both responses and receipts.
- Added Hub stage-wise temporary TF planning for composite Hub-only
  `/hephaestus-network` requests while preserving the existing `hub_candidates`
  action for caller compatibility.
- Wired pipeline planning to prefer Agent Ontology `produces`/`consumes` graph
  paths when available, falling back to routing-card artifact contracts.
- Added a Memory/Playbook control-plane registry and candidate queues under the
  local networking home; the router still cannot write durable/global memory
  directly.
- Added terminal aliases `hephaestus hephaestus-network` and the typo-tolerant
  `hephaestus hephaests-network` for the two-command user surface.
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
