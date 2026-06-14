# Hephaestus Network 2.0 — Pipeline Routing 설계 (v1 draft, 2026-06-12)

상태: **구현 완료 (v0.4.6).** 브랜딩 주의: 별도 버전(2.1)이 아니라 **Network 2.0의 기능**으로 출하한다.
구현: `agentlas_cloud/networking/pipeline.py` + `router.py` 통합, 시드 카드 5종 산출물 계약,
`benchmarks/routing/pipeline.jsonl` 20케이스 (plan accuracy 100%, 과분해 0), `tests/test_network_pipeline.py`.
v1 탐지 범위는 plan→build→verify 체인(마케팅 체인 등은 산출물 계약만 선반영, 탐지기는 후속).
사용자-facing 명칭: *pipeline routing* / 멀티팀 자동 연결.

## 0. 목표

"웹앱 만들어줘" 같은 복합 요청을 단일 팀이 아니라 **여러 팀의 사슬**(예: PRD 팀 →
개발본부 → QA 팀)로 자동 분해·연결해 하나의 결과물로 잇는다. 단, Network 2.0의
원칙은 그대로: 결정론적 계획, 스테이지마다 승인 게이트, 영수증, 메모리는 로컬.

## 1. 카드 확장 — 산출물 계약 (additive, 비파괴)

routing-card v2에 선택 필드 2개를 추가한다 (기존 카드 전부 유효 유지):

```jsonc
"produces": [ {"kind": "prd", "path_hint": "docs/prds/", "description": "..."} ],
"consumes": [ {"kind": "prd", "required": true} ]
```

- `kind` 표준 어휘(초기): `prd`, `design_spec`, `ui_design`, `codebase_change`,
  `qa_report`, `content_draft`, `dataset`, `report`, `deploy_artifact`.
  스키마 enum이 아니라 권고 어휘로 시작(콜드스타트 방지), lint는 비표준 kind에 warning.
- 예: `hephaestus_prd_maker` → produces `prd`; `Web_master` → consumes `prd`(optional),
  produces `codebase_change`; QA류 → consumes `codebase_change`, produces `qa_report`.

## 2. 플래너 — `agentlas_cloud/networking/pipeline.py` (신규)

결정론적 그래프 탐색 (LLM 불필요):

1. 단일 카드 라우팅이 confident면 파이프라인을 시도하지 않는다 (기존 동작 우선).
2. 요청이 복합 신호(생성+검증, 기획+구현 동사 조합 휴리스틱)를 보이거나 단일 매치가
   없을 때: 후보 카드들의 `produces`/`consumes`로 DAG를 만들고, 요청 토큰과의
   스코어 합이 최대인 **최대 3스테이지** 경로를 찾는다.
3. 제약: 같은 카드 1회만, 같은 `kind` 재생산 금지, `routing_ready` 미만 카드 배제,
   경로 점수의 스테이지별 하한(약한 고리 방지).
4. 반환: `action: "pipeline"` —

```jsonc
{
  "action": "pipeline",
  "pipeline_id": "...",
  "stages": [
    {"order": 1, "card": "paid/hephaestus_prd_maker", "consumes": [], "produces": ["prd"],
     "approval_request": {...} | null},
    {"order": 2, "card": "paid/Web_master", "consumes": ["prd"], "produces": ["codebase_change"], ...},
    {"order": 3, "card": "<qa card>", "consumes": ["codebase_change"], "produces": ["qa_report"], ...}
  ],
  "handoff_dir": "<project>/.agentlas/pipeline/<pipeline_id>/",
  "receipt_id": "..."
}
```

## 3. 실행 모델 (러너 = 호출한 런타임 AI)

라우터는 **계획만** 반환한다. 러너 계약(어댑터 md에 명시):
- 스테이지 순서대로: 승인 확인 → 해당 카드의 canonical command 실행 → 산출물을
  `handoff_dir/<order>-<kind>/`에 기록 → `receipts.record_execution(pipeline_id, stage)` →
  다음 스테이지에 산출물 경로 전달.
- 스테이지 실패 시: 중단하고 진행 상황 + 남은 계획 보고 (자동 재시도 금지).
- 산출물은 전부 프로젝트 로컬 파일 — 클라우드-가능 스테이지로 로컬 메모리가 포함된
  산출물을 넘길 땐 기존 privacy 규칙대로 export 승인 필요.

## 4. 게이트·영수증·루프

- 승인: 스테이지별 독립 적용(기존 approvals.py 재사용). 사용자가 원하면 시작 시
  파이프라인 전체 1회 승인(`scope: "session"` grant) 허용.
- 영수증: 계획 1건 + 스테이지 실행마다 1건, 모두 `pipeline_id`로 연결.
  `router_chain`에 `pipeline:<id>:<order>` 추가 — 기존 hop 가드와 병행.
- 루프 방지: 플래너 자체가 DAG만 생성(사이클 불가) + 러너의 재라우팅은 hop 가드 적용.

## 5. 벤치마크 확장

- 픽스처: `{"query": "...", "expected": {"action": "pipeline", "stages_any": [["prd"], ["codebase_change"]]}}`
  (kind 시퀀스로 검증 — 특정 카드 강제 아님).
- 신규 지표: pipeline plan accuracy(스테이지 kind 시퀀스 일치), 과분해율
  (단일 카드로 충분한 요청을 파이프라인으로 쪼갠 비율 — 낮아야 함).
- 게이트: 과분해율 < 5%, 기존 top-3/unsafe 기준 비퇴행.

## 6. 구현 체크리스트

- [ ] `schemas/routing-card.schema.json`: `produces`/`consumes` 선택 필드 (완료 — 본 설계와 함께 추가)
- [ ] `agentlas_cloud/networking/pipeline.py`: 플래너 + handoff 디렉토리 규약
- [ ] `router.py`: 단일 매치 실패/복합 신호 시 플래너 호출 (clarify보다 먼저, hub보다 먼저)
- [ ] `receipts.py`: pipeline_id 연결 필드
- [ ] 시드 카드 산출물 계약 부여: hephaestus_prd_maker(produces prd), Web_master(consumes prd),
  QA류 1종, marketing 계열 1체인 — 초기 4~6카드만
- [ ] `benchmarks/routing/pipeline.jsonl` ≥20케이스 (ko/en)
- [ ] 어댑터 md 6종에 러너 계약 단락 추가, `docs/hephaestus-network-2.0.md`에 사용자 설명 추가
- [ ] `tests/test_network_pipeline.py`

## 7. 비범위

- 라우터가 스테이지를 직접 실행하는 것 (러너 책임 — Network 2.0 실행 모델 유지).
- 크로스-머신/클라우드 파이프라인 — 로컬 우선 원칙 유지, Hub 카드는 스테이지 후보로
  들어오되 스테이지 단위 승인 필수.
- AppBridge CEO 루프 대체 — 사내 오케스트레이션은 별도 유지, 본 기능은 공개 제품 표면.
