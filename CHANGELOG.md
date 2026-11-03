# Changelog

> Entries describe behavior at each release. For current standalone defaults and retired commands, see [README.md](README.md).


## 1.2.76 — 2026-11-03

- Grok: `agentlas-os host install|status|remove grok` registers the standalone
  plugin through Grok's own plugin manager, only when you run it. Antigravity
  and Grok now share one registration module.

## 1.2.75 — 2026-11-03

- After an update, `agentlas-os host session codex` moves its own verified
  Codex skill alias to the current runtime instead of refusing every session
  with `codex_skill_alias_outdated`. An alias it does not own is never replaced.
- `host status antigravity` reports the MCP permission rule headless `agy -p`
  runs need.

## 1.2.74 — 2026-11-03

- `agentlas-os host session claude|codex` no longer passes the engine's own
  location variables to the host app. Another Agentlas plugin installed in the
  same Claude Code or Codex could pick them up and replace the standalone
  runtime with an older release.
- Antigravity: `agentlas-os host install|status|remove antigravity` registers
  the standalone plugin (`agentlas-os-core`, MCP server `agentlas-os`) through
  Antigravity's own plugin manager, only when you run it.

## 1.2.73 — 2026-11-03

- Standalone OS installs into its own runtime namespace and preserves the legacy
  Desktop runtime. Automatic project bootstrap, indexing, Context Map, Memory,
  Storm, telemetry, and update checks are off by default and can be enabled
  explicitly. One has a separate on/off preference.
- Core agent building, Network, Cloud, search, calls, goal planning, and session
  builds remain available. Standalone Graph automation and Telegram/Connect
  commands have been retired; existing user data is not deleted.
- Standalone host integration prepares isolated, version-pinned sessions.
  Check the reported host status for any unconnected or unsupported component.
- Package and session builds work with the bundled schema validator when the
  host has no separately installed JSON Schema package.
- Agentlas Desktop and Agentlas Terminal keep their previous behavior: optional
  features stay on for them unless the user turned a feature off.
- A Storm run is no longer blocked when automatic project setup is skipped, a
  project format upgrade starts once instead of on every prompt and waits after a
  failure, and the memory-free project index keeps a single current copy.

## 1.2.72 — 2026-11-01

- Context: in a folder with no project map, the hint now tells the model to call
  `context.refresh` once for that folder and repeat the call (or carry on without
  the Context Map if the refresh refuses the folder), instead of naming a command
  line tool the model of a runtime session often does not have. The typed
  `project_not_initialized` error stays and is marked repairable. Read-only
  context tools still never create project state.
- Workforce: recording a Goal turn for a Goal with no roster bound in the project
  now answers `skipped` with a plain sentence instead of an error. Completing a
  Goal and the other Goal tools keep their typed errors.

## 1.2.71 — 2026-10-30

- Memory curation: a lesson that names a project path (in backticks, quotes,
  brackets, after `=`, `:` or `,`, including `C:/...`) is now treated as
  specific to that project instead of portable, so it is no longer recalled in
  an unrelated project (curator ruleset 1.4.0). Word characters before a root
  such as `/home/` (URL fragments) are still not treated as host paths.

## 1.2.70 — 2026-10-27

- Workforce: prepared agents can use the current host's native delegation when
  it is available and authorized, without switching to another application.
- Package read allowlists describe package contents. Project access and tools
  continue to follow the current host's permissions and explicit restrictions.
- Missing execution-receipt telemetry no longer blocks authorized host work.
  Receipt validation remains strict, and unvalidated work is not reported as
  validated execution.

## 1.2.69 — 2026-10-25

- Memory recall: source files with Korean or spaced names are found again, so
  recall no longer labels them "source missing"; labels show the decoded name.
  On Windows, stored `file:///C:/...` sources are checked as the same files.
- Windows: `.cmd` launchers (`python3.cmd`, `hephaestus.cmd`, memory hooks) work
  under a user folder with a Korean or other non-ASCII name.
- Windows: the local judge and translator reach loopback model servers
  (`127.0.0.1`, `localhost`, `::1`) directly instead of through a company proxy.
- Windows: without symlink privilege, `runtime/current` becomes a directory
  junction instead of a copy, so a running engine never mixes files from two
  versions, and pruning keeps the active generation.
- Windows: crashed update, translation and ingest jobs no longer hold their
  locks for up to an hour; process checks use the Windows process API.
- Windows: engine files are written and read as exact bytes, so CRLF sources,
  upload digests and artifact digests match on every OS.
- Windows: uploads, agent revision reads and local package registration work;
  they walk by path and re-check every folder before and after each read, and
  refuse links and junctions.
- Windows: shorter release folder names leave room for package files under the
  path limit; existing folders are still used.
- Windows: ledger appends and the networking init lock take a file lock, atomic
  JSON writes retry a brief sharing violation, the memory database waits longer
  on a busy file, scheduled-task output is decoded in the console code page, and
  directory swaps no longer half-delete a cache that holds a loaded module.
- Browser: the browser launcher can add notes from an approved per-site
  learning to page results. Nothing creates such a learning yet, so pages read
  the same as before.

## 1.2.68 — 2026-10-24

- Sign-in: `auth status` (CLI and the `agentlas_auth_status` MCP tool) renews a
  saved sign-in whose one-hour access token has aged out, instead of reporting
  the engine as signed out after an app update or restart. A refused grant
  reports `sign_in_required`, an unreachable server reports `refresh_deferred`,
  and an unreadable record says so; `--no-refresh` keeps the plain read.
- Local models: the OS judge's Ollama runner sizes the context window from the
  model's trained maximum and tells Ollama not to truncate, so long prompts are
  no longer silently cut on machines with a small default window. A prompt too
  large for the model stops with `local_context_limit_exceeded`.
- Windows: engine background jobs (update worker, runtime health checks, memory
  hook installer, detached memory worker and their children) no longer open
  blank console windows.
- Windows: the ontology reads its stored `file:///C:/...` and UNC source
  addresses back as the same files, so project verification and queries no
  longer report every source as deleted. Existing databases need no migration.

## 1.2.67 — 2026-10-20

- Hub search: the networking client asks the marketplace, owner Cloud and
  bookmark search tools for listing taglines in every search scope, so Hub
  candidates in the search menu carry their own descriptions and the local
  rerank reads more than names.
- Context Map: local verification dependencies that CI workflows and test
  commands name (support modules and fixture data, even when Git ignores them)
  are part of the content snapshot; the code-map policy moves to v4.

## 1.2.66 — 2026-10-17

- MCP server: one malformed JSON-RPC line no longer ends the server, and
  model-supplied paths (`context.refresh`, `memory_root`) must stay inside the
  roots the host approved.
- Sign-in: OAuth token refresh happens once across processes, invalidation
  clears only the token it read, and sign-in opens only the configured hub with
  same-origin OAuth metadata.
- Memory curation proves the owner through the MCP identity tool
  (`account_context`) before it writes.
- Windows: `/hep-goal` locks its strategy store without `fcntl`, process
  liveness is probed correctly, `.cmd` wrappers name their script through
  `%~dp0`, and runtime pruning recognises escaped Windows paths in host configs.
- `goal_runtime` returns the newest plans and prunes old plan files; the One
  ledger lock recovers a stale directory lock.
- Research fetches fail closed on the SSRF guard and connect to the address
  that was checked; the Stormbreaker executor timeout ends the whole process
  tree.
- The auto-update worker starts outside the runtime generation it replaces.
- Installers pin the Desktop signer on macOS, and the PowerShell installer
  stops on errors.
- The Hub WorkOrder privacy boundary recognises the upload scanner's secret
  key prefixes.

## 1.2.65 — 2026-10-16

- Add `/hep-goal`: a plan tree for long, measurable goals that adds to the host
  `/goal` (shape, strategies and tactics, KPI readings, stall and infeasibility
  reports, re-plan on a trigger). One MCP tool `goal.strategy`, CLI `hephaestus
  goal ...`, rules in `contracts/goal-rules.json`, state under
  `.agentlas/goal/`. A short goal stays a single tactic and adds nothing. The
  default mode is `shadow`; `AGENTLAS_GOAL_STRATEGY=on` enables it.
  Whether it beats a plain host goal on real long-running work is not measured.
- Prune old runtime generations on every install and update. Hidden
  `.generations/` folders were skipped, so each install left a 160 MB copy
  behind. The rule keeps the current release, any generation a host config or a
  running process still names, and one rollback of a different release.
  `AGENTLAS_RUNTIME_KEEP` now defaults to 2.
- The research browser launcher no longer lets the shared automation profile
  download Chrome's on-device AI model, and caps its HTTP cache at 256 MB.

## 1.2.64 — 2026-10-16

- Core automatic memory curation moved to the canonical model: `curate()` queues
  legacy tickets and `stop_hook` no longer admits learnings itself.
- Drop the unread `scopes.oneForwardable` value from the curator ruleset.

- Model-led secret review on upload: the connected model (or the host model, via
  a review file) can only remove more lines from an upload, never clear a
  deterministic pattern hit; receipts carry file, line and kind only.
- Ask where to store a built agent (Cloud, public Hub or local only) once the
  build verifies, and register built agents in the local roster automatically.
- Give every Cloud and Hub refusal code and every broken local agent a machine
  readable repair plan instead of a bare error token.
- `/hep-orch` can set the reasoning-effort ceiling (`role.effort=`).
- Remove Gemini CLI as a supported host. Its individual-tier service ended
  2026-06-18 and Antigravity is the successor. The installer and `hephaestus
  update` delete only the engine-owned files an older install left in
  `~/.gemini/extensions`, `~/.gemini/commands` and
  `~/.gemini/hephaestus-extension-source`; Antigravity's `~/.gemini/GEMINI.md`,
  `~/.gemini/antigravity*` and `~/.gemini/config/*` are untouched. `gemini-cli`
  is still accepted in routing cards that were published earlier.
- A failed Cloud or Hub search now returns its repair plan as `sourceRepairs`
  beside the digest-bound source receipts.

## 1.2.62 — 2026-10-10

- Raise the UserPromptSubmit memory-hook timeout from 20 to 60 seconds for the
  Claude, Codex and Grok adapters, so recall on a large project is no longer
  discarded by the host before it finishes.

## 1.2.61 — 2026-10-10

- Publish portable capability and routing cards without local runtime state or
  retired One drawer guard artifacts.

## 1.2.60 — 2026-10-09

- Keep single-agent packages intact through `contract complete`: a worker under
  `.agents/<id>/` now counts as a roster, so the company blueprint is no longer
  deleted and the single-agent shape check keeps passing.
- Register a package whose blueprint declares a single agent as an agent even
  when it has an `agents/` folder. Real teams and legacy `agents/` folders
  without a blueprint still register as teams.
- Never promote a thin adapter over the canonical `AGENTS.md`, so repeated
  `contract complete` runs no longer leave the core pointing at itself.

## 1.2.59 — 2026-10-08

- Reject combined WorkOrder and Selection dependency cycles during validation
  and preparation, and check cached plans before any host invocation.
- Pin the latest verified ACP runtimes while retaining live initialization gates.
- Update existing user-scope Claude installations and normalize only verified
  installer-owned runtime aliases to immutable marketplace sources, preserving
  unrelated plugin settings.

## 1.2.57 — 2026-10-06

- Seal prepared Workforce plans after local project grounding is attached so
  cached plans retain valid integrity pins when an executor resumes them.
- Prepare an accepted selection using its session and digest references.
  Restore only the exact pinned choice and reject changed or expired references.
- Expose the existing external host execution route and its measured invocation
  requirements in Network commands and skills.
- Reuse normalized Upload scan text and avoid duplicate searches when shadows
  are identical, preserving detection rules, priorities, and redaction behavior.
- Show Upload help before requesting a destination and include the contract
  completion step in top-level help.
- Verify Claude plugin activation from the exact user installation's JSON
  state so display layout changes cannot report an enabled plugin as failed.
- Advance independently verified managed marketplace generations during
  updates while preserving plugin settings and rejecting untrusted sources.
- Pin Claude Code ACP 0.86.0 and Copilot ACP 1.0.92 in the runtime registry.

## 1.2.54 — 2026-10-02

- Restore compatible One memory event envelopes and merge bounded evidence references.
- Accept recalled replacement hashes and preserve scoped memory replacements.
- Apply memory privacy checks to original-language content and evidence.

## Unreleased

- **Public Hub calls are free in the host guidance.** Login instructions and
  Workforce tool descriptions now reflect free Hub runtime plans. Older
  leased plans still require their original valid lease to resume.

- **Workforce tool bindings now admit measured host tool brokers.** Native and
  broker inventory rows remain distinct, and direct and nested invocation
  receipts must match the enforcement path selected by their bound tools.

- **Prepared Workforce goals can now run through provider-neutral external host adapters.**
  The new `workforce execute --adapter-argv-json` command loads the newest ready
  cached plan, invokes its exact orchestrator, planner, worker or team graph,
  synthesis, and independent verifier nodes without a shell, snapshots measured
  outputs, and exposes a receipt only after the existing Core validator accepts
  it. Provider authentication and runtime configuration remain in independently
  installed plugins.

- **Host permission mode (`host`) is now covered by a tracked CI gate.**
  `permissionPolicy` accepted `host` for `network`/`shell`/`fileRead.mode`/`mcp.mode`
  as of 1.2.41 (a package declares no tool ceiling; the host runtime decides at
  execution time, and Desktop emits a native-sandbox enforcement receipt for
  those rows), but nothing in CI checked that contract — `tests/` is
  gitignored, so a tests/-only check never ran there. `scripts/verify-host-authority-contract.sh`
  now calls the real Workforce functions (`host_permission_policy`,
  `deny_all_permission_policy`, `validate_permission_policy`) against
  `schemas/workforce-execution-plan.schema.json`, proves the gate can fail red
  by rejecting a no-authority-sandbox receipt carrying approvals, and runs in
  the cross-platform-wiring workflow's contract-gates job.

## 1.2.47 — 2026-09-17

- Existing Desktop 1.2.14 and 1.2.15 installations can recover known unsigned
  Claude/Grok npm additions through the verified engine-update path. Recovery
  preserves the files outside the app and requires the original Developer ID
  signature and Gatekeeper assessment to pass before reporting success.
- Interrupted recovery restores moved files before another attempt. Conflicts,
  active writers, changed signing metadata, and unknown additions remain blocked.
  Desktop 1.2.18 supplies the separate CLI update-path prevention fix.
- An install that is missing one of the engine's own modules no longer takes
  down every MCP tool that seeds a project first. Project bootstrap now skips
  the derived half of the context map, records it, and lands the rest of the
  seed. When one of our modules really is absent, the tool error says so and
  says that the other tools on the server still work and that the background
  updater repairs the runtime, so a host does not abandon its Workforce roster
  after a single failure.

## 1.2.39 — 2026-09-01

- **Runtime updates are now verified inside the release transaction.** The
  release workflow adopts the latest ACP pins, directly initializes every npx
  adapter, checks native runtimes against the current probe matrix, and creates
  the pin commit and release tag only after the package gates pass.
- **Daily version drift is reported as a pending release update, not an
  outage.** Missing runtimes and failed initialize probes still fail the job;
  ordinary upstream version changes remain visible without producing a false
  incident.

## 1.2.38 — 2026-08-30

- **Host hook manifests now share one verified schema across every adapter.**
  Unsupported top-level fields are removed, Windows/Linux wiring validation runs
  before installation, and the public runtime archive carries that verifier so
  a malformed hook bundle fails closed instead of reaching a user's host.

## 1.2.37 — 2026-08-29

- **Global router mutations are byte-idempotent and preserve every recovery
  point.** Repeating an install no longer adds leading blank lines, parallel
  installs serialize before re-reading the prompt, and each install/remove
  snapshot uses an exclusive high-resolution backup name that cannot overwrite
  an earlier receipt.
- **Wizard previews no longer claim that an unwritten package is executable.**
  `wizard --no-write` now returns a typed `preview` result with its projected
  status and an explicit no-write transition; only the writing path reports
  that `agentlas.json` was generated and is ready for an MCP call.
- **Parallel One sessions no longer erase recall and evolution evidence.**
  Recall counters, supersede pointers, semantic index state, and observed One
  state now serialize each read-modify-write against the target file. Atomic
  writes use exclusive per-process temporary files, so overlapping hooks retain
  every increment and mapping instead of silently replacing one another.

## 1.2.36 — 2026-08-29

- **Runtime updates repair the host's persistent Agentlas source, not only its
  cache.** Codex and Claude registries are migrated to the stable
  `runtime/current` adapter path with exact structural readback, while duplicate
  Codex source assignments and stale refs are removed without changing other
  marketplace records. An already-running host is reported as
  `pending_reload`; an inactive host becomes current immediately after the
  persistent state is verified.
- **Claude's installed-plugin ledger is pinned to the immutable public release
  commit.** Runtime archives now carry Git-exported release provenance, and the
  updater verifies and records that exact commit together with the release and
  install path. A stale developer checkout or same-version cache can therefore
  no longer masquerade as the public release that the next Claude session will
  load.

## 1.2.35 — 2026-08-28

- **Network menus expose candidates whose semantic fit has no evidence.** A
  candidate with no structured, lexical, vector, or publisher-trigger evidence
  now carries `gap:semantic-fit-unsubstantiated`. Core still leaves the final
  staffing decision to the host model, while validation reports one unmet
  requirement instead of presenting the selection as fully supported.
- **Plugin resolution matches actual plugin identities instead of incidental
  substrings.** Queries use Unicode word tokens, require the complete plugin
  name or two distinct description-token overlaps, and expose the documented
  `agentlas_resolve_plugins` MCP tool. A Trello request can therefore remain
  honestly unresolved rather than matching generic words such as `create` or
  the `card` substring in Cardputer.
- **Host memory hooks are installed only when their promoted runtime runner is
  callable.** Detected hosts now receive a typed
  `runtime_memory_hook_unavailable` refusal instead of durable hook commands
  that later exit 127. Machines without a detected host remain a genuine
  no-op success.

## 1.2.34 — 2026-08-28

- **Reload feedback remains truthful after the host ledger has already moved.**
  Reconciliation verifies the target-named cache directly, samples the process
  table once, and compares Codex/Claude host start times with a durable
  activation cutoff. Open sessions therefore remain `pending_reload` even when
  their command line does not expose the cache path or the persistent ledger
  already points at the new release. Unknown process visibility fails closed,
  process evidence is scoped to the matching UID and host profile, active hosts
  never trigger vendor CLI mutation, and Claude migration changes only the exact
  Agentlas plugin entry rather than every `hephaestus@*` entry.
- **Network discovery refreshes mutable source inventories without weakening
  execution pinning.** Owner Cloud searches bypass stale success-cache replay,
  while Local searches re-snapshot only sources already registered in the
  roster. New searches can therefore see an edited or removed package, but an
  existing selection session and its prepared runtime bundle continue to use
  the exact immutable release they originally selected.
- **The freshness contract now reaches every supported host adapter.** The
  canonical `/hep-local` and `/hep-network` bodies are rendered into each host
  format, and installers/self-updaters use the canonical skill tree so a stale
  mirror cannot silently ship a different runtime contract.

## 1.2.33 — 2026-08-28

- **Network staffing now ranks the work, not the host permission vocabulary.**
  Candidate discovery uses the WorkOrder title and task together with agent
  names, summaries, roles, skills, knowledge, inputs, outputs, and authored
  sample tasks. Runtime, language, modality, authority, and tool requirements
  stay in the execution contract for host-side validation instead of changing
  semantic fit or manufacturing per-candidate gaps. The supported recall window
  is consistently 30 candidates across the shipped host adapters.

- **Commands and packages stop reporting preparatory success as completed
  work.** The command registry now distinguishes executable,
  host-model-required, redirected, and identity-only surfaces and names the
  binary that actually owns each action. Contract completion returns blocked
  when verification still has blockers, runtime bundles refuse invalid package
  contracts, exact routing-card files are linted, and a zero-case benchmark can
  no longer claim routing-ready status.

- **Runtime auto-update repairs exact-version Codex and Claude plugin state.**
  A machine updating once from v1.2.32 materializes a v1.2.33 cache, migrates
  Claude's installed-plugin ledger atomically, records any old-name cache that
  the already-running v1.2.32 updater changed before the new bridge could take
  control, and reports that host as `pending_reload` until its process exits or
  reloads. From v1.2.33 onward every version-named cache is immutable and only
  the exact new target is created. Offline, disabled-update, and
  runtime-not-installed paths remain fail-closed; no vendor CLI is invoked
  during this bounded transition.

## 1.2.32 — 2026-08-27

- **`hep-build session` adds the fourth builder route across the supported host
  adapters.** Interactive hosts analyze the visible current conversation, ask
  for the agent destination, default to the global Agentlas agent folder when
  none is supplied, and require owner review before materialization. Terminal
  and headless callers may use explicit JSON/JSONL exports through the same
  deterministic Core boundary. Internal package and plugin names remain
  unchanged, and session builds never upload or publish automatically.

- `agentlas_tool_search` and `agentlas plugins tool-search` rank servers before tools and load schemas only for the chosen tool. `forbid_destructive` excludes deleting tools when deletion is forbidden.

- The candidate menu defaults to four candidates per slot. A role may supply up to eight `queries`, joined into its task.

- Plugin and agent discovery share a stopword list so function words do not create irrelevant substring matches.

- Build telemetry respects HTTP 429 with a bounded quiet window and resumes ordinary reporting afterward.

- **`hep-storm` with no arguments printed a bash internal error.** Under
  `set -u`, expanding an empty array crashed the launcher with
  `storm_args[@]: unbound variable` — the one branch in the file that expanded
  a possibly-empty array without the guard every other branch already used.
  It now answers `query or --decision-file is required` at exit 2, and
  arguments still reach the parser.

- Command handling fixes: scaffold and repackage normalize command slugs; orchestration refuses invalid tiers or model identifiers; unsupported launcher words direct callers to the owning command; browser research failures return a nonzero exit status.

- Work-order normalization refuses concepts whose non-ASCII letters or digits would be deleted, rather than admitting a bare namespace as a requirement. Authored English phrases remain supported.

- Hub transient errors and named server refusals now include a next step. `hep-call` preserves the server refusal verbatim and adds the remedy beside it.

- Network, Cloud, and bookmarks share the discovery path. The server tool and owner-scope arguments select the scope; the runtime does not filter the returned scope again.

- `search` exits 4 when every section fails without rows, and `call` exits 4 on failed preparation; partial results retain exit 0. Source failures carry recovery hints beside sealed receipts. A login failure remains one failed source receipt instead of terminating the entire federated search.

- Command behavior and failure guidance are documented for end users. Retired graph automation and Telegram connection commands are not available in the standalone engine; the current README lists supported commands.

- Package schema validation uses the local-only schema store with the vendored jsonschema 4.17.3 RefResolver when the newer referencing registry is unavailable, and prefers a healthy installed validator.

- **A tombstoned goal names its way out.** The implicit goal id
  is a deterministic digest of the WorkOrder, so preparing the same request in
  the same project after its auto goal was completed failed forever with a
  bare `workforce_goal_already_terminal`. The refusal now says to pass a new
  explicit goalId (or reuse an active goal from goal_context), and both MCP
  goal handlers forward remediation sentences beside their codes.

- Remote preparation failures identify the source, release, and slot involved and give a recovery action for unavailable artifacts.

- A pure-Python jsonschema 4.17.3 fallback with attrs and pyrsistent keeps schema validation available when native dependencies cannot load. Dependency licenses are included.

- The `.zcode` dispatcher accepts `login`, `orch`, and `update`. `auth ensure` exits 3 unless authenticated; CLI projection preserves sign-in hints. Login commands join the updater command floor and use the canonical update fallback.

- `auth ensure` respects `HEPHAESTUS_AUTO_AUTH=0` and headless operation. Silent token refresh remains available, while signed-out runs return promptly without opening a browser.

- **A signed-out owner-scope search stops answering "there is nothing".** The
  CLI `search` asked cloud/bookmarks anonymously and reported `status: ok` with
  zero rows — "could not ask" dressed as "none exist", while the MCP surface
  answered `failed`/`partial` honestly. It now refuses plainly with
  `unauthenticated` and a sign-in hint.
- **Search cache lines carry the account.** The hub-search cache key had no
  identity, so a signed-out session (or the next account) inherited the
  previous account's cloud/bookmark rows for the whole TTL. Owner-scoped lines are now keyed by an account
  digest, which makes a foreign hit impossible without any cross-module cache
  wipe on logout.
- **`project status` in an unsafe directory names the guard and the way out.**
  The intentional home/system-folder guard was collapsed by a bare exception
  handler into `project_bootstrap_failed` with no cause and no next step
 . The refusal now carries the real code (`unsafe_project_root`,
  `project_directory_does_not_exist`, …) and a remedy line.
- **`/agentlas login|orch|update` stop being refused.** The alias files said
  "identical to /hep-login" while the `/agentlas` dispatcher's accept list
  did not contain them, on every runtime — the freshly restored
  login command was unreachable through its most natural spelling. All eight
  dispatcher surfaces now accept the three verbs; resolution reuses the
  existing `hep-<cmd>.md` rule unchanged.
- Historical Telegram adapter coverage was extended across hosts. The command has since been retired from the standalone engine; see the current README.

- Package upload refuses to publish when schema validation is unavailable.

- The no-Python-anywhere hint no longer tells a Mac user about Windows.

- Goal bindings remain partitioned by account. `goal_context` reports active signed-out bindings for the same project as `signedOutGoalsForThisProject`; it does not merge accounts automatically.

- Authentication always prints the sign-in URL, including when the browser handler reports success, so users can open the page manually.

- Career Graph ingestion skips individually oversized sources and reports their limits under `skippedSources`; malformed sources still abort while preserving the previous projection.

- Replaced `Path.stat(follow_symlinks=)` with compatible filesystem calls so command paths support Python 3.9 as well as newer interpreters.

- CLI and MCP Context Map failures share recovery guidance. Incomplete refreshes identify `stats.budgetStop` and suggest narrowing `agentlas-context-map.json` scope or requesting stale data.

- Updates add missing commands for already configured host directories, including empty configured directories, and report them as `added` without creating unconfigured host surfaces.

- HTTP 401 invalidates the rejected access token while preserving its refresh grant. Retry obtains a new token, and local status reports `refreshable` with `server_rejected_at` instead of claiming an authenticated session.

- Stored releases with an older compiler version are recompiled even when their original import folder is no longer present.

- A vocabulary dimension demoted at slot level no longer generates contradictory candidate-level missing-skill labels. Fit evidence, structured ranking, and evidence-level checks are retained.

- **A refused selection now names the vocabulary it wanted.**
  `selection_reason_code_not_public_finite` stated the rule and not the allowed
  values, so the caller had to read the source to repair a rejection. The issue
  now carries a bounded `allowedValues`, the candidate's own fit evidence first.
  Everything listed already reached the caller in the candidate set it is
  selecting from, so this closes the loop without disclosing anything new.
- **Every shipped command reaches an existing machine.** The updater unions its
  command floor with the release bundle and with what the machine already has,
  so for a machine that never received a command the floor is the only path by
  which it can arrive. The floor still listed the eleven names it was born with:
  `hep-graph`, `hep-orch`, `hep-update` and the whole `agentlas-*` alias family
  were renderable, installable and documented, yet absent from a long-lived
  machine's global commands. The floor is now the full rendered set, and
  `tests/test_installer_registry_parity.py` fails if it drifts again.
- **Automatic routing stops reporting an unreachable blocker.** Routing
  benchmark suites are development fixtures the public release allowlist keeps
  out of every shipped build, so on an installed machine `network bench` has no
  suite to load and the status read "benchmark state is not ready (no_suites,
  no_cases)" — a blocker phrased as something the user could clear, which
  nothing they do ever will. A build that ships no suites now says so, and says
  the host LLM makes the routing decision; a checkout that does ship them keeps
  the original blocker wording.
- Doctor compares a host plugin ledger with the installed payload and reports version drift with the host command that reconciles it.

- **The MCP surface gate enforces the rule it documents.** The rule is "no
  second remote MCP that bypasses Core governance", but the assertion read
  "exactly one server, full stop". When a local companion launcher shipped, the
  gate failed on `main` for a reason that was not a governance problem while
  reporting the plugin contract "broken". Core must now be present and exact,
  any other entry must be a local process from an allowlist, and no entry may
  carry a remote endpoint.

- **A published agent is no longer reported as a failed publish.**
  Registration verifies the submitted hash, then withholds any file its own scan
  judged credential-like and stores the rest under a new hash. The client
  compared only against that stored hash, so the documented repair surfaced as
  `registration_attestation_failed` AFTER the listing was live — the agent was
  on the Hub, searchable and callable, while the publisher was told the upload
  failed, and everything downstream of attestation (pricing included) never ran.
  Either hash matching ours now satisfies attestation, the withheld paths are
  reported as `serverWithheld`, and a response carrying neither still fails
  closed.
- **The per-agent ceiling is 10 MB transport / 2 MB per file** (40 MB as
  authored), raised across the engine, Desktop, the Terminal and the server
  together. 10 MB is what the store can hold: a package's bytes live inside one
  manifest record, that record is one MongoDB document capped at 16 MiB, and
  content is stored base64.
- Packaging tokenizes before filename scanning and screens long lines in overlapping windows to avoid quadratic scanning of minified content.

- Packaging caches content-guard scans by exact bytes; any repaired or otherwise changed content is rescanned.

- Upload completes collection before applying importance-ranked trimming. Agent definitions, cards, skills, and knowledge are preserved; each omitted file carries a receipt.

- **An oversized file is withheld, not a refusal.** A file over the per-file
  ceiling can never travel, so it is left out with a receipt and the rest of the
  package uploads. The only size case that still stops is arithmetic, not
  policy: nothing droppable is left and the agent's own essential files are
  still over the ceiling.
- **The project's agent map heals itself.** `.agentlas/agent-ontology/` is
  derived from sitemap/routing-card/memory-map, all of which the project seed
  rewrites — and nothing re-derived it, so an ordinary seed left the map stale
  and a stale map fail-closes routing for the whole project. One test-suite run
  took ten routing paths down at once. The seed now re-derives the map, and
  never touches a materialization someone edited by hand.
- **Two contracts now run in CI.** `verify-upload-redaction.sh` held the upload
  contract but no workflow called it, so a regression that downgraded every
  package-limit finding to a warning sat undetected for nine days. It and the
  new `verify-project-map-selfheal.sh` run on every push.

- Collaboration edges describe handoff flow and stay in `edges`; they do not become mandatory qualification requirements for candidate discovery.

- **Authored phrases become concept ids instead of a pattern refusal.** A host
  writes "network efficiency research"; Core normalizes it to
  `network-efficiency-research`, reports every rewrite as `normalizedConcepts`,
  and refuses only what cannot be reduced to an ASCII concept — with a code that
  says so instead of a bare `schema_pattern`.
- **A staffing decision is compact too.** `workforce.validate_selection` accepts
  `decision` (session, author, one row per post naming the menu ordinal) and
  compiles the exact Selection, ending the empty-array ritual that survived in
  the Selection contract after the WorkOrder lost it.
- **An accepted receipt can no longer read as "nothing unmet".** Core still does
  not choose for you, but an accepted validation now carries
  `unmetRequirementCount` and the exact unmet rows, and the MCP surface repeats
  it as a notice.
- **Expansion shows the artifacts again.** `workforce.expand_candidates` is the
  narrow, exact look, so it no longer replaces produces/consumes with counts —
  the host could otherwise not judge edge compatibility on any surface.
- Preparation reuses the active implicit goal for the project. `goal-context.v2` supports `knownRevisions` deltas, and automatic bindings retain agent names for readable rosters.

- `goal_context` reports `pendingExecution`, and the session checkpoint warns when prepared work has not been executed without blocking the session.

- Stopword filtering runs at the ranking source. Requirement gaps accept concept-family matches rather than treating spelling variants as missing capabilities.

- Selection and WorkOrder boundary refusals use compact repair information instead of repeating the tool contract catalog.

- Both preparation paths use the shared Context Map compactor, with dropped rows reported in `omissions`.

- **`prepare_execution` takes the same compact `decision`.** Re-authoring the
  exact Selection to run a decision Core had just accepted was the last echo in
  the sequence.
- **The shared scratch root is not a project.** A stray `.agentlas/` had been
  written at the system temp root, so every temporary directory on the machine
  resolved to it while walking up for a project — the recall hook then attached
  an unrelated project's continuity to work that had nothing to do with it. The
  upward search and the bootstrap refusal now both exclude the exact scratch
  root (anything nested under it is still a legitimate working directory), which
  is the boundary the search already documented for home and the filesystem root.
- **An update check no longer builds the home of a runtime that is not
  installed.** That guard existed, but two calls ran ahead of it and created
  `~/.agentlas/runtime/` to write their own markers, so an isolated plugin
  bundle still grew a runtime home it had no runtime for. The retirement marker
  now returns when there is nothing to retire.

- **A gate that could not run stopped reporting success.** `verify-mcp-surface.sh`
  used `if rg -q ...`; on a machine without ripgrep that exits 127, reads as
  false, and skipped the "direct remote MCP bypass" check while still printing
  "passed".

The staffing request is now semantic at the model boundary and exact only
inside Core.

- **The first WorkOrder is compiled, not guessed.** The host submits a compact
  task/role/edge draft. Core deterministically generates transaction, slot and
  artifact IDs, supplies omitted empty fields, pins the ontology, validates the
  privacy boundary, and returns a one-hour local `workOrderRef`. Search accepts
  that reference while retaining the legacy exact object for rolling
  compatibility. An old runtime without this preflight boundary now produces
  `workforce_protocol_upgrade_required` instead of inviting another hand-built
  WorkOrder retry.
- WorkOrder preflight, search, selection, roster continuity, and status/auth are project-content independent. Explicit Context operations and project-grounded routes retain working-tree access.

- **Context Map refresh is change-driven and incremental.** Authored docs are
  indexable; generated evidence, binaries and build outputs remain narrowly
  excluded. A default Context call performs one automatic refresh after a
  filesystem fingerprint change, while `refresh=false` remains a strict
  no-write audit. Unchanged files reuse their prior content hashes instead of
  rereading multi-gigabyte repositories.
- **Protocol identity is release-gated.** `manifest.json`, MCP `serverInfo` and
  the Workforce protocol metadata must agree in the release verification gate,
  so a protocol change cannot remain a same-version local patch that no other
  installation can discover.

## v1.2.14

Two things a package could not say about itself, and a gate that disagreed with
the one it hands off to.

- Built agents record the engine version. Verification reports `engine_drift` as current, drifted, unstamped, or unknown_engine without manufacturing a stamp when the engine cannot be identified.

- **A package the build gate passes is one the upload gate accepts.** The build
  gate printed `public_marketplace_ready=true` whenever the profile was
  `standard`, reading neither the host-path scan nor the blocker list, while the
  function upload calls refused the same package. It now defers to that function
  instead of keeping a second copy of the rule, and fails when it cannot run it.
- The installed-package sweep checks current contracts and records findings without automatically repairing packages.

- Learning attribution uses the invocation ledger when exactly one borrowed agent has a certain session window. Ambiguous attribution is not guessed; project-scoped learnings retain their project association.

- The candidate menu reserves its last three seats for matches to publisher-authored trigger sentences, while preserving the existing ranking arithmetic.

- `shortlist: true` returns summary cards with ordinals, identity, requirements, and summaries. `workforce.expand_candidates` retrieves full cards for selected ordinals before a decision.

- `fullDossier: false` emits each directive bundle once per content digest. Callers that verify whole-row digests keep the self-contained default representation.

- Project grounding ranks files for the task before applying its cap, and gives an explicitly named file priority over unrelated or scratch paths.

- Verification traversal deduplicates emitted edges so repeated graph visits do not consume the result cap.

- Symbol rows use a bounded sample of referencing paths and report its size; the file section retains the paths selected for reading.

- Workforce compilation strips an existing `skill:` prefix. `COMPILER_VERSION` triggers reconciliation of stored profiles produced by older compilers.

- **Vendored interpreter payloads and scratch build trees are not indexed.**
  A desktop build tree carried a full CPython stdlib, and `.tmp-*` copies are
  byte-for-byte duplicates of real source that led every selection. Indexing a
  live build output also raced with the build that was writing it.

## v1.2.13 - 2026-08-19

The project map stopped being something the product built and started being
something an agent works from.

- Recall freshness checks run under a budget and can serve the last complete map as `unverified_served` when the check exceeds that budget.

- **The capsule spends its budget on where the code is.** Three different
  coding questions used to produce byte-identical slices carrying zero file
  paths, because standing goals consumed the layer budget first. Definitions,
  related files and co-edit history now render before them.
- Context capsules render the edges discovered during traversal within the existing response budget.

- Impact verification includes advisory name-matched targets with confidence information, and the PreToolUse warning carries those targets.

- **The graph opens without words.** Its only two entry points were a path or
  a symbol spelled in the task, so a question that describes rather than names
  fell through to conventional entry points. The contact ledger's edit history
  is now a third entry point, and one dependency hop follows every seeded file.
  A slice also states where things live, directory by directory.
- Project seeding runs in a detached worker, and existing seeds use an idempotent format migration ledger.

- **A subagent starts with the map.** SubagentStart wrote an observation and
  returned nothing, so every spawned explorer began by grepping for what the
  map already knew.
- Machine-generated sitemap edges use a columnar representation with indexed endpoints and edge types, reducing repeated path strings while preserving human-authored edges.

- Project-scoped learnings enter the declared map only when both scope and workspace match. Derivation emits relations as well as nodes without writing back to the personal drawer.

- **`context.locate` answers with files, not only symbols.**
- **`agentlas-one off` actually stops personal recall.** The switch was
  consulted by one unrelated branch while the layer that puts personal
  memories into the prompt never asked, and it hard-coded the drawer path so
  `AGENTLAS_ONE_DIR` was ignored for reads and receipt writes alike.
- **A project inside another project is its own project.** The upward search
  adopted the enclosing map, answering with a different project's files. A VCS
  root always ends the search; a manifest ends it only when no repository
  encloses it, so monorepo packages keep their repository's map.


## v1.2.12 - 2026-08-18

- **One host-adapter catalog for the installer, the updater and the release
  build.** The three programs each carried their own list of adapter payloads,
  so a path retired in one place kept being requested by another — the release
  asset build passed deleted paths to `git archive` and failed outright.
- **`/hep-orch` and `/hep-update` ship as commands**, and the orchestration
  allocator now receives the two inputs it never had.
- **Uploads exclude run outputs, protect capability samples, and compress
  packages** — knowledge files no longer die to the transport limit.
- **Recall freshness checks run under a budget**, so the host stops discarding
  every capsule when verification is slow.
- **Interview questions are a channel, not a UI.** The builder gate now names
  the channel ladder — desktop sheet, host-native question tool, numbered
  markdown list, or `NEEDS-INPUT:` for unattended runs — so a plugin-surface
  interview degrades honestly instead of leaving a raw fence nothing renders.
- Context freshness checks are bounded, and capsules include readable relations from the completed traversal.

- **Five shipped contracts tell the truth again**: the package-contract schema
  accepts its own `text` kind, scaffolded packages can read all of their own
  required artifacts, generated-package verification honors minimal-private,
  the workforce-skills-root gate exists, and the source-bundle public schema
  accepts the runtime's idempotency fields.

## v1.2.7 - 2026-08-16

- Memory curation no longer classifies ordinary Korean sentence endings as prompt injection. Explicit override phrasing remains screened; actual tool permissions remain enforced by the broker.

- The A2A agent card version pin had been left at 1.2.4 through two releases; the
  bump script moves it with everything else now.

## v1.2.6 - 2026-08-15

- **Project map (Perk) reaches the agent and grows from work.** The recall hook
  no longer trims the whole slice at the layer budget; a project being edited by
  another session serves its last complete map (`refreshStatus=stale_served`);
  declared-graph load truncates after selection with per-node edge budgets;
  non-ASCII query words are kept; empty matches hand over entry points instead of
  nothing; one malformed sitemap no longer closes the library. A contact ledger
  (touched paths + stated intent per session, no content, append-only) feeds
  `co_edited` files into slices; `coverage()`/`drift()` diagnostics; every edge
  carries its authority (A0–A3). `.agentlas` is never indexed; OS-owned roots are
  refused before the bootstrap lock; Unicode identifiers become symbols.
- **Behaviour change:** `project_bootstrap.py` `auto_bootstrap` now defaults **on**
  — the three maps are seeded on a project's first contact from any tool, without
  a consent prompt (opt out with
  `AGENTLAS_PROJECT_BOOTSTRAP_AUTO=0`). `project_bootstrap.py` and
  `memory_hook.py` join the runtime release asset.
- **Phase B (2026-08-15 evening).**
  - `agentlas-one` reads `contracts/runtime-registry.json` for every runtime's
    instruction file, hook file and hook pack (hardcoded lists remain only as
    the registry-less fallback); registry grew to 18 rows (amp, warp, amazonq).
    Installer/registry parity is a contract.
  - Runtime drift now surfaces where the owner looks: the session-end hook runs
    one background check per day (opt-out `AGENTLAS_ONE_DRIFT_CHECK=0`),
    `agentlas-one status --drift [--now]`, a `Drift` line in `status`, and a
    `⚠ drift N` marker in the Claude Code status line. Detector moved to
    `agentlas_cloud/runtime_drift.py` (shipped in the runtime home).
  - Cross-platform wiring CI is green again: runners get jsonschema/referencing,
    and a Windows runtime home copied by `ln -s` is accepted instead of rolled back.
- **Runtime × Model architecture (PRD 2026-08-15) — Core track.**
  - `agentlas-one uninstall [--purge]`: backs every touchpoint up to a timestamped
    tar.gz, then removes hook entries (Claude/Codex/Cursor/Antigravity), marker
    blocks, the status line and state atomically; idempotent.
  - `agentlas-one status --runtimes [--json]`: per-runtime support matrix from the
    new declarative registry `contracts/runtime-registry.json` (grade A–E, install
    level L0–L3, access path, ACP command).
  - Stdlib-only ACP v1 client (`agentlas_cloud/networking/acp_client.py`):
    initialize → authenticate (menu, not priority) → session/new model list with
    zero text parsing; produces `transport=acp` capability descriptors.
  - `session_inventory[]` now carries `provider` and `access_path` as its own
    channel; provider/model identities are scrubbed from descriptor features.
  - Agent Plugins 1.0 manifests (`plugin.json`, `mcp.json`) + gate.
  - Installer: Codex prompts/skills decision is feature-detected
    (`codex features list`), version threshold only as last resort.
  - `scripts/check-runtime-drift.py` + daily workflow: pins vs ACP registry,
    matrix health, capability diffs — detect only, never auto-apply.
  - Fix: installer default `HEPHAESTUS_REF` had stayed at v1.2.4 after the v1.2.5
    release; `verify-install-docs.sh` now checks that pin.
  - `sync-adapters.sh --check` now enforces the builder canon and interview
    contract mirrors (previously matched by luck, never compared).


## v1.2.5 - 2026-08-15

- **Project map is seeded on first contact from any tool.**
  Bootstrapping previously ran only for a fixed set of routing tools, so a session
  that opened with any other tool never received a project map. The seed now runs on
  the first Agentlas tool call that resolves a folder, once per root per process.
- **Wider read surface for the generated map**, reported through the MCP handshake.
- **Adapter mirrors stay byte-identical** to the canonical source (Claude, Codex).

## v1.2.3 - 2026-08-14

- **Universal Command Parity across Claude Code and all Host Adapters.**
  Both GitHub README full command names (`/agentlas <subcommand>`) and direct shorthand
  aliases (`/hep-<subcommand>`) are cleanly unified and supported across Claude Code,
  Codex, Antigravity, Gemini CLI, Cursor, and OpenCode.
- **Support for `graph` and `one` in unified `/agentlas` dispatcher.**
  `/agentlas graph` maps directly to `hep-graph.md` and `/agentlas one` / `/agentlas-one`
  maps to `agentlas-one.md` across all prompt and workflow entrypoints.
- **Zero adapter drift verification.**
  Synchronized and validated all 14 canonical plugin commands, prompt templates, and
  universal skills with standard grep-safe verification gates.

## v1.2.2 - 2026-08-14

- **Release and adapter verification stay reproducible after local QA work.**
  Public package gates now keep private memory fixtures and generated ontology
  material out of the source/release boundary while still running them when a
  private checkout provides them. Installer, runtime-home, Windows wiring,
  upload-redaction, and adapter-sync checks now share the same fail-closed
  contract.

## v1.2.1 - 2026-08-14

- **Super Ontology is retired from active surfaces.** Core no longer ships its
  schemas, templates, generated seeds, package contract entry, runtime kernel,
  CLI status command, or validation gates. Agent Ontology (AO), Agent Workforce
  Ontology, the local semantic ontology, Context Map, and Career Graph remain
  independent active systems.
- **Runtime installation fails closed across release skew.** The installer now
  requires both platform-helper symbols before it reports a helper load as
  successful, so an older archive cannot fall through to a missing Python
  resolver. The graph skill is shipped through every declared adapter mirror
  instead of being referenced only by an untracked local path.

## v1.2.0 - 2026-08-12

- **The local Core MCP server now starts on native Windows.** Windows Claude
  Code, Codex, Cursor, OpenCode, Amp, Copilot CLI and Amazon Q spawn stdio MCP
  servers without a shell, but every host registration pointed at an
  extensionless bash runner — so on Windows the local Core could not start at
  all and every session silently fell through to the remote Hub. All eight
  registrations now render from one launch vector, `PYTHONPATH` is written in
  native form with the platform separator, and `.cmd` shims are installed for
  the commands that need them.
- **`agentlas-one on` works on a stock Mac.** The runner now prefers the
  runtime's own Python over whatever is first on `PATH`; macOS ships 3.9.6,
  which could not parse the One workspace module, and the only symptom was
  `(verification failed)` with no error.
- **The managed command list is derived, not typed out.** It had been written
  by hand in seven places, and all seven omitted `agentlas-one` and `hep-graph`
  — the documented switch was not a command on any machine that had not been
  hand-edited.
- **Agents built and borrowed locally accumulate experience and self-evolve
  even when One is off.** An agent's own experience is its asset; it is no
  longer gated behind the One switch.
- **Content screening no longer decides what a memory is allowed to say.**
  Judgment stays with evidence and shape; the screening pass that tried to
  classify meaning by word list is removed, and the canonical curator ruleset
  now actually reaches the installed runtime.

## v1.1.111 - 2026-08-12

- One projects durable soul blocks into a rebuildable incremental semantic index. The soul file remains authoritative, and hosts without the index retain their previous recall behavior.

- Recall reuses the runtime instance to avoid repeated initialization.

## v1.1.110 - 2026-08-12

- **Built packages follow the planned folder layout.** A2A, tools, permissions,
  hooks and provenance projections, plus thin `CLAUDE.md` / `GEMINI.md`
  adapters over the canonical core.
- **Experience pipeline v2.** Borrowed agents harvest from their own drawer, and
  evidence-shape governance plus reference framing decide what is allowed to
  become durable.

## v1.1.109 - 2026-08-11

- **One curator ruleset for every surface.** Three curators had drifted apart —
  one judging semantically, one discarding before the gate, one rejecting
  deterministically — so the same learning survived on one product and vanished
  on another. `system-agents/curator-ruleset.json` is now the canonical judgment
  table (kinds, evidence requirements, downgrade rules, concurrency, budgets)
  and every executor reads it instead of reimplementing it.
- **The One drawer is write-protected everywhere.** Direct edits to
  `~/.agentlas/one` are refused with a reason pointing at the Memory Events
  envelope. Recall stays free.
- **A learning cannot be recorded twice.** Tickets get deterministic
  content-hash IDs under a ledger lock, so double hooks, concurrent sessions and
  manual reruns no longer duplicate one learning. A new entry may also name the
  block it replaces; the old one is hidden from recall rather than deleted.

## v1.1.108 - 2026-08-10

- **Anonymous build telemetry.** `hep-build` runs locally without sign-in, so
  there was no signal on where builds actually fail. The engine now sends
  counters only — a locally generated install id, which step ran, whether it
  passed, a machine error code, a duration. Never a path, a package name, a
  prompt, or error text, and the allowlist is enforced on both ends. It runs
  detached with a 3-second timeout and swallows every failure, so an offline
  build is byte-identical to one with telemetry off. `AGENTLAS_TELEMETRY=0` and
  `DO_NOT_TRACK=1` both stop it.
  Existing installs are treated as undecided rather than opted out: they carry a
  `telemetry: false` written by an old default that no command could set and
  nobody chose, so only a value carrying the explicit marker counts as a choice.
- **A goal survives the session that created it.** Objective, tasks, cycle
  accounting and budget are now durable on the same goal id as the workforce
  roster binding, so hosts rejoin work that outlives one session.

## v1.1.107 - 2026-08-10

- **Switching Agentlas One on now arms every checkpoint by itself.** `on` used
  to write the identity and nothing else: the memory checkpoint was installed
  only by a separate `install` step, and a status line owned by someone else
  aborted that step before the checkpoint was ever reached. Both failures read
  to a user as an assistant that never learns anything, with no error anywhere.
  The status line and the checkpoint are now independent, and `off` removes
  every checkpoint it placed while leaving unrelated hooks, status lines, and
  settings untouched.
- **The checkpoint reaches three more runtimes.** OpenCode harvests on
  `session.idle` by handing the runtime the assistant text it already holds,
  because no OpenCode plugin ever receives a transcript path. OpenClaw has no
  session-end event at all, so a hook pack listens on the commands that close a
  session and reads the previous session entry. goose resolves its session file
  from the `SessionEnd` payload. Cursor is wired through its `stop` hook, whose
  payload carries a transcript path. Assistant ownership is tracked by message
  id, so an envelope a user pastes into a prompt is never harvested.
- **Runtimes without a session-end event are named rather than implied.**
  Amazon Q Developer CLI, Amp, Warp, and Hermes Agent expose no such event, so
  they carry no checkpoint and the runtime matrix says so.

## v1.1.106 - 2026-08-10

- **Agentlas One now persists as one owner-bound personal agent across supported
  hosts.** The new `agentlas-one` runtime switch seeds the canonical single-agent
  memory layout, installs non-blocking Stop checkpoints, and injects the same
  operating contract into Claude Code, Codex, and Antigravity entrypoints.
- **Conversation learning crosses the runtime boundary without copying raw
  transcripts.** Workers emit bounded Memory Events, the runtime converts them
  into append-only tickets, and a deterministic curator admits only supported
  durable memory while keeping experience chips as explicit promotion candidates.
- **Public adapters remain portable.** Runtime instructions and code comments are
  English, private repository fallbacks are absent, user-owned hook configuration
  is preserved, and every Stop path fails open instead of blocking a session.

## v1.1.98 - 2026-08-05

- MCP parameters that echo a pinned WorkOrder or Selection use compact descriptions while handlers still validate the canonical schema. Authored parameters retain full schemas, and Desktop metadata remains present.

- **The install pin catches up with the release.** `install-all-runtimes.sh`
  still pointed at v1.1.95 through two releases, so a fresh one-touch install
  landed two versions behind what the manifest advertised. The bump script moves
  one baseline value, which silently skips every file already sitting on a
  different version — the six README install lines were on v1.1.97 and
  manifest.json is not in its file list at all. All of them now move together.

## v1.1.97 - 2026-08-03

- **The version a build reports is the version it is.** v1.1.96 shipped with
  `1.1.95` hardcoded in the MCP server's SERVER_INFO handshake and in the CLI's
  own report, so every client saw the previous version from a build that called
  itself 1.1.96. Only manifest.json had been bumped. Desktop's pinned Core
  Workforce MCP contract probe caught the mismatch; both strings now follow the
  manifest, and the Claude and Codex adapter mirrors carry the same value.

## v1.1.96 - 2026-08-03

- **A command typo stops being a Hub search.** Any unrecognised top-level token
  used to fall through the natural-language shorthand: `hephaestus login`,
  `status`, `doctorr` and `init` each spent seconds on a Hub routing query and
  then exited 0, reporting success for something the user never asked for and
  leaving scripts unable to detect a renamed or mistyped command. A bare single
  word is now rejected the way second-level typos already were — a named
  boundary and a non-zero exit — while multi-word requests keep routing, in
  English and Korean alike, and the message names how to run the token as a
  request on purpose.
- **`context` refreshes a project instead of conjuring one.** Running
  `context refresh` in a directory with no state created 48 files, including
  ontology and career-graph databases, credentials and signing scaffolding, and
  a rewritten .gitignore — with no consent, and directly against the product's
  own promise that `project init` is explicit. Terminal already refused to do
  this; Core was overriding that boundary from underneath. An uninitialized
  directory is now left untouched and told to run `project init`.
- **Errors name their boundary.** `runtime bundle` on a folder with no
  agentlas.json raised a raw Python traceback that also disclosed the internal
  install path; it now reports a missing manifest and points at `wizard`. Every
  reachable context-map error carries a next action instead of a bare code.

## v1.1.95 - 2026-08-02

- **Installed runtimes remain immutable during project-memory refresh.** The
  recall backstop now distinguishes the packaged Hephaestus runtime from a
  user's active project, preventing generated ontology state from being written
  into signed application resources.

## v1.1.94 - 2026-08-02

- **Signed owners and free-plan runtimes remain callable through Workforce.**
  Runtime preparation now preserves the validated entitlement and zero-cost
  authority needed to execute exact releases without silently refusing an
  otherwise authorized task.
- **Local internal work stays outside the public runtime artifact.** Generated
  operator-only state is ignored while the release workflow continues to build
  from its explicit end-user runtime allowlist.

## v1.1.93 - 2026-08-02

- **One and project Work share one portable authority contract.** One remains
  the sole controller of One sessions, the first ordered project agent controls
  Work tasks, and additional agents remain turn- or task-scoped rather than
  silently taking over a session.
- **Model judgment owns semantic routing and recovery.** Host adapters expose
  explicit source scopes and typed evidence, while keyword routing, silent
  agent substitution, static recovery copy, and raw operational errors remain
  outside the customer-facing contract.
- **External host adapters no longer impersonate product ownership.** The
  Hephaestus global adapter is optional, and Network discovery returns exact
  releases for the active model to select, validate, and execute locally.

## v1.1.92 - 2026-08-01

- **Portable packages reject generated local state.** Package validation and
  upload filtering now keep rebuildable Code Map, graph, and local runtime
  artifacts out of shared bundles instead of treating machine-specific output
  as authored package content.
- **Installation updates stay recoverable.** Runtime delivery verifies the
  staged install before switching the active runtime and retains the previous
  known-good release when validation fails.
- **Ambiguous model sessions fail with a useful explanation.** When more than
  one active capable session could own a stage, allocation remains unresolved
  and describes the user choice required without leaking candidate or receipt
  internals.

## v1.1.91 - 2026-07-31

- **Context relationship receipts keep a stable readability margin.** Real
  installed-plugin testing found that a current project map could put
  `context.slice` 167 bytes over the 16 KB host UX limit even after v1.1.90's
  first compaction pass. Impact and slice now retain a smaller prioritized
  working set, report exact omission counts, and leave the complete graph local.

## v1.1.90 - 2026-07-31

- **Context relationship tools stay readable in chat hosts.** MCP
  `context.impact`, `context.slice`, and refreshed `context.verify` now return a
  bounded working set with explicit omission counts while Core retains the
  complete graph and verification receipts locally.
- **Natural-language routing no longer repeats the full discovery menu.** Hub
  candidate results are capped at ten exact rows with an omitted-row count, and
  routing uses the same compact project-readiness summary as Context Map tools.
- **An optional model-allocation decision is truly optional.** Omitting
  `decision` now falls back to the active host session without the misleading
  `decision_not_object` validation issue; a supplied non-object still reports
  that contract error.

## v1.1.89 - 2026-07-31

- **Context Map results prioritize the requested answer.** Codex and other MCP
  hosts now receive a compact project-readiness summary instead of repeated
  bootstrap internals, local path inventories, and long warning arrays on every
  `context.locate`, `context.refs`, `context.slice`, `context.impact`, and
  `context.verify` call.
- **A stale verification map explains its recovery.** `context.verify` now marks
  the refusal as repairable and returns the exact `refresh=true` retry argument
  instead of only the internal error code.

## v1.1.88 - 2026-07-31

- **The main CLI now reports its exact installed release.** `hephaestus
  --version`, `hephaestus -V`, and `hephaestus version` return the runtime's
  `RELEASE` value, while a source checkout reports the version pinned by its
  installer. Missing release metadata fails clearly instead of falling through
  to an unrelated command or the full usage screen.

## v1.1.87 - 2026-07-31

- **Agentlas Terminal keeps the `agentlas` command.** The Core installer no
  longer creates an `agentlas` alias for Hephaestus, so the independently
  released Terminal cannot be shadowed by `~/.local/bin`.
- **Existing Terminal installs are preserved during upgrade.** The installer
  removes only the exact legacy Core-owned shim and leaves npm, Homebrew, local
  source, and user-owned `agentlas` launchers untouched.
- **Core command documentation now names the correct executable.** Global
  router management uses `hephaestus global` or `hep-global`; it no longer
  teaches a command owned by the independent Terminal product.

## v1.1.86 - 2026-07-31

- **Local verification files stay visible without becoming public artifacts.**
  Code Map now discovers bounded local test and fixture paths even when Git
  intentionally ignores them, fingerprints those files, and links their symbol
  references into the verification graph.
- **Local and CI remain selectable execution channels.** A project may prove a
  change with local tests, GitHub workflows, or both; ignored local tests no
  longer appear missing merely because the public repository excludes them.
- **Large product repositories fail closed on graph truncation.** Verification
  edges have a larger bounded budget, and a truncated verification graph makes
  the map incomplete instead of silently passing.

## v1.1.85 - 2026-07-31

- **Code, tests, CI, and release versions now share one impact graph.** Code
  Map v2 embeds `agentlas.verification-map.v1`, linking source files to tests,
  package test commands, CI workflows, and version contracts.
- **CI and manifest edits invalidate the canonical map.** Workflow and version
  files participate in the fingerprint instead of sitting outside the stale-map
  check.
- **Completion verification follows verification responsibilities.**
  `context impact` now returns affected test, CI, and version files, while
  `context verify` accepts one valid execution channel per change: local
  tests/test commands, CI workflows, or both. The selected channel must carry
  reviewed execution evidence; version contracts remain a separate release
  responsibility instead of being mistaken for test evidence.
- **The functional AI Sitemap exposes verification nodes and edges.** Product
  surfaces can show which test and release gate owns a code path instead of
  presenting source modules alone.
- **Stale CI references are visible failures.** A workflow or package test
  command that names a missing test file becomes a verification-graph issue and
  blocks completion until fixed or explicitly waived.

## v1.1.84 - 2026-07-31

Route discovery now refuses sensitive input before any remote request or
rebuildable cache write.

- **Secrets and private paths stop at the local boundary.** Network, Cloud,
  Hub, and route MCP entry points reject credential-like values, `file://`
  references, and private local paths with a bounded remediation message.
  Rejections report zero remote calls and zero project writes without echoing
  the unsafe input.
- **Hub search caches no longer retain query material.** New cache rows store
  only a schema version, keyed digest, bounded result rows, and public slugs.
  Legacy cache files that may contain a query field are purged before lookup,
  and offline responses expose only cache availability and entry count.
- **Empty optional JSONL ledgers are valid package artifacts.** A required
  append-only ledger may begin with zero rows unless its contract declares a
  positive `minLines`; non-JSONL artifacts and explicitly populated ledgers
  keep the existing non-empty gate.
- **Single-agent packages stay on the single-agent contract.** The generated
  package verifier no longer mistakes the explicit `single-agent` topology for
  a team merely because worker metadata is present.

## v1.1.83 - 2026-07-30

Builder, Hub, Cloud, Network, and WorkOrder now share one open routing-resume
contract.

- **Builders 01, 02, and 03 emit the same card and package shape.** Single
  agents, teams, and packaged agents use one English semantic resume with
  communities, skills, knowledge, roles, inputs, outputs, title, and summary.
  Desktop and Terminal ask creators for an ordinary-language purpose; the
  connected model authors the English routing card.
- **Semantic IDs are open-world ontology concepts, not an official
  dictionary.** Stable English `community:*`, `skill:*`, `knowledge:*`, and
  `role:*` IDs are embedded and connected to the graph. The bundled ontology
  snapshot supplies aliases and relations but never rejects a faithful new
  concept.
- **Execution context cannot erase a relevant agent during discovery.**
  Runtime, language, modality, authority, forbidden-authority, and MCP
  availability remain visible for ranking and prepare-time enforcement but do
  not make an agent undiscoverable.
- **Lean and expanded WorkOrders keep one canonical digest.** The source
  service now freezes the normalized order used by the privacy boundary, so
  search, selection validation, and exact-release preparation agree even when
  optional list fields were omitted.

## v1.1.82 - 2026-07-30

The work-order form now describes what the catalogue can actually answer.

- Authority requirements act as ranking signals when the inventory lacks that vocabulary; prepare-time permission pins enforce execution authority. Hub relaxation requires the declared `gap:requirement-vocabulary-unsupported:authority` capability.

- Missing optional list constraints normalize to empty arrays before validation and canonical digest computation, so lean and full-form WorkOrders keep the same contract identity.

- **Authoring guidance drops the dead fields.** The hep-network command (all
  host variants) now constrains a hire only through communities, skills,
  knowledge, runtimes, and languages, and never fills
  requiredToolCapabilities, requiredAuthorities, forbiddenAuthorities,
  consumes, produces, requiredRoles, or modalities — tools, authorities,
  and modalities attach to the executing runtime; ordinary inputs/outputs
  belong in the task text and inter-slot handoffs in edges.

## v1.1.81 - 2026-07-29

Session learnings now feed every host's recall — the memory loop's supply side
is closed.

- Recall capsules direct sessions to record evidence-backed project learnings through the memory workflow, without storing secrets or raw transcripts.

- The index backstop refreshes when PM documents are newer than the index, prioritizes recent learnings, and includes each source document’s own modification date.

## v1.1.80 - 2026-07-29

The recall corpus regenerates from any surface — Desktop is no longer its
single point of failure.

- A host-independent backstop regenerates missing or expired project indexes with bounded, secret-filtered content. A fresh Desktop materialization remains authoritative for the TTL window.

- Reference-mode staffing keeps full candidate data in Core, permits optional echoed attachments, resolves menu ordinals, and derives `prepareAttempt` on the server.

## v1.1.79 - 2026-07-29

A recalled memory now confesses its age instead of impersonating the present.

- Recall labels source age from the source document and identifies deleted sources. Sources older than seven days carry a staleness notice; unresolvable metadata remains unannotated.

## v1.1.78 - 2026-07-29

A machine that only ever runs inside host sandboxes now heals itself.

- **The SessionStart hook starts the runtime auto-update worker.** v1.1.77
  repaired the update path, but a machine whose every tool command runs inside
  a host sandbox could never execute the repair: the in-command trigger cannot
  write `~/.agentlas` from inside the sandbox, so the runtime stayed pinned to
  a stale release forever while the plugin itself kept updating through the
  host marketplace. Host hooks run outside tool sandboxes, so the memory hook
  now starts the same TTL-gated, digest-verified, fail-silent worker on
  SessionStart only — after recall output is flushed, reusing the existing 24h
  marker/lock gating, never raising into the hook contract. Verified end to
  end: with an empty HOME and no installed runtime, one SessionStart hook
  invocation bootstrapped a digest-verified runtime with no terminal and no
  human step. Fleet effect: any machine running Claude Code or Codex with the
  marketplace plugin converges on the latest runtime at its next session
  start; Desktop and plain-terminal use remain the other unsandboxed triggers.

## v1.1.77 - 2026-07-29

The update check survives the sandbox every hosted runtime puts it in, and a
permission denial is named as one.

- **A denied cache write no longer kills a successful release check.**
  Reproduced under a deny-home-write sandbox — the state Claude Code, Codex,
  Cursor and Antigravity run commands in: after a successful GitHub release
  fetch, writing the `update-check.json` TTL cache raised `EPERM` and discarded
  the answer, so even `hep-update --check` died with a raw traceback and
  auto-update silently never ran on sandboxed machines. The cache is an
  optimization, never part of the answer; its write is now best-effort and the
  check path completes inside sandboxes.
- **EPERM/EACCES reports as a sandbox boundary, not as network or disk.** The
  previous wording blamed connectivity ("could not reach github.com") or free
  disk space precisely when neither was at fault. A permission denial anywhere
  in the failure chain now returns `check_blocked_sandboxed` /
  `install_blocked_sandboxed`, names the denied path, and tells the user to run
  `hephaestus hep-update` from a regular unsandboxed terminal once.

## v1.1.76 - 2026-07-29

A credential is identified by where it lives, not by a word in its filename.

- Upload scanning and runtime read policies match credential-store path segments instead of filename substrings, covering both rooted and nested stores while preserving ordinary files.

- Upload combines the current read-policy defaults with files explicitly referenced by the package’s agent cards, excluding credential stores.

## v1.1.75 - 2026-07-29

A package is priced and staffed as what it actually ships, and Codex can publish
again.

- Package structure determines agent versus team when it contradicts a declared type; corrections are recorded. Silent structure preserves the author declaration, and plugins are not retyped.

- **Codex gets an upload entrypoint back.** Codex 0.117+ replaced custom prompts
  with plugin skills, and only build/network/cloud/storm ever had a skill, so the
  installer pruned the `hep-upload` prompt and advertised nothing in its place —
  publishing simply disappeared from that host. Adds the `hephaestus-upload`
  skill across every adapter mirror. Upload stays a separate surface from
  `/hep-network` deliberately: staffing is a read, publishing is a write that is
  hard to take back.

## v1.1.74 - 2026-07-29

Staffing over MCP stops shipping the filing cabinet. A host LLM now reads a
decision menu, answers with a number, and Core resolves both against the
session it already holds.

- Network discovery fields use faithful English translation of the requested work. The `languages` slot retains the required output language; marketplace search remains multilingual.

- **The résumé is compiled and stored on upload.** The offer brief is generated
  from package files at publish time — it had been dead code with zero callers —
  the candidate menu is widened, and boundary failures are no longer misnamed.
- **Uploads repair instead of refusing.** A package shipping fewer than ten
  benchmark cases has one synthesised from its trigger examples, and the card
  lint counts inline cases it can see.
- Search keeps audit-weight fields in Core, returns candidate ordinals and evidence counts, and computes digests over the stored originals. `fullDossier: true` retains access to the original representation.

- `assignments[].candidateOrdinal` resolves against the pinned menu. Out-of-range values and conflicts with an explicit release ID are refused. The canonical Selection schema remains unchanged.

- **The resolve-by-session branch had never once run.** `_call_tool` binds
  `store` twice, making it a function-local that was unbound on that path, so
  every attempt raised `UnboundLocalError` — not a `FederationSessionError`, so
  the handler's own except never caught it and the call died. The escape from
  echoing a ~461KB candidate set therefore stayed theoretical from the day it
  was written. First live proof it works: validation accepted in 0.03s from a
  3.6KB request.
- Validation may resolve omitted `candidateSet` and `federationResult` from the pinned session while rechecking its digest, expiry, and lineage.

- Eligibility uses facts owned by the runtime instead of exact equality against small hand-written prose lists.

- `schema_max_length` and `schema_min_length` include `limit` and `actual` so callers can repair the specific violation.

## v1.1.72 - 2026-07-27

- Supersedes v1.1.71: the MCP server/agent-card version constants
  (mcp_stdio SERVER_INFO, cli agent card, a2a card) had sat at 1.1.67 since
  that release and failed Desktop's pinned-contract preflight. bump-version.sh
  now snaps these canonical in-code pins and the host adapter manifests to the
  release version regardless of the value they carry, so a pin that fell
  behind can never stick again.

## v1.1.71 - 2026-07-27

- Supersedes v1.1.70, whose release asset failed the updater's host-adapter
  version validation (adapter plugin manifests still carried 1.1.69) and was
  therefore never installable. Adapter mirrors are re-rendered from the
  canonical core and every version pin now moves together.

- **Upload repair loop for the workforce résumé.** When registration returns
  `workforce_resume_incomplete`, the uploader now surfaces the server's full
  mismatch list and pinned ontology menus verbatim (no truncation) so the
  submitter's own model can repair the card and resubmit; the hep-upload
  command adapters document the loop.

- Built routing cards include the workforce résumé block validated against the pinned ontology. Unknown IDs are errors, a missing block prevents routing readiness, and empty roles remain valid when no canonical role fits.

## v1.1.69 - 2026-07-27

- **Updates return to the command-triggered contract.** Desktop startup and
  `/hep-*` commands continue to launch the same digest-verified, rate-limited,
  non-blocking updater. Fresh installs no longer create a separate six-hour OS
  scheduler.
- **Older periodic jobs retire themselves.** The first command, Desktop update
  worker, or reinstall after upgrading removes the legacy macOS LaunchAgent,
  Linux user timer, or Windows scheduled task. Removal checks the loaded macOS
  service label as well as the current plist path so a job loaded from an
  obsolete runtime or QA location is not left behind.
- **The public update instructions now match runtime behavior.** Installation
  output and host-specific guides describe atomic runtime replacement and
  adapter reconciliation without promising or recreating a periodic daemon.

## v1.1.68 - 2026-07-26

- Card routing uses the local sentence model shared by ontology and Hub ranking, with token hashing only as an explicit degraded fallback. Trigger phrasing contributes to vectors; anti-triggers remain excluded.

- **Locally registered teams can be prepared again.** Local team runtime
  bundles shipped without an execution graph, so `prepare_execution` rejected
  them with `team_execution_graph_missing` and an empty roster. A team package
  now projects its own organization — entrypoint as manager, `agents/<member>`
  directives as workers, read through the same bounded no-follow reader — and a
  package with no readable member directive fails closed instead of having an
  organization invented for it.
- **A rejected preparation reports its own cause.** The MCP layer bound a
  rejected preparation anyway; goal binding then failed and the response
  claimed `preparedButUnbound: true` with the real `issues[]` dropped,
  inverting cause and effect. Binding is now gated on real readiness, so
  `preparedButUnbound` only ever means "prepared, then binding failed".
- **An unpopulated requirement dimension no longer empties every slot.** The
  published inventory declares zero `role:*` terms, so any work order using the
  documented `requiredRoles` vocabulary hard-filtered every candidate and
  returned an empty menu. A requirement dimension that no live profile
  populates is a data gap, not a discriminator: it is demoted to a ranking
  signal and reported as `gap:requirement-vocabulary-unsupported:<kind>`.
  Coverage is measured per dimension, never per term — demoting an individual
  unmatched term would let a poisoned candidate through whenever no profile
  declares the exact required term.

## v1.1.67 - 2026-07-26

- **The documented `hephaestus context` command now reaches the Context Map
  engine.** The public shell dispatches `refresh`, `locate`, `refs`, `slice`,
  `impact`, and `verify` directly instead of passing the unknown word
  `context` to the natural-language router.
- **A refresh is not considered successful until the canonical map exists.**
  Code Map v2 covers CommonJS and ESM source extensions, carries definitions
  and backlinks, and projects bounded module, entry-point, and dependency
  nodes into the functional AI Sitemap.
- **Completion verification is an actual gate.** Unreviewed impacted files
  return a blocked receipt and a nonzero process exit; a fully reviewed impact
  set returns a passing receipt and exit zero.
- **Context graph traversal no longer repeats edges.** Context Slices retain
  one canonical copy of every selected project or dependency relationship.

## v1.1.66 - 2026-07-26

- **Code maps now have one dependency-capable contract on every host.** The
  canonical `agentlas.code-map.v2` generator writes definitions, reverse
  references, module edges, and a source fingerprint instead of distributing a
  weaker map under the same filename. Fingerprint checks refresh stale maps
  without requiring a user to remember a maintenance command.
- **Concrete work receives a bounded Context Slice, not a project dump.**
  `context slice` inherits active project goals and constraints, then selects
  definitions, backlinks, interfaces, and related files by structural
  dependency. Claude, Codex, Desktop, Terminal, Stormbreaker, and Workforce use
  the same local implementation; Hub and Cloud discovery never receive project
  source or local map paths.
- **Mutation and completion have inspectable change-impact receipts.** The
  local MCP and CLI expose `context locate|refs|slice|impact|verify`. Claude and
  Codex hooks add a fail-open reverse-reference warning immediately before edit
  tools, while the Stormbreaker contract requires impact review before mutation
  and verification before completion.
- **The sitemap is no longer treated as a file-count prompt.** Bootstrap
  preserves operator nodes and adds typed project, goal, constraint, and
  requirement nodes with dependency edges. File/directory inventory remains
  separate from the functional project context inherited by a task.

## v1.1.59 - 2026-07-24

- **Memory-architecture parity with Desktop and Terminal.** The hep runtime now
  carries the same unified memory contract: per-slug member cells (slug == cell
  key), self-evolution proposals mirrored to `.agentlas/evolution-proposals.json`,
  content-free context-source markers in the per-project ontology runtime, and a
  `python -m agentlas_cloud.memory_import` path (dry-run/apply/idempotent). A
  single source of truth (`memory_contract.py`) is cross-checked by
  `scripts/verify-memory-contract.sh` so the three products cannot drift.

## v1.1.58 - 2026-07-23

- **Global Agentlas OS Python entrypoints can no longer mutate a signed
  Desktop bundle.** POSIX and Windows runners now force Python bytecode off and
  pin any defensive cache prefix to a per-user path outside the application,
  even when a caller supplies hostile environment values or selects the
  Desktop-bundled interpreter explicitly.
- **Installed and self-updated runtimes keep the same boundary.** The one-touch
  installer, atomic runtime updater, direct ontology/memory/career entrypoints,
  and Claude/Codex adapter mirrors all emit the protected Python launch
  contract, preventing a managed global runtime from invalidating the
  Developer ID resource seal after Desktop starts.

## v1.1.57 - 2026-07-23

- **Desktop v0.8.65/v0.8.66 can escape the macOS stale-updater loop through
  the independent Agentlas OS update channel.** The bridge runs only from a
  digest-verified v1.1.57-or-newer runtime and the affected app's bundled
  Python, requires the exact official bundle identity, Developer ID,
  designated requirement, Gatekeeper approval, and an exact logged
  `app.asar/dist` failure, then atomically quarantines only the cited signed
  `ShipIt/update.*` payload. It never modifies Application Support, the update
  journal, recovery copies, pending downloads, `ShipItState.plist`, or the
  installed application. A bilingual popup asks the user to restart Agentlas
  or press Retry after recovery is ready.
- **The recovery bridge is serialized, bounded, and resumable.** A dedicated
  owner-only `flock` prevents concurrent workers, a 20-second deadline limits
  the already-shipped updater call, and one exact payload is signature- and
  inode-verified before each same-filesystem rename. A committed quarantine is
  recognized again after interruption; additional exact payloads are handled
  on later launches while unrelated updater entries remain preserved. The old
  Desktop state machine remains responsible for its own remaining cleanup.
- **Historical release assets remain reproducible.** The runtime packager
  requires the new recovery files only for v1.1.57 and newer; rebuilding
  v1.1.56 still produces its original byte-identical archive and checksum.

## v1.1.56 - 2026-07-21

- **The Desktop recovery bridge now survives the exact v1.1.50 updater shipped
  by Desktop v0.8.58/v0.8.59.** The retry implementation and exact marker live
  inside `agentlas_cloud`, which the old updater already copies into the
  managed runtime. A failed first repair is retried on later Desktop launches
  from only the selected v1.1.56-or-newer managed runtime; no website download
  or installer is used.
- **The repair rejects a linked CodeResources leaf.** Both the first-run and
  managed retry paths require the signature plist to be a regular single-link
  file before reading it, in addition to the existing directory, sealed-file,
  inode, hard-link, and post-repair signature gates.

## v1.1.55 - 2026-07-21

- **The installed Desktop recovery bridge now genuinely retries after the
  runtime is already current.** In addition to the first digest-verified
  temporary extraction, the bridge accepts only the exact regular version
  directory selected by the managed `~/.agentlas/runtime/current` symlink,
  with the exact repair marker and a v1.1.55-or-newer `RELEASE` marker.
  Arbitrary copied directories, linked roots, linked or hard-linked markers,
  and stale managed versions fail closed. This fixes the v1.1.54 path mismatch
  that made post-install retries report `not_verified_update_context`.

## v1.1.54 - 2026-07-21

- **Affected Agentlas Desktop v0.8.58/v0.8.59 installations can restore their
  original signed-resource seal without a website download or reinstall.** A
  digest-verified runtime bridge runs only from the bundled Desktop Python and
  only for the exact official bundle, Team ID, Developer ID authority,
  designated requirement, and affected versions. It rejects linked ancestors,
  hard links, signed resources, and changed inodes; removes only unsealed
  generated `__pycache__/*.pyc`/`*.pyo`; records cache digests locally; and
  requires `codesign` plus Gatekeeper verification afterward. The installed
  runtime retains the bridge and retries it on every Desktop-started update
  worker until the app seal is healthy.

## v1.1.53 - 2026-07-21

- **Confirms the restored tag-triggered auto-release pipeline.** v1.1.52's
  release had to be published by hand because a prior cleanup removed the CI
  workflow from the repo (0 registered workflows). The workflow is now tracked
  again as a lean build+publish job (no test suite in the repo; the build step
  self-enforces the runtime allowlist). No runtime behavior changes since
  v1.1.52 — this patch exists to verify that pushing a `vX.Y.Z` tag once again
  builds and publishes the verified runtime asset automatically.

## v1.1.52 - 2026-07-21

- **The runtime self-update command is now `hep-update` and auto-update is the
  default on every command.** `hephaestus update` is kept as a backward-compatible
  alias, and a new `bin/hep-update` wrapper joins the `hep-*` family (registered in
  the installer and adapter mirrors). The fail-silent, rate-limited background
  update check (`maybe_auto_update`) was hoisted to run once for *every* command
  instead of only the network/routing paths, so any invocation keeps the runtime
  current — still gated by `HEPHAESTUS_AUTO_UPDATE`/`HEPHAESTUS_UPDATE_CHECK` and
  skipped for the explicit `hep-update` command itself. The update-available
  notice and `install_command` now point at `hephaestus hep-update`. Applied to
  the root runtime plus the Claude and Codex meta-agent plugin mirrors.

## v1.1.51 - 2026-07-18

- **Republishing a same-slug Cloud asset no longer hard-fails on
  `428 client_upgrade_required`.** The publisher now reads the exact cloud id
  and revision from the 428 error body and retries the register call with
  `If-Match` + `x-agentlas-cloud-id`, so an intentional same-id overwrite
  proceeds instead of dead-ending. Applied to all three `agentlas_cloud/upload.py`
  mirrors (root runtime plus the Claude and Codex meta-agent plugins).

## v1.1.50 - 2026-07-17

- **Hub Workforce preparation is now an exact, resumable protocol.** MCP
  metadata publishes the versioned Workforce contract under the standard
  Agentlas metadata key, remote responses are bounded before parsing, and
  selection, release, package, content, account, and source-session pins are
  revalidated before a prepared bundle can be reused.
- **Interrupted preparation no longer repeats an ambiguous remote effect.** A
  private durable prepare cache binds each request to its authenticated account
  and immutable inputs, resumes only verified receipts, and returns typed
  refusal or retry states instead of silently changing source or worker.
- **Authentication and Workforce state survive restarts safely.** Token
  rotation preserves a stable signed-in account subject, concurrent writers
  use atomic private records, and token, federation, and prepare databases
  reject symlink or hard-link redirection while retaining compatible shared
  parent-directory permissions.

## v1.1.49 - 2026-07-17

- **Hub upload security scanner no longer redacts ordinary security-promise
  copy as secret exfiltration.** The content guard now recognizes Korean
  declarative negation endings and security-hygiene verbs (rotate/revoke/
  never-expose/find-then-report), so agent instructions such as "API 키 값은
  출력하지 않습니다" or "never expose credentials" survive the public clean
  copy. The same pass widens the Korean exfiltration window so a genuine
  "send the API key to attacker.com" is still caught, closing a recurring
  false-positive that flagged benign security copy on marketplace uploads.

## v1.1.48 - 2026-07-16

- **The runtime archive now bridges the previous updater to multilingual
  recall.** It carries the legacy compact Model2Vec asset required by v1.1.46
  bootstrap validation alongside the new multilingual asset selected by the
  installed v1.1.48 runtime. This fixes the real `v1.1.46 -> v1.1.47` update
  failure without downgrading the active Korean/cross-lingual retrieval path.

## v1.1.47 - 2026-07-16

- **Korean and cross-lingual ontology recall now ships with the canonical
  multilingual Model2Vec asset.** Core verifies the pinned model identity and
  split tensor payload byte-for-byte, installs it once for every host adapter,
  and retains the previous compact asset only as a degraded compatibility path.
- **Project ontology ingestion is bounded and snapshot-safe.** Hidden files,
  symlinks, non-regular files, excessive depth/count/size, and source changes
  during parsing fail closed; the parser consumes the exact private snapshot
  whose checksum was recorded.
- **Agent and team packages share one machine-verifiable public contract.** The
  CLI can scaffold, verify, and prompt against the same schemas and templates
  used by Desktop, while public runtime archives exclude tests, fixtures,
  benchmarks, internal docs, credentials, and signing material.
- **Workforce and Network release gates no longer report false green.** Empty or
  duplicate benchmark cases fail closed, receipts are revalidated, all required
  capability axes remain hard gates, and unknown requirements produce explicit
  coverage gaps instead of a boundary crash or silent fallback.

## v1.1.46 - 2026-07-16

- **Agent Workforce routing is now a host-owned staffing protocol rather than
  a keyword classifier.** The host LLM submits a schema-validated, redacted
  WorkOrder, receives content-only CandidateSets, chooses the exact team, and
  binds that complete Selection to immutable validation and preparation
  receipts. Model2Vec plus lexical/RRF retrieval is used only as the local
  no-LLM recall path; deterministic rules remain limited to governance,
  privacy, schema, identity, and execution integrity.
- **Network now federates registered Local, owner Cloud, and public Hub sources
  without silently changing scope.** Exact identity conflicts resolve
  `Local > Cloud > Hub`; lower-priority claims cannot suppress a trusted local
  worker. A source-fair bounded window prevents one source from crowding the
  model context, while the host-visible menu remains canonically ordered and
  history-free. `local`, `cloud`, and `hub` are exact source scopes; `network`
  is their sealed union.
- **Selected workers are fetched and executed by immutable source pins.** The
  source session, CandidateSet digest, definition, release, version, package
  hash, content digest, entity kind, complete WorkOrder, and complete Selection
  are rechecked before any remote bundle call. One immutable release can fill
  multiple legitimate role slots with one fetch and distinct roster rows;
  failures remain explicit instead of disappearing behind a success receipt.
- **The original production routing regressions are fixed and pinned.** AO
  governance applies only to mapped cards, same-stage workers are all invoked,
  private graph entities/relations/evidence inherit scope, and a domain
  mismatch is an additive signal rather than a hard candidate deletion. No new
  substring or keyword-list intent rules were added.
- **Local imports and remote responses are bounded before trust.** Explicitly
  registered local packages are read into one secret-checked immutable
  snapshot and all routing, MCP, team, worker, hash, and execution metadata is
  derived from those same bytes. Hub capability and bundle responses have
  pre-allocation size limits, federation sessions are durable with TTL/GC, and
  unverified or unsupported source capabilities fail closed.
- **The same Core contract is installed across Claude, Codex, Gemini,
  Antigravity, Cursor, OpenCode, and Terminal adapters.** Local-capable hosts
  expose one local OS MCP surface; Hub and Cloud remain OS-managed upstreams,
  avoiding duplicate tool names and direct remote bypass.

## v1.1.45 - 2026-07-16

- **Hub coverage gaps now cross every runtime through one finite contract.**
  Core accepts the complete 23-code aggregate vocabulary emitted by Web
  workforce search, including hard-eligibility exclusion classes observed in
  the Desktop Qwen run, while retaining minimum-count and no-eligible-candidate
  signals.
- **Unknown coverage reasons fail closed without leaking candidate data.** The
  candidate-set schema, host-selection validator, execution projection, Core
  reference index, and both adapter mirrors share the same allowlist. Golden
  vectors accept the live aggregate response and reject arbitrary reasons or
  candidate identities without reflecting the untrusted value in errors.

## v1.1.44 - 2026-07-16

- **Prepared staffing is now an executable organization contract.**
  `agentlas.workforce-execution-plan.v5` preserves the complete validated
  WorkOrder and Selection, binds an explicit deny-by-default permission policy,
  and distinguishes direct `agent` execution from a mandatory nested `team`
  manager/worker graph. `group` remains discovery metadata and cannot enter an
  executable roster.
- **Execution receipts prove actual workers instead of flattening teams.**
  `agentlas.workforce-execution-receipt.v2` records unique leader, planner,
  direct worker or packaged manager/worker/synthesis, top synthesis, and
  verifier invocations with truthful effort observability and runtime
  permission evidence. Missing structured plans, fallback, reordered or
  skipped nested workers, release drift, and fabricated success fail closed.
- **Tool choice belongs to the host LLM and authority remains deterministic.**
  A private `agentlas.workforce-tool-inventory.v1` snapshot is scoped to each
  slot/release/policy and never sent to Hub. The host planner selects exact
  capability bindings; Core recomputes the inventory and binding digests and
  rejects tools outside the snapshot, package policy, eligible runtime, or
  required capability coverage. Missing package permissions project to
  deny-all, MCP wildcards are forbidden, and zero-tools/no-authority execution
  cannot claim tool grants.
- **`redacted=true` is no longer treated as proof.** A deterministic local/Hub
  boundary rejects secrets, local paths, and direct or labelled identifiers in
  the public task brief and role text before candidate retrieval. Shared
  adversarial Python/JavaScript vectors pin runtime digest v4 and capability
  binding v1 across hosts.

## v1.1.43 - 2026-07-16

- **Prepared plans now require a real executable directive.** Core accepts a
  roster row only when `systemPrompt`, `instructions`, or `agentMd` is a
  nonblank top-level string. An unrelated nonblank field can no longer produce
  a schema-invalid "prepared" plan; missing directives reject the row and keep
  the rejected execution roster schema-valid and empty.
- **Prototype-mutation keys are excluded from the shared digest domain.**
  `agentlas.workforce-execution-plan.v4` requires
  `agentlas.workforce-runtime-bundle-digest.v3`, which rejects `__proto__`,
  `prototype`, and `constructor` at every object depth. The authoritative
  Python/JavaScript vectors now exercise those keys explicitly, preventing
  ordinary JavaScript objects from dropping a key that Python would hash.

## v1.1.42 - 2026-07-16

- **Runtime bundle hashes now have a genuinely cross-language canonical
  domain.** `agentlas.workforce-execution-plan.v3` requires
  `agentlas.workforce-runtime-bundle-digest.v2`. Digest values permit only
  strings, booleans, null, arrays, and ASCII-keyed objects; all numbers,
  numeric-first or Unicode keys, lone surrogates, non-JSON containers, and
  excessive depth or size fail closed. Arrays preserve order, object keys sort
  lexicographically, Unicode scalar string values are UTF-8 encoded without
  normalization, and producers represent quantities as decimal strings.
- **Adversarial Python/JavaScript vectors pin the bytes, not just one happy
  hash.** The shared fixture covers Korean, emoji, U+2028/U+2029, NFC versus
  NFD, nested key order, tampering, numeric representations, unsafe integers,
  Unicode keys, and lone surrogates. This retires v1 digest and v2 execution
  plans, whose generic JSON number/key serialization was not interoperable.

## v1.1.41 - 2026-07-16

- **Coverage repair is bounded, semantic, and candidate-blind.** The same host
  LLM may replace the complete WorkOrder at most twice using only aggregate
  slot IDs, counts, and gap codes. A provisional Selection can request one
  content expansion through `requestExpansionForSlots`; candidate identities,
  descriptions, ranks, history, and popularity never leak into refinement.
- **Direct host decisions are exact contracts.** WorkOrder and Selection
  schemas require every adapter-owned array, policy field, runtime identity,
  and edge artifact list instead of silently inserting defaults. Hard skill,
  tool, consume, and produce fields describe candidate package declarations;
  ordinary workflow deliverables remain in slot tasks and handoff edges.
- **Prepared directives are cryptographically bound to the selected post and
  immutable release.** `agentlas.workforce-execution-plan.v2` requires
  `agentlas.workforce-runtime-bundle-digest.v1`; Core ignores any digest carried
  by an input bundle and recomputes canonical SHA-256 over the exact slot,
  definition, release, version, package/content hashes, entity kind, and BYOM
  directive bundle. Hosts must recompute before execution and fail closed on a
  v1 plan, missing marker, or mismatch.

## v1.1.40 - 2026-07-16

- **Cross-platform workforce adapters now have one direct-object contract.**
  The host LLM emits a complete WorkOrder and Selection directly; typed host
  adapters invoke the three fixed workforce tools without asking models for a
  ceremonial tool-call envelope or normalizing, defaulting, or relaxing model
  fields. Bounded ambiguous search replay preserves the exact WorkOrder and
  deterministic selection-session material, while validation and preparation
  remain fail-closed and non-replayed.
- **The difficult workforce benchmark scores declared expertise without hidden
  answer leakage.** Required and optional communities or skills can evidence a
  role family while distinct-slot matching remains mandatory; unrelated
  communities stay hidden negative-recall probes rather than a list the model
  must copy. The ontology menu remains `awo:2026-07-15.2` with unchanged raw
  snapshot SHA-256
  `d6d30d45fe8d35fb785e165d1e80c6471a72436f0160c3933c21d4a31bf2fb32`.
- **Community exclusions are explicit boundaries, not an inverted staffing
  menu.** Hosts must not forbid every unused, broader, adjacent, or legitimately
  co-occurring community because workforce profiles are multi-community. A
  bounded same-host refinement may remove a model-inferred conflicting
  exclusion exposed by coverage-gap codes, but explicit user prohibitions are
  preserved unchanged.

## v1.1.39 - 2026-07-16

- **The Agent Workforce Ontology menu recognizes singular payment and general
  security language without reviving the retired lexical router.** The reviewed
  `payment` and `security` aliases map only to their controlled occupational
  communities; final task-force selection remains owned by the active host LLM.
- **Every runtime can pin the same immutable menu bytes.** Ontology version
  `awo:2026-07-15.2` has raw snapshot SHA-256
  `d6d30d45fe8d35fb785e165d1e80c6471a72436f0160c3933c21d4a31bf2fb32`;
  Core loading and the difficult payment benchmark fail closed on version or
  snapshot drift.

## v1.1.38 - 2026-07-16

- **Agent Workforce Ontology replaces default lexical agent selection.** The
  host LLM creates a redacted occupational work order, receives hard-eligible
  immutable AgentRelease candidates through Hub MCP, and remains the only
  semantic team-selection authority.
- **Selection and execution are independently auditable.** Frozen candidate,
  host-selection, BYOM preparation, planner, child-worker, synthesis, and
  verifier receipts reject history/popularity influence, stale ontology
  versions, silent substitutions, digest drift, planner fallback, and fake
  single-model benchmark passes.
- **Agent and ontology lifecycle is versioned and rebuildable.** Stable
  definitions, immutable releases, append-only lifecycle events, evidence
  levels, community governance proposals, and cross-platform contract schemas
  cover publish, update, withdraw, restore, delete, and ontology evolution.

## v1.1.37 - 2026-07-15

- **Background Stormbreaker execution keeps its bounded replan contract on
  every supported Python and OS matrix.** Child-argument construction now uses
  the parser default when tests or host adapters provide a reduced Namespace,
  removing the Windows/Linux `max_replans` crash without weakening retries.
- **Promoted Hub task-force stages preserve the discovered entity kind.** Team
  stages are invoked as Teams and must return a matching executable graph;
  unproven or mismatched bundles continue to fail closed.

## v1.1.36 - 2026-07-15

- **Exact Cloud/Hub Team references retain their entity boundary.**
  `cloud/team/<slug>` and `hub/team/<slug>` reach the Hub with the requested
  scope and kind, and a mismatched or unproven returned kind fails closed.
- **Executable Team graphs survive the BYOM handoff.** Hephaestus preserves the
  signed manager/worker graph returned by Agentlas Hub instead of shrinking a
  Team to one entry prompt. A Team without that graph returns
  `team_execution_graph_unavailable` and never pretends a single model turn was
  a multi-agent run.
- **Stormbreaker external executors receive the complete local goal and Work
  Brief.** Hub promotion and local pipelines now use the same bounded brief,
  and every packet exposes the non-truncated execution goal only inside the
  local executor contract.

## v1.1.35 - 2026-07-15

- **Hub task forces now reject cross-domain specialist bundles.** High-precision
  domain markers are compared before automatic execution, so an OpenSSL/TLS
  terminal task cannot borrow a civil-litigation package merely because that
  package is callable and shares generic plan/build/verify language.
- **Security routing recognizes concrete certificate work.** OpenSSL, TLS,
  self-signed certificates, fingerprints, cryptography, RSA private keys, and
  cross-site scripting now provide an explicit security-domain signal. Legal
  requests continue to route to legal specialists, while mismatched or absent
  specialists fall back to the Agentlas Core temporary orchestrator.

## v1.1.34 - 2026-07-15

- **Fully specified composite tasks survive a low-confidence Hub search.** If
  every plan/build/verify stage returns `clarify` or no candidates, the router
  preserves those search receipts as discovery evidence and still materializes
  the explicit Agentlas Core temporary orchestrator. It no longer discards the
  stage plan and asks the operator to restate an already complete task.

## v1.1.33 - 2026-07-15

- **Hub task forces no longer dead-end when discovery has no callable,
  intent-fit bundle.** Composite routes preserve the Hub-produced stage plan
  and materialize a local Stormbreaker temporary orchestrator with explicit
  core plan, build, and verify workers. Off-domain callable and install-only
  marketplace hits remain visible as discovery evidence but are never borrowed
  merely to avoid the deterministic core fallback.
- **Core-only orchestration has an honest execution contract.** It exposes no
  fake `hep-call` command or borrowed-agent directive, carries artifacts through
  the same execution fabric, and remains blocked until the final Storm verifier
  passes.

## v1.1.32 - 2026-07-15

- **Hub-only Storm routes now execute instead of stopping at candidate cards.**
  A Hub stagewise task force is promoted into the canonical Stormbreaker
  execution fabric, every selected BYOM bundle carries its complete entry
  instructions into the matching packet, and plan/build/verify artifacts retain
  explicit dependencies and final-gate semantics for local host models.
- **Automatic temporary orchestrators reject callable but off-domain slugs.**
  Stage-role fit is checked independently from Hub availability, install-only
  Cloud or bookmark results no longer block public Hub fallback, callable
  candidates are prioritized without discarding install-only discovery, and a
  missing verifier uses the named Agentlas Core Storm verifier instead of an
  unrelated marketplace team.
- **Router card identifiers are callable across boundaries.** `paid/`, `free/`,
  and other local marketplace tiers are removed before `hep-call` addresses the
  canonical Hub slug. The user-facing `hep-storm` shortcut is Hub-first while
  explicit `--no-hub` and the lower-level Stormbreaker debug command preserve
  local routing behavior.

## v1.1.31 - 2026-07-15

- **Windows checkouts preserve the bundled Model2Vec payload byte-for-byte.**
  Git attributes now force LF for the verified JSON/license files and mark the
  quantized tensor files binary across the canonical, Claude, and Codex asset
  copies. `core.autocrlf` can no longer invalidate strict model checksums.
- **Runtime self-update now installs the same complete local payload as the
  one-touch installer.** Versioned runtimes include `career_graph`, `templates`,
  and the verified `potion-base-8M-int8` asset under
  `models/model2vec/potion-base-8M-int8`. Release-source, staged, and
  post-activation health checks fail closed when the model is missing or
  tampered instead of silently degrading to hash-only recall.
- **Self-update repairs automatic memory hooks for detected hosts.** Claude and
  Codex plugin hooks are refreshed with their plugin bundles; the existing
  merge-safe installer now also runs for detected Antigravity, Grok, and
  OpenCode hosts. It owns only Agentlas keys/files or its managed Markdown
  block, preserves unrelated user configuration, and reports hook repair
  separately from the verified runtime update.

## v1.1.30 - 2026-07-15

- **Agent experience memory now uses one governed local retrieval path.** Each
  normalized Hub slug has a rebuildable
  `hub-agents/<slug>/memory/experience.sqlite` projection. Exact agent, allowed
  privacy scope, active status, expiry, and same-scope structural supersession
  are enforced before scoring. Every eligible row is scored, then rows that
  pass lexical or semantic relevance gates enter lexical/cosine reciprocal-rank
  fusion with a bounded salience prior before adaptive selection: all relevant
  memories when they fit, otherwise budgeted top-k.
  Automatic relation inference is limited to semantic `similar_to`;
  `supersedes` and `contradicts` remain curator-authored edges.
- **The v1.1.30 primary semantic adapter is a bundled, verified Model2Vec
  hybrid.** The offline `potion-base-8M` int8 asset is pinned by model revision
  and content digest. A normalized 256-dimensional Model2Vec vector and
  normalized hash-96 vector form the fixed 352-dimensional local embedding;
  asset drift is rejected. CJK retrieval applies absolute and relative semantic
  gates. Missing or rejected assets enter an explicit `degraded_hash` fallback
  rather than a silent replacement. No server embedding call or per-user
  embedding charge is introduced.
- **Plain supported host sessions can recall local context without invoking an
  agent first.** Claude Code and Codex use `SessionStart` and
  `UserPromptSubmit` additional context; Antigravity uses a `PreInvocation`
  ephemeral message; OpenCode uses an experimental system transform; Grok
  refreshes a workspace cache because its passive hooks cannot inject stdout.
  All adapters fail open, exclude native policy files, and redact and bound the
  evidence capsule before delivery. The one-touch installer also recognizes
  the live `~/.gemini/antigravity-cli` marker without writing workflows into
  that private state directory.
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

- Upload content screening normalizes obfuscated text and checks multiline context for prompt overrides, credential access, and exfiltration patterns across supported languages.

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
- Routing and serving integrate the marketplace index, semantic profiles, host directive handoff, and preserved BYOC/BYOM execution boundary.

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
