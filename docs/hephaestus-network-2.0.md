# Hephaestus Network 2.0

Local-first Agent OS routing: call Hephaestus from any major AI runtime, route
natural-language requests to local agents/teams/plugins or Agentlas Hub
candidates, form a temporary task force for composite work, and keep
user/project memory on the local machine unless the operator explicitly exports
it.

## What you get

- Agentlas-native surfaces (Agentlas Terminal and the Agentlas app) accept plain
  language and infer the native Agentlas/Hephaestus tool path without requiring
  a `/hep-*` command.
- Six explicit external commands in Claude Code, Codex, Gemini CLI,
  Antigravity, Cursor, and OpenCode: `/hep-build`, `/hep-network`,
  `/hep-cloud`, `/hep-search`, `/hep-call`, and `/hep-upload`. Stormbreaker,
  research loadouts, and lower-level route options are attached automatically
  from context.
- A visible command surface where `/hep-build` creates and repairs agents,
  `/hep-network` borrows public Hub agents into temporary task forces,
  `/hep-cloud` uses agents saved or shared through the signed-in user's
  Agentlas Cloud, `/hep-search` compares Cloud/Hub candidates without invoking,
  `/hep-call` prepares exact named agents, and `/hep-upload` gates Cloud-vs-Hub
  upload decisions.
- On Agentlas Web and connector surfaces, signed-in `/hep-network` resolves
  remote candidates in this order: the user's own Agent Cloud packages, saved
  Hub bookmarks, then public Hub. `/hep-cloud` remains owner Cloud only.
- A global, local-only structure at `~/.agentlas/networking/`:
  `cards/` (routing cards), `policies/`, `memory/` (routing preferences only),
  `ledgers/` (routing receipts, executions, capability grants), `cache/`,
  `registry.sqlite` (rebuildable index), `sources.json`, `config.json`.
- Routing receipts for every decision. The router selects agents or Hub bundles
  first; terminal `hep-network` then auto-runs only when the decision
  contains a runnable Stormbreaker `execution_fabric`. Use `--plan-only` to
  force routing-only output.
- Local Operator Mode policy labels: most super-ontology signals become
  `allow`, `allow_with_label`, `auto_redact`, or `candidate_only`. Human
  approval is reserved for real external export, global promotion, or
  irreversible execution handled by the host runtime.

## Core rules

1. **Local first.** Explicit commands → project overrides
   (`.agentlas/routing-overrides.json`) → local routing cards → only then the
   Hub.
2. **Memory stays local.** Agent capability can come from the Hub; your
   user/project memory never leaves the machine unless you explicitly approve
   an export. Hub searches send redacted keywords, never raw prompts.
   Agentlas Web personalization is a separate workspace-scoped Cloud record:
   promoted memory summaries, promoted playbook cards, plugin locks, retrieval
   receipts, and self-evolution proposals for Cloud/Hub bundles. It is never a
   raw prompt, transcript, secret, credential value, or private local file
   archive.
3. **No card, no auto-routing.** A card below `routing_ready` can appear in
   search results but is never auto-executed. Malformed cards are quarantined
   individually.
4. **No home-folder scans.** Only paths you registered
   (`hephaestus network add-source <path>`), installed plugin caches, and
   known `.agentlas` package folders are indexed.

## Routing cards

Every agent, team, and plugin ships `.agentlas/routing-card.json`
(`schemas/routing-card.schema.json`). `routing_ready` requires at least:
5 trigger examples (with both Korean and English coverage), 3 anti-triggers,
verb-form capabilities, declared required inputs, a risk profile, validated
entrypoints, declared memory behavior, and 10 routing benchmark cases.
`hephaestus cards lint` reports the gates; `hephaestus cards migrate` creates
draft cards from existing packages.

Status lifecycle: `draft → searchable → candidate → routing_ready → trusted`.

## Commands

```bash
hephaestus network init          # create/migrate ~/.agentlas/networking (idempotent; runs on install)
hephaestus network status        # card counts, benchmark state, auto-routing gate
hephaestus network add-source <path>
hephaestus network reindex
hephaestus network bench         # routing quality benchmark (gates auto-routing)
hephaestus network grant <capability> --target <id> --scope per_call|session|project|global  # legacy ledger helper
hephaestus cards lint [path]
hephaestus cards migrate <root> --tier free|paid|plugin|local
hephaestus route "<request>"     # or just: hephaestus "<request>"
hephaestus hep-build "<request>"     # build/create/package surface
hephaestus hep-network "<request>"   # Hub-only Network surface; auto-runs runnable pipeline fabrics
hephaestus hep-network "<request>" --plan-only   # route/plan only
hep-storm "<request>" --background   # route + auto-run Stormbreaker packets
hep-search "<request>"               # show cloud + Hub candidates only
hep-call "agent-a,agent-b" "<ctx>"    # prepare exact named agents
hep-upload <agent-folder>            # ask private Cloud vs public Hub first
hep-build "<request>"     # human-facing build alias
hep-search "<request>"    # human-facing search alias
hep-call "agent-a,agent-b" "<ctx>"    # human-facing call alias
hep-network "<request>"    # standalone Hub-only Network alias
```

Lower-level automation/debug helpers such as `hep-storm` may exist on disk for
native tool selection and test harnesses, but they are not part of the visible
external LLM command set.

## Decisions the router can return

| action | meaning |
|--------|---------|
| `route` | confident local match |
| `pipeline` | plan-anchored composite request ("기획부터 구현, QA까지") — a multi-team stage plan chained by Agent Ontology or card `produces`/`consumes` artifact contracts; includes a Stormbreaker `execution_fabric` so host runtimes can run independent packets across active sessions and block success until every required packet passes |
| `clarify` | low confidence or ambiguous local match — answer the question to continue |
| `hub_fallback` / `hub_candidates` | no local match or Hub-only mode; Hub lookup used redacted keywords only. Composite Hub-only requests include a `task_force` with stage-level Hub candidates |
| `propose_new` | nothing matched locally or on the Hub — build a new agent with `/hep-build` |
| `refuse` | loop guard or another technical guard; the reason is in `reasons` |

Every decision writes a receipt to
`~/.agentlas/networking/ledgers/routing-decisions.jsonl` with normalized,
redacted tokens — never the raw prompt.

0.7.3 receipts also carry:

- `agent_os_router`: the primary command surface and router version.
- `task_force`: single-agent route, local pipeline, or Hub stage candidates.
- `policy_decision`: Local Operator Mode labels such as `auto_redact` or
  `candidate_only`.
- `memory_playbook`: candidate-first operational memory/playbook notes. The
  router never writes durable/global memory directly.

On Agentlas Web, runtime bundle preparation can also include:

- `personalization.binding`: `workspaceId + sourceScope + baseAgentId`, with
  package compatibility checked by `packageHash`.
- `personalization.memoryItems`: promoted, bounded summaries only.
- `personalization.playbookCards`: promoted recipes selected by task context.
- `personalization.pluginLocks`: resolved plugin slug/version/permission state.
- `personalization.retrievalReceiptId`: audit id for exactly what was included.

Candidate write tools are explicit: `agentlas.record_agent_memory`,
`agentlas.record_agent_playbook`, and `agentlas.propose_agent_evolution`.
They save candidates only. Promotion remains curator/user-policy controlled.

## Benchmarks gate quality claims

`hephaestus network bench` measures top-1 accuracy, top-3 recall, clarify
rate, unsafe route rate, wrong plugin attachment rate, latency, Hub fallback
correctness, and Korean/English coverage. Auto-routing is reported as enabled
only when enough `routing_ready` cards exist **and** the benchmark passes
(top-3 recall ≥ 0.9, zero unsafe routes in the privacy suite).

## Execution robustness is a separate gate

The Network benchmark answers "did Hephaestus choose the right route?" It does
not prove that the selected agent finished the user's work correctly.

Use `docs/robustness-protocol.md` for the execution contract after routing and
`docs/robustness-eval.md` for the three-way comparison:

1. Codex native, no skills and no agent calls.
2. Existing Hephaestus Network with agent or Hub calls.
3. Hephaestus Network plus Robustness Protocol gates.

For `pipeline` decisions, the returned JSON includes `execution_fabric`:
required work packets, dependency groups, session hints, and a resume/final-gate
policy. The fabric and every `hep-storm` result also include the canonical
`execution_harness`; hosts must apply its `system_prompt` verbatim and retain
its `prompt_sha256` instead of redefining Goal mode or UltraCode mode.
`hep-storm` consumes that fabric, launches local packet workers
by parallel group, records per-packet receipts, and blocks a
success claim until the required packet list is complete. External Codex,
Claude, GLM, DeepSeek, Gemini, or local-model sessions are attached through an
explicit executor adapter (`--executor-command`) or host runtime integration;
without an executor the runner only materializes auditable handoff artifacts,
returns `status: materialized`, and keeps `final_gate.can_report_success` false.
Use `--background` when the product surface should return immediately while the
runner completes packets and writes `.agentlas/stormbreaker/background/<run_id>/result.json`.
Terminal `hep-network` uses this runner automatically for decisions that
already contain a runnable `execution_fabric`; non-runnable Hub candidates,
clarify results, and single-agent routes are returned as routing decisions.
The runner is elastic but bounded: pass `--session-inventory` or set
`AGENTLAS_SESSION_INVENTORY` to advertise
available Codex/Claude/GLM/DeepSeek/Gemini/local sessions and `--max-workers`
to cap concurrent packet workers. Hephaestus never starts an unbounded swarm.

When an Agent Ontology graph is present, pipeline planning first tries the AO
`produces`/`consumes` graph and records the resulting `graph_path`. Card-level
`produces`/`consumes` planning remains the fallback for projects that have not
materialized AO yet.

The first recommended topic is public agent repo repair. It is intentionally
file-heavy, validation-heavy, and safety-sensitive, so false completion and
scope drift are visible in deterministic verifier output.
