# Agentlas Research Engine

Status: phase-0 core.

Agentlas Research Engine is the lightweight web research core for Hephaestus.
It is designed to keep search, reading, browser control, platform APIs, and
credentialed access as detachable modules instead of mandatory runtime weight.

## Contract

The core owns:

- `ResearchRequest`, `ResearchResult`, and `ResearchReceipt`;
- module selection and allowed/forbidden module policy;
- SSRF-safe URL classification for built-in readers;
- receipt writing under the Agentlas networking ledger;
- browser-free static and adaptive reader adapters.

The core does not import Playwright, browser-use, Stagehand, HyperAgent,
BrowserOS, Crawl4AI, cloud browser SDKs, or stealth/browser-provider libraries.
Built-in cartridges stay dependency-free and policy-selected; heavier tools
must register as optional modules.

## Loadout Model

Modules are treated like detachable hardpoints. The registry can describe every
cartridge, but a request only mounts a named loadout or explicitly allowed
module IDs.

| Loadout | Use | Mounted modules |
| --- | --- | --- |
| `auto` | Source-aware safe default; explicit social/GitHub hints mount public fallbacks, but browser modules and social APIs are never mounted by default. | light public modules; public Reddit/Threads fallbacks for explicit hints; GitHub search only for GitHub hints |
| `safe` | Fast public evidence and static reads. | `search.ddg_html`, `search.news_rss`, `read.http`, `platform.reddit` |
| `public-web` | Blocked public pages, metadata, feeds, GitHub repo discovery, RSS fallback. | `safe` + `search.github_repos` + `platform.threads.public` + `read.insane_fetch` |
| `social` | Operator-approved Threads/Reddit research with official platform API cartridges. | `search.ddg_html`, `search.news_rss`, `search.github_repos`, `platform.reddit.oauth`, `platform.reddit`, `platform.threads`, `platform.threads.public`, `read.insane_fetch` |
| `browser` | JS-heavy pages and real browser snapshots. | public readers + `read.jina`, `browser.playwright_mcp`, `browser.browser_use`, `browser.stagehand`, `browser.steel`, `browser.hyperagent`, `browser.agent_cli` |
| `full` | Operator-approved deep research. | all built-in cartridges |

```bash
bin/hephaestus research loadouts
bin/hephaestus research doctor
bin/hephaestus research status
bin/hephaestus research credentials
bin/hephaestus research social-fallbacks
bin/hephaestus research proofs
bin/hephaestus research verify
bin/hephaestus research hardpoints
bin/hephaestus research armory --loadout browser
bin/hephaestus research profile
bin/hephaestus research profile --loadout browser
bin/hephaestus research recommend "Threads와 Reddit 반응까지 조사"
bin/hephaestus research browser-candidates
bin/hephaestus research bridge-contract --module browser.stagehand
bin/hephaestus research bridge-check --module browser.stagehand --url https://example.com
bin/hephaestus research platform-contract --module platform.threads
bin/hephaestus research platform-check --module platform.reddit --source "reddit:search:agent browser"
bin/hephaestus research plan https://example.com --loadout browser --depth deep
bin/hephaestus research gather "agent browser modules"
bin/hephaestus research read https://example.com --loadout browser
bin/hephaestus research search "agent browser modules" --loadout safe
bin/hephaestus research search "agent browser modules" --loadout public-web --follow-results 3
```

This is the weight boundary: the engine always knows what browser and adaptive
reader modules exist, but the adaptive public-route fetch chain only starts at
`public-web` and browser work only starts at `browser`, `full`, or an explicit
`--allow-module browser.*` policy.

The `auto` loadout is intentionally conservative. When the caller has not set
`allowed_modules`, it mounts safe public search/static read modules. Explicit
Reddit or Threads source hints mount only no-token public fallback cartridges,
not Reddit OAuth or Threads Graph API. It does not mount `read.insane_fetch`,
Jina, official social APIs, or browser modules unless the caller selects a
heavier loadout or explicitly allows that module.

The upstream design this cartridge was inspired by is best treated as a
reference for a detachable public-page reader, not as the whole Agentlas
research brain. Agentlas keeps the planner,
module policy, ranking, receipts, preflight, and Stormbreaker packet contract
inside the Research Engine, then mounts `read.insane_fetch` only when
`public-web`, `social`, `browser`, `full`, or an explicit allow-list asks for
that heavier public-route chain.

When `read.insane_fetch` runs, result limits and receipt attempts include
bounded route evidence such as `trace:*`, `stop_reason:*`, and
`untried_routes:*`. That lets Stormbreaker or a build agent explain whether it
used Reddit RSS, direct HTML, or Jina Reader, and which remaining public routes
were still available, without logging secrets or private local paths.

Threads has two separate cartridges. `platform.threads` is the official Graph
API path for keyword/tag search, profile reads, posts, and replies; it requires
a configured access token. `platform.threads.public` is a no-token public HTML
fallback for explicit Threads URLs and username/profile hints only. It does not
run hidden keyword scraping and labels output as `public_html_fallback` with
`official_api_preferred`.

Use `research plan` as the dry-run surface before launching heavier modules. It
applies the same loadout, allow/forbid, depth, max-weight, and request-budget
policy, then returns the candidate modules that would mount or be blocked. It
does not fetch URLs, start browsers, call external readers, or write research
receipts. The payload shows `source_hints_before_budget`,
`source_hints_used`, and `source_hints_dropped_by_budget` so operators can see
whether query variants or follow-up fanout would be trimmed before anything
runs.

```bash
bin/hephaestus research plan https://example.com \
  --loadout safe \
  --allow-module browser.stagehand \
  --depth deep

bin/hephaestus research plan --search --query "agent browser modules" \
  --loadout public-web \
  --variant reddit \
  --max-requests 2
```

Use `research doctor` as the non-executing readiness audit. It checks that the
core registry has search/reader/platform/browser slots, that `auto` keeps heavy
browser modules detached, that search variants and evidence-quality receipts are
available, and that Reddit/Threads/browser live proof is still missing when
credentials or hardpoints are not configured.

```bash
bin/hephaestus research doctor
bin/hephaestus research doctor --home /tmp/agentlas-networking-check
```

Doctor does not run network calls, browser commands, or credentialed APIs. Its
`completion.missing_proofs`, `completion.missing_or_unready_proofs`, and
`next_commands` fields tell the operator which live checks still need to be run
or reconfigured before the full research-engine goal can be called complete. It
also exposes a `coverage` summary that separates public social fallbacks,
credentialed social proof, and browser hardpoint proof at a glance. It scans the
selected networking home's
`ledgers/research-receipts.jsonl`; if a live platform or browser check has
already produced a fresh `ok` receipt and the module is still locally ready,
doctor marks that proof as satisfied. Live proof receipts expire after 24 hours
by default; stale or timestamp-less receipts remain visible but are reported as
`stale_live_proof` or `unknown_live_proof`, so they cannot accidentally satisfy
the completion gate.

Use `research status` when you want the short completion view instead of the
full doctor/proofs payload:

```bash
bin/hephaestus research status
bin/hephaestus research status --home /tmp/agentlas-networking-check
```

It does not run network calls or browser commands. It reuses doctor/proofs
evidence and returns requirement rows for core registry, light default loadout,
browser modularity, search recall, evidence quality, public social fallbacks,
browser hardpoint proof, official Reddit OAuth proof, official Threads Graph
proof, and credential-output safety. This is the operator-facing answer to
"is the original research engine ready yet?"
For requirements that are not ready, `status` includes a safe `setup` block with
environment variable names, requirement names, the next check command, and
`secret_values_exposed: false`. It never prints configured secret values.

Use `research credentials` when `status` says official Reddit or Threads proof
is missing:

```bash
bin/hephaestus research credentials
bin/hephaestus research credentials --home /tmp/agentlas-networking-check
```

This command does not run network calls or token checks. It reports only env
names, minimum permissions, documentation links, and the next live-check
commands. It never prints token values. The official Reddit cartridge accepts
either a pre-issued OAuth2 bearer token in `AGENTLAS_REDDIT_BEARER_TOKEN` or
`REDDIT_BEARER_TOKEN`, or a Reddit app-only OAuth pair in
`AGENTLAS_REDDIT_CLIENT_ID` plus `AGENTLAS_REDDIT_CLIENT_SECRET`. The official
Threads cartridge expects a Meta Threads access token with `threads_basic` and
`threads_keyword_search` in `AGENTLAS_THREADS_ACCESS_TOKEN` or
`THREADS_ACCESS_TOKEN`. Public fallback modules remain available while those
official tokens are missing, but the full completion gate stays partial until
fresh live proof receipts exist.

Use `research proofs` when you want the receipt-ledger view behind that doctor
verdict:

```bash
bin/hephaestus research proofs
bin/hephaestus research proofs --home /tmp/agentlas-networking-check --limit 20
```

It reports the required live proof gates (`reddit_oauth_live_check`,
`threads_live_graph_check`, and `browser_hardpoint_live_check`), each gate's
current local readiness, the latest matching receipt if one exists, receipt
freshness, and the next check command for anything still missing or stale. It
never reruns modules, starts browsers, opens networks, or prints credential
values.
The payload also includes `public_fallback_proofs` for lower-confidence but
useful no-token social coverage: `reddit_public_live_check` and
`threads_public_live_check`. Its `coverage` field lists which required proofs
and public fallback proofs are already satisfied, plus any stale or unknown
proofs that should be refreshed.

Use `research verify` when you want to refresh live proof receipts in one pass:

```bash
bin/hephaestus research verify
bin/hephaestus research verify --skip-browser
bin/hephaestus research verify --skip-public --skip-browser
```

By default it runs public Reddit fallback, public Threads fallback, the configured
browser hardpoint, and any credentialed Reddit/Threads modules that are already
locally ready. The browser proof is module-agnostic: `verify` selects the first
ready browser hardpoint, such as Playwright MCP, Browser Use, Stagehand, Steel,
HyperAgent, BrowserOS, or `agent-browser`, and writes a normal browser proof
receipt for that selected module. Credentialed modules with missing env tokens are not
called; they are reported as `skipped_not_ready`. The command writes ordinary
research receipts, does not print secret values, and returns the updated
`proofs` summary.

Use `research hardpoints` to make an approved heavy browser bridge durable
without turning it into a default dependency:

```bash
bin/hephaestus research hardpoints
bin/hephaestus research hardpoints --arm browser.agent_cli --recipe npx-agent-browser
bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com
bin/hephaestus research hardpoints --disarm browser.agent_cli
```

The config lives at `policies/research-hardpoints.json` inside the selected
networking home. It stores recipe names only; the engine ignores arbitrary argv
values in that file and expands recipes from its own allowlist.

Use `research armory` when you want the spaceship-weapons view: every module is
listed with its slot, loadout membership, weight gate, and local readiness.
Armory checks only local environment variables, approved hardpoint recipes, and
binary presence; it does not run commands, open browsers, call networks, or
print secret values. The payload also reports `slot_counts` and
`mounted_slot_counts`, so operators can see the currently mounted search,
reader, platform, and browser hardpoints at a glance.

```bash
bin/hephaestus research armory --loadout browser
bin/hephaestus research armory --loadout social --slot platform
```

Use `research profile` when you want the lighter dashboard view across
loadouts. It compares mounted module count, detached module count, slot counts,
weight counts, readiness counts, heaviest mounted weight, and browser hardpoint
count without executing any module. Each profile also includes an
`operator_summary` with the posture (`light`, `adaptive_public`,
`credentialed_social`, or `browser_heavy`), whether heavy browser modules stay
detached, ready browser hardpoints, missing credential modules, and safe next
actions such as credential or browser-hardpoint setup commands. This is the
quick answer to "is this loadout still light, or did it mount a heavier
weapon?"

```bash
bin/hephaestus research profile
bin/hephaestus research profile --loadout browser
bin/hephaestus research profile --loadout auto --source "threads:keyword:agent browser"
```

Use `research recommend` when you have a natural-language research request and
want the engine to pick a detachable loadout before running anything. It does
not call networks, start browsers, write receipts, or print credentials. It
returns the recommended loadout/depth/follow count/query variants, the dry-run
plan preview, and the footprint so reviewers can see exactly what would be
mounted. The recommendation also includes `mount_decision`, a compact
mounted/detached summary for browser hardpoints, credentialed social modules,
public social fallbacks, and the adaptive public reader.

```bash
bin/hephaestus research recommend "agent browser modules 찾아봐"
bin/hephaestus research recommend "Threads와 Reddit 반응까지 조사"
bin/hephaestus research recommend "403 blocked dynamic browser page"
```

The recommender keeps browser candidates detached for ordinary "agent browser"
research. It recommends `browser` only when the request signals a blocked,
dynamic, or interactive page. Reddit/Threads requests choose `public-web` by
default: the engine broadens public web search with Reddit/Threads variants and
keeps official social API cartridges detached unless the operator explicitly
chooses `social`, `full`, or an allow-list for those modules.

The same recommendation policy can be used directly on execution and preview
commands by choosing `--loadout recommended`. The CLI resolves it to a concrete
loadout before calling the engine:

```bash
bin/hephaestus research plan --search --query "Threads와 Reddit 반응까지 조사" \
  --loadout recommended

bin/hephaestus research gather "agent browser modules 찾아봐" \
  --loadout recommended
```

In other words:

- `research modules` shows the static detachable module catalog.
- `research doctor` shows the non-executing readiness audit and missing live
  proofs.
- `research status` shows the concise goal-readiness summary and next commands.
- `research hardpoints` arms or disarms approved local browser recipes.
- `research armory` shows whether those hardpoints are ready on this machine.
- `research profile` compares loadout footprints so operators can see what is
  mounted versus detached before any fetch happens.
- `research recommend` turns a plain request into a non-executing loadout and
  module recommendation.
- `research browser-candidates` shows source-backed browser candidates and why
  each one stays detachable.
- `research bridge-contract` shows how a browser hardpoint should be wired.
- `research bridge-check` runs one configured browser hardpoint against one URL
  and returns a compact proof summary plus the research receipt id.
- `research platform-contract` shows how Reddit/Threads cartridges should be
  configured and which source hints they accept.
- `research platform-check` runs one selected Reddit/Threads cartridge against
  one source hint and returns a compact proof summary plus the research receipt
  id.
- `research plan` shows which ready or unready modules a specific request would
  mount before any fetch happens.

Depth is a second boundary. `quick` stops at the first usable reader. `deep`
still does nothing extra unless a browser module is mounted; when browser
modules are mounted through `--loadout browser`, `--loadout full`, or
`--allow-module browser.*`, the engine keeps the static read and adds one
browser snapshot as separate evidence. Receipts separate the policy request from
the actual result through `browser_execution`: `status=used` means a browser
hardpoint returned evidence, `unavailable` means the requested command or
provider was not configured, `blocked_by_policy` means the loadout/weight/URL
guard stopped it, and `not_requested` means no browser module was mounted.
Browser modules that are only present in the registry but not mounted by the
loadout are not counted as attempts; auth walls may still produce an advisory
suggestion to choose a browser loadout.
`read_strategy` is only `deep_static_plus_browser` when browser evidence really
landed; otherwise it remains `first_success`.

Weight is the third boundary. Each loadout carries a `max_weight`; modules whose
manifest weight exceeds that ceiling are recorded as `module_unavailable`
instead of running. This means `safe` remains safe even if a caller tries to add
`--allow-module browser.stagehand`. Operators can raise the ceiling explicitly
with `--max-weight browser_heavy`, or choose `--loadout browser` / `full`.

`--follow-results` turns search into bounded evidence collection: the search
cartridge returns result URLs, then the engine ranks candidate URLs and reads
the top N with the same loadout policy. The receipt records both the search
cartridge and the follow-up reader attempts, so Stormbreaker can tell whether
it saw snippets only or actually read the cited pages.

`--variant` broadens recall without mounting new modules. Search and gather
always include the base query, then add bounded variants such as `official`,
`docs`, `github`, `reddit`, `threads`, or `news` to the same selected search
hardpoints.
This is useful when one exact query misses source material, while still keeping
the loadout weight and provider boundary unchanged.

```bash
bin/hephaestus research gather "agent browser modular research" \
  --variant docs \
  --variant reddit \
  --variant threads
```

Receipts also include `escalation_advice`. This is deliberately advisory: the
engine never auto-escalates from safe readers into adaptive, credentialed, or
browser modules. When a static read is blocked, advice may suggest
`loadout=public-web` and `read.insane_fetch`. When a requested browser hardpoint
is missing, advice points at the module that needs configuration. When Reddit,
Threads, or Jina credentials are missing, advice names the module and credential
class without printing secret values. Each suggestion includes a bounded
`request_patch` with only loadout/module/weight/depth fields, plus
`approval_required`, `run_after_config`, `auto_apply=false`, and
`safety_boundary=advisory_only`. The `auto_escalated` flag stays `false`.

Receipts stay lightweight by design. They include `registered_module_count`,
`mounted_module_ids`, `mounted_module_slots`, and `module_manifests` for the
modules that actually mounted in that run. The full detachable catalog belongs
to `research modules`, `research armory`, and `research profile`, not every
runtime receipt.

Receipts also include `evidence_quality`, a non-fetching quality report over the
results already collected. It separates search snippets from direct reads,
counts source classes such as official docs, code hosts, community, news, web,
social, and browser snapshots, and returns a bounded `score` with `none`,
`thin`, `usable`, or `strong` status. Stormbreaker packet summaries carry the
same compact quality status and score, so a packet can tell whether it has only
search snippets or actual read evidence without opening the full
`research-evidence.json`.

Receipts also include `evidence_coverage`, which answers a different question:
what kind of proof path was actually present. It marks search-only evidence,
direct reads, official Reddit/Threads API evidence, public Reddit/Threads
fallback evidence, and browser-backed evidence separately. Public social
fallback coverage includes direct platform fallbacks and search results whose
citations point to public Reddit or Threads URLs, exposed through
`public_social_fallback_platforms`. When a social public fallback works but
official credentials are missing, the receipt names the missing proof check
(`reddit_oauth_live_check` or `threads_live_graph_check`) and the required
environment variable names, never secret values. Stormbreaker copies the compact
coverage status, missing official social modules, missing env variable names,
blockers, and warnings into each packet summary.

Receipts and top-level research results also include `capability_summary`, which
is the operator-facing "what can I trust from this run?" view. It records the
resolved loadout, mounted modules, mounted slots, heavy modules, browser status,
social status, web evidence type, and missing proof IDs without including raw
source text, browser stdout, or secret values. Example statuses include
`ready`, `partial_public_social_fallback`, `partial_needs_proof`,
`needs_browser_config`, and `missing_evidence`. Stormbreaker copies this compact
summary into packet results so build agents can distinguish "usable public
fallback evidence" from "official Reddit/Threads API proof is complete."

The phase-0 ranker is intentionally light: it canonicalizes citations, merges
duplicates across search modules, prefers direct source URLs, lowers known
search-engine shell URLs, gives a small boost to query-term matches, and then
selects follow-up reads with host diversity before taking a second URL from the
same domain. When the request query or the search-result source context asks
for Reddit or Threads, matching Reddit/Threads direct URLs receive an additional
`social_host_requested` boost so public search fallbacks are more likely to read
the social source itself instead of a generic article first. It also honors the
request `max_cost.requests` budget before
scheduling follow-up reads, and query variants are counted against the same
source-hint request budget before they run. For `social` and `full` loadouts,
the source-hint budget uses a small diversity pass before trimming: it keeps
Reddit, Threads, and the no-token public-search fallbacks from being silently
pushed out by extra search providers or query variants, then preserves requested
follow-up read slots when enough request budget remains. CLI users can
set this budget with `--max-requests` on `research plan`, `research read`,
`research search`, and `research gather`. Runtime receipts expose the boundary under
`request_budget`, including source hints dropped by budget and whether follow-up
reads were capped. The selected candidates are written to the receipt as
`followup_candidates`, while the broader candidate pool is summarized under
`search_candidate_report` with source counts, host counts, direct-vs-search
shell totals, and the diversity strategy.

`research gather` is the higher-level search path. It uses `search:auto:<query>`
inside the engine, expands that to the search modules mounted by the current
loadout, and follows the top result URLs. This gives Stormbreaker and `/hep-*`
flows a better default research move without making Jina, browser modules, or
credentialed platform readers mandatory.
GitHub repository search is a light cartridge, but it does not join every
default search fan-out. It activates for explicit `--provider github`,
`search:github:<query>`, or GitHub/source hints such as `github`, `깃헙`, or
`repo:`.

When the caller explicitly chooses `social` or `full`, the same auto search
hint also adds bounded `reddit:search:<query>` and `threads:keyword:<query>`
platform hints. The default `auto`, `safe`, `public-web`, and `recommended`
paths do not add those official social API hints; they use public search
variants and public fallback readers instead.

`research preflight` is the build-time armory check. It does not fetch the web,
start browser commands, write receipts, or call provider APIs. It resolves the
requested loadout, including `recommended`, then returns the module mount table:
which search, reader, platform, and browser cartridges would be mounted, which
heavy cartridges stay detached, which mounted modules need local config, and
what source-hint budget the plan would use. This is the "spaceship weapon rack"
view for `/hep-build` and Stormbreaker: operators can see when browser or social
modules are attached before paying the runtime cost.

```bash
bin/hephaestus research preflight "agent browser modules 찾아봐"
bin/hephaestus research preflight "Threads와 Reddit 반응까지 조사"
bin/hephaestus research preflight "403 blocked dynamic browser page"
```

When Stormbreaker runs with `--research-evidence`, each research/planning packet
now materializes three files in its packet write scope:

- `research-preflight.json`: non-executing mount table, readiness blockers, and
  detached heavy modules.
- `research-status.json`: non-executing proof/readiness status, including public
  fallback proof coverage, browser hardpoint proof status, and missing official
  social credentials.
- `research-evidence.json`: executed research result, receipt, evidence quality,
  and coverage.

The packet contract and packet result include compact summaries for all three, and
external executors receive `STORMBREAKER_RESEARCH_PREFLIGHT_FILE` plus
`STORMBREAKER_RESEARCH_STATUS_FILE` plus `STORMBREAKER_RESEARCH_EVIDENCE_FILE`.
That keeps build agents aware of the module weight boundary and proof gaps
without requiring them to parse the full evidence receipt.

## Escalation Model

Research should move from light to heavy:

1. Search snippets or explicit source hints.
2. Safe static readers.
3. Official platform APIs.
4. Static browser snapshots.
5. Interactive browser actions.
6. Cloud or stealth browser providers, only with explicit policy approval.

Missing optional modules return `module_unavailable`; they do not crash the
runtime.

## Current Phase

Phase 0 supports explicit URL source hints, search hints, platform hints, and
bounded search follow-up through the built-in registry:

| Module | Weight | State | Purpose |
| --- | --- | --- | --- |
| `platform.reddit.oauth` | `credentialed_medium` | available if configured | OAuth-first Reddit reader for explicit Reddit URLs. Reads through `oauth.reddit.com`, accepts bearer tokens or app-only client credentials, records rate-limit headers, and never exposes token values to results or receipts. |
| `platform.reddit` | `adaptive_medium` | public fallback available | Explicit Reddit URLs via truthful User-Agent JSON/RSS fallback when OAuth is missing or unavailable. |
| `platform.threads` | `credentialed_medium` | available if configured | Official Threads keyword/tag search plus profile, profile lookup, posts, and replies through Graph API tokens. |
| `platform.threads.public` | `adaptive_medium` | public fallback available | Explicit Threads URLs and username/profile hints through bounded public HTML/meta reads; official API remains preferred. |
| `search.ddg_html` | `light` | available | No-key DuckDuckGo lite/html search for general web discovery with direct result URL extraction. |
| `search.news_rss` | `light` | available | No-key public RSS search for current/news-like web discovery. |
| `search.github_repos` | `light` | available | No-key GitHub REST repository search for public repo discovery. It is mounted by `public-web`/`full`, but auto fan-out uses it only for GitHub hints or explicit `--provider github`. |
| `search.jina` | `external_light` | available if configured | Jina web search cartridge for explicit `research search` calls; requires `AGENTLAS_JINA_API_KEY` or `JINA_API_KEY`. |
| `read.http` | `light` | available | Safe static HTTP/HTML reader. |
| `read.insane_fetch` | `adaptive_medium` | available if allowed | Bounded public-route fetch-chain inspired by an external resilient-reader design: direct read, Reddit `.rss`, Jina Reader fallback, metadata/feed parsing, route trace evidence, and hard stop on login/paywall. This stays a detachable public reader, not the core research engine. |
| `read.jina` | `external_light` | available if allowed | Jina Reader URL-to-markdown cartridge; plain URL reads are not sent to Jina unless this module is explicitly allowed. |
| `browser.playwright_mcp` | `browser_heavy` | available if configured | Optional Playwright MCP snapshot bridge. The engine calls a configured local snapshot command and records an accessibility-tree snapshot without importing Playwright or MCP packages. |
| `browser.browser_use` | `browser_heavy` | available if configured | Optional Browser Use snapshot bridge for local or hosted Browser Use harnesses. The engine calls a configured local command and records bounded text output. |
| `browser.stagehand` | `browser_heavy` | available if configured | Optional Stagehand snapshot/extraction bridge. The engine calls a configured local command and records bounded structured extraction text without importing Stagehand. |
| `browser.steel` | `browser_heavy` | available if configured | Optional Steel remote-browser bridge. The engine calls a configured local command and keeps provider tokens outside the core runtime. |
| `browser.hyperagent` | `browser_heavy` | available if configured | Optional HyperAgent/Hyperbrowser bridge. The engine calls a configured local command and keeps cloud-browser tokens outside the core runtime. |
| `browser.agent_cli` | `browser_heavy` | available if installed | Optional local `agent-browser` snapshot/ref hardpoint. Missing binary is nonfatal. |
| `browser.browseros` | `browser_heavy` | available if configured | Optional BrowserOS snapshot bridge. The engine calls a configured local command and keeps desktop profile state outside the core runtime. |

Current browser hardpoint candidates:

```bash
bin/hephaestus research browser-candidates
bin/hephaestus research browser-candidates --module browser.agent_cli
bin/hephaestus research browser-candidates --query "로컬 브라우저 스냅샷"
bin/hephaestus research browser-candidates --home ~/.agentlas/networking
```

This command is read-only. It does not check package registries, start browsers,
call provider APIs, or execute configured commands. It only combines the static
candidate catalog with local adapter readiness so operators can choose a mount
without silently increasing runtime weight.

Each candidate also includes a `mount_plan`. For registered browser bridges the
plan names the `browser_hardpoint_live_check` proof, the exact `bridge-check`
command that will create a receipt, and any safe setup command the operator can
choose.

- `browser.playwright_mcp`: first Playwright MCP hardpoint. Playwright MCP uses
  structured accessibility snapshots rather than screenshots. Agentlas keeps it
  as a command bridge so the core does not import browser/MCP packages.
- `browser.browser_use`: Browser Use hardpoint for agentic browser harnesses.
  Browser Use can use local or hosted browser infrastructure; Agentlas keeps it
  as a command bridge so provider tokens and browser dependencies stay outside
  the core engine.
- `browser.stagehand`: Stagehand hardpoint for code-first browser control and
  natural-language extraction. Agentlas keeps it as a command bridge so the
  core does not import SDK packages or provider credentials.
- `browser.steel`: remote browser infrastructure hardpoint for isolated cloud
  sessions. Provider tokens remain owned by the bridge command.
- `browser.hyperagent`: HyperAgent or Hyperbrowser-backed hardpoint for
  Playwright-plus-AI browser sessions. Agentlas only passes the requested URL to
  the configured command and stores bounded text output.
- `browser.agent_cli`: local CLI mount. `agent-browser` is agent-oriented, uses
  compact text output, refs, sessions, profiles, and supports Chrome or
  Lightpanda.
- `browser.browseros`: BrowserOS bridge for local-first browser flows. Agentlas
  keeps the desktop profile and provider details outside the engine and only
  calls a configured snapshot command after the operator mounts it.
- Browser bridge stderr and exception summaries are redacted before they enter
  receipts or status output. Bridge stdout is still treated as source evidence,
  so provider commands must not print credentials in successful snapshots.
- Reader, search, and platform adapter exception summaries use the same
  redaction path before they are written to receipts. HTTP status classes and
  missing environment variable names are still reported, but configured secret
  values are not.

Source-backed candidate anchors:

| Candidate | Primary source | Why it stays detachable |
| --- | --- | --- |
| Playwright MCP | <https://github.com/microsoft/playwright-mcp> | MCP/browser dependencies and accessibility snapshots are useful, but too heavy for the core. |
| Browser Use | <https://github.com/browser-use/browser-use> | Agentic browser harness can run local or hosted infrastructure, so credentials and runtime setup stay in the bridge. |
| Stagehand | <https://github.com/browserbase/stagehand> | Natural-language/code browser automation belongs behind an explicit command hardpoint. |
| Steel Browser | <https://github.com/steel-dev/steel-browser> | Remote browser/session infrastructure should remain an operator-approved hardpoint. |
| HyperAgent / Hyperbrowser | <https://github.com/hyperbrowserai/HyperAgent> and <https://www.hyperbrowser.ai/> | Browser infrastructure for AI agents belongs behind an explicit command hardpoint, not inside the core engine. |
| agent-browser | <https://github.com/vercel-labs/agent-browser> and <https://agent-browser.dev/> | Compact agent CLI output is a good local mount, but the binary is optional and nonfatal when missing. |
| BrowserOS | <https://github.com/browseros-ai/BrowserOS> and <https://docs.browseros.com/> | Local-first agentic browser shell can be mounted through an explicit snapshot command; desktop profile state stays outside the core. |

```python
from agentlas_cloud.research import run_research

result = run_research({
    "query": "Read the source",
    "source_hints": ["https://example.com"],
})
```

Terminal smoke:

```bash
bin/hephaestus research read https://example.com --query "Read example"
```

Read a URL with static plus one configured browser snapshot:

```bash
AGENTLAS_STAGEHAND_SNAPSHOT_CMD='agentlas-stagehand-snapshot {url}' \
  bin/hephaestus research read https://example.com \
  --loadout browser \
  --depth deep
```

Explicitly override a lower loadout's weight ceiling when a heavy hardpoint is
operator-approved:

```bash
AGENTLAS_STAGEHAND_SNAPSHOT_CMD='agentlas-stagehand-snapshot {url}' \
  bin/hephaestus research read https://example.com \
  --loadout safe \
  --allow-module browser.stagehand \
  --depth deep \
  --max-weight browser_heavy
```

Search the web through the no-key general web cartridge:

```bash
bin/hephaestus research search "agent browser modular research"
```

Search through the no-key news RSS cartridge:

```bash
bin/hephaestus research search "agent browser modular research" \
  --provider news-rss
```

Search public GitHub repositories without a token:

```bash
bin/hephaestus research search "agent browser modular research" \
  --provider github
```

Search and read the top three discovered pages:

```bash
bin/hephaestus research search "agent browser modular research" \
  --loadout public-web \
  --follow-results 3
```

Gather evidence with the public-web loadout. This performs search fanout through
the mounted search modules, dedupes result URLs, and reads up to three top
sources:

```bash
bin/hephaestus research gather "agent browser modular research"
```

Mount an extra configured search provider for a deeper gather:

```bash
AGENTLAS_JINA_API_KEY=... bin/hephaestus research gather "agent browser modular research" \
  --provider news-rss \
  --provider github \
  --provider jina \
  --follow-results 5
```

Search through the Jina cartridge when a key is configured:

```bash
AGENTLAS_JINA_API_KEY=... bin/hephaestus research search "agent browser modular research" \
  --provider jina
```

List detachable modules:

```bash
bin/hephaestus research modules
```

List modules plus local readiness, without running them:

```bash
bin/hephaestus research armory --loadout browser
```

List detachable loadouts:

```bash
bin/hephaestus research loadouts
```

Force the browser hardpoint when `agent-browser` is installed:

```bash
bin/hephaestus research read https://example.com \
  --allow-module browser.agent_cli
```

Inspect the command contract for a browser hardpoint before configuring it:

```bash
bin/hephaestus research bridge-contract --module browser.stagehand
bin/hephaestus research bridge-contract --module browser.agent_cli
```

The contract output never executes a browser and never prints configured command
values. For snapshot-command hardpoints, it describes the env var, argv rule,
accepted JSON fields, max stdout size, SSRF boundary, and sample output shape.
For `browser.agent_cli`, it describes the `agent-browser open`, `snapshot -i`,
and `close` sequence.

`browser.agent_cli` can be checked through an installed binary or through `npx`
without a global install:

```bash
AGENTLAS_AGENT_BROWSER_BIN='npx -y agent-browser' \
  bin/hephaestus research bridge-check \
  --module browser.agent_cli \
  --url https://example.com
```

On a clean machine, this is the fastest proof path for the agent-browser
hardpoint: the command opens the page, reads an accessibility snapshot, closes
the session, and returns `status=ok` with a research receipt id when successful.
For a durable local setup without exporting an env var every time, arm the
allowlisted recipe:

```bash
bin/hephaestus research hardpoints --arm browser.agent_cli --recipe npx-agent-browser
bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com
```

The same proof command is exposed in `research browser-candidates --query ...`
under `recommendation.check_command`, so a browser recommendation can be turned
into a live receipt without guessing which hardpoint to run.

After configuring a bridge command, check the hardpoint end to end:

```bash
AGENTLAS_STAGEHAND_SNAPSHOT_CMD='agentlas-stagehand-snapshot {url}' \
  bin/hephaestus research bridge-check \
  --module browser.stagehand \
  --url https://example.com
```

`bridge-check` is intentionally narrower than `research read`: it allows only
the selected browser module, raises the ceiling to `browser_heavy`, writes a
normal research receipt, and returns compact `attempts`, `browser_execution`, and
`result_summaries`. If the command is missing it returns `status=not_ready`; if
the URL is blocked by the SSRF guard it returns `status=blocked`; if the bridge
command fails it returns `status=failed`.

Use a configured Playwright MCP snapshot bridge:

```bash
AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD='agentlas-playwright-snapshot {url}' \
  bin/hephaestus research read https://example.com \
  --allow-module browser.playwright_mcp
```

The bridge command must print either plain snapshot text or JSON with one of
`snapshot`, `content_markdown`, `text`, or `stdout`. It is intentionally a thin
local-process boundary: missing commands return `module_unavailable`; they do
not install or import browser dependencies into Hephaestus.

Use a configured Browser Use snapshot bridge:

```bash
AGENTLAS_BROWSER_USE_SNAPSHOT_CMD='agentlas-browser-use-snapshot {url}' \
  bin/hephaestus research read https://example.com \
  --allow-module browser.browser_use
```

The Browser Use bridge accepts plain text or JSON with one of `result`,
`snapshot`, `content_markdown`, `text`, or `stdout`. Browser Use API keys,
profiles, and cloud/local session details remain owned by the bridge command,
not by the Research Engine.

Use a configured Stagehand snapshot/extraction bridge:

```bash
AGENTLAS_STAGEHAND_SNAPSHOT_CMD='agentlas-stagehand-snapshot {url}' \
  bin/hephaestus research read https://example.com \
  --allow-module browser.stagehand
```

Use a configured Steel remote-browser bridge:

```bash
AGENTLAS_STEEL_SNAPSHOT_CMD='agentlas-steel-snapshot {url}' \
  bin/hephaestus research read https://example.com \
  --allow-module browser.steel
```

Use a configured HyperAgent or Hyperbrowser-backed bridge:

```bash
AGENTLAS_HYPERAGENT_SNAPSHOT_CMD='agentlas-hyperagent-snapshot {url}' \
  bin/hephaestus research read https://example.com \
  --allow-module browser.hyperagent
```

Stagehand, Steel, and HyperAgent bridge commands accept plain text or JSON with
one of `content_markdown`, `extraction`, `snapshot`, `result`, `text`, or
`stdout`, depending on the hardpoint. Secrets and provider-specific session
details stay inside the bridge command.

Use a configured BrowserOS snapshot bridge:

```bash
AGENTLAS_BROWSEROS_SNAPSHOT_CMD='agentlas-browseros-snapshot {url}' \
  bin/hephaestus research read https://example.com \
  --allow-module browser.browseros
```

BrowserOS bridge commands follow the same stdout contract and are intentionally
operator-configured because they may use a persistent desktop browser profile.

Inspect platform cartridge contracts before configuring social research:

```bash
bin/hephaestus research platform-contract --module platform.reddit.oauth
bin/hephaestus research platform-contract --module platform.reddit
bin/hephaestus research platform-contract --module platform.threads
bin/hephaestus research platform-contract --module platform.threads.public
```

The contract output does not call Reddit or Threads and does not print token
values. It lists accepted source hints, credential environment variable names,
runtime notes, local readiness, and example check commands. Use it when deciding
whether a build needs durable OAuth/Graph evidence or only a labeled public
fallback.

Run one platform cartridge directly:

```bash
bin/hephaestus research platform-check \
  --module platform.reddit \
  --source "reddit:search:agent browser"

THREADS_ACCESS_TOKEN=... bin/hephaestus research platform-check \
  --module platform.threads \
  --source "threads:keyword:agent browser"

bin/hephaestus research platform-check \
  --module platform.threads.public \
  --source "threads:lookup:agentlas"
```

`platform-check` is intentionally narrower than `research read`: it allows only
the selected platform module and writes a normal research receipt. If
`platform.reddit.oauth` has no token it returns `status=not_ready` instead of
silently falling through to `platform.reddit`; check the public fallback
separately when that lower-confidence path is acceptable. If a Threads token is
missing, `platform.threads` also returns `status=not_ready` for keyword/tag
discovery. Use `platform.threads.public` only for explicit public Threads URLs
or username/profile hints; it does not perform hidden Threads search. If a
public Threads hint resolves to a login page, the result is marked
`auth_required` instead of being treated as usable profile evidence.
The broader `research read` / `research gather` path may add a lightweight
public web-search fallback for `threads:keyword:<query>` and
`reddit:search:<query>` when official platform APIs are not mounted, or when a
corresponding token is missing and search modules are mounted. Those fallbacks
are reported as `web_search` evidence, not as official platform API evidence.

Read a Reddit URL through the platform cartridge:

```bash
bin/hephaestus research read https://www.reddit.com/r/redditdev/ \
  --allow-module platform.reddit
```

Read Reddit without first discovering a URL:

```bash
bin/hephaestus research read "reddit:subreddit:redditdev" \
  --loadout public-web

bin/hephaestus research read "reddit:search:agent browser" \
  --loadout public-web
```

Supported public Reddit source hints are `reddit:subreddit:<name>`,
`reddit:r:<name>`, `reddit:user:<name>`, `reddit:u:<name>`, and
`reddit:search:<query>`. These hints normalize to public `www.reddit.com` URLs,
then use the public JSON/RSS cartridge unless the operator explicitly mounts
the OAuth cartridge through `social`, `full`, or an allow-list. Public fallback
results remain labeled with `public_json_fallback`, `public_rss_fallback`, and
`oauth_preferred` limits. When a `reddit:search:<query>` request runs through
the broader research engine without official Reddit API mounted, Agentlas also
adds bounded `site:reddit.com` web-search fallbacks so search-only evidence can
survive public Reddit JSON/RSS rate limits.

Read Reddit through OAuth first, then public fallback if no token is configured:

```bash
REDDIT_BEARER_TOKEN=... bin/hephaestus research read https://www.reddit.com/r/redditdev/ \
  --loadout social
```

Or configure a Reddit app-only OAuth pair and let the cartridge exchange it for
a short-lived access token:

```bash
AGENTLAS_REDDIT_CLIENT_ID=... \
AGENTLAS_REDDIT_CLIENT_SECRET=... \
bin/hephaestus research read https://www.reddit.com/r/redditdev/ --loadout social
```

The OAuth cartridge accepts bearer tokens from `AGENTLAS_REDDIT_BEARER_TOKEN` or
`REDDIT_BEARER_TOKEN`, or app-only client credentials from
`AGENTLAS_REDDIT_CLIENT_ID` plus `AGENTLAS_REDDIT_CLIENT_SECRET` (with
`REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` as aliases). It records
`X-Ratelimit-Used`, `X-Ratelimit-Remaining`, and `X-Ratelimit-Reset` as compact
limits, not token values. Reddit's OAuth documentation describes app-only access
using the `client_credentials` grant and bearer-token calls to
`oauth.reddit.com`; Reddit's broader Data API terms reserve commercial and
high-volume access behind the platform's policy and agreements. Agentlas
therefore treats durable Reddit access as a credentialed cartridge, with the
public JSON/RSS path only as a labeled fallback for explicit Reddit URLs.

Primary anchors:

- <https://developers.reddit.com/docs/capabilities/server/reddit-api>
- <https://github.com/reddit-archive/reddit/wiki/oauth2>
- <https://redditinc.com/policies/data-api-terms>

Search Threads through the official API cartridge:

```bash
THREADS_ACCESS_TOKEN=... bin/hephaestus research read "threads:keyword:agent browser" \
  --allow-module platform.threads
```

Read Threads profile/posts/replies through the same official API cartridge:

```bash
THREADS_ACCESS_TOKEN=... bin/hephaestus research read "threads:profile:me" \
  --loadout social

THREADS_ACCESS_TOKEN=... bin/hephaestus research read "threads:posts:me" "threads:replies:me" \
  --loadout social

THREADS_ACCESS_TOKEN=... bin/hephaestus research read "threads:lookup:agentlas" \
  --loadout social
```

Supported Threads source hints are `threads:keyword:<query>`,
`threads:tag:<tag>`, `threads:profile:<threads-user-id|me>`,
`threads:lookup:<username>`, `threads:posts:<threads-user-id|me>`, and
`threads:replies:<threads-user-id|me>`. Tokens come only from
`AGENTLAS_THREADS_ACCESS_TOKEN` or `THREADS_ACCESS_TOKEN` and are never written
to results or receipts. Threads keyword/tag discovery is kept on the official
API path instead of page scraping, because Meta exposes credentialed developer
endpoints for this class of read.
When no Threads token is configured, Agentlas can still mount the existing
search slot as a public discovery fallback by adding a bounded
`<query> Threads site:threads.com` search hint. That fallback can discover
public Threads URLs, but it remains lower-confidence web-search evidence until
the official API proof is configured.

To turn that discovered public URL into direct page evidence in the same read,
request a bounded follow-up:

```bash
bin/hephaestus research read "threads:keyword:agent browser" \
  --loadout auto \
  --follow-results 1
```

That follow-up still uses the public Threads URL reader and remains labeled as
public fallback evidence, not official Graph API evidence.

Primary anchors:

- <https://developers.facebook.com/docs/threads/>
- <https://developers.facebook.com/docs/threads/keyword-search/>

Read a URL through Jina Reader only when external reader disclosure is acceptable:

```bash
bin/hephaestus research read https://example.com \
  --allow-module read.jina
```

Try the adaptive public fetch-chain for blocked public pages:

```bash
bin/hephaestus research read https://example.com \
  --allow-module read.insane_fetch
```

The receipt records the attempted route chain, stop reason, and any untried
public fallback routes so the caller can decide whether to retry with a heavier
browser hardpoint.

## Stormbreaker Evidence

Stormbreaker can attach Research Engine evidence to planning/research packets
without making research mandatory for every build run:

```bash
bin/hephaestus hep-storm "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘" \
  --research-evidence

bin/hephaestus hep-storm "Threads와 Reddit 반응까지 조사해서 에이전트 빌드해줘" \
  --research-evidence \
  --research-loadout recommended

bin/hephaestus hep-storm "Threads와 Reddit 반응까지 조사해서 에이전트 빌드해줘" \
  --research-evidence \
  --research-loadout social \
  --research-depth deep \
  --research-follow-results 4 \
  --research-variant reddit
```

When enabled, planning/research packets get a bounded public research request.
The full result is written to the packet's `research-evidence.json`; the packet
contract and packet result keep only the receipt summary, normalized request
summary, capability summary, module chain, result count, and compact source
summaries. The request and capability summaries include loadout/depth, follow
count, source hints, query variants, mounted module IDs, browser status, social
fallback status, and missing proof IDs so reviewers can confirm which
detachable cartridges were actually used without exposing credentials or local
environment values.
Executor processes also receive:

```text
STORMBREAKER_RESEARCH_EVIDENCE_FILE
STORMBREAKER_RESEARCH_PREFLIGHT_FILE
STORMBREAKER_RESEARCH_STATUS_FILE
STORMBREAKER_RESEARCH_RECEIPT_ID
```

This keeps Stormbreaker evidence-based without turning the runtime into a
heavy crawler. The default Stormbreaker research loadout is `safe`; callers can
choose `recommended` to let Stormbreaker run the non-executing recommender for
each packet and resolve it to a concrete loadout such as `public-web` or
`browser`. Official Reddit/Threads API evidence remains opt-in through
`social`, `full`, or explicit module allow-lists. The packet summary records both the requested option and the
resolved recommendation so reviewers can see why a heavier cartridge was
mounted. The packet preflight and recommendation summaries include
`mount_decision`, so the receiving agent can see whether browser hardpoints,
credentialed social cartridges, public social fallbacks, and adaptive readers
were mounted or deliberately left detached. Callers can still explicitly choose
`social`, `browser`, or `full`
when they want heavier platform or browser hardpoints regardless of the
recommendation.
Stormbreaker includes the original user request in each default packet research
query before adding stage/card context, so `recommended` can still see user
signals like Reddit, Threads, blocked pages, or dynamic browser requirements.

With `social` or `full`, Stormbreaker augments its normal `search:auto:` hint
with `reddit:search:` and `threads:keyword:` hints so the platform cartridges
can contribute official evidence. With `recommended`, Stormbreaker keeps those
official API hints detached and instead adds `reddit` and `threads` query
variants so public web search has a no-token path. The `safe` default also
keeps those social hardpoints detached. If evidence collection is unavailable
or partial, the packet still runs and the research receipt records the
limitation.

Each run writes a research receipt to:

```text
~/.agentlas/networking/ledgers/research-receipts.jsonl
```

Callers can pass `home=<path>` to isolate receipts in tests or project-specific
networking state.

## Planned Modules

- Shared browser bridge helpers for multi-step action traces, screenshots, and
  human-visible replay artifacts.
