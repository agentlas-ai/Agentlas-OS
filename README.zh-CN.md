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
  <strong>你的猎头。工作需要专家团队时，它把人带来。</strong><br>
  <sub>在 Claude Code、Codex、Cursor、Antigravity 里直接运行。</sub>
</p>

<p align="center">
  如果不管你在做什么，合适的专家都会自己组织起来，会怎么样。<br>
  如果你一开始做服务，前端专家和后端专家就主动找上门，会怎么样。<br>
  既要懂会计又要做营销的活儿，一个智能体做得了吗？
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

**Agentlas Hub 是免费的智能体社区。**发布和调用公开智能体无需设定售价、租赁或购买 Agentlas 积分。调用者使用自己的模型和 API；订阅针对 Agentlas 软件和托管功能。新的 Hub 活动不再产生创作者结算，既有账户余额及历史请求依适用账户条款处理。

### 安装

**Agentlas OS** — 装进本机的 Claude Code、Codex、Antigravity、Cursor 等宿主。无需 <code>sudo</code>，不会写入 <code>$HOME</code> 之外的任何位置。安装后重启你的智能体宿主并运行 <code>hephaestus doctor</code>。

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

**Agentlas Desktop** — 想要窗口而不是终端时，安装这个应用。

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash        # macOS · Linux
```

```powershell
irm https://agentlas.cloud/install.ps1 | iex               # Windows PowerShell
```

<p align="center"><sub>下载最新签名版本并校验 sha512,无需 <code>sudo</code> 或管理员权限即可安装 · <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest">手动下载</a> · <a href="https://github.com/agentlas-ai/agentlas-desktop">Agentlas Desktop 是开源的 — 查看仓库</a></sub></p>

<details>
<summary><strong>同时安装 Desktop 和 Agentlas OS</strong></summary>

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash -s -- --with-engine
```

```powershell
$env:AGENTLAS_WITH_ENGINE="1"; irm https://agentlas.cloud/install.ps1 | iex
```

</details>

---

## 没有平台做得到的事

没有哪个智能体平台能高效路由成百上千个智能体。**用最少的 token** 把各领域专家编成团队派上任何一份工作的，只有 Agentlas。

这件事之所以成立，是因为智能体规格和调用智能体的协议都被标准化了。

- **A2A v1.0，照规范实现。** 智能体卡片在标准路径 `/.well-known/agent-card.json` 读写。导入、导出、调用方校验全部建在标准之上。外部智能体只有在能力对齐**且身份经签名卡片验证**后才可调用。
- **一个任务、20 个候选：40,873B → 10,087B。** 不是减少候选，而是压缩每一行。正确智能体出现在名单里的概率不变，token 降到四分之一。
- 这些数字测自 **849 个本地档案**与 **188 条已发布条目**。

## 大多数工具停在这里

|  | 没有任务拆分 | 有任务拆分 |
| --- | --- | --- |
| **没有专家调度** | 一个聊天整块处理 | 同一个模型，换个提示词 |
| **有专家调度** | 从商店里挑一个用 | **Agentlas** |

有些工具确实会拆分工作。但接下每个任务的，是同一个模型换了提示词。也有地方在卖专家。但那里没有拆分——你只能挑一个来用。

**在别处，拆出来的任务是你写的提示词。在这里，它是一则招聘启事。**
每个任务同时投向你的本机、你的私有云和公开 Hub。

---

## 三个步骤

<table>
<tr>
<td width="44%" valign="middle">

### 1. 任务拆分

一句话进去，任务出来——角色、交接顺序，以及每个角色要交付的产物。

一份让评审指回上游任务的组织图会**在任何东西运行之前被驳回**，并告诉你环在哪里。

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-build-pipeline.gif" alt="请求被拆分为任务的界面" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 2. 智能体编组

每个任务都会返回候选——同时来自你的本机、你的云和公开 Hub。

**名单没有排名。** 选择的是你的模型，理由会被记录。

资质分四级：`declared`、`checked`、`demonstrated`、`attested`，每个任务都能设下限。选定的那一刻该版本即按摘要锁定，明天差一个字节就会停机。

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-make-group-v2.gif" alt="为每个任务编入专家智能体的界面" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 3. 执行与验证

规划、干活、汇总、验证各自作为独立调用运行。

**必须由独立验证者放行才算完成。** 每次调用、每次交接和汇总都要有回执证明。否则你拿到的是它停下的地方——`prepared`、`blocked`、`source_unavailable`。

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-run-v2.gif" alt="执行与验证界面" width="100%"></a>
</td>
</tr>
</table>

---

## 自己打造专家

名单里没有合适的人，就自己打造一个。`/hep-build` 把一句话变成可移植的单智能体或团队：只问会改变结果的问题，写出包，并在宣布完成之前跑完契约检查。`/hep-build session` 则用你正在进行的对话做同样的事。

```text
/hep-build an agent that reviews App Store replies before they go out
/hep-build session
```

每次构建都会交出输入/输出 schema、路由卡，以及下文包契约里的其余文件；缺少任何必需文件的构建会直接失败，而不是发布出去。用 `/hep-upload` 把它存进私有 Agent Cloud 或发布到免费 Hub，之后 `/hep-network` 就能像对待其他候选一样编组它。

---

## 你大概会问

<details open>
<summary><strong>说到底还是你们替我推荐吧？</strong></summary>

<br>

每个卖智能体的地方都在给它们排名。那是他们赚钱的方式。人们点靠前的，而谁靠前由那家公司决定。

我们不建排名。schema 把 `allowHistoryEvidence` 钉死为常量 `false`，返回带分数名单的来源会被**整份拒绝**。

评分、安装数、上月销量——我们一个都不读。候选原样交给你，由你的模型来选。

</details>

<details>
<summary><strong>这只给开发者用吗？</strong></summary>

<br>

不是。角色本体里，除了后端、安全和 QA，还有**保险精算师、并购尽调负责人、核保尽调专家和旅行规划师**。

光保险就有四个领域。清单之外的领域也不会被挡住。

</details>

---

## 我们加过自己的点子，又把它删了

我们试过把发布者自己写的「什么时候该叫我」句子当作排名信号。正确智能体排第一的比例从 **73.1% 掉到 57.0%**。我们删了。现在那些句子只在名单末尾预留三个位置——不被删掉的权利，而非改变排名的权力。

用中文提问时，正确的智能体排在 **第 144 位**。同一个问题用英文问，排 **第 1 位**。所以工单用英文书写，交付物的语言是另一个字段。

展示 10、20、30、50 个候选时，正确答案出现在名单里的比例分别是 **73、83、87、93%**。默认值是 30。

---

## 在 Agentlas Desktop 上

Desktop 本身就是宿主，所以它在运行开始**之前**就用代码决定：这份工作一个人够，还是需要一支团队。那个决定会被记成一次预留的运行，而不是一条建议。它可以编入已安装的智能体，也可以调用公开 Hub 的智能体。调用公开 Hub 智能体不收取 Agentlas 费用，但所选宿主或模型、API 服务商可能另行收费。

| 界面 | 作用 |
| --- | --- |
| **Agentlas OS (Hephaestus)** | 本仓库——面向 CLI 宿主的开源构建与路由引擎及命令界面 |
| **Agentlas Desktop** | 用窗口运行同一引擎的应用（macOS · Windows · Linux） |
| **Agentlas Hub** | 免费发布、发现和使用智能体的公开空间 |
| **Agentlas Cloud** | 私密保存并再次取回自己智能体的所有者专属仓库 |

---

## 安装：所有方式，以及它写了什么

把下面内容粘贴到你正在使用的 LLM，例如 Claude Code、Codex、Antigravity 或 Cursor：

```text
从这个 GitHub 仓库安装 Hephaestus:
https://github.com/agentlas-ai/Agentlas-OS

不要只安装 marketplace plugin 就停止。请运行仓库的标准一键安装器，
同时写入可在下一次 session 中继续使用的 host command adapters：
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash

请报告安装器自身的验证输出。如果下一次 session 中 `/agentlas build`
（或该 host 对应的 command surface）无法使用，不要报告安装完成；确认可用后，
提示我重启 host 或重新加载 plugin。
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


<details>
<summary><strong>全部安装方式 — 源码·离线·分宿主</strong></summary>


### 手动安装 LLM Adapter

仅当当前 LLM 无法自行执行设置时使用。它会安装共享的 Hephaestus runner
以及面向受支持 LLM tools 的 command adapters。

```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```
该命令会把中立运行器安装到 `~/.agentlas/runtime/current/bin/hephaestus`，并为 Claude Code、Codex、Antigravity、Cursor、OpenCode、OpenClaw、Hermes、Kimi Code CLI、goose 和 GitHub Copilot CLI 注册命令、技能或 MCP 适配器，并为 Grok 安装记忆钩子。本地模型使用 MCP 入口 `hephaestus mcp serve`。安装器会在注册后逐一验证每个运行时表面。

### 各运行时的插件驱动

<details>
<summary>Claude Code 插件</summary>

在操作系统终端中运行：
```bash
claude plugin marketplace add https://github.com/agentlas-ai/Agentlas-OS --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```
*注：Claude Code 会始终为 marketplace plugin command 添加 namespace，
因此仅使用此 plugin 安装路径时，命令是 `/hephaestus:agentlas`。若要在每个
新 session 中使用文档里的 bare `/agentlas build` 自动补全，请使用上面的一键
安装器；它还会写入 `~/.claude/commands/agentlas.md`。Claude Code 也支持
`claude plugins ...` 别名，但本 README 统一使用单数形式的
`claude plugin ...`。*

</details>

<details>
<summary>Codex 插件</summary>

在操作系统终端中运行：
```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.2.64
codex plugin add hephaestus@agentlas-core-engine
```
*注：Codex 应用内不支持 `/plugin marketplace add`，请在操作系统终端中运行上面两条命令。操作系统终端的 CLI 命令为单数形式（`codex plugin`）；在 Codex 应用内，插件浏览器的斜杠命令为复数形式（`/plugins`）。Codex 0.117+ 已移除自定义 `/prompts:*` 命令；安装后请用 `$hephaestus-network <request>` 调用插件技能。*

</details>

<details>
<summary>将文件复制到项目中（手动驱动）</summary>

克隆本仓库，并把 `AGENTS.md`、`agent.md`、`agents/`、`skills/`、`modes/`、`schemas/`、`templates/` 和 `.agentlas/` 复制到你的工作区。运行时目录（`.claude/`、`codex/`、`antigravity/`、`.agents/`）作为同一规范内核之上的适配器工作。

</details>

**直接开口即可：** 安装完成后，在原生 Agentlas 界面中用自然语言说话即可自动路由任务。在外部 LLM tools 中，使用下面列出的显式命令。不清楚有哪些智能体时，先从 `/agentlas search` 开始。

---

</details>


<details>
<summary><strong>命令界面 — 全部命令</strong></summary>


在原生 Agentlas 环境中，Hephaestus 无需任何命令即可运行。外部 LLM tools 使用一组刻意精简的可见命令。这些命令用来构建智能体，并用它们编组工作：

| 系统子系统 | Shell 命令 | 示例 |
| :--- | :--- | :--- |
| **进程构建器** | `/agentlas build` | `/agentlas build create a customer support agent for Shopify refunds` |
| **Workforce 联合（Local + Cloud + Hub）** | `/agentlas network` | `/agentlas network split this launch plan into research, copy, QA, and release agents` |
| **仅已注册的 Local 智能体** | `/agentlas local` | `/agentlas local use only agents registered on this machine` |
| **仅本人 Cloud 智能体** | `/agentlas cloud` | `/agentlas cloud use my saved finance analyst agent to review this report` |
| **仅公开 Hub 智能体** | `/agentlas hub` | `/agentlas hub find public specialists for accessibility QA` |
| **目录搜索** | `/agentlas search` | `/agentlas search find agents for a market report workflow` |
| **进程间调用（IPC）** | `/agentlas call` | `/agentlas call market-researcher, report-writer {draft a market report}` |
| **包导出器** | `/agentlas upload` | `/agentlas upload ./agents/customer-support-hq` |

每条命令仍可使用原名 `/hep-*`。`/agentlas network` 与 `/hep-network` 是同一条
命令。旧名称并未移除，因此现有脚本、笔记和使用习惯都不受影响。


---

</details>


<details>
<summary><strong>更深一层 — 构建工厂与路由调度</strong></summary>


### Meta-Agent Factory — 进程创建
由四种构建器组成的统一编译工厂。每个生成的包都会注册其全局命令（`.agentlas/global-commands.json`）并附带验证脚本——用户永远不需要去猜编译后的包该怎么运行：

| 编译模式 | 路由目标 | 输出产物 |
| :--- | :--- | :--- |
| **单智能体** | `10-single-agent-builder` | 独立工作者，带本地化技能、记忆契约与运行时适配器。 |
| **多智能体团队** | `20-multi-agent-team-builder` | 层级化团队，包含 PM Orchestrator、Memory Curator、Policy Gate、QA 与校验脚本。 |
| **工作区打包器** | `30-agentlas-packager` | 编译好的捆绑包，可直接用于 runtime 导入、CLI 执行或 GitHub 分发。 |
| **会话智能体构建器** | `40-session-agent-builder` | 把当前对话（无头运行时则为明确的 JSON/JSONL 导出）变成经所有者审查的智能体；默认是单智能体，只有你选择团队时才生成团队。 |

*简报访谈门：* 构建器通过**简报访谈门**启动流程：进行透镜驱动的提问、评估歧义阈值、检索一手来源，并输出 Work Brief。

---

### Network 2.0 — 调度器

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>图 2. A2A 调度：LLM 运行时、本地优先编排器、路由卡、本地记忆，以及 Agentlas Hub 的 A2A/MCP 兜底。</sub>

*   **类型化岗位分析：** 当前宿主 LLM 将请求整理为脱敏的 `WorkOrder`，明确角色、技能、工具、产物、权限、人数与交接关系。Core 不通过子字符串列表猜测人员需求。
*   **精确来源联合：** `local`、`cloud`、`hub` 都是精确的单一范围，`network` 是三者封存后的并集。每个来源只返回有上限的 content-only 菜单；来源失败时 Core 不会悄悄扩展到其他范围。
*   **由宿主组建特遣队：** 宿主 LLM 阅读资格证据并编写精确的 `Selection`。Core 不选择确定性赢家，也不进行隐藏的 Router Agent 重排序；它只验证治理、隐私、身份、人数与图结构完整性。
*   **固定身份执行：** 验证后，Core 仅从原始来源会话获取已选的不可变发布，核对发布、包与内容摘要，再分别调用规划、执行、综合和验证角色。
*   **基于证据的评估：** 检索覆盖、宿主选择、不可变准备、真实子调用与最终验证分别计分。基准结果或使用历史不会取代宿主的人力配置判断。


---

</details>


<details>
<summary><strong>构建产物 — 进程打包</strong></summary>


Hephaestus 将智能体打包为标准目录布局，任何工作区运行时都能解析、安装、验证并运行。下面的布局就是 `package-contract.json` 所要求、`hephaestus contract verify` 所检查的内容：

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

`docs/`、评估计划和工作简报只有在用户确认的最小私有构建中才可以省略。`provenance.json`、`knowledge/`、`schemas/`、`sandbox/` 和 `examples/` 是可选的。

---

</details>

## 按目标查文档

| 系统目标 | 参考文档 |
|---|---|
| 理解规范路由 | [`AGENTS.md`](AGENTS.md) |
| 查看完整团队契约 | [`agent.md`](agent.md) |
| 包契约 | [`package-contract.json`](package-contract.json) |
| 会话构建 | [`contracts/session-build.md`](contracts/session-build.md) |
| 路由卡 | [`schemas/routing-card.schema.json`](schemas/routing-card.schema.json) |
| Workforce 工作单 | [`schemas/workforce-work-order.schema.json`](schemas/workforce-work-order.schema.json) |
| 编译后的简报 | [`schemas/agentlas-brief.schema.json`](schemas/agentlas-brief.schema.json) |

---

## 公共安全边界

本仓库**不**包含 Agentlas 计费/账户逻辑、生产云凭据、客户数据库、原始私有会话记录、原生钥匙串管理器或私有部署脚本。

由 Hephaestus 编译的公开输出包必须排除本地绝对路径、API 密钥、服务账号密钥、`.env` 机密、原始会话记录、客户日志与私人开发者笔记。

---

## 许可证

Apache-2.0。参见 [LICENSE](LICENSE)。
