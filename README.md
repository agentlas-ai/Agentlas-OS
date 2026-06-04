<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">agentlas-meta-agent</h1>

<p align="center">
  <strong>Build installable AI agents and multi-agent teams from one rough idea.</strong>
</p>

<p align="center">
  Create one agent, create a full agent team, or package an existing Claude/Codex/OpenClaw/Hermes workspace into a public-safe Agentlas repo.
</p>

<p align="center">
  <a href="https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/releases/latest">
    <img alt="Latest release" src="https://img.shields.io/github/v/release/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent?label=release">
  </a>
  <a href="LICENSE">
    <img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green">
  </a>
  <img alt="Runtimes" src="https://img.shields.io/badge/runtimes-Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20%7C%20AGENTS.md-black">
  <img alt="Package" src="https://img.shields.io/badge/package-agentlas--meta--agent-blue">
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a>
  ·
  <a href="#what-it-builds">What It Builds</a>
  ·
  <a href="#install">Install</a>
  ·
  <a href="#compare">Compare</a>
  ·
  <a href="#docs-by-goal">Docs</a>
  ·
  <a href="https://agentlas.cloud">agentlas.cloud</a>
</p>

<p align="center">
  <a href="#ko">한국어</a>
  ·
  <a href="#zh">中文</a>
  ·
  <a href="#en">English</a>
  ·
  <a href="#ja">日本語</a>
  ·
  <a href="#hi">हिन्दी</a>
</p>

---

## Quick Start

Pick the surface you already use.

### Claude Code

Run from your shell:

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

Or run inside Claude Code:

```text
/plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
/plugin install agentlas-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

Expected result:

```text
✓ Installed agentlas-meta-agent. Run /reload-plugins to apply.
Reloaded: 1 plugin · 0 skills · 9 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

### Codex

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.3
codex plugin list
codex plugin add agentlas-meta-agent@agentlas-core-engine
codex plugin list
```

If a Codex session is already open, start a new session after installation so the plugin is loaded.

### Any `AGENTS.md` Project

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.3/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Install into another folder:

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.3/scripts/install.sh | bash -s -- /path/to/project
```

> The README does not register the plugin for anyone automatically. Each user adds this GitHub repo as a marketplace in their own Claude Code or Codex environment, then installs `agentlas-meta-agent`.

## What It Builds

| You ask for | It routes to | You get |
|---|---|---|
| "Make one agent that does X" | `10-single-agent-builder` | One installable worker with skills, memory rules, runtime adapters, and verification |
| "Make a team/company for this workflow" | `20-multi-agent-team-builder` | A CEO/HQ, PM Soul, Memory Curator, Policy Gate, workers, eval, QA, and handoffs |
| "Package this existing agent/repo/workspace" | `30-agentlas-packager` | A cleaned Agentlas package for local use, Desktop import, Codex, Claude, Gemini, or public GitHub release |

The output is not a prompt pasted into a chat. It is a repo shape that other runtimes can read:

```text
AGENTS.md
CLAUDE.md
GEMINI.md
agent.md
agents/
skills/
modes/
.agentlas/
.agents/
.claude/
.gemini/
codex/
schemas/
templates/
scripts/verify-package.sh
scripts/public_safety_check.sh
```

## Why This Exists

Most AI tools can answer. Fewer can leave behind an agent package that survives another tool, another model, another maintainer, or a public GitHub release.

`agentlas-meta-agent` fixes the gap between:

- a good agent idea and a usable repo;
- a Claude-only helper and a portable Claude/Codex/Gemini/AGENTS.md package;
- a local OpenClaw/Hermes-style workspace and an Agentlas Desktop-ready import;
- a role list and a real team with memory, policy, eval, QA, install, and public-safety checks.

## Highlights

- **Three-mode router**: single agent, multi-agent team, or package/repair existing material.
- **Visible architecture**: roles, skills, modes, memory contracts, and runtime adapters are files.
- **Multi-runtime by default**: Codex, Claude Code, Gemini CLI, Cursor-style, and generic `AGENTS.md` workflows.
- **Agentlas Desktop ready**: package output can be opened, imported, and managed from Desktop and `agentlas` CLI workflows.
- **Public-safe release path**: verification and safety scans block private paths, tokens, service-account material, and common secret formats.
- **No model lock-in**: use the model/runtime you already trust; this repo packages the agent operating contract.

## Install

### Claude Code Plugin

This is a user-local marketplace install. Every Claude Code user runs it once in their own environment.

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

Local checkout option:

```bash
git clone https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent.git
cd agent_agentlas_core_engine_meta_agent
claude plugin marketplace add ./claude
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

### Codex Plugin

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.3
codex plugin add agentlas-meta-agent@agentlas-core-engine
```

Check:

```bash
codex plugin list
```

### Terminal Package Install

Use this when you want the files installed directly into a project without a Claude/Codex plugin marketplace.

```bash
curl -fsSL https://raw.githubusercontent.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent/v0.1.3/scripts/install.sh | bash
```

### Agentlas Desktop + `agentlas` CLI

1. Download the latest Desktop build from [Agentlas Desktop Releases](https://github.com/jeongmk522-netizen/agentlas-desktop/releases/latest).
2. Connect Claude Code, Codex, Gemini CLI, or BYOK API keys.
3. Open or import the agent/team package created by `agentlas-meta-agent`.
4. Use Desktop for visual team structure, local history, Apps, vault, automations, and runtime switching.
5. Install the `agentlas` CLI from Desktop settings to use the same agents from terminal.

```bash
agentlas list
agentlas run <agent> "Package this workflow for Agentlas"
cd "$(agentlas cd <agent>)" && claude
```

## Use It

Single agent:

```text
/meta-agent Create a research agent for SEC filing analysis.
Package it for Codex, Claude Code, Gemini, and Agentlas Desktop.
```

Multi-agent team:

```text
Use agentlas-meta-agent.
Build a customer-support operations team with PM Soul, Memory Curator, Policy Gate, QA, eval, and public-safe release checks.
```

Package an existing workspace:

```text
Package this local OpenClaw/Hermes-style workspace into Agentlas architecture.
Keep private notes, machine paths, raw logs, and secrets out of the public repo.
```

## Compare

| Compared with | Their strength | What `agentlas-meta-agent` adds |
|---|---|---|
| OpenAI / Codex | Strong models and coding terminal | Portable repo contracts, `.agentlas` memory/package files, skills, schemas, and multi-runtime adapters |
| Claude / Claude Code | Strong reasoning and Claude-native workflows | Claude support without becoming Claude-only; Codex, Gemini, Desktop, terminal, and `AGENTS.md` stay aligned |
| OpenClaw | Local identity and workspace agent loop | Visible role folders, public-safety checks, Desktop import, vault, and Agentlas packaging |
| Hermes | Persona and memory-centered local agent runtime | PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, and release verification as files |

OpenAI and Claude are model/runtime surfaces. OpenClaw and Hermes are local-agent experiences. `agentlas-meta-agent` is the package layer that makes agents portable, inspectable, installable, and publishable.

## Docs By Goal

| Goal | Start here |
|---|---|
| Understand the canonical route | [`AGENTS.md`](AGENTS.md) |
| See the full team contract | [`agent.md`](agent.md) |
| See the chain map | [`docs/chain-map.md`](docs/chain-map.md) |
| Understand runtime architecture | [`docs/llm-runtime-architecture.md`](docs/llm-runtime-architecture.md) |
| Understand memory architecture | [`docs/memory-architecture.md`](docs/memory-architecture.md) |
| Operate PM Soul | [`docs/pm-soul-operating-loop.md`](docs/pm-soul-operating-loop.md) |
| Read research notes | [`docs/research-log.md`](docs/research-log.md) |
| Choose a mode | [`modes/single-agent-creator.md`](modes/single-agent-creator.md), [`modes/team-builder.md`](modes/team-builder.md), [`modes/agentlas-packager.md`](modes/agentlas-packager.md) |
| Verify a package | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| Check public safety | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |
| See README benchmark notes | [`docs/readme-top10-patterns.md`](docs/readme-top10-patterns.md) |

## Public Safety Boundary

This repo intentionally does **not** include hosted Agentlas billing/account logic, production credentials, customer data, raw private logs, raw transcripts, desktop keychain storage, or local database implementation.

Public output packages should not include:

- local machine paths;
- API keys, tokens, private keys, service-account JSON, or `.env` secrets;
- private research notes;
- raw chat transcripts;
- customer or production logs;
- hosted billing, account, OAuth, or deployment internals.

## Localized Quick Starts

<h3 id="ko">한국어</h3>

`agentlas-meta-agent`는 아이디어 하나를 바로 설치 가능한 Agentlas agent/team repo로 바꿔주는 메타 에이전트입니다.

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.3
codex plugin add agentlas-meta-agent@agentlas-core-engine
```

핵심은 간단합니다. 사용자가 자기 Claude/Codex 환경에 marketplace를 등록하고, `agentlas-meta-agent`를 설치한 다음, 필요한 agent/team/package 작업을 요청합니다.

<h3 id="zh">中文</h3>

`agentlas-meta-agent` turns one rough idea into an installable Agentlas agent or team repository.

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.3
codex plugin add agentlas-meta-agent@agentlas-core-engine
```

每个用户都需要在自己的 Claude Code 或 Codex 环境中添加 marketplace，然后安装 plugin。README 不会自动注册 plugin。

<h3 id="en">English</h3>

Use `agentlas-meta-agent` when you want a real repo, not just a generated prompt.

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.3
codex plugin add agentlas-meta-agent@agentlas-core-engine
```

<h3 id="ja">日本語</h3>

`agentlas-meta-agent` は、曖昧な agent/team のアイデアを installable な Agentlas package に変換します。

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.3
codex plugin add agentlas-meta-agent@agentlas-core-engine
```

各ユーザーが自分の Claude Code または Codex 環境で marketplace を追加し、plugin を install する必要があります。

<h3 id="hi">हिन्दी</h3>

`agentlas-meta-agent` rough agent idea को installable Agentlas repo में बदलता है।

```bash
claude plugin marketplace add https://github.com/jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

```bash
codex plugin marketplace add jeongmk522-netizen/agent_agentlas_core_engine_meta_agent --ref v0.1.3
codex plugin add agentlas-meta-agent@agentlas-core-engine
```

हर user को अपने Claude Code या Codex environment में marketplace add करके plugin install करना होगा।

## Contributing

Public packages should stay portable and safe. Before opening a PR or publishing a release, run:

```bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

## License

Apache-2.0. See [LICENSE](LICENSE).
