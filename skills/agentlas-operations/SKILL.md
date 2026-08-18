---
name: agentlas-operations
description: Agentlas 시스템 운용 절차 — hep-network 편성, hep-graph 자동화, cargo/Agent Cloud·marketplace 활용, workforce 로스터 재사용, 메모리 계약. One(개인 에이전트)이 Agentlas를 조작할 때 이 절차를 따른다.
---

# Agentlas 시스템 운용 (One 운용 스킬)

도구의 **존재와 이름은 이 문서가 아니라 [INDEX.md](INDEX.md)가 정본**이다(릴리스 빌드가
라이브 레지스트리에서 자동 생성 — 손 목록은 반드시 썩는다). 이 문서는 **절차만** 다룬다.

## 1. 편성 (hep-network) — 로스터 재사용이 항상 먼저

1. `workforce.goal_context`로 활성 로스터부터 확인한다. **재사용으로 충분하면 모집하지 않는다.**
2. 진짜 공백일 때만: 축약(redacted) 워크오더 1장 → `workforce.search_candidates`
   (`sourceScope=network` = local+cloud+hub 연합).
   - ⚠️ `requiredSkills`에 시드 온톨로지 ID를 걸면 실후보 전원이 가짜 결격을 단다(실측).
3. 선발은 **호스트 LLM이** 한다(연합은 점수 매기지 않는다) → `workforce.validate_selection`
   (연합 결과 원본 그대로 — 축약본은 거절됨) → `workforce.prepare_execution`(projectDir 필수).
4. 준비 성공은 자동으로 로스터에 바인딩된다. 바인딩은 명시적 `workforce.complete_goal`까지 유지
   — 24시간 Hub 리스는 과금 단위지 바인딩 종료가 아니다.
5. 소스 스코프는 정확하게: network=전체, local/cloud/hub는 제한 스코프이지 폴백 계층이 아니다.
6. **워커를 띄우기 직전마다** 살아 있는 세션을 알리고 `model.resolve_allocation`을 부른다
   (stage=`planner`/`worker`/`synthesis`/`verifier`). 영수증의 provider·model·effort를 그대로 쓴다.
   - 이건 편성뿐 아니라 **One이 스스로 워커를 나눌 때도** 적용된다. 한 모델로 다 하는 턴은
     배정할 것이 없으니 부르지 않는다 — 역할이 갈리는 순간에만 부른다.
   - 세션에는 `session_id`·`model`·`provider`를, 호스트가 아는 경우에만 `tier`·
     `supported_efforts`·`context_window`를 싣는다. **없는 값을 지어내지 않는다** —
     빠진 컨텍스트 창은 보수적 하한으로 가정되고 영수증이 그 사실을 밝힌다
     (`inventory_context_window_assumed`).
   - 오케스트레이터/워커 등급은 오퍼레이터가 `hep-orch orchestrator=<tier|model> worker=<tier|model>`로 정한다. 작업이나 도구 인자가 그 상한을 올릴 수 없다.

## 2. 자동화 (hep-graph)

- 반복 작업은 대화로 그래프를 만들어 저장한다(`/hep-graph`). 실행 중 승인 게이트는 없다
  (오너 결정 2026-08-09: 승인은 만들 때 한 번).
- "항상 허용"을 그래프 digest에 걸지 않는다 — digest가 바뀌면 바로 그 실행의 재개가 거부된다.
  사람의 결정은 실행 밖 기록에 둔다.

## 3. 자산 (cargo / Agent Cloud / marketplace)

- **내 서랍**: `cargo.*` (드래프트·라이브러리, 로그인 필요). 오너 자산 검색은 `/hep-cloud`.
- **공개 검색**: `marketplace.search_agents` (로그인 불필요) — kind가 `cloud-callable`이면
  `get_runtime_bundle`(BYOM: 내 모델이 번들을 실행, 서버는 LLM을 돌리지 않는다),
  `install-only`면 `get_manifest`로 설치.
- 도구가 안 보이면 단정 전에 `agentlas_resolve_plugins` — 미설치 ≠ 부재. 설치는 사용자 결정.
- 서버 거절(`insufficient_credits`·`owner_only` 등)은 그 문구 그대로 보고한다. 지정 원격
  에이전트를 로컬 폴백이 대신 실행한 척하지 않는다.

## 4. 메모리 계약 (One 워커로서)

- 작업 전 `agentlas.memory.preflight` — 아는 사실 재유도 금지.
- durable은 직접 쓰지 않는다. 답 끝의 `## Memory Events` 봉투가 유일한 기록 경로이고
  런타임이 티켓으로 포장한다. 근거 없는 fact/decision/procedure는 hypothesis로 강등된다.
- 앞선 durable을 **대체**하는 학습이면 candidate에 `"supersedes":"<h:16hex>"`를 넣는다
  (회수에서 숨겨질 뿐 삭제되지 않는다).
- One 서랍(`~/.agentlas/one/`)은 읽기 자유·쓰기 금지(D3) — 편집 시도는 PreToolUse가 거절한다.

## 5. 표면별 함정 (실측 기반)

- 플러그인 MCP 서버는 **세션 시작 때 캐시에서 로드**된다 — 릴리스 직후엔 새 세션에서 검증.
- 원격 서버는 관대하고 로컬 Core는 엄격하다(validate에는 연합 결과 원본 전체를 넘길 것).
- Hub 발행 503 `WRITE_MODE=blocked`는 서버 상태이지 패키지 결함이 아니다.
