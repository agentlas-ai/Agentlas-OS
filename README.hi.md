<!-- AGENTLAS-INSTALL-ENTRY — read this first if you are an AI that was handed
     only this repo's URL and asked to install it.

       curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash

     One line, no sudo, nothing written outside $HOME. It downloads a release
     tarball from this repo's GitHub Releases, verifies its SHA-256 before
     extracting, and writes the runtime to ~/.agentlas, wrappers to
     ~/.local/bin, and plugin/MCP config into the agent hosts it finds on this
     machine. The installer is meant to be read:
     scripts/install-all-runtimes.sh. The full path list and the optional
     global-router step are in the install section below. Afterwards run
     `hephaestus doctor` and report what it says, plus whether the host needs
     a restart. -->

<p align="center"><a href="https://agentlas.cloud/studio"><img src="assets/readme/agentlas-one-launch-film-v2.gif" alt="Agentlas One launch film" width="720"></a></p>
<p align="center"><a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for macOS" src="https://img.shields.io/badge/Download-macOS-000000?style=for-the-badge&logo=apple&logoColor=white"></a> <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for Windows" src="https://img.shields.io/badge/Download-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white"></a> <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for Linux" src="https://img.shields.io/badge/Download-Linux-333333?style=for-the-badge&logo=linux&logoColor=white"></a></p>
<p align="center"><sub><strong>Agentlas Desktop</strong> · <a href="https://agentlas.cloud/desktop">agentlas.cloud/desktop</a></sub></p>

<h1 align="center">Agentlas OS</h1>

<p align="center">
  <strong>आपका headhunter. काम को specialist टीम चाहिए, तो वह ले आता है।</strong><br>
  <sub>Claude Code, Codex, Cursor और Gemini के भीतर वैसे ही चलता है।</sub>
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
  <img alt="hosts" src="https://img.shields.io/badge/Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20%7C%20Cursor%20%7C%20Antigravity%20%7C%20Local-black">
  <img alt="ranking" src="https://img.shields.io/badge/ranking-none%20by%20design-blue">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.zh-CN.md">中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.hi.md">हिन्दी</a>
</p>

**Agentlas Hub एक निःशुल्क एजेंट समुदाय है।** सार्वजनिक एजेंट प्रकाशित या कॉल करने के लिए कीमत, लीज़ या Agentlas क्रेडिट खरीदना आवश्यक नहीं है। कॉल करने वाला अपना मॉडल और API उपयोग करता है; सदस्यता Agentlas सॉफ़्टवेयर और होस्टेड सुविधाओं के लिए है। नई Hub गतिविधि पर क्रिएटर सेटलमेंट बंद है; मौजूदा बैलेंस और पुराने दावे लागू खाता शर्तों के अनुसार संभाले जाते हैं।

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

<p align="center">
  <sub>एक लाइन। <code>sudo</code> नहीं। <code>$HOME</code> के बाहर कुछ नहीं लिखता।<br>इसके बाद अपना AI टूल दोबारा शुरू करें और <code>hephaestus doctor</code> चलाएँ।</sub>
</p>

<p align="center">
  <a href="https://agentlas.cloud/desktop">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Desktop लें">
  </a>
</p>

<p align="center">
  <sub>terminal के बजाय एक window · macOS · Windows · Linux · <a href="https://agentlas.cloud/desktop">agentlas.cloud/desktop</a></sub>
</p>

---

## जो कोई platform नहीं कर पाता

कोई भी agent platform सैकड़ों-हज़ारों agents को कुशलता से route नहीं कर पाता। किसी भी काम पर हर क्षेत्र के specialists को **सबसे कम tokens में** एक टीम के रूप में लगाने वाली जगह सिर्फ़ Agentlas है।

यह इसलिए संभव है क्योंकि agent का spec और agent को बुलाने का protocol, दोनों मानकीकृत हैं।

- **A2A v1.0, जैसा लिखा है वैसा।** Agent cards मानक पथ `/.well-known/agent-card.json` पर पढ़े और लिखे जाते हैं। Import, export और caller gating सब मानक पर टिके हैं। कोई बाहरी agent तभी बुलाया जा सकता है जब उसकी capability aligned हो **और हस्ताक्षरित card से उसकी पहचान सत्यापित हो।**
- **एक task, 20 candidates: 40,873B → 10,087B.** candidates घटाए नहीं गए — पंक्ति compress की गई। सही agent के सूची में होने की संभावना वही रहती है, tokens एक-चौथाई रह जाते हैं।
- ये आँकड़े **849 local profiles** और **188 प्रकाशित listings** पर मापे गए हैं।

और जो specialist आता है, खाली हाथ नहीं आता। code map, sitemap और project की memory task के साथ ही चलती है। कौन-सी फ़ाइलें दायरे में हैं, पहले क्या पढ़ना है, काम सचमुच पूरा हुआ या नहीं — यह सब staffing से पहले गणना करके साथ सौंपा जाता है। कुछ tools अकेले memory बेचते हैं; यहाँ memory staffing, execution और verification से जुड़ा एक पुर्ज़ा भर है।

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

<p align="center">
  <a href="https://agentlas.cloud/desktop">
    <img src="assets/readme/agentlas-desktop-hero-v2.png" alt="Agentlas Desktop workspace" width="880">
  </a>
</p>

<h2 align="center">Desktop पर और असरदार</h2>

Desktop खुद host है, इसलिए run शुरू होने से **पहले** ही code तय कर लेता है कि काम एक agent से बनेगा या टीम चाहिए। वह निर्णय सुझाव नहीं, एक आरक्षित run के रूप में दर्ज होता है। यह सिर्फ़ उन्हीं agents को लगाता है जो आपने पहले से install किए हैं, और पैसे वाली बाहरी मदद बुलाने से पहले हमेशा पूछता है।

आप जितने LLM इस्तेमाल करते हैं, सब एक जगह: जिन coding CLIs की आप पहले से subscription लेते हैं (Claude Code, Codex, Antigravity/Gemini, Cursor, Grok, Kimi), 11 providers की आपकी अपनी API keys, और local models भी। एक हस्ताक्षर-सत्यापित llama.cpp engine साथ आता है, Hugging Face से GGUF models लाता है, और LM Studio तथा MLX से भी जुड़ता है।

**और जिस model पर आप हैं उसका quota ख़त्म हो जाए, तो वह turn आपकी अपनी priority के अगले model पर दोबारा चलाया जाता है।** आपका सहेजा हुआ model चुनाव नहीं बदलता, और limit हटते ही मूल model अपने आप लौट आता है।

<p align="center">
  <strong><a href="https://agentlas.cloud/desktop">Agentlas Desktop लें →</a></strong><br>
  <sub>macOS (Apple silicon · Intel) · Windows · Linux</sub>
</p>

| सतह | भूमिका |
| --- | --- |
| **Agentlas Desktop** | agent teams, memory, browser काम और Hub specialists के लिए स्थानीय visual OS |
| **Hephaestus plugin** | यही repo — CLI hosts के लिए open-source engine और command surface |
| **Agentlas Hub** | specialists प्रकाशित करने और उधार लेने की सार्वजनिक सतह |
| **Agentlas Cloud** | अपने बनाए agents को निजी तौर पर रखने और वापस लाने का owner-only store |

---

<h2 align="center">एक लाइन से शुरू करें</h2>

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

<p align="center">
  <sub>यह installer <strong>इस मशीन पर मिले हर supported host</strong> को configure करता है, सिर्फ़ उसे नहीं जिसमें आप अभी टाइप कर रहे हैं। यह क्या और कहाँ लिखता है, नीचे पूरा दिया है।</sub>
</p>

---

## Install: सभी तरीक़े, और यह क्या लिखता है

इसे उस LLM में paste करें जिसे आप अभी इस्तेमाल कर रहे हैं, जैसे Claude Code,
Codex, Gemini CLI, Antigravity या Cursor:

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
<summary><strong>अंदर क्या है — routing, permissions, memory, retrieval, packaging</strong></summary>


इंडस्ट्री अब stateless, ad-hoc "tools वाले chatbots" से आगे निकल चुकी है। Google और प्रमुख AI labs द्वारा developer रणनीतियों को **Agent Operating Systems** (जैसे Antigravity orchestration platform और Gemini Spark daemon processes) के इर्द-गिर्द पुनर्परिभाषित करने के साथ, AI agents आधिकारिक रूप से first-class operating-system primitives बन चुके हैं — विशिष्ट पहचान, relational memory systems, security permissions और native tool-calling environments वाली long-lived, stateful processes।

इससे टीमों के लिए महत्वपूर्ण इंजीनियरिंग प्रश्न बदल जाता है: **आपका workforce किसके operating system पर चलता है?**

यदि आपके agents किसी एक model provider के proprietary API से कसकर जुड़े (tightly coupled) हैं, तो आपकी organizational memory, custom tools और task-specific logic प्रभावी रूप से उस vendor के ecosystem में lock हो जाते हैं।

**Hephaestus एक स्वतंत्र kernel है, जो किसी एक model से बंधा नहीं है।** यह कोई agent framework या API wrapper नहीं है। यह एक local-first Agent Operating System है — एक unified execution substrate, जो portable agent processes को किसी भी LLM runtime पर compile, schedule और govern करता है। नीचे का reasoning engine बदल दीजिए; पूरा workforce जस-का-तस सुरक्षित रहता है।

Hephaestus classical operating system अवधारणाओं से सीधे map होता है:

| OS Abstraction | Hephaestus में कार्यान्वयन |
| :--- | :--- |
| **Kernel / Policy Gate** | Deterministic router + security gates। हर routing action एक auditable receipt उत्पन्न करता है; tool execution permissions सख्ती से sandboxed हैं और active runtime द्वारा लागू की जाती हैं। |
| **Processes / Threads** | स्पष्ट, typed contracts (Routing Cards, anti-scopes, memory boundaries और verification shims) के साथ packages के रूप में compile किए गए स्वतंत्र agents और multi-agent teams। |
| **Process Scheduler** | Network 2.0 routing (local-first, quality-gated और benchmark-gated dispatch), जो Stormbreaker के parallel execution fabric और append-only run journals के साथ जुड़ा है। |
| **Memory Management (MMU)** | Two-boundary governed memory: local project memory मशीन पर isolated रहती है, जबकि durable promotions एक local Memory Curator द्वारा gate किए जाते हैं। |
| **Virtual File System** | Production Ontology Runtime: local-first source ingestion, CJK trigram FTS5 search, hybrid Reciprocal Rank Fusion और GraphRAG retrieval। |
| **Inter-Process Call (IPC)** | A2A Agent Card Boundary (cryptographic import/export और caller-gating) + Model Context Protocol (MCP) tool registrations। |
| **Package Manager** | Agentlas Hub & Cloud: built-in quality gates के साथ agents को compile, publish, version और share करें। |
| **Shell Interface** | External client runtimes में छोटा, unified command set; native Agentlas shells में plain-language intent routing। |
| **Process Initialization** | Integrated Briefing Interview Gate के साथ Meta-Agent Factory — code compile करने से पहले agent parameters को specify करना। |

<p align="center">
  <img src="assets/agentlas-meta-agent-architecture.svg" alt="Figure 1. Agentlas Meta-Agent architecture decomposition">
</p>

<p align="center">
  <sub>चित्र 1. Request shaping, चार builders, generated package contracts, memory curation, skill lifecycle, runtime adapters और sync boundaries।</sub>
</p>

---

</details>


<details>
<summary><strong>Briefing Interview Engine</strong></summary>


अस्पष्ट, एक-वाक्य वाले prompts से generate किए गए agents वास्तविक दुनिया के edge cases में विफल हो जाते हैं। Hephaestus v1.1.0, **Briefing Interview Engine** के माध्यम से task specification को एक first-class OS service के रूप में स्थापित करता है:

*   **Quantitative Ambiguity Gates:** Compilation scheduler चार प्रमुख vectors (Goal, Constraints, Scope, Context) पर prompt की स्पष्टता का मूल्यांकन करता है। build process तब तक सख्ती से gated रहती है जब तक ambiguity score एक numeric threshold पार न कर ले (ambiguity score $\le 0.2$, per-dimension safety floors के साथ)। स्पष्ट prompts एक budget system के जरिए interview loop को पूरी तरह bypass कर जाते हैं, जो trivial tasks के लिए प्रश्नों की संख्या सीमित रखता है।
*   **Lens-Driven System Analysis:** स्पष्टीकरण के प्रश्न एक structured lens table (Scope, Intent, Challenge, System Architecture) से गतिशील रूप से लिए जाते हैं, जो critical routing indicators पर केंद्रित है: *anti-scope bounds* (agent को क्या **नहीं** करना है), *verifiable acceptance criteria* और *exit conditions*।
*   **Work Brief:** तय हो चुके विवरण `.agentlas/work-brief.json` में freeze कर दिए जाते हैं — जिसमें validated goal, ठोस constraints, source tags के साथ एक assumption ledger और metadata ambiguity score दर्ज होते हैं।
*   **Contextual In-Flight Briefs:** CLI tool `cards migrate` brief के विवरणों को स्वचालित रूप से agent के routing card के triggers और anti-triggers पर map करता है। `route --brief` चलाने से यह brief सभी Stormbreaker execution packets तक propagate होता है, जिससे पूरे lifecycle में parallel subprocesses पर constraints और exit conditions लागू रहते हैं।
*   **Enhanced Routing Discrimination:** Double-sided gating के जरिए same-topic/different-intent टकराव (जैसे किसी security agent का deployment prompt को intercept कर लेना) रोका जाता है: routing card पर interview-validated anti-triggers, और router के अंदर low-confidence LLM re-ranking escalation।

---

</details>


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
यह neutral runner को `~/.agentlas/runtime/current/bin/hephaestus` पर install करता है और Claude Code, Codex, Gemini CLI, Antigravity तथा Cursor के लिए command adapters register करता है। installer registration के बाद हर runtime surface को verify करता है।

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
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.2.49
codex plugin add hephaestus@agentlas-core-engine
```
*नोट: Codex ऐप के अंदर `/plugin marketplace add` काम नहीं करता — ऊपर दिए दोनों commands को OS terminal में चलाएँ। OS-terminal CLI command एकवचन है (`codex plugin`); Codex ऐप के अंदर plugin browser का slash command बहुवचन है (`/plugins`)। install के बाद `/prompts:agentlas` in-app entry है।*

</details>

<details>
<summary>फ़ाइलें Project में कॉपी करें (Manual Driver)</summary>

Repo को clone करें और `AGENTS.md`, `agent.md`, `agents/`, `skills/`, `modes/`, `schemas/`, `templates/` तथा `.agentlas/` को अपने workspace में copy करें। Runtime folders (`.claude/`, `codex/`, `.gemini/`, `.agents/`) उसी canonical core पर adapters के रूप में काम करते हैं।

</details>

**बस बात कीजिए:** Installation के बाद native Agentlas interfaces में plain language में बोलें — tasks अपने-आप route हो जाते हैं। External LLM tools में नीचे दिए गए explicit commands का उपयोग करें। जब पता न हो कि कौन-से agents मौजूद हैं, तो `/agentlas search` से शुरू करें। Telegram connect करने के लिए Claude Code में `/agentlas connect` या Codex में `/prompts:agentlas` use करें।

---

</details>


<details>
<summary><strong>कमांड सरफेस — सभी commands</strong></summary>


Native Agentlas environments के अंदर Hephaestus commandless चलता है। External LLM tools जान-बूझकर छोटा रखा गया visible command set उपयोग करते हैं। Stormbreaker, research loadouts और configuration tables जैसी system-level utilities context से अपने-आप जुड़ जाती हैं:

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
| **Telegram Setup** | `/agentlas connect` या `/prompts:agentlas` | `/agentlas connect Telegram for Marketing Agent Team` |

हर कमांड अपने मूल नाम `/hep-*` से भी काम करती है। `/agentlas network` और
`/hep-network` एक ही कमांड हैं। कोई नाम हटाया नहीं गया है, इसलिए मौजूदा
स्क्रिप्ट, नोट्स और आपकी आदत सब वैसे ही चलते रहेंगे।


---

</details>


<details>
<summary><strong>और गहराई में — routing scheduler, execution gate, memory, retrieval engine</strong></summary>


### Meta-Agent Factory — Process निर्माण
चार builders का उपयोग करने वाली एक unified compilation factory। हर generated package अपना global command (`.agentlas/global-commands.json`) register करता है और verification scripts के साथ ship होता है — user को कभी अनुमान नहीं लगाना पड़ता कि compiled package कैसे चलाना है:

| Compilation Mode | Routing Target | Output Artifact |
| :--- | :--- | :--- |
| **Single-Agent** | `10-single-agent-builder` | Localized skills, memory contracts और runtime adapters के साथ standalone worker। |
| **Multi-Agent Team** | `20-multi-agent-team-builder` | PM Orchestrator, Memory Curator, Policy Gate, QA और validation scripts वाली hierarchical team। |
| **Workspace Packager** | `30-agentlas-packager` | runtime import, CLI execution या GitHub distribution के लिए तैयार compiled bundle। |
| **Session Agent Builder** | `40-session-agent-builder` | Explicitly exported sessions को reviewed single-agent या multi-agent team package में बदलता है। |

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

### Stormbreaker — अनुशासित Execution
Stormbreaker इस Agent OS का execution gating subsystem है। यह सुनिश्चित करता है कि agents तब तक success रिपोर्ट न करें या terminate न हों, जब तक सभी outcomes deterministic checks से verify न हो जाएँ:

```text
Kernel Gating Envelope:
[Scope Lock] -> [Decomposition] -> [Parallel Work Packets] -> [Verify Contracts] -> [Bounded Repair] -> [Final Gate]
```

एक local run journal लंबे executions को रुकावट के बाद resumable बनाता है। Execution packets अपने साथ Work Brief लेकर चलते हैं, ताकि anti-scope नियम और exit criteria सभी parallel subprocesses पर लागू रहें। Stormbreaker स्पष्ट completion states (**verified / unverified / blocked**) रिपोर्ट करता है, ताकि autonomous completion theater न होने पाए।


---

### Ontology Runtime — Knowledge Filesystem
Knowledge-intensive operations के लिए `bin/ontology` semantic filesystem की तरह काम करता है, जो unstructured local files को agent-readable database stack में बदल देता है:

```text
Ingested Files -> [Parser Adapter] -> [CJK trigram/bigram tokenization] 
  -> [FTS5 + SQLite Storage] -> [Reciprocal Rank Fusion Ranking] -> [GraphRAG Search]
```

इसमें first-party Korean document parsing (HWPX और legacy HWP5) शामिल है, बिना किसी GPL dependency के। पूरी तरह local और SQLite-backed; confidential और private chunks isolated रहते हैं, जिससे वे external cloud hooks तक नहीं पहुँच पाते।

```bash
bin/ontology ingest ./corpus --scope internal
bin/ontology query "Project Helios Memory Curator" --agent verifier
bin/ontology memory candidates
```


---

### Governed Memory — Curated Promotion
*   **Local Project Memory:** `~/.agentlas/networking/` के अंतर्गत संग्रहीत और local मशीन तक isolated। स्पष्ट authorization के बिना इसे export नहीं किया जा सकता।
*   **Workspace Personalization:** Borrowed Cloud/Hub agents के लिए personalization logs (summaries, playbooks, plugin locks और receipts) manage करता है — raw prompts, credential values या private files को store किए बिना।
*   **Curator Gating:** Skills और memory modifications candidates के रूप में रखे जाते हैं। इन्हें durable status पर तभी promote किया जाता है जब एक local curator holdout/replay proofs, rollback coverage और security policy approvals की पुष्टि कर दे।

---

### A2A Boundary — Inter-Agent Isolation
Standardized CLI commands सुरक्षित inter-agent coordination संभव बनाते हैं:

```bash
agentlas-cloud ao a2a import ./agent-card.json .
agentlas-cloud ao a2a export . --agent local/10-builder
agentlas-cloud route "run the release check" --caller local/orchestrator .
```
Import एक proposal की तरह काम करता है (automatic invocation को सीमित करते हुए), export private paths और logic को redact करता है, और routing resolve होने से पहले invocations caller-gated होते हैं।

---

</details>


<details>
<summary><strong>यह क्या बनाता है — process packaging</strong></summary>


Hephaestus agents को एक standard directory layout में package करता है, जिसे कोई भी workspace runtime parse, install, verify और run कर सकता है:

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
```

---

</details>

## लक्ष्य के अनुसार Docs

| सिस्टम लक्ष्य | संदर्भ दस्तावेज़ |
|---|---|
| Canonical route को समझें | [`AGENTS.md`](AGENTS.md) |
| पूरा team contract देखें | [`agent.md`](agent.md) |
| Package verify करें | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| Public safety check | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

---

## सार्वजनिक सुरक्षा सीमा

इस repository में Agentlas billing/account logic, production cloud credentials, customer databases, raw private transcripts, native keychain managers या private deployment scripts **शामिल नहीं** हैं।

Hephaestus द्वारा compile किए गए public output packages में local absolute paths, API keys, service-account keys, `.env` secrets, raw transcripts, customer logs या private developer notes शामिल नहीं होने चाहिए।

---

## योगदान और सत्यापन

Pull request खोलने या updates publish करने से पहले verification test suite चलाएँ:

```bash
scripts/verify-package.sh
scripts/verify-ontology-runtime.sh
scripts/verify-experience-assets-contract.sh
scripts/public_safety_check.sh
```

---

## लाइसेंस

Apache-2.0। देखें: [LICENSE](LICENSE)।
