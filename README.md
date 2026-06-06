<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">agentlas-meta-agent</h1>

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

There are three install paths. Use **1 + 3** when you want the full Agentlas runtime. Use **2** only when you want this package installed directly into Claude Code, Codex, or a plain project folder.

| Path | Best for | What you open |
|---|---|---|
| 1. Agentlas Terminal | Running Agentlas agents from a shell | Agentlas Desktop first, then macOS Terminal / Windows PowerShell / Linux terminal |
| 2. Standalone agentlas-meta-agent | Claude Code, Codex, or a normal repo without Desktop | Claude Code, Codex, or your OS terminal |
| 3. Agentlas Desktop | Visual local runtime, agent/team management, vault, Apps | A browser for download, then the Agentlas Desktop app |

### 1. Install Agentlas Terminal

Agentlas Terminal is installed from **Agentlas Desktop**. First install Desktop, then open:

```text
Agentlas Desktop -> Settings -> Use from the terminal (`agentlas` CLI) -> Install CLI
```

After that, open your normal terminal and run `agentlas`.

**macOS Terminal**

```bash
arch=$([ "$(uname -m)" = "arm64" ] && echo arm64 || echo x64)
curl -fL "https://agentlas.cloud/api/desktop/download?arch=${arch}" -o Agentlas.dmg
open Agentlas.dmg
```

**Windows PowerShell**

```powershell
$r = Invoke-RestMethod https://api.github.com/repos/agentlas-ai/agentlas-desktop/releases/latest
$u = ($r.assets | Where-Object { $_.name -like '*Windows-x64-Setup.exe' }).browser_download_url
Invoke-WebRequest $u -OutFile "$env:TEMP\AgentlasSetup.exe"
Start-Process "$env:TEMP\AgentlasSetup.exe"
```

**Linux terminal, AppImage**

```bash
url=$(curl -fsSL https://api.github.com/repos/agentlas-ai/agentlas-desktop/releases/latest \
  | grep -o 'https://[^"]*Linux-x64\.AppImage' | head -1)
curl -fL "$url" -o Agentlas.AppImage
chmod +x Agentlas.AppImage
./Agentlas.AppImage
```

**Linux terminal, Debian/Ubuntu**

```bash
url=$(curl -fsSL https://api.github.com/repos/agentlas-ai/agentlas-desktop/releases/latest \
  | grep -o 'https://[^"]*Linux-x64\.deb' | head -1)
curl -fL "$url" -o agentlas.deb
sudo dpkg -i agentlas.deb
```

After installing the CLI from Desktop Settings:

```bash
agentlas list
agentlas run agentlas-meta-agent "Package this workflow for Agentlas"
```

### 2. Install agentlas-meta-agent standalone

#### Simple file install

Open macOS Terminal, Linux terminal, Windows Git Bash, or WSL in the project folder where you want the package files installed:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.1.6/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Windows PowerShell:

```powershell
$zip = "$env:TEMP\agentlas-meta-agent-v0.1.6.zip"
$extract = "$env:TEMP\agentlas-meta-agent-v0.1.6"
Invoke-WebRequest "https://github.com/agentlas-ai/Hephaestus/archive/refs/tags/v0.1.6.zip" -OutFile $zip
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $extract -Force
$src = Get-ChildItem $extract -Directory | Select-Object -First 1
Get-ChildItem $src.FullName -Force | Copy-Item -Destination (Get-Location) -Recurse -Force
```

#### Claude Code plugin install

Marketplace registration and plugin installation are separate steps. The marketplace command only registers where Claude Code can find this repo. The install command actually installs the plugin. Reload after install.

Inside a **Claude Code chat**, type:

```text
/plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
/plugin install agentlas-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

From your **OS terminal** with the `claude` CLI available:

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

Expected result after reload:

```text
✓ Installed agentlas-meta-agent. Run /reload-plugins to apply.
Reloaded: 1 plugin · 0 skills · 9 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

#### Codex plugin install

Inside a **Codex chat**, type:

```text
/plugin marketplace add agentlas-ai/Hephaestus --ref v0.1.6
/plugin install agentlas-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

From your **OS terminal** with the `codex` CLI available:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.1.6
codex plugin list
codex plugin add agentlas-meta-agent@agentlas-core-engine
codex plugin list
```

If a Codex session was already open, run `/reload-plugins` or start a new session.

### 3. Install Agentlas Desktop

Open this page in your browser:

```text
https://agentlas.cloud/desktop
```

Desktop gives you the visual Agentlas surface: local projects, agents, teams, Apps, vault references, runtime selection, built-in Core Engine Meta-Agent routing, and the `agentlas` CLI installer.

## Visual Install Guide

Use the slash-command images when you are already inside a Claude Code or Codex chat. Use the CLI images when you are in macOS Terminal, Windows PowerShell, Linux terminal, Git Bash, or WSL.

### Claude Code chat

Type these commands directly into Claude Code:

![Claude Code chat install flow](assets/install-claude-code-chat.svg)

### Claude CLI from your OS terminal

Use this path when the `claude` command is available in your shell:

![Claude CLI install flow](assets/install-claude-cli.svg)

### Codex chat

Type these commands directly into Codex:

![Codex chat install flow](assets/install-codex-chat.svg)

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
| Install Codex plugin by slash command | Codex chat | `/plugin marketplace add ...`, `/plugin install ...`, `/reload-plugins` |
| Install Codex plugin by shell | OS terminal | `codex plugin marketplace add ...`, `codex plugin add ...` |

## What It Builds

`agentlas-meta-agent` leaves behind a repository that another runtime can inspect, install, verify, and keep improving.

| You ask for | It routes to | You get |
|---|---|---|
| "Make one agent that does X" | `10-single-agent-builder` | One installable worker with skills, memory contracts, runtime adapters, and verification |
| "Make a team/company for this workflow" | `20-multi-agent-team-builder` | A multi-role operating team with HQ, PM Soul, Memory Curator, Policy Gate, eval, QA, and handoffs |
| "Package this existing agent/repo/workspace" | `30-agentlas-packager` | A cleaned Agentlas package for Desktop import, terminal use, Codex, Claude, Gemini, or public GitHub release |

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
.agents/
.claude/
.gemini/
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
| `.agentlas` auto-activation | Lets local runtimes seed project memory, sitemap/task-bias, Memory Tickets, and vault references |
| Skill lifecycle registry | Ships candidate skill metadata, empty trial ledgers, and Curator decision ledgers before first-class recall |
| Super Ontology candidate layer | Seeds public-safe graph and memory governance files for source lineage, privacy, task coverage, causality, consensus, repair, and reflexive feedback checks |
| Production Ontology Runtime | Ingests local sources into SQLite/FTS chunks, entities, relations, GraphRAG retrieval, Memory Curator tickets, and Agent Working Memory cache |

The default export state is conservative. Generated skills are searchable candidate metadata, not automatically promoted runtime behavior. A local Curator must see execution evidence, sealed holdout or replay proof, rollback coverage, and workspace policy approval before a skill becomes first-class recall.

### Production Ontology Runtime

For knowledge-heavy personal or company agents, Hephaestus now ships a real local-first ontology runtime under `ontology/` with the executable CLI `bin/ontology`. It turns approved files into an agent-readable source archive, chunk store, full-text index, deterministic local vector index, ontology graph, GraphRAG result, Memory Curator candidate ticket, and Agent Working Memory cache.

The Super Ontology files under `.agentlas/` remain the safety/governance layer. They define the source-lineage, privacy, task-coverage, causal, consensus, and memory-write gates around the runtime. The runtime is the implementation layer.

Supported ingest formats:

| Format | Status |
|---|---|
| `.txt`, `.md`, `.json`, `.csv` | parsed |
| `.docx`, `.xlsx`, `.pptx` | parsed through OpenXML adapters |
| `.pdf`, `.hwp` / `.hwpx`, images/OCR, unknown extensions | `unsupported_pending_adapter` |

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
| Search index | Uses SQLite FTS5 plus a pluggable vector adapter; the default is deterministic local hashing when no provider key exists |
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

See [`docs/ontology-runtime.md`](docs/ontology-runtime.md) for the schema, adapter boundaries, storage commands, verification coverage, and current limits.

## Why Agentlas Desktop And Terminal Make It Better

Desktop and Terminal make this package useful beyond a static prompt:

- Desktop shows the agent/team structure, local projects, Apps, vault references, and runtime choices.
- Terminal runs the same package from a shell with `agentlas`.
- The built-in Core Engine Meta-Agent path means fresh Desktop/Terminal installs can create or package agents without a separate standalone plugin install.
- Standalone Claude/Codex install is still useful when you want this package directly inside those runtimes.

## Compare

| Compared with | Their strength | What `agentlas-meta-agent` adds |
|---|---|---|
| OpenAI / Codex | Strong models and coding terminal | Portable repo contracts, `.agentlas` memory/package files, skills, schemas, runtime adapters, and public verification |
| Claude / Claude Code | Strong reasoning and Claude-native workflows | Claude support without becoming Claude-only; Codex, Gemini, Desktop, terminal, and `AGENTS.md` stay aligned |
| OpenClaw | Local identity and workspace agent loop | Visible role folders, Agentlas package contracts, public-safety checks, Desktop import, vault references, and install surfaces |
| Hermes | Persona and memory-centered local agent runtime | PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, and skill lifecycle evidence as files |

OpenAI and Claude are model/runtime surfaces. OpenClaw and Hermes are local-agent experiences. `agentlas-meta-agent` is the package layer that makes agents portable, inspectable, installable, and publishable.

## Use It

Single agent:

```text
/meta-agent Create a research agent for SEC filing analysis.
Package it for Codex, Claude Code, Gemini, and Agentlas Desktop.
```

Multi-agent team:

```text
Use agentlas-meta-agent.
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
