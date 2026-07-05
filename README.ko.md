<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus — 어떤 모델 위에서든 돌아가는 에이전트 OS</h1>

<p align="center">
  <strong>에이전트를 매번 새로 만들고 세팅하는 일, 이제 그만하세요. Hephaestus는 전문 에이전트를 허브에 쌓아두고, 태스크마다 임시 오케스트레이터를 즉석에서 만들어 돌립니다.</strong><br>
  모든 데이터는 내 컴퓨터에 먼저 저장되고, Claude Code, Codex, Gemini, Cursor, 로컬 모델 어디서든 그대로 쓸 수 있습니다.
</p>

<p align="center">
  <a href="https://github.com/agentlas-ai/Hephaestus/releases/latest">
    <img alt="Latest release" src="https://img.shields.io/github/v/release/agentlas-ai/Hephaestus?label=release">
  </a>
  <a href="LICENSE">
    <img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green">
  </a>
  <img alt="Runtimes" src="https://img.shields.io/badge/runtimes-Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20%7C%20Antigravity%20%7C%20Cursor%20%7C%20DeepSeek%20%7C%20GLM%20%7C%20Ollama%20%7C%20Terminal-black">
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

<p align="center">
  <img src="assets/hephaestus-network-mcp-demo.gif" alt="MCP를 통해 태스크를 실시간으로 올바른 에이전트에 라우팅하는 Hephaestus Network 2.0" width="760">
</p>

<p align="center">
  <sub>허브에서 불러온 전문 에이전트들이 임시 태스크포스로 조립되어 MCP로 실시간 라우팅됩니다 — 태스크마다 에이전트를 세팅할 필요가 없습니다.</sub>
</p>

## 빠른 시작

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```

이 명령은 중립 러너를 설치하고 Claude Code, Codex, Gemini CLI, Antigravity, Cursor용 명령 어댑터를 등록합니다. 플러그인, 수동 복사, 또는 AI에게 설치를 맡기고 싶다면 [전체 설치 방법](#전체-설치-방법)을 참고하세요.

<p align="center">
  <a href="#에이전트-os-시대">에이전트 OS 시대</a>
  ·
  <a href="#빠른-시작">빠른 시작</a>
  ·
  <a href="#전체-설치-방법">전체 설치 방법</a>
  ·
  <a href="#명령-표면">명령 표면</a>
  ·
  <a href="#v110의-새로운-기능--briefing-interview-engine">v1.1.0의 새로운 기능</a>
  ·
  <a href="#os-서브시스템">서브시스템</a>
  ·
  <a href="#엔터프라이즈를-위한-설계">엔터프라이즈 운영</a>
  ·
  <a href="#무엇을-만들어내는가-프로세스-패키징">시스템 패키징</a>
  ·
  <a href="#목표별-문서">문서 레지스트리</a>
  ·
  <a href="#데스크톱-셸--agentlas-desktop">데스크톱 셸</a>
</p>

---

## 에이전트 OS 시대

업계는 이제 상태 없는 임시방편식 "도구 달린 챗봇" 단계를 넘어섰습니다. Google과 주요 AI 랩이 Antigravity 오케스트레이션 플랫폼, Gemini Spark 데몬 프로세스 같은 **에이전트 운영체제(Agent Operating System)**를 중심으로 개발자 전략을 재편하면서, AI 에이전트는 공식적으로 일급 운영체제 프리미티브가 되었습니다 — 고유한 정체성, 관계형 메모리 시스템, 보안 권한, 네이티브 도구 호출 환경을 갖춘, 오래 살아 있는 상태 유지 프로세스가 된 것입니다.

이로 인해 팀이 마주하는 핵심 엔지니어링 질문이 바뀝니다. **여러분의 에이전트 워크포스는 누구의 운영체제 위에서 돌아갑니까?**

에이전트가 단일 모델 제공자의 독점 API에 강하게 결합되어 있다면, 조직의 메모리, 커스텀 도구, 태스크별 로직은 사실상 그 벤더의 생태계에 묶이게 됩니다.

**Hephaestus는 어떤 모델에도 묶이지 않는 독립 커널입니다.** 에이전트 프레임워크도, API 래퍼도 아닙니다. 로컬 우선 에이전트 운영체제로서, 어떤 호스트 런타임에서든 이식 가능한 에이전트 프로세스를 컴파일·스케줄링·관리하는 통합 실행 기반입니다. 밑단의 추론 엔진을 갈아끼워도 워크포스 전체는 그대로 유지됩니다.

Hephaestus는 고전적인 운영체제 개념에 그대로 대응됩니다:

| OS 추상화 | Hephaestus에서의 구현 |
| :--- | :--- |
| **커널 / 정책 게이트** | 결정적 라우터 + 보안 게이트. 모든 라우팅 동작은 감사 가능한 영수증을 남기며, 도구 실행 권한은 엄격히 샌드박스되어 호스트 런타임이 강제합니다. |
| **프로세스 / 스레드** | 명시적 타입 계약(Routing Card, 안티스코프, 메모리 경계, 검증 심)을 갖춘 패키지로 컴파일되는 독립 에이전트와 멀티 에이전트 팀. |
| **프로세스 스케줄러** | Network 2.0 라우팅(로컬 우선·품질 게이트·벤치마크 게이트 디스패치)과 Stormbreaker의 병렬 실행 패브릭, 추가 전용(append-only) 실행 저널의 결합. |
| **메모리 관리(MMU)** | 두 경계로 관리되는 메모리: 로컬 프로젝트 메모리는 머신 안에 격리되고, 영구 승격은 로컬 Memory Curator가 게이트합니다. |
| **가상 파일 시스템** | Production Ontology Runtime: 로컬 우선 소스 수집, CJK 트라이그램 FTS5 검색, 하이브리드 Reciprocal Rank Fusion, GraphRAG 검색. |
| **프로세스 간 호출(IPC)** | A2A Agent Card Boundary(암호학적 가져오기/내보내기와 호출자 게이팅) + Model Context Protocol(MCP) 도구 등록. |
| **패키지 매니저** | Agentlas Hub & Cloud: 품질 게이트가 내장된 에이전트 컴파일·발행·버저닝·공유. |
| **셸 인터페이스** | 외부 클라이언트 런타임에서는 작고 통일된 명령 집합, 네이티브 Agentlas 셸에서는 평문 의도 라우팅. |
| **프로세스 초기화** | Briefing Interview Gate가 통합된 Meta-Agent Factory — 코드를 컴파일하기 전에 에이전트 파라미터를 확정합니다. |

<p align="center">
  <img src="assets/agentlas-meta-agent-architecture.svg" alt="Figure 1. Agentlas Meta-Agent architecture decomposition">
</p>

<p align="center">
  <sub>그림 1. 요청 셰이핑, 세 개의 빌더, 생성된 패키지 계약, 메모리 큐레이션, 스킬 수명주기, 런타임 어댑터, 동기화 경계.</sub>
</p>

---

## v1.1.0의 새로운 기능 — Briefing Interview Engine

모호한 한 문장짜리 프롬프트로 생성된 에이전트는 실제 엣지 케이스 앞에서 무너집니다. Hephaestus v1.1.0은 **Briefing Interview Engine**을 통해 태스크 명세를 일급 OS 서비스로 격상합니다:

*   **정량적 모호성 게이트:** 컴파일 스케줄러가 프롬프트의 명확성을 네 가지 핵심 벡터(목표, 제약, 범위, 컨텍스트)에서 평가합니다. 모호성 점수가 수치 임계값(모호성 점수 $\le 0.2$, 차원별 안전 하한 포함)을 통과할 때까지 빌드 프로세스는 엄격히 게이트됩니다. 명확한 프롬프트는 사소한 작업의 질문 수를 제한하는 예산 시스템 덕분에 인터뷰 루프를 완전히 건너뜁니다.
*   **렌즈 기반 시스템 분석:** 명확화 질문은 구조화된 렌즈 테이블(범위, 의도, 도전 과제, 시스템 아키텍처)에서 동적으로 뽑아내며, 핵심 라우팅 지표에 집중합니다: *안티스코프 경계*(에이전트가 절대 하면 안 되는 것), *검증 가능한 수용 기준*, *종료 조건*.
*   **Work Brief:** 확정된 세부 사항은 `.agentlas/work-brief.json`에 동결됩니다 — 검증된 목표, 구체적 제약, 출처 태그가 달린 가정 원장(assumption ledger), 메타데이터 모호성 점수를 기록합니다.
*   **컨텍스트 반영 인플라이트 브리프:** CLI 도구 `cards migrate`가 브리프의 세부 내용을 에이전트 라우팅 카드의 트리거와 안티트리거에 자동으로 매핑합니다. `route --brief`를 실행하면 이 브리프가 모든 Stormbreaker 실행 패킷으로 전파되어, 제약과 종료 조건이 전체 수명주기에 걸쳐 병렬 서브프로세스를 관장하도록 보장합니다.
*   **강화된 라우팅 판별력:** 같은 주제·다른 의도 충돌(예: 보안 에이전트가 배포 프롬프트를 가로채는 문제)을 양면 게이팅으로 방지합니다: 라우팅 카드에 기록된 인터뷰 검증 안티트리거, 그리고 라우터 내부의 저신뢰도 LLM 리랭킹 에스컬레이션.

---

## 전체 설치 방법

### 붙여넣어 부팅하기 (AI에게 맡기기)
아래 내용을 Claude Code, Codex, Gemini CLI, Antigravity 또는 Cursor에 붙여넣으세요:

```text
Install Hephaestus Agentlas for this workspace from this GitHub repo:
https://github.com/agentlas-ai/Hephaestus

Use the latest release/instructions. If anything errors, diagnose and fix it,
retry, and confirm which command surface is active in this tool:
- Agentlas Terminal / Desktop route plain language natively.
- 외부 LLM 호스트는 핵심 작업 명령을 노출합니다: build, network, cloud,
  search, call, upload. Claude Code와 Codex에는 Telegram 설정 helper인
  connect도 함께 노출됩니다.
```

### 새 macOS 점검
```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
```

### 모든 런타임을 한 줄 터미널 명령으로
```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```
이 명령은 중립 러너를 `~/.agentlas/runtime/current/bin/hephaestus`에 설치하고, Claude Code, Codex, Gemini CLI, Antigravity, Cursor용 명령 어댑터를 등록합니다. 설치기는 등록이 끝난 뒤 각 런타임 표면을 검증합니다.

### 런타임별 플러그인 드라이버

<details>
<summary>Claude Code 플러그인</summary>

OS 터미널에서:
```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```
*참고: Claude Code는 별칭으로 `claude plugins ...`도 지원하지만, 이 README에서는 일관성을 위해 단수형 `claude plugin ...`을 사용합니다.*

</details>

<details>
<summary>Codex 플러그인</summary>

OS 터미널에서:
```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v1.1.4
codex plugin add hephaestus@agentlas-core-engine
```
*참고: Codex 앱 안에서는 `/plugin marketplace add`가 동작하지 않습니다 — 위 두 명령을 OS 터미널에서 실행하세요. OS 터미널 CLI 명령은 단수형(`codex plugin`)이고, Codex 앱 안의 플러그인 브라우저 슬래시 명령은 복수형(`/plugins`)입니다. 설치 후에는 `/prompts:hep-build`가 앱 내 진입점입니다.*

</details>

<details>
<summary>프로젝트에 파일 복사하기 (수동 드라이버)</summary>

저장소를 클론한 뒤 `AGENTS.md`, `agent.md`, `agents/`, `skills/`, `modes/`, `schemas/`, `templates/`, `.agentlas/`를 워크스페이스에 복사하세요. 런타임 폴더(`.claude/`, `codex/`, `.gemini/`, `.agents/`)는 동일한 정본 코어 위의 어댑터로 동작합니다.

</details>

**그냥 말하세요:** 설치 후 네이티브 Agentlas 인터페이스에서는 평문으로 말하면 태스크가 자동 라우팅됩니다. 외부 호스트 도구에서는 아래에 나열된 명시적 명령을 사용하세요. 어떤 에이전트가 있는지 모를 때는 `/hep-search`부터 시작하세요. Telegram을 연결하려면 Claude Code에서는 `/hep-connect`, Codex에서는 `/prompts:hep-connect`를 사용하세요.

---

## 명령 표면

네이티브 Agentlas 환경 안에서 Hephaestus는 명령어 없이 동작합니다. 외부 LLM 호스트는 의도적으로 작게 유지한 가시 명령 집합을 사용합니다. Stormbreaker, 리서치 로드아웃, 설정 테이블 같은 시스템 수준 유틸리티는 컨텍스트에서 자동으로 붙습니다:

| 시스템 서브시스템 | 셸 명령 | 예시 |
| :--- | :--- | :--- |
| **프로세스 빌더** | `/hep-build` | `/hep-build create a customer support agent for Shopify refunds` |
| **A2A 스케줄러** | `/hep-network` | `/hep-network split this launch plan into research, copy, QA, and release agents` |
| **클라우드 상태 동기화** | `/hep-cloud` | `/hep-cloud use my saved finance analyst agent to review this report` |
| **디렉터리 검색** | `/hep-search` | `/hep-search find agents for a market report workflow` |
| **프로세스 간 호출(IPC)** | `/hep-call` | `/hep-call market-researcher, report-writer {draft a market report}` |
| **패키지 익스포터** | `/hep-upload` | `/hep-upload ./agents/customer-support-hq` |
| **Telegram 설정** | `/hep-connect` 또는 `/prompts:hep-connect` | `/hep-connect Telegram for Marketing Agent Team` |

---

## 데스크톱 셸 — Agentlas Desktop

[Agentlas Desktop](https://agentlas.cloud/desktop)은 이 에이전트 OS의 그래픽 셸입니다 — 동일한 커널, 스케줄러, 거버넌스 서브시스템을 시각적으로 운용합니다. Desktop 0.6.0에는 Hephaestus v1.1.4 엔진이 번들로 고정되어 함께 배포되며, 앱과 커널은 버전이 서로 잠긴 채 하나의 단위로 자동 업데이트됩니다.

| 셸 표면 | 운용 대상 |
| :--- | :--- |
| **채팅 워크스페이스** | 어떤 런타임에든 바인딩되는 평문 세션 — Claude Code, Codex, Gemini CLI, Antigravity, BYOK API(DeepSeek, GLM, Kimi), 로컬 Ollama — 라이브 스트리밍, 스티어링 큐, 채팅별 작업 폴더를 지원합니다. |
| **빌드 메뉴** | UI 뒤에서 돌아가는 Meta-Agent Factory: 인터뷰 게이트 빌드(브리핑 질문 묶음이 네이티브 질문 카드로 렌더링됨) 후 디스크에 실제 패키지 파일을 생성합니다. |
| **에이전트 라이브러리 & 허브** | 직접 컴파일한 에이전트와 팀, 빌려 온 Hub 전문가들 — Agentlas Hub 패키지 레지스트리를 상대로 설치·버저닝·발행·가격 책정을 수행합니다. |
| **태스크 포스 & 스웜** | 빌려 온 멀티 에이전트 태스크 포스, 머신 사양 기반 동시성 슬라이더가 달린 병렬 스웜 실행, 장기 작업을 위한 연속 라이브 실행. |
| **자동화** | 크론/이벤트/파일 감시 트리거를 시각적 그래프 에디터가 딸린 병렬 DAG 워크플로우로 컴파일합니다 — OS 용어로 말하면 스케줄된 에이전트 프로세스입니다. |
| **메모리 & 진화 패널** | 관리형 메모리 서브시스템의 가시화: 큐레이터 티켓, 승격된 플레이북, 자기 진화 제안, 보안 재스캔. |

데스크톱 셸은 CLI와 동일한 경계를 강제합니다: 내 머신과 내 구독으로 실행하는 BYOC, 라우팅 결정마다 남는 영수증, 로컬 우선 메모리. 다운로드: [agentlas.cloud/desktop](https://agentlas.cloud/desktop).


---

## OS 서브시스템

### Meta-Agent Factory — 프로세스 생성
세 개의 빌더를 사용하는 통합 컴파일 팩토리입니다. 생성된 모든 패키지는 전역 명령(`.agentlas/global-commands.json`)을 등록하고 검증 스크립트를 함께 배포합니다 — 사용자가 컴파일된 패키지를 어떻게 실행할지 추측할 필요가 없습니다:

| 컴파일 모드 | 라우팅 대상 | 산출물 |
| :--- | :--- | :--- |
| **싱글 에이전트** | `10-single-agent-builder` | 로컬화된 스킬, 메모리 계약, 런타임 어댑터를 갖춘 독립 워커. |
| **멀티 에이전트 팀** | `20-multi-agent-team-builder` | PM Orchestrator, Memory Curator, Policy Gate, QA, 검증 스크립트를 포함하는 계층형 팀. |
| **워크스페이스 패키저** | `30-agentlas-packager` | 데스크톱 임포트, CLI 실행, GitHub 배포가 가능한 컴파일 번들. |

*Briefing Interview Gate:* 빌더는 **briefing interview gate**([docs/builder-interview-research-gate.md](docs/builder-interview-research-gate.md))로 프로세스를 시작합니다: 렌즈 기반 질문을 수행하고, 모호성 임계값을 평가하고, 1차 출처를 검색하고, work brief를 출력합니다.

---

### Network 2.0 — 스케줄러

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>그림 2. A2A 스케줄링: 호스트 런타임, 로컬 우선 오케스트레이터, 라우팅 카드, 로컬 메모리, Agentlas Hub A2A/MCP 폴백.</sub>

*   **Routing Cards:** 모든 에이전트, 팀, 플러그인은 트리거, 안티트리거, 능력, 리스크 프로필, 메모리 파라미터를 담은 표준화된 카드를 함께 배포합니다. 검증에 실패한 카드는 라우팅에서 제외됩니다.
*   **로컬 우선 디스패치:** 디스패치는 먼저 로컬에서 해석됩니다(프로젝트 오버라이드 $\rightarrow$ 로컬 카드). Agentlas Hub를 통한 외부 조회는 키워드 수준으로 마스킹되며, 원시 프롬프트는 절대 로컬 환경을 벗어나지 않습니다.
*   **임시 태스크 포스:** 복합 요청은 Hub/로컬 Task Force 플랜으로 분해되어 Stormbreaker 엔벨로프, 세션 힌트, 온톨로지 경로를 함께 담습니다. 이름이 지목된 전문가들이 동적으로 스케줄되고, 임시 오케스트레이터가 태스크 핸드오프를 관리합니다.
*   **영수증 기반 실행:** 모든 라우팅 결정은 영수증을 남깁니다. 라우터는 어떤 에이전트나 패키지를 호출할지만 결정하며, 도구 실행 권한은 여전히 엄격히 샌드박스된 채 호스트 런타임이 관리합니다.
*   **이중 언어 벤치마크:** 자동 라우팅은 top-3 recall $\ge 90\%$와 프라이버시 유출 0건을 요구하는 이중 언어(한국어 + 영어) 벤치마크로 게이트됩니다. 저신뢰도 경로는 호스트 수준의 Router Agent 리랭킹으로 에스컬레이션됩니다.

자세한 내용: [docs/hephaestus-network-2.0.md](docs/hephaestus-network-2.0.md) · 런타임 지원 매트릭스: [docs/runtime-fallback-adapters.md](docs/runtime-fallback-adapters.md)

---

### Stormbreaker — 규율 있는 실행
Stormbreaker는 이 에이전트 OS의 실행 게이팅 서브시스템입니다. 모든 결과가 결정적 검사로 검증되기 전에는 에이전트가 성공을 보고하거나 종료하지 못하도록 보장합니다:

```text
Kernel Gating Envelope:
[Scope Lock] -> [Decomposition] -> [Parallel Work Packets] -> [Verify Contracts] -> [Bounded Repair] -> [Final Gate]
```

로컬 실행 저널 덕분에 긴 실행도 중단 후 재개할 수 있습니다. 실행 패킷은 Work Brief를 함께 실어 나르므로, 안티스코프 규칙과 종료 기준이 모든 병렬 서브프로세스를 관장합니다. Stormbreaker는 명시적 완료 상태(**verified / unverified / blocked**)를 보고하여 자율 에이전트의 "완료 연기(completion theater)"를 방지합니다.

실행 프로토콜: [docs/robustness-protocol.md](docs/robustness-protocol.md) · 벤치마크 & 평가: [docs/robustness-eval.md](docs/robustness-eval.md)

---

### Ontology Runtime — 지식 파일시스템
지식 집약적 작업에서는 `bin/ontology`가 시맨틱 파일시스템 역할을 하며, 비정형 로컬 파일을 에이전트가 읽을 수 있는 데이터베이스 스택으로 변환합니다:

```text
Ingested Files -> [Parser Adapter] -> [CJK trigram/bigram tokenization] 
  -> [FTS5 + SQLite Storage] -> [Reciprocal Rank Fusion Ranking] -> [GraphRAG Search]
```

GPL 의존성 없이 한국어 문서 파싱(HWPX 및 레거시 HWP5)을 퍼스트파티로 제공합니다. 완전 로컬 SQLite 기반이며, 기밀·비공개 청크는 격리되어 외부 클라우드 훅에 도달하지 못합니다.

```bash
bin/ontology ingest ./corpus --scope internal
bin/ontology query "Project Helios Memory Curator" --agent verifier
bin/ontology memory candidates
```

자세한 내용: [docs/ontology-runtime.md](docs/ontology-runtime.md)

---

### 관리형 메모리 — 큐레이션 승격
*   **로컬 프로젝트 메모리:** `~/.agentlas/networking/` 아래에 저장되며 로컬 머신에 격리됩니다. 명시적 승인 없이는 내보낼 수 없습니다.
*   **워크스페이스 개인화:** 빌려 온 Cloud/Hub 에이전트의 개인화 로그(요약, 플레이북, 플러그인 잠금, 영수증)를 원시 프롬프트, 자격 증명 값, 비공개 파일을 저장하지 않은 채 관리합니다.
*   **큐레이터 게이팅:** 스킬과 메모리 수정은 후보 상태로 유지됩니다. 로컬 큐레이터가 홀드아웃/리플레이 증명, 롤백 커버리지, 보안 정책 승인을 확인한 뒤에야 영구 상태로 승격됩니다.

---

### A2A Boundary — 에이전트 간 격리
표준화된 CLI 명령으로 에이전트 간 협업을 안전하게 수행할 수 있습니다:

```bash
agentlas-cloud ao a2a import ./agent-card.json .
agentlas-cloud ao a2a export . --agent local/10-builder
agentlas-cloud route "run the release check" --caller local/orchestrator .
```
가져오기(import)는 제안으로 처리되어 자동 호출이 제한되고, 내보내기(export)는 비공개 경로와 로직을 가리며, 호출은 라우팅이 해석되기 전에 호출자 게이트를 거칩니다.

---

## 엔터프라이즈를 위한 설계

엔터프라이즈에 필요한 것은 고립된 Python 에이전트를 작성하는 또 하나의 방법이 아닙니다. 그런 에이전트들로 이루어진 **관리형 워크포스를 운영**하는 것입니다. Hephaestus는 바로 이 운영 모델을 위해 설계되었습니다:

*   **조달 레버리지가 되는 모델 중립성:** 에이전트, 메모리 저장소, 지식 도메인은 여러분의 통제 아래 로컬 자산으로 저장됩니다. 새 모델 제공자로 전환하는 것(또는 Ollama, Llama 같은 로컬 모델이나 DeepSeek, GLM, Gemini, Claude 같은 엔터프라이즈 엔진을 활용하는 것)은 코드베이스 마이그레이션이 아니라 단순한 설정 변경입니다.
*   **구조적으로 보장되는 감사 가능성:** 모든 라우팅 결정, 실행 단계, 메모리 후보, 큐레이터 결정이 텍스트 파일로 기록됩니다. diff하고, 감사하고, 커밋할 수 있습니다. 작업은 검증되었거나, 미검증으로 표시됩니다.
*   **결정적 파이프라인 게이트:** 보안 필터, 안티스코프, 라우팅 카드 트리거, 프롬프트 새니타이즈는 OS 파이프라인에 하드코딩되어 있습니다 — LLM 시스템 지침이나 가이드라인에 의존하지 않습니다.
*   **생성 전 명세:** Briefing Interview Engine이 요청의 모호성을 측정해 그 점수를 Work Brief에 찍어 두므로, 태스크 실행을 언제나 합의된 내용까지 거슬러 올라가 감사할 수 있습니다.
*   **로컬 우선 데이터 경계:** 원시 텍스트, 문서, 데이터베이스 파일은 로컬에 남습니다. 외부 트랜잭션은 마스킹되며 옵트인입니다.

### 프레임워크의 자리
CrewAI, LangChain, 각 벤더의 에이전트 SDK는 **라이브러리**로 기능합니다 — 단일 프로세스 안에서 커스텀 에이전트 로직을 작성하기에 훌륭합니다. Hephaestus는 **호스트 기반(substrate)**으로 동작합니다: 워크스페이스 런타임 전반에서 에이전트를 명세하고, 패키징하고, 라우팅하고, 실행하고, 감사하고, 마이그레이션합니다. 프레임워크 코드는 Hephaestus 패키지 안에서 실행되며, 커널은 에이전트가 디렉터리 계약과 Routing Card를 준수할 것만을 요구합니다.

---

## 무엇을 만들어내는가 (프로세스 패키징)

Hephaestus는 어떤 워크스페이스 런타임이든 파싱·설치·검증·실행할 수 있는 표준 디렉터리 레이아웃으로 에이전트를 패키징합니다:

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

## 목표별 문서

| 시스템 목표 | 참조 문서 |
|---|---|
| 정본 라우트 이해하기 | [`AGENTS.md`](AGENTS.md) |
| 전체 팀 계약 보기 | [`agent.md`](agent.md) |
| 아키텍처의 단일 진실 원천 | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| 런타임 경계 | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| 브리핑 인터뷰 & 리서치 게이트 | [`docs/builder-interview-research-gate.md`](docs/builder-interview-research-gate.md) |
| Network 2.0 라우팅 | [`docs/hephaestus-network-2.0.md`](docs/hephaestus-network-2.0.md) |
| Stormbreaker 프로토콜 | [`docs/robustness-protocol.md`](docs/robustness-protocol.md) |
| 온톨로지 런타임 | [`docs/ontology-runtime.md`](docs/ontology-runtime.md) |
| 메모리 아키텍처 | [`docs/memory-architecture.md`](docs/memory-architecture.md) |
| 스킬 수명주기 승격 | [`docs/skill-lifecycle-promotion.md`](docs/skill-lifecycle-promotion.md) |
| 클라우드 런타임 번들 | [`docs/agentlas-cloud-runtime.md`](docs/agentlas-cloud-runtime.md) |
| 패키지 검증하기 | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| 공개 안전 점검 | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

---

## 공개 안전 경계

이 저장소에는 호스팅된 Agentlas 결제/계정 로직, 프로덕션 클라우드 자격 증명, 고객 데이터베이스, 원시 비공개 대화 기록, 데스크톱 키체인 관리자, 비공개 배포 스크립트가 포함되어 있지 **않습니다**.

Hephaestus가 컴파일하는 공개 산출 패키지에는 로컬 절대 경로, API 키, 서비스 계정 키, `.env` 시크릿, 원시 대화 기록, 고객 로그, 비공개 개발자 노트가 들어가서는 안 됩니다.

---

## 기여와 검증

풀 리퀘스트를 열거나 업데이트를 발행하기 전에 검증 테스트 스위트를 실행하세요:

```bash
scripts/verify-package.sh
scripts/verify-ontology-runtime.sh
scripts/public_safety_check.sh
```

---

## 라이선스

Apache-2.0. [LICENSE](LICENSE)를 참고하세요.
