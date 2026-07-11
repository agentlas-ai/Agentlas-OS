# Agent Ontology + A2A 구현 기획안 (v0.3 draft)

> v0.2 변경: 저장 백엔드 확정(JSONL+인메모리+registry.sqlite 재사용), 임베딩 Phase 2 고정,
> 마이그레이션 필드매핑·진실원 전환·워크드 예시·능력 어휘 거버넌스·공리 평가모델 추가.
>
> v0.3 첨언: "허브 검색 개선"과 "Agent Ontology 런타임"의 경계를 명확히 하고,
> AO로 인정할 최소 행동변화·수락기준·A2A v1.0 Agent Card 경로를 고정.

> 목표: 흩어진 에이전트 위상 정보를 **하나의 검증 가능한 에이전트 온톨로지(Agent Ontology, AO)**로 통합하고,
> 라우터를 "키워드 매칭"에서 "온톨로지 그래프 추론"으로 승격시킨 뒤, 외부 에이전트와는 **A2A Agent Card**로 정렬한다.

## 0. 문제 정의 (현재 상태)

| 가진 것 | 위치 | 한계 |
| --- | --- | --- |
| 에이전트 명함 | `.agentlas/routing-card.json` | 납작한 자기기술. 카드끼리 관계 없음 |
| 팀 위상 | `.agentlas/company-blueprint.json` | nodes/edges 있으나 라우팅이 안 씀 |
| 태스크 흐름 | `.agentlas/sitemap.json` | produces/consumes 절반만 활용 |
| 메모리 소유 | `.agentlas/memory-map.json` | 별도 파일, 온톨로지와 분리 |
| 거버넌스 규칙 | 산문/코드 | "specialist↔specialist 금지"가 공리가 아님 |
| 라우터 | `agentlas_cloud/networking/router.py` | **토큰 교집합 매칭. 임베딩·그래프추론 없음** |
| 문서 온톨로지 | `ontology/runtime.py` | **도메인 지식용. 에이전트와 무관 → deprecate** |
| 거버넌스 씨앗 | `super-ontology-{capability-delegation-authority, consensus-coordination}.json` | `export_only` = 실행 안 됨 |

**핵심 공백**: 에이전트들을 1급 엔티티로 두고 그 관계·권한·금지규칙을 형식화한 모델이 없다.

### 0.1 범위 판정: 검색 개선 vs AO 구현

이 계획은 단순히 "서버가 Hub에서 에이전트를 더 잘 찾는 것"으로 끝나면 실패다.

| 범위 | 하는 일 | 결과 | AO로 인정? |
| --- | --- | --- | --- |
| Hub 검색 개선 | 공개/소유 Hub 에이전트를 BM25·벡터·trust signal로 더 잘 찾음 | 좋은 후보 추천 | ❌ 아니오. 후보 검색 품질 개선일 뿐 |
| 임베딩 라우팅 | 로컬 routing-card 후보를 의미 유사도로 더 잘 찾음 | 동의어/패러프레이즈 흡수 | ❌ 단독으로는 아니오. 매칭축 개선 |
| Agent Ontology 런타임 | 에이전트·능력·아티팩트·권한·금지규칙을 그래프로 검증하고 라우터 결정에 사용 | 호출 가능성, 파이프라인, 거버넌스가 바뀜 | ✅ 예 |

따라서 AO의 최소 수락기준은 **후보를 잘 찾는 것**이 아니라, 라우터가 다음 질문에 기계적으로 답하는 것이다:

- 이 caller가 이 agent를 호출해도 되는가?
- 이 agent가 요청 산출물을 만들 수 있는가?
- 다음 stage가 이전 stage의 산출물을 consume할 수 있는가?
- 어떤 공리 때문에 후보가 허용/차단되었는가?

## 1. 설계 원칙

1. **에이전트가 주어다.** 온톨로지의 노드는 문서가 아니라 에이전트/아티팩트/능력이다.
2. **타입 강제 + 공리.** 모든 관계는 `(from_type, relation, to_type)` 문법으로 검증. 금지규칙은 deny 공리로 명시.
3. **단일 진실원.** AO가 원본이고, 기존 4개 JSON은 AO에서 생성되는 view가 된다.
4. **로컬 우선·소규모.** 에이전트는 수십 개 → Neo4j 불필요. JSONL + 인메모리 그래프 + SQLite 인덱스로 충분.
5. **매칭과 온톨로지는 다른 축.** 임베딩은 "매칭 품질"을, AO는 "관계 추론"을 담당. 둘 다 하되 섞지 않는다.
6. **A2A는 경계.** 내부 AO부터 세우고, 외부 상호운용은 그 위에 Agent Card로 얹는다.

## 2. 온톨로지 스키마

### 2.1 노드 타입 (agent-space)

```
Orchestrator | HRDirector | PMSoul | MemoryCurator | PolicyGate
Specialist | EvalJudge | QAGate | SitemapRouter | RuntimeArchitect
ExternalAgent        # A2A 외부 피어
Artifact             # produces/consumes 대상 (1급 노드 → 파이프라인 경로탐색용)
Capability           # 통제 어휘(taxonomy) 노드
```

### 2.2 관계 타입 (meta-edge, 검증됨)

| 분류 | relation | from → to |
| --- | --- | --- |
| 구조 | `member_of` | Agent → (HRDirector\|Orchestrator) |
| 구조 | `supervises` | (Orchestrator\|HRDirector) → Agent |
| 구조 | `owns_scope` | Agent → MemoryScope |
| 통신 | `routes_to` / `delegates_to` / `can_invoke` / `hands_off_to` | Agent → Agent |
| 데이터흐름 | `produces` | Agent → Artifact |
| 데이터흐름 | `consumes` | Agent → Artifact |
| 능력 | `has_capability` | Agent → Capability |
| 거버넌스 | `gated_by` / `requires_approval_from` | Agent → (PolicyGate\|EvalJudge\|QAGate) |
| 거버넌스 | `blocked_from` (음성) | Agent → Agent |
| 신뢰(A2A) | `trusts` / `aligned_with` / `exposes_card` | Agent ↔ ExternalAgent |

### 2.3 공리 (deny/require — 기계검증)

```jsonc
// .agentlas/agent-ontology/grammar.json (발췌)
{
  "deny": [
    {"from": "Specialist", "relation": "routes_to", "to": "Specialist",
     "reason": "Policy Office: specialist↔specialist 직접통신 금지"},
    {"from": "PMSoul", "relation": "routes_to", "to": "PMSoul",
     "reason": "peer PM Soul 통신 금지"},
    {"from": "HRDirector", "relation": "delegates_to", "to": "Specialist",
     "when": "to.member_of != from", "reason": "out-of-dept specialist 호출 금지"}
  ],
  "require": [
    {"if": "edge.kind == shared_memory_write",
     "then": "requires_approval_from(PolicyGate)"},
    {"if": "from.type == ExternalAgent and relation == can_invoke",
     "then": "exists aligned_with(from)"}
  ]
}
```

**공리 평가 모델 (단순·결정적, LLM 없음):**
- `deny`: 엣지/라우팅 후보 `(from, relation, to)`를 deny 규칙과 매칭. `when` 조건은 노드 속성에 대한 **불리언 식**만 허용(예: `to.member_of != from.member_of`) — 임의 코드 실행 없음.
- `require`: 특정 종류의 엣지가 생성/실행될 때 동반 엣지 존재를 강제(예: shared_write → PolicyGate 승인 엣지).
- 평가 시점: ① `ao lint`(빌드/커밋 시 그래프 전체) ② 라우터 결정 시점(후보별 실시간) — 두 곳 모두 동일 평가기 사용.
- 위반 처리: lint=실패(커밋 차단), 런타임=후보 제거 + 영수증에 `blocked_by_axiom` 기록.

### 2.4 노드/엣지 인스턴스 예시

```jsonc
// agents.jsonl
{"id":"pm-soul","type":"PMSoul","capabilities":["track_decisions","own_project_memory"],
 "produces":["decision-record","risk-log"],"consumes":["mission-brief"],
 "memory_behavior":{"owns_scope":"project"},"routing_status":"trusted"}

// edges.jsonl
{"from":"00-orchestrator","relation":"delegates_to","to":"pm-soul"}
{"from":"pm-soul","relation":"produces","to":"artifact:decision-record"}
{"from":"20-team-builder","relation":"consumes","to":"artifact:decision-record"}
{"from":"10-specialist-a","relation":"blocked_from","to":"10-specialist-b"}
```

## 3. 저장·런타임 구조

```
.agentlas/agent-ontology/
  grammar.json        # 노드타입 · 관계문법 · 공리(deny/require)
  agents.jsonl        # 에이전트 노드 (routing-card+blueprint에서 생성)
  edges.jsonl         # 관계
  artifacts.jsonl     # 아티팩트 카탈로그
  capabilities.json   # 능력 통제어휘(taxonomy)

agentlas_cloud/agent_graph/
  loader.py           # JSONL → 인메모리 그래프
  validator.py        # grammar.json으로 노드/엣지/공리 검증 (외부 문서 온톨로지 검증기 설계 차용)
  query.py            # 그래프 질의: who_produces(X), reachable, is_blocked, plan_path
  migrate.py          # 기존 4개 JSON → AO 생성 (card_migrate.py 패턴)
```

> 차용 1줄: 외부 문서 온톨로지 도구에서 *유일하게* 가져올 것 = **"타입 문법 + grammar-validated 엣지 + 증거기반 승격"** 기계장치. 단 대상이 문서→에이전트.

**저장 백엔드 결정 (확정): JSONL(진실원) + 인메모리 그래프(런타임) + `registry.sqlite` 재사용(임베딩 인덱스).** 근거:
- 에이전트는 수십~저백 개 → 인메모리 그래프 질의 sub-ms. Neo4j/무거운 DB 불필요.
- 쓰기는 빌드시점에만 드묾 → **JSONL은 git diff/리뷰 친화적**(조직도 변경이 PR로 보임).
- 읽기는 요청마다(라우터, 지연민감) → 로드시 1회 검증 후 인메모리.
- 임베딩 벡터(Phase 2)는 networking에 **이미 있는 `registry.sqlite`를 재사용**해 카드 인덱스 옆에 벡터 컬럼 추가.
- ❌ `ontology/runtime.py` SQLite는 재사용 안 함 — sources/chunks/entities 문서스키마라 모양이 안 맞고, 어차피 deprecate 대상이라 결합하면 부채.

## 4. 라우터 업그레이드 (핵심 보상)

기존 `router.py` 결정(`route/pipeline/clarify/hub_fallback/propose_new`) API는 유지하되 엔진을 교체:

```
요청
 ├─ 1단계 매칭(후보 추리기)
 │    ├─ 토큰 매칭 (기존, 싸고 빠른 pre-filter)
 │    └─ [신규] 의미 매칭(임베딩) — 동의어/패러프레이즈 흡수   ← 사용자가 원하던 "임베딩"
 ├─ 2단계 온톨로지 추론(AO 그래프 질의)
 │    ├─ 공리 검증: caller로부터 blocked_from 인 후보 제거
 │    ├─ 능력/produces 매칭: 요청 산출물을 produces 하는 에이전트만
 │    └─ 파이프라인: 다단계 요청이면 produces/consumes 그래프 경로탐색 → 스테이지 자동 구성
 └─ 결정 + 영수증(어떤 공리가 허용/차단했는지 명시)
```

- **임베딩**은 1단계 매칭 보강(별도 축)으로 도입 — 카드에 `embedding` 필드 추가, 인덱스(`registry.sqlite`)에 벡터 저장. 진짜 의미 임베딩 사용(현 `ontology/embeddings.py`의 hashing vector 아님).
- **온톨로지**는 2단계 추론. "X를 produces 하고, caller에게 blocked 아니고, routing_ready인 에이전트" 같은 질의가 가능해짐.
- `pipeline` 결정이 비로소 완전해짐: 지금 둘씩만 잇던 걸 그래프 경로탐색으로.

## 5. A2A 경계 (외부 상호운용)

1. **포맷 채택**: 외부 교환은 [A2A Agent Card](https://a2a-protocol.org/latest/) 표준 사용. `routing-card.json` ↔ A2A `AgentCard` 매핑 어댑터 작성 (capabilities·I/O·auth·endpoints 거의 1:1).
2. **수입(import)**: 외부 A2A 카드 도착 → 능력 정렬(Agent-OM식 LLM 매칭, [arxiv 2312.00326](https://arxiv.org/abs/2312.00326))으로 우리 `Capability` 어휘에 매핑 → `aligned_with` 엣지 생성 → `ExternalAgent` 노드로 등록. **정렬 전엔 `can_invoke` 금지(공리).**
3. **수출(export)**: 우리 에이전트를 `/.well-known/agent-card.json` 형태 A2A 카드로 노출 → 남이 발견·호출 가능. 기존 예제/구버전 문서의 `/.well-known/agent.json` 표기는 호환 별칭으로만 다루고, canonical은 A2A v1.0 well-known URI인 `agent-card.json`으로 둔다.
4. **역할 분담 유지**: A2A = 에이전트↔에이전트, MCP = 에이전트↔도구. 둘 상보적, 혼동 금지.

**A2A 어댑터 수락기준:**
- import: A2A `AgentCard.skills[].tags/name/description` → 내부 `Capability` 후보로 정렬하되, curator 승인 전에는 `aligned_with`만 생성하고 `can_invoke`는 생성하지 않는다.
- export: 내부 AO Agent + Capability + endpoint/auth 정보를 A2A `AgentCard`로 투영하되, private path, local memory, raw routing-card text, 내부 policy rationale은 공개 카드에 넣지 않는다.
- invoke: 외부 에이전트 호출은 `ExternalAgent --aligned_with--> Capability`와 `caller --can_invoke--> ExternalAgent` 공리를 모두 만족할 때만 허용한다.

## 6. 마이그레이션 / 폐기

- `ontology/runtime.py`(문서 온톨로지) → **deprecate**. 삭제는 말고 "domain-knowledge" 별도 능력으로 강등 표시.
- super-ontology 씨앗 2종(`capability-delegation-authority`, `consensus-coordination`) → `export_only` 해제, AO grammar/공리로 **승격**(그린필드 아님).
- **super-ontology 24종 스코프 정리** (범위 확산 방지):
  - AO가 **흡수**: 2종(위 둘) → 런타임 공리.
  - Phase 4 A2A 정렬이 **재사용**: 2종(`semantic-alignment`, `entity-identity-resolution`) → 새로 안 만들고 그대로 씀.
  - 나머지 20종: 문서/지식 거버넌스용 → **현행 유지, AO와 분리**(건드리지 않음).
- `migrate.py`로 초기 그래프 생성: `company-blueprint`(nodes/edges) + `routing-card`(capabilities) + `sitemap`(produces/consumes) + `memory-map`(owns_scope) 머지 → `agents.jsonl`/`edges.jsonl`/`artifacts.jsonl`.

## 7. 단계별 로드맵

| Phase | 내용 | 산출물 | 행동변화 |
| --- | --- | --- | --- |
| **0. Spec** | grammar.json·JSON Schema·검증기 | `agent-ontology/grammar.json`, `hephaestus ao lint` | 없음 |
| **1. Materialize** | 마이그레이션 → 그래프 적재·검증, 씨앗 2종 승격 | `agents/edges/artifacts.jsonl`, `hephaestus ao graph` | 그래프 조회 가능 |
| **2. Router** | AO 질의를 router에 통합(공리차단·능력필터·경로탐색), 임베딩 pre-filter | 온톨로지 검증 라우팅 + 진짜 pipeline | 라우팅이 똑똑해짐 |
| **3. Governance** | Policy Office 규칙을 공리로 이전, 결정시점 검증·영수증 | 기계강제 통신규칙 | 위반 자동차단 |
| **4. A2A** | Agent Card 수입/수출·정렬계층 | A2A 발화/수용 | 외부 에이전트 합류 |
| **5. (선택) 진화** | 에이전트가 온톨로지 수정 제안 → curator/policy 리뷰 → 승격(candidate→validated→promoted, receipt) | 자가진화 AO | 외부 문서 온톨로지 승격패턴 적용 |

## 8. 성공 지표

- 라우팅 bench top-3 recall 유지/개선, **거버넌스 스위트에서 공리위반 자동라우팅 0건**.
- 다단계 요청이 produces/consumes로 **자동 파이프라인** 구성(수작업 체인 제거).
- Policy Office 규칙 **100%가 기계검증 공리**로 표현(산문 0).
- 에이전트 위상이 **단 한 곳(AO)**에 존재, 기존 4개 JSON은 생성 view.
- 라우팅 영수증이 `match_reason`, `graph_path`, `allowed_by`, `blocked_by_axiom`, `fallback_scope`를 분리해서 기록한다.
- Hub-only 검색을 꺼도 로컬 AO 라우팅/파이프라인/공리검증 테스트가 통과한다.

## 9. 비목표 / 리스크

- ❌ 무거운 그래프 DB(Neo4j) 재구축 — 수십 노드엔 과함.
- ❌ 매칭(임베딩)과 온톨로지(그래프)를 한 덩어리로 — 별개 축으로 유지.
- ❌ AO 구현 없이 Hub 검색만 개선하고 "A2A 온톨로지"라고 부르기 — 제품 약속이 달라짐.
- ⚠️ 로컬우선·프라이버시 불변식(raw prompt 미전송) 유지.
- ⚠️ A2A는 외부 경계 — 내부 AO 안정화 후 착수.
- ⚠️ `routing-card.json`/`company-blueprint.json`/`sitemap.json`/`memory-map.json` 이중쓰기 구간에서 drift가 생길 수 있음. `ao diff`가 CI 게이트가 되기 전까지는 수동 리뷰 필수.

## 10. 핵심 결정사항 (확정)

1. **저장 백엔드** ✅ JSONL(진실원) + 인메모리 그래프 + `registry.sqlite` 재사용(임베딩). `ontology/runtime.py` 재사용 안 함. (근거 §3)
2. **임베딩 도입 시점** ✅ **Phase 2에 라우터와 함께**, 단 "매칭축"으로 온톨로지 추론과 격리.
3. **Artifact 노드화** ✅ **1급 노드** — produces/consumes 경로탐색(파이프라인)의 전제.
4. **A2A 우선순위** ✅ Phase 4 — 내부 AO(Phase 0–3) 안정화 후 착수.

## 11. 마이그레이션 필드 매핑 (Phase 1 — 최대 리스크 구간)

조직도 자동생성의 정확성이 전체 품질을 좌우한다. 필드 단위로 못박는다.

| AO 요소 | 출처 파일 | 출처 필드 | 변환 규칙 |
| --- | --- | --- | --- |
| Agent 노드 `id`/`type` | `company-blueprint.json` | `nodes[].id`, `nodes[].role`/`tier` | `role`→`type` 매핑 테이블 (Worker→Specialist 등) |
| `has_capability` | `routing-card.json` | `capabilities[]` | verb-form 정규화 → `capabilities.json` 어휘에 매핑 |
| `produces`/`consumes` + Artifact 노드 | `routing-card.json`, `sitemap.json` | `produces`/`consumes`, edges | 아티팩트명 정규화 → Artifact 노드 생성·연결 |
| `owns_scope` | `memory-map.json` | `writeOwners`, `canonicalMemoryRoots` | scope별 소유 에이전트 1:1 |
| `routes_to`/`delegates_to`/`hands_off_to` | `company-blueprint.json` | `edges[].from/to/handoff` | `handoff` 라벨 → relation 매핑 |
| `blocked_from` (공리) | (Policy Office 산문) | 수기 추출 | grammar.json `deny`로 **코드화** |
| `routing_status` | `routing-card.json` | `routing_status` | 그대로 (draft→trusted) |

**검증 게이트**: 마이그레이션 직후 `ao lint` 통과 필수. 매핑 안 된 필드는 `unmapped` 리포트로 표면화(조용히 버리지 않음).

## 12. 진실원(Source of Truth) 전환 전략 — drift 방지

AO가 원본이 되는 순간, 기존 4개 JSON과의 이중관리가 최대 함정. 단계적 플립:

1. **Phase 1 (AO=파생)**: 4개 JSON이 원본, AO는 거기서 **생성된 읽기전용**. 행동변화 0, 안전.
2. **Phase 2–3 (플립)**: AO가 원본, 4개 JSON은 AO에서 **codegen 되는 view**. 쓰기는 AO에만(single-write), 읽기는 둘 다 가능(전환기).
3. **가드레일**: `hephaestus ao diff` — AO와 생성된 view 간 drift 탐지. **CI에서 drift 시 실패.**
4. **종착**: 4개 JSON은 빌드 산출물로 강등. 수기편집은 경고/차단.

## 13. 워크드 예시 — "기획부터 구현·QA까지 해줘"

| 단계 | 오늘 (키워드 라우터) | 신규 (AO 라우터) |
| --- | --- | --- |
| 의도 | 키워드로 에이전트 **1개**만 뱉음 | 의미매칭 → `pipeline`(plan-anchored) 의도 감지 |
| 분해 | (없음) | 요청을 산출물 체인으로 분해 |
| 경로탐색 | (없음) | produces/consumes 그래프 탐색:<br>`PMSoul`(→decision-record) → `team-builder`(consume decision-record, →team-package) → `eval-judge`(consume team-package, →release-verdict) → `qa-gate` |
| 거버넌스 | (없음) | 각 hop을 deny/require 공리 검증, `gated_by` 충족 확인 |
| 결과 | 단일 에이전트 | **스테이지 순서 + 각 단계 handoff_dir + 영수증(경로·충족공리 명시)** |

→ "다단계 일을 규칙 지키며 자동으로 줄세우기"가 비로소 동작. 이게 AO 도입의 가장 체감되는 보상.

## 14. 능력 어휘(Capability) 거버넌스

매칭·정렬의 정확성은 **능력 어휘가 통제(controlled)되어야** 성립 — 자유문자열이면 깨진다.

- **시드**: 기존 routing-card들의 `capabilities`를 verb-form 정규화해 seed taxonomy 구축 (예: `create_agent`, `build_team`, `package_agent`, `curate_memory`, `gate_policy`, `review_release`, `run_qa`...).
- **성장**: 새 능력은 `candidate`로 등록 → curator/policy 리뷰 → 승격(Phase 5 패턴). 무분별 증식 차단.
- **외부(A2A)**: 외부 에이전트의 선언 능력은 새 어휘를 만들지 않고 `aligned_with`로 **시드 어휘에 매핑**.

## 15. CLI 표면 (예정)

```bash
hephaestus ao lint                 # grammar.json으로 그래프 전체 검증 (공리 포함)
hephaestus ao migrate              # 기존 4개 JSON → agents/edges/artifacts.jsonl 생성
hephaestus ao graph [--agent ID]   # 조직도 조회/시각화
hephaestus ao query "produces:team-package and not blocked_from:CALLER"
hephaestus ao plan "<요청>"         # produces/consumes 경로탐색 → 파이프라인 미리보기
hephaestus ao diff                 # AO ↔ 생성된 view drift 탐지 (CI 게이트)
```

## 16. 첫 구현 PR 권장 범위

첫 PR은 라우터 행동을 바로 바꾸지 말고, AO를 안전하게 물질화하는 데서 끊는다.

**PR 1 — AO foundation (행동변화 없음):**
- `.agentlas/agent-ontology/grammar.json` 기본 문법과 공리 스키마 추가.
- `agentlas_cloud/agent_graph/loader.py`, `validator.py`, `query.py`, `migrate.py` 추가.
- `hephaestus ao lint`, `hephaestus ao migrate`, `hephaestus ao graph`, `hephaestus ao diff` CLI 추가.
- 기존 4개 JSON에서 AO를 생성하되, 이 단계에서는 AO를 읽기전용 파생물로 둔다.
- 테스트: valid graph 통과, invalid edge 차단, deny/require 공리 평가, unmapped field report, drift report.

**PR 2 — Router integration (행동변화 시작):**
- `router.py`가 기존 token score 뒤에 AO 후보 필터를 적용한다.
- `plan_pipeline`을 hard-coded stage intent에서 `produces/consumes` graph path로 점진 대체한다.
- routing receipt에 lexical/semantic match와 graph/governance decision을 분리 기록한다.
- 테스트: Hub off 상태에서도 local AO route/pipeline이 동작해야 한다.

**PR 3 — Semantic pre-filter (매칭 품질):**
- routing-card 전용 embedding adapter와 `registry.sqlite` 벡터 인덱스를 추가한다.
- `ontology/embeddings.py`의 hashing vector는 문서 온톨로지용 fallback으로 남기고, Agent AO 라우팅의 "진짜 의미 임베딩"으로 재사용하지 않는다.

**PR 4 — A2A boundary:**
- A2A AgentCard import/export 어댑터를 추가한다.
- canonical discovery path는 `/.well-known/agent-card.json`.
- 외부 카드는 `ExternalAgent`로 들어오며, `aligned_with` 검증 전에는 호출 불가.

## 17. 구현 현황 & 남은 작업 (검증 + Codex 교차검증 반영)

검증 근거는 `docs/validation-ledger.jsonl`. 빌드는 `agentlas_cloud/agent_graph/` + router/CLI 통합 + `.agentlas/agent-ontology/` materialize.

**구현·검증 완료**
- Phase 0–1: grammar(+ `grammar.json` materialize) · loader · validator · migrate · `ao lint` valid · `ao diff` clean · 멱등.
- Phase 2: router AO 후보 필터 배선(`_filter_candidates_by_ao`) · receipt 필드 분리 · `plan_path` 경로탐색.
- Phase 3 거버넌스: deny/require 위반이 **하드 lint 에러**(경고 아님) · `_evaluate_condition`이 `and`/`or` 파싱 → A2A `can_invoke` require-rule 실제 발동.
- Phase 4 A2A: `import`(aligned_with만, can_invoke 게이팅, 입력 검증, DoS 한도) · `export`(whitelist 기반, private 누출 0, well-known URI).
- 95 pytest 통과.

**남은 작업 (정직한 next-phase — 조용히 "완료"로 주장하지 않음)**
- **owns_scope → MemoryScope** (Codex #5/#6): `MemoryScope` 노드 타입 신설 + `memory-map.json` writeOwners를 `owns_scope` 엣지로 materialize. 현재는 `unmapped`로만 기록(코드 정직, 모델 미완).
- **pipeline routing을 AO 그래프로** (Codex #4): 현재 `plan_pipeline`은 routing-card produces/consumes 사용. AO `produces/consumes` 그래프로 이전 필요 — 단 routing-card에 produces/consumes가 없어 실 repo artifacts=0이라 **데이터 저작이 선행**돼야 시연 가능.
- **receipt graph_path 실증거** (Codex #8): 현재 `graph_path=[]`·일반 라벨. 실제 AO 엣지 경로·충족 규칙 ID로 채우기.
- **A2A export endpoint/auth 매핑** (Codex #9): §5의 "거의 1:1" 완성 — 공개 allowlist 기반 url/auth + 중첩 redaction 단언.
