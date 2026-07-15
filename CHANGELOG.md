# Changelog

## v1.1.30 - 2026-07-15

- **Agent experience memory now uses one governed local retrieval path.** Agent
  learning is stored in per-agent SQLite projections, fused through semantic
  and lexical RRF with salience as a prior, and loaded adaptively: all relevant
  memories when they fit the context budget, otherwise bounded top-k. Scope,
  expiry, redaction, and explicit supersession remain filtering authority.
- **The default semantic adapter is a bundled, verified Model2Vec hybrid.** The
  offline `potion-base-8M` int8 asset is pinned by model revision and content
  digest, combined with the deterministic hash adapter into a 352-dimensional
  local vector, and rejected on asset drift. CJK retrieval applies an absolute
  and relative semantic gate so unrelated high-baseline vectors cannot enter
  context. No server embedding call or per-user embedding charge is introduced.
- **Plain host sessions receive the same local recall without invoking an agent
  first.** Merge-safe Claude Code, Codex, Antigravity, Grok, and OpenCode
  adapters inject bounded capsules while excluding native policy files and
  failing open when local memory is unavailable. The one-touch installer also
  recognizes the live `~/.gemini/antigravity-cli` marker without writing
  workflows into that private state directory.
- **Borrowed agents no longer consume a concatenated nest file.** Cross-project
  grounding resolves the normalized agent slug to its private experience
  database and queries the ontology runtime, preserving structured provenance,
  relations, and governance across projects.

## v1.1.29 - 2026-07-15

- **Every `/hep-build` host now ends with an explicit private-Cloud choice.**
  Claude Code, Codex, Gemini, and Antigravity ask whether to save the verified
  package owner-private in Agent Cloud or keep it only on this computer.
  Missing/non-interactive input stays local, public Hub publication is never
  inferred, and a failed Cloud save leaves the local package intact. Copy also
  states the real Mobile boundary: another Desktop must restore/install the
  package before its paired Mobile can use that Desktop to run it.
- **Fresh host interviews now default consistently to English.** Korean remains
  an explicit locale, and the canonical interview directive, lens table, and
  scoring prompt are synchronized into both Claude and Codex plugin mirrors so
  host adapters cannot silently disagree.

## v1.1.28 - 2026-07-14

- **Plugin first contact now installs the real project architecture before
  routing.** `hep-network`, owner Cloud, and Storm calls from Codex, Claude
  Code, Gemini, Cursor, OpenCode, Antigravity, and other named host runtimes
  synchronously use Core's one `ensure_project` implementation. The local MCP
  server enables its separate host gate when it starts and may initialize only
  its exact current workspace when that folder has not been put under Git yet.
- **Private Agentlas state is protected before agent work.** Core installs the
  full merge-only `.agentlas/` ignore block before memory, code map, ontology,
  and CareerGraph files; a plugin call is blocked if that privacy or permission
  contract is incomplete. Intentionally public, already tracked `.agentlas`
  contracts remain merge-only and are reported as an explicit privacy warning;
  Core never rewrites the user's Git index. Ordinary terminal read-only
  commands remain non-mutating.

## v1.1.27 - 2026-07-14

- **Windows first-contact setup now completes through the canonical Core.**
  Windows ACLs, not synthetic POSIX group/world mode bits, govern local file
  access. Core no longer turns those meaningless mode bits into a false
  `privacy_warning`, so Desktop and Terminal retain the same Core-owned
  project soul, code map, memory, ontology, Career Graph, and `.gitignore`
  bootstrap on Windows. POSIX hosts still enforce owner-only `0700`/`0600`
  modes, and all hosts retain symlink, bounded-scan, tracked-sensitive, and
  merge-only guards.

## v1.1.26 - 2026-07-14

- **Project Foundation no longer treats read access as write consent.** Passive
  search, call, route, Storm, and MCP requests leave the working folder
  untouched by default. Explicit activation remains available, while automatic
  activation requires a trusted host opt-in, an allowed root, and a recognized
  workspace marker; MCP uses a separate default-off gate.
- **Bootstrap scans and receipts are bounded and private.** Core enforces
  no-follow project boundaries, file/count/time/read/output budgets, private
  permissions, advisory locking, atomic writes, and refresh fingerprints. MCP
  and automatic receipts report counts and stable reason codes instead of
  absolute local paths or raw filesystem errors.
- **Existing project state stays merge-only under failure.** Oversized or
  incomplete Git listings defer map refresh instead of replacing a known-good
  map, managed ignore rules are read through a bounded regular-file path, and
  tracked-sensitive scans fail closed when their own budgets are exceeded.
- **Clean checkouts keep Agent OS inspection live without generating files.**
  If the ignored AO materialized view is absent, Core derives the graph in
  memory from tracked project contracts; pack, scheduler, and filesystem checks
  therefore work read-only. Explicit OKF export now creates its requested
  output directory even when the graph is empty.

## v1.1.25 - 2026-07-14

- **Runtime release reconciliation is idempotent on macOS Bash 3.2.** A release
  whose two digest-verified assets already exist now completes the final
  verification pass instead of tripping over an empty missing-assets array.

## v1.1.24 - 2026-07-14

- **Every host now receives the same Core-owned project bootstrap on first
  contact.** Desktop, Terminal, Claude Code, Codex, MCP, Network, Cloud, and
  Storm initialize the project soul, memory map, code map, ontology, career
  graph, and privacy-first `.gitignore` contract through one idempotent Core
  command. Existing project files are merge-only and never overwritten.
- **Local Agentlas state is private before it is written.** The bootstrap
  installs managed ignore rules before creating `.agentlas` memory, code-map,
  ontology, career, Stormbreaker, and pipeline state, and reports already
  tracked sensitive paths without rewriting the Git index.
- **Model allocation no longer carries provider- or model-name fallbacks.**
  The parent AI chooses an exact ID from live host-advertised inventory and the host
  enforces capability, trust, capacity, explicit pins, and cost constraints;
  Core does not encode vendor aliases, provider-family preference bonuses, or
  lexical tie-breaking between ambiguous live candidates.

## v1.1.23 - 2026-07-13

- **Runtime updates now refresh every installed Storm adapter.** Existing
  `hep-storm` command files and `hephaestus-storm` skill directories for
  Claude Code, Codex, Cursor, OpenCode, Gemini, Antigravity, OpenClaw, and
  Hermes are synchronized from the newly verified Core release alongside the
  older Hephaestus adapters. Custom `CODEX_HOME` locations are honored too, so
  Core remains the only harness owner after an in-place runtime update.

## v1.1.22 - 2026-07-13

- **One byte-identical Goal + UltraCode harness across every supported host.**
  Core remains the only prompt owner; the universal AgentSkills package plus
  Codex, Claude Code, Gemini, Antigravity, Cursor, OpenCode, OpenClaw, Hermes,
  Agentlas Desktop, and Agentlas Terminal now load the same digest-addressed
  `system_prompt` and fail closed on any SHA-256 mismatch instead of keeping a
  host-local copy.
- **Cross-platform execution is now a release gate.** Native macOS/Linux shell
  wrappers and the Windows `.cmd` entry point are exercised across Python 3.9,
  3.12, and 3.13. Every matrix job uploads its harness bytes and a final gate
  rejects the release unless all nine proofs match exactly.
- **Windows background and packet execution no longer share the host console.**
  Stormbreaker isolates its detached launcher, packet executors, goal checks,
  and real CLI integration boundaries while preserving durable result files,
  preventing delayed console control events from interrupting Codex, Claude
  Code, Desktop, Terminal, or their CI host.

## v1.1.21 - 2026-07-13

- **Native hosts now load the canonical harness directly from Core.** The new
  `hephaestus stormbreaker harness` JSON command exports the complete,
  digest-addressed Goal + UltraCode contract without routing or execution.
  Agentlas Desktop and Agentlas Terminal verify the returned SHA-256 digest,
  apply `system_prompt` verbatim to planning, workers, and synthesis, and fail
  closed instead of falling back to host-local Goal/UltraCode prompt variants.

## v1.1.20 - 2026-07-13

- **One Core-owned Goal + UltraCode harness on every runtime.** Stormbreaker now
  emits a canonical, digest-addressed `execution_harness` in every result,
  execution fabric, packet contract, and external-executor environment. Codex,
  Claude Code, Gemini, Antigravity, Cursor, OpenCode, OpenClaw, Hermes, and the
  universal AgentSkills adapter consume the returned prompt verbatim instead of
  maintaining host-local Goal/UltraCode variants. Live sessions can be supplied
  with `--session-inventory` or `AGENTLAS_SESSION_INVENTORY`; the explicit
  `host:primary` fallback never invents workers or model IDs.
- **Materialization no longer masquerades as completion.** A Stormbreaker run
  without a real executor returns `status: materialized`, leaves
  `final_gate.can_report_success` false, and still exits successfully so the
  host can execute the complete packet set. Only verified executor results can
  produce `status: completed`.

## v1.1.19 - 2026-07-13

- **Experience and Taste are portable assets, separate from the base agent.**
  Exact-release schemas now cover Experience Packs, references-only Variants,
  Taste/Style releases, evidence receipts, privacy filtering, taxonomy, and a
  rebuildable relation index. Raw prompts, transcripts, credentials, local
  paths, and base-package bytes are excluded from publishable assets.
- **MCP resolution is system-global-first and consent-gated.** Packages declare
  value-free capability requirements, while the trusted host owns executable
  definitions and key presence. Missing or failed MCPs are isolated per
  capability, ordered alternatives are tried, and a tool-free degraded path
  remains valid instead of causing an agent-wide shortage.
- **Model allocation separates AI judgment from host enforcement.** A parent AI
  may request a provider-neutral tier and effort, but the host applies actual
  inventory, explicit pins, context support, cost ceilings, and independent
  verification requirements before recording a privacy-safe receipt.

## v1.1.14 - 2026-07-11

- **Name-only matches no longer become confident routes.** Agent and team names
  remain useful recall signals, but a match supported by no trigger,
  capability, summary, or domain evidence is now capped just below the direct
  routing threshold and sent through candidate re-ranking. Substantive matches
  retain their existing scores, with dedicated regression tests for both paths.
- **Release gates now reproduce a clean installation.** The ontology graph is
  materialized before lint/diff tests, one-touch verification accepts optional
  runtimes while still requiring all five core installs and zero failures, and
  the pre-tag package, public-safety, adapter-sync, and ontology gates now pass
  from a clean checkout.

## v1.1.13 - 2026-07-11

- **Local registrations reach the Agentlas Desktop library automatically.**
  `card_store.save_card` now hands off every completed local registration
  (`trusted` + `local/*` card with a real absolute-path package folder) to a
  desktop import queue at `~/.agentlas/networking/desktop-sync/pending/`.
  Because every runtime copy (Claude plugin, Codex plugin, terminal runtime,
  desktop-vendored engine) funnels card writes through this single choke
  point, an agent built anywhere now shows up in the desktop app without a
  manual import. The gate is strict by design: `routing_ready` forge
  experiment cards and relative/stale source refs never qualify, and the
  handoff is best-effort — registration never fails because the desktop
  queue could not be written. Drained entries record a `content_hash` in
  `desktop-sync/done/` so an unchanged card is not re-enqueued.

## v1.1.12 - 2026-07-10

- **Verified, rollback-safe runtime updates.** The updater now installs only the
  tag-specific GitHub release asset whose SHA-256 digest and size are published
  in release metadata. Archives are extracted without link traversal, staged and
  health-checked before activation, and rolled back if the new runtime cannot
  start. Stale update locks recover safely without deleting another process's
  live lock.
- **SemVer-correct release selection.** Stable, prerelease, and build-metadata
  versions now follow SemVer 2.0 precedence instead of digit scraping, preventing
  a prerelease from replacing a newer stable runtime.
- **Current Codex plugin compatibility.** The bundled skills path is explicitly
  relative, and the installer removes the retired remote-MCP feature flag that
  strict current Codex builds reject while preserving the user's other settings.

## v1.1.11 - 2026-07-09

- **24h lease ("call once, hired for a day") passthrough.** `hub_invocation`
  now normalizes the Hub's server-reported lease block, caches a display copy
  at `~/.agentlas/networking/leases.json`, records lease state on execution
  receipts, and injects the lease status plus a presence badge (`🔗 <agent>`)
  into the executing model's runtime contract. Older servers without a lease
  block keep the exact previous behavior.
- **Agentlas Career Graph runtime.** New `career_graph/` package and
  `bin/career-graph` (`ingest / query / trace / verify / public-card`,
  `hephaestus career-graph ...` dispatch): a rebuildable SQLite index over the
  project's canonical Markdown/JSONL ledgers (memory, sitemap, code map, run
  journals, receipts, evolution proposals) with promoted `FailureSignature`,
  `PlaybookCandidate`, and `EvolutionProposal` nodes. Project-scoped by
  default; `--include-networking-home` additionally indexes the global
  routing/execution ledgers (lease-bearing receipts are preserved on
  `ExecutionReceipt` payloads — covered by a regression test).
- **Redacted public career card on upload.** `hep-upload` packaging
  auto-generates `.agentlas/public-career-card.json` for opted-in projects and
  validates it (counts-only aggregate, privacy flags forced false, local
  absolute paths rejected) before attaching it to `manifest.careerGraph` /
  `bundle.careerGraph`.

## v1.1.10 - 2026-07-07

- **Router no longer crashes on list-form `locale_coverage` cards.** Routing
  a Korean query against a card whose `locale_coverage` was a bare locale
  list (e.g. `["ko", "en"]`) instead of the migrated dict shape raised
  `AttributeError: 'list' object has no attribute 'get'` and killed the
  whole `/hep-storm` / `route` run. The scorer now accepts both shapes.
  This was previously hot-patched only into the installed 1.1.5 runtime and
  regressed on update; the fix is now in the canonical source with a
  regression test.
- **`hep-browser` automation contract.** URL requests with an explicit action
  now drive the Agentlas browser hardpoint through `open -> chat -> snapshot`
  instead of stopping at a read-only page snapshot. Use
  `hep-browser <url> "click the CTA"` or `--act "<instruction>"`; pass
  `--read` to force the old snapshot-only behavior. CDP/profile flags can be
  forwarded to `agent-browser` for Desktop/browser attach flows.
- **`hep-browser` Desktop CDP attach and primitive clicks.** When the Agentlas
  Browser CDP port is already live, `hep-browser` now attaches to it by default
  instead of silently launching a fresh automation profile. Read and primitive
  modes both forward CDP/profile flags. `--click` and `--click-text` provide
  LLM-free browser primitives for host-selected refs and visible text, with
  `--wait-ms` for dynamic app UI before the final snapshot.
- **Human-facing app URLs.** `hep-browser` now prefers human entry URLs for
  known browser apps such as Gmail, rewriting automation shell URLs like
  `https://mail.google.com/mail/u/0/#inbox` to `https://mail.google.com/`.
  `--raw-url` keeps the exact URL when a deep route is intentional.

## v1.1.8 - 2026-07-07

- **`hep-browser` browser hardpoint surface.** Added the short
  `hep-browser <url-or-query>` shell command plus `/hep-browser` and
  `/prompts:hep-browser` host adapters for browser-required work. URL reads now
  go straight through the Agentlas browser hardpoint (`browser.agent_cli`), with
  `hep-browser --setup` and `hep-browser --check` covering first-run setup and
  proof.
- **Agentlas browser first routing.** Browser-needed recommendations now select
  the `browser` research loadout and suggest `bin/hep-browser '<query>'`.
  Browser hardpoint candidate ordering and loadout metadata put
  `browser.agent_cli` ahead of other optional browser bridges, while ordinary
  deep research still preserves the static-reader plus browser-read behavior.
- **Install and release parity.** Registered `hep-browser` across Claude Code,
  Codex, Gemini, Antigravity, Cursor, OpenCode, terminal shims, global command
  metadata, manifests, and release verifiers so newly installed runtimes receive
  the same browser command surface.

## v1.1.7 - 2026-07-07

- **Global router prompt installer (`hep-global`).** Added
  `hephaestus global install|status|remove` plus the short `hep-global`
  shell shim. The installer writes a managed marker block into
  `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, and `~/.gemini/GEMINI.md` so
  ordinary Codex, Claude Code, and Antigravity/Gemini prompts can route through
  Network, Cloud, local agents, then local skills, while respecting signed-in
  Hub credit gates and naming final workers instead of router commands in
  status lines. The block is idempotent, removable, and backed up before edits.
- **Install docs for global routing.** README, Korean README, and runtime
  adapter docs now describe the optional `hep-global install` flow and the
  `HEPHAESTUS_INSTALL_GLOBAL_ROUTER=1` one-touch installer opt-in.
- **Quickstart install moved above the demo media.** The README and Korean
  README now put the one-line installer in the first viewport, with the optional
  global-router opt-in directly beside it.
- **Antigravity global router support.** `hep-global --target antigravity`
  installs the same routing priority block into `~/.gemini/GEMINI.md`, matching
  Antigravity's existing global `/hep-*` workflow install surface.

## v1.1.6 - 2026-07-07

- **Enterprise upload content-safety gate (`hep-upload`).** Hardened the cloud
  upload sanitizer against malicious agent packages. A new
  `agentlas_cloud/content_guard.py` defeats modern prompt-injection obfuscation
  — Cyrillic/Greek homoglyphs, leetspeak, zero-width and bidi characters,
  Unicode Tag-block smuggling, separated-letter tricks, and injections split
  across lines — by scanning a normalized detection shadow plus a multi-line
  window. Detection is multilingual (English, Korean, Chinese/Japanese, and
  major European languages) and now covers secret-exfiltration beacons and
  high-value credential access. Verified against 139 adversarial attack vectors
  across ~25 evasion families: 100% of malicious lines are stripped.
- **Quality preservation over blind deletion.** The gate is two-tier: only
  high-confidence attacker directives are removed line-by-line, while ambiguous,
  negated, quoted, or descriptive matches (security-training, prompt-engineering,
  and devops-docs agents that legitimately mention these terms) are kept and
  flagged for review, not deleted. Zero false positives across 35 realistic
  benign agent samples. Packages still publish (`ready`) with the offending
  lines removed rather than being hard-blocked.

## v1.1.5 - 2026-07-05

- **`hephaestus update` `/hep-storm` install parity.** Fixed the one-touch
  installer so `/hep-storm` is actually refreshed into every global runtime
  surface it documents: Claude Code, Codex custom prompts, Gemini fallback
  commands, Antigravity workflows, Cursor/OpenCode commands, and the
  `hephaestus-storm` AgentSkill for `.agents`, OpenClaw, Hermes, and Cursor.
  This closes the gap where the repo and plugin cache had Stormbreaker, but
  fresh host sessions could still miss the visible command.
- **Latest-release alignment.** Publishes the Stormbreaker command surface as a
  new public release so `hephaestus update` and `update --check` can discover it
  from GitHub latest instead of stopping at v1.1.1.
- **Shell command shim.** The installer now links `hephaestus` into
  `~/.local/bin` when possible and the one-touch verifier proves the short
  `hephaestus update --check` command works, not only the full runtime path.
- **Package verifier parity.** The public package verifier now treats
  `hephaestus-storm` as an expected shipped skill, so release verification and
  the installed command surface agree.

## v1.1.2 - 2026-07-05

- **`/hep-storm` Stormbreaker loop surface.** Promoted the Stormbreaker
  auto-runner from a terminal-only alias to a first-class global command across
  every runtime (Claude Code `/hep-storm`, Codex `/prompts:hep-storm`, Gemini,
  Antigravity, Cursor, OpenCode, plus OpenClaw / Hermes / `.agents` skills). It
  routes the goal, materializes a verified pipeline fabric, then the host model
  executes it under the verifier-first, no-fake-pass Stormbreaker Loop protocol
  (scope-lock → issue contract → plan-lock → act → verify → bounded repair/retry
  → final-gate) with the goal-loop stability invariants (no stall, no runaway,
  journal-resumable). Registered in `.agentlas/global-commands.json`,
  `manifest.json`, the global-command contract, and the contract verifier.
- **`/hep-connect` command-surface contract.** Fixed the four `hep-connect`
  surfaces to open their body with the standard update-fallback line, restoring
  the `test_all_hep_command_surfaces_start_body_with_update_fallback_line`
  contract test.

## v1.1.1 - 2026-07-05

- **Telegram gateway contract.** Added the gateway channel schema, template,
  verification script, and architecture note for binding single agents,
  orchestrators, or teams to Telegram without treating the bot account as the
  agent itself.
- **`/hep-connect` surface.** Added Claude Code, Codex, and Agentlas workflow
  entrypoints that point operators to the Desktop Connect flow, require a real
  paired chat and test message, and keep bot tokens out of normal chat.
- **Copy pass through No-AI-Slop.** Tightened Telegram setup language around
  receipts, session boundaries, local secret storage, and actionable failure
  states.

## v1.1.0 - 2026-07-02

- **Briefing interview engine.** New `agentlas_cloud/interview/` package:
  Work Brief schema (`work-brief/1.0`), deterministic ambiguity composition
  with numeric stop gates (threshold 0.2, per-dimension floors, 2-round
  stability streak), a four-group lens table with per-surface question
  budgets (trivial asks get zero questions), and a host-executed interview
  directive. The engine never calls a model (BYOC).
- **Work Brief rides the pipeline.** `plan_pipeline(brief=...)` extends stage
  detection with the confirmed goal/acceptance text and relaxes the
  plan-anchored guard for scoped briefs; the Stormbreaker runner injects the
  brief into every packet contract; `route --brief <path|dir>` loads
  `.agentlas/work-brief.json`.
- **Interview-confirmed routing cards.** `cards migrate` consumes the Work
  Brief as its first-choice source: anti_scope becomes anti_triggers verbatim
  and the confirmed goal/acceptance become trigger examples.
- **Builder gate upgraded.** The Builder Interview and Research Gate and all
  hep-build command surfaces now specify lens-driven questions (anti-scope /
  done-signal / stop-criterion required), the numeric stop rule, a coverage
  check, and a one-sentence goal restate before generation.
- **README repositioned.** Full rewrite around the model-neutral Agent OS
  positioning: OS-subsystem mapping, enterprise governance posture, and the
  v1.1.0 interview engine. Framework-alternative comparisons removed.
- Includes the v1.0.5 router discrimination patches (hub_candidates Router
  Agent escalation, brand-token generic list, bridged Hub query tokens) in the
  canonical release line.

## v1.0.5 - 2026-07-01

- **Borrow every explicitly named agent.** When the operator names multiple
  specialists in one request ("웹마스터 카피라이터 불러서 …"), the network router
  now borrows all of them instead of collapsing to the single top-ranked Hub
  candidate. Matching is by the operator's own words against each candidate's
  name, so an off-domain agent the Hub lexically over-ranks no longer wins over
  an agent the operator actually named (`_explicitly_named_borrowables`).
- **Temporary orchestrator for multi-specialist borrows.** A request that names
  two or more specialists now returns `formation: temporary_orchestrator` and a
  directive that puts the executing model in the manager seat — plan the split,
  dispatch each named agent grounded in the project, then synthesize their
  outputs into one deliverable instead of running them in isolation.
- **Router fix mirrored into host bundles.** Root runtime + Claude Code/Codex
  plugin bundles all carry the same change so packaged hosts do not drift back.

## v1.0.4 - 2026-06-30

- **Plugins no longer route as agents.** The local/network router now removes
  `type: plugin` cards and `plugin/*` ids from the user-facing route pool before
  scoring, so a generic lexical match cannot recommend tools such as
  `plugin/shopify-dev` as if they were runnable agents. Plugins remain available
  to agents through `required_plugins`.
- **Plugin exclusion is mirrored into host bundles.** The root runtime and the
  mirrored Claude Code/Codex plugin bundles carry the same router fix, preventing
  packaged hosts from drifting back to the stale route behavior.
- **Release metadata moved to v1.0.4.** Runtime manifests, plugin package
  manifests, one-touch install defaults, global command install refs, and tests
  now point at v1.0.4 so desktop bundles and CLI installs can use the same
  tagged engine.

## v1.0.3 - 2026-06-30

- **Release metadata and docs synced.** Runtime manifests, MCP server metadata,
  plugin package manifests, one-touch install defaults, Codex install docs, and
  tests now consistently point at v1.0.3 so new installs and update checks no
  longer straddle the v1.0.2 tag.
- **README release notes corrected.** The top-level English and Korean READMEs
  now describe the current release line instead of showing the older 100K
  routing copy under the latest patch heading.
- **Plugin mirrors stay aligned.** The mirrored Claude Code and Codex plugin
  bundles carry the same v1.0.3 metadata as the root runtime.

## v1.0.2 - 2026-06-29

- **Antigravity workflow surface fixed.** The Antigravity global workflows
  (`/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, `/hep-upload`) were
  the only runtime adapter shipping without YAML frontmatter and with a
  prose-only recipe instead of a runnable command block, so the host model had
  no deterministic command to run and would improvise (fabricated PATH/git
  "fixes"). Each now carries a `description` and the same resolve-runner →
  `route --runtime antigravity` block the other runtimes use, plus explicit
  guardrails against inventing PATH/zshrc/git work. Mirrored to
  `.agents/workflows/`.
- **v1.0.x published as a real GitHub release.** v1.0.0/v1.0.1 existed only as
  tags, so `hephaestus update` (which reads `releases/latest`) resolved to the
  stale v0.7.32. Releasing v1.0.2 made update land on the current line.

## v1.0.1 - 2026-06-29

- **100K Agentlas routing release.** Hephaestus now ships as the Agent OS engine
  behind Agentlas' 100K-agent routing path: lexical routing is augmented by
  OpenAI query/document embeddings, Atlas `$vectorSearch` dense ANN candidate
  sourcing, optional Z.ai/DeepSeek reranking, and an R2-backed marketplace search
  index.
- **Router Agent cascade.** When deterministic routing lands on
  `clarify`/`propose_new` or otherwise low-confidence decisions, Hephaestus
  attaches a structured Router Agent escalation directive so the host can do a
  final LLM reasoning pass over intent, candidates, and next action.
- **BYOC/BYOM boundary preserved.** The engine still does not call a model for
  the Router Agent cascade. It emits a redacted directive and leaves the actual
  model call to the host runtime, so external LLM hosts and Agentlas Desktop keep
  control of their own model usage.
- **Desktop runtime connection.** Agentlas Desktop now consumes the Router Agent
  directive and injects the assembled `ROUTER_SYSTEM_AGENT` prompt before the
  normal auto-route preamble, so escalation context is no longer dropped at the
  desktop runtime boundary.
- **Production proof.** The release was verified with Atlas vector index READY,
  R2 marketplace index loading, 120 routed profiles backfilled with embeddings,
  routing eval passing 10/10 plus 5/5 guards, production readiness passing 8/8,
  Hephaestus pytest, and Desktop typecheck/smoke gates.

## v0.7.32 - 2026-06-27

- **Reverted the classifier-blocked curl|bash auto-update preflight.** The inline
  `curl <install-all-runtimes.sh> | bash` preflight that v0.7.31 embedded in every
  `/hep-*` command and skill surface is denied by host permission classifiers
  (e.g. Claude Code auto mode) on every machine — it could never run and surfaced
  a blocked-command prompt each time. Adapters no longer carry it.
- **Runtime self-heals stale adapters.** `agentlas_cloud.update.reconcile_adapters`
  strips the blocked preflight from already-installed command/skill adapters —
  network-free and version-independent — on every command (via `maybe_auto_update`,
  `update`, and `doctor`). Machines already on v0.7.31 recover automatically.
- **Routed Hub agents attach to the live codebase.** Borrowed BYOM agents are
  grounded in the working project (`project_dir`) before producing output, and
  `route` emits a `byom_local_grounded` execution directive on `hub_candidates`
  so routing resolves to a context-attached, locally-executed plan instead of a
  dead-end candidate list.
- **Stormbreaker goal loop.** New `goal_loop.run_goal_loop`: iterate a task until
  a goal verifier passes, with stall detection, transient-failure tolerance, a
  runaway ceiling, and Run Journal resume. Wired into the packet executor via a
  packet `loop: {goal_command, ...}` spec.

## v0.7.31 - 2026-06-26

- **No-terminal app-host auto-update preflight.** `/hep-build`,
  `/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, and `/hep-upload`
  surfaces for Claude Code, Codex, Gemini, Antigravity, Cursor, OpenCode,
  OpenClaw, Hermes, and AgentSkills now try to repair/update Hephaestus from
  inside the host app before resolving the runner. Users no longer need to open
  a separate terminal when the host provides a Bash/shell/exec tool.
- **Runtime-current runner wins before stale plugin caches.** Command surfaces
  resolve `~/.agentlas/runtime/current/bin/hephaestus` before Claude/Codex
  plugin cache copies, so a refreshed neutral runtime is not shadowed by an
  older plugin cache.
- **App-only update boundary documented.** If an already-installed host surface
  is so old that it has no update/preflight instruction, or the host exposes no
  shell/MCP/local-file mutation tool at all, Hephaestus cannot rewrite that
  local install from chat alone; one marketplace/plugin refresh or one-touch
  install is still required to reach the self-healing surface.
- **One-touch installs now stamp plugin release markers.** Fresh installs write
  `RELEASE` and Python shims into Claude Code and Codex plugin cache
  directories, and the one-touch verifier now fails if `update --check` does
  not report `current`.
- **Update cache writes are race-safe.** Manual `hephaestus update --check` and
  fail-silent background auto-update no longer share the same temporary JSON
  filename.
- **Bundled runners ignore shadow packages in the working directory.**
  `bin/hephaestus` now forces its own runtime root to the front of Python's
  module path, so a project checkout with another `agentlas_cloud/` folder does
  not hijack the installed runner.
- **Self-healing updates for stale plugin caches.** `hephaestus update` now
  recovers runtimes with no `RELEASE` marker and refreshes existing Claude Code
  and Codex plugin cache directories in addition to the neutral
  `~/.agentlas/runtime/current` install.
- **Non-interactive `/hep-upload` no longer stalls.** After Cloud or Agentlas
  Hub has been chosen, `hep-upload <agent-folder> --visibility private-link`
  and `--visibility marketplace` run through the bundled publisher without
  requiring an interactive TTY.
- **English README language cleanup.** Removed Korean examples from the English
  README command table and changed the language selector label to English.
- **Deterministic `/hep-build` team shape gate.** Added
  `scripts/verify-team-package.sh` plus valid/degenerate fixtures so generated
  packages must be either one `single-agent` worker or a real team with
  orchestrator/HQ, topology, memory, policy, eval, QA, and one HQ command.
- **Ownership-boundary single vs team classifier.** Documented the 0-3 step
  classifier across canonical skills, modes, command adapters, and mode map so
  `/hep-build` no longer treats the word "team" as enough evidence by itself.
- **Plain-language clarify questions.** Builder interview and clarify surfaces
  now ask ordinary user-facing questions about whether one expert can do the
  job or several experts must split and merge it, while internal labels such as
  ownership boundary, memory/context, and produces/consumes stay hidden.
- **Agentlas Cloud/Network personalization contract.** Documented the remote
  Agentlas Web/MCP behavior where signed-in `/hep-network` searches Cloud,
  then bookmarks, then public Hub, while `/hep-cloud` remains Cloud-only.
- **Workspace-scoped borrowed-agent memory.** Added the implemented storage
  contract for Agentlas Web agent bindings, overlays, promoted memory items,
  promoted playbook cards, plugin locks, retrieval receipts, run events, and
  self-evolution proposals. Public Hub packages are not mutated by one
  workspace's personalization.
- **Runtime bundle overlay boundary.** Clarified that Cloud/Hub bundles may
  receive bounded workspace overlays and receipt ids, but raw prompts,
  transcripts, secrets, credential values, and private local files are not
  durable personalization records.

## v0.7.27 - 2026-06-25

- **Update fallback is the first command body line.** The `/hep-*` chat
  command/prompt surfaces now put the `hephaestus update` fallback before the
  command title, immediately after host metadata where metadata is required.
- **Regression coverage locks the placement.** The command-surface test now
  verifies that the fallback is the first non-metadata body line, not merely
  present somewhere in the file.
- **Machine-readable CLI output is unchanged.** The fallback remains limited to
  chat command/prompt surfaces, not JSON-emitting shell commands.

## v0.7.26 - 2026-06-25

- **Update fallback on every `/hep-*` command surface.** Claude, Codex,
  Gemini, Antigravity, Cursor, OpenCode, and mirrored workflow prompts now start
  with one line telling the user to run `hephaestus update` if automatic update
  did not fire.
- **Old versions still work.** The fallback line explicitly says the current
  installed command continues to work even without updating, so the notice is
  advisory rather than a hard dependency.
- **Machine-readable CLI output is unchanged.** The fallback is added only to
  chat command/prompt surfaces, not to JSON-emitting shell commands.

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
- **Detachable public-page reader inspired by an external resilient-reader
  design.** The adaptive `read.insane_fetch` cartridge is mounted only through
  `public-web`, `social`, `browser`, `full`, or explicit allow-lists. It records
  bounded route evidence for direct reads, Reddit RSS, Jina Reader fallback,
  metadata/feed parsing, and login/paywall hard stops, while staying a
  detachable reader cartridge rather than the whole research engine.
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
