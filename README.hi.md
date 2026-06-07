<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">agentlas-meta-agent</h1>

<p align="center">
  <strong>एक अधूरा agent idea लेकर उसे installable Agentlas agent/team repository में बदलें।</strong>
</p>

<p align="center">
  एक specialist agent बनाएं, multi-agent team तैयार करें, या किसी मौजूदा Claude/Codex/OpenClaw/Hermes workspace को public-safe Agentlas package में बदलें।
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
  <img src="assets/agentlas-meta-agent-architecture.svg" alt="Agentlas Meta-Agent architecture decomposition">
</p>

---

## Quickstart

तीन install paths हैं। अगर आपको पूरा Agentlas runtime चाहिए, तो **1 + 3** इस्तेमाल करें। अगर यह package सीधे Claude Code, Codex या किसी सामान्य project folder में चाहिए, तो **2** इस्तेमाल करें।

| Path | कब इस्तेमाल करें | क्या खोलना है |
|---|---|---|
| 1. Agentlas Terminal | shell से Agentlas agents चलाने के लिए | पहले Agentlas Desktop, फिर macOS Terminal / Windows PowerShell / Linux terminal |
| 2. Standalone agentlas-meta-agent | Claude Code, Codex या normal repo में direct install के लिए | Claude Code, Codex या OS terminal |
| 3. Agentlas Desktop | visual local runtime, agent/team management, vault, Apps के लिए | browser में download page, फिर Agentlas Desktop app |

### 1. Agentlas Terminal install करें

Agentlas Terminal **Agentlas Desktop** से install होता है। पहले Desktop install करें, फिर app में यह खोलें:

```text
Agentlas Desktop -> Settings -> Use from the terminal (`agentlas` CLI) -> Install CLI
```

उसके बाद अपना सामान्य terminal खोलें और `agentlas` चलाएं।

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

Desktop Settings से CLI install करने के बाद:

```bash
agentlas list
agentlas run agentlas-meta-agent "Package this workflow for Agentlas"
```

### 2. agentlas-meta-agent standalone install करें

#### Simple file install

जिस project folder में package files चाहिए, वहां macOS Terminal, Linux terminal, Windows Git Bash या WSL खोलें:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.0/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Windows PowerShell:

```powershell
$zip = "$env:TEMP\agentlas-meta-agent-v0.2.0.zip"
$extract = "$env:TEMP\agentlas-meta-agent-v0.2.0"
Invoke-WebRequest "https://github.com/agentlas-ai/Hephaestus/archive/refs/tags/v0.2.0.zip" -OutFile $zip
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $extract -Force
$src = Get-ChildItem $extract -Directory | Select-Object -First 1
Get-ChildItem $src.FullName -Force | Copy-Item -Destination (Get-Location) -Recurse -Force
```

#### Claude Code plugin install

Marketplace registration और plugin installation अलग steps हैं। marketplace command Claude Code को बताता है कि यह repo कहां है। install command असल plugin install करता है। install के बाद reload करें।

**Claude Code chat के अंदर टाइप करें**:

```text
/plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
/plugin install agentlas-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

**`claude` CLI वाले OS terminal में टाइप करें**:

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

Expected result:

```text
✓ Installed agentlas-meta-agent. Run /reload-plugins to apply.
Reloaded: 1 plugin · 0 skills · 9 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

#### Codex plugin install

**Codex chat के अंदर टाइप करें**:

```text
/plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.0
/plugin install agentlas-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

**`codex` CLI वाले OS terminal में टाइप करें**:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.0
codex plugin list
codex plugin add agentlas-meta-agent@agentlas-core-engine
codex plugin list
```

अगर Codex session पहले से खुला है, तो `/reload-plugins` चलाएं या नया session शुरू करें।

### 3. Agentlas Desktop install करें

browser में खोलें:

```text
https://agentlas.cloud/desktop
```

Desktop आपको visual Agentlas surface देता है: local projects, agents, teams, Apps, vault references, runtime selection, built-in Core Engine Meta-Agent routing और `agentlas` CLI installer।

## तस्वीरों के साथ install guide

अगर आप Claude Code या Codex chat के अंदर हैं, तो slash command वाली तस्वीरें follow करें। अगर आपने macOS Terminal, Windows PowerShell, Linux terminal, Git Bash या WSL खोला है, तो CLI वाली तस्वीरें follow करें।

### Claude Code chat

इन commands को सीधे Claude Code में type करें।

![Claude Code chat install flow](assets/install-claude-code-chat.svg)

### OS terminal में Claude CLI

जब आपके shell में `claude` command उपलब्ध हो, तो यह path इस्तेमाल करें।

![Claude CLI install flow](assets/install-claude-cli.svg)

### Codex chat

इन commands को सीधे Codex में type करें।

![Codex chat install flow](assets/install-codex-chat.svg)

### Codex Desktop या IDE Extension

जब Codex में Plugins settings screen दिखे, तो यह path इस्तेमाल करें।

![Codex Desktop settings install flow](assets/install-codex-desktop-settings.svg)

### OS terminal में Codex CLI

जब आपके shell में `codex` command उपलब्ध हो, तो यह path इस्तेमाल करें।

![Codex CLI install flow](assets/install-codex-cli.svg)

## क्या खोलें और कहां type करें

| काम | क्या खोलें | कहां type करें |
|---|---|---|
| Desktop download | Browser | `https://agentlas.cloud/desktop` या OS download command |
| `agentlas` CLI install | Agentlas Desktop | Settings -> Use from the terminal -> Install CLI |
| Agentlas Terminal चलाना | OS terminal | `agentlas list`, `agentlas run ...` |
| Claude plugin slash command से install | Claude Code | `/plugin marketplace add ...`, `/plugin install ...`, `/reload-plugins` |
| Claude plugin shell से install | OS terminal | `claude plugin marketplace add ...`, `claude plugin install ...` |
| Codex plugin slash command से install | Codex chat | `/plugin marketplace add ...`, `/plugin install ...`, `/reload-plugins` |
| Codex plugin shell से install | OS terminal | `codex plugin marketplace add ...`, `codex plugin add ...` |

## यह क्या बनाता है

`agentlas-meta-agent` सिर्फ prompt answer नहीं बनाता। यह ऐसा repository छोड़ता है जिसे दूसरा runtime inspect, install, verify और आगे improve कर सके।

| आप क्या मांगते हैं | Route | Output |
|---|---|---|
| "X करने वाला एक agent बनाओ" | `10-single-agent-builder` | skills, memory contracts, runtime adapters और verification वाला single worker |
| "इस workflow के लिए team/company बनाओ" | `20-multi-agent-team-builder` | HQ, PM Soul, Memory Curator, Policy Gate, eval, QA और handoff वाली multi-agent team |
| "इस existing agent/repo/workspace को package करो" | `30-agentlas-packager` | Desktop import, terminal, Codex, Claude, Gemini या public GitHub release के लिए साफ Agentlas package |

## Architecture

public core architecture/foldering contract है। Claude, Codex, Gemini, Desktop और Terminal folders उसी core पर बने thin adapters हैं; वे अलग source of truth नहीं हैं।

| Public contract | काम |
|---|---|
| Mode auto-detection | generation से पहले `single-agent-creator`, `team-builder`, या `agentlas-packager` चुनता है |
| Clarify question loop | सिर्फ runtime, public/private boundary, tools या safety पर असर डालने वाले सवाल पूछता है |
| `.agentlas` auto-activation | local runtime को project memory, sitemap/task-bias, Memory Tickets और vault references seed करने देता है |
| Skill lifecycle registry | skill को candidate metadata से शुरू करता है और trial/Curator decision ledgers रखता है |

Default export conservative है। Generated skills automatic first-class recall नहीं बनते। Curator को execution evidence, sealed holdout/replay, rollback coverage और workspace policy approval देखना होगा।

## Agentlas Desktop और Terminal साथ क्यों बेहतर हैं

- Desktop agent/team structure, local projects, Apps, vault references और runtime choices दिखाता है।
- Terminal वही package `agentlas` command से चलाता है।
- Desktop/Terminal में Core Engine Meta-Agent path built in है, इसलिए fresh install के बाद भी agent creation और packaging शुरू हो सकती है।
- Standalone Claude/Codex install तब उपयोगी है जब package सीधे उन runtimes में चाहिए।

## Compare

| तुलना | उनकी ताकत | `agentlas-meta-agent` क्या जोड़ता है |
|---|---|---|
| OpenAI / Codex | strong models और coding terminal | portable repo contracts, `.agentlas` memory/package files, skills, schemas, runtime adapters, public verification |
| Claude / Claude Code | strong reasoning और Claude-native workflows | Claude support, लेकिन Claude-only नहीं; Codex, Gemini, Desktop, terminal और `AGENTS.md` भी aligned रहते हैं |
| OpenClaw | local identity और workspace agent loop | visible role folders, Agentlas package contracts, public-safety checks, Desktop import, vault references |
| Hermes | persona और memory-centered local runtime | PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, skill lifecycle evidence |

OpenAI और Claude model/runtime surfaces हैं। OpenClaw और Hermes local-agent experiences हैं। `agentlas-meta-agent` agent को portable, inspectable, installable और publishable बनाने वाली package layer है।

## Usage examples

```text
/meta-agent Create a research agent for SEC filing analysis.
Package it for Codex, Claude Code, Gemini, and Agentlas Desktop.
```

```text
Use agentlas-meta-agent.
Build a customer-support operations team with PM Soul, Memory Curator, Policy Gate, QA, eval, and public-safe release checks.
```

```text
Package this local OpenClaw/Hermes-style workspace into Agentlas architecture.
Keep private notes, machine paths, raw logs, and secrets out of the public repo.
```

## Docs

| Goal | Document |
|---|---|
| canonical route समझना | [`AGENTS.md`](AGENTS.md) |
| team contract देखना | [`agent.md`](agent.md) |
| source of truth देखना | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| runtime boundaries समझना | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| mode चुनना | [`docs/mode-classifier.md`](docs/mode-classifier.md) |
| package verify करना | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| public safety check करना | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

## Public Safety Boundary

यह repo hosted Agentlas billing/account logic, production credentials, customer data, raw private logs, raw transcripts, desktop keychain storage, local database implementation या private deployment configuration शामिल नहीं करता।

Public package में local machine paths, API keys, tokens, private keys, service-account JSON, `.env` secrets, private research notes, raw chat transcripts, customer logs, hosted billing/account/OAuth internals या desktop storage internals नहीं होने चाहिए।

## License

Apache-2.0. [`LICENSE`](LICENSE) देखें।
