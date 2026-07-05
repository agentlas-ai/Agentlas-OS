<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus — Model-Agnostic Agent OS</h1>

<p align="center">
  <strong>Stop building and configuring a new agent for every task. Hephaestus keeps specialist agents in a hub and spins up a temporary orchestrator per task.</strong><br>
  Local-first, works with any model — Claude Code, Codex, Gemini, Cursor, and local models.
</p>

<p align="center">
  <a href="https://github.com/agentlas-ai/Hephaestus/releases/latest">
    <img alt="Latest release" src="https://img.shields.io/github/v/release/agentlas-ai/Hephaestus?label=release">
  </a>
  <a href="LICENSE">
    <img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green">
  </a>
  <img alt="Runtimes" src="https://img.shields.io/badge/runtimes-Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20%7C%20Antigravity%20%7C%20Cursor%20%7C%20DeepSeek%20%7C%20GLM%20%7C%20Ollama%20%7C%20Terminal-black">
</p>

<p align="center">
  <a href="README.md">English</a>
  ·
  <a href="README.ko.md">Korean</a>
  ·
  <a href="README.zh-CN.md">中文</a>
  ·
  <a href="README.ja.md">日本語</a>
  ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center">
  <img src="assets/hephaestus-network-mcp-demo.gif" alt="Hephaestus Network 2.0 routing a task live to the right agent over MCP" width="760">
</p>

<p align="center">
  <sub>Specialists pulled from the hub, assembled into a temporary task force, and routed live over MCP — no per-task agent setup.</sub>
</p>

## Quickstart

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```

This installs the neutral runner and registers command adapters for Claude Code, Codex, Gemini CLI, Antigravity, and Cursor. Prefer a plugin, a manual copy, or letting your AI install it for you? See [All Install Methods](#all-install-methods).

<p align="center">
  <a href="#the-agent-os-era">The Agent OS Era</a>
  ·
  <a href="#quickstart">Quickstart</a>
  ·
  <a href="#all-install-methods">All Install Methods</a>
  ·
  <a href="#the-command-surface">Command Surface</a>
  ·
  <a href="#new-in-v110--the-briefing-interview-engine">New in v1.1.0</a>
  ·
  <a href="#the-os-subsystems">Subsystems</a>
  ·
  <a href="#built-for-the-enterprise">Enterprise Operations</a>
  ·
  <a href="#what-it-builds">System Packaging</a>
  ·
  <a href="#docs-by-goal">Docs Registry</a>
  ·
  <a href="#the-desktop-shell--agentlas-desktop">Desktop Shell</a>
</p>

---

## The Agent OS Era

The industry has evolved past stateless, ad-hoc "chatbots with tools". With Google and major AI labs reframing developer strategies around **Agent Operating Systems** (such as the Antigravity orchestration platform and Gemini Spark daemon processes), AI agents have officially become first-class operating-system primitives—long-lived, stateful processes with distinct identities, relational memory systems, security permissions, and native tool-calling environments.

This shifts the critical engineering question for teams: **Whose operating system does your workforce run on?**

If your agents are tightly coupled to a single model provider's proprietary API, your organizational memory, custom tools, and task-specific logic are effectively locked into that vendor's ecosystem.

**Hephaestus is the independent, model-agnostic kernel.** It is not an agent framework or an API wrapper. It is a local-first Agent Operating System—a unified execution substrate that compiles, schedules, and governs portable agent processes across any host runtime. Swap the underlying reasoning engine; preserve the entire workforce.

Hephaestus maps directly to classical operating system concepts:

| OS Abstraction | Implementation in Hephaestus |
| :--- | :--- |
| **Kernel / Policy Gate** | Deterministic router + security gates. Every routing action yields an auditable receipt; tool execution permissions are strictly sandboxed and enforced by the host runtime. |
| **Processes / Threads** | Independent agents and multi-agent teams compiled as packages with explicit, typed contracts (Routing Cards, anti-scopes, memory boundaries, and verification shims). |
| **Process Scheduler** | Network 2.0 routing (local-first, quality-gated, and benchmark-gated dispatch) combined with Stormbreaker's parallel execution fabric and append-only run journals. |
| **Memory Management (MMU)** | Two-boundary governed memory: local project memory remains isolated on the machine, while durable promotions are gated by a local Memory Curator. |
| **Virtual File System** | Production Ontology Runtime: local-first source ingestion, CJK trigram FTS5 search, hybrid Reciprocal Rank Fusion, and GraphRAG retrieval. |
| **Inter-Process Call (IPC)** | A2A Agent Card Boundary (cryptographic import/export and caller-gating) + Model Context Protocol (MCP) tool registrations. |
| **Package Manager** | Agentlas Hub & Cloud: compile, publish, version, and share agents with built-in quality gates. |
| **Shell Interface** | A small, unified command set in external client runtimes; plain-language intent routing in native Agentlas shells. |
| **Process Initialization** | Meta-Agent Factory with an integrated Briefing Interview Gate—specifying agent parameters before compiling code. |

<p align="center">
  <img src="assets/agentlas-meta-agent-architecture.svg" alt="Figure 1. Agentlas Meta-Agent architecture decomposition">
</p>

<p align="center">
  <sub>Figure 1. Request shaping, three builders, generated package contracts, memory curation, skill lifecycle, runtime adapters, and sync boundaries.</sub>
</p>

---

## New In v1.1.0 — The Briefing Interview Engine

Agents generated from vague, single-sentence prompts fail under real-world edge cases. Hephaestus v1.1.0 positions task specification as a first-class OS service through the **Briefing Interview Engine**:

*   **Quantitative Ambiguity Gates:** The compilation scheduler evaluates prompt clarity across four key vectors (Goal, Constraints, Scope, Context). The build process is strictly gated until the ambiguity score passes a numeric threshold (ambiguity score $\le 0.2$, with per-dimension safety floors). Clear prompts bypass the interview loop entirely via a budget system that caps questions for trivial tasks.
*   **Lens-Driven System Analysis:** Clarifying questions are dynamically sourced from a structured lens table (Scope, Intent, Challenge, System Architecture) focusing on critical routing indicators: *anti-scope bounds* (what the agent must NOT do), *verifiable acceptance criteria*, and *exit conditions*.
*   **The Work Brief:** Resolved details are frozen into `.agentlas/work-brief.json`—recording the validated goal, concrete constraints, an assumption ledger with source tags, and the metadata ambiguity score.
*   **Contextual In-Flight Briefs:** The CLI tool `cards migrate` automatically maps brief details directly to triggers and anti-triggers on the agent's routing card. Running `route --brief` propagates this brief to all Stormbreaker execution packets, ensuring constraints and exit conditions govern parallel subprocesses across the entire lifecycle.
*   **Enhanced Routing Discrimination:** Prevents same-topic/different-intent collision (e.g., a security agent intercepting a deployment prompt) via double-sided gating: interview-validated anti-triggers on the routing card, and low-confidence LLM re-ranking escalation inside the router.

---

## All Install Methods

### Paste to Boot (Let Your AI Do It)
Paste this into Claude Code, Codex, Gemini CLI, Antigravity, or Cursor:

```text
Install Hephaestus Agentlas for this workspace from this GitHub repo:
https://github.com/agentlas-ai/Hephaestus

Use the latest release/instructions. If anything errors, diagnose and fix it,
retry, and confirm which command surface is active in this tool:
- Agentlas Terminal / Desktop route plain language natively.
- External LLM hosts expose the core work commands: build, network, cloud,
  search, call, upload. Claude Code and Codex also expose the Telegram setup
  helper: connect.
```

### Fresh macOS Check
```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
```

### One Terminal Command for All Runtimes
```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```
This installs the neutral runner at `~/.agentlas/runtime/current/bin/hephaestus` and registers the command adapters for Claude Code, Codex, Gemini CLI, Antigravity, and Cursor. The installer verifies each runtime surface after registration.

### Per-Runtime Plugin Drivers

<details>
<summary>Claude Code Plugin</summary>

From your OS terminal:
```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```
*Note: Claude Code also supports `claude plugins ...` as an alias, but this README uses the singular `claude plugin ...` for consistency.*

</details>

<details>
<summary>Codex Plugin</summary>

From your OS terminal:
```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v1.1.3
codex plugin add hephaestus@agentlas-core-engine
```
*Note: Codex does not accept `/plugin marketplace add` inside the app — run the two commands above in your OS terminal. The OS-terminal CLI command is singular (`codex plugin`); inside the Codex app, the plugin browser slash command is plural (`/plugins`). After install, `/prompts:hep-build` is the in-app entry.*

</details>

<details>
<summary>Copy Files into a Project (Manual Driver)</summary>

Clone the repo and copy `AGENTS.md`, `agent.md`, `agents/`, `skills/`, `modes/`, `schemas/`, `templates/`, and `.agentlas/` into your workspace. Runtime folders (`.claude/`, `codex/`, `.gemini/`, `.agents/`) function as adapters over the same canonical core.

</details>

**Just talk:** After installation, speak in plain language within native Agentlas interfaces to auto-route tasks. In external host tools, use the explicit commands listed below. When you don't know what agents exist, start with `/hep-search`. To connect Telegram, use `/hep-connect` in Claude Code or `/prompts:hep-connect` in Codex.

---

## The Command Surface

Inside native Agentlas environments, Hephaestus operates commandless. External LLM hosts utilize a deliberately small visible command set. System-level utilities like Stormbreaker, research loadouts, and configuration tables attach automatically from context:

| System Subsystem | Shell Command | Example |
| :--- | :--- | :--- |
| **Process Builder** | `/hep-build` | `/hep-build create a customer support agent for Shopify refunds` |
| **A2A Scheduler** | `/hep-network` | `/hep-network split this launch plan into research, copy, QA, and release agents` |
| **Cloud State Sync** | `/hep-cloud` | `/hep-cloud use my saved finance analyst agent to review this report` |
| **Directory Search** | `/hep-search` | `/hep-search find agents for a market report workflow` |
| **Inter-Process Call (IPC)** | `/hep-call` | `/hep-call market-researcher, report-writer {draft a market report}` |
| **Package Exporter** | `/hep-upload` | `/hep-upload ./agents/customer-support-hq` |
| **Telegram Setup** | `/hep-connect` or `/prompts:hep-connect` | `/hep-connect Telegram for Marketing Agent Team` |

---

## The Desktop Shell — Agentlas Desktop

[Agentlas Desktop](https://agentlas.cloud/desktop) is the graphical shell for this Agent OS — the same kernel, scheduler, and governance subsystems, operated visually. Desktop 0.6.0 ships with the Hephaestus v1.1.3 engine bundled and pinned; the app and its kernel version-lock together and auto-update as one unit.

| Shell Surface | What it operates |
| :--- | :--- |
| **Chat Workspaces** | Plain-language sessions bound to any runtime — Claude Code, Codex, Gemini CLI, Antigravity, BYOK APIs (DeepSeek, GLM, Kimi), or local Ollama — with live streaming, steering queues, and per-chat working folders. |
| **Build Menu** | The Meta-Agent Factory behind a UI: interview-gated builds (batched briefing questions rendered as native question cards), then real package files on disk. |
| **Agent Library & Hub** | Your compiled agents, teams, and borrowed Hub specialists — install, version, publish, and price them against the Agentlas Hub package registry. |
| **Task Forces & Swarm** | Borrowed multi-agent task forces, parallel swarm execution with a machine-spec concurrency slider, and continuous live runs for long-horizon work. |
| **Automations** | Cron/event/file-watch triggers compiled into parallel DAG workflows with a visual graph editor — scheduled agent processes, in OS terms. |
| **Memory & Evolution Panels** | The governed-memory subsystem made visible: curator tickets, promoted playbooks, self-evolution proposals, and security re-scans. |

The Desktop shell enforces the same boundaries as the CLI: BYOC execution on your machine and your subscriptions, receipts for routing decisions, and local-first memory. Download: [agentlas.cloud/desktop](https://agentlas.cloud/desktop).


---

## The OS Subsystems

### Meta-Agent Factory — Process Creation
A unified compilation factory using three builders. Every generated package registers its global command (`.agentlas/global-commands.json`) and ships verification scripts—the user never has to infer how to run the compiled package:

| Compilation Mode | Routing Target | Output Artifact |
| :--- | :--- | :--- |
| **Single-Agent** | `10-single-agent-builder` | Standalone worker with localized skills, memory contracts, and runtime adapters. |
| **Multi-Agent Team** | `20-multi-agent-team-builder` | Hierarchical team containing a PM Orchestrator, Memory Curator, Policy Gate, QA, and validation scripts. |
| **Workspace Packager** | `30-agentlas-packager` | Compiled bundle ready for desktop import, CLI execution, or GitHub distribution. |

*Briefing Interview Gate:* Builders initiate the process using the **briefing interview gate** ([docs/builder-interview-research-gate.md](docs/builder-interview-research-gate.md)): conducting lens-driven questions, evaluating the ambiguity threshold, searching primary sources, and outputting the work brief.

---

### Network 2.0 — The Scheduler

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>Figure 2. A2A scheduling: host runtimes, local-first orchestrator, routing cards, local memory, and the Agentlas Hub A2A/MCP fallback.</sub>

*   **Routing Cards:** Every agent, team, and plugin ships a standardized card containing triggers, anti-triggers, capabilities, risk profiles, and memory parameters. Cards failing verification are excluded from routing.
*   **Local-First Dispatch:** Dispatch is resolved locally first (project overrides $\rightarrow$ local cards). Outer lookups via the Agentlas Hub are redacted to keywords; your raw prompts never leave your local environment.
*   **Temporary Task Forces:** Composite requests decompose into Hub/local Task Force plans, packing Stormbreaker envelopes, session hints, and ontology pathways. Named specialists are scheduled dynamically, and a temporary orchestrator manages task handoffs.
*   **Receipt-Driven Execution:** Every routing decision writes a receipt. The router determines only which agent or package to invoke; tool execution permissions remain strictly sandboxed and managed by the host runtime.
*   **Bilingual Benchmarking:** Auto-routing is gated by a bilingual (Korean + English) benchmark requiring top-3 recall $\ge 90\%$ and zero privacy leaks. Low-confidence paths escalate to host-level Router Agent re-ranking.

Details: [docs/hephaestus-network-2.0.md](docs/hephaestus-network-2.0.md) · Runtime support matrix: [docs/runtime-fallback-adapters.md](docs/runtime-fallback-adapters.md)

---

### Stormbreaker — Disciplined Execution
Stormbreaker is the execution gating subsystem of the Agent OS. It ensures that agents do not report success or terminate until all outcomes have been verified by deterministic checks:

```text
Kernel Gating Envelope:
[Scope Lock] -> [Decomposition] -> [Parallel Work Packets] -> [Verify Contracts] -> [Bounded Repair] -> [Final Gate]
```

A local run journal makes long executions resumable after interruption. Execution packets carry the Work Brief so that anti-scope rules and exit criteria govern all parallel subprocesses. Stormbreaker reports explicit completion states (**verified / unverified / blocked**) to prevent autonomous completion theater.

Execution protocol: [docs/robustness-protocol.md](docs/robustness-protocol.md) · Benchmarks & Evals: [docs/robustness-eval.md](docs/robustness-eval.md)

---

### Ontology Runtime — The Knowledge Filesystem
For knowledge-intensive operations, `bin/ontology` acts as the semantic filesystem, converting unstructured local files into an agent-readable database stack:

```text
Ingested Files -> [Parser Adapter] -> [CJK trigram/bigram tokenization] 
  -> [FTS5 + SQLite Storage] -> [Reciprocal Rank Fusion Ranking] -> [GraphRAG Search]
```

Features first-party Korean document parsing (HWPX and legacy HWP5) with zero GPL dependencies. Fully local and SQLite-backed; confidential and private chunks are isolated, preventing them from reaching external cloud hooks.

```bash
bin/ontology ingest ./corpus --scope internal
bin/ontology query "Project Helios Memory Curator" --agent verifier
bin/ontology memory candidates
```

Details: [docs/ontology-runtime.md](docs/ontology-runtime.md)

---

### Governed Memory — Curated Promotion
*   **Local Project Memory:** Stored under `~/.agentlas/networking/` and isolated to the local machine. It cannot be exported without explicit authorization.
*   **Workspace Personalization:** Manages personalization logs (summaries, playbooks, plugin locks, and receipts) for borrowed Cloud/Hub agents without storing raw prompts, credential values, or private files.
*   **Curator Gating:** Skills and memory modifications are kept as candidates. They are promoted to durable status only after a local curator confirms holdout/replay proofs, rollback coverages, and security policy approvals.

---

### A2A Boundary — Inter-Agent Isolation
Standardized CLI commands allow safe inter-agent coordination:

```bash
agentlas-cloud ao a2a import ./agent-card.json .
agentlas-cloud ao a2a export . --agent local/10-builder
agentlas-cloud route "run the release check" --caller local/orchestrator .
```
Import acts as a proposal (restricting automatic invocation), export redacts private paths and logic, and invocations are caller-gated before routing is resolved.

---

## Built For The Enterprise

Enterprises do not need another way to write isolated Python agents. They need to **operate a governed workforce** of them. Hephaestus is designed specifically for this operational model:

*   **Model Neutrality as Procurement Leverage:** Agents, memory repositories, and knowledge domains are stored as local assets under your control. Transitioning to a new model provider (or utilizing local models like Ollama, Llama, and enterprise engines like DeepSeek, GLM, Gemini, or Claude) is a simple configuration update—not a codebase migration.
*   **Auditability by Construction:** Every routing decision, execution step, memory candidate, and curator decision is logged as a text file. You can diff, audit, and commit them. Work is either verified or flagged as unverified.
*   **Deterministic Pipeline Gates:** Security filters, anti-scopes, routing card triggers, and prompt sanitizations are hardcoded into the OS pipeline—they do not rely on LLM system instructions or guidelines.
*   **Specification Before Generation:** The Briefing Interview Engine measures request ambiguity and stamps the score on the Work Brief, ensuring task execution can always be audited back to what was agreed.
*   **Local-First Data Boundary:** Raw text, documents, and database files remain local. External transactions are redacted and opt-in.

### Where Frameworks Fit
CrewAI, LangChain, and vendor agent SDKs function as **libraries**—excellent for writing custom agent logic inside a single process. Hephaestus operates as the **host substrate**: it specifies, packages, routes, runs, audits, and migrates agents across workspace runtimes. Framework code runs inside Hephaestus packages; the kernel only requires that agents honor their directory contracts and Routing Cards.

---

## What It Builds (Process Packaging)

Hephaestus packages agents into a standard directory layout that any workspace runtime can parse, install, verify, and run:

```text
├── AGENTS.md                          # Canonical route configurations
├── agent.md / agents/                 # Single worker or team roles
├── skills/                            # Local agent skills and capabilities
├── modes/                             # Custom agent execution modes
├── schemas/                           # Validation contracts and schemas
├── templates/                         # Configuration templates
├── .agentlas/                         # System Directory: routing cards, work briefs,
│                                      # global commands, memory contracts, eval plans
├── .claude/ codex/ .gemini/ .agents/  # Runtime shims (driver adapters over the core)
├── scripts/
│   ├── verify-package.sh              # Package structure verifier
│   └── public_safety_check.sh         # Secret and credentials scanner
└── docs/                              # Briefing records, tool specifications,
                                       # and prompt contracts
```

---

## Docs By Goal

| System Goal | Reference Documentation |
|---|---|
| Understand the canonical route | [`AGENTS.md`](AGENTS.md) |
| See the full team contract | [`agent.md`](agent.md) |
| Architecture source of truth | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| Runtime boundaries | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| Briefing interview & research gate | [`docs/builder-interview-research-gate.md`](docs/builder-interview-research-gate.md) |
| Network 2.0 routing | [`docs/hephaestus-network-2.0.md`](docs/hephaestus-network-2.0.md) |
| Stormbreaker protocol | [`docs/robustness-protocol.md`](docs/robustness-protocol.md) |
| Ontology runtime | [`docs/ontology-runtime.md`](docs/ontology-runtime.md) |
| Memory architecture | [`docs/memory-architecture.md`](docs/memory-architecture.md) |
| Skill lifecycle promotion | [`docs/skill-lifecycle-promotion.md`](docs/skill-lifecycle-promotion.md) |
| Cloud runtime bundles | [`docs/agentlas-cloud-runtime.md`](docs/agentlas-cloud-runtime.md) |
| Verify a package | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| Public safety check | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

---

## Public Safety Boundary

This repository does **not** include hosted Agentlas billing/account logic, production cloud credentials, customer databases, raw private transcripts, desktop keychain managers, or private deployment scripts.

Public output packages compiled by Hephaestus must exclude local absolute paths, API keys, service-account keys, `.env` secrets, raw transcripts, customer logs, or private developer notes.

---

## Contributing and Verification

Before opening a pull request or publishing updates, run the verification test suite:

```bash
scripts/verify-package.sh
scripts/verify-ontology-runtime.sh
scripts/public_safety_check.sh
```

---

## License

Apache-2.0. See [LICENSE](LICENSE).
