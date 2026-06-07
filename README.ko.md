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

새 컴퓨터에서는 아래 경로 중 하나로 시작하세요. Claude Code나 Codex에서 쓰려면 플러그인 설치가 먼저입니다. 일반 프로젝트 폴더에 파일만 복사하고 싶을 때만 파일 설치를 쓰세요.

### A. Claude Code 플러그인

Claude 채팅창이 아니라 **macOS Terminal, Windows PowerShell, Linux terminal, Git Bash, WSL 같은 OS 터미널**에서 실행합니다.

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install agentlas-meta-agent@agentlas-core-engine
```

그 다음 작업할 프로젝트 폴더에서 Claude Code를 열거나 재시작하고, Claude Code 안에 아래처럼 입력합니다.

```text
/reload-plugins
/Hephaestus ontology
```

`/Hephaestus ontology`는 현재 프로젝트에 로컬 ontology GUI를 만들고 엽니다.

```text
.agentlas/ontology-inbox/
.agentlas/ontology-sources.json
.agentlas/ontology-runtime.sqlite
.agentlas/ontology-gui/index.html
```

홈 폴더나 옆 프로젝트를 훑지 않습니다. 승인된 회사 문서나 프로젝트 문서는 `.agentlas/ontology-inbox/`에 넣고 `/Hephaestus ontology`를 다시 실행하면 됩니다.

에이전트나 팀을 만들 때는 설치 후 Claude Code 안에서 이렇게 입력합니다.

```text
/Hephaestus create a research agent for SEC filing analysis
/Hephaestus create a customer support operations team
/Hephaestus package this existing Claude agent into Agentlas architecture
```

Claude CLI는 `claude plugins ...`도 alias로 받지만, 이 문서에서는 헷갈리지 않게 `claude plugin ...` 단수형으로 통일합니다.

### B. Codex 플러그인

Codex 채팅창이 아니라 **OS 터미널**에서 실행합니다.

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.1
codex plugin add agentlas-meta-agent@agentlas-core-engine
```

그 다음 작업할 프로젝트 폴더에서 Codex를 열거나 재시작하고, Codex 안에 아래처럼 입력합니다.

```text
/Hephaestus ontology
```

Codex CLI 명령은 `codex plugins`가 아니라 `codex plugin` 단수형입니다. 플러그인 설치 후 `/Hephaestus ontology`를 실행하면 같은 프로젝트 로컬 GUI가 만들어집니다.

```text
.agentlas/ontology-gui/index.html
```

에이전트나 팀을 만들 때는 설치 후 Codex 안에서 이렇게 입력합니다.

```text
/Hephaestus create a self-evolving research agent
/Hephaestus create a finance analyst team
/Hephaestus package this existing Codex workspace into Agentlas architecture
```

### C. 파일 복사 설치

Claude/Codex 플러그인이 아니라 현재 프로젝트에 패키지 파일만 복사하고 싶을 때 씁니다. 설치할 프로젝트 폴더에서 OS 터미널을 열고 실행합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.1/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Windows PowerShell:

```powershell
$zip = "$env:TEMP\agentlas-meta-agent-v0.2.1.zip"
$extract = "$env:TEMP\agentlas-meta-agent-v0.2.1"
Invoke-WebRequest "https://github.com/agentlas-ai/Hephaestus/archive/refs/tags/v0.2.1.zip" -OutFile $zip
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $extract -Force
$src = Get-ChildItem $extract -Directory | Select-Object -First 1
Get-ChildItem $src.FullName -Force | Copy-Item -Destination (Get-Location) -Recurse -Force
```

파일 설치 후에는 slash command가 아니라 터미널에서 직접 실행합니다.

```bash
bin/hephaestus ontology
```

### D. 이미 Claude/Codex 채팅창 안에 있을 때

아래 명령은 OS 터미널이 아니라 Claude Code 또는 Codex 채팅창 안에 그대로 입력하는 버전입니다.

Claude Code:

```text
/plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
/plugin install agentlas-meta-agent@agentlas-core-engine
/reload-plugins
/Hephaestus ontology
```

Codex:

```text
/plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.1
/plugin install agentlas-meta-agent@agentlas-core-engine
/Hephaestus ontology
```

설치 후 `/Hephaestus`가 안 보이면 해당 프로젝트에서 Claude Code나 Codex를 재시작하세요.

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
