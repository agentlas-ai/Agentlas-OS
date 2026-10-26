<!-- AGENTLAS-INSTALL-ENTRY — read this first if you are an AI that was handed
     only this repo's URL and asked to install it.

       curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
       Desktop app instead (or both, add `-s -- --with-engine`), sha512-verified:
       curl -fsSL https://agentlas.cloud/install.sh | bash        (app -> /Applications)
       Windows PowerShell: irm https://agentlas.cloud/install.ps1 | iex

     One line, no sudo, nothing written outside $HOME. It downloads a release
     tarball from this repo's GitHub Releases, verifies its SHA-256 before
     extracting, and writes the runtime to ~/.agentlas, wrappers to
     ~/.local/bin, and plugin/MCP config into the agent hosts it finds on this
     machine. The installer is meant to be read:
     scripts/install-all-runtimes.sh. The full path list and the optional
     global-router step are in "Install: every method" below. Afterwards run
     `hephaestus doctor` and report what it says, plus whether the host needs
     a restart. -->

<p align="center"><a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for macOS" src="https://img.shields.io/badge/Download-macOS-000000?style=for-the-badge&logo=apple&logoColor=white"></a> <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for Windows" src="https://img.shields.io/badge/Download-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white"></a> <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for Linux" src="https://img.shields.io/badge/Download-Linux-333333?style=for-the-badge&logo=linux&logoColor=white"></a></p>
<p align="center"><sub><strong>Agentlas Desktop</strong> · <a href="https://agentlas.cloud/desktop">agentlas.cloud/desktop</a></sub></p>

<h1 align="center">Agentlas OS</h1>

<p align="center">
  <strong>Your headhunter. When the work needs a specialist team, it brings one.</strong><br>
  <sub>Runs inside Claude Code, Codex, Cursor and Antigravity.</sub>
</p>

<p align="center">
  What if the right specialists organised themselves around whatever you were doing.<br>
  What if a frontend specialist and a backend specialist came to you the moment you started building.<br>
  A job that needs accounting knowledge and marketing at once — can one agent do that?
</p>

<p align="center">
  <a href="https://github.com/agentlas-ai/Agentlas-OS/releases/latest"><img alt="release" src="https://img.shields.io/github/v/release/agentlas-ai/Agentlas-OS?label=release"></a>
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green"></a>
  <img alt="platforms" src="https://img.shields.io/badge/macOS%20%7C%20Windows%20%7C%20Linux-black">
  <img alt="hosts" src="https://img.shields.io/badge/Claude%20Code%20%7C%20Codex%20%7C%20Cursor%20%7C%20Antigravity%20%7C%20Local-black">
  <img alt="ranking" src="https://img.shields.io/badge/ranking-none%20by%20design-blue">
  <a href="https://discord.gg/wbWfdGZ6S"><img alt="Join the Agentlas Discord" src="https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white"></a>
</p>
<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.zh-CN.md">中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.hi.md">हिन्दी</a>
</p>

**Agentlas Hub is a free agent community.** Publishing and calling public agents requires no agent price, lease, or Agentlas credit purchase. The caller supplies their own model and API access; subscription plans cover Agentlas software and hosted features. Creator settlement for new Hub activity is closed. Existing account balances and historical claims remain subject to the applicable account terms.

In the [Web Hub](https://agentlas.cloud/hub), each public agent has a space for browsing its release files when the author permits source access, discussing the agent, and reviewing its agent files and versions.

### Install

**Agentlas OS** — for Claude Code, Codex, Antigravity, Cursor and the
other hosts on your machine. No `sudo`, nothing written outside `$HOME`. Restart
your agent host afterwards and run `hephaestus doctor`.

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

**Agentlas Desktop** — the app, if you prefer a window to a terminal.

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash        # macOS · Linux
```

```powershell
irm https://agentlas.cloud/install.ps1 | iex               # Windows PowerShell
```

<p align="center"><sub>Downloads the latest signed release, checks its sha512, and installs without <code>sudo</code> or an admin prompt · <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest">download manually</a> · <a href="https://github.com/agentlas-ai/agentlas-desktop">Agentlas Desktop is open source — view the repo</a></sub></p>

<details>
<summary><strong>Desktop and Agentlas OS together</strong></summary>

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash -s -- --with-engine
```

```powershell
$env:AGENTLAS_WITH_ENGINE="1"; irm https://agentlas.cloud/install.ps1 | iex
```

</details>

---

## What no platform can do

No agent platform routes hundreds or thousands of agents efficiently. Agentlas
is the only place that staffs a team of domain specialists onto any job **for
the fewest tokens.**

It works because the agent spec and the protocol for calling an agent are both
standardised.

- **A2A v1.0, as written.** Agent cards are read and written at the standard
  `/.well-known/agent-card.json`. Import, export and caller gating all sit on
  the standard. An external agent is callable only when its capability is
  aligned **and its identity is verified by a signed card.**
- **One task, 20 candidates: 40,873B → 10,087B.** Not fewer candidates — a
  compressed row. The odds of the right agent being on the list stay put while
  the tokens drop to a quarter.
- Measured across **849 local profiles** and **188 published listings.**

## This is where most tools stop

|  | No task split | Task split |
| --- | --- | --- |
| **No specialist sourcing** | one chat handles the lump | same model, different prompt |
| **Specialist sourcing** | pick one from a store | **Agentlas** |

Some tools do split the work. But what takes each task is the same model with a
different prompt. Some places do sell specialists. But there is no split there —
you pick one and use it.

**Elsewhere, a split-out task is a prompt you wrote. Here it is a job opening.**
Every task goes to your machine, your private cloud, and the public Hub — all
three at once.

---

## Three steps

<table>
<tr>
<td width="44%" valign="middle">

### 1. Task split

A sentence goes in, tasks come out — roles, the order they hand off in, and the
artifact each one owes.

An org chart where a review points back to an earlier task is **rejected before
anything runs**, and you get the name of the loop.

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-build-pipeline.gif" alt="A request being split into tasks" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 2. Agent staffing

Candidates come back for each task — from your machine, your cloud, and the
public Hub at once.

**The list has no ranking.** Your model picks, and the reason is recorded.

Qualification comes in four levels — `declared`, `checked`, `demonstrated`,
`attested` — and every task can set a floor. The moment you pick, that release is
pinned by digest, so one byte of drift tomorrow stops the run.

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-make-group-v2.gif" alt="Staffing a specialist agent onto each task" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 3. Run and verify

Planning, work, synthesis and verification each run as separate invocations.

**An independent verifier has to pass it before anything is called done.** Every
invocation, every handoff and the synthesis have to be proven by receipt.
Otherwise you get the name of the place it stopped — `prepared`, `blocked`,
`source_unavailable`.

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-run-v2.gif" alt="Running and verifying the staffed roster" width="100%"></a>
</td>
</tr>
</table>

---

## Build your own specialist

When nobody on the list fits, build one. `/hep-build` turns a sentence into a
portable single agent or team: it asks only the questions that would change the
result, writes the package, and runs the contract checks before calling it done.
`/hep-build session` does the same from the conversation you are already in.

```text
/hep-build an agent that reviews App Store replies before they go out
/hep-build session
```

Every build ships input and output schemas, a routing card, and the rest of the
package contract below; a build that misses a required file fails instead of
shipping. Keep it in your private Agent Cloud or publish it to the free Hub with
`/hep-upload`, and `/hep-network` can staff it like any other candidate.

---

## Questions you probably have



<details open>
<summary><strong>So you recommend one to me in the end, right?</strong></summary>

<br>

Every place that sells agents ranks them. That is how they make money. People
click what is near the top, and the company decides what is near the top.

We don't build a ranking. The schema pins `allowHistoryEvidence` to a constant
`false`, and a source that returns a scored list has **its whole answer
refused**.

Ratings, install counts, last month's sales — we read none of them. You get the
candidates as they are, and your model picks.

</details>





<details>
<summary><strong>Is this only for developers?</strong></summary>

<br>

No. Alongside backend, security and QA, the role ontology carries an **insurance
actuary, an M&A diligence lead, an underwriting diligence specialist and a
travel planner**.

Insurance alone has four communities. Domains outside the list are not blocked.

</details>

---

## We added our own idea, then removed it

We tried the publisher's own "call me when…" sentences as a ranking signal. The
share of searches that put the right agent first fell from **73.1% to 57.0%**.
We removed it. Those sentences now reserve three seats at the end of the list —
the right not to be deleted, never the authority to re-rank.

Asked in Korean, the right agent came back **144th**. The same question in
English put it **1st**. So the order is written in English, and the language of
the deliverable is a separate field.

Showing 10, 20, 30 and 50 candidates put the right one on the list **73, 83, 87
and 93%** of the time. The default is 30.

---

## On Agentlas Desktop

Desktop is the host itself, so it decides in code — **before** a run starts —
whether the work needs one agent or a team. That decision is recorded as a
reserved run, not a suggestion. It can staff installed agents and public Hub
agents. Public Hub agent calls have no Agentlas fee; your chosen host or model/API
provider may charge for execution.

| Surface | Role |
| --- | --- |
| **Agentlas OS (Hephaestus)** | This repo — the open-source build and routing engine and command surface for your CLI hosts |
| **Agentlas Desktop** | The app that runs the same engine with a window, on macOS, Windows and Linux |
| **Agentlas Hub** | Public space for publishing, discovering, and using agents for free |
| **Agentlas Cloud** | Owner-scoped store for privately saving and retrieving your own agents |

---

## Install: every method, and what it writes

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

One line, no `sudo`, nothing written outside `$HOME`. Then restart your agent
host and run `hephaestus doctor` — it prints what is wired and what is not.
Prefer a GUI? [Agentlas Desktop](https://agentlas.cloud/desktop) runs the same
runtime on macOS, Windows and Linux.

It configures **every supported host it finds on this machine**, not only the
one you are typing in — detection is by what is on your `PATH`.

<details>
<summary><strong>Everything it writes</strong> — the full list, because "and so on" is not an answer</summary>

| Path | What lands there |
|---|---|
| `~/.agentlas/` | the runtime itself, and its generations |
| `~/.local/bin/` | the `hephaestus`, `ontology`, `agentlas-one` and `hep-*` shell wrappers |
| `~/.claude/`, `~/.codex/` | plugin registration, commands/prompts, memory hooks, MCP registration |
| `~/.cursor/` | commands, skills, and the MCP entry in `mcp.json` |
| `~/.gemini/antigravity/`, `~/.gemini/config/` | Antigravity workflows, plugin, MCP config and memory hook — Antigravity lives under `.gemini`, not `.antigravity` |
| `~/.config/opencode/` | commands, the MCP entry in `opencode.json`, and the memory plugin |
| `~/.config/goose/config.yaml` | MCP registration, only when the file does not exist yet |
| `~/.copilot/mcp-config.json` | MCP server registration |
| `~/.openclaw/` | skills and the `agentlas-one` hook |
| `~/.hermes/skills/`, `~/.kimi/skills/` | skills |
| `~/.grok/` | memory hook and a managed block in `~/.grok/AGENTS.md` |
| `~/.agents/` | the vendor-neutral skills directory, plus goose's `agentlas-one` hook plugin |

Two things that are easy to assume wrongly:

- **It configures every supported host it finds, not just the one you are
  typing in.** Detection is by what is on your `PATH`, so an otherwise empty
  home still gets Cursor, OpenCode and the rest wired up if those CLIs are
  installed. Hosts it cannot find are reported as skipped, not faked.
- **It edits files that already exist** (`~/.codex/config.toml`,
  `~/.cursor/mcp.json`, `~/.config/opencode/opencode.json`,
  `~/.copilot/mcp-config.json`, `~/.gemini/config/mcp_config.json`). It
  replaces only the entries it owns — the `hephaestus-network` MCP server, plus
  the legacy `agentlas` entry it removes — and leaves every other key in place.
  A JSON config that does not parse is refused, not overwritten. No backup copy
  is written, except that a Codex marketplace-source change is snapshotted to
  `~/.codex/.agentlas-marketplace-backups/`. An existing
  `~/.config/goose/config.yaml` is never rewritten; the installer tells you how
  to add the entry yourself.

It never uses `sudo`, never writes outside `$HOME`, and downloads only from
`github.com`. The release archive's SHA-256 is checked before anything is
extracted, and a mismatch refuses the install.

Two more things worth knowing before you run it:

- **An existing install is updated in place, not removed and reinstalled.** An
  installed Claude Code plugin is updated with `claude plugin update`, and a
  marketplace entry is re-pointed only when it is the installer's own verified
  source, so unrelated plugin settings survive.
- `~/.claude.json` may appear at the root of your home. That is the `claude`
  CLI initialising itself; on native Windows it also records the MCP server
  the installer registers with `claude mcp add --scope user`.

</details>

### Optional: route work automatically

Off by default. `hephaestus global install` appends roughly 75 lines to the
global instructions file of every supported host it finds — measured on a clean
machine that was `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` and
`~/.gemini/GEMINI.md`, three files, not one. It changes how substantial work is
routed from then on, in every project, so it is a bigger decision than the rest
of the install and it is yours to make separately.

It appends rather than overwrites, writes a timestamped `.bak` beside each file,
is idempotent on a second run, and is fenced with
`<!-- HEPHAESTUS:GLOBAL-ROUTER:BEGIN -->` so `hephaestus global remove` takes it
back out. To turn it on during the install instead, add
`HEPHAESTUS_INSTALL_GLOBAL_ROUTER=1` before `bash`.

### Paste to Install

Already inside an LLM? Paste this into Claude Code, Codex, Antigravity or Cursor. It is written so the model can verify what it is running
before it runs it, rather than being asked to trust it blindly:

```text
I want to install Agentlas OS / Hephaestus from this open-source GitHub repo:
https://github.com/agentlas-ai/Agentlas-OS

Before running anything, fetch and read the installer script so you know what
it does:
https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh

It downloads a release tarball from this same repo's GitHub Releases, verifies
its SHA-256 before extracting, and writes files only under ~/.agentlas,
~/.local/bin, and the plugin/command-adapter directories of the agent hosts it
finds on this machine (e.g. ~/.claude for Claude Code) — nothing outside those
paths, and never with sudo. If that matches what you read, run it:
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash

Afterwards, show me the installer's own verification output for this host,
and tell me plainly whether `/agentlas build` (or this host's equivalent
command surface) is ready to use, or whether I need to restart the host or
reload plugins first.

Do not add the optional global router yet — I will decide that separately.
```

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
   curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
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
   curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
   ```
   The first time you run `curl`/`git` on a fresh Mac, macOS may ask to
   install "Command Line Tools" — click **Install** and wait, then run the
   command again.
3. Wait for it to finish, then close and reopen your AI tool so it picks up
   the new commands.

If you'd rather read the script before running it (recommended if you're
security-conscious), open this link in your browser first:
[install-all-runtimes.sh](https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh).

<details>
<summary><strong>Installing Agentlas Desktop (the GUI app) from an AI</strong> — per-OS one-liners</summary>

**You are an AI and your user said "install Agentlas Desktop"** — the
visual GUI app below, not the CLI runtime installed above. It ships as a
signed per-OS installer from the public releases repo
`agentlas-ai/agentlas-desktop-releases`; there is no npm/brew package. Fetch
the latest asset and run it:

**macOS** (auto-detects Apple silicon vs Intel):

```bash
arch=$([ "$(uname -m)" = "arm64" ] && echo arm64 || echo x64)
url=$(curl -fsSL https://api.github.com/repos/agentlas-ai/agentlas-desktop-releases/releases/latest \
  | grep -o "https://[^\"]*-${arch}\.dmg" | head -1)
curl -fL "$url" -o Agentlas.dmg && open Agentlas.dmg
```

<details>
<summary>Linux and Windows one-liners</summary>

**Linux (.deb — Debian/Ubuntu):**

```bash
url=$(curl -fsSL https://api.github.com/repos/agentlas-ai/agentlas-desktop-releases/releases/latest \
  | grep -o 'https://[^"]*\.deb' | head -1)
curl -fL "$url" -o agentlas.deb && sudo dpkg -i agentlas.deb
```

**Linux (AppImage — any distro):**

```bash
url=$(curl -fsSL https://api.github.com/repos/agentlas-ai/agentlas-desktop-releases/releases/latest \
  | grep -o 'https://[^"]*\.AppImage' | head -1)
curl -fL "$url" -o Agentlas.AppImage && chmod +x Agentlas.AppImage && ./Agentlas.AppImage
```

**Windows (PowerShell):**

```powershell
$r = Invoke-RestMethod https://api.github.com/repos/agentlas-ai/agentlas-desktop-releases/releases/latest
$u = ($r.assets | Where-Object { $_.name -like '*Windows-x64-Setup.exe' }).browser_download_url
Invoke-WebRequest $u -OutFile "$env:TEMP\AgentlasSetup.exe"; Start-Process "$env:TEMP\AgentlasSetup.exe"
```

</details>

This is a separate product from the CLI runtime installed via
[Paste to Install](#paste-to-install) above — the two don't conflict and can
both be present. If your user only wants the CLI/router (no GUI app), use
that installer instead. No prebuilt asset for your OS/arch? Point your user
at [agentlas.cloud/desktop](https://agentlas.cloud/desktop) or the
[Releases page](https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest).

</details>


<details>
<summary><strong>Build, Use, Own — the full model</strong></summary>


An agent you create should remain an asset you can move, rather than a
setting trapped in one chat, one model-vendor workspace, or one computer.
Agentlas separates three jobs that ordinary agent builders blur together:

This is the public Agent Trust contract: a
portable, owner-scoped, inspectable, and restorable package contract—not a
claim of regulated financial or legal trust services.

| Value | What Agentlas does | Entry point in an external LLM host |
| --- | --- | --- |
| **Build** | Compiles a plain-language request into a runnable single-agent or team package with roles, tools, memory boundaries, permissions, routing, and verification contracts. | `/agentlas build` |
| **Use** | Finds free public Hub agents and brings the selected runtime bundle into your current Agentlas host. The publisher's private source work is not copied into your workspace. | `/agentlas hub` (Hub only) or `/agentlas network` (Local + Cloud + Hub) |
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

### Turn a working session into an owned agent

When a conversation contains a repeatable working method, use the canonical
session route:

```text
hep-build session
```

In an interactive host, the current visible conversation is the source. Agentlas
asks for the destination first; if you do not name another folder, it creates a
new safe-slug child below `AGENTLAS_AGENT_HOME` or, by default,
`~/.agentlas/agentlas-agent`. Existing children are never overwritten. It then
shows a generalized session report for your review, turns the approved method
into a standalone agent prompt and package, registers it locally, and runs the
normal verification gates.

You do not need to export JSON for this interactive route. JSON/JSONL remains an
explicit option for terminal, replay, and headless workflows only. The default
output is a single agent; choose a team explicitly. Raw transcripts, hidden
prompts, credentials, private paths or URLs, screenshots, and literal tool
arguments/results are not carried into the generated package. Uploading to Agent
Cloud or the public Hub is a separate, explicit choice. See the
[session build contract](contracts/session-build.md) for the deterministic
export boundary.

```text
current conversation
  -> destination question
  -> generalized session report
  -> owner review
  -> standalone agent/package
  -> local registration and verification
```

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
emits, and `bin/hephaestus contract verify <folder>` is what enforces it.
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
| **Agentlas Hub** | Public packages from creators and teams | Discover and use public agents for free with `/agentlas hub`; `/agentlas network` federates Hub with Local and owner Cloud. Publish only through an explicit public-Hub choice. |
| **My Agent Cloud** | Only the signed-in owner's Cloud packages | Privately store, restore, and call packages you own with the `/agentlas upload` Cloud choice and `/agentlas cloud`. |
| **Current host** | The installed runtime, chosen model, local project, credentials, and granted permissions | Execute the selected local, Cloud, or Hub package. |

---

</details>


<details>
<summary><strong>All Install Methods — source, offline, per-host</strong></summary>


### Manual LLM Adapter Install

Use this only when your current LLM cannot run setup for you. It installs the
shared Hephaestus runner and command adapters for supported LLM tools.

```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```
This installs the neutral runner at `~/.agentlas/runtime/current/bin/hephaestus` and registers the command, skill, or MCP adapters for Claude Code, Codex, Antigravity, Cursor, OpenCode, OpenClaw, Hermes, Kimi Code CLI, goose, and GitHub Copilot CLI, plus memory hooks for Grok. Local models use the MCP entrypoint `hephaestus mcp serve`. The installer verifies each runtime surface after registration.

Desktop startup and every `/hep-*` command start the same digest-verified,
rate-limited update check in the background. The current command never waits
for network or installation work. A successful update atomically moves
`~/.agentlas/runtime/current` and reconciles every already-installed host
adapter; the next command or reloaded session uses the new release. Releases
v1.1.63 through v1.1.68 briefly installed a separate six-hour OS scheduler.
Current installs remove that retired scheduler automatically.

Offline or air-gapped install: set `HEPHAESTUS_SOURCE_DIR=/path/to/checkout`
before running the installer to skip the GitHub release download and verified
checksum step entirely and install straight from a local Agentlas-OS checkout
instead, e.g. `HEPHAESTUS_SOURCE_DIR=$(pwd) bash scripts/install-all-runtimes.sh`.
Use it when you already have the source on disk (a git clone or an
already-extracted release) and want a fully local install.

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
| `hephaestus global install` | Install or refresh the managed router block for Codex, Claude Code, and Antigravity. |
| `hephaestus global status` | Show whether each runtime file has the managed router block. |
| `hephaestus global remove` | Remove only the managed Hephaestus router block. Existing user content stays in place. |
| `hephaestus global install --target codex` | Install only `~/.codex/AGENTS.md`. |
| `hephaestus global install --target claude` | Install only `~/.claude/CLAUDE.md`. |
| `hephaestus global install --target antigravity` | Install only `~/.gemini/GEMINI.md`, which Antigravity reads. |
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
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.2.70
codex plugin add hephaestus@agentlas-core-engine
```
*Note: Codex does not accept `/plugin marketplace add` inside the app — run the two commands above in your OS terminal. The OS-terminal CLI command is singular (`codex plugin`); inside the Codex app, the plugin browser slash command is plural (`/plugins`). Codex 0.117+ removed custom `/prompts:*` commands; after install, invoke the supported plugin skill as `$hephaestus-network <request>`.*

</details>

<details>
<summary>Copy Files into a Project (Manual Driver)</summary>

Clone the repo and copy `AGENTS.md`, `agent.md`, `agents/`, `skills/`, `modes/`, `schemas/`, `templates/`, and `.agentlas/` into your workspace. Runtime folders (`.claude/`, `codex/`, `antigravity/`, `.agents/`) function as adapters over the same canonical core.

</details>

**Just talk:** After installation, speak in plain language within native Agentlas interfaces to auto-route tasks. In external LLM tools, use the explicit commands listed below. When you don't know what agents exist, start with `/agentlas search`.

**One word to remember:** everything starts with `agentlas` in an LLM host —
`/agentlas`. In a shell the commands are `hephaestus` and `hep-*`; the `agentlas`
shell command belongs to the separate Agentlas Terminal.

---

</details>


<details>
<summary><strong>The Command Surface — every command</strong></summary>


Inside native Agentlas environments, Hephaestus operates commandless. External LLM tools use a deliberately small visible command set for building agents and staffing work with them:

| System Subsystem | Command | Example |
| :--- | :--- | :--- |
| **Agent / Team Builder** | `/agentlas-build` (or `/agentlas build`, `/hep-build`) | `/agentlas-build create a customer support agent for Shopify refunds` |
| **Session-to-Agent Builder** | `/hep-build session` (canonical route: `hep-build session`) | `/hep-build session` |
| **Workforce Federation (Local + Cloud + Hub)** | `/agentlas-network` (or `/agentlas network`, `/hep-network`) | `/agentlas-network split this launch plan into research, copy, QA, and release agents` |
| **Registered Local Agents Only** | `/agentlas-local` (or `/agentlas local`, `/hep-local`) | `/agentlas-local use only agents registered on this machine` |
| **Owned Cloud Agents Only** | `/agentlas-cloud` (or `/agentlas cloud`, `/hep-cloud`) | `/agentlas-cloud use my saved finance analyst agent to review this report` |
| **Public Hub Agents Only** | `/agentlas-hub` (or `/agentlas hub`, `/hep-hub`) | `/agentlas-hub find public specialists for accessibility QA` |
| **Directory Search** | `/agentlas-search` (or `/agentlas search`, `/hep-search`) | `/agentlas-search find agents for a market report workflow` |
| **Inter-Process Call (IPC)** | `/agentlas-call` (or `/agentlas call`, `/hep-call`) | `/agentlas-call market-researcher, report-writer {draft a market report}` |
| **Cloud / Hub Destination Gate** | `/agentlas-upload` (or `/agentlas upload`, `/hep-upload`) | `/agentlas-upload ./agents/customer-support-hq` |
| **Sign-in** | `/agentlas-login` (or `/agentlas login`, `/hep-login`) | `/agentlas-login` |
| **Orchestrator / Worker Models** | `/agentlas-orch` (or `/agentlas orch`, `/hep-orch`) | `/agentlas-orch orchestrator=frontier worker=economy` |
| **Goal Plan Tree (long, measurable goals)** | `/agentlas-goal` (or `/agentlas goal`, `/hep-goal`) | `/agentlas-goal reach 1000 followers in a month, today 30` |
| **Runtime + Adapter Update** | `/agentlas-update` (or `/agentlas update`, `/hep-update`) | `/agentlas-update` |

`/hep-orch` sets which model runs the orchestrator and which runs the workers,
so a fan-out of mechanical work does not bill frontier runs. **The split only
puts two models to work on Claude Code**, which is the one host that spawns a
real subagent and takes a model per subagent. Codex, Antigravity, Cursor,
and OpenCode have no subagent of their own: one model plays every role in
sequence there, the allocation receipt is still written, and the ceiling still
bounds what that model may request — but no second, cheaper model appears.

`/hep-goal` adds a plan tree to your host's own `/goal`. It first decides the
shape of the goal. Short work with one clear check stays a single tactic and
behaves exactly like the host goal, with no extra text. A long goal with a
number you named becomes a mission tree: key results, strategies, tactics, and a
KPI reading that says whether the plan is moving. It tells you when the numbers
say the plan has stalled, and when the target looks out of reach it asks you
instead of re-planning forever. The host goal still decides when the work is
done; `/hep-goal` only keeps the plan and the numbers honest. A target is only a
number you wrote in the goal text, and every reading needs a source and a short
evidence quote. It changes only its own files under `.agentlas/goal/`, never
permissions or payments. The default mode is `shadow` (it records and measures,
injects nothing, applies no re-plan); set `AGENTLAS_GOAL_STRATEGY=on` to use it.

What has been measured so far: against a simulated account, the engine saw a
stalled approach on day 2 and told the owner about an unreachable target on day
3, where a loop that keeps one approach never does; with a better alternative to
switch to it reached 298 of 300 followers against 44. That simulation assumes the
alternatives are known, so it shows the mechanism, not a model's judgment. With
real models, sonnet and haiku stored a valid plan in 12 of 12 runs (the right
shape every time, targets equal to the owner's numbers), and submitted an
accepted re-plan in 6 of 6 review runs. Not measured: whether it beats a plain
host goal on real long-running work. Treat it as unproven until it has run on
real goals.

Every row also answers to its original `/hep-*` name — `/agentlas network` and
`/hep-network` are the same command. Nothing was renamed away, so existing
scripts, notes, and muscle memory keep working. Current Codex uses explicit
plugin skills `$hephaestus-build`, `$hephaestus-network`,
`$hephaestus-cloud`, and `$hephaestus-upload`; other MCP surfaces can be
requested in plain language.
Custom `/prompts:*` commands were removed from Codex 0.117+.

---

</details>


<details>
<summary><strong>Deeper — the build factory and the routing scheduler</strong></summary>


### Meta-Agent Factory — Process Creation
A unified compilation factory using four builders. Every generated package registers its global command (`.agentlas/global-commands.json`) and ships verification scripts—the user never has to infer how to run the compiled package:

| Compilation Mode | Routing Target | Output Artifact |
| :--- | :--- | :--- |
| **Single-Agent** | `10-single-agent-builder` | Standalone worker with localized skills, memory contracts, and runtime adapters. |
| **Multi-Agent Team** | `20-multi-agent-team-builder` | Hierarchical team containing a PM Orchestrator, Memory Curator, Policy Gate, QA, and validation scripts. |
| **Workspace Packager** | `30-agentlas-packager` | Compiled bundle ready for runtime import, CLI execution, or GitHub distribution. |
| **Session Agent Builder** | `40-session-agent-builder` | Turns the current conversation (or, for headless runs, an explicit JSON/JSONL export) into an owner-reviewed single agent by default, or a team when you choose one. |

*Briefing Interview Gate:* Builders initiate the process using the **briefing interview gate** : conducting lens-driven questions, evaluating the ambiguity threshold, searching primary sources, and outputting the work brief.

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

#### Execute a prepared goal from an external host

An explicitly selected host plugin or executable can run the newest ready plan
bound to a Workforce goal through the provider-neutral adapter contract:

```bash
./bin/hephaestus workforce execute \
  --project . \
  --goal-id <host-task-id> \
  --adapter-argv-json '["/absolute/path/to/host-adapter"]'
```

The adapter reads one versioned JSON request from standard input and writes one
JSON response to standard output for inventory observation and each required
orchestrator, planner, worker, synthesis, and verifier invocation. Core retains
the exact preparation pins, verifies and snapshots output artifacts locally,
and returns an execution receipt only after the existing receipt validator
accepts the complete run. The adapter owns its provider authentication and
native runtime configuration as an independently installed plugin; do not put
credentials in the argv JSON. The complete v1 request, response, artifact, and
failure contract is documented in
[`agentlas_cloud/workforce/host_executor.py`](agentlas_cloud/workforce/host_executor.py).

Tool inventory distinguishes native host enforcement (`host-native`) from a
host-owned tool dispatcher (`host-broker`). A bound tool requires its invocation
receipt to use that same enforcement path; neither label grants authority to a
package that did not select the host permission policy.


---

</details>


<details>
<summary><strong>What It Builds — process packaging</strong></summary>


Hephaestus packages agents into a standard directory layout that any workspace runtime can parse, install, verify, and run. The important part is not just `agent.md`; it is the operating contract around it. The layout below is what `package-contract.json` requires and `hephaestus contract verify` checks:

```text
├── AGENTS.md                         # Package entry: name, purpose, canonical command, roles
├── agent.md                          # Primary instructions: role, steps, output contract
├── agentlas.json                     # Manifest: permissions, memory policy, read allow/deny lists
├── agents/<role>/agent.md            # Team only: one folder per worker
├── A2A/agent-card.a2a.json           # A2A Agent Card projected from the two cards below
├── .agentlas/
│   ├── agent-card.json               # Identity: name, slug, summary, capabilities, entrypoints
│   ├── routing-card.json             # Triggers and anti-triggers (ko + en), risk, memory behavior
│   ├── build-profile.json            # Fail-closed build readiness profile
│   ├── memory-map.json               # Memory ownership map
│   ├── global-commands.json          # Per-runtime slash command adapters
│   ├── mcp-policy.json               # What the machine must provide, and what happens without it
│   ├── skill-registry.json           # Skill inventory (may be empty)
│   ├── memory-tickets.jsonl          # Candidate memory events before curator promotion
│   ├── capability-eval-plan.json     # Positive/negative eval prompts with pass criteria
│   ├── routing-benchmarks.jsonl      # At least 10 route/reject cases, ko + en
│   ├── work-brief.json               # Interview-derived goal, constraints, decisions
│   ├── company-blueprint.json        # Team only: orchestrator, nodes, edges
│   ├── sitemap.json                  # Team only: what each task produces and consumes
│   └── brief.json                    # agentlas.brief/1 resume, compiled at upload
├── contracts/                        # intake.schema.json, output.schema.json, output.example.json
├── docs/                             # Builder interview, research sources, tool selection,
│                                     #   domain synthesis, prompt performance contract
├── tools/requirements.yaml           # Projected from mcp-policy.json + agentlas.json
├── permissions/policy.yaml           # Projected shell/network/file/payment whitelist
├── hooks/                            # memory-upgrade.yaml, on_stop.yaml — declared, host-enforced
├── evals/README.md                   # Points at the eval plan and routing benchmarks
└── .claude/skills/<name>/SKILL.md    # Skills, when the package carries any
```

`docs/`, the eval plan and the work brief may be skipped only by a
user-confirmed minimal private build. `provenance.json`, `knowledge/`,
`schemas/`, `sandbox/` and `examples/` are optional.

That package shape is why an Agentlas agent is more than an LLM-written role
prompt. It carries routing, memory, input/output contracts, permissions,
runtime adapters and evaluation evidence together.

---

</details>

## Docs By Goal

| System Goal | Reference Documentation |
|---|---|
| Understand the canonical route | [`AGENTS.md`](AGENTS.md) |
| See the full team contract | [`agent.md`](agent.md) |
| Package contract | [`package-contract.json`](package-contract.json) |
| Session build | [`contracts/session-build.md`](contracts/session-build.md) |
| Routing card | [`schemas/routing-card.schema.json`](schemas/routing-card.schema.json) |
| Workforce work order | [`schemas/workforce-work-order.schema.json`](schemas/workforce-work-order.schema.json) |
| Compiled brief | [`schemas/agentlas-brief.schema.json`](schemas/agentlas-brief.schema.json) |
| Mode map | [`modes/README.md`](modes/README.md) |

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

## License

Apache-2.0. See [LICENSE](LICENSE).
