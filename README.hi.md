<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus — Network 2.0</h1>

<p align="center">
  <strong>लोकल-फ़र्स्ट एजेंट और प्लगइन नेटवर्किंग: अपने एजेंट्स को किसी भी AI रनटाइम से कॉल करें, मानकीकृत राउटिंग कार्ड से रूट करें, मेमोरी अपनी मशीन पर रखें।</strong>
</p>

<p align="center">
  एक अधूरे agent idea को installable Agentlas agent या team repository में बदलें — फिर Hephaestus Network हर request को सही local agent तक route करता है, Hub fallback सिर्फ़ आपकी मंज़ूरी पर।
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

## Hephaestus Network 2.0

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Hephaestus Network 2.0 A2A networking architecture">
</p>

<p align="center">
  <sub>चित्र 2. Hephaestus Network 2.0 — रनटाइम, ग्लोबल लोकल-फ़र्स्ट ऑर्केस्ट्रेटर, राउटिंग कार्ड, अनुमोदन गेट, लोकल मेमोरी, और Agentlas Hub A2A/MCP फ़ॉलबैक।</sub>
</p>

एक command, हर runtime, सब कुछ local:

```text
/hep-network इन मीटिंग नोट्स को साप्ताहिक रिपोर्ट में बदलो
/hep-network प्रोडक्ट लॉन्च प्लान का ड्राफ़्ट बनाओ
@Hephaestus इस फ़ोल्डर के दस्तावेज़ों को व्यवस्थित कर सारांश दो   # बिना स्लैश कमांड वाले रनटाइम
hep-network "इस काम के लिए सही एजेंट ढूँढो"   # टर्मिनल
```

- **राउटिंग कार्ड।** हर agent, team और plugin के साथ एक मानकीकृत राउटिंग
  कार्ड आता है (triggers, anti-triggers, capabilities, risk profile, memory
  behavior)। जो कार्ड quality gates पास नहीं करते, वे कभी auto-route नहीं होते।
- **लोकल फ़र्स्ट।** explicit commands → project overrides → आपके local cards।
  Agentlas Hub एक fallback है और उसे सिर्फ़ redacted keywords मिलते हैं —
  आपका raw prompt कभी नहीं।
- **मेमोरी लोकल रहती है।** agent capability Hub से आ सकती है; आपकी
  user/project memory `~/.agentlas/networking/` में रहती है और explicit export
  approval के बिना मशीन से कभी बाहर नहीं जाती।
- **Receipts, execution नहीं।** हर routing decision एक receipt लिखता है।
  Router सिर्फ़ agent या Hub bundle चुनता है; actual tool permissions host
  runtime संभालता है।
- **दावा नहीं, मापा हुआ।** एक routing benchmark (Korean + English)
  auto-routing को gate करता है: top-3 recall ≥ 90%, privacy suite में zero
  unsafe routes।

विवरण: [docs/hephaestus-network-2.0.md](docs/hephaestus-network-2.0.md) ·
runtime support matrix: [docs/runtime-fallback-adapters.md](docs/runtime-fallback-adapters.md)

---

## पेस्ट करके install (अपने AI से करवाएं)

Terminal नया लगता है? खुद कुछ चलाने की ज़रूरत नहीं। कोई भी AI coding tool —
**Claude Code, Codex, Gemini CLI, Antigravity, या Cursor** — खोलें और नीचे का
message उसके chat box में जैसा है वैसा paste करें। Agent आपके लिए installer
चलाएगा और अगली command बता देगा:

```text
इस workspace में Hephaestus Agentlas meta-agent set up करो। GitHub repo यहाँ है:
https://github.com/agentlas-ai/Hephaestus

Latest release/install instructions follow करो, फिर बताओ कि मैं जो tool इस्तेमाल कर रहा/रही हूँ (Claude Code, Codex, Gemini CLI, Antigravity, Cursor) उसमें ये commands कैसे इस्तेमाल करनी हैं: /hep-build, /hep-network, /hep-cloud, /hep-search, /hep-call, /hep-upload। कुछ fail हो तो error पढ़कर ठीक करो और दोबारा try करो।
```

खत्म होने पर यह boundary याद रखें: Agentlas Terminal और Agentlas app में आप सीधे
natural language में काम बताएं; native Agentlas/Hephaestus tools context से path
चुनेंगे। Claude Code, Codex, Gemini CLI, Antigravity, Cursor और OpenCode जैसे
external LLM hosts में सिर्फ़ छह explicit commands दिखती हैं: `/hep-build`,
`/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, और `/hep-upload`।
Stormbreaker, research loadouts और lower-level options context से automatically
attach होते हैं। खुद commands चलाना चाहते हैं? नीचे दिया **Quickstart** इस्तेमाल करें।

---

## Quickstart

तीन install paths हैं। अगर आपको पूरा Agentlas runtime चाहिए, तो **1 + 3** इस्तेमाल करें। अगर यह package सीधे Claude Code, Codex या किसी सामान्य project folder में चाहिए, तो **2** इस्तेमाल करें।

| Path | कब इस्तेमाल करें | क्या खोलना है |
|---|---|---|
| 1. Agentlas Terminal | shell से Agentlas agents चलाने के लिए | पहले Agentlas Desktop, फिर macOS Terminal / Windows PowerShell / Linux terminal |
| 2. Standalone Hephaestus | Claude Code, Codex या normal repo में direct install के लिए | Claude Code, Codex या OS terminal |
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

### 2. Hephaestus standalone install करें

#### Simple file install

जिस project folder में package files चाहिए, वहां macOS Terminal, Linux terminal, Windows Git Bash या WSL खोलें:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Windows PowerShell:

```powershell
$zip = "$env:TEMP\hephaestus-main.zip"
$extract = "$env:TEMP\hephaestus-main"
Invoke-WebRequest "https://github.com/agentlas-ai/Hephaestus/archive/refs/heads/main.zip" -OutFile $zip
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
/plugin install hephaestus@agentlas-core-engine
/reload-plugins
/plugin list
```

**`claude` CLI वाले OS terminal में टाइप करें**:

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```

Expected result:

```text
✓ Installed hephaestus. Run /reload-plugins to apply.
Reloaded: 1 plugin · 0 skills · 9 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

#### Codex plugin install

Codex chat के अंदर `/plugin marketplace add` इस्तेमाल न करें। Codex app में installed plugins देखने के लिए `/plugins` है; install OS terminal से करें।

**`codex` CLI वाले OS terminal में टाइप करें**:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus
codex plugin list
codex plugin add hephaestus@agentlas-core-engine
codex plugin list
```

अगर Codex पहले से खुला है, तो नया chat शुरू करें और `/plugins` से plugin दिख रहा है या नहीं देखें। Install के बाद `/prompts:hep-build ontology` चलाएं।

### 3. Agentlas Desktop install करें

browser में खोलें:

```text
https://agentlas.cloud/desktop
```

Desktop आपको visual Agentlas surface देता है: local projects, agents, teams, Apps, vault references, runtime selection, built-in Core Engine Meta-Agent routing और `agentlas` CLI installer।

## तस्वीरों के साथ install guide

अगर आप Claude Code chat के अंदर हैं, तो Claude slash command वाली तस्वीर follow करें। Codex पहले OS terminal से install करें; Codex app में `/plugins` से installed plugins देखें। अगर आपने macOS Terminal, Windows PowerShell, Linux terminal, Git Bash या WSL खोला है, तो CLI वाली तस्वीरें follow करें।

### Claude Code chat

इन commands को सीधे Claude Code में type करें।

![Claude Code chat install flow](assets/install-claude-code-chat.svg)

### OS terminal में Claude CLI

जब आपके shell में `claude` command उपलब्ध हो, तो यह path इस्तेमाल करें।

![Claude CLI install flow](assets/install-claude-cli.svg)

### Codex app plugin browser

OS terminal में `codex plugin ...` install पूरा करने के बाद Codex app में `/plugins` type करके check करें।

![Codex app plugin browser](assets/install-codex-chat.svg)

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
| Installed Codex plugins देखना | Codex app | `/plugins` |
| Codex plugin shell से install | OS terminal | `codex plugin marketplace add ...`, `codex plugin add ...` |

## यह क्या बनाता है

Hephaestus सिर्फ prompt answer नहीं बनाता। यह ऐसा repository छोड़ता है जिसे दूसरा runtime inspect, install, verify और आगे improve कर सके।

| आप क्या मांगते हैं | Route | Output |
|---|---|---|
| "X करने वाला एक agent बनाओ" | `10-single-agent-builder` | skills, memory contracts, runtime adapters और verification वाला single worker |
| "इस workflow के लिए team/company बनाओ" | `20-multi-agent-team-builder` | HQ, PM Soul, Memory Curator, Policy Gate, eval, QA और handoff वाली multi-agent team |
| "इस existing agent/repo/workspace को package करो" | `30-agentlas-packager` | Desktop import, terminal, Codex, Claude, Gemini या public GitHub release के लिए साफ Agentlas package |

## v0.7.25 में नया

- **Self-contained `/hep-upload`।** Cloud/Hub upload अब private local checkout या external publish script पर निर्भर नहीं है; bundled Hephaestus package/publish runtime इस्तेमाल होता है।
- **Hub upload gates bundled हैं।** Marketplace upload से पहले `publicProfile`, `routing-card/2.0`, package hash, static security और bundle size validate होते हैं।
- **Routing-card migration fix।** Auto-migrated cards अब null package hash नहीं भेजते, और bundled meta-agent card `routing_ready` है।

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

| तुलना | उनकी ताकत | Hephaestus क्या जोड़ता है |
|---|---|---|
| OpenAI / Codex | strong models और coding terminal | portable repo contracts, `.agentlas` memory/package files, skills, schemas, runtime adapters, public verification |
| Claude / Claude Code | strong reasoning और Claude-native workflows | Claude support, लेकिन Claude-only नहीं; Codex, Gemini, Desktop, terminal और `AGENTS.md` भी aligned रहते हैं |
| OpenClaw | local identity और workspace agent loop | visible role folders, Agentlas package contracts, public-safety checks, Desktop import, vault references |
| Hermes | persona और memory-centered local runtime | PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, skill lifecycle evidence |

OpenAI और Claude model/runtime surfaces हैं। OpenClaw और Hermes local-agent experiences हैं। Hephaestus agent को portable, inspectable, installable और publishable बनाने वाली package layer है।

## Usage examples

```text
/meta-agent Create a research agent for SEC filing analysis.
Package it for Codex, Claude Code, Gemini, and Agentlas Desktop.
```

```text
Use Hephaestus.
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
