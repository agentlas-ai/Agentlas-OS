<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus</h1>

<p align="center">
  <strong>把一个粗略的智能体想法变成可安装的 Agentlas agent/team 仓库。</strong>
</p>

<p align="center">
  创建单个专家智能体，组装多智能体团队，或把现有 Claude/Codex/OpenClaw/Hermes 工作区整理成可公开发布的 Agentlas 包。
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

## 快速开始

这里有三种安装路径。如果你想使用完整的 Agentlas 本地运行时，请使用 **1 + 3**。如果你只想把这个包直接装进 Claude Code、Codex 或普通项目文件夹，请使用 **2**。

| 路径 | 适合场景 | 需要打开什么 |
|---|---|---|
| 1. Agentlas Terminal | 从命令行运行 Agentlas agents | 先打开 Agentlas Desktop，再打开 macOS Terminal / Windows PowerShell / Linux terminal |
| 2. 独立安装 Hephaestus | 直接安装到 Claude Code、Codex 或普通 repo | Claude Code、Codex 或系统终端 |
| 3. Agentlas Desktop | 可视化本地运行时、agent/team 管理、vault、Apps | 先用浏览器下载，再打开 Agentlas Desktop 应用 |

### 1. 安装 Agentlas Terminal

Agentlas Terminal 通过 **Agentlas Desktop** 安装。先安装 Desktop，然后在应用里打开：

```text
Agentlas Desktop -> Settings -> Use from the terminal (`agentlas` CLI) -> Install CLI
```

完成后，打开系统终端并运行 `agentlas`。

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

在 Desktop Settings 中安装 CLI 后：

```bash
agentlas list
agentlas run agentlas-meta-agent "Package this workflow for Agentlas"
```

### 2. 独立安装 Hephaestus

#### 简单文件安装

在你想安装包文件的项目文件夹中打开 macOS Terminal、Linux terminal、Windows Git Bash 或 WSL：

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.6/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Windows PowerShell:

```powershell
$zip = "$env:TEMP\hephaestus-v0.2.6.zip"
$extract = "$env:TEMP\hephaestus-v0.2.6"
Invoke-WebRequest "https://github.com/agentlas-ai/Hephaestus/archive/refs/tags/v0.2.6.zip" -OutFile $zip
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $extract -Force
$src = Get-ChildItem $extract -Directory | Select-Object -First 1
Get-ChildItem $src.FullName -Force | Copy-Item -Destination (Get-Location) -Recurse -Force
```

#### 安装 Claude Code 插件

注册 marketplace 和安装 plugin 是两个不同步骤。marketplace 命令只是告诉 Claude Code 到哪里找这个 repo；install 命令才会真正安装插件。安装后需要 reload。

**在 Claude Code 聊天窗口中输入**：

```text
/plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
/plugin install hephaestus@agentlas-core-engine
/reload-plugins
/plugin list
```

**在带有 `claude` CLI 的系统终端中输入**：

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```

预期结果：

```text
✓ Installed hephaestus. Run /reload-plugins to apply.
Reloaded: 1 plugin · 0 skills · 9 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

#### 安装 Codex 插件

不要在 Codex 聊天窗口中输入 `/plugin marketplace add`。Codex app 目前使用 `/plugins` 浏览已安装插件；安装要在系统终端里完成。

**在带有 `codex` CLI 的系统终端中输入**：

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.6
codex plugin list
codex plugin add hephaestus@agentlas-core-engine
codex plugin list
```

如果 Codex 会话已经打开，请重新打开一个会话，然后输入 `/plugins` 确认插件可见。安装后运行 `/hephaestus ontology`。

### 3. 安装 Agentlas Desktop

在浏览器中打开：

```text
https://agentlas.cloud/desktop
```

Desktop 提供可视化 Agentlas 界面：本地项目、agents、teams、Apps、vault references、runtime 选择、内置 Core Engine Meta-Agent 路由，以及 `agentlas` CLI 安装入口。

## 图解安装方法

如果你已经在 Claude Code 聊天窗口中，请使用 Claude slash command 图片。Codex 需要先在系统终端安装；在 Codex app 中用 `/plugins` 查看已安装插件。如果你打开的是 macOS Terminal、Windows PowerShell、Linux terminal、Git Bash 或 WSL，请使用 CLI 图片。

### Claude Code 聊天窗口

把这些命令直接输入 Claude Code。

![Claude Code chat install flow](assets/install-claude-code-chat.svg)

### OS 终端中的 Claude CLI

当你的 shell 中可以运行 `claude` 命令时，使用这个路径。

![Claude CLI install flow](assets/install-claude-cli.svg)

### Codex app 插件浏览

在系统终端完成 `codex plugin ...` 安装之后，在 Codex app 中输入 `/plugins` 查看插件。

![Codex app plugin browser](assets/install-codex-chat.svg)

### Codex Desktop 或 IDE Extension

当 Codex 显示 Plugins 设置页面时，使用这个路径。

![Codex Desktop settings install flow](assets/install-codex-desktop-settings.svg)

### OS 终端中的 Codex CLI

当你的 shell 中可以运行 `codex` 命令时，使用这个路径。

![Codex CLI install flow](assets/install-codex-cli.svg)

## 打开什么，在什么地方输入

| 任务 | 打开位置 | 输入位置 |
|---|---|---|
| 下载 Desktop | 浏览器 | `https://agentlas.cloud/desktop` 或对应系统的下载命令 |
| 安装 `agentlas` CLI | Agentlas Desktop | Settings -> Use from the terminal -> Install CLI |
| 运行 Agentlas Terminal | 系统终端 | `agentlas list`, `agentlas run ...` |
| 用 slash command 安装 Claude 插件 | Claude Code | `/plugin marketplace add ...`, `/plugin install ...`, `/reload-plugins` |
| 用 shell 安装 Claude 插件 | 系统终端 | `claude plugin marketplace add ...`, `claude plugin install ...` |
| 查看已安装的 Codex 插件 | Codex app | `/plugins` |
| 用 shell 安装 Codex 插件 | 系统终端 | `codex plugin marketplace add ...`, `codex plugin add ...` |

## 它会生成什么

Hephaestus 不只是生成一段提示词。它会留下一个其他运行时可以检查、安装、验证并继续改进的仓库。

| 你的请求 | 路由到 | 结果 |
|---|---|---|
| “做一个能完成 X 的 agent” | `10-single-agent-builder` | 带 skills、memory contracts、runtime adapters、verification 的单个 worker |
| “为这个 workflow 做一个 team/company” | `20-multi-agent-team-builder` | 带 HQ、PM Soul、Memory Curator、Policy Gate、eval、QA、handoff 的多智能体团队 |
| “把这个已有 agent/repo/workspace 打包” | `30-agentlas-packager` | 可用于 Desktop import、terminal、Codex、Claude、Gemini 或公开 GitHub release 的 Agentlas 包 |

## 架构

public core 是 architecture/foldering contract。Claude、Codex、Gemini、Desktop、Terminal 文件夹只是同一个 core 之上的轻量 adapter，不是新的源头。

| 公开 contract | 作用 |
|---|---|
| Mode auto-detection | 在生成前选择 `single-agent-creator`、`team-builder` 或 `agentlas-packager` |
| Clarify question loop | 只询问会影响 runtime、公开/私有边界、tools 或 safety 的问题 |
| `.agentlas` auto-activation | 让本地 runtime 可以 seed project memory、sitemap/task-bias、Memory Tickets、vault references |
| Skill lifecycle registry | 让 skill 先以 candidate metadata 存在，并保留 trial 和 Curator decision ledger |

默认导出状态是保守的。生成的 skill 不会自动成为 first-class recall。Curator 必须看到执行证据、sealed holdout/replay、rollback 覆盖和 workspace policy 批准后，才能升级。

## 为什么配合 Agentlas Desktop 和 Terminal 更好

- Desktop 可以显示 agent/team 结构、本地项目、Apps、vault references 和 runtime 选择。
- Terminal 可以用 `agentlas` 命令运行同一个 package。
- Desktop/Terminal 内置 Core Engine Meta-Agent 路径，刚安装后也能创建或打包 agents。
- 独立 Claude/Codex 安装适合把这个包直接放进那些运行时。

## 对比

| 对比对象 | 它的强项 | Hephaestus 增加的能力 |
|---|---|---|
| OpenAI / Codex | 强模型和 coding terminal | portable repo contracts、`.agentlas` memory/package files、skills、schemas、runtime adapters、public verification |
| Claude / Claude Code | 强推理和 Claude-native workflow | 支持 Claude，但不只服务 Claude；Codex、Gemini、Desktop、Terminal、`AGENTS.md` 也保持一致 |
| OpenClaw | local identity 和 workspace agent loop | visible role folders、Agentlas package contracts、public-safety checks、Desktop import、vault references |
| Hermes | persona 和 memory-centered local runtime | PM Soul、Memory Tickets、sitemap/task-bias、policy/eval/QA、skill lifecycle evidence |

OpenAI 和 Claude 是 model/runtime surfaces。OpenClaw 和 Hermes 是 local-agent experience。Hephaestus 是让 agent 变得 portable、inspectable、installable、publishable 的 package layer。

## 使用示例

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

## 文档

| 目标 | 文档 |
|---|---|
| 理解 canonical route | [`AGENTS.md`](AGENTS.md) |
| 查看 team contract | [`agent.md`](agent.md) |
| 查看 source of truth | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| 查看 runtime boundaries | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| 选择 mode | [`docs/mode-classifier.md`](docs/mode-classifier.md) |
| 验证 package | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| 检查 public safety | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

## Public Safety Boundary

这个 repo 不包含 hosted Agentlas billing/account logic、production credentials、customer data、raw private logs、raw transcripts、desktop keychain storage、local database implementation 或 private deployment configuration。

公开包中不应包含 local machine paths、API keys、tokens、private keys、service-account JSON、`.env` secrets、private research notes、raw chat transcripts、customer logs、hosted billing/account/OAuth 内部实现或 desktop storage 内部实现。

## License

Apache-2.0。请查看 [`LICENSE`](LICENSE)。
