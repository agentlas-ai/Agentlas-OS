<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Agentlas Core Engine Meta-Agent Team</h1>

<p align="center">
  <strong>Turn a rough agent idea into an installable Agentlas package for Codex, Claude Code, Gemini, Cursor, Desktop, and terminal workflows.</strong>
</p>

<p align="center">
  <a href="https://agentlas.cloud">agentlas.cloud</a>
  ·
  <a href="https://github.com/jeongmk522-netizen/Agentlas_public_repo">Agent Lab Hub</a>
  ·
  <a href="https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent">GitHub Repo</a>
  ·
  <a href="https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/releases/latest">Latest Release</a>
</p>

<table align="center">
  <tr>
    <td><a href="#ko">한국어</a></td>
    <td><a href="#zh">中文</a></td>
    <td><a href="#en">English</a></td>
    <td><a href="#ja">日本語</a></td>
    <td><a href="#hi">हिन्दी</a></td>
  </tr>
</table>

<p align="center">
  Click a language in the banner above to jump to the localized README.
</p>

---

<h2 id="ko">한국어</h2>

## 한 줄 소개

**Agentlas Core Engine Meta-Agent Team**은 "이런 에이전트 하나 만들어줘", "우리 팀 업무를 맡길 멀티 에이전트 팀으로 패키징해줘", "이미 만든 Claude/Codex/Hermes/OpenClaw 스타일 에이전트를 Agentlas 구조로 정리해줘" 같은 요청을 받아서, 바로 설치하고 검증할 수 있는 공개 Agentlas agent repo로 바꿔주는 3인 메타 에이전트 팀입니다.

이 repo는 모델이 아닙니다. 채팅 UI도 아닙니다. **에이전트와 에이전트 팀을 제품처럼 포장하는 공개 운영체제 계약**입니다. 결과물은 `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, visible `agents/`, reusable `skills/`, `.agentlas/` 계약, runtime adapter, 설치 스크립트, 검증 스크립트를 포함합니다.

## 왜 필요한가

요즘 AI 도구는 답변을 잘합니다. 하지만 "쓸 수 있는 에이전트 repo"를 만들려면 여전히 빠지는 것이 많습니다.

- 역할은 있어도 실제 파일 구조가 없습니다.
- Claude에서는 되는데 Codex나 Gemini에서는 다시 설명해야 합니다.
- memory, PM Soul, policy, eval, QA gate가 말로만 있고 repo에 남지 않습니다.
- 공개 GitHub에 올리기 전에 private path, token, 내부 메모가 섞였는지 확인하기 어렵습니다.
- OpenClaw나 Hermes처럼 로컬에서 돌리던 agent를 Desktop/terminal에서 보이는 Agentlas package로 옮기려면 구조가 필요합니다.

Agentlas Core Engine은 이 문제를 **파일로** 해결합니다. 생각만 있는 agent를 installable package로 만들고, 이미 있는 agent를 공개 가능한 Agentlas 구조로 수리합니다.

## 3개의 핵심 에이전트

| 에이전트 | 언제 쓰나 | 결과 |
|---|---|---|
| `10-single-agent-builder` | 한 명의 전문 agent가 충분할 때 | self-evolving single agent package |
| `20-multi-agent-team-builder` | CEO/HQ, PM, Memory Curator, worker, QA가 필요한 팀 업무일 때 | multi-agent team package |
| `30-agentlas-packager` | 기존 prompt, repo, Claude agent, Codex agent, OpenClaw/Hermes 스타일 workspace를 Agentlas 구조로 정리할 때 | public-safe Agentlas package |

PM Soul, Memory Curator, sitemap/task-bias, policy, eval, QA gate, runtime adapters는 이 3개 팀원이 만들어내는 **아키텍처 구성요소**입니다. 이 meta-agent team의 추가 멤버가 아닙니다.

## 바로 설치

### 1. 아무 프로젝트에 terminal로 설치

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash
```

다른 폴더에 설치하려면:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash -s -- /path/to/project
```

설치 후 확인:

```bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

### 2. Claude Code plugin으로 설치

아래 명령은 README가 자동 실행하는 것이 아닙니다. Claude Code 사용자가 자기 환경에서 직접 실행해야 marketplace가 등록되고 plugin이 설치됩니다.

터미널에서 설치:

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
```

이미 Claude Code 안에 들어와 있다면 slash command로도 설치할 수 있습니다.

```text
/plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
/plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

정상 적용 예시는 이런 흐름입니다.

```text
✓ Installed agentlas-core-engine-meta-agent. Run /reload-plugins to apply.
Reloaded: 1 plugin · 0 skills · 9 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

로컬 checkout에서 설치할 수도 있습니다.

```bash
git clone https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent.git
cd agent_agentlas_core_engine_meta_agent
claude plugin marketplace add ./claude
claude plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
```

### 3. Codex plugin으로 설치

Codex도 사용자가 자기 환경에 marketplace를 추가한 뒤 plugin을 설치해야 합니다.

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.2
codex plugin list
codex plugin add agentlas-core-engine-meta-agent@agentlas-core-engine
codex plugin list
```

이미 Codex 세션이 열려 있었다면 새 세션을 열어 plugin 로딩을 반영하세요.

### 4. Agentlas Desktop과 같이 쓰기

Agentlas Desktop은 이 repo가 만든 agent package를 로컬에서 더 편하게 실행하는 GUI/Apps 표면입니다.

1. 최신 Desktop을 받습니다: [Agentlas Desktop Releases](https://github.com/jeongmk522-netizen/agentlas-desktop/releases/latest)
2. Desktop을 열고 Claude Code, Codex, Gemini CLI 또는 BYOK API key를 연결합니다.
3. 이 repo로 만든 agent/team package를 project folder로 열거나 Agentlas import/install 흐름에 올립니다.
4. Desktop에서 org chart, local chat history, Apps, vault, automations를 확인합니다.
5. Settings에서 `agentlas` CLI를 설치하면 같은 agents/env/runtime을 terminal에서도 씁니다.

```bash
agentlas list
agentlas run <agent> "Create a public-safe Agentlas package for this workflow"
cd "$(agentlas cd <agent>)" && claude
```

## Desktop + Terminal을 같이 쓰면 좋은 점

| 표면 | 장점 |
|---|---|
| Agentlas Desktop | 눈으로 보는 agent/team 구조, local keychain, local history, Apps, imports, runtime 선택 |
| Terminal install script | repo에 바로 설치, CI/검증에 적합, `AGENTS.md` runtime과 호환 |
| `agentlas` CLI | Desktop과 같은 agent/env/runtime을 terminal에서 재사용 |
| 둘을 같이 쓸 때 | Desktop으로 선택/실행/관리하고 terminal로 생성/수정/검증하는 workflow가 됩니다. 결과물이 말이 아니라 repo로 남습니다. |

## OpenAI, Claude, OpenClaw, Hermes 대비 장점

| 비교 대상 | 그 도구의 강점 | Agentlas Core Engine이 더하는 것 |
|---|---|---|
| OpenAI / Codex | 강한 모델, 코딩 terminal, 빠른 실행 | 결과를 `AGENTS.md`, `.agentlas/`, skills, schemas, install script가 있는 portable agent repo로 고정합니다. OpenAI에만 묶이지 않습니다. |
| Claude / Claude Code | 긴 컨텍스트, 좋은 code reasoning, Claude-native command/plugin | `CLAUDE.md`만 만들고 끝내지 않습니다. Codex, Gemini, Desktop, terminal까지 같은 core contract를 읽게 만듭니다. |
| OpenClaw | 로컬 agent identity, workspace, terminal-style agent loop | Agentlas package로 옮기면 visible role folders, public-safety check, Desktop import, local vault, multi-runtime adapters가 붙습니다. |
| Hermes | 로컬 persona/memory 중심 agent runtime | Agentlas는 persona만이 아니라 PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, release verification까지 repo 계약으로 남깁니다. |

요점은 간단합니다. OpenAI와 Claude는 뛰어난 **모델/런타임**입니다. OpenClaw와 Hermes는 좋은 **로컬 에이전트 경험**입니다. Agentlas Core Engine은 그 위에 올라가는 **공개 가능하고 설치 가능한 agent package layer**입니다.

## 사용 예시

Claude Code:

```text
/meta-agent Create a single research agent for SEC filing analysis.
Package it for Codex, Claude, Gemini, and Agentlas Desktop.
```

Codex:

```text
Use the Agentlas Core Engine Meta-Agent Team.
Build a multi-agent customer-support operations team with PM Soul, Memory Curator, QA gate, and public-safe release checks.
```

Packaging an existing local agent:

```text
Package this existing agent workspace into Agentlas architecture.
Keep private notes out of the public repo.
Add AGENTS.md, CLAUDE.md, GEMINI.md, .agentlas contracts, skills, install script, and verification.
```

## Repository Map

```text
.
├── AGENTS.md                         # canonical portable entry point
├── CLAUDE.md                         # Claude Code adapter
├── GEMINI.md                         # Gemini CLI adapter
├── agent.md                          # single-file meta-agent team contract
├── agents/                           # 3 visible meta-agent team members
├── modes/                            # single-agent, team, packaging contracts
├── skills/                           # reusable architecture procedures
├── .agents/                          # portable runtime-discovered core
├── .agentlas/                        # mode, memory, sitemap, package contracts
├── .claude-plugin/                   # Claude marketplace manifest
├── .claude/                          # Claude command/agent/skill adapters
├── claude/                           # Claude Code plugin package
├── .gemini/                          # Gemini adapter
├── codex/                            # Codex plugin package scaffold
├── docs/                             # source-of-truth and runtime docs
├── schemas/                          # JSON schemas for generated repos
├── templates/                        # starter files emitted by the meta-agent
├── examples/                         # minimal example output
└── scripts/                          # install and verification scripts
```

## Source of Truth

- Canonical operating rules: [`AGENTS.md`](AGENTS.md)
- Architecture ownership: [`docs/source-of-truth.md`](docs/source-of-truth.md)
- Runtime boundary: [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md)
- Mode classifier: [`docs/mode-classifier.md`](docs/mode-classifier.md)
- Clarify loop: [`docs/clarify-question-loop.md`](docs/clarify-question-loop.md)
- `.agentlas` activation: [`docs/agentlas-auto-activation.md`](docs/agentlas-auto-activation.md)

This repo intentionally does **not** include private Agentlas web service code, billing/account logic, production credentials, customer data, private logs, raw transcripts, or desktop keychain/database implementation.

---

<h2 id="zh">中文</h2>

## 简介

**Agentlas Core Engine Meta-Agent Team** 是一个三成员元代理团队，用来把粗略的代理想法、团队工作流，或已有的 Claude/Codex/OpenClaw/Hermes 风格工作区，整理成可安装、可验证、可公开发布的 Agentlas 代理仓库。

它不是模型，也不是单一聊天界面。它是一个 **agent package layer**：让代理输出落到真实文件中，包括 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md`、visible `agents/`、`skills/`、`.agentlas/` contracts、runtime adapters、install scripts 和 verification scripts。

## 三个核心成员

| Agent | 适用场景 | 输出 |
|---|---|---|
| `10-single-agent-builder` | 一个专家代理就够了 | self-evolving single agent package |
| `20-multi-agent-team-builder` | 需要 orchestrator、PM、Memory Curator、workers、QA | multi-agent team package |
| `30-agentlas-packager` | 整理已有 prompt、agent、repo、Claude/Codex/OpenClaw/Hermes workspace | public-safe Agentlas package |

## 安装

Terminal install:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Install into another folder:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash -s -- /path/to/project
```

Claude Code plugin:

这些命令需要每个 Claude Code 用户在自己的环境中手动运行。README 只是说明安装路径，不会自动注册 plugin。

Install from terminal:

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
```

Or install from inside Claude Code:

```text
/plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
/plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

Codex plugin:

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.2
codex plugin list
codex plugin add agentlas-core-engine-meta-agent@agentlas-core-engine
codex plugin list
```

If Codex was already open, start a new session after installation.

Agentlas Desktop:

1. Download from [Agentlas Desktop Releases](https://github.com/jeongmk522-netizen/agentlas-desktop/releases/latest).
2. Connect Claude Code, Codex, Gemini CLI, or your own API key.
3. Open or import the package generated by this repo.
4. Use Desktop for visual execution, local history, key vault, Apps, automations, and runtime switching.
5. Install the `agentlas` CLI from Desktop settings to use the same agents in terminal.

```bash
agentlas list
agentlas run <agent> "Package this workflow for Agentlas"
```

## Why Agentlas

| Compared with | What it is good at | What Agentlas adds |
|---|---|---|
| OpenAI / Codex | strong models and coding terminal | portable repo contracts, runtime adapters, `.agentlas` memory/package files |
| Claude / Claude Code | excellent reasoning and Claude-native workflow | not Claude-only: Codex, Gemini, Desktop, terminal, and `AGENTS.md` stay aligned |
| OpenClaw | local identity and workspace agent loop | visible roles, public-safety checks, Desktop import, vault, multi-runtime packaging |
| Hermes | persona and memory-centered local agent runtime | PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, release verification |

## Best with Desktop + Terminal

Desktop gives a visible local operating surface. Terminal gives reproducible repo installation and verification. Together, they let you design, run, inspect, and publish agents without turning architecture into private notes.

---

<h2 id="en">English</h2>

## What this is

**Agentlas Core Engine Meta-Agent Team** converts rough agent ideas, multi-agent team requests, and existing local agent workspaces into installable Agentlas-compatible repositories.

It is not another model and not just a chat UI. It is a **portable agent packaging layer**. It turns an agent plan into files that other runtimes can actually read: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, visible `agents/`, reusable `skills/`, `.agentlas/` contracts, schemas, templates, install scripts, and verification scripts.

## The team

| Agent | Use it when | It produces |
|---|---|---|
| `10-single-agent-builder` | one expert agent is enough | an installable self-evolving worker package |
| `20-multi-agent-team-builder` | the work needs orchestration, roles, gates, and handoffs | a multi-agent team package |
| `30-agentlas-packager` | you already have a prompt, agent, repo, or external workspace | a repaired, public-safe Agentlas package |

## Install

Terminal install:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Install into another project:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash -s -- /path/to/project
```

Claude Code plugin:

These commands must be run by each Claude Code user. The README only documents the install path; it does not register the plugin automatically.

Install from terminal:

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
```

Or install from inside Claude Code:

```text
/plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
/plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

Expected apply flow:

```text
✓ Installed agentlas-core-engine-meta-agent. Run /reload-plugins to apply.
Reloaded: 1 plugin · 0 skills · 9 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

Codex plugin:

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.2
codex plugin list
codex plugin add agentlas-core-engine-meta-agent@agentlas-core-engine
codex plugin list
```

If Codex was already open, start a new session after installation.

Agentlas Desktop:

1. Download the latest build from [Agentlas Desktop Releases](https://github.com/jeongmk522-netizen/agentlas-desktop/releases/latest).
2. Connect Claude Code, Codex, Gemini CLI, or BYOK API keys.
3. Open or import the agent package generated by this repo.
4. Use Desktop for visual team structure, local chat history, Apps, vault, automations, and runtime switching.
5. Install the `agentlas` CLI from Desktop settings when you want the same agents from terminal.

```bash
agentlas list
agentlas run <agent> "Create a public-safe Agentlas package for this workflow"
```

## Why use it with Desktop and terminal

| Surface | What it gives you |
|---|---|
| Agentlas Desktop | visual execution, org chart, local keychain, local history, Apps, imports, runtime switching |
| Terminal installer | reproducible repo setup, CI-friendly checks, any `AGENTS.md`-compatible runtime |
| `agentlas` CLI | same Desktop agents/env/runtime from terminal |
| Together | build and verify in terminal, run and manage visually in Desktop |

## Compared with OpenAI, Claude, OpenClaw, and Hermes

| Compared with | Their strength | Agentlas Core Engine advantage |
|---|---|---|
| OpenAI / Codex | strong models and a capable coding terminal | makes the result portable across runtimes with repo contracts, skills, schemas, and `.agentlas` files |
| Claude / Claude Code | excellent reasoning, long-context coding, Claude-native plugins | keeps Claude support while also shipping Codex, Gemini, Desktop, terminal, and `AGENTS.md` adapters |
| OpenClaw | local agent identity and workspace loop | adds public-safe packaging, visible role folders, verification scripts, and Desktop import/run paths |
| Hermes | persona and memory-centered local agent runtime | adds PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, and release checks as files |

OpenAI and Claude are powerful model/runtime surfaces. OpenClaw and Hermes are useful local-agent experiences. Agentlas Core Engine is the layer that makes agents **portable, inspectable, installable, and publishable**.

## Example prompts

```text
/meta-agent Create a single research agent for SEC filing analysis.
Package it for Codex, Claude, Gemini, and Agentlas Desktop.
```

```text
Use the Agentlas Core Engine Meta-Agent Team.
Build a multi-agent customer-support operations team with PM Soul, Memory Curator, QA gate, and public-safe release checks.
```

```text
Package this existing local agent workspace into Agentlas architecture.
Keep private notes out of the public repo.
```

## Repository map

```text
.
├── AGENTS.md                         # canonical portable entry point
├── CLAUDE.md                         # Claude Code adapter
├── GEMINI.md                         # Gemini CLI adapter
├── agent.md                          # single-file meta-agent team contract
├── agents/                           # 3 visible meta-agent team members
├── modes/                            # single-agent, team, packaging contracts
├── skills/                           # reusable architecture procedures
├── .agents/                          # portable runtime-discovered core
├── .agentlas/                        # mode, memory, sitemap, package contracts
├── .claude-plugin/                   # Claude marketplace manifest
├── .claude/                          # Claude command/agent/skill adapters
├── claude/                           # Claude Code plugin package
├── .gemini/                          # Gemini adapter
├── codex/                            # Codex plugin package scaffold
├── docs/                             # source-of-truth and runtime docs
├── schemas/                          # JSON schemas for generated repos
├── templates/                        # starter files emitted by the meta-agent
├── examples/                         # minimal example output
└── scripts/                          # install and verification scripts
```

## Public boundary

This repo is public by design. It does not include hosted billing/account logic, production credentials, customer data, raw private logs, raw transcripts, desktop keychain storage, or local database implementation. Runtime-specific products can mirror this contract, but this repo remains the portable public core.

---

<h2 id="ja">日本語</h2>

## 概要

**Agentlas Core Engine Meta-Agent Team** は、曖昧な agent アイデア、multi-agent team の要望、既存の Claude/Codex/OpenClaw/Hermes 風 workspace を、インストール可能で検証可能な Agentlas package に変換する 3 人構成の meta-agent team です。

これはモデルでも、単なるチャット UI でもありません。Agent を repo として残すための **portable packaging layer** です。`AGENTS.md`、`CLAUDE.md`、`GEMINI.md`、visible `agents/`、`skills/`、`.agentlas/` contracts、runtime adapters、install scripts、verification scripts を生成または修復します。

## コアメンバー

| Agent | 使う場面 | 出力 |
|---|---|---|
| `10-single-agent-builder` | 1 つの専門 agent で十分な場合 | self-evolving single agent package |
| `20-multi-agent-team-builder` | orchestrator、PM、Memory Curator、workers、QA が必要な場合 | multi-agent team package |
| `30-agentlas-packager` | 既存 prompt、agent、repo、外部 workspace を整理したい場合 | public-safe Agentlas package |

## インストール

Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

別フォルダへ:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash -s -- /path/to/project
```

Claude Code plugin:

このコマンドは各 Claude Code ユーザーが自分の環境で実行する必要があります。README は install path を説明するだけで、plugin を自動登録するものではありません。

Install from terminal:

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
```

Or install from inside Claude Code:

```text
/plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
/plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

Codex plugin:

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.2
codex plugin list
codex plugin add agentlas-core-engine-meta-agent@agentlas-core-engine
codex plugin list
```

Codex がすでに開いている場合は、install 後に新しい session を開始してください。

Agentlas Desktop:

1. [Agentlas Desktop Releases](https://github.com/jeongmk522-netizen/agentlas-desktop/releases/latest) から最新版をダウンロードします。
2. Claude Code、Codex、Gemini CLI、または BYOK API key を接続します。
3. この repo で生成した agent/team package を開く、または import します。
4. Desktop で org chart、local history、Apps、vault、automations、runtime switching を使います。
5. Settings から `agentlas` CLI を入れると terminal でも同じ agent を使えます。

```bash
agentlas list
agentlas run <agent> "Package this workflow for Agentlas"
```

## 比較したときの強み

| 比較対象 | 強み | Agentlas Core Engine が追加する価値 |
|---|---|---|
| OpenAI / Codex | 強いモデルと coding terminal | runtime をまたぐ repo contracts、skills、schemas、`.agentlas` files |
| Claude / Claude Code | 高品質な reasoning と Claude-native flow | Claude 専用で終わらず、Codex/Gemini/Desktop/terminal へ展開 |
| OpenClaw | local identity と workspace agent loop | visible roles、public-safety check、Desktop import、multi-runtime packaging |
| Hermes | persona/memory 中心の local runtime | PM Soul、Memory Tickets、sitemap/task-bias、policy/eval/QA、release checks |

## Desktop + Terminal

Desktop は見える実行面を提供します。Terminal は repo への再現可能な install と verification を提供します。両方を使うと、agent を作る、検証する、実行する、公開する流れが 1 つにつながります。

---

<h2 id="hi">हिन्दी</h2>

## परिचय

**Agentlas Core Engine Meta-Agent Team** एक तीन-agent meta team है। यह rough agent idea, multi-agent workflow, या पहले से बने Claude/Codex/OpenClaw/Hermes-style workspace को installable और verifiable Agentlas package में बदलता है।

यह कोई नया model नहीं है और केवल chat UI भी नहीं है। यह एक **portable agent packaging layer** है। इसका काम agent को वास्तविक repo files में बदलना है: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, visible `agents/`, reusable `skills/`, `.agentlas/` contracts, runtime adapters, install scripts, और verification scripts।

## Core agents

| Agent | कब इस्तेमाल करें | Output |
|---|---|---|
| `10-single-agent-builder` | जब एक expert agent काफी हो | self-evolving single agent package |
| `20-multi-agent-team-builder` | जब orchestrator, PM, Memory Curator, workers, QA चाहिए | multi-agent team package |
| `30-agentlas-packager` | जब existing prompt, repo, Claude/Codex/OpenClaw/Hermes workspace को clean package बनाना हो | public-safe Agentlas package |

## Install

Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

दूसरे folder में:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.2/scripts/install.sh | bash -s -- /path/to/project
```

Claude Code plugin:

इन commands को हर Claude Code user को अपने environment में चलाना होगा। README केवल install path बताता है; plugin अपने-आप register नहीं होता।

Install from terminal:

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
```

Or install from inside Claude Code:

```text
/plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
/plugin install agentlas-core-engine-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

Codex plugin:

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.2
codex plugin list
codex plugin add agentlas-core-engine-meta-agent@agentlas-core-engine
codex plugin list
```

अगर Codex पहले से खुला था, तो install के बाद नया session शुरू करें।

Agentlas Desktop:

1. Latest build यहां से लें: [Agentlas Desktop Releases](https://github.com/jeongmk522-netizen/agentlas-desktop/releases/latest).
2. Claude Code, Codex, Gemini CLI, या BYOK API key connect करें।
3. इस repo से बने agent/team package को open या import करें।
4. Desktop में visual team structure, local history, Apps, vault, automations, और runtime switching इस्तेमाल करें।
5. Settings से `agentlas` CLI install करें ताकि terminal में वही agents चलें।

```bash
agentlas list
agentlas run <agent> "Package this workflow for Agentlas"
```

## OpenAI, Claude, OpenClaw, Hermes की तुलना में फायदा

| तुलना | उनकी ताकत | Agentlas Core Engine क्या जोड़ता है |
|---|---|---|
| OpenAI / Codex | strong model और coding terminal | portable repo contracts, `.agentlas` files, skills, schemas, multi-runtime adapters |
| Claude / Claude Code | strong reasoning और Claude-native workflow | Claude-only नहीं; Codex, Gemini, Desktop, terminal, `AGENTS.md` support |
| OpenClaw | local identity और workspace agent loop | visible roles, public-safety checks, Desktop import, vault, packaging |
| Hermes | persona और memory centered local runtime | PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, release verification |

## Desktop + Terminal क्यों बेहतर है

Desktop agent/team को देखने और चलाने का local UI देता है। Terminal reproducible install, repo checks, और automation देता है। दोनों साथ में agent को idea से public-ready package तक ले जाते हैं।

---

## License

Apache-2.0. See [LICENSE](LICENSE).
