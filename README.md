<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus</h1>

<p align="center">
  <strong>Turn one rough agent idea into an installable Agentlas agent or team repository.</strong>
</p>

<p align="center">
  Build one specialist, assemble a multi-agent team, or package an existing Claude/Codex/OpenClaw/Hermes workspace into a public-safe Agentlas repo.
</p>

<p align="center">
  <a href="https://github.com/agentlas-ai/Hephaestus/releases/latest">
    <img alt="Latest release" src="https://img.shields.io/github/v/release/agentlas-ai/Hephaestus?label=release">
  </a>
  <a href="LICENSE">
    <img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green">
  </a>
  <img alt="Runtimes" src="https://img.shields.io/badge/runtimes-Agentlas%20Desktop%20%7C%20Terminal%20%7C%20Claude%20Code%20%7C%20Codex-black">
</p>

<p align="center">
  <a href="README.md">English</a>
  ·
  <a href="README.ko.md">한국어</a>
  ·
  <a href="README.zh-CN.md">中文</a>
  ·
  <a href="README.ja.md">日本語</a>
  ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a>
  ·
  <a href="#what-you-open-and-where-you-type">Where To Type</a>
  ·
  <a href="#visual-install-guide">Visual Install Guide</a>
  ·
  <a href="#what-it-builds">What It Builds</a>
  ·
  <a href="#architecture">Architecture</a>
  ·
  <a href="#compare">Compare</a>
  ·
  <a href="https://agentlas.cloud/desktop">Desktop</a>
</p>

<p align="center">
  <img src="assets/agentlas-meta-agent-architecture.svg" alt="Figure 1. Agentlas Meta-Agent architecture decomposition">
</p>

<p align="center">
  <sub>Figure 1. Request shaping, three builders, generated package contracts, memory curation, skill lifecycle, runtime adapters, and sync boundaries.</sub>
</p>

---

## Quickstart

Use one of these paths on a new computer. Start with a Claude Code or Codex
plugin install unless you only want the package files copied into a normal
project folder.

### Step 0. Fresh macOS check

Claude and Codex plugin marketplace commands use `git clone`. On a fresh Mac,
`git` requires Apple's Command Line Tools. If you see
`xcode-select: note: No developer tools were found`, run this once:

```bash
xcode-select --install
```

Finish the Apple installer popup, open a new Terminal window, then verify:

```bash
git --version
```

After `git --version` works, rerun the Claude or Codex plugin install command.

### Recommended. One terminal command for all runtimes

Run this from your normal OS terminal. It installs or updates the Claude Code
plugin, Codex plugin, and Gemini CLI extension/custom command. It also fixes the
common `Already added from a different source` marketplace conflict by removing
the old `agentlas-core-engine` entry and adding it again from this repo.

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.6/scripts/install-all-runtimes.sh | bash
```

After it finishes, restart any open Claude Code, Codex, or Gemini sessions.
Then use:

```text
Claude Code: /reload-plugins, then /hephaestus ontology
Codex:       /plugins, then /hephaestus ontology
Gemini CLI:  /extensions list or /commands list, then /hephaestus
```

Use the same command again to update to the packaged ref. To force a different
ref:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | HEPHAESTUS_REF=main bash
```

### Option A. Claude Code plugin

Open your normal OS terminal, not the Claude chat box, and run:

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```

Then open or restart Claude Code in the project you want to work on and type:

```text
/reload-plugins
/hephaestus ontology
```

If you already installed the old `agentlas-meta-agent` plugin and Claude says
`hephaestus` is not found, refresh the marketplace and replace the old plugin:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.6/scripts/install-all-runtimes.sh | bash
```

`/hephaestus ontology` opens a local ontology dashboard for the current project.
It creates these files in that project only:

```text
.agentlas/ontology-inbox/
.agentlas/ontology-sources.json
.agentlas/ontology-runtime.sqlite
.agentlas/ontology-gui/index.html
```

It does not scan your home folder or sibling projects. Put approved company docs
inside `.agentlas/ontology-inbox/`, then run `/hephaestus ontology` again.

To create agents or teams after install:

```text
/hephaestus create a research agent for SEC filing analysis
/hephaestus create a customer support operations team
/hephaestus package this existing Claude agent into Agentlas architecture
```

Claude also supports `claude plugins ...` as an alias, but this README uses
`claude plugin ...` everywhere so the command shape stays consistent.

### Option B. Codex plugin

Open your normal OS terminal, not the Codex chat box, and run:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.6
codex plugin add hephaestus@agentlas-core-engine
```

Then open or restart Codex in the project you want to work on and type:

```text
/hephaestus ontology
```

If Codex still shows `agentlas-meta-agent`, refresh the marketplace and replace
the old plugin:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.6/scripts/install-all-runtimes.sh | bash
```

The Codex OS-terminal CLI command is singular: `codex plugin`, not
`codex plugins`. Inside the Codex app, the slash command for the plugin browser
is plural: `/plugins`. After plugin install, `/hephaestus ontology` creates and
opens the same project-local ontology dashboard:

```text
.agentlas/ontology-gui/index.html
```

To create agents or teams after install:

```text
/hephaestus create a self-evolving research agent
/hephaestus create a finance analyst team
/hephaestus package this existing Codex workspace into Agentlas architecture
```

Every generated or packaged Agentlas agent receives a global command during
creation. The final handoff must include `global_commands` for Claude Code,
Codex, Gemini CLI, generic `AGENTS.md` tools, and terminal use. For a team,
that public command routes to the orchestrator/HQ.

### Option C. Copy the files into a project

Use this if you are not installing the Claude/Codex plugin and just want the
repo package files in your current project. Open macOS Terminal, Linux terminal,
Windows Git Bash, or WSL in that project folder and run:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.6/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Windows PowerShell:

```powershell
$zip = "$env:TEMP\hephaestus-v0.2.6.zip"
$extract = "$env:TEMP\hephaestus-v0.2.6"
Invoke-WebRequest "https://github.com/agentlas-ai/Hephaestus/archive/refs/tags/v0.2.6.zip" -OutFile $zip
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $extract -Force
$src = Get-ChildItem $extract -Directory | Select-Object -First 1
Get-ChildItem $src.FullName -Force | Copy-Item -Destination (Get-Location) -Recurse -Force
```

After file install, run the ontology GUI directly:

```bash
bin/hephaestus ontology
```

### Optional Claude Code in-chat plugin install

Use this only when you are already inside Claude Code and want to install from
the Claude chat UI instead of the OS terminal.

Claude Code chat:

```text
/plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
/plugin install hephaestus@agentlas-core-engine
/reload-plugins
/hephaestus ontology
```

Codex does not accept `/plugin marketplace add` inside the app. In Codex,
install from the OS terminal with `codex plugin ...`, then restart Codex and
use `/plugins` only to browse or enable installed plugins. After Hephaestus is
installed, run `/hephaestus ontology`.

If a Claude chat session does not show the new command after install, restart
Claude Code in that project.

## Visual Install Guide

Use the Claude slash-command image only when you are already inside Claude
Code. For Codex, install from the OS terminal; inside the Codex app, use
`/plugins` to browse installed plugins.

### Claude Code chat

Type these commands directly into Claude Code:

![Claude Code chat install flow](assets/install-claude-code-chat.svg)

### Claude CLI from your OS terminal

Use this path when the `claude` command is available in your shell:

![Claude CLI install flow](assets/install-claude-cli.svg)

### Codex app plugin browser

Use this only after the OS-terminal `codex plugin ...` install:

![Codex app plugin browser](assets/install-codex-chat.svg)

### Codex Desktop or IDE Extension

Use this path when Codex shows a Plugins settings screen:

![Codex Desktop settings install flow](assets/install-codex-desktop-settings.svg)

### Codex CLI from your OS terminal

Use this path when the `codex` command is available in your shell:

![Codex CLI install flow](assets/install-codex-cli.svg)

## What You Open And Where You Type

| Task | Open this | Type here |
|---|---|---|
| Download Desktop | Browser | `https://agentlas.cloud/desktop` or the OS download command |
| Install `agentlas` CLI | Agentlas Desktop | Settings -> Use from the terminal -> Install CLI |
| Run Agentlas Terminal | OS terminal | `agentlas list`, `agentlas run ...` |
| Install Claude plugin by slash command | Claude Code | `/plugin marketplace add ...`, `/plugin install ...`, `/reload-plugins` |
| Install Claude plugin by shell | OS terminal | `claude plugin marketplace add ...`, `claude plugin install ...` |
| Browse installed Codex plugins | Codex app | `/plugins` |
| Install Codex plugin by shell | OS terminal | `codex plugin marketplace add ...`, `codex plugin add ...` |

## What It Builds

Hephaestus leaves behind a repository that another runtime can inspect, install, verify, and keep improving.

| You ask for | It routes to | You get |
|---|---|---|
| "Make one agent that does X" | `10-single-agent-builder` | One installable worker with skills, memory contracts, runtime adapters, and verification |
| "Make a team/company for this workflow" | `20-multi-agent-team-builder` | A multi-role operating team with HQ, PM Soul, Memory Curator, Policy Gate, eval, QA, and handoffs |
| "Package this existing agent/repo/workspace" | `30-agentlas-packager` | A cleaned Agentlas package for Desktop import, terminal use, Codex, Claude, Gemini, or public GitHub release |

All three modes must create `.agentlas/global-commands.json` and report the
exact global command after generation. The user should not have to infer how to
run the new agent.

Generated or repaired packages can include:

```text
AGENTS.md
CLAUDE.md
GEMINI.md
agent.md
agents/
skills/
modes/
.agentlas/
.agentlas/global-commands.json
.agents/
.claude/
.gemini/
.gemini/commands/
codex/
schemas/
templates/
scripts/verify-package.sh
scripts/public_safety_check.sh
```

## Architecture

The public core is the architecture and foldering contract. Runtime-specific folders are adapters over the same core, not separate sources of truth.

| Public contract | What it does |
|---|---|
| Mode auto-detection | Chooses `single-agent-creator`, `team-builder`, or `agentlas-packager` before generation |
| Clarify question loop | Asks only package-shaping questions that affect runtime, public boundary, tools, or safety |
| Global command registry | Adds `.agentlas/global-commands.json`, runtime command files, and the final `global_commands` handoff |
| `.agentlas` auto-activation | Lets local runtimes seed project memory, sitemap/task-bias, Memory Tickets, and vault references |
| Skill lifecycle registry | Ships candidate skill metadata, empty trial ledgers, and Curator decision ledgers before first-class recall |
| Super Ontology candidate layer | Seeds public-safe graph and memory governance files for source lineage, privacy, task coverage, causality, consensus, repair, and reflexive feedback checks |
| Production Ontology Runtime | Ingests local sources into SQLite/FTS chunks, entities, relations, GraphRAG retrieval, Memory Curator tickets, and Agent Working Memory cache |

The default export state is conservative. Generated skills are searchable candidate metadata, not automatically promoted runtime behavior. A local Curator must see execution evidence, sealed holdout or replay proof, rollback coverage, and workspace policy approval before a skill becomes first-class recall.

### Production Ontology Runtime

For knowledge-heavy personal or company agents, Hephaestus now ships a real local-first ontology runtime under `ontology/` with the executable CLI `bin/ontology`. It turns approved files into an agent-readable source archive, chunk store, full-text index, vector index, ontology graph, GraphRAG result, Memory Curator candidate ticket, and Agent Working Memory cache.

The Super Ontology files under `.agentlas/` remain the safety/governance layer. They define the source-lineage, privacy, task-coverage, causal, consensus, and memory-write gates around the runtime. The runtime is the implementation layer.

Supported ingest formats:

| Format | Status |
|---|---|
| `.txt`, `.md`, `.json`, `.csv` | parsed |
| `.docx`, `.xlsx`, `.pptx` | parsed through OpenXML adapters |
| `.pdf` | parsed through `pdftotext` when installed |
| `.hwpx` | parsed through the HWPX XML adapter |
| images/OCR | parsed through macOS Vision OCR or Tesseract when available |
| `.hwp` binary | parsed through `hwp5txt` when available; otherwise clearly reported as `unsupported_pending_adapter` |
| unknown extensions | `unsupported_pending_adapter` |

The storage default is SQLite at `.agentlas/ontology-runtime.sqlite`, ignored by Git. The schema includes `sources`, `source_lineage`, `chunks`, `chunk_fts`, `entities`, `entity_aliases`, `relations`, `memory_candidates`, `memory_candidate_events`, `working_memory`, `runtime_adapters`, and `schema_migrations`.

Basic local run:

```bash
bin/ontology ingest examples/ontology-corpus --scope internal
bin/ontology query "Project Helios Memory Curator" --agent verifier
bin/ontology graph entity "Project Helios"
bin/ontology memory candidates
bin/ontology working-memory read --agent verifier
bin/ontology verify
```

The query response includes relevant chunks, related entities, relation edges, evidence refs, source spans, confidence, Memory Curator candidate suggestions, and optional Agent Working Memory writes. It is not a vector-only result.

The runtime stack is layered:

| Layer | Role |
|---|---|
| Source archive and chunk store | Stores source metadata, checksum, source type, parser status, version, privacy scope, lineage, chunks, source spans, token estimates, and checksums |
| Search index | Uses SQLite FTS5 plus local hashing vectors; no API key is needed and source text stays local |
| Ontology graph | Stores entities, aliases, relations, confidence, evidence chunks, observed/valid time fields, source lineage, and active/stale/deprecated status |
| GraphRAG retriever | Returns text evidence and graph slices together |
| Memory Curator bridge | Creates candidate tickets only; direct durable memory writes are blocked |
| Agent Working Memory | Per-agent hot cache with task/session scope, source refs, confidence, importance, TTL, last-used time, and invalidation reason |

Memory Curator flow:

```bash
bin/ontology memory candidates
bin/ontology memory decide <ticket-id> approve --reason "Curator accepted source-backed fact"
bin/ontology memory decide <ticket-id> quarantine --reason "Needs source owner review"
```

Approval records review state but still does not write durable memory. The Memory Curator owns durable promotion. Agent Working Memory is intentionally a cache, not a source of truth.

See [`docs/ontology-runtime.md`](docs/ontology-runtime.md) for the schema, adapter behavior, storage commands, and verification coverage.

## Why Agentlas Desktop And Terminal Make It Better

Desktop and Terminal make this package useful beyond a static prompt:

- Desktop shows the agent/team structure, local projects, Apps, vault references, and runtime choices.
- Terminal runs the same package from a shell with `agentlas`.
- The built-in Core Engine Meta-Agent path means fresh Desktop/Terminal installs can create or package agents without a separate standalone plugin install.
- Standalone Claude/Codex install is still useful when you want this package directly inside those runtimes.

## Compare

| Compared with | Their strength | What Hephaestus adds |
|---|---|---|
| OpenAI / Codex | Strong models and coding terminal | Portable repo contracts, `.agentlas` memory/package files, skills, schemas, runtime adapters, and public verification |
| Claude / Claude Code | Strong reasoning and Claude-native workflows | Claude support without becoming Claude-only; Codex, Gemini, Desktop, terminal, and `AGENTS.md` stay aligned |
| OpenClaw | Local identity and workspace agent loop | Visible role folders, Agentlas package contracts, public-safety checks, Desktop import, vault references, and install surfaces |
| Hermes | Persona and memory-centered local agent runtime | PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, and skill lifecycle evidence as files |

OpenAI and Claude are model/runtime surfaces. OpenClaw and Hermes are local-agent experiences. Hephaestus is the package layer that makes agents portable, inspectable, installable, and publishable.

## Use It

Single agent:

```text
/meta-agent Create a research agent for SEC filing analysis.
Package it for Codex, Claude Code, Gemini, and Agentlas Desktop.
```

Multi-agent team:

```text
Use Hephaestus.
Build a customer-support operations team with PM Soul, Memory Curator, Policy Gate, QA, eval, and public-safe release checks.
```

Package an existing workspace:

```text
Package this local OpenClaw/Hermes-style workspace into Agentlas architecture.
Keep private notes, machine paths, raw logs, and secrets out of the public repo.
```

## Docs By Goal

| Goal | Start here |
|---|---|
| Understand the canonical route | [`AGENTS.md`](AGENTS.md) |
| See the full team contract | [`agent.md`](agent.md) |
| See the architecture source of truth | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| Understand runtime boundaries | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| Choose a mode | [`docs/mode-classifier.md`](docs/mode-classifier.md) |
| Ask the right setup questions | [`docs/clarify-question-loop.md`](docs/clarify-question-loop.md) |
| Activate local `.agentlas` workspace files | [`docs/agentlas-auto-activation.md`](docs/agentlas-auto-activation.md) |
| Review skill lifecycle promotion | [`docs/skill-lifecycle-promotion.md`](docs/skill-lifecycle-promotion.md) |
| Run the production ontology runtime | [`docs/ontology-runtime.md`](docs/ontology-runtime.md) |
| Review Super Ontology candidate contract | [`docs/super-ontology-candidate-contract.md`](docs/super-ontology-candidate-contract.md) |
| Understand graph and Memory Curator boundaries | [`docs/super-ontology-candidate-contract.md`](docs/super-ontology-candidate-contract.md) |
| Verify ontology runtime behavior | [`scripts/verify-ontology-runtime.sh`](scripts/verify-ontology-runtime.sh) |
| Verify a package | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| Check public safety | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

## Public Safety Boundary

This repo intentionally does **not** include hosted Agentlas billing/account logic, production credentials, customer data, raw private logs, raw transcripts, desktop keychain storage, local database implementation, or private deployment configuration.

Public output packages should not include local machine paths, API keys, tokens, private keys, service-account JSON, `.env` secrets, private research notes, raw chat transcripts, customer logs, hosted billing/account/OAuth internals, or desktop storage internals.

## Contributing

Before opening a PR or publishing a release, run:

```bash
scripts/verify-package.sh
scripts/verify-ontology-runtime.sh
scripts/public_safety_check.sh
```

## License

Apache-2.0. See [LICENSE](LICENSE).
