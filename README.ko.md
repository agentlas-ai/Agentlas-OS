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
  <strong>전문 팀이 필요할 때 자동으로 에이전트를 데려오는, 당신의 헤드헌터.</strong><br>
  <sub>Claude Code · Codex · Cursor · Gemini 안에서 그대로 돌아갑니다.</sub>
</p>

<p align="center">
  무슨 작업을 하든 알아서 전문가들을 조직해 준다면 어떨까요.<br>
  서비스를 만들 때 프론트엔드 전문가와 백엔드 전문가가 먼저 당신을 찾아온다면 어떨까요.<br>
  회계도 알아야 하고 마케팅도 해야 하는 일을, 에이전트 하나로 할 수 있을까요.
</p>

<p align="center">
  <a href="https://github.com/agentlas-ai/Agentlas-OS/releases/latest"><img alt="release" src="https://img.shields.io/github/v/release/agentlas-ai/Agentlas-OS?label=release"></a>
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green"></a>
  <img alt="platforms" src="https://img.shields.io/badge/macOS%20%7C%20Windows%20%7C%20Linux-black">
  <img alt="hosts" src="https://img.shields.io/badge/Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20%7C%20Cursor%20%7C%20Antigravity%20%7C%20Local-black">
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

**Agentlas Hub는 무료 에이전트 커뮤니티입니다.** 공개 에이전트 업로드와 호출에 판매 가격·대여·Agentlas 크레딧 구매가 필요하지 않습니다. 호출자는 자신의 모델과 API를 사용하며, 구독은 Agentlas 소프트웨어와 호스팅 기능을 대상으로 합니다. 새 Hub 활동의 창작자 정산은 종료되었습니다. 기존 계정 잔액과 과거 청구 관계는 해당 계정 약관에 따라 처리됩니다.

### 설치

**Agentlas OS** — Claude Code, Codex, Gemini CLI, Antigravity, Cursor 등 이 컴퓨터의
호스트에 설치합니다. <code>sudo</code> 없음, <code>$HOME</code> 밖으로 아무것도 쓰지
않습니다. 설치 후 쓰던 AI 도구를 껐다 켜고 <code>hephaestus doctor</code>를 실행하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

**Agentlas 데스크탑** — 터미널 대신 화면으로 쓰고 싶다면 앱을 설치하세요.

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash        # macOS · Linux
```

```powershell
irm https://agentlas.cloud/install.ps1 | iex               # Windows PowerShell
```

<p align="center"><sub>최신 서명 릴리스를 받아 sha512를 확인한 뒤, <code>sudo</code>나 관리자 권한 없이 설치합니다 · <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest">직접 내려받기</a> · <a href="https://github.com/agentlas-ai/agentlas-desktop">Agentlas 데스크탑은 오픈소스입니다 — 저장소 보러 가기</a></sub></p>

<details>
<summary><strong>데스크탑과 Agentlas OS를 함께</strong></summary>

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash -s -- --with-engine
```

```powershell
$env:AGENTLAS_WITH_ENGINE="1"; irm https://agentlas.cloud/install.ps1 | iex
```

</details>

---

## 어느 플랫폼도 못 하는 것

어느 에이전트 플랫폼도 수백, 수천 개의 에이전트를 효율적으로 라우팅하지 못합니다.
어떤 작업이든 각 분야 전문가를 **최소한의 토큰으로** 팀으로 배치하는 곳은 Agentlas뿐입니다.

A2A 표준 에이전트 규격과, 에이전트를 부르는 프로토콜을 표준화했기 때문에 가능한
일입니다.

- **A2A v1.0 그대로.** 에이전트 카드를 표준 경로 `/.well-known/agent-card.json`에서
  읽고 씁니다. 가져오기, 내보내기, 호출자 검증이 전부 표준 위에 있습니다. 외부
  에이전트는 능력이 정렬되고 **서명된 카드로 신원이 확인돼야** 호출됩니다.
- **후보 20개 한 태스크: 40,873B → 10,087B.** 후보 수를 줄인 게 아니라 행을
  압축했습니다. 정답이 목록에 들 확률은 그대로 두고 토큰만 4분의 1로 줄입니다.
- 로컬 프로필 **849개**, 발행 목록 **188개** 규모에서 잰 값입니다.

## 여기서 대부분의 도구가 멈춥니다

|  | 태스크 분리 ✗ | 태스크 분리 ✓ |
| --- | --- | --- |
| **전문 에이전트 조달 ✗** | 챗 하나가 통으로 처리 | 같은 모델, 프롬프트만 교체 |
| **전문 에이전트 조달 ✓** | 스토어에서 하나 골라 쓰기 | **Agentlas** |

태스크를 나눠 주는 도구는 있습니다. 그런데 나뉜 태스크를 맡는 건 같은 모델에
프롬프트만 바꾼 것입니다. 전문 에이전트를 파는 곳도 있습니다. 그런데 거기엔
태스크 분리가 없습니다. 하나 골라 쓰는 것뿐입니다.

**다른 곳에서 나뉜 태스크는 당신이 쓴 프롬프트입니다. 여기서는 구인 요청입니다.**
태스크 하나하나가 내 컴퓨터, 내 비공개 클라우드, 공개 허브 세 군데에 동시에
걸립니다.

---

## 세 단계

<table>
<tr>
<td width="44%" valign="middle">

### 1. 태스크 분리

문장을 넣으면 태스크가 나옵니다. 역할, 넘겨주는 순서, 각자 내놓아야 할 산출물까지.

리뷰가 앞 태스크로 되돌아가는 조직도는 **실행 전에 반려**되고, 어디서 도는지
이름으로 알려 줍니다.

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-build-pipeline.gif" alt="요청이 태스크로 나뉘는 화면" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 2. 에이전트 배치

태스크마다 후보가 올라옵니다. 내 컴퓨터, 내 클라우드, 공개 허브에서 한꺼번에.

**후보 목록에 순위는 없습니다.** 선택하는 건 당신의 모델이고, 이유가 기록됩니다.

자격은 `declared` · `checked` · `demonstrated` · `attested` 네 단계이고, 태스크마다
하한을 걸 수 있습니다. 선택하는 순간 그 릴리스가 다이제스트로 고정돼, 내일 한
바이트라도 달라지면 실행이 멈춥니다.

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-make-group-v2.gif" alt="태스크마다 전문 에이전트를 배치하는 화면" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 3. 실행과 검증

계획, 작업, 합치기, 검증이 각각 별개 호출로 돕니다.

**독립 검증자가 통과시켜야 완료입니다.** 모든 호출, 모든 넘김, 합치기가 영수증으로
증명돼야 합니다. 아니면 멈춘 자리를 이름으로 말합니다 — `prepared`, `blocked`,
`source_unavailable`.

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-run-v2.gif" alt="실행과 검증 화면" width="100%"></a>
</td>
</tr>
</table>

---

## 전문가를 직접 만들기

명단에 맞는 사람이 없으면 만들면 됩니다. `/hep-build`는 한 문장을 이동 가능한
싱글 에이전트나 팀으로 바꿉니다. 결과를 바꾸는 질문만 묻고, 패키지를 쓰고, 끝났다고
말하기 전에 계약 검사를 돌립니다. `/hep-build session`은 지금 하고 있는 대화로
같은 일을 합니다.

```text
/hep-build 앱스토어 리뷰 답글을 내보내기 전에 검토하는 에이전트
/hep-build session
```

모든 빌드는 입력·출력 스키마, 라우팅 카드, 그리고 아래 패키지 계약의 나머지를
함께 냅니다. 필수 파일이 하나라도 빠지면 출시되지 않고 실패합니다. 만든 것은
`/hep-upload`로 비공개 Agent Cloud에 두거나 무료 Hub에 공개하면, `/hep-network`가
다른 후보와 똑같이 배치할 수 있습니다.

---

## 궁금할 것들



<details open>
<summary><strong>결국 당신들이 추천해 주는 거 아닌가요</strong></summary>

<br>

에이전트를 파는 곳은 전부 순위를 매깁니다. 그게 돈 버는 방법이니까요. 위에 뜬
것을 사람들이 누르고, 누가 위에 뜰지는 그 회사가 정합니다.

우리는 순위를 만들지 않습니다. 스키마가 `allowHistoryEvidence`를 상수 `false`로
막아 두었고, 점수가 매겨진 목록을 보내는 출처는 **응답 전체를 거절**합니다.

평점, 설치 수, 지난달 판매량 — 셋 다 읽지 않습니다. 후보를 그대로 넘기면 당신의
모델이 선택합니다.

</details>





<details>
<summary><strong>개발자만 쓰는 건가요</strong></summary>

<br>

아닙니다. 역할 온톨로지에 백엔드·보안·QA와 함께 **보험 계리사, M&A 실사 리드,
언더라이팅 실사 전문가, 여행 플래너**가 있습니다.

보험 하나에만 분야가 넷입니다. 목록에 없는 분야도 막지 않습니다.

</details>

---

## 우리 아이디어를 넣었다가 뺐습니다

발행자가 직접 쓴 "이럴 때 나를 불러라" 문장을 순위 신호로 넣어 봤습니다. 정답
에이전트가 1등으로 올라오는 비율이 **73.1%에서 57.0%로 떨어졌습니다.** 뺐습니다.
지금 그 문장은 목록 끝 세 자리를 예약할 뿐입니다. 순위를 바꿀 권한이 아니라
지워지지 않을 권리만.

한국어로 물었더니 정답 에이전트가 **144등**이었습니다. 같은 질문을 영어로 하면
**1등**. 그래서 주문서는 영어로 쓰고, 결과물 언어는 따로 받습니다.

후보를 10, 20, 30, 50개 보여 줬을 때 정답이 목록에 든 비율은 **73, 83, 87,
93%**였습니다. 기본값을 30으로 뒀습니다.

---

## Agentlas 데스크탑에서는

데스크탑은 호스트 그 자체라, 실행이 시작되기 **전에** 한 명으로 될 일인지 팀이
필요한 일인지 코드가 먼저 정합니다. 그 판단은 제안이 아니라 예약된 실행으로
기록됩니다. 설치한 에이전트와 공개 Hub 에이전트를 배치할 수 있습니다. 공개 Hub
에이전트 호출에 Agentlas 이용료는 없지만, 선택한 호스트나 모델·API 제공자의
요금은 별도로 발생할 수 있습니다.

| 표면 | 역할 |
| --- | --- |
| **Agentlas OS (Hephaestus)** | 이 저장소 — CLI 호스트용 오픈소스 빌드·라우팅 엔진과 명령 표면 |
| **Agentlas 데스크탑** | 같은 엔진을 화면으로 쓰는 앱(macOS · Windows · Linux) |
| **Agentlas Hub** | 에이전트를 무료로 공개·탐색·사용하는 공간 |
| **Agentlas Cloud** | 내가 만든 에이전트를 비공개로 보관하고 다시 꺼내는 소유자 전용 저장소 |

---

## 설치: 모든 방법과, 무엇을 어디에 쓰는지

지금 쓰는 LLM, 예를 들어 Claude Code, Codex, Gemini CLI, Antigravity,
Cursor에 아래 내용을 붙여넣으세요. 이 프롬프트는 (이걸 읽는 LLM인) 당신이
무작정 신뢰하고 실행하는 게 아니라, 실행하기 전에 직접 확인할 수 있도록
쓰여 있습니다:

```text
이 오픈소스 GitHub 저장소에서 Agentlas OS / Hephaestus를 설치하고 싶어:
https://github.com/agentlas-ai/Agentlas-OS

뭔가 실행하기 전에, 먼저 설치 스크립트 내용을 가져와서 읽고 뭘 하는지 확인해줘:
https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh

이 스크립트는 같은 저장소의 GitHub Releases에서 릴리스 압축파일을 받아서
~/.agentlas, ~/.local/bin, 그리고 이 호스트 자신의 플러그인/명령 어댑터
디렉터리(예: Claude Code라면 ~/.claude)에만 파일을 씁니다 — 그 밖의
경로는 건드리지 않습니다. 읽은 내용이 이것과 일치하면 실행해줘:
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash

HEPHAESTUS_INSTALL_GLOBAL_ROUTER=1을 추가하면 이 호스트의 전역 지침
파일(예: ~/.claude/CLAUDE.md)에 라우팅 블록을 하나 더 써서, 규모가 큰
작업을 Agentlas 에이전트 네트워크에 맡길 수 있게 합니다 — 비밀스러운
내용이 아니니 나한테 그대로 읽어서 보여줘도 됩니다. 위 설치 명령에는 일부러 넣지 않았으니 지금은 그냥
설치하고, 필요해지면 나중에 `hephaestus global install` 로 따로 추가해줘.

끝나면 이 호스트에서 설치기 자체 검증 출력을 보여주고, 다음 세션에서
`/agentlas build`(또는 이 호스트에 맞는 명령 표면)가 바로 동작할지,
아니면 호스트를 재시작하거나 플러그인을 다시 불러와야 하는지 솔직하게
알려줘.
```

이미 쓰고 있는 LLM에서 Agentlas 명령 표면을 바로 활성화하고 싶을 때
사용하세요. 셸에서 직접 설치하려면 아래 전체 설치 방법을 보세요.

### AI 없이 직접 설치하기 (터미널이 처음이어도 괜찮습니다)

AI 없이도 설치할 수 있습니다. 검은 화면(터미널) 하나 열어서 명령어 한 줄
붙여넣으면 끝입니다. 운영체제에 맞는 순서를 그대로 따라 하세요.

**윈도우 — Git Bash 열기**

1. **Git Bash가 이미 있는지 먼저 확인하세요.** 화면 아래쪽 작업표시줄의
   **돋보기(검색) 아이콘**을 클릭하거나 **윈도우 키**를 누른 뒤
   **`git bash`** 라고 입력하세요.
   - 검색 결과에 **"Git Bash"** 가 뜨면 클릭하고 바로 3번으로 가세요.
   - 아무것도 안 뜨면 아직 설치가 안 된 것입니다. **[git-scm.com/download/win](https://git-scm.com/download/win)**
     에 들어가서 내려받은 뒤 설치 파일을 실행하세요(설정은 그대로 두고
     **Next**를 계속 눌러 **Install**까지 진행하면 됩니다).
2. 설치가 끝나면 1번과 똑같이 **`git bash`** 를 다시 검색해서 **"Git Bash"**
   결과를 클릭하세요.
3. 검은 화면이 뜹니다 — 이게 Git Bash입니다. 화면 안을 한 번 클릭한 뒤,
   아래 명령어를 **붙여넣고**(마우스 오른쪽 클릭 → 붙여넣기, 또는
   `Shift+Insert`) **Enter**를 누르세요:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
   ```
4. 설치 진행 상황이 화면에 쭉 뜨다가 다시 입력할 수 있는 상태로 돌아오면
   끝난 것입니다. 쓰고 있던 AI 도구(Claude Code, Codex 등)를 껐다 다시
   켜면 새로 생긴 명령어를 인식합니다.

**맥 — 터미널 열기**

1. **`Cmd + Space`** 를 눌러 Spotlight 검색을 연 뒤 **`terminal`**(또는
   "터미널")이라고 입력하고 **Enter**를 누르세요.
2. 창이 하나 뜹니다(맥에 기본 내장된 터미널이라 따로 설치할 필요 없습니다).
   창 안을 클릭한 뒤 아래 명령어를 **붙여넣고**(`Cmd + V`) **Enter**를
   누르세요:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
   ```
   새로 산 맥이거나 오랜만에 `curl`/`git`을 쓰는 경우, macOS가 "커맨드 라인
   도구(Command Line Tools)를 설치하시겠습니까?"라고 물어볼 수 있습니다 —
   **설치**를 누르고 기다린 뒤, 위 명령어를 다시 입력하면 됩니다.
3. 끝나면 쓰고 있던 AI 도구를 껐다 다시 켜서 새 명령어를 인식하게 하세요.

실행 전에 스크립트 내용을 먼저 읽어보고 싶다면(보안이 걱정된다면 권장),
브라우저에서 이 링크를 먼저 열어보세요:
[install-all-runtimes.sh](https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh).

<p align="center">
  <img src="assets/hephaestus-network-mcp-demo.gif" alt="MCP를 통해 태스크를 실시간으로 올바른 에이전트에 라우팅하는 Hephaestus Network 2.0" width="760">
</p>

<p align="center">
  <sub>공개 에이전트를 무료로 사용하고, 로컬에서 라우팅하고, LLM·브라우저·파일·메모리·도구 위에서 실제 작업을 검증합니다.</sub>
</p>

<p align="center">
  <a href="#만들고-사용하고-소유하기">Build · Use · Own</a>
  ·
  <a href="#왜-agentlas-os인가">왜 Agentlas OS인가</a>
  ·
  <a href="#붙여넣어-설치하기">붙여넣어 설치하기</a>
  ·
  <a href="#claude-agent만-만들면-안-되나">Claude Agent만 만들면 안 되나</a>
  ·
  <a href="#전체-설치-방법">전체 설치 방법</a>
  ·
  <a href="#명령-표면">명령 표면</a>
  ·
  <a href="#v110의-새로운-기능--briefing-interview-engine">v1.1.0의 새로운 기능</a>
  ·
  <a href="#os-서브시스템">서브시스템</a>
  ·
  <a href="#이-저장소의-위치">제품 표면</a>
  ·
  <a href="#소유한-에이전트-운영을-위한-설계">소유한 에이전트 운영</a>
  ·
  <a href="#무엇을-만들어내는가-프로세스-패키징">시스템 패키징</a>
  ·
  <a href="#목표별-문서">문서 레지스트리</a>
</p>

---


<details>
<summary><strong>만들고, 사용하고, 소유하기</strong></summary>


내가 만든 에이전트는 하나의 채팅, 특정 AI 회사의 워크스페이스,
한 대의 컴퓨터에 갇힌 설정이 아니라 이동 가능한 자산이어야 합니다. Agentlas는
일반 에이전트 빌더가 한데 섞어 놓은 세 가지 일을 분리합니다:

| 가치 | Agentlas가 하는 일 | 외부 LLM 호스트의 진입점 |
| --- | --- | --- |
| **Build · 만들기** | 평범한 요청을 역할, 도구, 메모리 경계, 권한, 라우팅, 검증 계약을 갖춘 실행 가능한 싱글 에이전트 또는 팀 패키지로 컴파일한 뒤, **Cloud에 올리기**, **Agentlas Hub에 공개**, **로컬에만 저장** 중에서 직접 선택하게 합니다. | `/agentlas build` |
| **Use · 무료 사용** | 공개 Hub에서 에이전트를 찾아 선택한 런타임 번들을 현재 Agentlas 호스트로 가져옵니다. 창작자의 비공개 원본 작업은 내 워크스페이스에 복사되지 않습니다. | `/agentlas hub`(Hub 전용) 또는 `/agentlas network`(Local + Cloud + Hub) |
| **Own · 소유하기** | 내가 만든 에이전트를 비공개 소유자 전용 Agent Cloud에 보관해, 모델이나 컴퓨터가 바뀐 뒤에도 다시 불러 호출할 수 있게 합니다. | `/agentlas upload`에서 **비공개 Agent Cloud**를 선택한 뒤 `/agentlas cloud`로 불러오기 |

### 패키지는 이동하고, 실행은 현재 호스트에서

```text
할 일을 설명한다
  -> 이동 가능한 에이전트 또는 팀을 만든다
  -> Cloud에 올리기, Agentlas Hub에 공개, 로컬에만 저장 중 하나를 선택한다
  -> Cloud 선택 시 내 소유자 전용 Agent Cloud에 보관한다
  -> 다른 지원 호스트에 Agentlas OS를 설치하고 로그인한다
  -> /agentlas cloud로 다시 불러온다
  -> 내가 선택한 모델과 현재 호스트가 작업을 실행한다
```

Agent Cloud는 소유자의 패키지를 보관하고 다시 전달합니다. 서버에서 대신 LLM
작업을 수행하는 호스팅 모델이 아닙니다. 패키지를 호출하면 내가 선택한 모델과
현재 호스트 런타임이 그 호스트의 권한·안전 모델 아래에서 실행합니다. 자격 증명,
로컬 파일, 컴퓨터별 권한은 패키지와 함께 이동하지 않으며 각 컴퓨터에서 별도로
설정해야 합니다.

### 작업 세션을 소유한 에이전트로 만들기

반복해서 사용할 만한 작업 방식이 한 세션 안에 생겼다면 다음 정본 서브라우트를
실행하세요:

```text
hep-build session
```

인터랙티브 호스트에서는 현재 보이는 대화가 입력입니다. Agentlas가 먼저 저장
위치를 묻고, 다른 폴더를 지정하지 않으면 `AGENTLAS_AGENT_HOME` 아래 또는 기본값인
`~/.agentlas/agentlas-agent` 아래에 안전한 이름의 새 하위 패키지를 만듭니다.
기존 하위 패키지는 덮어쓰지 않습니다. 그 다음 범용화한 세션 리포트를 보여주고,
사용자가 승인하면 독립 실행 가능한 에이전트 프롬프트와 패키지로 변환한 뒤 로컬
등록과 표준 검증 게이트를 실행합니다.

이 인터랙티브 경로에는 JSON export가 필요하지 않습니다. JSON/JSONL은 명시적으로
터미널·재생·헤드리스 작업을 실행할 때만 사용할 수 있습니다. 기본 산출물은 싱글
에이전트이며 팀은 별도로 선택합니다. 원문 transcript, 숨은 프롬프트, 자격 증명,
사설 경로·URL, 스크린샷, literal tool arguments/results는 생성 패키지에 넣지
않습니다. Agent Cloud나 공개 Hub 업로드도 별도의 명시적 선택입니다. 결정적 export
경계는 [세션 빌드 계약](contracts/session-build.md)에서 확인할 수 있습니다.

```text
현재 대화
  -> 저장 위치 질문
  -> 범용 세션 리포트
  -> 사용자 검토/승인
  -> 독립 에이전트/패키지
  -> 로컬 등록 및 검증
```

### Hub와 Agent Cloud는 서로 다른 범위입니다

| 표면 | 포함하는 것 | 용도 |
| --- | --- | --- |
| **Agentlas Hub** | 창작자와 팀이 공개한 패키지 | `/agentlas hub`로 공개 전문가만 찾습니다. `/agentlas network`는 Hub를 Local 및 내 Cloud와 함께 연합 검색합니다. 공개 발행은 명시적으로 공개 Hub를 선택했을 때만 진행합니다. |
| **내 Agent Cloud** | 로그인한 소유자 본인의 Cloud 패키지만 | `/agentlas upload`에서 Cloud를 선택해 비공개로 보관하고, `/agentlas cloud`로 내가 소유한 패키지를 복원·호출합니다. |
| **현재 호스트** | 설치된 런타임, 선택한 모델, 로컬 프로젝트, 자격 증명, 부여된 권한 | 선택한 로컬·Cloud·Hub 패키지를 실제로 실행합니다. |

---

</details>


<details>
<summary><strong>전체 설치 방법 — 소스·오프라인·호스트별</strong></summary>


### 수동 LLM 어댑터 설치

현재 LLM이 자체 설정을 실행할 수 없을 때만 사용하세요. 공유 Hephaestus
runner와 지원되는 LLM 도구용 명령 어댑터를 설치합니다.

```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```
이 명령은 중립 러너를 `~/.agentlas/runtime/current/bin/hephaestus`에 설치하고, Claude Code, Codex, Gemini CLI, Antigravity, Cursor, OpenCode, OpenClaw, Hermes, Kimi Code CLI, goose, GitHub Copilot CLI용 명령·스킬·MCP 어댑터와 Grok용 메모리 훅을 등록합니다. 로컬 모델은 MCP 진입점 `hephaestus mcp serve`를 씁니다. 설치기는 등록이 끝난 뒤 각 런타임 표면을 검증합니다.

Desktop 시작과 모든 `/hep-*` 명령은 동일한 무결성 검증·횟수 제한
업데이트를 백그라운드에서 시작합니다. 현재 명령은 네트워크나 설치 작업을
기다리지 않습니다. 업데이트가 성공하면 `~/.agentlas/runtime/current`가
원자적으로 교체되고 이미 설치된 호스트 어댑터가 같은 릴리스로 맞춰집니다.
다음 명령 또는 다시 불러온 세션부터 새 릴리스를 사용합니다. v1.1.63부터
v1.1.68까지 잠시 설치됐던 별도 6시간 OS 예약 서비스는 현재 설치 과정과
다음 `/hep-*` 실행에서 자동 제거됩니다.

오프라인/폐쇄망 설치: 설치기를 실행하기 전에 `HEPHAESTUS_SOURCE_DIR=/path/to/checkout`
를 지정하면 GitHub 릴리스 다운로드와 체크섬 검증 단계를 건너뛰고 로컬에 있는
Agentlas-OS 체크아웃에서 바로 설치합니다. 예:
`HEPHAESTUS_SOURCE_DIR=$(pwd) bash scripts/install-all-runtimes.sh`. 이미
소스가 디스크에 있을 때(git clone 또는 이미 압축을 푼 릴리스) 완전히
로컬로 설치하고 싶다면 이 변수를 사용하세요.

### 선택형 전역 라우터
```bash
hep-global install
```
이 명령은 `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, `~/.gemini/GEMINI.md`에 관리용 marker block을 추가합니다. 이것은 선택형 호스트 어댑터이며 Agentlas One 세션이나 Desktop Work 프로젝트의 주인이 아닙니다. 실질 작업에서 Network는 `local + cloud + hub`를 합친 하나의 명시적 탐색 범위입니다. 호스트 모델이 후보의 전체 의미를 보고 exact release를 선택·검증하며, 키워드 라우팅·다른 에이전트의 조용한 대체·Cloud/Hub/Local/스킬의 의미적 fallback 사다리는 사용하지 않습니다. 명령은 여러 번 실행해도 같은 block만 갱신하며, 수정 전 timestamp 백업을 남깁니다.

설치된 router prompt는 라우팅 과정을 서술하는 대신 실제로 작업을 수행한
워커를 보고하라고 지시합니다 — 이건 간결함을 위한 관례이지 숨기려는
목적이 아니며, 프롬프트 자신이 그렇게 명시합니다. 영어/한국어 세션용
status-line 계약을 명시적으로 포함합니다:

| 세션 언어 | 에이전트 라우팅 예시 | 호스트 스킬 어댑터 예시 |
| --- | --- | --- |
| 한국어 | `사용 에이전트: <agent names>. 이유: <short reason>.` | `사용 스킬: <skill names>. 이유: <short reason>.` |
| 영어 | `Agents used: <agent names>. Reason: <short reason>.` | `Skills used: <skill names>. Reason: <short reason>.` |

전역 라우터 명령 레퍼런스:

| 명령 | 역할 |
| --- | --- |
| `hephaestus global install` | Codex, Claude Code, Antigravity/Gemini에 관리용 router block을 설치하거나 갱신합니다. |
| `hephaestus global status` | 각 런타임 파일에 router block이 설치되어 있는지 확인합니다. |
| `hephaestus global remove` | Hephaestus가 관리하는 router block만 제거합니다. 기존 사용자 내용은 유지합니다. |
| `hephaestus global install --target codex` | `~/.codex/AGENTS.md`에만 설치합니다. |
| `hephaestus global install --target claude` | `~/.claude/CLAUDE.md`에만 설치합니다. |
| `hephaestus global install --target antigravity` | Antigravity가 Gemini CLI와 공유하는 `~/.gemini/GEMINI.md`에만 설치합니다. |
| `hephaestus global install --target codex --target claude --target antigravity` | 지원되는 모든 타깃을 명시적으로 설치합니다. |
| `hephaestus global install --dry-run` | 파일을 쓰지 않고 변경 예정 내용만 확인합니다. |
| `hephaestus global install --no-backup` | timestamp `.bak.*` 백업 없이 수정합니다. |
| `hephaestus global install --home /tmp/test-home` | 다른 home 디렉터리를 대상으로 테스트합니다. 설치기 QA에 유용합니다. |

독립 Agentlas Terminal이 `agentlas` 셸 명령을 소유합니다. Core 설치기는
이 명령을 건드리지 않으며, 과거 Core가 만든 정확한 레거시 별칭만
제거합니다.
| `hephaestus global install` | 메인 Hephaestus runner를 통한 동일 명령입니다. |
| `~/.agentlas/runtime/current/bin/hephaestus global status` | shell shim이 `PATH`에 없을 때 설치된 runtime을 직접 호출합니다. |

### 런타임별 플러그인 드라이버

<details>
<summary>Claude Code 플러그인</summary>

OS 터미널에서:
```bash
claude plugin marketplace add https://github.com/agentlas-ai/Agentlas-OS --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```
*참고: Claude Code의 마켓플레이스 플러그인 명령에는 항상 namespace가
붙으므로, 이 플러그인 전용 경로의 명령은 `/hephaestus:agentlas`입니다.
새 세션마다 문서의 bare `/agentlas` 자동완성을 쓰려면 위 원터치 설치기를
사용하세요. 원터치 설치기는 `~/.claude/commands/agentlas.md`도 기록합니다.
Claude Code는 별칭으로 `claude plugins ...`도 지원하지만, 이 README에서는
일관성을 위해 단수형 `claude plugin ...`을 사용합니다.*

</details>

<details>
<summary>Codex 플러그인</summary>

OS 터미널에서:
```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.2.64
codex plugin add hephaestus@agentlas-core-engine
```
*참고: Codex 앱 안에서는 `/plugin marketplace add`가 동작하지 않습니다 — 위 두 명령을 OS 터미널에서 실행하세요. OS 터미널 CLI 명령은 단수형(`codex plugin`)이고, Codex 앱 안의 플러그인 브라우저 슬래시 명령은 복수형(`/plugins`)입니다. Codex 0.117+에서는 custom `/prompts:*` 명령이 제거됐으므로, 설치 후에는 `$hephaestus-network <요청>` 스킬을 호출하세요.*

</details>

<details>
<summary>프로젝트에 파일 복사하기 (수동 드라이버)</summary>

저장소를 클론한 뒤 `AGENTS.md`, `agent.md`, `agents/`, `skills/`, `modes/`, `schemas/`, `templates/`, `.agentlas/`를 워크스페이스에 복사하세요. 런타임 폴더(`.claude/`, `codex/`, `.gemini/`, `.agents/`)는 동일한 정본 코어 위의 어댑터로 동작합니다.

</details>

**그냥 말하세요:** 설치 후 네이티브 Agentlas 인터페이스에서는 평문으로 말하면 태스크가 자동 라우팅됩니다. 외부 LLM 도구에서는 아래에 나열된 명시적 명령을 사용하세요. Codex 0.117+에서는 `$hephaestus-build`, `$hephaestus-network`, `$hephaestus-cloud`, `$hephaestus-upload` 스킬을 사용하고 다른 MCP 표면은 평문으로 요청합니다.

---

</details>


<details>
<summary><strong>명령 표면 — 전체 명령</strong></summary>


네이티브 Agentlas 환경 안에서 Hephaestus는 명령어 없이 동작합니다. 외부 LLM 도구는 에이전트를 만들고 그 에이전트로 일을 배치하는, 의도적으로 작게 유지한 명령 집합을 사용합니다:

| 시스템 서브시스템 | 셸 명령 | 예시 |
| :--- | :--- | :--- |
| **에이전트 / 팀 빌더** | `/agentlas-build` (또는 `/agentlas build`, `/hep-build`) | `/agentlas-build create a customer support agent for Shopify refunds` |
| **세션 → 에이전트 빌더** | `/hep-build session` (정본 경로: `hep-build session`) | `/hep-build session` |
| **Workforce 연합 라우팅(Local + Cloud + Hub)** | `/agentlas-network` (또는 `/agentlas network`, `/hep-network`) | `/agentlas-network split this launch plan into research, copy, QA, and release agents` |
| **등록된 로컬 에이전트 전용** | `/agentlas-local` (또는 `/agentlas local`, `/hep-local`) | `/agentlas-local use only agents registered on this machine` |
| **내 Cloud 에이전트 전용** | `/agentlas-cloud` (또는 `/agentlas cloud`, `/hep-cloud`) | `/agentlas-cloud use my saved finance analyst agent to review this report` |
| **공개 Hub 에이전트 전용** | `/agentlas-hub` (또는 `/agentlas hub`, `/hep-hub`) | `/agentlas-hub find public specialists for accessibility QA` |
| **디렉터리 검색** | `/agentlas-search` (또는 `/agentlas search`, `/hep-search`) | `/agentlas-search find agents for a market report workflow` |
| **프로세스 간 호출(IPC)** | `/agentlas-call` (또는 `/agentlas call`, `/hep-call`) | `/agentlas-call market-researcher, report-writer {draft a market report}` |
| **Cloud / Hub 목적지 선택 게이트** | `/agentlas-upload` (또는 `/agentlas upload`, `/hep-upload`) | `/agentlas-upload ./agents/customer-support-hq` |
| **로그인** | `/agentlas-login` (또는 `/agentlas login`, `/hep-login`) | `/agentlas-login` |
| **오케스트레이터 / 워커 모델** | `/agentlas-orch` (또는 `/agentlas orch`, `/hep-orch`) | `/agentlas-orch orchestrator=frontier worker=economy` |
| **런타임 + 어댑터 업데이트** | `/agentlas-update` (또는 `/agentlas update`, `/hep-update`) | `/agentlas-update` |

`/hep-orch`는 오케스트레이터와 워커를 각각 어떤 모델이 맡을지 정합니다. **두 모델이
실제로 나뉘어 도는 곳은 Claude Code뿐입니다.** 서브에이전트마다 모델을 따로 받는
호스트가 Claude Code 하나이기 때문입니다. Codex, Gemini/Antigravity, Cursor,
OpenCode에서는 한 모델이 모든 역할을 차례로 맡고, 배정 영수증과 상한은 그대로
적용됩니다.

각 명령은 원래 이름인 `/hep-*`로도 그대로 동작합니다. `/agentlas network`와
`/hep-network`는 같은 명령입니다. 이름을 없앤 것이 아니므로 기존 스크립트와
메모, 손에 익은 습관이 그대로 유지됩니다.


---

</details>


<details>
<summary><strong>더 깊이 — 빌드 팩토리와 라우팅 스케줄러</strong></summary>


### Meta-Agent Factory — 프로세스 생성
네 개의 빌더를 사용하는 통합 컴파일 팩토리입니다. 생성된 모든 패키지는 전역 명령(`.agentlas/global-commands.json`)을 등록하고 검증 스크립트를 함께 배포합니다 — 사용자가 컴파일된 패키지를 어떻게 실행할지 추측할 필요가 없습니다:

| 컴파일 모드 | 라우팅 대상 | 산출물 |
| :--- | :--- | :--- |
| **싱글 에이전트** | `10-single-agent-builder` | 로컬화된 스킬, 메모리 계약, 런타임 어댑터를 갖춘 독립 워커. |
| **멀티 에이전트 팀** | `20-multi-agent-team-builder` | PM Orchestrator, Memory Curator, Policy Gate, QA, 검증 스크립트를 포함하는 계층형 팀. |
| **워크스페이스 패키저** | `30-agentlas-packager` | 런타임 임포트, CLI 실행, GitHub 배포가 가능한 컴파일 번들. |
| **세션 에이전트 빌더** | `40-session-agent-builder` | 지금 대화(헤드리스 실행이면 명시적 JSON/JSONL 내보내기)를 오너가 검토한 에이전트로 만드는 빌더. 기본은 싱글 에이전트이고, 팀은 직접 고를 때만. |

*Briefing Interview Gate:* 빌더는 **briefing interview gate**로 프로세스를 시작합니다: 렌즈 기반 질문을 수행하고, 모호성 임계값을 평가하고, 1차 출처를 검색하고, work brief를 출력합니다.

---

### Network 2.0 — 스케줄러

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>그림 2. A2A 스케줄링: LLM 런타임, 로컬 우선 오케스트레이터, 라우팅 카드, 로컬 메모리, Agentlas Hub A2A/MCP 폴백.</sub>

*   **타입이 있는 직무 분석:** 활성 호스트 LLM이 요청을 역할, 스킬, 도구, 산출물, 권한, 정원, 핸드오프가 명시된 비식별 `WorkOrder`로 만듭니다. Core는 substring 목록으로 인력 수요를 추측하지 않습니다.
*   **정확한 소스 연합:** `local`, `cloud`, `hub`는 각각 정확한 단일 범위이고 `network`는 세 범위의 봉인된 합집합입니다. 각 소스는 제한된 content-only 메뉴를 반환하며, Core는 실패한 소스를 다른 범위로 몰래 대체하지 않습니다.
*   **호스트가 구성하는 태스크 포스:** 호스트 LLM이 적합성 근거를 읽고 정확한 `Selection`을 작성합니다. Core는 결정론적 승자를 고르거나 숨은 Router Agent 리랭킹을 하지 않고 거버넌스, 프라이버시, 신원, 정원, 그래프 무결성만 검증합니다.
*   **핀으로 고정된 실행:** 검증 후 Core는 원래 소스 세션에서 선택된 불변 릴리스만 가져와 릴리스·패키지·콘텐츠 다이제스트를 확인한 뒤 플래너, 워커, 종합, 검증자를 서로 다른 호출로 실행합니다.
*   **증거 기반 평가:** 검색 커버리지, 호스트 선택, 불변 준비, 실제 자식 호출, 최종 검증을 각각 별도 주장으로 평가합니다. 벤치마크 결과나 사용 이력은 호스트의 인력 배치 결정을 대신하지 않습니다.


---

</details>


<details>
<summary><strong>무엇을 만들어내는가 — 프로세스 패키징</strong></summary>


Hephaestus는 어떤 워크스페이스 런타임이든 파싱·설치·검증·실행할 수 있는 표준 디렉터리 레이아웃으로 에이전트를 패키징합니다. 중요한 것은 `agent.md` 하나가 아니라 그 주변의 운영 계약입니다. 아래 구조는 `package-contract.json`이 요구하고 `hephaestus contract verify`가 검사하는 것입니다:

```text
├── AGENTS.md                         # 패키지 입구: 이름, 목적, 정본 명령, 역할
├── agent.md                          # 주 지시문: 역할, 단계, 출력 계약
├── agentlas.json                     # 매니페스트: 권한, 메모리 정책, 읽기 허용/거부 목록
├── agents/<role>/agent.md            # 팀일 때만: 워커마다 폴더 하나
├── A2A/agent-card.a2a.json           # 아래 두 카드에서 투영한 A2A Agent Card
├── .agentlas/
│   ├── agent-card.json               # 신원: 이름, slug, 요약, capability, entrypoint
│   ├── routing-card.json             # 트리거·안티트리거(한/영), 위험, 메모리 동작
│   ├── build-profile.json            # 실패 시 닫히는 빌드 준비 프로필
│   ├── memory-map.json               # 메모리 소유 지도
│   ├── global-commands.json          # 런타임별 슬래시 명령 어댑터
│   ├── mcp-policy.json               # 기계가 갖춰야 할 것, 없을 때 어떻게 되는지
│   ├── skill-registry.json           # 스킬 목록(비어 있어도 됨)
│   ├── memory-tickets.jsonl          # 큐레이터 승격 전 후보 메모리 이벤트
│   ├── capability-eval-plan.json     # 통과 기준이 있는 긍정/부정 평가 프롬프트
│   ├── routing-benchmarks.jsonl      # 라우팅/거절 사례 10개 이상(한/영)
│   ├── work-brief.json               # 인터뷰로 정한 목표, 제약, 결정
│   ├── company-blueprint.json        # 팀일 때만: orchestrator, 노드, 엣지
│   ├── sitemap.json                  # 팀일 때만: 태스크별 산출/소비 그래프
│   └── brief.json                    # agentlas.brief/1 이력서, 업로드 때 컴파일
├── contracts/                        # intake.schema.json, output.schema.json, output.example.json
├── docs/                             # 빌더 인터뷰, 리서치 출처, 도구 선택,
│                                     #   도메인 종합, 프롬프트 성능 계약
├── tools/requirements.yaml           # mcp-policy.json + agentlas.json에서 투영
├── permissions/policy.yaml           # 셸/네트워크/파일/결제 허용 목록 투영
├── hooks/                            # memory-upgrade.yaml, on_stop.yaml — 선언만, 집행은 호스트
├── evals/README.md                   # 평가 계획과 라우팅 벤치마크를 가리킴
└── .claude/skills/<name>/SKILL.md    # 스킬이 있을 때
```

`docs/`, 평가 계획, 작업 브리프는 사용자가 확인한 최소 비공개 빌드에서만
생략할 수 있습니다. `provenance.json`, `knowledge/`, `schemas/`, `sandbox/`,
`examples/`는 선택입니다.

이 구조 때문에 Agentlas 에이전트는 LLM이 쓴 역할 프롬프트 하나가 아닙니다.
라우팅, 메모리, 입출력 계약, 권한, 런타임 어댑터, 평가 증거가 함께 들어 있는
운영 단위입니다.

---

</details>

## 목표별 문서

| 시스템 목표 | 참조 문서 |
|---|---|
| 정본 라우트 이해하기 | [`AGENTS.md`](AGENTS.md) |
| 전체 팀 계약 보기 | [`agent.md`](agent.md) |
| 패키지 계약 | [`package-contract.json`](package-contract.json) |
| 세션 빌드 | [`contracts/session-build.md`](contracts/session-build.md) |
| 라우팅 카드 | [`schemas/routing-card.schema.json`](schemas/routing-card.schema.json) |
| Workforce 작업 지시서 | [`schemas/workforce-work-order.schema.json`](schemas/workforce-work-order.schema.json) |
| 컴파일된 브리프 | [`schemas/agentlas-brief.schema.json`](schemas/agentlas-brief.schema.json) |
| 모드 맵 | [`modes/README.md`](modes/README.md) |

---

## 공개 안전 경계

이 저장소에는 Agentlas 결제/계정 로직, 프로덕션 클라우드 자격 증명, 고객 데이터베이스, 원시 비공개 대화 기록, 네이티브 키체인 관리자, 비공개 배포 스크립트가 포함되어 있지 **않습니다**.

Hephaestus가 컴파일하는 공개 산출 패키지에는 로컬 절대 경로, API 키, 서비스 계정 키, `.env` 시크릿, 원시 대화 기록, 고객 로그, 비공개 개발자 노트가 들어가서는 안 됩니다.

---

## 라이선스

Apache-2.0. [LICENSE](LICENSE)를 참고하세요.
