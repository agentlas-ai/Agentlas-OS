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
     global-router step are in the install section below. Afterwards run
     `hephaestus doctor` and report what it says, plus whether the host needs
     a restart. -->

<p align="center"><a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for macOS" src="https://img.shields.io/badge/Download-macOS-000000?style=for-the-badge&logo=apple&logoColor=white"></a> <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for Windows" src="https://img.shields.io/badge/Download-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white"></a> <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for Linux" src="https://img.shields.io/badge/Download-Linux-333333?style=for-the-badge&logo=linux&logoColor=white"></a></p>
<p align="center"><sub><strong>Agentlas Desktop</strong> · <a href="https://agentlas.cloud/desktop">agentlas.cloud/desktop</a></sub></p>

<h1 align="center">Agentlas OS</h1>

<p align="center">
  <strong>आपका headhunter. काम को specialist टीम चाहिए, तो वह ले आता है।</strong><br>
  <sub>Claude Code, Codex, Cursor और Antigravity के भीतर वैसे ही चलता है।</sub>
</p>

<p align="center">
  आप जो भी कर रहे हों, सही specialists अपने आप संगठित हो जाएँ तो कैसा हो।<br>
  service बनाना शुरू करते ही frontend और backend specialist खुद आपके पास आ जाएँ तो कैसा हो।<br>
  जिस काम में accounting भी आनी चाहिए और marketing भी करनी है — क्या एक अकेला agent वह कर सकता है?
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

**Agentlas Hub एक निःशुल्क एजेंट समुदाय है।** सार्वजनिक एजेंट प्रकाशित या कॉल करने के लिए कीमत, लीज़ या Agentlas क्रेडिट खरीदना आवश्यक नहीं है। कॉल करने वाला अपना मॉडल और API उपयोग करता है; सदस्यता Agentlas सॉफ़्टवेयर और होस्टेड सुविधाओं के लिए है। नई Hub गतिविधि पर क्रिएटर सेटलमेंट बंद है; मौजूदा बैलेंस और पुराने दावे लागू खाता शर्तों के अनुसार संभाले जाते हैं।

### Install

**Agentlas OS** — इस मशीन के Claude Code, Codex, Antigravity, Cursor और बाकी hosts के लिए। <code>sudo</code> नहीं, <code>$HOME</code> के बाहर कुछ नहीं लिखा जाता। Install के बाद अपना agent host restart करें और <code>hephaestus doctor</code> चलाएँ।

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

**Agentlas Desktop** — terminal की जगह window पसंद हो तो यह app।

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash        # macOS · Linux
```

```powershell
irm https://agentlas.cloud/install.ps1 | iex               # Windows PowerShell
```

<p align="center"><sub>नवीनतम हस्ताक्षरित रिलीज़ डाउनलोड करता है, उसका sha512 जाँचता है, और बिना <code>sudo</code> या एडमिन अनुमति के इंस्टॉल करता है · <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest">मैन्युअल रूप से डाउनलोड करें</a> · <a href="https://github.com/agentlas-ai/agentlas-desktop">Agentlas Desktop ओपन सोर्स है — रिपॉज़िटरी देखें</a></sub></p>

<details>
<summary><strong>Desktop और Agentlas OS एक साथ</strong></summary>

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash -s -- --with-engine
```

```powershell
$env:AGENTLAS_WITH_ENGINE="1"; irm https://agentlas.cloud/install.ps1 | iex
```

</details>

---

## जो कोई platform नहीं कर पाता

कोई भी agent platform सैकड़ों-हज़ारों agents को कुशलता से route नहीं कर पाता। किसी भी काम पर हर क्षेत्र के specialists को **सबसे कम tokens में** एक टीम के रूप में लगाने वाली जगह सिर्फ़ Agentlas है।

यह इसलिए संभव है क्योंकि agent का spec और agent को बुलाने का protocol, दोनों मानकीकृत हैं।

- **A2A v1.0, जैसा लिखा है वैसा।** Agent cards मानक पथ `/.well-known/agent-card.json` पर पढ़े और लिखे जाते हैं। Import, export और caller gating सब मानक पर टिके हैं। कोई बाहरी agent तभी बुलाया जा सकता है जब उसकी capability aligned हो **और हस्ताक्षरित card से उसकी पहचान सत्यापित हो।**
- **एक task, 20 candidates: 40,873B → 10,087B.** candidates घटाए नहीं गए — पंक्ति compress की गई। सही agent के सूची में होने की संभावना वही रहती है, tokens एक-चौथाई रह जाते हैं।
- ये आँकड़े **849 local profiles** और **188 प्रकाशित listings** पर मापे गए हैं।

## यहीं अधिकांश tools रुक जाते हैं

|  | task विभाजन नहीं | task विभाजन है |
| --- | --- | --- |
| **specialist sourcing नहीं** | एक chat पूरा हिस्सा संभालता है | वही model, अलग prompt |
| **specialist sourcing है** | store से एक चुनकर इस्तेमाल | **Agentlas** |

कुछ tools काम बाँटते ज़रूर हैं। पर हर task जो संभालता है वह वही model होता है, बस prompt बदला हुआ। कुछ जगहें specialists बेचती भी हैं। पर वहाँ विभाजन नहीं है — आप एक चुनते हैं और इस्तेमाल करते हैं।

**कहीं और बँटा हुआ task वह prompt है जो आपने लिखा। यहाँ वह एक नौकरी का विज्ञापन है।**
हर task एक साथ आपकी मशीन, आपके private cloud और सार्वजनिक Hub तक जाता है।

---

## तीन चरण

<table>
<tr>
<td width="44%" valign="middle">

### 1. Task विभाजन

एक वाक्य जाता है, tasks निकलते हैं — भूमिकाएँ, handoff का क्रम, और हर एक को क्या देना है।

जिस org chart में review पिछले task पर लौटता हो, वह **कुछ भी चलने से पहले अस्वीकार** हो जाता है, और loop का नाम बता दिया जाता है।

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-build-pipeline.gif" alt="request को tasks में बाँटने की स्क्रीन" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 2. Agent staffing

हर task के लिए candidates लौटते हैं — आपकी मशीन, आपके cloud और सार्वजनिक Hub से एक साथ।

**सूची में कोई ranking नहीं है।** चुनाव आपका model करता है, और कारण दर्ज होता है।

योग्यता चार स्तरों में है: `declared`, `checked`, `demonstrated`, `attested` — और हर task पर न्यूनतम स्तर तय किया जा सकता है। चुनते ही वह release digest से pin हो जाता है, इसलिए कल एक byte भी बदला तो run रुक जाता है।

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-make-group-v2.gif" alt="हर task पर specialist agent लगाने की स्क्रीन" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 3. चलाना और सत्यापन

योजना, काम, संश्लेषण और सत्यापन — हर एक अलग invocation के रूप में चलता है।

**जब तक एक स्वतंत्र verifier पास न करे, कुछ भी पूरा नहीं कहलाता।** हर invocation, हर handoff और संश्लेषण receipt से सिद्ध होने चाहिए। वरना आपको वह जगह नाम से मिलती है जहाँ यह रुका — `prepared`, `blocked`, `source_unavailable`।

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-run-v2.gif" alt="चलाने और सत्यापन की स्क्रीन" width="100%"></a>
</td>
</tr>
</table>

---

## अपना specialist ख़ुद बनाइए

सूची में कोई फ़िट न हो, तो एक बना लीजिए। `/hep-build` एक वाक्य को portable single agent या team में बदल देता है: सिर्फ़ वही सवाल पूछता है जो नतीजा बदलें, package लिखता है, और काम पूरा कहने से पहले contract checks चलाता है। `/hep-build session` यही काम उस बातचीत से करता है जिसमें आप अभी हैं।

```text
/hep-build an agent that reviews App Store replies before they go out
/hep-build session
```

हर build input और output schemas, routing card और नीचे दिए package contract की बाकी फ़ाइलें साथ देता है; कोई ज़रूरी फ़ाइल छूटे तो build ship होने की जगह fail होता है। `/hep-upload` से इसे अपने private Agent Cloud में रखें या free Hub पर publish करें, फिर `/hep-network` इसे किसी भी दूसरे candidate की तरह staff कर सकता है।

---

## जो सवाल शायद आपके मन में हैं

<details open>
<summary><strong>आख़िर में आप ही एक की सिफ़ारिश कर देते हैं, है ना?</strong></summary>

<br>

agents बेचने वाली हर जगह उन्हें rank करती है। कमाई का तरीका यही है। लोग ऊपर वाले पर click करते हैं, और ऊपर कौन आएगा यह वह कंपनी तय करती है।

हम ranking बनाते ही नहीं। schema `allowHistoryEvidence` को स्थिरांक `false` पर pin करता है, और जो source scored सूची लौटाए उसका **पूरा उत्तर अस्वीकार** कर दिया जाता है।

Ratings, install counts, पिछले महीने की बिक्री — हम इनमें से कुछ नहीं पढ़ते। candidates जैसे हैं वैसे मिलते हैं, और चुनाव आपका model करता है।

</details>

<details>
<summary><strong>क्या यह सिर्फ़ developers के लिए है?</strong></summary>

<br>

नहीं। role ontology में backend, security और QA के साथ-साथ **insurance actuary, M&A diligence lead, underwriting diligence specialist और travel planner** भी हैं।

अकेले insurance के चार क्षेत्र हैं। सूची से बाहर के क्षेत्र भी रोके नहीं जाते।

</details>

---

## हमने अपना ही विचार जोड़ा, फिर हटा दिया

हमने publisher के अपने लिखे "मुझे तब बुलाइए…" वाक्यों को ranking signal की तरह आज़माया। सही agent के पहले स्थान पर आने का अनुपात **73.1% से गिरकर 57.0%** हो गया। हमने हटा दिया। अब वे वाक्य सूची के अंत में तीन सीटें भर आरक्षित करते हैं — सूची से न हटाए जाने का अधिकार, rank बदलने का अधिकार नहीं।

हिंदी में पूछने पर सही agent **144वें** स्थान पर आया। वही सवाल अंग्रेज़ी में पूछने पर **पहले**। इसलिए work order अंग्रेज़ी में लिखा जाता है, और deliverable की भाषा एक अलग field है।

10, 20, 30 और 50 candidates दिखाने पर सही वाला सूची में **73, 83, 87 और 93%** बार आया। डिफ़ॉल्ट 30 है।

---

## Agentlas Desktop पर

Desktop खुद host है, इसलिए run शुरू होने से **पहले** ही code तय कर लेता है कि काम एक agent से बनेगा या टीम चाहिए। वह निर्णय सुझाव नहीं, एक आरक्षित run के रूप में दर्ज होता है। यह इंस्टॉल किए हुए agents के साथ सार्वजनिक Hub agents को भी काम में लगा सकता है। सार्वजनिक Hub agents को बुलाने पर Agentlas शुल्क नहीं लगता; चुने हुए host या model/API provider के शुल्क अलग से लग सकते हैं।

| Surface | भूमिका |
| --- | --- |
| **Agentlas OS (Hephaestus)** | यह repo — CLI hosts के लिए open-source build और routing engine तथा command surface |
| **Agentlas Desktop** | वही engine window के साथ चलाने वाला app (macOS · Windows · Linux) |
| **Agentlas Hub** | agents को मुफ़्त में publish, discover और use करने की public जगह |
| **Agentlas Cloud** | अपने agents को private रूप से रखने और फिर निकालने के लिए owner-scoped store |

---

## Install: सभी तरीक़े, और यह क्या लिखता है

इसे उस LLM में paste करें जिसे आप अभी इस्तेमाल कर रहे हैं, जैसे Claude Code,
Codex, Antigravity या Cursor:

```text
इस GitHub repo से Hephaestus install करें:
https://github.com/agentlas-ai/Agentlas-OS

सिर्फ marketplace plugin install करके न रुकें। अगली session में भी बने रहने वाले
host command adapters लिखने के लिए repo का canonical one-touch installer चलाएँ:
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash

installer के अपने verification output की report दें। अगली session में
`/agentlas build` (या उस host के बराबर command surface) काम नहीं करता, तो
install complete report न करें; काम करने की पुष्टि होने पर host restart या
plugin reload करने को कहें।
```

जब आप पहले से किसी LLM के अंदर हों और Hephaestus वहीं active करना चाहते हों,
तो इसे use करें। shell से manual install के लिए नीचे install methods देखें।

<p align="center">
  <img src="assets/hephaestus-network-mcp-demo.gif" alt="Hephaestus Network 2.0, MCP के जरिए एक task को सही agent पर live route करते हुए" width="760">
</p>

<p align="center">
  <sub>Hub से लाए गए specialist agents एक temporary task force में जुड़ते हैं और MCP के जरिए live route होते हैं — हर task के लिए अलग agent setup की जरूरत नहीं।</sub>
</p>

<p align="center">
  <a href="#agent-os-का-युग">Agent OS का युग</a>
  ·
  <a href="#paste-करके-install-करें">Paste करके install करें</a>
  ·
  <a href="#सभी-install-methods">सभी Install Methods</a>
  ·
  <a href="#कमांड-सरफेस">कमांड सरफेस</a>
  ·
  <a href="#v110-में-नया--briefing-interview-engine">v1.1.0 में नया</a>
  ·
  <a href="#os-सबसिस्टम">सबसिस्टम</a>
  ·
  <a href="#एंटरप्राइज-के-लिए-निर्मित">एंटरप्राइज ऑपरेशंस</a>
  ·
  <a href="#यह-क्या-बनाता-है-process-packaging">सिस्टम पैकेजिंग</a>
  ·
  <a href="#लक्ष्य-के-अनुसार-docs">Docs रजिस्ट्री</a>
</p>

---


<details>
<summary><strong>सभी Install Methods — source, offline, host-wise</strong></summary>


### Manual LLM Adapter Install

इसे केवल तब इस्तेमाल करें जब current LLM खुद setup नहीं चला सकता। यह shared
Hephaestus runner और supported LLM tools के command adapters install करता है।

```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```
यह neutral runner को `~/.agentlas/runtime/current/bin/hephaestus` पर install करता है और Claude Code, Codex, Antigravity, Cursor, OpenCode, OpenClaw, Hermes, Kimi Code CLI, goose तथा GitHub Copilot CLI के लिए command, skill या MCP adapters, और Grok के लिए memory hooks register करता है। Local models MCP entrypoint `hephaestus mcp serve` इस्तेमाल करते हैं। installer registration के बाद हर runtime surface को verify करता है।

### प्रति-Runtime Plugin Drivers

<details>
<summary>Claude Code Plugin</summary>

अपने OS terminal से:
```bash
claude plugin marketplace add https://github.com/agentlas-ai/Agentlas-OS --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```
*नोट: Claude Code marketplace plugin commands को हमेशा namespace देता है, इसलिए
इस plugin-only path में command `/hephaestus:agentlas` है। हर नई session में
documented bare `/agentlas build` autocomplete के लिए ऊपर का one-touch installer
इस्तेमाल करें; यह `~/.claude/commands/agentlas.md` भी लिखता है। Claude Code
`claude plugins ...` alias भी support करता है, लेकिन यह README एकवचन
`claude plugin ...` उपयोग करता है।*

</details>

<details>
<summary>Codex Plugin</summary>

अपने OS terminal से:
```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.2.69
codex plugin add hephaestus@agentlas-core-engine
```
*नोट: Codex ऐप के अंदर `/plugin marketplace add` काम नहीं करता — ऊपर दिए दोनों commands को OS terminal में चलाएँ। OS-terminal CLI command एकवचन है (`codex plugin`); Codex ऐप के अंदर plugin browser का slash command बहुवचन है (`/plugins`)। Codex 0.117+ में custom `/prompts:*` commands हटा दिए गए; install के बाद plugin skill को `$hephaestus-network <request>` से बुलाएँ।*

</details>

<details>
<summary>फ़ाइलें Project में कॉपी करें (Manual Driver)</summary>

Repo को clone करें और `AGENTS.md`, `agent.md`, `agents/`, `skills/`, `modes/`, `schemas/`, `templates/` तथा `.agentlas/` को अपने workspace में copy करें। Runtime folders (`.claude/`, `codex/`, `antigravity/`, `.agents/`) उसी canonical core पर adapters के रूप में काम करते हैं।

</details>

**बस बात कीजिए:** Installation के बाद native Agentlas interfaces में plain language में बोलें — tasks अपने-आप route हो जाते हैं। External LLM tools में नीचे दिए गए explicit commands का उपयोग करें। जब पता न हो कि कौन-से agents मौजूद हैं, तो `/agentlas search` से शुरू करें।

---

</details>


<details>
<summary><strong>कमांड सरफेस — सभी commands</strong></summary>


Native Agentlas environments के अंदर Hephaestus commandless चलता है। External LLM tools जान-बूझकर छोटा रखा गया visible command set उपयोग करते हैं। ये commands agents बनाने और उन्हीं से काम staff करने के लिए हैं:

| सिस्टम सबसिस्टम | Shell Command | उदाहरण |
| :--- | :--- | :--- |
| **Process Builder** | `/agentlas build` | `/agentlas build create a customer support agent for Shopify refunds` |
| **Workforce Federation (Local + Cloud + Hub)** | `/agentlas network` | `/agentlas network split this launch plan into research, copy, QA, and release agents` |
| **केवल registered Local agents** | `/agentlas local` | `/agentlas local use only agents registered on this machine` |
| **केवल owned Cloud agents** | `/agentlas cloud` | `/agentlas cloud use my saved finance analyst agent to review this report` |
| **केवल public Hub agents** | `/agentlas hub` | `/agentlas hub find public specialists for accessibility QA` |
| **Directory Search** | `/agentlas search` | `/agentlas search find agents for a market report workflow` |
| **Inter-Process Call (IPC)** | `/agentlas call` | `/agentlas call market-researcher, report-writer {draft a market report}` |
| **Package Exporter** | `/agentlas upload` | `/agentlas upload ./agents/customer-support-hq` |

हर कमांड अपने मूल नाम `/hep-*` से भी काम करती है। `/agentlas network` और
`/hep-network` एक ही कमांड हैं। कोई नाम हटाया नहीं गया है, इसलिए मौजूदा
स्क्रिप्ट, नोट्स और आपकी आदत सब वैसे ही चलते रहेंगे।


---

</details>


<details>
<summary><strong>और गहराई में — build factory और routing scheduler</strong></summary>


### Meta-Agent Factory — Process निर्माण
चार builders का उपयोग करने वाली एक unified compilation factory। हर generated package अपना global command (`.agentlas/global-commands.json`) register करता है और verification scripts के साथ ship होता है — user को कभी अनुमान नहीं लगाना पड़ता कि compiled package कैसे चलाना है:

| Compilation Mode | Routing Target | Output Artifact |
| :--- | :--- | :--- |
| **Single-Agent** | `10-single-agent-builder` | Localized skills, memory contracts और runtime adapters के साथ standalone worker। |
| **Multi-Agent Team** | `20-multi-agent-team-builder` | PM Orchestrator, Memory Curator, Policy Gate, QA और validation scripts वाली hierarchical team। |
| **Workspace Packager** | `30-agentlas-packager` | runtime import, CLI execution या GitHub distribution के लिए तैयार compiled bundle। |
| **Session Agent Builder** | `40-session-agent-builder` | मौजूदा बातचीत (headless runs में explicit JSON/JSONL export) को owner-reviewed agent में बदलता है; default single agent है, team तभी जब आप चुनें। |

*Briefing Interview Gate:* Builders प्रक्रिया की शुरुआत **briefing interview gate** से करते हैं: lens-driven प्रश्न पूछना, ambiguity threshold का मूल्यांकन करना, primary sources खोजना, और work brief output करना।

---

### Network 2.0 — Scheduler

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>चित्र 2. A2A scheduling: LLM runtimes, local-first orchestrator, routing cards, local memory और Agentlas Hub A2A/MCP fallback।</sub>

*   **Typed Job Analysis:** Active host LLM request को roles, skills, tools, artifacts, authority, cardinality और handoffs वाले redacted `WorkOrder` में बदलता है। Core substring lists से staffing intent का अनुमान नहीं लगाता।
*   **Exact Source Federation:** `local`, `cloud` और `hub` exact single scopes हैं; `network` उनका sealed union है। हर source bounded content-only menu लौटाता है, और failure पर Core चुपचाप किसी दूसरे scope तक नहीं फैलता।
*   **Host-Owned Task Force:** Host LLM qualification evidence पढ़कर exact `Selection` लिखता है। Core deterministic winner या hidden Router Agent re-ranking नहीं करता; वह केवल governance, privacy, identity, cardinality और graph integrity validate करता है।
*   **Pinned Execution:** Validation के बाद Core original source session से केवल selected immutable releases लाता है, release/package/content digests जाँचता है, फिर planner, worker, synthesis और verifier को अलग invocations में चलाता है।
*   **Evidence-Scored Evaluation:** Retrieval coverage, host selection, immutable preparation, real child invocations और final verification अलग claims के रूप में score होते हैं। Benchmark या usage history host staffing decision की जगह नहीं लेते।


---

</details>


<details>
<summary><strong>यह क्या बनाता है — process packaging</strong></summary>


Hephaestus agents को एक standard directory layout में package करता है, जिसे कोई भी workspace runtime parse, install, verify और run कर सकता है। नीचे का layout वही है जो `package-contract.json` माँगता है और `hephaestus contract verify` जाँचता है:

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

`docs/`, eval plan और work brief सिर्फ user-confirmed minimal private build में छोड़े जा सकते हैं। `provenance.json`, `knowledge/`, `schemas/`, `sandbox/` और `examples/` optional हैं।

---

</details>

## लक्ष्य के अनुसार Docs

| सिस्टम लक्ष्य | संदर्भ दस्तावेज़ |
|---|---|
| Canonical route को समझें | [`AGENTS.md`](AGENTS.md) |
| पूरा team contract देखें | [`agent.md`](agent.md) |
| Package contract | [`package-contract.json`](package-contract.json) |
| Session build | [`contracts/session-build.md`](contracts/session-build.md) |
| Routing card | [`schemas/routing-card.schema.json`](schemas/routing-card.schema.json) |
| Workforce work order | [`schemas/workforce-work-order.schema.json`](schemas/workforce-work-order.schema.json) |
| Compiled brief | [`schemas/agentlas-brief.schema.json`](schemas/agentlas-brief.schema.json) |

---

## सार्वजनिक सुरक्षा सीमा

इस repository में Agentlas billing/account logic, production cloud credentials, customer databases, raw private transcripts, native keychain managers या private deployment scripts **शामिल नहीं** हैं।

Hephaestus द्वारा compile किए गए public output packages में local absolute paths, API keys, service-account keys, `.env` secrets, raw transcripts, customer logs या private developer notes शामिल नहीं होने चाहिए।

---

## लाइसेंस

Apache-2.0। देखें: [LICENSE](LICENSE)।
