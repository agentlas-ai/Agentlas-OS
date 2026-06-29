<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus — Agent OS</h1>

<p align="center">
  <strong>Claude Code, Codex, Cursor를 위한 open Agent OS: meta-agent builder, A2A Hub routing, local ontology, memory/security gate로 개발자 소유 에이전트를 운영합니다.</strong>
</p>

<p align="center">
  에이전트를 만들고, 런타임 사이에서 라우팅하고, 프로젝트 문맥을 연결하고, memory·skill·verification·security gate를 통과한 변화만 오래 남깁니다.
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

## 복붙 퀵스타트

Claude Code, Codex, Gemini CLI, Antigravity, Cursor 중 아무 데나 아래 문장을
그대로 붙여넣으세요. AI가 Hephaestus를 설치하고, 지금 쓰는 도구에서 어떤
명령을 쓰면 되는지 알려줍니다.

```text
이 워크스페이스에 Hephaestus Agentlas를 설치해줘. GitHub 주소는 여기야:
https://github.com/agentlas-ai/Hephaestus

최신 릴리스/설치 안내를 기준으로 진행하고, 오류가 나면 네가 직접 원인을 고치고 재시도해줘. 설치가 끝나면 지금 도구에서 어떤 명령 표면이 활성화됐는지 확인해줘.

끝나면 명령 경계를 알려줘:
- Agentlas Terminal과 Agentlas 앱에서는 별도 /hep-* 명령 없이 자연어로 말하면
  Agentlas/Hephaestus 네이티브 도구가 맥락에 맞게 경로를 고른다.
- Claude Code, Codex, Gemini CLI, Antigravity, Cursor, OpenCode 같은 외부 LLM
  호스트에서는 build, network, cloud, search, call, upload 여섯 명령만
  명시적으로 보인다.
- Stormbreaker, research loadout, lower-level 옵션은 사용자가 이름을 몰라도
  맥락에 따라 자동으로 붙는다.

실패하면 에러를 읽고 고친 뒤 다시 시도하고, Claude Code, Codex, Gemini CLI,
Antigravity, Cursor 등록 상태까지 확인해줘.
```

## 네이티브와 외부 LLM 표면

Agentlas Terminal과 Agentlas 앱은 명령어 없는 네이티브 표면입니다. 하고 싶은
일을 자연어로 말하면 Agentlas/Hephaestus 도구가 맥락에 맞게 선택됩니다.

Claude Code, Codex, Gemini CLI, Antigravity, Cursor, OpenCode 같은 외부 LLM
호스트에서는 slash/prompt 명령이 필요합니다. 보이는 명령 표면은 여섯 개로
고정하고, 나머지는 맥락으로 자동 선택합니다.

| 할 일 | 명령 | 예시 프롬프트 |
|---|---|---|
| 생성 | `/hep-build` | `/hep-build 쇼피파이 환불용 고객지원 에이전트 만들어줘` |
| 빌리기 | `/hep-network` | `/hep-network 출시 계획을 리서치, 카피, QA, 릴리즈 에이전트로 쪼개서 TF 짜줘` |
| 공유 | `/hep-cloud` | `/hep-cloud 내 클라우드에 저장한 재무 분석 에이전트로 이 보고서 검토해줘` |
| 검색 | `/hep-search` | `/hep-search 시장 리포트에 쓸만한 에이전트 찾아줘` |
| 호출 | `/hep-call` | `/hep-call market-researcher, report-writer {시장 리포트 초안 작성}` |
| 업로드 | `/hep-upload` | `/hep-upload ./agents/customer-support-hq` |

새 설치와 업데이트는 오래된 `/hephaestus` 채팅 명령을 정리하고, 외부 LLM
호스트에서는 위 여섯 명령만 보이게 맞춥니다. Agentlas 안에서는 자연어 라우팅이
기본입니다.

## v1.0.2 새 기능

- **10만 에이전트 라우팅 경로.** Hephaestus가 Agentlas의 10만 에이전트
  라우팅 업그레이드에 연결됐습니다. 단순 단어 매칭을 넘어 OpenAI 임베딩으로
  후보를 넓히고, Atlas `$vectorSearch`가 dense ANN 후보를 가져오며,
  선택적으로 Z.ai/DeepSeek 리랭커가 최종 순서를 다듬습니다.
- **Router Agent cascade.** 결정론 라우터가 확신 있게 고르지 못해
  `clarify` 또는 `propose_new`로 떨어질 때, Hephaestus가 host runtime에
  넘길 구조화된 Router Agent escalation directive를 붙입니다.
- **모델 호출은 계속 host 쪽 책임.** Hephaestus 엔진은 cascade 때문에 직접
  LLM을 호출하지 않습니다. 민감한 내용을 줄인 directive만 넘기고, Claude Code,
  Codex, Agentlas Desktop 같은 host가 자기 모델 정책으로 추론합니다.
- **Agentlas Desktop 런타임 연결.** Desktop은 Router Agent directive를 받아
  기존 auto-route preamble 앞에 조립된 system-agent prompt를 주입합니다.
  그래서 escalation 문맥이 데스크탑 런타임 경계에서 떨어지지 않습니다.
- **프로덕션 게이트 통과.** R2 marketplace index 로딩, Atlas vector index READY,
  routing profile 120개 embedding backfill, routing eval 10/10 및 guard 5/5,
  production readiness 8/8, Hephaestus pytest, Desktop typecheck/smoke로
  검증했습니다.

## 이전 안정화 업데이트

- **앱 안에서 자동 업데이트 복구.** Claude Code, Codex, Gemini,
  Antigravity, Cursor, OpenCode, OpenClaw, Hermes, Pi, DeepSeek, GLM,
  Agentlas 같은 앱이 로컬 shell/exec 도구를 제공하면 `/hep-build`,
  `/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, `/hep-upload`
  실행 전에 Hephaestus가 앱 안에서 먼저 원터치 설치/업데이트를 시도합니다.
  사용자가 별도 OS 터미널을 열 필요가 없습니다.
- **최신 neutral runtime을 먼저 사용.** slash/prompt command는 이제
  Claude/Codex 플러그인 캐시보다
  `~/.agentlas/runtime/current/bin/hephaestus`를 먼저 봅니다. 그래서
  neutral runtime은 최신인데 플러그인 캐시가 예전 버전이라 생기는 꼬임을 줄입니다.
- **원클릭 설치 안정화.** 새 설치는 Claude Code/Codex 플러그인 캐시에도
  `RELEASE` 마커와 Python shim을 찍고, 검증 스크립트는 `update --check`가
  현재 버전을 못 읽으면 실패합니다.
- **설치된 러너의 import 안정화.** `bin/hephaestus`는 자기 런타임 루트를 Python
  경로 맨 앞에 강제로 넣습니다. 그래서 현재 작업 폴더에 다른
  `agentlas_cloud/`가 있어도 설치된 명령을 가로채지 못합니다.
- **플러그인 캐시까지 자가 복구.** `hephaestus update`는 이제 `RELEASE` 마커가
  없는 오래된 설치도 복구하고, 이미 설치된 Claude Code/Codex 플러그인 캐시
  디렉터리까지 갱신합니다. 그래서 standalone 런타임만 최신이고 slash command는
  예전 캐시를 쓰는 상태를 줄입니다.
- **비대화형 `/hep-upload` 실행.** 사용자가 Cloud 또는 Agentlas Hub를 선택한 뒤에는
  TTY 없는 호스트에서도 `hep-upload <agent-folder> --visibility private-link` 또는
  `--visibility marketplace`로 바로 진행합니다. 더 이상 질문만 출력하고
  "No upload performed"로 끝나지 않습니다.
- **영어 README 정리.** 영어 README의 명령 예시와 언어 라벨에서 한국어가 섞이지
  않게 정리했습니다.
- **팀 모양을 결정적으로 검사.** 생성된 패키지는 한 워커짜리 single agent이거나,
  오케스트레이터/HQ·토폴로지·메모리·정책·평가·QA·HQ 단일 명령을 가진 팀
  둘 중 하나여야 합니다. HQ 없이 워커 폴더만 여러 개인 패키지는
  `scripts/verify-team-package.sh`에서 실패합니다.
- **single/team 판정 기준을 역할 소유권으로 변경.** `/hep-build`는 이제 "팀"이라는
  단어만 보지 않고, 일을 따로 맡아야 하는 역할이 있는지, 넘겨받는 순서가 있는지,
  마지막에 결과를 합쳐야 하는지를 봅니다.
- **일반인이 알아듣는 빌더 질문.** 모호하면 "한 명의 전문가가 처음부터 끝까지
  맡으면 되는지, 아니면 여러 전문가가 나눠 맡고 마지막에 합쳐야 하는지"처럼
  쉬운 말로 먼저 묻습니다. ownership boundary, memory/context,
  produces/consumes 같은 내부 용어는 사용자에게 보이지 않습니다.

한계도 명확합니다. 앱이 로컬 shell/exec/MCP/파일 변경 도구를 전혀 제공하지 않으면
채팅만으로 로컬 설치 파일을 바꿀 수 없습니다. 또 이미 설치된 명령 표면이 너무 오래돼
preflight 문구 자체가 없으면, 그 설치본은 한 번은 플러그인 관리자나 원터치 설치로
새 표면까지 올라와야 그다음부터 자가 복구됩니다.

## 이전 명령 업데이트 안내

- **모든 명령에 업데이트 fallback 안내.** 각 `/hep-*` command/prompt 첫 줄에
  자동 업데이트가 안 되면 `hephaestus update`를 실행하라는 안내가 들어갑니다.
- **현재 버전도 계속 동작.** 안내문은 업데이트가 선택 사항이며, 지금 설치된 버전
  명령도 그대로 실행된다고 명시합니다.
- **자동화 출력은 그대로.** 이 안내는 chat command/prompt에만 들어가고 JSON을
  내보내는 shell CLI 출력에는 섞이지 않습니다.

Hephaestus는 Agentlas가 단순 prompt generator가 아니라 agent operating
system처럼 동작하게 만드는 공개 core engine입니다. 개발자가 제어해야 하는
네 가지 축을 하나로 묶습니다.

- **Meta-agent builder.** 의도를 분류하고 빠진 설정 질문을 채운 뒤 single
  agent, multi-agent team, 또는 runtime adapter가 포함된 package로 만듭니다.
- **A2A Hub router.** local routing card를 먼저 보고, 승인된 경우에만
  Agentlas Hub fallback을 쓰며, 모든 handoff에 receipt를 남깁니다.
- **Project ontology.** 승인된 프로젝트 소스를 local graph, search,
  source-lineage context로 바꿔 에이전트가 필요한 문맥만 질의하게 합니다.
  이것은 Hub 에이전트 검색이 아니라, 내 프로젝트 자료와 메모리를 정리하는
  로컬 지도입니다.
- **Memory, self-evolution, security gates.** durable memory, skill promotion,
  install verification, package scan, publish block을 통해 에이전트가 무엇을
  오래 기억하고 배워도 되는지 통제합니다. durable memory는 **관계 그래프**로,
  candidate ticket을 타입드 엣지(similar/supersedes/contradicts)로 잇고
  근접 중복을 자동 탐지하며, 교체 시 supersedes 엣지를 남겨 새 학습이 옛 학습을
  소리 없이 덮어쓰지 않게 합니다. 장기 작업은 **run journal**로 단계를 기록해
  중단돼도 처음부터가 아니라 안 끝난 단계부터 재개하고, 검증을 통과 못 한 단계는
  완료로 치지 않으며(verifier-first), 애매하면 멈춰 되묻습니다(clarification).

---

## Hephaestus Network 2.0

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Hephaestus Network 2.0 A2A networking architecture">
</p>

<p align="center">
  <sub>그림 2. Hephaestus Network 2.0 — 런타임, 전역 로컬 우선 오케스트레이터, 라우팅 카드, 로컬 메모리, 그리고 Agentlas Hub A2A/MCP 폴백.</sub>
</p>

명령 하나, 모든 런타임, 전부 로컬:

```text
/hep-build 고객지원 에이전트 만들어줘
/hep-network 출시 준비에 맞는 에이전트들 빌려와서 TF 짜줘
/hep-cloud 내 Agentlas Cloud에 공유한 에이전트로 처리해줘
```

- **라우팅 카드.** 모든 에이전트·팀·플러그인은 표준화된 라우팅 카드(트리거,
  안티 트리거, 능력, 리스크 프로파일, 메모리 동작)를 함께 제공합니다. 품질
  게이트를 통과하지 못한 카드는 절대 자동 라우팅되지 않습니다.
- **로컬 우선.** 명시적 명령 → 프로젝트 오버라이드 → 내 로컬 카드 순서입니다.
  Agentlas Hub는 폴백일 뿐이며 마스킹된 키워드만 전달받습니다 — 원본
  프롬프트는 절대 보내지 않습니다.
- **원격 Cloud > 북마크 > Hub 순서.** 로그인된 Agentlas Web/커넥터 표면의
  `/hep-network`는 내 Agent Cloud 패키지를 먼저 찾고, 내가 저장한 Hub
  북마크를 다음으로 찾고, 마지막에 공개 Hub를 찾습니다. `/hep-cloud`는 계속
  Cloud 전용이며, 내가 만든 Cloud 단일 에이전트 재사용은 공개 Hub 호출과
  별도 가격으로 처리됩니다.
- **메모리 경계는 둘입니다.** 로컬 프로젝트 메모리는
  `~/.agentlas/networking/`에 남고 명시적인 내보내기 승인 없이는 컴퓨터 밖으로
  나가지 않습니다. Agentlas Web은 Cloud/Hub에서 빌려온 에이전트에 대해
  workspace-scoped 개인화 기록도 저장할 수 있습니다: 승격된 메모리 요약,
  승격된 플레이북, 플러그인 lock, retrieval receipt, 자가진화 제안입니다.
  원문 프롬프트, 전체 transcript, secret, credential 값, private local file은
  durable personalization으로 저장하지 않습니다.
- **영수증, 실행 아님.** 모든 라우팅 결정은 영수증(receipt)을 남깁니다.
  라우터는 에이전트나 Hub 번들을 고를 뿐이며, 실제 도구 실행 권한은 현재
  호스트 런타임이 처리합니다.
- **주장이 아니라 측정.** 라우팅 벤치마크(한국어 + 영어)가 자동 라우팅을
  게이트합니다: top-3 recall ≥ 90%, privacy suite에서 unsafe route 0건.
- **외부 명령은 여섯 개로 압축.** 외부 LLM 호스트에서는 `/hep-build`,
  `/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, `/hep-upload`만
  보입니다. Agentlas Terminal과 Agentlas 앱은 자연어 네이티브 표면이고,
  Stormbreaker, research loadout, `ao`, `network`, `cards`, `mcp` 같은
  하위 경로는 맥락에 따라 자동으로 붙거나 자동화/디버그용 내부 표면으로 남습니다.
- **임시 TF 라우팅.** 복합 요청은 필요할 때만 작업을 쪼개 Hub/local 후보와
  활성 세션을 묶은 TF 계획으로 반환합니다. 영수증에는 Stormbreaker packet,
  ontology graph path, Local Operator policy label, Memory/Playbook 후보가
  같이 남습니다.

### A2A Agent Card 경계

이번 A2A 업그레이드는 단순히 Hub 검색을 더 잘하는 기능이 아닙니다. 외부
에이전트 카드를 가져오고, 공개 가능한 카드로 내보내고, agent-to-agent 호출
권한을 라우팅 전에 막는 상호운용 경계입니다.

```bash
agentlas-cloud ao a2a import ./agent-card.json .
agentlas-cloud ao a2a export . --agent local/10-builder
agentlas-cloud route "release check 돌려줘" --caller local/orchestrator
```

- **import는 제안까지만.** 외부 A2A `AgentCard`는 `ExternalAgent` 제안과
  capability 정렬 edge만 만듭니다. import 단계에서는 절대 `can_invoke`를
  주지 않고, 깨진 JSON과 과도한 skill 목록도 막습니다.
- **export는 whitelist 기반.** 내부 agent는 `/.well-known/agent-card.json`
  공개 카드로만 투영합니다. private path, local memory 동작, raw routing
  card, 내부 policy rationale은 빠집니다.
- **호출은 caller-gated.** CLI `route --caller`와 MCP
  `hephaestus_route.caller_id`가 호출자 agent id를 라우팅 게이트에 전달해서,
  차단된 agent-to-agent 호출은 후보 선택 전에 그대로 차단됩니다.

자세한 내용: [docs/hephaestus-network-2.0.md](docs/hephaestus-network-2.0.md) ·
런타임 지원 매트릭스: [docs/runtime-fallback-adapters.md](docs/runtime-fallback-adapters.md)

---

## 한 줄 붙여넣기 설치 (AI에게 시키기)

터미널이 낯설다면 직접 실행할 필요 없습니다. AI 코딩 도구 아무거나 —
**Claude Code · Codex · Gemini CLI · Antigravity · Cursor** — 를 열고 아래
메시지를 챗박스에 그대로 붙여넣으세요. 에이전트가 대신 설치 스크립트를
실행하고, 다음에 쓸 정확한 명령을 알려줍니다.

```text
이 워크스페이스에 Hephaestus Agentlas 메타 에이전트를 설치해줘. GitHub 주소는 여기야:
https://github.com/agentlas-ai/Hephaestus

최신 릴리스/설치 안내를 기준으로 진행하고, 내가 쓰는 도구에서 활성화된 명령 경계를 알려줘. Agentlas Terminal/앱은 자연어 네이티브 도구로 동작하고, Claude Code, Codex, Gemini CLI, Antigravity, Cursor 같은 외부 LLM 호스트는 build/network/cloud/search/call/upload 여섯 명령만 보이게 확인해줘. 실패하면 에러를 읽고 고친 뒤 다시 시도해줘.
```

끝나면 Agentlas 안에서는 자연어로 말하고, 외부 LLM 호스트에서는 `/hep-build`,
`/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, `/hep-upload` 중 맞는
명령을 쓰세요. 직접 명령을 실행하고 싶으면 아래 터미널 **빠른 시작**을 씁니다.

---

## 빠른 시작

새 컴퓨터에서는 아래 경로 중 하나로 시작하세요. Claude Code나 Codex에서 쓰려면 플러그인 설치가 먼저입니다. 일반 프로젝트 폴더에 파일만 복사하고 싶을 때만 파일 설치를 쓰세요.

### 0. 새 macOS 확인

Claude와 Codex의 plugin marketplace 명령은 내부에서 `git clone`을 씁니다. 새 Mac에서는 `git`을 쓰려면 Apple Command Line Tools가 먼저 필요합니다. 터미널에 `xcode-select: note: No developer tools were found`가 보이면 아래를 한 번 실행하세요.

```bash
xcode-select --install
```

Apple 설치 팝업을 끝낸 뒤 새 Terminal 창을 열고 확인합니다.

```bash
git --version
```

`git --version`이 정상 출력된 뒤 Claude 또는 Codex 플러그인 설치 명령을 다시 실행하세요.

### 추천. 터미널 원터치 전체 설치/업데이트

아래 하나를 **OS 터미널**에서 실행합니다. Claude Code 플러그인, Codex
플러그인, Gemini CLI extension/custom command, Antigravity 워크플로를 한 번에
설치하거나 업데이트합니다. `Already added from a different source`처럼 기존
marketplace 출처가 꼬인 경우도 `agentlas-core-engine`만 제거 후 다시
등록해서 복구합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```

끝나면 열려 있던 Claude Code, Codex, Gemini, Antigravity 세션은 재시작하세요.
그 다음 이렇게 확인합니다.

```text
Claude Code: /reload-plugins 실행 후 /hep-build, /hep-network, /hep-cloud, /hep-search, /hep-call, /hep-upload
Codex:       /prompts:hep-build, /prompts:hep-network, /prompts:hep-cloud, /prompts:hep-search, /prompts:hep-call, /prompts:hep-upload
Gemini CLI:  /extensions list 또는 /commands list 확인 후 /hep-build, /hep-network, /hep-cloud, /hep-search, /hep-call, /hep-upload
Antigravity: 워크스페이스 다시 열고 /hep-build, /hep-network, /hep-cloud, /hep-search, /hep-call, /hep-upload
```

새 버전 업데이트도 같은 명령을 다시 실행하면 됩니다. main을 바로 받고
싶으면 아래처럼 실행합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | HEPHAESTUS_REF=main bash
```

### A. Claude Code 플러그인

Claude 채팅창이 아니라 **macOS Terminal, Windows PowerShell, Linux terminal, Git Bash, WSL 같은 OS 터미널**에서 실행합니다.

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```

그 다음 작업할 프로젝트 폴더에서 Claude Code를 열거나 재시작하고, Claude Code 안에 아래처럼 입력합니다.

```text
/reload-plugins
/hep-build ontology
```

이미 예전 `agentlas-meta-agent` 플러그인을 설치했는데 Claude에서 `hephaestus`를 못 찾는다고 나오면, marketplace를 새로 받고 예전 플러그인을 교체하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```

`/hep-build ontology`는 이제 메인 Agent OS 화면이 아니라 Knowledge/Memory 패널입니다. 프로젝트 소스, memory candidate, 재사용 가능한 playbook 재료를 확인할 때 씁니다. 왼쪽 네비게이션, Obsidian 스타일 지식 그래프, 소스 검색, GraphRAG 질문 빌더, Memory Candidate Queue, 복사 가능한 명령어 화면이 포함됩니다.

```text
.agentlas/ontology-inbox/
.agentlas/ontology-sources.json
.agentlas/ontology-runtime.sqlite
.agentlas/ontology-gui/index.html
```

홈 폴더나 옆 프로젝트를 훑지 않습니다. 승인된 회사 문서나 프로젝트 문서는 `.agentlas/ontology-inbox/`에 넣고 `/hep-build ontology`를 다시 실행하면 대시보드가 갱신됩니다.

에이전트나 팀을 만들 때는 설치 후 Claude Code 안에서 이렇게 입력합니다.

```text
/hep-build create a research agent for SEC filing analysis
/hep-build create a customer support operations team
/hep-build package this existing Claude agent into Agentlas architecture
```

Claude CLI는 `claude plugins ...`도 alias로 받지만, 이 문서에서는 헷갈리지 않게 `claude plugin ...` 단수형으로 통일합니다.

### B. Codex 플러그인

Codex 채팅창이 아니라 **OS 터미널**에서 실행합니다.

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v1.0.2
codex plugin add hephaestus@agentlas-core-engine
```

그 다음 작업할 프로젝트 폴더에서 Codex를 열거나 재시작하고, Codex 안에 아래처럼 입력합니다.

```text
/prompts:hep-build ontology
```

Codex 앱에 아직 `agentlas-meta-agent`로 보이면 marketplace를 새로 받고 예전 플러그인을 교체하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```

OS 터미널의 Codex CLI 명령은 `codex plugins`가 아니라 `codex plugin` 단수형입니다. Codex 앱 안의 slash command는 `/plugins` 복수형입니다. 플러그인 설치 후 `/prompts:hep-build ontology`를 실행하면 graph, sources, query, memory queue, command 화면이 있는 같은 프로젝트 로컬 대시보드가 만들어집니다.

```text
.agentlas/ontology-gui/index.html
```

에이전트나 팀을 만들 때는 설치 후 Codex 안에서 이렇게 입력합니다.

```text
/hep-build create a self-evolving research agent
/hep-build create a finance analyst team
/hep-build package this existing Codex workspace into Agentlas architecture
```

Agentlas가 새 agent나 team을 만들면 생성 시점에 전역 명령어도 같이
부여합니다. 완료 응답에는 Claude Code, Codex, Gemini CLI, generic
`AGENTS.md`, 터미널에서 쓸 `global_commands`가 반드시 나와야 합니다.
팀이면 이 공개 명령어는 orchestrator/HQ로 라우팅됩니다.

### C. 파일 복사 설치

Claude/Codex 플러그인이 아니라 현재 프로젝트에 패키지 파일만 복사하고 싶을 때 씁니다. 설치할 프로젝트 폴더에서 OS 터미널을 열고 실행합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Windows PowerShell:

```powershell
$zip = "$env:TEMP\hephaestus-main.zip"
$extract = "$env:TEMP\hephaestus-main"
Invoke-WebRequest "https://github.com/agentlas-ai/Hephaestus/archive/refs/heads/main.zip" -OutFile $zip
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $extract -Force
$src = Get-ChildItem $extract -Directory | Select-Object -First 1
Get-ChildItem $src.FullName -Force | Copy-Item -Destination (Get-Location) -Recurse -Force
```

파일 설치 후에는 slash command가 아니라 터미널에서 직접 실행합니다.

```bash
bin/hephaestus ontology
```

### D. 이미 Claude Code 채팅창 안에 있을 때

아래 명령은 OS 터미널이 아니라 Claude Code 채팅창 안에 그대로 입력하는 버전입니다.

Claude Code:

```text
/plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
/plugin install hephaestus@agentlas-core-engine
/reload-plugins
/hep-build ontology
```

Codex 앱 안에서는 `/plugin marketplace add`가 동작하지 않습니다. Codex는 OS 터미널에서 `codex plugin ...`으로 설치하고, 앱 안에서는 `/plugins`로 설치된 플러그인을 확인하세요. 설치 후에는 `/prompts:hep-build ontology`를 실행합니다.

설치 후 여섯 명령이 안 보이면 해당 프로젝트에서 Claude Code나 Codex를 재시작하세요.

## 그림으로 보는 설치 방법

Claude Code 안에 있다면 Claude slash command 그림을 따라 하세요. Codex는 OS 터미널에서 설치하고, Codex 앱 안에서는 `/plugins`로 설치된 플러그인을 확인합니다. macOS Terminal, Windows PowerShell, Linux terminal, Git Bash, WSL을 열었다면 CLI 그림을 따라 하면 됩니다.

### Claude Code 채팅창

Claude Code 안에 그대로 입력합니다.

![Claude Code chat install flow](assets/install-claude-code-chat.svg)

### OS 터미널의 Claude CLI

셸에서 `claude` 명령어가 되는 경우 이 경로를 씁니다.

![Claude CLI install flow](assets/install-claude-cli.svg)

### Codex 앱 플러그인 확인

OS 터미널에서 `codex plugin ...` 설치를 끝낸 뒤 Codex 앱 안에서 확인할 때 씁니다.

![Codex app plugin browser](assets/install-codex-chat.svg)

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
| Codex 설치 플러그인 확인 | Codex 앱 | `/plugins` |
| Codex 플러그인 shell 설치 | OS 터미널 | `codex plugin marketplace add ...`, `codex plugin add ...` |

## 설치 후 이렇게 씁니다 (3분 사용법)

설치가 끝나면 **agentlas Hub MCP도 함께 등록됩니다** — Claude Code는 플러그인에
번들된 `.mcp.json`으로, Codex/Antigravity는 원터치 설치 스크립트가,
Gemini CLI는 extension 매니페스트가 자동 처리합니다. 별도 MCP 등록이 필요 없습니다.

### 1. 어디서 입력하나

| 런타임 | 여는 법 | 그다음 |
|---|---|---|
| Claude Code | OS 터미널에서 `claude` 입력 (또는 데스크톱 앱 실행) | `/hep-build`, `/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, `/hep-upload` |
| Codex | OS 터미널에서 `codex` 입력 (또는 Codex 앱) | `/prompts:hep-build`, `/prompts:hep-network`, `/prompts:hep-cloud`, `/prompts:hep-search`, `/prompts:hep-call`, `/prompts:hep-upload` |
| Gemini CLI | OS 터미널에서 `gemini` 입력 | `/hep-build`, `/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, `/hep-upload` |
| Antigravity | 워크스페이스 열기 | `/hep-build`, `/hep-network`, `/hep-cloud`, `/hep-search`, `/hep-call`, `/hep-upload` |

`/hep-build`는 **생성**, `/hep-network`는 공개 Hub 에이전트
**빌리기**, `/hep-cloud`는 내 Agentlas Cloud 에이전트 **공유/사용**입니다.
`/hep-search`는 Cloud와 Hub 후보 비교, `/hep-call`은 지정 agent/team 호출 준비,
`/hep-upload`는 패키지 업로드입니다.
`/hep-upload`는 Cloud 비공개 업로드인지 Agentlas Hub 공개 업로드인지 먼저 묻습니다.
새 설치/업데이트는 예전 `/hephaestus` 채팅 명령을 보이는 목록에서 정리합니다.
Agentlas Terminal과 Agentlas 앱에서는 이 slash 명령을 직접 치지 않아도 자연어로
같은 흐름을 실행합니다.

### 2. MCP는 명령어가 아니라 자연어로 씁니다

MCP 도구는 직접 호출하는 명령이 아닙니다. 그냥 한국어(또는 영어)로 말하면
AI가 알아서 맞는 도구를 골라 실행합니다.

| 이렇게 말하면 | 내부에서 실행되는 도구 |
|---|---|
| "agentlas에서 ASO 도와주는 에이전트 찾아줘" | `agentlas.search` |
| "agentlas 마켓플레이스에 어떤 에이전트들 있어? 카테고리별로 보여줘" | `marketplace.search_agents` |
| "그 팀을 이 프로젝트에 설치해줘" | `agentlas.get_runtime_bundle` |
| "내 에이전트 목록 보여줘" (로그인 필요) | `cargo.*` |

로그인이 필요한 기능을 처음 쓰면 Hephaestus가 기본 브라우저를 열어
Agentlas/Google 로그인 화면으로 보냅니다. 한 번 로그인하면 그 로그인 상태가
Claude Code, Codex, Gemini, Antigravity 등에서 이어지므로 다시 설정할
필요가 없습니다.

등록이 잘 됐는지 확인하려면:

| 런타임 | 확인 방법 |
|---|---|
| Claude Code | 대화창에 `/mcp` → `agentlas` 서버와 도구 목록이 보이면 정상 |
| Codex | 터미널에서 `codex mcp list`; 내 에이전트 기능은 처음 사용할 때 브라우저 로그인이 자동으로 뜨면 정상 |
| Gemini CLI | 대화창에 `/mcp` 또는 터미널에서 `gemini mcp list` |

### 3. 어떤 에이전트가 있는지 모를 때

- 그냥 물어보세요: **"agentlas에 어떤 에이전트들이 있어?"**, **"내 앱 출시에 도움될 에이전트 추천해줘"** — 검색 도구가 알아서 돕습니다.
- 웹으로 훑어보려면: [agentlas.cloud/marketplace](https://agentlas.cloud/marketplace)
- MCP를 다른 클라이언트(Cursor, Windsurf, VS Code 등)에 수동 등록하려면: [agentlas.cloud/mcp](https://agentlas.cloud/mcp)

## 무엇을 만들어 주나

Hephaestus는 프롬프트 답변만 만들지 않습니다. 다른 런타임이 읽고, 설치하고, 검증하고, 계속 개선할 수 있는 repo를 남깁니다.

| 요청 | 라우팅 | 결과 |
|---|---|---|
| "X를 하는 단일 agent를 만들어줘" | `10-single-agent-builder` | skills, memory contract, runtime adapter, verification이 있는 단일 worker |
| "이 workflow용 팀/company를 만들어줘" | `20-multi-agent-team-builder` | HQ, PM Soul, Memory Curator, Policy Gate, eval, QA, handoff가 있는 멀티 에이전트 팀 |
| "이 기존 agent/repo/workspace를 패키징해줘" | `30-agentlas-packager` | Desktop import, terminal, Codex, Claude, Gemini, public GitHub release에 맞는 Agentlas 패키지 |

세 모드 모두 `.agentlas/global-commands.json`을 만들고, 생성 완료 후
사용자에게 정확한 전역 명령어를 알려줘야 합니다. 사용자가 새 agent를
어떻게 실행하는지 추측하게 두면 안 됩니다.

## 아키텍처

public core는 architecture/foldering contract입니다. Claude, Codex, Gemini, Desktop, Terminal 폴더는 같은 core 위의 얇은 adapter이며 별도 원본이 아닙니다.

| 공개 contract | 역할 |
|---|---|
| Mode auto-detection | `single-agent-creator`, `team-builder`, `agentlas-packager` 중 하나를 먼저 고릅니다. |
| Clarify question loop | runtime, 공개/비공개 경계, tools, safety에 영향 있는 질문만 합니다. |
| Global command registry | `.agentlas/global-commands.json`, runtime별 command 파일, 최종 `global_commands` 안내를 추가합니다. |
| `.agentlas` auto-activation | local runtime이 project memory, sitemap/task-bias, Memory Tickets, vault reference를 seed할 수 있게 합니다. |
| Skill lifecycle registry | skill을 candidate metadata로 시작하고 trial/Curator decision ledger를 둡니다. |
| Super Ontology candidate layer | source lineage, privacy, task coverage, causality, consensus, repair, reflexive feedback을 확인하는 공개 가능한 graph/memory governance 파일을 seed합니다. (현재 개발 단계) |
| Ontology-backed agent overlay | 문서 코퍼스에 의존하는 요청을 `ontology_backed: true`로 라우팅해, 빌더가 runtime을 활성화하고 검색-우선 워크플로우와 risk tier별 `loop_policy`를 설정합니다. |
| Rule-based contract injection | `.agentlas/contract-injection-map.json`이 작업 특성에 맞는 governance contract만 선택 주입합니다 (26개 일괄 주입 금지). |

기본 export는 보수적입니다. 생성된 skill은 바로 first-class recall이 되지 않습니다. Curator가 실행 증거, sealed holdout/replay, rollback, workspace policy를 확인해야 승격됩니다.

### Production Ontology Runtime

개인 자료나 회사 자료처럼 지식이 많은 agent/team을 만들 때 Hephaestus는 실제 local-first ontology runtime을 제공합니다. 원본 파일을 source archive에 넣고, chunk를 만들고, full-text/vector 검색과 graph relation을 저장한 뒤, GraphRAG 결과를 Memory Curator ticket과 Agent Working Memory cache로 연결합니다.

Super Ontology 파일은 현재 개발 중인 안전 규칙층입니다. 실제 저장/검색/graph/memory cache는 `ontology/`와 `bin/ontology`가 처리합니다.

**Hephaestus Network MCP 기능:**

- **`hephaestus_hub_invoke` MCP 도구.** Hephaestus Network가 이제 Hub 후보 검색에 그치지 않고 Agentlas Hub MCP(`marketplace.search_agents`, `agentlas.get_runtime_bundle`, `agentlas.resolve_plugins`)를 호출해 runtime bundle을 받고 실행 영수증을 `~/.agentlas/networking/ledgers/executions.jsonl`에 남깁니다.
- **Hub-only 로컬 우회.** `hub_only: true`와 `local_inventory: []` 조합으로 로컬 private/restricted/plugin 카드를 선택하거나 실행하지 않고 Hub 경로만 탑니다.
- **전역 Agentlas memory bootstrap.** Hub invocation이 `~/.agentlas/` 아래 공유 파일(`memory-map.json`, `project-soul-memory.md`, `invocation-ledger.jsonl` 등)을 missing-only로 만들고, raw prompt나 secret 없이 호출 증거만 append합니다.
- **Agentlas Web workspace 개인화.** `agentlas.get_runtime_bundle`은 retrieval
  ranking용 선택적 task context를 받고, 승격된 메모리, 승격된 플레이북,
  plugin lock, retrieval receipt id가 들어간 `personalization` 블록을 반환할
  수 있습니다. `agentlas.record_agent_memory`,
  `agentlas.record_agent_playbook`, `agentlas.propose_agent_evolution`은 후보만
  저장하고, durable behavior는 curator 또는 명시적 승인 후 승격됩니다.
- **설치 런타임 검증.** one-touch installer가 5개 런타임 표면을 검증하고, 중립 러너 `~/.agentlas/runtime/current/bin/hephaestus`를 최신으로 유지합니다.

**Ontology runtime 업그레이드:**

- **한국 문서 1차 파서 내장.** HWPX는 ZIP/XML에서 문단과 표 span을 직접 뽑고, legacy `.hwp`는 CFB `FileHeader`와 `BodyText/Section*` 스트림을 직접 읽습니다. GPL/AGPL 파서나 `hwp5txt` 바이너리가 필요 없습니다. 암호화되었거나 배포용으로 보호된 HWP는 명시적으로 차단합니다.
- **한국어 검색이 동작합니다.** tokenizer가 한국어/일본어/중국어 음절 bigram을 만들고 FTS 인덱스가 `trigram` tokenizer를 쓰므로, 제안서/계약서/견적서 같은 한국어 코퍼스(HWPX 포함)를 추가 설치 없이 검색합니다. 기존 DB는 처음 열 때 자동으로 마이그레이션·재색인됩니다.
- **RRF hybrid ranking.** full-text와 vector 순위를 고정 가중치 대신 Reciprocal Rank Fusion으로 결합하고, 후보 풀을 제한해 전체 코퍼스 Python 스캔을 없앴습니다.
- **호스트 LLM 검색 hook (옵션, 추가 비용 0).** Claude Code / Codex 같은 호스트 런타임이 쿼리 확장·rerank hook을 주입할 수 있습니다. embedding API/key가 필요 없고, private/confidential scope chunk는 cloud hook에 절대 전달되지 않습니다 (검색 파이프라인 안에서 강제).
- **Chunk overlap 15%.** 청크 경계에서 문맥이 잘리지 않습니다.
- **Ontology-backed agent mode.** 빌더가 검색-우선·출처 인용 에이전트를 생성합니다 (`modes/ontology-backed-agent.md`, 골든 패스 예시 `examples/ontology-proposal-agent/`). contract는 규칙 기반으로 주입되고 `loop_policy`(none / self-correct / verified)가 작업 위험도에서 결정됩니다.
- **Adapter drift 차단 + MCP 표면 검사.** `scripts/sync-adapters.sh --check`가 runtime adapter를 canonical core와 byte 단위로 일치시키고, `scripts/verify-mcp-surface.sh`가 `agentlas` MCP 등록 계약을 회귀 검사합니다.

| 층 | 역할 |
|---|---|
| Source archive / chunk store | 원본 파일 metadata, checksum, type, parser status, version, privacy scope, lineage, chunk span을 저장합니다. |
| Search / vector | SQLite FTS5(trigram, CJK 지원)와 CJK bigram token 기반 local hashing vector를 RRF로 결합합니다. 옵션으로 호스트 LLM 쿼리 확장/rerank hook을 쓸 수 있고, API key가 필요 없으며 원문이 밖으로 나가지 않습니다. |
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
| `.hwpx` | 1차 HWPX ZIP/XML adapter가 문단과 표 span을 남기며 parse |
| 이미지/OCR | macOS Vision OCR 또는 Tesseract가 있으면 parse |
| binary `.hwp` | 1차 HWP5 CFB/BodyText adapter로 parse, 암호화/배포보호 파일은 차단 |

이 hot working-memory layer는 source of truth가 아니라 cache입니다. 수십 GB 개인/회사 자료에서 context token을 줄이고, 빠르게 recall하고, 개인화 성능을 올리는 게 목표라면 이 층이 필요합니다.

## Agentlas Desktop과 Terminal을 같이 쓰면 좋은 점

- Desktop에서 agent/team 구조, local project, Apps, vault reference, runtime 선택을 볼 수 있습니다.
- Terminal에서 같은 package를 `agentlas` 명령으로 실행할 수 있습니다.
- Desktop/Terminal에는 Core Engine Meta-Agent 경로가 내장되어 있어 별도 standalone plugin 없이도 agent 생성과 패키징을 시작할 수 있습니다.
- Claude/Codex 단독 설치는 해당 런타임 안에 이 package를 직접 넣고 싶을 때 유용합니다.

## 비교

| 비교 대상 | 강점 | Hephaestus가 더하는 것 |
|---|---|---|
| OpenAI / Codex | 강한 모델과 coding terminal | portable repo contract, `.agentlas` memory/package files, skills, schemas, runtime adapters, public verification |
| Claude / Claude Code | 강한 추론과 Claude-native workflow | Claude-only가 아니라 Codex, Gemini, Desktop, Terminal, `AGENTS.md`까지 맞추는 구조 |
| OpenClaw | local identity와 workspace agent loop | visible role folders, Agentlas package contracts, public-safety checks, Desktop import, vault references |
| Hermes | persona와 memory 중심 local runtime | PM Soul, Memory Tickets, sitemap/task-bias, policy/eval/QA, skill lifecycle evidence |

OpenAI와 Claude는 model/runtime 표면입니다. OpenClaw와 Hermes는 local-agent 경험입니다. Hephaestus는 agent를 portable, inspectable, installable, publishable하게 만드는 package layer입니다.

## 사용 예시

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
