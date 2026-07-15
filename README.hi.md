<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus — हर model पर चलने वाला Agent OS</h1>

<p align="center">
  <strong>हर task के लिए नया agent बनाना और configure करना बंद कीजिए। Hephaestus specialist agents को एक hub में रखता है और हर task के लिए एक temporary orchestrator तुरंत बना देता है।</strong><br>
  Local-first, और हर model के साथ चलता है — Claude Code, Codex, Gemini, Cursor तथा local models।
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

## Paste करके install करें

इसे उस LLM में paste करें जिसे आप अभी इस्तेमाल कर रहे हैं, जैसे Claude Code,
Codex, Gemini CLI, Antigravity या Cursor:

```text
इस GitHub repo से Hephaestus install करें:
https://github.com/agentlas-ai/Agentlas-OS

इसे plugin marketplace में register करें, plugin install करें, और अगली session
से Hephaestus plugin और commands काम करें। अगर global routing support है, तो
उसे भी enable करें।

अंत में active plugin, command surface और global routing status confirm करें।
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

## Agent OS का युग

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
  <sub>चित्र 1. Request shaping, तीन builders, generated package contracts, memory curation, skill lifecycle, runtime adapters और sync boundaries।</sub>
</p>

---

## v1.1.0 में नया — Briefing Interview Engine

अस्पष्ट, एक-वाक्य वाले prompts से generate किए गए agents वास्तविक दुनिया के edge cases में विफल हो जाते हैं। Hephaestus v1.1.0, **Briefing Interview Engine** के माध्यम से task specification को एक first-class OS service के रूप में स्थापित करता है:

*   **Quantitative Ambiguity Gates:** Compilation scheduler चार प्रमुख vectors (Goal, Constraints, Scope, Context) पर prompt की स्पष्टता का मूल्यांकन करता है। build process तब तक सख्ती से gated रहती है जब तक ambiguity score एक numeric threshold पार न कर ले (ambiguity score $\le 0.2$, per-dimension safety floors के साथ)। स्पष्ट prompts एक budget system के जरिए interview loop को पूरी तरह bypass कर जाते हैं, जो trivial tasks के लिए प्रश्नों की संख्या सीमित रखता है।
*   **Lens-Driven System Analysis:** स्पष्टीकरण के प्रश्न एक structured lens table (Scope, Intent, Challenge, System Architecture) से गतिशील रूप से लिए जाते हैं, जो critical routing indicators पर केंद्रित है: *anti-scope bounds* (agent को क्या **नहीं** करना है), *verifiable acceptance criteria* और *exit conditions*।
*   **Work Brief:** तय हो चुके विवरण `.agentlas/work-brief.json` में freeze कर दिए जाते हैं — जिसमें validated goal, ठोस constraints, source tags के साथ एक assumption ledger और metadata ambiguity score दर्ज होते हैं।
*   **Contextual In-Flight Briefs:** CLI tool `cards migrate` brief के विवरणों को स्वचालित रूप से agent के routing card के triggers और anti-triggers पर map करता है। `route --brief` चलाने से यह brief सभी Stormbreaker execution packets तक propagate होता है, जिससे पूरे lifecycle में parallel subprocesses पर constraints और exit conditions लागू रहते हैं।
*   **Enhanced Routing Discrimination:** Double-sided gating के जरिए same-topic/different-intent टकराव (जैसे किसी security agent का deployment prompt को intercept कर लेना) रोका जाता है: routing card पर interview-validated anti-triggers, और router के अंदर low-confidence LLM re-ranking escalation।

---

## सभी Install Methods

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
*नोट: Claude Code `claude plugins ...` को alias के रूप में भी सपोर्ट करता है, लेकिन consistency के लिए यह README एकवचन `claude plugin ...` का उपयोग करता है।*

</details>

<details>
<summary>Codex Plugin</summary>

अपने OS terminal से:
```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.1.44
codex plugin add hephaestus@agentlas-core-engine
```
*नोट: Codex ऐप के अंदर `/plugin marketplace add` काम नहीं करता — ऊपर दिए दोनों commands को OS terminal में चलाएँ। OS-terminal CLI command एकवचन है (`codex plugin`); Codex ऐप के अंदर plugin browser का slash command बहुवचन है (`/plugins`)। install के बाद `/prompts:hep-build` in-app entry है।*

</details>

<details>
<summary>फ़ाइलें Project में कॉपी करें (Manual Driver)</summary>

Repo को clone करें और `AGENTS.md`, `agent.md`, `agents/`, `skills/`, `modes/`, `schemas/`, `templates/` तथा `.agentlas/` को अपने workspace में copy करें। Runtime folders (`.claude/`, `codex/`, `.gemini/`, `.agents/`) उसी canonical core पर adapters के रूप में काम करते हैं।

</details>

**बस बात कीजिए:** Installation के बाद native Agentlas interfaces में plain language में बोलें — tasks अपने-आप route हो जाते हैं। External LLM tools में नीचे दिए गए explicit commands का उपयोग करें। जब पता न हो कि कौन-से agents मौजूद हैं, तो `/hep-search` से शुरू करें। Telegram connect करने के लिए Claude Code में `/hep-connect` या Codex में `/prompts:hep-connect` use करें।

---

## कमांड सरफेस

Native Agentlas environments के अंदर Hephaestus commandless चलता है। External LLM tools जान-बूझकर छोटा रखा गया visible command set उपयोग करते हैं। Stormbreaker, research loadouts और configuration tables जैसी system-level utilities context से अपने-आप जुड़ जाती हैं:

| सिस्टम सबसिस्टम | Shell Command | उदाहरण |
| :--- | :--- | :--- |
| **Process Builder** | `/hep-build` | `/hep-build create a customer support agent for Shopify refunds` |
| **A2A Scheduler** | `/hep-network` | `/hep-network split this launch plan into research, copy, QA, and release agents` |
| **Cloud State Sync** | `/hep-cloud` | `/hep-cloud use my saved finance analyst agent to review this report` |
| **Directory Search** | `/hep-search` | `/hep-search find agents for a market report workflow` |
| **Inter-Process Call (IPC)** | `/hep-call` | `/hep-call market-researcher, report-writer {draft a market report}` |
| **Package Exporter** | `/hep-upload` | `/hep-upload ./agents/customer-support-hq` |
| **Telegram Setup** | `/hep-connect` या `/prompts:hep-connect` | `/hep-connect Telegram for Marketing Agent Team` |

---

## OS सबसिस्टम

### Meta-Agent Factory — Process निर्माण
तीन builders का उपयोग करने वाली एक unified compilation factory। हर generated package अपना global command (`.agentlas/global-commands.json`) register करता है और verification scripts के साथ ship होता है — user को कभी अनुमान नहीं लगाना पड़ता कि compiled package कैसे चलाना है:

| Compilation Mode | Routing Target | Output Artifact |
| :--- | :--- | :--- |
| **Single-Agent** | `10-single-agent-builder` | Localized skills, memory contracts और runtime adapters के साथ standalone worker। |
| **Multi-Agent Team** | `20-multi-agent-team-builder` | PM Orchestrator, Memory Curator, Policy Gate, QA और validation scripts वाली hierarchical team। |
| **Workspace Packager** | `30-agentlas-packager` | runtime import, CLI execution या GitHub distribution के लिए तैयार compiled bundle। |

*Briefing Interview Gate:* Builders प्रक्रिया की शुरुआत **briefing interview gate** ([docs/builder-interview-research-gate.md](docs/builder-interview-research-gate.md)) से करते हैं: lens-driven प्रश्न पूछना, ambiguity threshold का मूल्यांकन करना, primary sources खोजना, और work brief output करना।

---

### Network 2.0 — Scheduler

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>चित्र 2. A2A scheduling: LLM runtimes, local-first orchestrator, routing cards, local memory और Agentlas Hub A2A/MCP fallback।</sub>

*   **Routing Cards:** हर agent, team और plugin एक standardized card के साथ ship होता है, जिसमें triggers, anti-triggers, capabilities, risk profiles और memory parameters होते हैं। verification में विफल cards routing से बाहर कर दिए जाते हैं।
*   **Local-First Dispatch:** Dispatch पहले locally resolve होता है (project overrides $\rightarrow$ local cards)। Agentlas Hub के जरिए बाहरी lookups keywords तक redact किए जाते हैं; आपके raw prompts कभी आपके local environment से बाहर नहीं जाते।
*   **Temporary Task Forces:** Composite requests Hub/local Task Force plans में decompose होती हैं — Stormbreaker envelopes, session hints और ontology pathways के साथ pack होकर। Named specialists गतिशील रूप से schedule होते हैं, और एक temporary orchestrator task handoffs संभालता है।
*   **Receipt-Driven Execution:** हर routing decision एक receipt लिखता है। router केवल यह तय करता है कि किस agent या package को invoke करना है; tool execution permissions सख्ती से sandboxed रहती हैं और active runtime द्वारा manage की जाती हैं।
*   **Bilingual Benchmarking:** Auto-routing एक bilingual (Korean + English) benchmark से gated है, जिसमें top-3 recall $\ge 90\%$ और शून्य privacy leaks अनिवार्य हैं। Low-confidence paths runtime-level Router Agent re-ranking तक escalate होते हैं।

विवरण: [docs/hephaestus-network-2.0.md](docs/hephaestus-network-2.0.md) · Runtime support matrix: [docs/runtime-fallback-adapters.md](docs/runtime-fallback-adapters.md)

---

### Stormbreaker — अनुशासित Execution
Stormbreaker इस Agent OS का execution gating subsystem है। यह सुनिश्चित करता है कि agents तब तक success रिपोर्ट न करें या terminate न हों, जब तक सभी outcomes deterministic checks से verify न हो जाएँ:

```text
Kernel Gating Envelope:
[Scope Lock] -> [Decomposition] -> [Parallel Work Packets] -> [Verify Contracts] -> [Bounded Repair] -> [Final Gate]
```

एक local run journal लंबे executions को रुकावट के बाद resumable बनाता है। Execution packets अपने साथ Work Brief लेकर चलते हैं, ताकि anti-scope नियम और exit criteria सभी parallel subprocesses पर लागू रहें। Stormbreaker स्पष्ट completion states (**verified / unverified / blocked**) रिपोर्ट करता है, ताकि autonomous completion theater न होने पाए।

Execution protocol: [docs/robustness-protocol.md](docs/robustness-protocol.md) · Benchmarks & Evals: [docs/robustness-eval.md](docs/robustness-eval.md)

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

विवरण: [docs/ontology-runtime.md](docs/ontology-runtime.md)

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

## एंटरप्राइज के लिए निर्मित

Enterprises को isolated Python agents लिखने का एक और तरीका नहीं चाहिए। उन्हें ऐसे agents का **governed workforce संचालित** करना है। Hephaestus विशेष रूप से इसी operational model के लिए डिज़ाइन किया गया है:

*   **Procurement Leverage के रूप में Model Neutrality:** Agents, memory repositories और knowledge domains आपके नियंत्रण में local assets के रूप में संग्रहीत रहते हैं। किसी नए model provider पर जाना (या Ollama, Llama जैसे local models और DeepSeek, GLM, Gemini या Claude जैसे enterprise engines का उपयोग) एक साधारण configuration update है — codebase migration नहीं।
*   **निर्माण से ही Auditability:** हर routing decision, execution step, memory candidate और curator decision एक text file के रूप में log होता है। आप उन्हें diff, audit और commit कर सकते हैं। काम या तो verified होता है या unverified के रूप में flag किया जाता है।
*   **Deterministic Pipeline Gates:** Security filters, anti-scopes, routing card triggers और prompt sanitizations OS pipeline में hardcoded हैं — वे LLM system instructions या guidelines पर निर्भर नहीं करते।
*   **Generation से पहले Specification:** Briefing Interview Engine request की ambiguity मापता है और score को Work Brief पर stamp करता है, जिससे task execution का audit हमेशा उसी पर वापस ले जाया जा सके जो तय हुआ था।
*   **Local-First Data Boundary:** Raw text, documents और database files local रहते हैं। External transactions redacted और opt-in होते हैं।

### Frameworks कहाँ फिट होते हैं
CrewAI, LangChain और vendor agent SDKs **libraries** की तरह काम करते हैं — किसी single process के अंदर custom agent logic लिखने के लिए बेहतरीन। Hephaestus **runtime substrate** के रूप में काम करता है: यह workspace runtimes के आर-पार agents को specify, package, route, run, audit और migrate करता है। Framework code Hephaestus packages के अंदर चलता है; kernel केवल इतना माँगता है कि agents अपने directory contracts और Routing Cards का पालन करें।

---

## यह क्या बनाता है (Process Packaging)

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
└── docs/                              # Briefing records, tool specifications,
                                       # and prompt contracts
```

---

## लक्ष्य के अनुसार Docs

| सिस्टम लक्ष्य | संदर्भ दस्तावेज़ |
|---|---|
| Canonical route को समझें | [`AGENTS.md`](AGENTS.md) |
| पूरा team contract देखें | [`agent.md`](agent.md) |
| Architecture का source of truth | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| Runtime सीमाएँ | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| Briefing interview और research gate | [`docs/builder-interview-research-gate.md`](docs/builder-interview-research-gate.md) |
| Network 2.0 routing | [`docs/hephaestus-network-2.0.md`](docs/hephaestus-network-2.0.md) |
| Stormbreaker protocol | [`docs/robustness-protocol.md`](docs/robustness-protocol.md) |
| Canonical Goal + UltraCode harness | [`docs/stormbreaker-goal-ultracode-harness.md`](docs/stormbreaker-goal-ultracode-harness.md) |
| Ontology runtime | [`docs/ontology-runtime.md`](docs/ontology-runtime.md) |
| Memory आर्किटेक्चर | [`docs/memory-architecture.md`](docs/memory-architecture.md) |
| Experience और Taste assets | [`docs/agent-experience-assets.md`](docs/agent-experience-assets.md) |
| MCP build resolution | [`docs/mcp-build-resolution.md`](docs/mcp-build-resolution.md) |
| Model allocation | [`docs/model-allocation.md`](docs/model-allocation.md) |
| Skill lifecycle promotion | [`docs/skill-lifecycle-promotion.md`](docs/skill-lifecycle-promotion.md) |
| Cloud runtime bundles | [`docs/agentlas-cloud-runtime.md`](docs/agentlas-cloud-runtime.md) |
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
