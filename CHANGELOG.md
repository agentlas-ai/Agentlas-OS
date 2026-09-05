# Changelog

## Unreleased

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

- **Tool search descends servers before tools, and never ships input schemas.**
  Finding the tool for a concrete action was the plugin search wearing the wrong
  hat: it answered "which plugin covers this topic" when the caller needed
  "which callable does this". `agentlas_tool_search` (MCP, plus
  `agentlas plugins tool-search "<need>"`) ranks servers first and looks only at
  the winners' tools, so catalogue size never changes what the model reads.
  Measured over the 43 shipped routing cards and their 207 capabilities: the
  expected server was in a four-candidate shortlist 5/5 times, four of them at
  rank 1, at ~209 tokens and ~3ms per search — against ~9,982 tokens to hand
  over every tool definition up front. Schemas load for the tool actually
  chosen. `forbid_destructive` keeps deleting tools out of a shortlist for work
  that must not delete.

- **The candidate menu defaults to four per slot, and a role can carry several
  phrasings.** Measured on the 116 routing-eligible profiles with 389 English
  queries: the right agent is inside the top four 97.4% of the time and inside
  the top three 97.2%, so slots five through eight bought 0.2 points for roughly
  2,900 characters a slot. And one request rarely matches a card in only one
  wording — "our webhook double-charges", "duplicate effects under retry" and
  "design an idempotency key" reach different cards while describing one job —
  so a role may now list up to eight `queries`, joined into its task.

- **Plugin discovery stopped scoring function words.** Matching is substring
  containment, so "it" hit "edit" and "the" hit "theme": on the live catalogue,
  "book me a flight and pay with my card" put a positive score on 106 of 113
  plugins and "read the file and send it" on 109, while the same shape of
  request without the glue touched 17. One stopword list now serves this and the
  agent catalogue, so the two cannot drift apart again.

- **The upload seam is closed end to end, and telemetry stops shouting at a
  closed door.** With production's Agent Cloud write mode restored, a
  throwaway package was published, the server was asked to describe that exact
  record back (it returned the same package hash this machine had computed),
  and the record was then removed and confirmed gone. Registration, storage,
  read-back and deletion are one verified round trip, not four separate
  claims. Alongside it, build telemetry now honours a 429 instead of
  discarding it: a rate-limited install goes quiet for a bounded window
  (measured: 0 requests across the next five commands) rather than sending at
  the same rate into the wall that just rejected it, and an ordinary run still
  reports normally.

- **`hep-storm` with no arguments printed a bash internal error.** Under
  `set -u`, expanding an empty array crashed the launcher with
  `storm_args[@]: unbound variable` — the one branch in the file that expanded
  a possibly-empty array without the guard every other branch already used.
  It now answers `query or --decision-file is required` at exit 2, and
  arguments still reach the parser.

- **Audit round 9 — first round graded on "does it work", and most of it
  does.** Seven commands finished their success path with visible evidence: an
  automation described in words got interviewed, saved, listed, shown, run, and
  **wrote a real file**; a signed-out machine went through login to a verified
  token and watched cloud flip from `unauthenticated` to `ok`; the staffing
  chain reached `prepared` with an 18.5KB plan on disk; unrelated queries
  returned genuinely different candidates; five runtimes each lost a command
  file and got it back byte-identical in one update; an orchestration setting
  changed and stuck; the browser took a real snapshot. Four defects that
  round 1-8's refusal-shaped grading could never have surfaced:
  - `contract scaffold` wrote a `canonicalCommand` its own schema rejects for
    any folder name containing an underscore — scaffold emitting a file that
    fails the verify it ships with. `command_slug`, the repair written when 16
    published packages hit this, existed; scaffold was simply never routed
    through it. Both scaffold and the repackage templates now are.
  - `orch worker=<typo>` stored the typo as a pinned model id and exited 0, so
    a mistyped tier became a pin nothing can resolve. A value that is neither
    a tier nor shaped like a model id is now refused with both options named.
  - `hephaestus graph list` fell through to the natural-language router and
    answered with Hub candidates at exit 0 — a marketplace list that reads
    exactly like the saved-automation list the user asked for. Words this
    launcher does not own but the sibling `agentlas` CLI does now name the
    right tool. Real phrases still route.
  - `hep-browser` exited 0 on its research path even when no browser could be
    opened and nothing was produced (honest in the body, success to a script).
    The action and snapshot paths already exited nonzero; this one now does too.

- **A concept whose meaning normalization would delete is refused, instead of
  passing as its bare namespace.** The work-order normalizer refused an id only
  when nothing ASCII survived, so `네트워크 효율` was rejected while
  `role:성능-조사자` was not: it normalized to `role`, and `community:웹-개발` to
  `community`. Both were accepted, pinned as mandatory slot requirements, and
  then matched against nothing — measured, all 8 local candidates returned
  `missing-community:community`, which no required slot can be staffed through.
  The refusal now triggers whenever a non-ASCII letter or digit is present,
  since the ASCII-only substitution can only delete it; this covers Japanese,
  Chinese, Arabic and Hindi identically and leaves authored English phrases
  untouched.

- **The last two refusals without a next move now have one.** Round 8 found
  the neighbours the round-7 repair had not reached: a transient Hub error
  (measured mid-audit as HTTP 502) reported what broke and nothing to do about
  it, and the named server refusals (`agent_not_found`, `no_cloud_package`,
  `owner_only`, `team_execution_graph_unavailable`) stated a fact with no next
  step. The server's own sentence is preserved verbatim — hep-call's contract
  is to relay the exact refusal, never substitute — and the remedy is added
  beside it, which is where that contract and common rule 3 only appeared to
  conflict.

- **The cloud scope's contract sentence is checked by structure, not by
  counting (owner decision).** Round 7 marked "cloud sees everything you own"
  unmeasurable for lack of a reference count. The owner pointed out the real
  shape: cloud and hub are the same routing — one function, one code path,
  differing only in which server tool it calls (network→marketplace,
  cloud→cargo, bookmark→bookmarks). So the check is structural sameness: the
  three scopes share the path, cloud alone attaches the owner-scope arguments,
  and the runtime never re-filters the answer. Measured all three today. This
  also fixes where such a defect belongs: scope is decided server-side, so
  "something I own is missing from search" is a server defect, not this
  command's — exactly what the 284 hidden public listings turned out to be.
  The browser sentence stays as written, by owner decision.

- **Audit round 7 (first graded against the behaviour contract).**
  - Exit codes tell the truth (contract, common rule 6): `search` exits 4 when
    every section failed with zero rows — previously indistinguishable, to a
    script, from "searched fine, nothing matched" — and `call` exits 4 on a
    failed preparation. Partial results stay 0.
  - A `bundle_unavailable` refusal carries its detail and its way out on the
    call surface too, with the same wording every surface uses (common rule 3;
    one live refusal was measured bare).
  - A failed source receipt's way out rides beside the sealed receipt: the
    menu projection decorates failures with per-source hints
    ("sign in with `hephaestus auth login`, then retry") without touching the
    digest-sealed receipt rows.
  - Found while measuring: the sign-in-by-default gate can start a login
    attempt inside a source call, and a network hiccup during that attempt
    (measured: connection reset fetching OAuth metadata) crashed the entire
    federated search with a traceback — RuntimeError lineage, no arm caught
    it. One source's login trouble is now one failed receipt.
  - Live server-side evidence recorded for the web repo: listing
    `brand-introduction` refuses with `object_store_unreadable` ("re-save this
    asset from a trusted machine") — the stored package itself is corrupt, the
    exact artifact-health defect deferred in round 5, now with a named case.

- **Every command now has a natural-language definition of "working", and the
  definition is the audit rubric.** Owner directive: what matters is defining,
  in plain sentences, what each command's normal behaviour is — and whether
  that actually happens. `contracts/COMMAND-NORMAL-BEHAVIOR.md` states, for
  all sixteen commands plus the shared rules, what a user must observe, what
  must never happen, and how to check — each sentence grounded in something
  measured this week. Audit rounds grade these sentences directly; a mismatch
  is fixed in the product or, with owner approval, in the sentence — never
  left silently divergent. A new command is incomplete until its definition
  exists here. The file ships with the runtime.

- **Package schema validation now actually runs on a machine without the
  compiled stack (audit round 5 condition).** The previous entry said F7 was
  closed; the auditor measured that only the receipt half was — package
  contract validation still degraded, because the validator was built through
  the 4.18-era referencing registry, which the vendored 4.17.3 deliberately
  predates. The same local-only schema store now resolves through 4.17's
  RefResolver when the registry path is unavailable. Measured with the
  auditor's own teeth check: an invalid document yields 5 real schema errors
  on stock 3.9 with user-site blocked (previously "schema validation
  unavailable"), and a healthy interpreter still uses the genuine installed
  jsonschema.
- **A tombstoned goal names its way out (audit R5-1).** The implicit goal id
  is a deterministic digest of the WorkOrder, so preparing the same request in
  the same project after its auto goal was completed failed forever with a
  bare `workforce_goal_already_terminal`. The refusal now says to pass a new
  explicit goalId (or reuse an active goal from goal_context), and both MCP
  goal handlers forward remediation sentences beside their codes.

- **A remote prepare refusal names the roster row it refused.** Audit R4-1:
  four consecutive menu candidates failed prepare with a bare
  `release_artifact_unavailable` and the only way to find the culprit was to
  bisect the selection by hand. The refusal now carries which source refused
  which release for which slot, and for the unavailable-artifact case, the
  move ("validate a different candidate for this slot, or retry later").
  Surfacing an unpreparable listing in the menu itself needs server-side data
  and stays on the web-side list.
- **Schema validation works without a compiled dependency (audit F7 closed).**
  `jsonschema` 4.18+ requires `rpds`, a native module — absent on a fresh Mac,
  and measured broken on the dev Mac itself (x86_64 `rpds.so` under an arm64
  interpreter), which left workforce execution-receipt verification entirely
  unavailable. The runtime now vendors pure-Python jsonschema 4.17.3 (+attrs,
  pyrsistent; licenses included, test/benchmark dirs stripped) behind a loader
  that prefers a healthy installed copy and falls back only when the real
  import fails. Measured on stock 3.9 with user-site blocked, and on the
  broken-arch 3.12: both validate; the receipt validator loads.
- Working-tree edits make the router block with `ao_graph_stale` until
  `ao migrate --overwrite` re-materializes — today's recurring "flaky"
  network-pipeline test failures were exactly this, three times. Not a code
  change; recorded so the next person runs the remedy instead of re-diagnosing.

- **Audit round 2 follow-ups.** The re-audit's one condition and both
  non-blocking notes, plus two defects the parity tests caught in the freshly
  restored login command:
  - the `.zcode` dispatcher surface accepts `login|orch|update` (the last of
    ten surfaces; the other nine were fixed in the previous commit);
  - `auth ensure` exits 3 when it ends anything other than authenticated, so
    `auth ensure && <cloud work>` can actually gate (deployed bodies run it
    with `|| true` and are unaffected);
  - the sign-in hint on an unauthenticated search section survives the CLI
    projection instead of being dropped (`error` too);
  - `hep-login`/`agentlas-login` join the updater's command floor — without
    this, a machine that never received them never would, the exact delivery
    defect fixed in v1.2.20;
  - the login body carries the standard update-fallback first line, from the
    canonical body, so every surface renders it identically.

- **The automation kill-switch now kills.** Every hep staffing command runs
  `auth ensure --timeout 180` first, in every runtime, and that path called
  `ensure_access_token` with a hard-coded `interactive=True` — so
  `HEPHAESTUS_AUTO_AUTH=0` had no effect there (independent audit, F1:
  unset/0/1 all burned the full timeout and tried to open a window). A
  signed-out machine's scheduled run would stall three minutes per command and
  pop a browser at night. `auth ensure` now consults the same screen/kill-switch
  gate as the hub client: silent refresh still happens, but with the switch off
  (or no display) it returns `signed_out` immediately with a reason. Measured:
  15s burn → 1s refusal.
- **A signed-out owner-scope search stops answering "there is nothing".** The
  CLI `search` asked cloud/bookmarks anonymously and reported `status: ok` with
  zero rows — "could not ask" dressed as "none exist", while the MCP surface
  answered `failed`/`partial` honestly (audit F2). It now refuses plainly with
  `unauthenticated` and a sign-in hint.
- **Search cache lines carry the account.** The hub-search cache key had no
  identity, so a signed-out session (or the next account) inherited the
  previous account's cloud/bookmark rows for the whole TTL (audit F3,
  reproduced across a logout). Owner-scoped lines are now keyed by an account
  digest, which makes a foreign hit impossible without any cross-module cache
  wipe on logout.
- **`project status` in an unsafe directory names the guard and the way out.**
  The intentional home/system-folder guard was collapsed by a bare exception
  handler into `project_bootstrap_failed` with no cause and no next step
  (audit F4). The refusal now carries the real code (`unsafe_project_root`,
  `project_directory_does_not_exist`, …) and a remedy line.
- **`/agentlas login|orch|update` stop being refused.** The alias files said
  "identical to /hep-login" while the `/agentlas` dispatcher's accept list
  did not contain them, on every runtime (audit F5) — the freshly restored
  login command was unreachable through its most natural spelling. All eight
  dispatcher surfaces now accept the three verbs; resolution reuses the
  existing `hep-<cmd>.md` rule unchanged.
- **`hep-connect` reaches cursor, gemini and opencode.** The renderer
  deliberately leaves a command a host never shipped to a person; the audit
  (F6) confirmed the gap was benign but real. Coverage completed from the
  canonical body; both render gates green.
- Known gap, deferred with reason: package schema validation needs `jsonschema`,
  which the runtime does not bundle (audit F7). The failure is honest — it
  reports "schema validation unavailable" and upload refuses to publish an
  unvalidated package — and bundling a dependency into the release asset is a
  build-pipeline change that should not be rushed into this tag.
- The no-Python-anywhere hint no longer tells a Mac user about Windows.

- **Signing in no longer makes pre-sign-in rosters look deleted.** Goal
  bindings are partitioned by account, so rosters bound while signed out live
  in the shared signed-out drawer and stop appearing after sign-in — nothing is
  deleted, but "I signed in and my team vanished" is indistinguishable from
  data loss (measured: 2 goals / 21 roster rows visible before login,
  `goals: []` after). Merging across partitions is a cross-account write and
  waits for an owner decision; saying the other drawer is non-empty does not.
  `goal_context` now counts active signed-out bindings for the same project and
  reports them as `signedOutGoalsForThisProject` with a plain-language notice.

- **The sign-in URL is printed whether or not the browser "opened".**
  `webbrowser.open` returning True means a handler was invoked, not that the
  person is looking at a sign-in window, and the URL was only printed when it
  returned False. Measured on macOS: the call returned True, a Chrome process
  started, and no browser anywhere held the authorization URL — the flow then
  waited silently on its callback while the user had nowhere to go. Three
  attempts in a row ended that way. The URL is now printed on both paths, with
  wording that says a window should have opened and to use the URL if it did
  not; printing the line costs nothing, and its absence makes signing in
  impossible. This is the third separate break on the path to a login window,
  after the one that never opened it and the missing login command.

- **One oversized source stopped being able to fail every future ingest.**
  `career-graph ingest` refuses a JSON source over the 64 MiB reader cap, and
  refused the whole run with it, so a generated `project-map.json` that reached
  69 MB left `career-graph status` answering `stale` with exit 1 on every run
  afterwards and no command able to clear it. A malformed source still aborts —
  its content cannot be trusted and keeping the previous projection is the
  point, which its test defends — but a source that is merely too large is
  valid content we decline to read, so it is skipped alone and the rest is
  ingested. `status` reports such a file under `skippedSources` with its size,
  the limit and the remedy, instead of counting it as staleness that will never
  clear: a permanent condition dressed as a pending one is how a genuinely
  stale source goes unnoticed. Measured on the stuck project: ingest went from
  `career_ingest_failed` to 27,086 nodes / 27,089 edges, and `status` from
  `stale` exit 1 to `active` exit 0 with one named exclusion.

- **A new Mac could not run six commands at all.** `Path.stat(follow_symlinks=)`
  exists only from Python 3.10, and the system Python a fresh macOS ships is
  3.9, so `project ensure`, `route`, `hep-search`, `hep-call`, `hep-storm` and
  `ao lint` all died with a `TypeError` on any machine without the desktop
  app's bundled interpreter. A development machine never sees it. Found by
  running the commands in an isolated new-machine environment rather than by a
  gate, and fixed at every site. Re-measured on Python 3.9.6 after the fix: all
  175 modules of `agentlas_cloud`, `career_graph` and `ontology` import cleanly,
  and no `Path.stat(follow_symlinks=)` remains — the surviving
  `os.stat(..., follow_symlinks=False)` calls have accepted that keyword since
  3.3.

- **A context error now carries a way out, on every surface.** The CLI kept its
  own hint table covering four codes; the MCP surface — the one the `/hep-*`
  commands go through — ended in a bare `{"error": "<code>"}` with nothing to
  act on. Measured: `context.slice` answered `context_map_integrity_failed`
  with no next step, and the code the documented remedy then produced,
  `context_refresh_incomplete`, was in neither copy — so following the
  instructions led to a second dead end. One table now lives beside the codes
  in `context_map.py` and is read by both surfaces, covering every code a
  caller can reach; the two refresh branches that bypass the error handler
  carry it themselves. The incomplete-refresh remedy names the actual lever:
  read `stats.budgetStop`, then narrow the mapped scope in
  `agentlas-context-map.json`, or use allow_stale meanwhile.

- **A newly shipped command can now reach a machine that already has the
  others.** The adapter sweep overwrote only destination paths that already
  existed, so that a host surface the user never set up is never created. But
  "did the user set this surface up" is a question about the directory, not
  about each file in it: keyed per file the answer was always "no" for a command
  that did not exist yet, and no update could ever add one. Measured on a live
  machine — `hep-orch` and `hep-update` sat in the verified adapter bundle while
  `~/.claude/commands/` held seventeen of their siblings, and two consecutive
  updates reported success without adding them; completing the install floor did
  not help either, because this loop never got as far as consulting it. The
  question is now asked of the directory, by existence rather than contents: an
  empty `~/.codex/prompts` is not evidence that the user declined our commands,
  and a contents-based rule skipped all fourteen for a host the machine plainly
  has. Verified by running it, not by the gate: 29 files added, 0 skipped, 0
  failed, and codex went from 0 commands to 29. New arrivals are reported as
  `added` rather than folded into the refresh count.

- **A revoked sign-in is now noticed instead of replayed forever.** The stored
  token's `expires_at` is the issuer's claim, not proof the server still honours
  it, so a revoked credential kept a future expiry and `auth status` kept
  answering `authenticated` while every owner-scoped call returned 401. The
  retry in `call_hub_tool` asked for a token again and got the same dead one
  back, which made both the refresh branch and the browser-login branch
  unreachable: the "retry" replayed the identical credential. A 401 now
  invalidates the access token (keeping the refresh grant), the retry forces
  past it, and `auth status` reports `refreshable` with `server_rejected_at`
  rather than claiming a live session. Measured: owner Cloud staffing failed
  `source_unauthorized` on every attempt with the local status reading
  "authenticated until 2026-09-13".
- **A compiler fix now reaches releases whose import folder is gone.**
  `register()` recompiles a stored release when the profile predates the current
  compiler, but it is only reached for a package whose original source folder is
  still on disk and still registered. Everything else kept serving whatever the
  old compiler wrote. Measured: 849 of 849 stored profiles were still
  `awo-compiler:1.1.0`, and 154 of them carried the doubled `skill:skill:`
  prefix that makes a skill unmatchable by any requirement lookup — months after
  the doubling itself was fixed. `workforce local-repair` recompiles in place
  from the package the registry already owns, keeping definition, release and
  package identity unchanged; `local-reconcile` now runs it first. Verified on a
  copy of the live registry before applying: 849 repaired, 0 failed, pollution
  154 -> 0, integrity 149/149, and a rerun finds nothing (idempotent).
- **A requirement the ontology cannot enforce no longer brands every
  candidate.** `_hard_eligibility` already demotes such a term so it excludes
  nobody, but the candidate card kept enforcing the same term as a label, so a
  candidate passed the gate and then arrived carrying `gap:required-skill:<term>`
  beside a slot-level `gap:requirement-vocabulary-unsupported:skill` saying that
  term was never applied — two answers to one question, and the louder one was
  wrong. Measured: 16 of 16 candidates in both slots reported "missing" a skill
  none of them could have declared; after the fix, 0 of 8 on the same query,
  with the slot-level demotion still reported. Only the absence claim is
  dropped: a demoted term still earns fit evidence, still feeds the structured
  score, and still carries the minimum evidence-level check.
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
- **Doctor names a host plugin ledger that drifted from its own files.** The
  updater refreshes the plugin payload in place while the host's install ledger
  keeps the number recorded at install time, so the host's update check compares
  against a stale version. Measured: ledger and cache directory both said
  1.2.4 while every file inside, manifest and bundled binary included, was
  1.2.18. Doctor reports the drift and the one command that reconciles it.
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
- **Packaging a minified file no longer looks like a hang.** The filename
  scanner ran a greedy pattern over whole files, which is quadratic on a long
  run of identical characters — one megabyte on a single line (minified JS, a
  base64 data URI, a one-line JSON) spent 483 seconds in it. Tokenizing first
  makes it linear: the same file now packages in 2.0s, with identical extracted
  names across 200 checked files. The content guard also scans a long line in
  overlapping windows instead of whole.
- **Repeated scans of unchanged files are cached.** Packaging reads the tree
  four times, because repair, brief compilation and card generation each rewrite
  files. The content guard is most of packaging time, so three of those passes
  were re-scanning identical bytes: 6 MB authored went 41.3s -> 13.3s. Keyed by
  exact content, so a repaired file is always rescanned.

- **Upload conforms the package instead of shipping a broken one.** The
  importance-ranked trimmer (agent definitions, cards, `skills/`, `knowledge/`
  are never dropped) existed but never ran: collection stopped walking at the
  file that crossed the ceiling, so the trimmer only ever saw a list that
  already fit. Whoever was left out was decided by the filesystem's walk order.
  Measured on a package with a heavy `benchmarks/` folder: 13 benchmark files
  shipped and all 3 `skills/` files were dropped — and it reported `ready`.
  Collection now completes and the ranked trimmer chooses, each drop leaving a
  receipt. Same package: every skill kept, one benchmark dropped.
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

- **Collaboration edges no longer disqualify every candidate.** An edge is a
  declaration of handoff, not a qualification requirement. Compiling edges into
  each slot's consumes/produces made discovery unusable: `artifact:worker-result`
  is the default edge artifact and 0 of 849 local workforce profiles declare it,
  so a measured 16 of 16 candidates in every slot came back with a mandatory
  gap. Requirements are now exactly what the author wrote; the handoff stays in
  `edges`. Same search, same menu: mandatory gaps went 100% -> 0%.
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
- **Continuity stopped growing without bound.** An implicit goal is per project,
  not per WorkOrder: preparation joins the incumbent active auto goal instead of
  opening a new one every task (measured: 3 active goals, 21 roster rows for one
  project). The per-turn read is projected (`goal-context.v2`) and accepts
  `knownRevisions` for a delta: 5,647 -> 3,894 tokens, and 1,161 on later turns.
  Automatic binding also stores the agent's name, so a roster line is readable.
- **Preparation is no longer silently mistaken for delivery.** 19 of 21 bound
  roster rows had never been executed. `goal_context` now reports
  `pendingExecution`, and the session-end checkpoint tells the user in their own
  view — a warning, never a block.
- **Stopwords stopped scoring.** The `fit:text:term` stopword filter moved from
  the MCP projection to the ranking source; half of the lexical fit evidence on
  an accepted receipt was "and"/"the". Requirement gaps also accept a concept
  family match, so a spelling variant is no longer reported as a gap.
- **Refusals stopped re-teaching the catalog.** Selection boundary refusals use
  the same compaction as WorkOrder refusals (81% of a 3.4KB refusal was the
  contract catalog already declared in the tool contract), and the tool surface
  the model actually reads dropped from 9,762 to 8,881 tokens.
- **Preparation stopped shipping a project dump.** `prepare_execution` attached
  the raw Context Map slice because the compaction lived inside the Context tool
  branch and nothing else could reach it. Measured: 44,313 of 57,311 response
  tokens (77%) were that slice, against a 16 KiB budget the Context tools have
  enforced all along, while the agent directives the host actually executes were
  3,010. The compactor is now module-level and both preparation paths use it —
  57,311 -> 13,680 tokens, with every dropped row declared in `omissions`.
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
- **Network no longer drags the project map through every protocol call.**
  WorkOrder preflight, search, selection validation, roster continuity and
  status/auth calls are project-content independent. Removing the accidental
  common bootstrap reduced installed-runtime preflight from 23.5s to 0.78s;
  only explicit Context operations and project-grounded legacy routes inspect
  a working tree.
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

- **A built agent now records the engine it was built with.** None of the seven
  local agent packages on the test machine carried an engine version anywhere,
  and six of them fail today's contract — five missing
  `.agentlas/build-profile.json`, which became required after they were built,
  and one carrying an absolute host path in a generated tool. Not one could say
  it was old, so the person finds out at upload time. `verify` now reports
  `engine_drift` (current / drifted / unstamped / unknown_engine) beside its
  blockers. Unstamped stays distinct from drifted, and an engine we cannot
  identify stamps nothing rather than writing "unknown" and manufacturing a
  false drift later.
- **A package the build gate passes is one the upload gate accepts.** The build
  gate printed `public_marketplace_ready=true` whenever the profile was
  `standard`, reading neither the host-path scan nor the blocker list, while the
  function upload calls refused the same package. It now defers to that function
  instead of keeping a second copy of the rule, and fails when it cannot run it.
- **One sweep over the installed agents.** Opening one package says "this one is
  missing a file"; sweeping all of them says six of seven fail, five missing the
  same file, three carrying a summary copied verbatim from another agent, and
  one declaring three command adapters nobody wrote. The sweep judges and does
  not repair — filling those in would hide the builder defect that produced them.
- **A learning is attributed to the agent that made it, from what the host
  observed.** Routing into a borrowed agent's drawer turned on `agent_slug`
  being present in the model's envelope, and that field does not exist in the
  contract the model reads. One's drawer held 1,278 tickets, 1,273 of them
  stamped as One's own, while seven local agents had zero experience between
  them. The invocation ledger already knows who ran; with exactly one borrowed
  agent and a certain session window, its learnings go to it. Two or more and we
  do not guess. `project` scope deliberately stays in the drawer — it is already
  clustered by project and feeds the project map.


Staffing stopped throwing away the publisher's own words, and the grounding a
worker inherits stopped being the same 64 files for every task.

- **The menu keeps three seats for the publisher's own trigger sentences.**
  A routing card's `trigger_examples` are what the publisher wrote about when
  to call them, and the marketplace path reaches hit@30 100% with them; the
  workforce compiler never copied them into a profile, so staffing discarded
  them. Adding them as a fourth ranking channel makes things worse — hit@1
  73.1% -> 57.0%, and every significance threshold from 0.15 to 0.4 lost
  ground — because weak matches dilute the agreement of the other three.
  Reserving the last three menu seats instead touches no arithmetic and only
  decides who cannot be cut: menu entry 60.1% -> 66.2% with first-place
  accuracy unchanged. Measured over 1,306 publisher-written sentences against
  the 149 locally registered agents.
- **A search can hand back summary cards and be asked for the rest.**
  `shortlist: true` returns ordinal, name, kind, communities, one summary,
  callable and missing requirements — 40,873B to 10,087B for a 20-candidate
  slot, since 68% of a card is the semantic snapshot rather than the
  identifiers. `workforce.expand_candidates` returns the full cards for the
  ordinals worth a closer look, so the decision is still made on full cards.
  End to end with three expansions: 40,873B -> 16,124B.
- **Prepared execution ships each worker's bundle once per digest.** A roster
  with the same agent in two slots repeated its directive bundle and execution
  graph byte for byte. Roster wire weight 95,673B -> 3,640B. Opt in with
  `fullDossier: false`; machine verifiers that recompute a digest over whole
  rows keep the self-contained shape by default.
- **Project grounding answers the task it was given.** Three unrelated
  requests used to receive 64 files of which 63 were identical, led by scratch
  build trees, because the selection was sorted alphabetically before being
  capped — so relevance was discarded at the last step and dot-paths won. The
  three now share 10 of 64, and a task that names a file gets that file first.
- **The verification map stopped repeating itself.** Each traversal round
  re-scanned the graph and re-emitted edges it had already emitted: 256 edges,
  181 distinct. The duplicates also consumed the cap and evicted real edges.
- **A symbol row is a summary, not a listing.** It carried up to 64 referencing
  paths — 4,768B for one symbol — while `files` already holds the paths worth
  reading. Sampled to eight, with the sample size reported. 9,296B -> 1,498B.
- **Skill ids stop doubling their own prefix.** `skill:skill:<slug>` appeared
  in 143 of 149 local agents and in 974 of 2,167 distinct skill ids; the card
  lint has stripped a leading prefix since 2026-08-12 and the compiler never
  did. Fixing the compiler alone would have healed nobody: an unchanged
  package resolves to the same release directory and registration replayed it
  unconditionally. `COMPILER_VERSION` is now the migration trigger, so the
  next reconcile recompiles a release whose stored profile predates the fix.
  Verified on a copy of the live registry: polluted profiles 143 -> 0.
- **Vendored interpreter payloads and scratch build trees are not indexed.**
  A desktop build tree carried a full CPython stdlib, and `.tmp-*` copies are
  byte-for-byte duplicates of real source that led every selection. Indexing a
  live build output also raced with the build that was writing it.

## v1.2.13 - 2026-08-19

The project map stopped being something the product built and started being
something an agent works from.

- **Recall reached the model again.** The freshness check walked the whole
  repository on every prompt and outlived its own hook contract, so the host
  discarded the entire capsule — measured on a 25,453-file project:
  SessionStart 21.1s against 15s, UserPromptSubmit 22.9s against 20s,
  PreToolUse 17.1s against 10s. Freshness now runs under a budget and serves
  the last complete map labelled `unverified_served` when it runs out
  (4.4s / 4.3s / 0.6s after). Desktop's slice went from an outright error to
  1.9s.
- **The capsule spends its budget on where the code is.** Three different
  coding questions used to produce byte-identical slices carrying zero file
  paths, because standing goals consumed the layer budget first. Definitions,
  related files and co-edit history now render before them.
- **The edges the traversal already walked are rendered.** 680,119 declared
  edges reached the model as 0 lines; they now reach it as 8 within the same
  budget.
- **"What breaks if I change this" answers.** Verification traversal discarded
  every name-matched edge, which on a real repository is the majority
  (advisory_by_name 1,497 vs verified_by_import 403), so the answer was always
  an empty list. Advisory targets are reported with their confidence, and the
  PreToolUse warning carries them.
- **The graph opens without words.** Its only two entry points were a path or
  a symbol spelled in the task, so a question that describes rather than names
  fell through to conventional entry points. The contact ledger's edit history
  is now a third entry point, and one dependency hop follows every seeded file.
  A slice also states where things live, directory by directory.
- **First contact seeds the project.** Recall only ever read maps; a user who
  simply talked to their agent in a fresh folder never got one. Seeding is
  detached (0.34s small, 33s large — far past any hook contract), and already
  seeded projects are brought to the current formats through an idempotent
  migration ledger.
- **A subagent starts with the map.** SubagentStart wrote an observation and
  returned nothing, so every spawned explorer began by grepping for what the
  map already knew.
- **The sitemap stopped blocking its own refresh.** Machine-generated edges
  repeated full path strings per row: 223.6MB of a 229MB file, past the read
  bound of the function that maintains it, so the functional projection had
  been frozen since 2026-08-15. Packed into a column store: 219MB -> 11MB,
  declared-graph load 0.8s -> 0.07s.
- **Project learnings fold back in every turn.** Nothing re-derived the
  declared map after bootstrap, while the personal One drawer held 1,199
  tickets of which 917 were already project-scoped. Those cross over (scope and
  workspace must both match; nothing is written back), the derivation now emits
  edges as well as nodes, and it runs per turn. Measured: 111 -> 234 nodes,
  9 -> 65 edges, 0 -> 56 decision-to-code links.
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
- **Context capsules now reach the host AND carry real relations.** The recall
  freshness check runs under a budget (SessionStart 21.1s → 4.2s, PreToolUse
  17.1s → 0.4s), and the slice renders the edges its traversal already walked
  (capsule edge lines 0 → 8, measured) with the relation arrow kept legible.
- **Five shipped contracts tell the truth again**: the package-contract schema
  accepts its own `text` kind, scaffolded packages can read all of their own
  required artifacts, generated-package verification honors minimal-private,
  the workforce-skills-root gate exists, and the source-bundle public schema
  accepts the runtime's idempotency fields.

## v1.2.7 - 2026-08-16

- **Ordinary Korean writing is no longer thrown away as prompt injection.** The
  curator decided injection from a list of seven Korean sentence endings, so
  guidance written the way guidance is written got rejected: dosage instructions
  ("이 약은 하루 3회 식후에 복용하세요"), care steps ("증상이 지속되면 의사와
  상담하세요", "개봉 후에는 냉장 보관하세요") and app steps ("설치 후 앱을 다시
  시작해줘"). Meanwhile "볶아주세요" and "복용하지 마십시오" passed — the split was
  which ending happened to be on the list, not what the sentence meant. This is the
  same failure the capability-widening screen was retired for in 1.2.3, and its
  explanation sat directly below the line being changed. What remains is the
  explicit English override phrasing ("ignore previous instructions", "disregard
  the above", "forget everything"), which has no collision with ordinary writing.
  Real defence stays at the PreToolUse broker; a stored string cannot widen a tool
  permission by itself. Eleven cases measured: zero ordinary sentences blocked,
  zero injections missed. The fixture that pinned the old behaviour now asserts the
  new contract with two different endings, so the two cannot diverge again.
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
  a consent prompt (owner decision 2026-08-15; opt out with
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
    level L0–L3, access path, ACP command), measured on this machine.
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

- **One's memory now searches by meaning, like every other layer.** The project,
  borrowed-agent and Desktop memories were already served by the local ontology
  runtime — the engine behind the published LoCoMo and LongMemEval numbers — but
  the One drawer had been built later on its own store and searched by word
  overlap. Durable soul blocks are now projected into that engine as a
  rebuildable, incremental index; the soul file stays authoritative, and a host
  without the engine recalls exactly as before. Measured on LongMemEval with
  gold evidence labels and no reader model: 93.5% to 96.0% recall@10 over 200
  questions.
- **Recall got roughly 20x faster.** 490ms to 21ms, by reusing the runtime
  instance instead of reconstructing it on every call.

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

- **A tool description stops paying for a value the host cannot author.** The
  local stdio surface advertised 91,897 bytes of tools/list for 22 tools, while
  the same-named remote surface spent 28,488 for 11 — three times heavier with
  half the tools, on a payload that rides every request. Two causes, both
  measured. `workOrder` and the accepted `selection` are echoed back
  unchanged from an earlier call, so a host cannot invent them and re-publishing
  their 8,144-byte contract schema a second and third time only spends context;
  those arguments now carry a description and nothing else, and the handler
  still revalidates them against the canonical contract. Separately,
  `x-agentlas-contracts` shipped 20,292 bytes that no code anywhere reads —
  a repository-wide sweep found all six occurrences were producers. The values a
  host actually writes keep their full schema, `_meta` stays because Desktop
  reads it, and the surface is 49,125 bytes with the same 22 tools and identical
  argument lists. Schema duplication fell from 51,831 to 3,280 bytes, so no
  `$ref` rewrite was needed.
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

- **Authority requirements demote instead of exclude.** The last dimension
  exempt from the rank-and-report demotion ("authority is a security
  contract") was measured inverted on the live network: capability attaches
  to the executing runtime, not the BYOM bundle, so almost no card declares
  authorities — a slot requiring `authority:file-read` staffed four
  engineering slots with the same two domain-irrelevant auditors and
  excluded every relevant engineer (2 → 6 candidates the moment the gate
  lifted, all other hard fields bisected innocent). Real authority
  enforcement lives in the prepare-time permission policy pins. Local
  demotes by the same population rule as every other dimension; the Hub
  relaxes only for callers that declare
  `gap:requirement-vocabulary-unsupported:authority` (35th code), so
  non-declaring runtimes keep their exact old behavior.
- **An absent list-valued slot field IS the empty constraint.** Authoring a
  slot no longer requires spelling out fifteen empty arrays: only slotId,
  title, task, cardinality, criticality, and allowedEntityKinds stay
  required, and every ingestion point normalizes absent → [] BEFORE
  validation and BEFORE any canonical digest — so a lean-form author and a
  full-form author produce byte-identical orders and the fail-closed digest
  chain cannot fork. Full forms pass through by identity (live A/B across
  fixed queries: zero change). Proven live end to end: a 775-byte lean order
  ran search → ordinal validate accepted → prepare prepared with the digest
  chain intact.
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

- **The recall capsule carries a standing emission contract.** Evidence first
  (central DB + Desktop logs, 2026-07-29): the curation pipeline was alive
  (468 episodes) but admission starved — most discards were CORRECT (episodes
  were QA noise), and valid candidates were admitted by policy fallback even
  with the semantic judge blocked by Codex CLI isolation limits. The real
  defect was supply: the work worth remembering happens in Claude Code /
  Codex / Cursor / Antigravity sessions, which had no path into the loop.
  Judgment stays with the session LLM; delivery is now the system's job:
  every capsule tells sessions that durable project learnings
  (fact/decision/procedure with evidence; never secrets or transcripts)
  belong in `.agentlas/pm/learnings/`.
- **A learning written today is recallable at the next session start.** The
  index backstop also regenerates when any pm document is newer than the
  index (not only after the 7-day TTL), embeds pm documents learnings-first
  and newest-first (measured live: name-ordered traversal let mid-July
  handoff notes exhaust the 48K budget and a fresh learning never made it
  in), and stamps every embedded document heading with its own last-written
  date so a freshly regenerated index cannot launder an old note as current.
  Verified end to end: one recorded learning → SessionStart → regenerated
  index → ingest → rank-2 recall for a targeted query.

## v1.1.80 - 2026-07-29

The recall corpus regenerates from any surface — Desktop is no longer its
single point of failure.

- **A stale project index is regenerated wherever the runtime runs.** The
  index (`.agentlas/ontology-inbox/agentlas-project-index.md`) had a single
  producer: Desktop's working-folder materializer. A machine driven only
  through terminal or plugin sessions froze at its last Desktop visit —
  measured 2026-07-29: 12 days — while every session's recall kept citing the
  snapshot. v1.1.79 made that staleness visible; this release removes it. A
  host-independent backstop rebuilds a bounded, secret-filtered index (sitemap
  file map, fixed root documents, bounded `.agentlas/pm` documents — bounds
  mirror Desktop's) whenever the index is missing or older than 7 days, then
  starts a detached ontology ingest. It fires from both universal surfaces —
  the memory hook on SessionStart and the CLI on every command — so any
  project with `.agentlas` converges no matter which product the machine uses,
  and the project workspace location keeps it working inside host sandboxes.
  Desktop's richer materializer stays authoritative: its next visit overwrites
  the file, and any fresh file disables the backstop for the TTL window.
  Verified live on the real frozen corpus: one SessionStart regenerated the
  Jul 17 index and the next capsule cited it with no staleness labels.
- **MCP workforce staffing goes reference-first and menu-light.** Measured on
  the live MCP host path (1 slot × 10 candidates), the search → validate →
  prepare round trip cost ~360KB of host context, and reference-style prepare
  could not finish because it still demanded full-echo attachments plus a hash
  no LLM can compute. The search menu now also folds
  `semanticSnapshot.produces/consumes` (unique-per-candidate slugs with zero
  cross-candidate overlap, so they never supported comparison), attachments
  are optional in reference mode, prepare accepts menu ordinals, and
  `prepareAttempt` is server-derived.

## v1.1.79 - 2026-07-29

A recalled memory now confesses its age instead of impersonating the present.

- **Stale recall sources are labeled, and deleted ones are named.** Measured
  2026-07-29: a recall capsule served 12-day-old project facts (a project
  index frozen since Jul 17 — its only producer is Desktop's working-folder
  ontology materialization) with no freshness signal, and a session asserted
  them as current state. The consumer cannot infer a source's age, so the
  producer must label it: each cited project chunk now resolves its source
  document's mtime; sources older than 7 days carry an inline age tag
  (`| stale 2026-07-17, 12d old`) and inject a staleness directive —
  "historical snapshot, not current state; verify versions, statuses, and
  paths against the live system before asserting". A deleted source is named
  as missing outright. Fail-open: an unresolvable source stays unannotated
  rather than risking a false warning. This guards every stalled-producer
  case (frozen index, frozen PM documents, dead emission loops) at the one
  place all of them converge: the capsule consumers actually read.

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

- **Credential detection matches a path SEGMENT, never a filename substring.**
  `**/*token*` and `**/*secret*` matched ordinary vocabulary: measured on the
  live `web-master` bundle, they gave a flagship paid package
  `securityVerdict: BLOCK` for shipping its own `token-architecture.md` and
  `reference-token-db.json`, and the matching `denyRead` entry then hid those
  files from the runtime, so a worker card could name them as Required Context
  and never receive them. Dropping the substring rule costs no coverage —
  `collect_package_files` skips every non-text suffix and every file that fails
  to decode, so anything reaching the scan is text whose content is matched
  against SECRET_PATTERNS, the check that actually looks at values. Matching by
  segment also closes a hole the globs had: `matches` is fnmatch, so
  `**/secrets/**` required a parent directory and a store at the package ROOT
  matched nothing at all. Both the publish scan and the runtime read policy now
  cover rooted and nested stores.
- **Upload widens `allowRead` to the context its own agent cards demand.** A
  worker card naming `webmaster_frontend/knowledge/stack-and-standards.md` as
  Required Context is a promise the runtime has to keep. Measured across 143 live
  packages, `allowRead` came in 15 different shapes, 128 of them a 5-entry list
  written before `agents/**`, `docs/**` and `contracts/**` joined the default,
  and 82 card-declared files were unreachable. Re-uploading now unions the
  current default with every path the cards actually reference, minus credential
  stores.

## v1.1.75 - 2026-07-29

A package is priced and staffed as what it actually ships, and Codex can publish
again.

- **A contradicted entity type is corrected, not trusted.** Upload only derived
  `agent` vs `team` when the routing card was silent, so an older package that
  hardcoded `type: "agent"` stayed one no matter what it shipped — measured on
  the live `analyst-team`, an HQ-routed roster listed as `entityKind: agent`
  with `agentCount: 1` and billed 3 credits instead of the team's 10. Structure
  is now the authority: a declaration the package's own files contradict is
  overwritten and the correction is recorded, while a package whose structure is
  silent keeps the author's declaration. `topology` is read in every shape the
  live corpus actually uses — a bare string, a whole `{nodes, edges}` graph, or
  absent — and a roster of `agents/*/agent.md` counts as the same evidence.
  Plugins are never retyped.
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

- **Network routing normalises the query to English.** `/hep-network` step 1
  now has the host LLM author the work order's discovery-facing fields in
  English, faithfully translating a non-English request rather than passing its
  wording through: the candidate corpus is English and cross-lingual matching
  silently buried the correct agent (measured: an identical query ranked its
  target 1st in English and 144th in Korean). The `languages` slot stays the
  required delivery language, and marketplace search stays multilingual — only
  network routing normalises, because it is the LLM that authors the query.
- **The résumé is compiled and stored on upload.** The offer brief is generated
  from package files at publish time — it had been dead code with zero callers —
  the candidate menu is widened, and boundary failures are no longer misnamed.
- **Uploads repair instead of refusing.** A package shipping fewer than ten
  benchmark cases has one synthesised from its trigger examples, and the card
  lint counts inline cases it can see.
- **Search returns a decision menu, not a dossier.** Audit-weight fields
  (`qualificationEvidence`, `packageHash`, `contentDigest`,
  `candidateProvenance`) stay in Core's session store instead of crossing the
  wire; each candidate carries a `candidateOrdinal`, and evidence is summarised
  as `qualificationEvidenceCount`. Measured 2026-07-28 on a live 10-candidate
  slot: 41,216 → 22,512 bytes with the candidate-set digest unchanged, because
  the digest is computed over the stored original. Only the fields named above
  are removed, so a résumé schema that gains or renames a field passes through
  untouched. `fullDossier: true` returns the original shape for a caller that
  still wants it.
- **A selection may name its candidate by ordinal.** Copying a 48-hex
  `agentReleaseId` by hand is a transcription surface, not a contract: measured
  2026-07-28, a local 30B model truncated one to 34 characters in 1 of 12
  attempts, while ordinals were never malformed across 19 answers from two
  models. `assignments[].candidateOrdinal` is resolved against the pinned menu
  before validation; an out-of-range ordinal, or an ordinal that disagrees with
  an `agentReleaseId` sent alongside it, is refused rather than silently
  resolved. The canonical selection schema is unchanged — only the MCP tool
  input relaxes — so Hub and Terminal contracts are untouched.
- **The resolve-by-session branch had never once run.** `_call_tool` binds
  `store` twice, making it a function-local that was unbound on that path, so
  every attempt raised `UnboundLocalError` — not a `FederationSessionError`, so
  the handler's own except never caught it and the call died. The escape from
  echoing a ~461KB candidate set therefore stayed theoretical from the day it
  was written. First live proof it works: validation accepted in 0.03s from a
  3.6KB request.
- **Selection validates by session id.** `candidateSet` and `federationResult`
  are optional; omitting them resolves the pinned session, whose digest,
  expiry, and lineage are re-verified exactly as before. A menu wide enough to
  contain the right agent does not fit in one tool call, and the digest covers
  the exact bytes so it cannot be trimmed — in the measured run the intended
  pick ranked 4th, so a 3-candidate menu would have cut the answer out.
- **Eligibility stops deciding by string equality over words.** Both sides of a
  match are model-written prose, yet exact equality ran against a 23-word skill
  list and an 11-word tool list. Measured 2026-07-28: `"api design"` matched but
  `"designing REST APIs"` did not, Korean input could never match, and stating
  any single requirement took a 3-candidate inventory to 0 across all eight
  probes. Eligibility now decides only on facts this system owns.
- **A schema bound violation now reports the bound.** `schema_max_length` and
  `schema_min_length` issues carried only a path, so a caller told its field
  was too long knew neither the ceiling nor by how much it had overshot — its
  one repair attempt then wrote something too long again. Both issues now
  carry `limit` and `actual`. Measured 2026-07-27: a completed 20-agent run
  was discarded whole by exactly this loop.

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

- **Built packages must ship the workforce résumé block.** `card lint` now
  requires `workforce: {roles, communities, modalities, languages}` on the
  routing card, validated against the pinned Agent Workforce Ontology
  (awo:2026-07-15.2); ids outside the pinned vocabulary are errors, a missing
  block is a `routing_ready` blocker, and `roles: []` stays honest when no
  canonical role fits. The packaging skill authors the block at build time.
  Measured over the live catalog, sellers declared roles/modalities on 0 of
  250 cards, which silently excluded the whole catalog from every WorkOrder
  that used those fields.

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

- **The router's semantic signal is actually semantic.** Card routing used a
  token hashing adapter, which scored equivalent Korean and English requests
  ("사업계획서 만들어줘" vs "business plan writer") at 0.0 — every value the code
  called a semantic score was really lexical. It now uses the verified local
  sentence model that the ontology and Hub rerank paths already use, with
  hashing kept only as an explicitly degraded fallback. That pair now scores
  0.383. Card vectors additionally embed trigger phrasing as meaning material
  (anti-triggers stay out: they name work the card must refuse), and the
  caller's sentence reaches the Hub rerank path so semantics can order
  lexically tied candidates.
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
