# Hephaestus Network 2.0 — 구현 계획 (v1 draft, 2026-06-12)

상태: **설계안 v1.1 — Codex 설계 리뷰 반영 완료. 사용자 승인 전 구현 금지.** (리뷰 결과: §12)
작성 근거: 2026-06-12 5개 영역 코드 검사 (Forge, Hephaestus repo, agentlas_desktop, AgentsAtlas Hub, 런타임 등록 관행).

---

## 0. 검사 결과 요약 (증거)

| 영역 | 현재 상태 | Network 2.0 관점 갭 |
|------|----------|---------------------|
| Forge `restricted` (74개) | 100% `agent-card.json` 보유, `protocolVersion: a2a-1.0-draft`, `capabilities.tools/runtimeTargets` | trigger_examples / anti_triggers / risk_tier 없음 |
| Forge `private` (12개) | 100% 카드 보유, orchestrator/governance/workers 구조 | 카드 스키마가 restricted 계열과 불일치 (id/runtime vs urlPath/runtimeTargets) |
| Forge `plugin/` (24개) | `plugin.json` 정적 카탈로그 | 라우팅 카드 자체가 없음 |
| Hephaestus repo | `schemas/agent-card.schema.json` (최소 필드, `additionalProperties: true`), `agentlas_cloud/plugin_discovery.py` (로컬 우선 + `https://agentlas.cloud/api/plugins` 머지, 오프라인 폴백) | routing-card 스키마·라우터·`~/.agentlas/networking/` 미구현 |
| agentlas_desktop | `electron/agents/auto-router.ts` 키워드 스코어링 라우터(한글 지원), SQLite `installed_agents`, `surface-trust.ts` 승인 게이트 | 라우팅 카드 미연동, 라우팅 영수증 없음 |
| AgentsAtlas Hub | `POST /api/mcp/v1` `marketplace.search_agents` (무인증, ko/en 토크나이저), `cloud-agents/v1/register` (보안 차단 패턴), OAuth RFC 9728 | routingCard 필드·폴백 승인 게이트 미구현 |
| 런타임 등록 | `global-commands.json` 계약 + `install-all-runtimes.sh` (Claude/Codex/Gemini/Antigravity 4종 검증됨) | Cursor 미지원, /hep-network 별칭 없음, 글로벌 init 훅 없음 |

핵심 결론: **새로 발명할 것은 적다.** 기존 3개의 독립 라우팅/검색 구현(desktop auto-router, Hub catalog, plugin_discovery)을 하나의 카드 표준 + 글로벌 레지스트리로 수렴시키는 작업이다.

---

## 1. 목표 아키텍처

```
사용자: /hephaestus <자연어 요청>   (Claude Code · Codex · Gemini · Antigravity · Cursor · 터미널)
        │
        ▼
[Hephaestus Network Router]  agentlas_cloud/networking/router.py  (결정론적, LLM 불필요)
  1. 명시적 명령/별칭 매치 (global-commands 레지스트리)
  2. 프로젝트 .agentlas/routing-overrides.json
  3. ~/.agentlas/networking/registry.sqlite 의 로컬 라우팅 카드 검색·스코어링
  4. required_plugins 해석 (plugin_discovery 재사용)
  5. confidence 高 + risk 低 → 로컬 실행 준비 / confidence 中 → 명확화 질문
  6. 로컬 무매치 → Hub MCP marketplace.search_agents (승인 후)
  7. Hub 무매치 → 신규 에이전트 생성 제안 (기존 meta-agent 3모드로 라우팅)
        │
        ▼
[Routing Receipt] ledgers/routing-decisions.jsonl  +  승인 게이트  +  실행
```

원칙:
- **로컬 우선**: 모든 단계는 오프라인에서 동작. Hub는 폴백이며 매 호출 사용자 승인(최초 1회 grant 기록).
- **메모리는 로컬**: 능력(capability)은 Hub에서 올 수 있지만 사용자/프로젝트 메모리는 명시적 승인 없이 절대 외부 전송 금지.
- **카드 없으면 자동 라우팅 없음**: `routing_status < routing_ready` 카드는 검색 결과에만 노출, 자동 실행 차단.

## 2. 글로벌 구조 `~/.agentlas/networking/`

사용자 제안 구조를 그대로 채택하되 2가지 보강:

```
~/.agentlas/networking/
  config.json                # schemaVersion, locale, hub endpoint, telemetry off 기본
  sources.json               # ★ 명시적 등록 경로만. 홈 폴더 스캔 절대 금지
  registry.sqlite            # 카드 인덱스(FTS5: trigger/anti-trigger/capability 토큰, ko+en)
  cards/{agents,teams,plugins}/<id>.json
  policies/{routing-policy.json, capability-policy.json, approval-policy.json}
  memory/{routing-profile.json, hierarchical-memory-map.json, feedback.jsonl}
  ledgers/{routing-decisions.jsonl, executions.jsonl, capability-grants.jsonl}
  cache/{hub-search.jsonl, plugin-index.json}
  VERSION                    # ★ init 스키마 버전 (업그레이드 마이그레이션 판단용)
```

- `sources.json` 초기값: Hephaestus 설치 경로, `~/.claude/plugins/cache`, `~/.codex/plugins/cache`, `~/.gemini/extensions` — 즉 **이미 설치된 패키지 위치만**. Forge 같은 사용자 폴더는 `hephaestus network add-source <path>`로 명시 등록해야만 인덱스됨.
- 생성 주체: `bin/hephaestus network init` (멱등). 호출 지점 ①`install-all-runtimes.sh`/`install.sh` 말미 ②라우터 첫 호출 시 lazy-init ③업그레이드 시 `VERSION` 비교 후 마이그레이션.
- `registry.sqlite`는 캐시다 — 진실의 원본은 `cards/*.json` + 각 패키지의 `.agentlas/routing-card.json`. sqlite 삭제 시 재빌드 가능해야 함.
- **동시성 계약 (Codex 리뷰 반영)**: 여러 런타임(Claude Code/Codex/Gemini)이 동시에 쓸 수 있으므로 ① SQLite `WAL` 모드 + `busy_timeout` + 트랜잭션 단위 리빌드, ② 카드 JSON은 `tmp 작성 → fsync → rename` 원자적 쓰기, ③ JSONL 원장 append는 `fcntl` flock 보호 (경합 빈도가 높아지면 sqlite ledger 테이블로 승격), ④ `network init`은 디렉토리 단위 lock 파일로 중복 초기화 방지.

## 3. 라우팅 카드 스키마 v2 — `schemas/routing-card.schema.json` (신규)

```jsonc
{
  "schemaVersion": "routing-card/2.0",
  "id": "restricted/researcher-001-public-safe-marketplace-packager",  // <tier>/<slug> 네임스페이스
  "type": "agent | team | plugin",
  "name": "...", "name_ko": "...",                // i18n 1급 필드 (한국어 커버리지 요건)
  "summary": "...", "summary_ko": "...",
  "description": "...",
  "capabilities": ["package_public_marketplace_item", "scan_secrets"],  // 동사형 강제 (verb_object 패턴 검증)
  "trigger_examples": [ {"text": "마켓플레이스에 올릴 수 있게 패키징해줘", "locale": "ko"}, ... ],  // ready 기준 ≥5, ko+en 각 ≥2
  "anti_triggers": [ {"text": "단순 코드 리뷰", "locale": "ko"}, ... ],   // ready 기준 ≥3
  "required_inputs": [ {"name": "target_path", "type": "path", "description": "..."} ],
  "optional_inputs": [...],
  "required_plugins": [ {"id": "...", "min_permissions": ["read_fs"]} ],  // wrong-plugin 방지: 최소권한 선언
  "supported_runtimes": ["claude-code", "codex", "gemini-cli", "antigravity", "cursor", "terminal", "agents-md"],
  "entrypoints": { "canonical_command": "/...", "agent": "agents/.../agent.md", "terminal": "bin/...", ... },
  "risk_profile": { "tier": "low|medium|high",
    "capabilities_at_risk": ["file_write","cloud_call","payment","publish","delete","private_data_export","external_tool"] },
  "approval_requirements": ["file_write", "cloud_call"],   // risk_profile에서 도출, 명시적 오버라이드 가능
  "memory_behavior": { "reads": "project|none", "writes": "project|none", "exports_to_cloud": false },
  "cloud_delegation_policy": "never | ask | allowed_with_grant",
  "cost_hints": { "model_calls": "low|medium|high", "paid_api": false },
  "benchmark_fixtures": "benchmarks/routing/<id>.jsonl",   // ready 기준 ≥10 케이스
  "known_failure_cases": ["..."],
  "card_quality_score": 0.0,        // verify-routing-cards가 계산·기록
  "routing_status": "draft | searchable | candidate | routing_ready | trusted",
  "source": { "kind": "local_path|hub", "ref": "...", "package_hash": "...", "package_version": "..." },
  "updated_at": "ISO8601",

  // --- Codex 리뷰 반영 추가 필드 ---
  "card_version": "2.0.0",            // 카드 계약 semver (패키지 버전과 독립)
  "revision": 1,                       // 단조 증가 — 로컬 충돌 해소
  "canonical_id": "...",              // 로컬/Hub/경로 변경에도 안정적인 dedupe 키
  "aliases": ["..."],                 // 개명된 에이전트·명령 별칭
  "supersedes": ["..."],              // 마이그레이션/폐기 체인
  "agent_card_ref": { "path": ".agentlas/agent-card.json", "slug": "...", "content_hash": "..." },  // 카드 간 드리프트 방지
  "integrity": { "content_hash": "...", "signature": null, "signing_key_id": null },  // 변조 탐지·Hub 신뢰
  "locale_coverage": { "primary": "en", "ready": ["en","ko"], "partial": [] },  // ko/en 준비도 기계 검증
  "routing_status_reason": "...",     // draft/quarantined 사유 명시
  "data_access": { "reads": ["project_memory"], "writes": [], "exports": [] },  // memory_behavior보다 정밀한 선언
  "approval_scope": { "grant": "per_call|session|project|global", "ttl_seconds": null },  // 모호한 영구 grant 방지
  "quality": { "score": 0.0, "lint_version": "...", "evaluated_at": "...", "benchmark_suites": [] }  // card_quality_score의 감사 가능 버전
}
```

설계 결정:
- **기존 `agent-card.json`을 대체하지 않는다.** `routing-card.json`은 패키지의 `.agentlas/`에 나란히 추가되는 별도 파일 (A2A draft 카드와 역할 분리: agent-card=신원/설치, routing-card=라우팅 시그널). Hub 등록 시 manifest에 `routingCard` 필드로 동봉.
- 광범위 generalist 페널티: `capabilities` 항목 수 > 12 또는 `do_anything`류 동사 휴리스틱 → `card_quality_score` 감점 + 라우터 스코어링에서 breadth penalty.
- 품질 게이트(`routing_ready` 최소 요건)는 사용자 요구사항 그대로: trigger≥5, anti≥3, 동사형 capabilities, required_inputs 선언, risk 선언, entrypoints 실재 검증, 벤치마크≥10, memory_behavior 선언. 검증기: `scripts/verify-routing-cards.sh` + `agentlas_cloud/networking/card_lint.py`.

## 4. 라우터 설계 — `agentlas_cloud/networking/` (신규 Python 패키지)

| 모듈 | 역할 |
|------|------|
| `bootstrap.py` | `network init`/업그레이드/마이그레이션, sources 인덱싱 (등록 경로만) |
| `card_store.py` | cards/ ↔ registry.sqlite 동기화, FTS5 인덱스 (ko/en 토크나이저는 Hub `catalog.ts` 필러 목록 포팅) |
| `card_lint.py` | 스키마 검증 + 품질 점수 + routing_status 게이트 |
| `router.py` | 7단계 파이프라인 (§1), 결정론적 스코어링: trigger 매치(+), anti-trigger(−), capability verb 매치(+), breadth penalty(−), risk·plugin 최소권한 게이트 |
| `receipts.py` | routing-decisions.jsonl 영수증: **정규화 토큰·후보·점수·결정만 기록, 원문 프롬프트 미저장** |
| `hub_fallback.py` | Hub MCP `marketplace.search_agents`/`agentlas.resolve_plugins` (무인증 공개 도구) 호출, `cache/hub-search.jsonl` 캐시, 오프라인 시 캐시→로컬 전용 강등 |
| `approvals.py` | capability-grants.jsonl, 7대 고위험 캐퍼빌리티 승인 게이트 (런타임이 사용자에게 질문을 던지도록 구조화된 `approval_request` 반환 — 라우터 자체는 UI 없음) |
| `memory.py` | routing-profile.json (선호/교정 구조화 요약), feedback.jsonl. 나쁜 라우팅 강화 방지: 교정은 카드 점수가 아닌 사용자별 boost/suppress 목록에 기록, 벤치마크 통과 없이 카드 자체 승급 금지 |

CLI (bin/hephaestus 확장): `network init|status|add-source|remove-source|reindex|route "<요청>" [--dry-run]|cards lint|bench`.

신뢰도 정책 (routing-policy.json 기본값): top1 점수≥T_high이고 top2와 마진≥M → 실행 준비, T_low~T_high → 명확화 질문 (후보 ≤3 제시), <T_low → Hub 폴백 제안. 한국어/영어 요청 모두 동일 파이프라인 (필러 제거 토크나이저 ko/en).

루프 방지: receipt에 `hop_count`·`router_chain` 기록, 라우터→라우터 위임 시 hop>2 차단. 삭제된 에이전트: reindex 시 source 경로 부재 카드는 `stale` 마킹 후 자동 라우팅 제외.

Codex 리뷰 반영 보강:
- **개별 격리(quarantine)**: malformed 카드는 해당 카드만 `quarantined`(+`routing_status_reason`) 처리하고 인덱싱을 계속한다. 카드 1장 때문에 전체 인덱스가 중단되는 일 금지.
- **조용한 라우팅 공백 방지**: `network status`가 ready/searchable/draft/quarantined 카운트를 항상 보고하고, `routing_ready` 카드 수와 벤치마크 통과가 최소 임계치(기본: ready ≥5, seed suite pass) 미달이면 자동 라우팅을 "enabled"로 표기하지 않고 명시적 안내를 낸다.
- **한국어 토크나이저**: `plugin_discovery.py`의 단순 `.split()` 재사용 금지. 기존 `ontology/embeddings.py`의 CJK bigram/trigram 방식을 포팅해 ko 쿼리 ↔ en-only 카드 매칭 열화를 줄인다. `locale_coverage`가 `ko` 미포함인 카드는 ko 쿼리에서 confidence 상한을 낮춰 clarify로 유도.

## 5. 메모리 / 프라이버시 설계

- 기존 프로젝트-로컬 `.agentlas/` 메모리 아키텍처(memory-map, tickets, curator)를 **대체하지 않고 글로벌 계층 1개를 위에 추가**: `hierarchical-memory-map.json`이 `user_global(networking) → project(.agentlas/) → session` 계층과 소유자/승인 규칙을 선언.
- 글로벌 메모리 admission 규칙 (Memory Curator 규율 준용): 구조화 요약·선호·교정만. 원문 프롬프트, 비밀, 파일 내용, 트랜스크립트 금지. `receipts.py`/`memory.py`에 시크릿 패턴 필터 (desktop `curator.ts` 필터 포팅).
- 클라우드 위임 시: `memory_behavior.exports_to_cloud=false`(기본)인 카드가 프로젝트 메모리를 읽는 상태에서 cloud 후보가 선택되면 → **unsafe route로 차단**하고 명시적 export 승인 플로우만 허용. 프라이버시 픽스처로 회귀 테스트 (MVP 기준 "0 unsafe cloud delegation").
- 첫 사용 런타임이 init하면 이후 모든 런타임이 동일 `~/.agentlas/networking/`을 재사용 (단일 진실 원본, 런타임별 사본 금지).
- **라우터 결정 밖 우회 경로 차단 (Codex 리뷰 반영)**:
  - *Hub 검색 쿼리 누출*: Hub 폴백 시 원문 요청을 그대로 보내지 않는다. 시크릿 패턴 필터 + 정규화된 토큰/요약만 전송하고, 전송 전 1회 사용자에게 전송 내용 표시·승인. `cache/hub-search.jsonl`에도 동일 정제본만 기록.
  - *클라우드-가능 플러그인의 로컬 호출*: `required_plugins.min_permissions`에 `network` 권한이 있으면 위임 정책과 무관하게 plugin network-risk 체크를 통과해야 함.
  - *과소 선언 카드*: `data_access` 선언과 entrypoint 패키지의 실제 manifest(allowRead 등)를 lint에서 교차 검증, 불일치 시 quarantine.
  - *집행 지점*: 차단은 라우터 판단만이 아니라 실행 직전(executor/approvals 레이어)에서 한 번 더 강제. 쿼리 누출·우회 시나리오는 privacy 픽스처에 회귀 테스트로 포함.

## 6. 런타임 등록 계획

| 런타임 | 자동 등록 | 방식 | 비고 |
|--------|-----------|------|------|
| Claude Code | ✅ | 기존 플러그인 + `~/.claude/commands/hephaestus*.md` symlink. `/hep-network` 명령 파일 추가 | 검증됨 |
| Codex | ✅ | `codex/plugins/.../commands/hep-network.md` 추가 | 검증됨 |
| Gemini CLI | ⚠️ 부분 | extension + `hep-network.toml`. TOML 생성은 설치 스크립트가 수행 | 폴백: `~/.gemini/commands/` 직접 복사 |
| Antigravity | ✅ | `antigravity/workflows/hep-network.md` + global_workflows 복사 | 다중 소스 엔진 해석 이미 내장 |
| Cursor | ⚠️ 신규 | `cursor/rules/hephaestus.mdc` 어댑터 신규 작성 + 프로젝트 `.cursor/rules/` 설치. 슬래시 명령 미지원 → `@Hephaestus` 트리거 규칙으로 폴백 | 이 머신엔 Cursor 미설치, 어댑터만 출하 |
| 터미널 | ✅ | `bin/hephaestus route "<요청>"` + `hephaestus "<요청>"` 단축 | |
| Gemma/로컬 모델, Hermes류 | ⚠️ 문서 폴백 | 자동 등록 불가 → `AGENTS.md` generic 섹션 + `docs/runtime-fallback-adapters.md`에 수동 설치 가이드 | 현실적 한계 명시 |

`@Hephaestus <요청>` 형태는 명령 등록이 안 되는 런타임의 공통 폴백 (AGENTS.md 계약에 명시).

## 7. private/restricted/plugin 마이그레이션 계획

1. `agentlas_cloud/networking/card_migrate.py` (신규): 기존 `agent-card.json` + `AGENTS.md` + `manifest.json`에서 routing-card v2 **초안(draft)** 자동 생성. trigger/anti-trigger는 자동 생성하되 품질 게이트 미달이므로 전부 `routing_status: draft`로 시작 — **자동 라우팅에 즉시 노출되지 않음** (안전 기본값).
2. 기존 패키지 소스에서 `hephaestus cards migrate private/ restricted/ plugin/` 1회 실행 → 110개 draft 카드.
3. 시드 승급: MVP용으로 대표 카드 ~15개(private 12 + restricted 3)를 수동 검수해 trigger/anti/벤치마크 작성, `routing_ready`로 승급. 나머지는 `searchable`.
4. 패키저(`agents/30-agentlas-packager`)·single/team 빌더의 출력 계약에 routing-card 생성 의무 추가. `verify-package.sh` 카드 게이트는 **2단계 도입** (Codex 리뷰 반영): Hub 서버가 routingCard를 수용하기 전까지는 `warn`, Hub 지원 랜딩 후 `block`으로 승격 — 기존 발행 파이프라인이 조기에 멈추는 것을 방지.
5. Hub 측(별도 저장소 작업): `cloud-agents/v1/register`가 manifest의 routingCard를 스키마 검증, `marketplace.search_agents` 응답에 routing_status 포함. — *이번 구현 범위에서는 Hephaestus repo의 계약 문서와 클라이언트만, Hub 서버 변경은 후속 PR.*

## 8. 벤치마크 계획 — `benchmarks/routing/`

- 시드 셋: `seed.jsonl` ≥120 케이스 (승급 카드 15개 × 8 + 엣지 케이스). 각 케이스 `{query, locale, expected: {top1, top3_any, action: route|clarify|hub|refuse}, tags}`.
- 러너: `agentlas_cloud/networking/bench.py` + `bin/hephaestus network bench` → 지표: top-1 accuracy, top-3 recall, clarify rate, unsafe route rate, wrong plugin attachment rate, latency(p50/p95), hub fallback correctness, ko/en 커버리지 분리 리포트.
- 프라이버시 픽스처: `privacy.jsonl` — 로컬 메모리 노출 위험 시나리오, 기대값 전부 `refuse_or_ask`. CI 게이트: unsafe=0.
- 엣지 픽스처: 유사 에이전트 다수 매치(마진 게이트), generalist 포획(breadth penalty), 과대권한 플러그인, Hub 오프라인, stale/malformed 카드, 삭제된 에이전트 캐시, 라우터 루프, 모호한 결제/삭제/공개 요청(=clarify 강제), ko→en-only 카드 매핑.
- 통과 기준(MVP): top-3 recall ≥90%, unsafe=0, malformed 카드 자동 라우팅 차단 100%.

## 9. 브랜딩 (GitHub 공개 표면)

- 대상: `README.md` + ko/zh-CN/ja/hi 4개 번역본, `docs/` 사용자 문서, manifest 설명 문구.
- 포지셔닝: 제목 "Hephaestus — Network 2.0" 부제 *"Local-first agent & plugin networking: call your agents from any AI runtime, route by standardized cards, keep memory on your machine."* 기존 정체성(메타 에이전트 포지) 유지, Network을 신규 레이어로 소개.
- 내부 전용 용어(PM Soul, super-ontology 계약명, AppBridge 등)는 사용자-facing 카피에서 배제. 사용자 언어: "routing cards", "local memory", "Hub fallback", "approval gates".
- 게시는 별도 승인 후 (push 금지 제약 준수).

## 10. 구현 체크리스트 (파일 단위)

**Phase 0 — 계약/스키마 (행동 변화 없음)**
- [ ] `schemas/routing-card.schema.json` 신규
- [ ] `docs/hephaestus-network-2.0.md` (사용자-facing 계약), `docs/runtime-fallback-adapters.md` 신규
- [ ] `docs/global-command-contract.md`에 `/hep-network`·`@Hephaestus` 추가

**Phase 1 — 글로벌 init + 카드 스토어**
- [ ] `agentlas_cloud/networking/{__init__,bootstrap,card_store,card_lint}.py`
- [ ] `bin/hephaestus`에 `network init|status|add-source|reindex`, `cards lint|migrate` 서브커맨드
- [ ] `scripts/install-all-runtimes.sh`·`install.sh` 말미에 `network init` 훅
- [ ] `scripts/verify-routing-cards.sh` 신규, `scripts/verify-package.sh`에 카드 게이트 추가
- [ ] `tests/test_network_bootstrap.py`, `tests/test_card_lint.py`

**Phase 2 — 라우터 + 영수증 + 메모리**
- [ ] `agentlas_cloud/networking/{router,receipts,memory,approvals}.py`
- [ ] `bin/hephaestus route` / `network bench`
- [ ] 런타임 명령 파일: `.claude/commands/hep-network.md`, `claude/plugins/.../commands/`, `codex/plugins/.../commands/`, `gemini/extension/commands/hep-network.toml`, `antigravity/workflows/hep-network.md`, `cursor/rules/hephaestus.mdc` (신규 어댑터 디렉토리)
- [ ] `.agentlas/global-commands.json`에 hephaestus-network 등록, `scripts/sync-adapters.sh` 미러 목록 갱신
- [ ] `tests/test_network_router.py` (엣지 케이스 표 전부)

**Phase 3 — Hub 폴백 + 승인**
- [ ] `agentlas_cloud/networking/hub_fallback.py` (`plugin_discovery.py` 패턴 재사용)
- [ ] capability-grants 승인 플로우 + 프라이버시 차단 룰
- [ ] `tests/test_hub_fallback.py` (오프라인/캐시/승인 시나리오)

**Phase 4 — 마이그레이션 + 벤치마크**
- [ ] `agentlas_cloud/networking/card_migrate.py` + Forge 110개 draft 카드 생성 실행
- [ ] 시드 15개 카드 수동 승급 + `benchmarks/routing/{seed,privacy,edges}.jsonl`
- [ ] `agentlas_cloud/networking/bench.py`, CI 게이트

**Phase 5 — 브랜딩 + 후속**
- [ ] README 5개 언어 Network 2.0 개정 (게시 승인 별도)
- [ ] 후속 PR 계획서: Hub(`AgentsAtlas/app`) routingCard 검증·검색 노출, desktop `auto-router.ts` 카드 연동

**기존 사용자 마이그레이션**: 업그레이드 시 `network init`이 `VERSION` 비교 → 없으면 신규 생성, 있으면 스키마 마이그레이션. 기존 `.agentlas/` 프로젝트 파일·global-commands symlink는 무변경 (추가만).

**검증 명령**: `scripts/verify-package.sh && scripts/verify-routing-cards.sh && python3 -m pytest tests/test_network_*.py tests/test_card_*.py && bin/hephaestus network bench --suite seed,privacy,edges`

## 11. 명시적 비범위 (이번 구현에서 제외)

- Hub 서버(`AgentsAtlas/app`)·desktop(`agentlas_desktop`) 코드 변경 — 계약 문서와 후속 PR 계획만 산출.
- 결제/유료 위임 실행 경로 — 승인 게이트 스키마만 정의.
- 자동 홈 폴더 스캔류 일체 — 영구 비범위.

## 12. Codex 설계 리뷰 결과 (2026-06-12)

평결 요약 (질문별):
1. **카드 분리: 동의.** agent-card(신원/설치)와 routing-card(라우팅 시그널) 분리 유지. 단 식별 연결·리비전·해시/서명·dedupe 필드 보강 필요 → §3에 반영 완료.
2. **레지스트리: 대체로 동의, 다중-writer 규칙 미흡.** WAL/busy_timeout/원자적 쓰기/flock 계약 필요 → §2에 반영 완료.
3. **결정론적 라우터: v1로 적정** (벤치마크가 정직하다는 전제). 최초 열화 지점은 ko 쿼리 ↔ en-only 카드. CJK bigram 토크나이저 포팅 + locale_coverage 게이트 → §4에 반영 완료.
4. **프라이버시 게이트: 동의하나 카드 수준 정책만으로 부족.** Hub 쿼리 누출, 클라우드-가능 플러그인 로컬 호출, 과소 선언 카드, 패키지 export 경로(`runtime.py`의 `.agentlas/*.json` 허용) 우회 차단 필요 → §5에 반영 완료.
5. **마이그레이션: draft-first 동의 + 락아웃 가드 추가.** ready 카드 부족 시 라우팅이 조용히 죽는 모드 방지(`network status` 임계치), verify-package 게이트는 warn→block 2단계 → §4·§7에 반영 완료.
6. **총평: 구현 진행 가능. 단 동시성·프라이버시 데이터 플로·마이그레이션/벤치마크 게이트를 계약으로 명시한 후 시작할 것.** (모두 본 문서에 반영됨)

Top-3 리스크 (Codex): ① 공유 레지스트리 손상/split-brain ② 라우터 결정 밖 프라이버시 우회 ③ 마이그레이션 중 라우팅 품질의 조용한 실패.

불일치 사항: 없음 — 본 설계와 Codex 권고 간 방향 충돌은 없었고, 전 항목 보강 수용.

합의된 기술 스택: Python(`agentlas_cloud/networking/`, stdlib + sqlite3 FTS5, LLM 비의존 결정론 라우터) · 카드 JSON = 진실의 원본 + SQLite 캐시 · JSONL 원장(flock) · 기존 `bin/hephaestus` CLI 확장 · 런타임 어댑터는 기존 global-command 계약 확장 · 벤치마크는 pytest + 전용 러너.
