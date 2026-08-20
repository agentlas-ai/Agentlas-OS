<p align="center">
  <a href="https://agentlas.cloud/studio">
    <img src="assets/readme/agentlas-one-launch-film-v2.gif" alt="Agentlas One launch film" width="960">
  </a>
</p>

<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Agentlas OS</h1>

<p align="center">
  <strong>Build it or borrow it. The agents you create stay yours.</strong><br>
  Turn a plain-language request into a runnable agent or team, borrow specialists from the public Agentlas Hub,
  and keep the agents you create available through your private, owner-scoped Agent Cloud.<br>
  Run them through supported hosts for the LLMs you already use. Hephaestus is the open-source engine underneath.
</p>

<p align="center">
  <strong>We are Agent Trust. Your agent is not a program. It is an asset. — Agentlas —</strong>
</p>

<p align="center">
  <sub>An agent you create is not tied to one model workspace or computer. To retrieve it from Cloud elsewhere, install Agentlas OS on a supported host and sign in.</sub>
</p>

<p align="center">
  <a href="https://github.com/agentlas-ai/Agentlas-OS/releases/latest">
    <img alt="Latest release" src="https://img.shields.io/github/v/release/agentlas-ai/Agentlas-OS?label=release">
  </a>
  <a href="LICENSE">
    <img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green">
  </a>
  <img alt="LLMs" src="https://img.shields.io/badge/LLMs-Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20%7C%20Antigravity%20%7C%20Cursor%20%7C%20DeepSeek%20%7C%20GLM%20%7C%20Ollama-black">
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

## Paste to Install

Paste this into the LLM you are using now, such as Claude Code, Codex,
Gemini CLI, Antigravity, or Cursor. It is written so you (the LLM reading it)
can verify what you're running before you run it, rather than being asked to
trust it blindly:

```text
I want to install Agentlas OS / Hephaestus from this open-source GitHub repo:
https://github.com/agentlas-ai/Agentlas-OS

Before running anything, fetch and read the installer script so you know what
it does:
https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh

It downloads a release tarball from this same repo's GitHub Releases and
writes files only under ~/.agentlas, ~/.local/bin, and this host's own plugin/
command-adapter directories (e.g. ~/.claude for Claude Code) — nothing outside
those paths. If that matches what you read, run it:
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | HEPHAESTUS_INSTALL_GLOBAL_ROUTER=1 bash

HEPHAESTUS_INSTALL_GLOBAL_ROUTER=1 additionally writes a routing block into
this host's global instructions file (e.g. ~/.claude/CLAUDE.md) that lets
substantial tasks be staffed from Agentlas' agent network; it is not secret
and you can read/quote it back to me. Drop that env var if you'd rather skip
it for now — you can add it later with `hephaestus global install`.

Afterwards, show me the installer's own verification output for this host,
and tell me plainly whether `/agentlas build` (or this host's equivalent
command surface) is ready to use, or whether I need to restart the host or
reload plugins first.
```

Use this when you are already inside an LLM and want the Agentlas command
surface active there. For direct shell commands, see the install methods below.

### No LLM handy? Type the command yourself

You don't need an AI to install this — a terminal and one pasted line is
enough. New to terminals? Follow your OS below.

**On Windows — open Git Bash:**

1. **Do you already have Git Bash?** Click the search icon (or press the
   **Windows key**) in your taskbar and type **`git bash`**.
   - If **"Git Bash"** shows up in the results, click it and skip to step 3.
   - If nothing shows up, you need to install Git for Windows first: go to
     **[git-scm.com/download/win](https://git-scm.com/download/win)**,
     download it, and run the installer (default options are fine — keep
     clicking **Next**, then **Install**).
2. After installing, search **`git bash`** again (same as step 1) and click
   the **"Git Bash"** result.
3. A black window opens — this is Git Bash. Click inside it, **paste** the
   command below (right-click → Paste, or `Shift+Insert`), then press
   **Enter**:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | HEPHAESTUS_INSTALL_GLOBAL_ROUTER=1 bash
   ```
4. Wait for it to finish (it prints its own progress). When it stops and
   gives you the prompt back, close and reopen your AI tool (Claude Code,
   Codex, etc.) so it picks up the new commands.

**On macOS — open Terminal:**

1. Press **`Cmd + Space`** to open Spotlight search, type **`terminal`**,
   and press **Enter**.
2. A window opens (Terminal, built into macOS — nothing to install). Click
   inside it, **paste** the command below (`Cmd + V`), then press **Enter**:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | HEPHAESTUS_INSTALL_GLOBAL_ROUTER=1 bash
   ```
   The first time you run `curl`/`git` on a fresh Mac, macOS may ask to
   install "Command Line Tools" — click **Install** and wait, then run the
   command again.
3. Wait for it to finish, then close and reopen your AI tool so it picks up
   the new commands.

If you'd rather read the script before running it (recommended if you're
security-conscious), open this link in your browser first:
[install-all-runtimes.sh](https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh).

<p align="center">
  <a href="https://agentlas.cloud/desktop">
    <img src="assets/readme/agentlas-desktop-hero.png" alt="Agentlas Desktop dashboard with local agents, owner-private Agent Cloud, Hub specialists, connected model hosts, and automations" width="960">
  </a>
</p>

<p align="center">
  <sub>Build, own, borrow, and run agents across your local workspace, private Agent Cloud, and the public Agentlas Hub.</sub>
</p>

## Agentlas Desktop in motion

<table>
<tr>
<td width="42%" valign="middle">

### Build an owned agent

Describe the work in plain language. Agentlas classifies the request, runs the interview and research gate, generates the package, verifies it, then asks whether to keep it only on this computer or save it privately in Agent Cloud for restore on another signed-in Desktop.

[Agentlas Desktop →](https://agentlas.cloud/desktop)

</td>
<td width="58%">
  <a href="https://agentlas.cloud/desktop"><picture><source srcset="assets/readme/feature-wall/workflow-build-pipeline.gif" type="image/gif"><img src="assets/readme/feature-wall/workflow-build-pipeline.jpg" alt="Building an owned agent package from a plain-language request in Agentlas Desktop" width="100%"></picture></a>
</td>
</tr>
<tr>
<td width="42%" valign="middle">

### Orchestrate a team

Combine local agents and borrowed Hub specialists into one orchestrator. Roles stay explicit while Agentlas manages routing, handoffs, and review boundaries.

[Explore Agentlas OS →](https://agentlas.cloud/models/hephaestus)

</td>
<td width="58%">
  <a href="https://agentlas.cloud/models/hephaestus"><picture><source srcset="assets/readme/feature-wall/workflow-make-group.gif" type="image/gif"><img src="assets/readme/feature-wall/workflow-make-group.jpg" alt="Composing local and Hub agents into one orchestrated team" width="100%"></picture></a>
</td>
</tr>
<tr>
<td width="42%" valign="middle">

### Run and verify locally

Use the model account or API key you choose. Your current host performs the work under its local files, tools, credentials, permissions, and verification rules.

[Read the trust model →](https://agentlas.cloud/docs/trust/agent-trust)

</td>
<td width="58%">
  <a href="https://agentlas.cloud/docs/trust/agent-trust"><picture><source srcset="assets/readme/feature-wall/workflow-run.gif" type="image/gif"><img src="assets/readme/feature-wall/workflow-run.jpg" alt="Running and verifying an Agentlas agent under the local host permission boundary" width="100%"></picture></a>
</td>
</tr>
</table>

<p align="center">
  <a href="#build-borrow-own">Build · Borrow · Own</a>
  ·
  <a href="#why-agentlas-os">Why Agentlas OS</a>
  ·
  <a href="#paste-to-install">Paste to Install</a>
  ·
  <a href="#agentlas-desktop-in-motion">Desktop Demo</a>
  ·
  <a href="#why-not-just-make-a-claude-agent">Why Not Just A Claude Agent?</a>
  ·
  <a href="#all-install-methods">All Install Methods</a>
  ·
  <a href="#the-command-surface">Command Surface</a>
  ·
  <a href="#new-in-v110--the-briefing-interview-engine">New in v1.1.0</a>
  ·
  <a href="#the-os-subsystems">Subsystems</a>
  ·
  <a href="#where-this-fits">Product Surfaces</a>
  ·
  <a href="#built-for-owned-agent-operations">Owned Agent Operations</a>
  ·
  <a href="#what-it-builds">System Packaging</a>
  ·
  <a href="#docs-by-goal">Docs Registry</a>
</p>

---

## Build, Borrow, Own

An agent you create should remain an asset you can move, rather than a
setting trapped in one chat, one model-vendor workspace, or one computer.
Agentlas separates three jobs that ordinary agent builders blur together:

This is the public [Agent Trust contract](docs/agent-trust-contract.md): a
portable, owner-scoped, inspectable, and restorable package contract—not a
claim of regulated financial or legal trust services.

| Value | What Agentlas does | Entry point in an external LLM host |
| --- | --- | --- |
| **Build** | Compiles a plain-language request into a runnable single-agent or team package with roles, tools, memory boundaries, permissions, routing, and verification contracts. | `/agentlas build` |
| **Borrow** | Finds public Hub specialists and brings the selected runtime bundle into your current Agentlas host. The publisher's private source work is not copied into your workspace. | `/agentlas hub` (Hub only) or `/agentlas network` (Local + Cloud + Hub) |
| **Own** | Keeps agents you create in a private, owner-scoped Agent Cloud so you can retrieve and call them again after changing models or computers. | Choose **private Agent Cloud** at `/agentlas upload`, then retrieve with `/agentlas cloud` |

### Portable package, local execution

```text
Describe the work
  -> build a portable agent or team
  -> save it to my owner-scoped Agent Cloud
  -> install Agentlas OS and sign in on another supported host
  -> retrieve it with /agentlas cloud
  -> my chosen model and current host execute the work
```

Agent Cloud stores and retrieves the owner's package; it is not a hosted LLM
that completes the work on the server. When you call a package, your selected
model and current host runtime execute it under that host's permission and
safety model. Credentials, local files, and machine-specific permissions do not
travel with the package—you configure those separately on each computer.

### The package contract — what every build must emit

An agent package is not a worker with capabilities. It is a **method document**.
Three layers, and conflating them is the single most expensive mistake this
project has made:

| layer | what it is | who supplies it |
|---|---|---|
| **LLM** | the worker: reasoning, language, general knowledge | you (BYOM) |
| **Runtime** | the facilities: read the web, write files, run a shell, drive a browser | the host machine |
| **Agent** | the work manual: procedure, judgement rules, source priority, input/output contracts, stop conditions | the package |

"Can this agent read the web?" is a category error. The runtime reads the web.
The only question a package can answer is *what method does it carry, and what
must the machine be able to do for that method to run.*

`package-contract.json` is the machine-readable list of artifacts every build
emits, and `scripts/verify-generated-package.sh <folder>` is what enforces it.
A build that omits a required artifact **fails**; it does not ship. Four of
those artifacts carry the routing contract:

```text
contracts/intake.schema.json     what a requester must hand over before work starts
contracts/output.schema.json     what the requester ends up holding
contracts/output.example.json    one real instance, validated by a JSON Schema
                                 validator at publish time — never by a model
.agentlas/brief.json             the compiled resume, schemaVersion agentlas.brief/1
```

Direction lives in the filename because nothing else ever marked it, and a
schema whose direction must be guessed cannot be matched against a request.

**Two rules bind every enum a build writes.** Both were paid for in production:

1. **Any enum reachable from matching must carry an escape member** (`"other"`,
   `"unknown"`). Matching one stated requirement against a 23-word closed list
   took a three-candidate inventory to zero on eight probes out of eight. A
   publisher whose real case is not on the list must still be findable.
2. **Sentences stay sentences.** No field that holds an author's sentence may be
   split into terms for matching. Shredding refusal sentences into the bare
   words `tests` and `ci` cut a correct agent's score to a quarter and pushed it
   from rank 2 to rank 24 — on a query that was literally its own job.

Vendor and MCP names live in exactly one place, `host[].preferred`, and that
field is display-only. Roughly 99.9% of machines have no MCP servers installed,
so a package wired to its author's own Slack, Notion or Jira has to stay usable
by everyone else: the matcher reads `host[].capability` ("open the page in a
real browser and read what a user would see") and every requirement states
`withoutIt`, what the method still does on a machine that lacks the facility.

`agentlas.brief/1` is written from either side — `side: "offer"` is the
package's resume, `side: "need"` is the requester's work order. The same form,
so the two can be compared without a translation step. Its schema is
`schemas/agentlas-brief.schema.json`, and it is **compiled, never hand-written**:
the upload path writes it from the files the package already ships.

| field | what it holds | where it comes from |
|---|---|---|
| `statement` | the author's own sentence about the work | the routing card, carried whole |
| `deliverables[].label` / `.contains` | what the requester ends up holding, and what is inside it | `contracts/output.schema.json` — the title and its property names |
| `deliverables[].shape` | `ledger` / `verdict` / `dossier` / `computation` / `blueprint` / `rendition` / `other` | computed from the output schema's **topology** — arity and value spaces, never a title or a filename |
| `deliverables[].rowVerdict` / `.verdictValues` | the per-record judgement and its allowed values | copied verbatim from the publisher's own enum; there is nothing to match them against, so no value is ever rejected |
| `obligations[].about` / `.stage` | a fact the requester must supply, and *when* it comes to exist | `contracts/intake.schema.json` and the card's stated inputs |
| `authority.performs` / `.gated` | what this method does to the requester's world, and what it stops to ask about first | derived from the approval requirements, not from what the package calls itself |
| `host[].capability` / `.withoutIt` | what the machine must be able to do, and what still happens when it cannot | `.agentlas/mcp-policy.json` |
| `provenance` | per field: `extracted`, `read`, `graded` or `absent` | written by the compiler |

`provenance` is the part that keeps the rest honest. `absent` is a legal value
that scores zero, so a gap stays a gap. Filling gaps with something plausible is
how `capabilities` came to equal `snake_case(agent.md ## Responsibilities)` in
130 of 130 packages — a field that was always full and never once informative.

The reference shape is `Web_master`: it ships input and output contracts as real
JSON Schema, a domain catalogue its rules are checked against, and verification
scripts that run. Everything above is what a build has to emit to be readable the
way that package already is.

Deliberately absent: there is no field for what an agent is *good at*, and none
for its permissions. Quality cannot be read off a package that has never run, and
permissions are granted by the host after the fact — an employer hands you a
computer once you are hired, so neither says anything about whether this method
fits the work.

### Hub and Agent Cloud are different scopes

| Surface | What it contains | What it is for |
| --- | --- | --- |
| **Agentlas Hub** | Public packages from creators and teams | Find and borrow only public specialists with `/agentlas hub`; `/agentlas network` federates Hub with Local and owner Cloud. Publish only through an explicit public-Hub choice. |
| **My Agent Cloud** | Only the signed-in owner's Cloud packages | Privately store, restore, and call packages you own with the `/agentlas upload` Cloud choice and `/agentlas cloud`. |
| **Current host** | The installed runtime, chosen model, local project, credentials, and granted permissions | Execute the selected local, Cloud, or Hub package. |

---

## The Standard, Not Another Engine

> **Agentlas is not building another graph engine.**
> It is designing the agent standard — and the distribution network that carries it —
> that many graph engines and runtimes can share.

Engines keep changing. A model workspace, a CLI, an orchestration framework, a graph
runner: each arrives, wins for a while, and is replaced. What has to survive that churn
is the contract an agent carries with it — what it is, how it is invoked, what it may
touch, what it remembers, and how its result is proven.

That contract is the product, and it is deliberately engine-neutral:

- **One definition, many runtimes.** The same package runs through Claude Code, Codex,
  Gemini, Antigravity, Cursor, or a local model, because the manifest, routing card,
  permissions, and memory rules travel with the agent instead of with the vendor.
- **A life outside the chat.** Package contracts, receipts, and verification gates
  outlive the session that produced them.
- **A way to reach other people.** Publish to the public Hub, or keep it in your
  owner-scoped Cloud. Either way it moves as a package, not as a copied prompt.

Hephaestus is one engine that implements this standard. It is open source precisely so
the standard can be inspected, forked, and re-implemented — including by engines we did
not write.

## Why Agentlas OS

Most AI products help you create another agent. Agentlas OS is for the harder
part: making agents operate as a team you own.

You should be able to imagine this after installing it:

- Your LLMs work like a team instead of isolated chat sessions.
- Your real browser becomes an execution surface, not a screenshot in a prompt.
- Your agents keep package contracts, routing cards, memory rules, permissions,
  and verification receipts after the chat ends.
- Packages you own can remain local or be privately stored in your owner-scoped
  Agent Cloud, then retrieved from another supported, installed, signed-in host.
- Your existing Claude Code, Codex, Gemini, Cursor, Antigravity, API keys, and
  local models become part of one operating layer.
- Hub specialists can be borrowed into your local runtime without copying the
  creator's private work or sending your private files to their agent.

Hephaestus is the open-source engine underneath Agentlas OS. It is not a prompt
marketplace, an agent template generator, or another model subscription. It is a
local-first runtime that builds, routes, borrows, runs, verifies, and packages
agents across LLM command surfaces.

The point is not "make an agent from a prompt." The point is:

> Create, package, route, run, and verify agents across your LLMs, browser,
> memory, and local tools.

## Why Not Just Make A Claude Agent?

Claude subagents and custom agents are useful. They give a task its own prompt,
tools, and context window. Agentlas starts after that point.

An LLM can draft an agent. Agentlas turns it into an operating unit:

| Layer | A prompt-made agent | An Agentlas package |
| --- | --- | --- |
| Definition | Role prompt, markdown, tool list | Manifest, agent card, mode map, package contract |
| Invocation | Manual mention or simple trigger | Routing card, triggers, anti-triggers, benchmarks, receipts |
| Browser | Ad hoc browsing or screenshots | Real browser hardpoint with visible clicks, forms, waits, and snapshots |
| Memory | Copied context or chat history | Memory map, memory tickets, Memory Curator, Policy Gate |
| Runtime | One LLM session or one vendor runtime | Adapters across Claude Code, Codex, Gemini, Cursor, Antigravity, and local runtime |
| Teams | Another prompt layer | Orchestrator, PM Soul, Memory Curator, Policy Gate, eval judge, QA gate |
| Verification | User checks manually | Package checks, receipts, Stormbreaker final gate |
| Ownership and portability | Trapped in the chat or vendor workspace where it was created | Portable package that can remain local or be retrieved from the owner's Agent Cloud on another supported, installed, signed-in host |
| Distribution | Copy the prompt | Explicit choice between public Hub publishing and private owner-scoped Cloud storage |

That is the product boundary: Agentlas does not compete on "better prompt." It
gives agents the architecture to keep working outside one chat.

## The Agent OS Stack

Agentlas maps agent work to operating-system-like responsibilities without
forcing your work into one model provider:

| OS Abstraction | Implementation in Hephaestus |
| :--- | :--- |
| **Kernel / Policy Gate** | Deterministic router + security gates. Every routing action yields an auditable receipt; tool execution permissions are enforced by the active host and runtime. |
| **Processes / Threads** | Independent agents and multi-agent teams compiled as packages with explicit, typed contracts (Routing Cards, anti-scopes, memory boundaries, and verification shims). |
| **Process Scheduler** | Network 2.0 routing (local-first, quality-gated, and benchmark-gated dispatch) combined with Stormbreaker's parallel execution fabric and append-only run journals. |
| **Memory Management (MMU)** | Two-boundary governed memory: local project memory remains isolated on the machine, while durable promotions are gated by a local Memory Curator. |
| **Virtual File System** | Production Ontology Runtime: local-first source ingestion, CJK trigram FTS5 search, hybrid Reciprocal Rank Fusion, and GraphRAG retrieval. |
| **Inter-Process Call (IPC)** | A2A Agent Card Boundary (cryptographic import/export and caller-gating) + Model Context Protocol (MCP) tool registrations. |
| **Package Manager** | Agentlas Hub for public publishing and borrowing; owner-scoped Agent Cloud for private package storage and retrieval. Neither is a server-side model executor. |
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

### Manual LLM Adapter Install

Use this only when your current LLM cannot run setup for you. It installs the
shared Hephaestus runner and command adapters for supported LLM tools.

```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```
This installs the neutral runner at `~/.agentlas/runtime/current/bin/hephaestus` and registers the command adapters for Claude Code, Codex, Gemini CLI, Antigravity, Cursor, OpenCode, OpenClaw, Hermes, and compatible local/API hosts. The installer verifies each runtime surface after registration.

Desktop startup and every `/hep-*` command start the same digest-verified,
rate-limited update check in the background. The current command never waits
for network or installation work. A successful update atomically moves
`~/.agentlas/runtime/current` and reconciles every already-installed host
adapter; the next command or reloaded session uses the new release. Releases
v1.1.63 through v1.1.68 briefly installed a separate six-hour OS scheduler.
Current installs remove that retired scheduler automatically.

### Optional Global Router
```bash
hephaestus global install
```
This appends a managed marker block to `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, and `~/.gemini/GEMINI.md`. It is an optional host adapter, not the owner of an Agentlas One session or a Desktop Work project. For substantial work, Network is one explicit federated source scope (`local + cloud + hub`): the host model selects exact releases from the returned menu and validates them. It never routes by keyword, silently substitutes a different agent, or treats Cloud, Hub, Local, and skills as semantic fallback tiers. The command is idempotent and keeps a timestamped backup before editing.

The installed router prompt asks the host to report results by the workers that
did the task rather than narrating the routing step — it is a conciseness
convention, not a secrecy one, and it says so. It carries an explicit
status-line contract for English and Korean sessions:

| Session language | Agent route example | Host-skill adapter example |
| --- | --- | --- |
| English | `Agents used: <agent names>. Reason: <short reason>.` | `Skills used: <skill names>. Reason: <short reason>.` |
| Korean | `사용 에이전트: <agent names>. 이유: <short reason>.` | `사용 스킬: <skill names>. 이유: <short reason>.` |

Global router command reference:

| Command | What it does |
| --- | --- |
| `hephaestus global install` | Install or refresh the managed router block for Codex, Claude Code, and Antigravity/Gemini. |
| `hephaestus global status` | Show whether each runtime file has the managed router block. |
| `hephaestus global remove` | Remove only the managed Hephaestus router block. Existing user content stays in place. |
| `hephaestus global install --target codex` | Install only `~/.codex/AGENTS.md`. |
| `hephaestus global install --target claude` | Install only `~/.claude/CLAUDE.md`. |
| `hephaestus global install --target antigravity` | Install only `~/.gemini/GEMINI.md`, which Antigravity shares with Gemini CLI. |
| `hephaestus global install --target codex --target claude --target antigravity` | Explicitly install all supported targets. |
| `hephaestus global install --dry-run` | Preview what would change without writing files. |
| `hephaestus global install --no-backup` | Edit without writing a timestamped `.bak.*` file. |
| `hephaestus global install --home /tmp/test-home` | Test against another home directory. Useful for installer QA. |
| `hep-global install` | The original spelling of the same command. Still supported. |
| `~/.agentlas/runtime/current/bin/hephaestus global status` | Use the installed runtime directly when shell shims are not on `PATH`. |

The independent Agentlas Terminal owns the `agentlas` shell command. The Core
installer intentionally leaves that command untouched and removes only the
exact legacy Core alias it created in older releases.

### Per-Runtime Plugin Drivers

<details>
<summary>Claude Code Plugin</summary>

From your OS terminal:
```bash
claude plugin marketplace add https://github.com/agentlas-ai/Agentlas-OS --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```
*Note: Claude Code always namespaces marketplace-plugin commands, so this
plugin-only path exposes `/hephaestus:agentlas`. To get the documented bare
`/agentlas` autocomplete in every new session, use the one-touch installer
above; it also writes `~/.claude/commands/agentlas.md` and `hep-*.md`. Claude Code supports
`claude plugins ...` as an alias, but this README uses the singular
`claude plugin ...` for consistency.*

</details>

<details>
<summary>Codex Plugin</summary>

From your OS terminal:
```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.2.16
codex plugin add hephaestus@agentlas-core-engine
```
*Note: Codex does not accept `/plugin marketplace add` inside the app — run the two commands above in your OS terminal. The OS-terminal CLI command is singular (`codex plugin`); inside the Codex app, the plugin browser slash command is plural (`/plugins`). Codex 0.117+ removed custom `/prompts:*` commands; after install, invoke the supported plugin skill as `$hephaestus-network <request>`.*

</details>

<details>
<summary>Copy Files into a Project (Manual Driver)</summary>

Clone the repo and copy `AGENTS.md`, `agent.md`, `agents/`, `skills/`, `modes/`, `schemas/`, `templates/`, and `.agentlas/` into your workspace. Runtime folders (`.claude/`, `codex/`, `.gemini/`, `.agents/`) function as adapters over the same canonical core.

</details>

**Just talk:** After installation, speak in plain language within native Agentlas interfaces to auto-route tasks. In external LLM tools, use the explicit commands listed below. When you don't know what agents exist, start with `/agentlas search`. To connect Telegram, use `/agentlas connect`.

**One word to remember:** everything starts with `agentlas` — `/agentlas` in an
LLM host, `agentlas` in a shell.

---

## Where This Fits

This repository installs the Hephaestus engine and LLM command adapters. It is
the open-source command surface under Agentlas OS.

| Surface | Role |
| --- | --- |
| **Agentlas Desktop** | Visual local OS for running AI-native apps, agent teams, memory, browser work, and Hub specialists. |
| **Hephaestus plugin** | Open-source engine and command surface for Claude Code, Codex, Gemini CLI, Antigravity, Cursor, and compatible runtimes. |
| **Agentlas Hub** | Public package surface for publishing and borrowing specialists. |
| **Agentlas Cloud** | Owner-scoped package store for privately saving and retrieving the signed-in user's own agents. |

The install prompt above is intentionally scoped to this repo and the current
LLM surface. Desktop, Hub, and Cloud are product surfaces around the same
Agentlas OS architecture; they are not prerequisites for installing the plugin.
Cloud retrieval on a new computer does require a supported Agentlas OS host to
be installed and the package owner to be signed in.

---

## The Command Surface

Inside native Agentlas environments, Hephaestus operates commandless. External LLM tools use a deliberately small visible command set. System-level utilities like Stormbreaker, research loadouts, and configuration tables attach automatically from context:

| System Subsystem | Command | Example |
| :--- | :--- | :--- |
| **Agent / Team Builder** | `/agentlas-build` (or `/agentlas build`, `/hep-build`) | `/agentlas-build create a customer support agent for Shopify refunds` |
| **Workforce Federation (Local + Cloud + Hub)** | `/agentlas-network` (or `/agentlas network`, `/hep-network`) | `/agentlas-network split this launch plan into research, copy, QA, and release agents` |
| **Stormbreaker Loop** | `/agentlas-storm` (or `/agentlas storm`, `/hep-storm`) | `/agentlas-storm build full-stack saas landing page` |
| **Graph Automations** | `/agentlas-graph` (or `/agentlas graph`, `/hep-graph`) | `/agentlas-graph create daily market summary automation` |
| **Personal Agent Mode** | `/agentlas-one on|off` (or `/agentlas one on|off`, `/hep-one on|off`) | `/agentlas-one on` |
| **Registered Local Agents Only** | `/agentlas-local` (or `/agentlas local`, `/hep-local`) | `/agentlas-local use only agents registered on this machine` |
| **Owned Cloud Agents Only** | `/agentlas-cloud` (or `/agentlas cloud`, `/hep-cloud`) | `/agentlas-cloud use my saved finance analyst agent to review this report` |
| **Public Hub Agents Only** | `/agentlas-hub` (or `/agentlas hub`, `/hep-hub`) | `/agentlas-hub find public specialists for accessibility QA` |
| **Directory Search** | `/agentlas-search` (or `/agentlas search`, `/hep-search`) | `/agentlas-search find agents for a market report workflow` |
| **Browser Hardpoint** | `/agentlas-browser` (or `/agentlas browser`, `/hep-browser`) | `/agentlas-browser https://example.com` |
| **Inter-Process Call (IPC)** | `/agentlas-call` (or `/agentlas call`, `/hep-call`) | `/agentlas-call market-researcher, report-writer {draft a market report}` |
| **Cloud / Hub Destination Gate** | `/agentlas-upload` (or `/agentlas upload`, `/hep-upload`) | `/agentlas-upload ./agents/customer-support-hq` |
| **Messenger / Channel Setup** | `/agentlas-connect` (or `/agentlas connect`, `/hep-connect`) | `/agentlas-connect Telegram for Marketing Agent Team` |
| **Orchestrator / Worker Models** | `/agentlas-orch` (or `/agentlas orch`, `/hep-orch`) | `/agentlas-orch orchestrator=frontier worker=economy` |
| **Runtime + Adapter Update** | `/agentlas-update` (or `/agentlas update`, `/hep-update`) | `/agentlas-update` |

`/hep-orch` sets which model runs the orchestrator and which runs the workers,
so a fan-out of mechanical work does not bill frontier runs. **The split only
puts two models to work on Claude Code**, which is the one host that spawns a
real subagent and takes a model per subagent. Codex, Gemini/Antigravity, Cursor,
and OpenCode have no subagent of their own: one model plays every role in
sequence there, the allocation receipt is still written, and the ceiling still
bounds what that model may request — but no second, cheaper model appears.

Every row also answers to its original `/hep-*` name — `/agentlas network` and
`/hep-network` are the same command. Nothing was renamed away, so existing
scripts, notes, and muscle memory keep working. Current Codex uses explicit
plugin skills `$hephaestus-build`, `$hephaestus-network`,
`$hephaestus-cloud`, `$hephaestus-upload`, `$hephaestus-storm`, and
`$hephaestus-graph`; other MCP surfaces can be requested in plain language.
Custom `/prompts:*` commands were removed from Codex 0.117+.

---

## The OS Subsystems

### Meta-Agent Factory — Process Creation
A unified compilation factory using three builders. Every generated package registers its global command (`.agentlas/global-commands.json`) and ships verification scripts—the user never has to infer how to run the compiled package:

| Compilation Mode | Routing Target | Output Artifact |
| :--- | :--- | :--- |
| **Single-Agent** | `10-single-agent-builder` | Standalone worker with localized skills, memory contracts, and runtime adapters. |
| **Multi-Agent Team** | `20-multi-agent-team-builder` | Hierarchical team containing a PM Orchestrator, Memory Curator, Policy Gate, QA, and validation scripts. |
| **Workspace Packager** | `30-agentlas-packager` | Compiled bundle ready for runtime import, CLI execution, or GitHub distribution. |

*Briefing Interview Gate:* Builders initiate the process using the **briefing interview gate** ([docs/builder-interview-research-gate.md](docs/builder-interview-research-gate.md)): conducting lens-driven questions, evaluating the ambiguity threshold, searching primary sources, and outputting the work brief.

---

### Network 2.0 — The Scheduler

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>Figure 2. A2A scheduling: explicit host commands, model-selected exact releases, local memory, and federated Agentlas Network discovery.</sub>

*   **Typed Job Analysis:** The active host LLM turns the request into a redacted `WorkOrder` with explicit roles, skills, tools, artifacts, authority, cardinality, and handoffs. Core does not infer staffing intent from a substring list.
*   **Exact Source Federation:** `local`, `cloud`, and `hub` are exact scopes; `network` is their sealed union. Each source returns a bounded, content-only menu, and Core records unavailable sources instead of silently widening scope.
*   **Host-Owned Task Forces:** The host LLM reads the qualification evidence and authors the exact `Selection`. Core never chooses a deterministic winner or performs a hidden Router Agent re-rank; it validates governance, privacy, identity, cardinality, and graph integrity.
*   **Pinned Execution:** After validation, Core fetches only the selected immutable releases from their original source sessions and verifies release, package, and content digests before distinct planner, worker, synthesis, and verifier invocations run.
*   **Evidence-Scored Evaluation:** Retrieval coverage, host selection, immutable preparation, real child invocations, and final verification are scored as separate claims. A benchmark result never replaces the host staffing decision or turns usage history into routing authority.

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

The v1.2.4 release contract ships and verifies the dependency-free
`potion-multilingual-128M-int8` Model2Vec asset as the primary semantic
adapter. Its pure-Python Unigram runtime returns a normalized 256-dimensional
semantic vector. Runtime queries never download a model or call a hosted
embedding API. Hash-96 mode is an explicitly reported degraded fallback when
the verified local asset is missing or rejected, not an alternative silent
default.

The v1.2.4 self-updater installs the complete one-touch runtime payload,
including Career Graph, templates, and the verified model under the versioned
`models/model2vec/potion-multilingual-128M-int8` directory. It checks that payload before
and after switching `~/.agentlas/runtime/current`, then repairs merge-safe
memory hooks for detected hosts without replacing unrelated user configuration.

Agent experience recall is a governed path, not an unrestricted nearest-vector
search:

```text
exact agent + allowed scope + active status + unexpired + not superseded
  -> lexical rank + local cosine rank
  -> reciprocal-rank fusion + bounded salience prior
  -> all relevant memories when they fit, otherwise budgeted top-k
```

Experience recall scores a deterministic newest-first window of at most 5,000
governance-eligible rows before token-budget selection. When more rows are
eligible, the response is explicitly `partial` with a truncated scan receipt;
older evidence outside the bounded window may require a narrower query or
projection rebuild. Each Hub agent has a rebuildable private projection at
`~/.agentlas/networking/hub-agents/<normalized-slug>/memory/experience.sqlite`.
The runtime may infer only same-agent, same-scope `similar_to` edges from local
cosine similarity; `supersedes` and `contradicts` require an explicit curator
decision.

```bash
bin/ontology ingest ./corpus --scope internal
bin/ontology --db .agentlas/ontology-runtime.sqlite query "Project Helios Memory Curator" --agent verifier
bin/ontology --db ~/.agentlas/networking/hub-agents/<slug>/memory/experience.sqlite experience query "What did we learn?" --agent hub:<slug>
bin/ontology memory candidates
```

Plain Claude Code and Codex sessions receive bounded recall through
`SessionStart` and `UserPromptSubmit` additional context. Antigravity uses a
`PreInvocation` ephemeral message, OpenCode uses an experimental local plugin,
and Grok refreshes a workspace-scoped cache because its passive hooks do not
inject stdout. These hooks supplement live `AGENTS.md`/`CLAUDE.md` policy rather
than copying it. Details: [docs/ontology-runtime.md](docs/ontology-runtime.md) ·
[docs/runtime-memory-hooks.md](docs/runtime-memory-hooks.md)

---

### Governed Memory — Curated Promotion

*   **Local Project Memory:** Project documents remain in the local `.agentlas/ontology-runtime.sqlite`; borrowed-agent experience remains in its exact per-agent projection. The two stores share one query engine without collapsing their scope or ownership boundaries.
*   **Governance Before Ranking:** Exact agent, allowed privacy scope, active status, expiry, and structural supersession are enforced before lexical/cosine ranking. Secret redaction and capsule bounds are applied again before host delivery.
*   **Workspace Personalization:** Manages summaries, playbooks, plugin locks, and receipts for borrowed Cloud/Hub agents without storing raw prompts, credential values, or private files.
*   **Curator Gating:** Skills and durable memory modifications remain candidates until a local curator confirms evidence, rollback coverage, and security policy approval. Automatic experience relations are limited to `similar_to`.

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

## Built For Owned Agent Operations

Users and teams do not need another way to write isolated agents. They need to
operate an owned workforce of them. Hephaestus is designed for that operational
model:

*   **Package Portability:** Packages you own can remain local or be stored in your private, owner-scoped Agent Cloud. On another supported computer, install Agentlas OS, sign in, and retrieve the package; host credentials, local files, and permissions stay machine-specific.
*   **Model Neutrality:** Agent packages use adapters for supported hosts instead of belonging to one model vendor's workspace. You can run the same package with supported Claude, Codex, Gemini, Antigravity, Cursor, or local-model surfaces without rebuilding its operating architecture.
*   **Auditability by Construction:** Every routing decision, execution step, memory candidate, and curator decision is logged as a text file. You can diff, audit, and commit them. Work is either verified or flagged as unverified.
*   **Deterministic Pipeline Gates:** Security filters, anti-scopes, routing card triggers, and prompt sanitizations are hardcoded into the OS pipeline—they do not rely on LLM system instructions or guidelines.
*   **Specification Before Generation:** The Briefing Interview Engine measures request ambiguity and stamps the score on the Work Brief, ensuring task execution can always be audited back to what was agreed.
*   **Local-First Data Boundary:** Raw text, documents, and database files remain local. External transactions are redacted and opt-in.

### Where Frameworks Fit
CrewAI, LangChain, and vendor agent SDKs function as **libraries**—excellent for writing custom agent logic inside a single process. Hephaestus operates as the **runtime substrate**: it specifies, packages, routes, runs, audits, and migrates agents across workspace runtimes. Framework code runs inside Hephaestus packages; the kernel only requires that agents honor their directory contracts and Routing Cards.

---

## What It Builds (Process Packaging)

Hephaestus packages agents into a standard directory layout that any workspace runtime can parse, install, verify, and run. The important part is not just `agent.md`; it is the operating contract around it:

```text
├── AGENTS.md                              # Canonical operating loop and source-of-truth map
├── agent.md / agents/                     # Single worker, HQ/orchestrator, or team roles
│   ├── 10-single-agent-builder/
│   ├── 20-multi-agent-team-builder/
│   └── 30-agentlas-packager/
├── .agentlas/                             # Agentlas OS system directory
│   ├── sitemap.json                       # Product graph: modes, runtime adapters, memory, release checks
│   ├── mode-map.json                      # Single-agent / team / packager classification contract
│   ├── routing-card.json                  # Triggers, anti-triggers, capabilities, risk, routing readiness
│   ├── agent-card.json                    # A2A-facing identity and capability card
│   ├── company-blueprint.json             # Team/company topology for multi-agent packages
│   ├── global-commands.json               # Runtime command aliases and install surfaces
│   ├── memory-map.json                    # Memory roots, write owners, trust labels, exclusions
│   ├── memory-tickets.jsonl               # Candidate memory events before durable promotion
│   ├── project-soul-memory.md             # Project-level operating memory
│   ├── curator-decisions.jsonl            # Memory Curator promotion/rejection decisions
│   ├── vault-references.json              # Secret/credential references without raw values
│   ├── validation-ledger.jsonl            # Verification and release evidence
│   ├── field-test-report.json             # Field test results for package readiness
│   ├── skill-registry.json                # Reusable skill inventory and lifecycle metadata
│   ├── skill-trials.jsonl                 # Skill trial evidence before promotion
│   └── agent-ontology/                    # Local code/agent map for capabilities, artifacts, scopes, edges
├── skills/                                # Canonical reusable skills
├── modes/                                 # Mode contracts for build/package behavior
├── schemas/                               # JSON schemas for cards, memory maps, sitemap, evals, manifests
├── templates/                             # Package, memory, interview, eval, ontology, and contract templates
├── ontology/ + bin/ontology               # Local-first parser/search/GraphRAG runtime
├── agentlas_cloud/                        # Hub/Cloud bundle, routing, update, and runtime APIs
├── .claude/ codex/ .gemini/ .agents/      # Thin runtime adapters over the same core
├── claude/ codex/ gemini/ antigravity/    # Plugin/extension/workflow distributions
├── cursor/ hermes/ openclaw/              # Additional runtime shims and skill mirrors
├── docs/                                  # Architecture, chain map, memory, ontology, routing, eval docs
│   ├── source-of-truth.md
│   ├── chain-map.md
│   ├── memory-architecture.md
│   ├── ontology-runtime.md
│   ├── hephaestus-network-2.0.md
│   └── builder-interview-research-gate.md
└── scripts/                               # Verification, installer, sync, release, and public-safety gates
    ├── verify-package.sh
    ├── verify-ontology-runtime.sh
    ├── verify-routing-cards.sh
    ├── sync-adapters.sh
    └── public_safety_check.sh
```

That package shape is why an Agentlas agent is more than an LLM-written role
prompt. It carries routing, memory, sitemap, code/agent ontology, permissions,
runtime adapters, verification ledgers, and release gates together.

### Dependency-aware project context

Hephaestus keeps the project map local. The explicit `context refresh` writer
creates a content-addressed snapshot; passive reads then hand each concrete
task only the goals, constraints, definitions, backlinks, interfaces, and
related files it structurally depends on.

Passive MCP context reads remain write-free, but they recompute the same
bounded file-list fingerprint before returning indexed data. If code,
verification, CI, or version-contract inputs changed—or the freshness scan
cannot complete—the read returns `context_map_stale` or
`context_freshness_incomplete` with a `refresh=true` retry instead of returning
old symbols as `status=ok`.

The v3 manifest retains the Code Map v2 compatibility projection and carries an
`agentlas.verification-map.v2` graph. Search-only lexical backlinks are kept
separate from completion-gating dependency edges. Blocking edges come from
resolved imports, explicit package commands, CI workflows, and version scopes;
generated releases, embedded runtimes, and declared mirrors are not rescanned
as canonical source. Every safe project file is inventoried by role, so docs,
config, and prior-snapshot deletion tombstones are valid change inputs.

`context impact` returns source review obligations separately from test/CI and
release obligations. `context verify` passively reuses the same fresh snapshot,
and `--verified` records an actually executed test path or exact command/CI ID.
Putting a test in `--reviewed` or `--waived` never masquerades as execution.
Local and CI are alternatives, not duplicate requirements. Version contracts
remain a separate release responsibility, and
a missing test reference blocks the CI channel that owns it until the workflow
is fixed or explicitly waived. Local test files and fixtures may remain
Git-ignored and excluded from public runtime archives; the project-local map
still fingerprints and links them so local execution is a real selectable
channel rather than invisible state.

```sh
hephaestus context refresh --project .
hephaestus context refs resolveHubEntityKind --project .
hephaestus context slice --project . --task "fix entity kind routing" \
  --target src/package-kind.ts --render
hephaestus context impact --project . --changed src/package-kind.ts
hephaestus context verify --project . --changed src/package-kind.ts \
  --reviewed src/register/route.ts \
  --verified tests/test-package-kind.ts
```

Claude and Codex receive the task slice from their local hook and get a
reverse-reference warning immediately before edit tools. Desktop, Terminal,
Stormbreaker, and Workforce call the same Core implementation. Network/Cloud
search and bundle fetches remain redacted and never receive local source paths
or Context Map contents.

---

## Docs By Goal

| System Goal | Reference Documentation |
|---|---|
| Understand the canonical route | [`AGENTS.md`](AGENTS.md) |
| See the full team contract | [`agent.md`](agent.md) |
| Architecture source of truth | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| Runtime boundaries | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| Context Map v3 | [`docs/context-map-v3.md`](docs/context-map-v3.md) |
| Sitemap contract | [`.agentlas/sitemap.json`](.agentlas/sitemap.json) and [`schemas/sitemap.schema.json`](schemas/sitemap.schema.json) |
| Mode map | [`.agentlas/mode-map.json`](.agentlas/mode-map.json) |
| Routing card | [`.agentlas/routing-card.json`](.agentlas/routing-card.json) and [`schemas/routing-card.schema.json`](schemas/routing-card.schema.json) |
| Memory map | [`.agentlas/memory-map.json`](.agentlas/memory-map.json) and [`schemas/memory-map.schema.json`](schemas/memory-map.schema.json) |
| Briefing interview & research gate | [`docs/builder-interview-research-gate.md`](docs/builder-interview-research-gate.md) |
| Network 2.0 routing | [`docs/hephaestus-network-2.0.md`](docs/hephaestus-network-2.0.md) |
| Stormbreaker protocol | [`docs/robustness-protocol.md`](docs/robustness-protocol.md) |
| Canonical Goal + UltraCode harness | [`docs/stormbreaker-goal-ultracode-harness.md`](docs/stormbreaker-goal-ultracode-harness.md) |
| Ontology runtime | [`docs/ontology-runtime.md`](docs/ontology-runtime.md) |
| Memory architecture | [`docs/memory-architecture.md`](docs/memory-architecture.md) |
| Runtime memory hooks | [`docs/runtime-memory-hooks.md`](docs/runtime-memory-hooks.md) |
| Experience and Taste assets | [`docs/agent-experience-assets.md`](docs/agent-experience-assets.md) |
| MCP build resolution | [`docs/mcp-build-resolution.md`](docs/mcp-build-resolution.md) |
| Plugin contributions | [`PLUGIN_CONTRIBUTIONS.md`](PLUGIN_CONTRIBUTIONS.md) |
| Model allocation | [`docs/model-allocation.md`](docs/model-allocation.md) |
| Skill lifecycle promotion | [`docs/skill-lifecycle-promotion.md`](docs/skill-lifecycle-promotion.md) |
| Cloud runtime bundles | [`docs/agentlas-cloud-runtime.md`](docs/agentlas-cloud-runtime.md) |
| Verify a package | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| Public safety check | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

---

## Public Safety Boundary

This repository does **not** include Agentlas billing/account logic, production cloud credentials, customer databases, raw private transcripts, native keychain managers, or private deployment scripts.

Public output packages compiled by Hephaestus must exclude local absolute paths, API keys, service-account keys, `.env` secrets, raw transcripts, customer logs, or private developer notes.

### Build telemetry

`hep-build` sends anonymous counters so we can see where builds fail: a random
install id generated locally, which build step ran, whether it succeeded, a
machine error code, a duration, and the OS/engine/python versions. Events are
deleted 180 days after they arrive.

Never sent: file paths, package names, prompts, agent content, error message
text, usernames, emails, or environment variables. The allowlist is enforced in
the engine before the request is built and again on the server, which drops
every field it does not recognize.

Turn it off with either of these — a build behaves identically with telemetry
disabled, and every failure path (offline, DNS, server error, a bug in the
telemetry code) is already swallowed silently without touching your build:

```bash
export AGENTLAS_TELEMETRY=0
export DO_NOT_TRACK=1     # the cross-vendor convention, honored here
```

Or permanently, in `~/.agentlas/networking/config.json`:

```json
{ "telemetry": false, "telemetrySetBy": "user" }
```

The `telemetrySetBy` marker is what separates a choice you made from the
`"telemetry": false` that `default_config()` wrote into every install created
before the key was ever read — that value never represented anyone's decision,
so it is not treated as one.

---

## Contributing and Verification

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. External
services and optional providers must be submitted as independently installable
Agentlas plugins; provider-specific Core wiring is not accepted. The detailed
boundary and review checklist are in the
[plugin contribution guide](PLUGIN_CONTRIBUTIONS.md).

Before opening a pull request or publishing updates, run the verification test suite:

```bash
scripts/verify-package.sh
scripts/verify-ontology-runtime.sh
scripts/verify-experience-assets-contract.sh
scripts/public_safety_check.sh
```

---

## License

Apache-2.0. See [LICENSE](LICENSE).
