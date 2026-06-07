<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">agentlas-meta-agent</h1>

<p align="center">
  <strong>거친 에이전트 아이디어 하나를 설치 가능한 Agentlas agent/team 저장소로 바꿉니다.</strong>
</p>

<p align="center">
  단일 전문가, 멀티 에이전트 팀, 기존 Claude/Codex/OpenClaw/Hermes 워크스페이스를 공개 가능한 Agentlas 패키지로 정리합니다.
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

## 빠른 시작

설치 경로는 세 가지입니다. **Agentlas 전체 런타임**이 필요하면 1번과 3번을 쓰세요. Claude Code, Codex, 일반 프로젝트 폴더에 이 패키지만 직접 넣고 싶으면 2번을 쓰면 됩니다.

| 경로 | 언제 쓰나 | 무엇을 열어야 하나 |
|---|---|---|
| 1. Agentlas Terminal | 셸에서 Agentlas 에이전트를 실행할 때 | 먼저 Agentlas Desktop, 그 다음 macOS Terminal / Windows PowerShell / Linux terminal |
| 2. agentlas-meta-agent 단독 설치 | Claude Code, Codex, 일반 repo에 직접 설치할 때 | Claude Code, Codex, 또는 OS 터미널 |
| 3. Agentlas Desktop | 시각적 로컬 런타임, agent/team 관리, vault, Apps가 필요할 때 | 브라우저로 다운로드 후 Agentlas Desktop 앱 |

### 1. Agentlas Terminal 설치

Agentlas Terminal은 **Agentlas Desktop**에서 설치합니다. Desktop 설치 후 앱에서 아래 메뉴를 여세요.

```text
Agentlas Desktop -> Settings -> Use from the terminal (`agentlas` CLI) -> Install CLI
```

그 다음 일반 터미널을 열고 `agentlas` 명령어를 입력합니다.

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

Desktop Settings에서 CLI 설치를 끝낸 뒤:

```bash
agentlas list
agentlas run agentlas-meta-agent "Package this workflow for Agentlas"
```

### 2. agentlas-meta-agent 단독 설치

#### 단순 파일 설치

설치할 프로젝트 폴더에서 macOS Terminal, Linux terminal, Windows Git Bash, WSL 중 하나를 엽니다.

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

#### Claude Code 플러그인 설치

마켓플레이스 등록과 플러그인 설치는 별도 단계입니다. 마켓플레이스 등록은 Claude Code가 이 repo를 찾을 수 있게 하는 작업이고, install이 실제 설치입니다.

**Claude Code 채팅창 안에서**:

```text
/plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
/plugin install agentlas-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

**OS 터미널에서 `claude` CLI로**:

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

예상 결과:

```text
✓ Installed agentlas-meta-agent. Run /reload-plugins to apply.
Reloaded: 1 plugin · 0 skills · 9 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

#### Codex 플러그인 설치

**Codex 채팅창 안에서**:

```text
/plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.0
/plugin install agentlas-meta-agent@agentlas-core-engine
/reload-plugins
/plugin list
```

**OS 터미널에서 `codex` CLI로**:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.0
codex plugin list
codex plugin add agentlas-meta-agent@agentlas-core-engine
codex plugin list
```

이미 Codex 세션이 열려 있었다면 `/reload-plugins`를 실행하거나 새 세션을 시작하세요.

### 3. Agentlas Desktop 설치

브라우저에서 아래 주소를 엽니다.

```text
https://agentlas.cloud/desktop
```

Desktop은 로컬 프로젝트, agents, teams, Apps, vault reference, runtime 선택, 내장 Core Engine Meta-Agent 라우팅, `agentlas` CLI 설치 화면을 제공합니다.

## 그림으로 보는 설치 방법

이미 Claude Code나 Codex 채팅창 안에 있다면 slash command 그림을 따라 하세요. macOS Terminal, Windows PowerShell, Linux terminal, Git Bash, WSL을 열었다면 CLI 그림을 따라 하면 됩니다.

### Claude Code 채팅창

Claude Code 안에 그대로 입력합니다.

![Claude Code chat install flow](assets/install-claude-code-chat.svg)

### OS 터미널의 Claude CLI

셸에서 `claude` 명령어가 되는 경우 이 경로를 씁니다.

![Claude CLI install flow](assets/install-claude-cli.svg)

### Codex 채팅창

Codex 안에 그대로 입력합니다.

![Codex chat install flow](assets/install-codex-chat.svg)

### Codex Desktop 또는 IDE Extension

Codex에 Plugins 설정 화면이 보이는 경우 이 경로를 씁니다.

![Codex Desktop settings install flow](assets/install-codex-desktop-settings.svg)

### OS 터미널의 Codex CLI

셸에서 `codex` 명령어가 되는 경우 이 경로를 씁니다.

![Codex CLI install flow](assets/install-codex-cli.svg)

## 무엇을 켜고 어디에 입력하나

| 작업 | 여는 곳 | 입력 위치 |
|---|---|---|
| Desktop 다운로드 | 브라우저 | `https://agentlas.cloud/desktop` 또는 OS별 다운로드 명령 |
| `agentlas` CLI 설치 | Agentlas Desktop | Settings -> Use from the terminal -> Install CLI |
| Agentlas Terminal 실행 | OS 터미널 | `agentlas list`, `agentlas run ...` |
| Claude 플러그인 slash 설치 | Claude Code | `/plugin marketplace add ...`, `/plugin install ...`, `/reload-plugins` |
| Claude 플러그인 shell 설치 | OS 터미널 | `claude plugin marketplace add ...`, `claude plugin install ...` |
| Codex 플러그인 slash 설치 | Codex 채팅창 | `/plugin marketplace add ...`, `/plugin install ...`, `/reload-plugins` |
| Codex 플러그인 shell 설치 | OS 터미널 | `codex plugin marketplace add ...`, `codex plugin add ...` |

## 무엇을 만들어 주나

`agentlas-meta-agent`는 프롬프트 답변만 만들지 않습니다. 다른 런타임이 읽고, 설치하고, 검증하고, 계속 개선할 수 있는 repo를 남깁니다.

| 요청 | 라우팅 | 결과 |
|---|---|---|
| "X를 하는 단일 agent를 만들어줘" | `10-single-agent-builder` | skills, memory contract, runtime adapter, verification이 있는 단일 worker |
| "이 workflow용 팀/company를 만들어줘" | `20-multi-agent-team-builder` | HQ, PM Soul, Memory Curator, Policy Gate, eval, QA, handoff가 있는 멀티 에이전트 팀 |
| "이 기존 agent/repo/workspace를 패키징해줘" | `30-agentlas-packager` | Desktop import, terminal, Codex, Claude, Gemini, public GitHub release에 맞는 Agentlas 패키지 |

## 아키텍처

public core는 architecture/foldering contract입니다. Claude, Codex, Gemini, Desktop, Terminal 폴더는 같은 core 위의 얇은 adapter이며 별도 원본이 아닙니다.

| 공개 contract | 역할 |
|---|---|
| Mode auto-detection | `single-agent-creator`, `team-builder`, `agentlas-packager` 중 하나를 먼저 고릅니다. |
| Clarify question loop | runtime, 공개/비공개 경계, tools, safety에 영향 있는 질문만 합니다. |
| `.agentlas` auto-activation | local runtime이 project memory, sitemap/task-bias, Memory Tickets, vault reference를 seed할 수 있게 합니다. |
| Skill lifecycle registry | skill을 candidate metadata로 시작하고 trial/Curator decision ledger를 둡니다. |
| Super Ontology candidate layer | source lineage, privacy, task coverage, causality, consensus, repair, reflexive feedback을 확인하는 공개 가능한 graph/memory governance 파일을 seed합니다. |

기본 export는 보수적입니다. 생성된 skill은 바로 first-class recall이 되지 않습니다. Curator가 실행 증거, sealed holdout/replay, rollback, workspace policy를 확인해야 승격됩니다.

### Production Ontology Runtime

개인 자료나 회사 자료처럼 지식이 많은 agent/team을 만들 때 Hephaestus는 실제 local-first ontology runtime을 제공합니다. 원본 파일을 source archive에 넣고, chunk를 만들고, full-text/vector 검색과 graph relation을 저장한 뒤, GraphRAG 결과를 Memory Curator ticket과 Agent Working Memory cache로 연결합니다.

Super Ontology 파일은 안전 규칙층입니다. 실제 저장/검색/graph/memory cache는 `ontology/`와 `bin/ontology`가 처리합니다.

| 층 | 역할 |
|---|---|
| Source archive / chunk store | 원본 파일 metadata, checksum, type, parser status, version, privacy scope, lineage, chunk span을 저장합니다. |
| Search / vector | SQLite FTS5와 local hashing vector만 씁니다. API key가 필요 없고 원문이 밖으로 나가지 않습니다. |
| Ontology graph | entity, alias, relation, confidence, evidence chunk, observed/valid time, stale/deprecated 상태를 저장합니다. |
| GraphRAG | chunk와 graph edge를 같이 반환합니다. 단순 vector 검색이 아닙니다. |
| Memory Curator | durable memory에 바로 쓰지 않고 candidate ticket만 만듭니다. |
| Agent Working Memory | 현재 작업에 필요한 per-agent hot cache입니다. TTL, source ref, confidence, invalidation state가 있고 source of truth가 아닙니다. |

지원 ingest:

| 형식 | 상태 |
|---|---|
| `.txt`, `.md`, `.json`, `.csv` | 실제 parse |
| `.docx`, `.xlsx`, `.pptx` | OpenXML adapter로 parse |
| `.pdf` | `pdftotext`가 있으면 parse |
| `.hwpx` | HWPX XML adapter로 parse |
| 이미지/OCR | macOS Vision OCR 또는 Tesseract가 있으면 parse |
| binary `.hwp` | `hwp5txt`가 있으면 parse, 없으면 이유와 함께 `unsupported_pending_adapter` |

이 hot working-memory layer는 source of truth가 아니라 cache입니다. 수십 GB 개인/회사 자료에서 context token을 줄이고, 빠르게 recall하고, 개인화 성능을 올리는 게 목표라면 이 층이 필요합니다.

## Agentlas Desktop과 Terminal을 같이 쓰면 좋은 점

- Desktop에서 agent/team 구조, local project, Apps, vault reference, runtime 선택을 볼 수 있습니다.
- Terminal에서 같은 package를 `agentlas` 명령으로 실행할 수 있습니다.
- Desktop/Terminal에는 Core Engine Meta-Agent 경로가 내장되어 있어 별도 standalone plugin 없이도 agent 생성과 패키징을 시작할 수 있습니다.
- Claude/Codex 단독 설치는 해당 런타임 안에 이 package를 직접 넣고 싶을 때 유용합니다.

## 비교

| 비교 대상 | 강점 | `agentlas-meta-agent`가 더하는 것 |
|---|---|---|
| OpenAI / Codex | 강한 모델과 coding terminal | portable repo contract, `.agentlas` memory/package files, skills, schemas, runtime adapters, public verification |
| Claude / Claude Code | 강한 추론과 Claude-native workflow | Claude-only가 아니라 Codex, Gemini, Desktop, Terminal, `AGENTS.md`까지 맞추는 구조 |
| OpenClaw | local identity와 workspace agent loop | visible role folders, Agentlas package contracts, public-safety checks, Desktop import, vault references |
| Hermes | persona와 memory 중심 local runtime | PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, skill lifecycle evidence |

OpenAI와 Claude는 model/runtime 표면입니다. OpenClaw와 Hermes는 local-agent 경험입니다. `agentlas-meta-agent`는 agent를 portable, inspectable, installable, publishable하게 만드는 package layer입니다.

## 사용 예시

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

## 문서

| 목표 | 문서 |
|---|---|
| canonical route 이해 | [`AGENTS.md`](AGENTS.md) |
| team contract 확인 | [`agent.md`](agent.md) |
| source of truth 확인 | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| runtime boundary 확인 | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| mode 선택 방식 | [`docs/mode-classifier.md`](docs/mode-classifier.md) |
| Super Ontology candidate contract 확인 | [`docs/super-ontology-candidate-contract.md`](docs/super-ontology-candidate-contract.md) |
| package 검증 | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| public safety 검사 | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

## Public Safety Boundary

이 repo에는 hosted billing/account logic, production credential, customer data, raw private log, raw transcript, desktop keychain storage, local database implementation, private deploy config를 넣지 않습니다.

공개 패키지에는 local machine path, API key, token, private key, service-account JSON, `.env` secret, private research note, raw chat transcript, customer log, hosted billing/account/OAuth 내부 구현, desktop storage 내부 구현이 들어가면 안 됩니다.

## License

Apache-2.0. [`LICENSE`](LICENSE)를 참고하세요.
