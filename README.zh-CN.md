<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus — 模型无关的 Agent OS</h1>

<p align="center">
  <strong>别再为每个任务重新搭建和配置智能体了。Hephaestus 把专家智能体沉淀在 Hub 里，为每个任务即时生成一个临时编排器。</strong><br>
  本地优先，可搭配任意模型使用 —— Claude Code、Codex、Gemini、Cursor 与本地模型皆可。
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

## 粘贴即安装

把下面内容粘贴到你正在使用的 LLM，例如 Claude Code、Codex、Gemini CLI、Antigravity 或 Cursor：

```text
从这个 GitHub 仓库安装 Hephaestus:
https://github.com/agentlas-ai/Agentlas-OS

把它注册到 plugin marketplace，安装 plugin，并让 Hephaestus plugin 和
commands 从下一次 session 开始可用。如果支持 global routing，也请开启。

最后确认已启用的 plugin、command surface 和 global routing 状态。
```

当你已经在某个 LLM 里，并希望直接启用 Hephaestus 时使用这段内容。
如果要用 shell 手动安装，请查看下面的完整安装方法。

<p align="center">
  <img src="assets/hephaestus-network-mcp-demo.gif" alt="Hephaestus Network 2.0 通过 MCP 实时将任务路由给正确的智能体" width="760">
</p>

<p align="center">
  <sub>从 Hub 调取的专家智能体被组装成临时任务组，通过 MCP 实时路由——无需为每个任务单独配置智能体。</sub>
</p>

<p align="center">
  <a href="#agent-os-时代">Agent OS 时代</a>
  ·
  <a href="#粘贴即安装">粘贴即安装</a>
  ·
  <a href="#全部安装方式">全部安装方式</a>
  ·
  <a href="#命令界面">命令界面</a>
  ·
  <a href="#v110-新特性--简报访谈引擎">v1.1.0 新特性</a>
  ·
  <a href="#os-子系统">子系统</a>
  ·
  <a href="#面向企业构建">企业运营</a>
  ·
  <a href="#构建产物--进程打包">系统打包</a>
  ·
  <a href="#按目标查文档">文档索引</a>
</p>

---

## Agent OS 时代

行业已经越过了无状态、临时拼凑的"带工具的聊天机器人"阶段。随着 Google 与各大 AI 实验室围绕**智能体操作系统（Agent Operating Systems）**（例如 Antigravity 编排平台和 Gemini Spark 守护进程）重塑开发者战略，AI 智能体已正式成为一等操作系统原语——具有独立身份、关系型记忆系统、安全权限和原生工具调用环境的长生命周期有状态进程。

这让团队面临的关键工程问题随之改变：**你的智能体劳动力运行在谁的操作系统上？**

如果你的智能体与单一模型供应商的专有 API 紧耦合，你的组织记忆、自定义工具和面向任务的逻辑实际上就被锁死在该供应商的生态里。

**Hephaestus 是独立的、模型无关的内核。**它不是智能体框架，也不是 API 封装层。它是一个本地优先的 Agent OS——一个统一的执行基底，在任意 LLM 运行时之上编译、调度并治理可移植的智能体进程。更换底层推理引擎，完整保留整个智能体劳动力。

Hephaestus 与经典操作系统概念一一对应：

| OS 抽象 | 在 Hephaestus 中的实现 |
| :--- | :--- |
| **内核 / 策略门（Policy Gate）** | 确定性路由器 + 安全门。每一次路由动作都会生成可审计的回执；工具执行权限被严格沙箱化，由活动运行时强制执行。 |
| **进程 / 线程** | 独立智能体与多智能体团队被编译为包，附带显式的类型化契约（Routing Card、反作用域、记忆边界与验证垫片）。 |
| **进程调度器** | Network 2.0 路由（本地优先、质量门控、基准门控的分发），结合 Stormbreaker 的并行执行织体与只追加的运行日志。 |
| **内存管理（MMU）** | 双边界的受治理记忆：本地项目记忆隔离在本机，持久化晋升由本地 Memory Curator 门控。 |
| **虚拟文件系统** | 生产级 Ontology Runtime：本地优先的源摄取、CJK 三元组 FTS5 搜索、混合倒数排名融合（Reciprocal Rank Fusion）与 GraphRAG 检索。 |
| **进程间调用（IPC）** | A2A Agent Card 边界（加密导入/导出与调用方门控）+ Model Context Protocol（MCP）工具注册。 |
| **包管理器** | Agentlas Hub 与 Cloud：编译、发布、版本化并共享智能体，内置质量门。 |
| **Shell 接口** | 在外部客户端运行时中提供小而统一的命令集；在原生 Agentlas Shell 中按自然语言意图路由。 |
| **进程初始化** | Meta-Agent Factory 集成简报访谈门（Briefing Interview Gate）——先明确智能体参数，再编译代码。 |

<p align="center">
  <img src="assets/agentlas-meta-agent-architecture.svg" alt="Figure 1. Agentlas Meta-Agent architecture decomposition">
</p>

<p align="center">
  <sub>图 1. 请求塑形、三种构建器、生成的包契约、记忆策展、技能生命周期、运行时适配器与同步边界。</sub>
</p>

---

## v1.1.0 新特性 — 简报访谈引擎

由模糊的单句提示生成的智能体，会在真实世界的边界情况下失效。Hephaestus v1.1.0 通过**简报访谈引擎（Briefing Interview Engine）**将任务规格化定位为一等 OS 服务：

*   **量化的歧义门控：** 编译调度器沿四个关键向量（目标、约束、范围、上下文）评估提示的清晰度。在歧义分数越过数值阈值之前（歧义分数 $\le 0.2$，并设有各维度的安全下限），构建流程被严格门控。清晰的提示会经由一套为琐碎任务设定提问上限的预算系统，完全绕过访谈循环。
*   **透镜驱动的系统分析：** 澄清问题从结构化的透镜表（范围、意图、挑战、系统架构）中动态取材，聚焦关键路由指标：*反作用域边界*（智能体绝不能做什么）、*可验证的验收标准*与*退出条件*。
*   **Work Brief：** 已敲定的细节被冻结进 `.agentlas/work-brief.json`——记录经确认的目标、具体约束、带来源标签的假设台账，以及元数据中的歧义分数。
*   **上下文内的在途简报：** CLI 工具 `cards migrate` 会自动把简报细节直接映射到智能体路由卡上的触发器与反触发器。运行 `route --brief` 会把该简报传播到所有 Stormbreaker 执行数据包，确保约束与退出条件在整个生命周期内约束所有并行子进程。
*   **增强的路由判别力：** 通过双侧门控防止同主题/不同意图的碰撞（例如安全智能体截胡部署提示）：路由卡上经访谈验证的反触发器，以及路由器内部低置信度时的 LLM 重排序升级。

---

## 全部安装方式

### 手动安装 LLM Adapter

仅当当前 LLM 无法自行执行设置时使用。它会安装共享的 Hephaestus runner
以及面向受支持 LLM tools 的 command adapters。

```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```
该命令会把中立运行器安装到 `~/.agentlas/runtime/current/bin/hephaestus`，并为 Claude Code、Codex、Gemini CLI、Antigravity 和 Cursor 注册命令适配器。安装器会在注册后逐一验证每个运行时表面。

### 各运行时的插件驱动

<details>
<summary>Claude Code 插件</summary>

在操作系统终端中运行：
```bash
claude plugin marketplace add https://github.com/agentlas-ai/Agentlas-OS --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```
*注：Claude Code 也支持 `claude plugins ...` 作为别名，但本 README 为保持一致，统一使用单数形式的 `claude plugin ...`。*

</details>

<details>
<summary>Codex 插件</summary>

在操作系统终端中运行：
```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.1.12
codex plugin add hephaestus@agentlas-core-engine
```
*注：Codex 应用内不支持 `/plugin marketplace add`，请在操作系统终端中运行上面两条命令。操作系统终端的 CLI 命令为单数形式（`codex plugin`）；在 Codex 应用内，插件浏览器的斜杠命令为复数形式（`/plugins`）。安装完成后，`/prompts:hep-build` 即为应用内入口。*

</details>

<details>
<summary>将文件复制到项目中（手动驱动）</summary>

克隆本仓库，并把 `AGENTS.md`、`agent.md`、`agents/`、`skills/`、`modes/`、`schemas/`、`templates/` 和 `.agentlas/` 复制到你的工作区。运行时目录（`.claude/`、`codex/`、`.gemini/`、`.agents/`）作为同一规范内核之上的适配器工作。

</details>

**直接开口即可：** 安装完成后，在原生 Agentlas 界面中用自然语言说话即可自动路由任务。在外部 LLM tools 中，使用下面列出的显式命令。不清楚有哪些智能体时，先从 `/hep-search` 开始。要连接 Telegram，请在 Claude Code 中使用 `/hep-connect`，或在 Codex 中使用 `/prompts:hep-connect`。

---

## 命令界面

在原生 Agentlas 环境中，Hephaestus 无需任何命令即可运行。外部 LLM tools 使用一组刻意精简的可见命令。Stormbreaker、研究装备（research loadouts）和配置表等系统级设施会根据上下文自动挂载：

| 系统子系统 | Shell 命令 | 示例 |
| :--- | :--- | :--- |
| **进程构建器** | `/hep-build` | `/hep-build create a customer support agent for Shopify refunds` |
| **A2A 调度器** | `/hep-network` | `/hep-network split this launch plan into research, copy, QA, and release agents` |
| **云状态同步** | `/hep-cloud` | `/hep-cloud use my saved finance analyst agent to review this report` |
| **目录搜索** | `/hep-search` | `/hep-search find agents for a market report workflow` |
| **进程间调用（IPC）** | `/hep-call` | `/hep-call market-researcher, report-writer {draft a market report}` |
| **包导出器** | `/hep-upload` | `/hep-upload ./agents/customer-support-hq` |
| **Telegram 设置** | `/hep-connect` 或 `/prompts:hep-connect` | `/hep-connect Telegram for Marketing Agent Team` |

---

## OS 子系统

### Meta-Agent Factory — 进程创建
由三种构建器组成的统一编译工厂。每个生成的包都会注册其全局命令（`.agentlas/global-commands.json`）并附带验证脚本——用户永远不需要去猜编译后的包该怎么运行：

| 编译模式 | 路由目标 | 输出产物 |
| :--- | :--- | :--- |
| **单智能体** | `10-single-agent-builder` | 独立工作者，带本地化技能、记忆契约与运行时适配器。 |
| **多智能体团队** | `20-multi-agent-team-builder` | 层级化团队，包含 PM Orchestrator、Memory Curator、Policy Gate、QA 与校验脚本。 |
| **工作区打包器** | `30-agentlas-packager` | 编译好的捆绑包，可直接用于 runtime 导入、CLI 执行或 GitHub 分发。 |

*简报访谈门：* 构建器通过**简报访谈门**（[docs/builder-interview-research-gate.md](docs/builder-interview-research-gate.md)）启动流程：进行透镜驱动的提问、评估歧义阈值、检索一手来源，并输出 Work Brief。

---

### Network 2.0 — 调度器

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>图 2. A2A 调度：LLM 运行时、本地优先编排器、路由卡、本地记忆，以及 Agentlas Hub 的 A2A/MCP 兜底。</sub>

*   **Routing Card（路由卡）：** 每个智能体、团队和插件都随附一张标准化卡片，包含触发器、反触发器、能力、风险画像与记忆参数。未通过验证的卡片会被排除在路由之外。
*   **本地优先分发：** 分发首先在本地解析（项目覆盖 $\rightarrow$ 本地卡片）。经由 Agentlas Hub 的外部查询会被脱敏为关键词；你的原始提示永远不会离开本地环境。
*   **临时特遣队：** 复合请求会分解为 Hub/本地特遣队计划，打包 Stormbreaker 信封、会话提示与本体路径。被点名的专家会被动态调度，并由一个临时编排器管理任务交接。
*   **回执驱动的执行：** 每个路由决策都会写下回执。路由器只决定调用哪个智能体或包；工具执行权限始终被严格沙箱化，由活动运行时管理。
*   **双语基准测试：** 自动路由由一套双语（韩语 + 英语）基准门控，要求 top-3 召回率 $\ge 90\%$ 且零隐私泄漏。低置信度路径会升级到 runtime 级 Router Agent 重排序。

详情：[docs/hephaestus-network-2.0.md](docs/hephaestus-network-2.0.md) · 运行时支持矩阵：[docs/runtime-fallback-adapters.md](docs/runtime-fallback-adapters.md)

---

### Stormbreaker — 有纪律的执行
Stormbreaker 是这套 Agent OS 的执行门控子系统。它确保在所有结果都通过确定性检查验证之前，智能体既不会上报成功，也不会终止：

```text
Kernel Gating Envelope:
[Scope Lock] -> [Decomposition] -> [Parallel Work Packets] -> [Verify Contracts] -> [Bounded Repair] -> [Final Gate]
```

本地运行日志让长时间执行在中断后可以续跑。执行数据包携带 Work Brief，使反作用域规则与退出标准约束所有并行子进程。Stormbreaker 上报显式的完成状态（**verified / unverified / blocked**），杜绝自主的"完成表演"。

执行协议：[docs/robustness-protocol.md](docs/robustness-protocol.md) · 基准与评测：[docs/robustness-eval.md](docs/robustness-eval.md)

---

### Ontology Runtime — 知识文件系统
对于知识密集型作业，`bin/ontology` 充当语义文件系统，把非结构化的本地文件转换为智能体可读的数据库栈：

```text
Ingested Files -> [Parser Adapter] -> [CJK trigram/bigram tokenization] 
  -> [FTS5 + SQLite Storage] -> [Reciprocal Rank Fusion Ranking] -> [GraphRAG Search]
```

内置第一方韩文文档解析（HWPX 与传统 HWP5），零 GPL 依赖。完全本地化并以 SQLite 为后端；机密与隐私分块被隔离，防止其触及外部云端钩子。

```bash
bin/ontology ingest ./corpus --scope internal
bin/ontology query "Project Helios Memory Curator" --agent verifier
bin/ontology memory candidates
```

详情：[docs/ontology-runtime.md](docs/ontology-runtime.md)

---

### 受治理的记忆 — 策展式晋升
*   **本地项目记忆：** 存储在 `~/.agentlas/networking/` 下并隔离在本机。未经显式授权无法导出。
*   **工作区个性化：** 为借用的 Cloud/Hub 智能体管理个性化日志（摘要、行动手册、插件锁与回执），且不存储原始提示、凭据值或私有文件。
*   **策展人门控：** 技能与记忆修改先以候选状态保留。只有在本地策展人确认留出/重放证明、回滚覆盖与安全策略批准之后，才会晋升为持久状态。

---

### A2A 边界 — 智能体间隔离
标准化的 CLI 命令支持安全的智能体间协同：

```bash
agentlas-cloud ao a2a import ./agent-card.json .
agentlas-cloud ao a2a export . --agent local/10-builder
agentlas-cloud route "run the release check" --caller local/orchestrator .
```
导入以提案的形式生效（限制自动调用），导出会脱敏私有路径与逻辑，且调用在路由解析之前先经调用方门控。

---

## 面向企业构建

企业并不需要又一种编写孤立 Python 智能体的方式，而是需要**运营一支受治理的智能体劳动力**。Hephaestus 正是为这种运营模式而设计的：

*   **模型中立即采购筹码：** 智能体、记忆仓库与知识域都以本地资产的形式存放在你的掌控之下。切换到新的模型供应商（或使用 Ollama、Llama 等本地模型，以及 DeepSeek、GLM、Gemini、Claude 等企业级引擎）只是一次简单的配置更新——而不是一次代码库迁移。
*   **以构造保证的可审计性：** 每个路由决策、执行步骤、记忆候选与策展决策都以文本文件形式记录。你可以对它们做 diff、审计和提交。工作要么已验证，要么被标记为未验证。
*   **确定性的流水线门：** 安全过滤器、反作用域、路由卡触发器与提示净化被硬编码进 OS 流水线——它们不依赖 LLM 系统指令或行为准则。
*   **先规格、后生成：** 简报访谈引擎度量请求的歧义度，并把分数盖章在 Work Brief 上，确保任务执行始终可以回溯审计到当初的约定。
*   **本地优先的数据边界：** 原始文本、文档与数据库文件保留在本地。对外交互经过脱敏且需显式选择加入。

### 框架的位置
CrewAI、LangChain 与各厂商的智能体 SDK 扮演的是**库**的角色——非常适合在单个进程内编写自定义智能体逻辑。Hephaestus 则作为**运行时基底**运作：它跨工作区运行时对智能体进行规格化、打包、路由、运行、审计与迁移。框架代码在 Hephaestus 包内部运行；内核只要求智能体遵守其目录契约与 Routing Card。

---

## 构建产物 — 进程打包

Hephaestus 将智能体打包为标准目录布局，任何工作区运行时都能解析、安装、验证并运行：

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

## 按目标查文档

| 系统目标 | 参考文档 |
|---|---|
| 理解规范路由 | [`AGENTS.md`](AGENTS.md) |
| 查看完整团队契约 | [`agent.md`](agent.md) |
| 架构的单一事实来源 | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| 运行时边界 | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| 简报访谈与研究门 | [`docs/builder-interview-research-gate.md`](docs/builder-interview-research-gate.md) |
| Network 2.0 路由 | [`docs/hephaestus-network-2.0.md`](docs/hephaestus-network-2.0.md) |
| Stormbreaker 协议 | [`docs/robustness-protocol.md`](docs/robustness-protocol.md) |
| Ontology 运行时 | [`docs/ontology-runtime.md`](docs/ontology-runtime.md) |
| 记忆架构 | [`docs/memory-architecture.md`](docs/memory-architecture.md) |
| 技能生命周期晋升 | [`docs/skill-lifecycle-promotion.md`](docs/skill-lifecycle-promotion.md) |
| Cloud 运行时捆绑包 | [`docs/agentlas-cloud-runtime.md`](docs/agentlas-cloud-runtime.md) |
| 验证一个包 | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| 公共安全检查 | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

---

## 公共安全边界

本仓库**不**包含 Agentlas 计费/账户逻辑、生产云凭据、客户数据库、原始私有会话记录、原生钥匙串管理器或私有部署脚本。

由 Hephaestus 编译的公开输出包必须排除本地绝对路径、API 密钥、服务账号密钥、`.env` 机密、原始会话记录、客户日志与私人开发者笔记。

---

## 贡献与验证

在发起 Pull Request 或发布更新之前，请运行验证测试套件：

```bash
scripts/verify-package.sh
scripts/verify-ontology-runtime.sh
scripts/public_safety_check.sh
```

---

## 许可证

Apache-2.0。参见 [LICENSE](LICENSE)。
