# feature-map.json — 기능-의도(FEATURE-INTENT) 정본

같은 기능이 표면마다 다른 코드 이름을 갖는 것은 정상이다(와이어 `INGEST` = UI
"장기대여", 원장 `workspaceId` = 실제로는 크리에이터 워크스페이스). 철자를 비교하는
게이트는 이런 기능을 서로 다른 기능으로 취급해 영영 정렬하지 못한다(오너 진단
2026-08-18: workspaceId 의미 불일치 사고, INGEST/장기대여/프로젝트 인제스트 3중
표기, hep-* 명령 10개 런타임 드리프트). 그래서 정렬의 키는 철자가 아니라 **의도**다
— `contracts/feature-map.json` 이 그 정본이다.

## 규칙

1. **2개 이상 표면에 존재할 기능은 코드보다 먼저 여기 등록한다.**
   featureId 하나 + 의도 한 문장(한/영) + 표면별 정확한 식별자(심볼·라우트·테이블·
   와이어 id 그대로).
2. **등록된 식별자를 리네임하면 같은 변경 안에서 이 맵을 갱신한다.**
   게이트(`scripts/verify-feature-map.py`, `verify-package.sh` 에 배선됨)는 각
   식별자가 지금도 그 파일에 실존하는지 grep 수준으로 확인하는 리네임 경보다 —
   의미 증명이 아니다. 실패 시 featureId·의도·형제 표면을 함께 출력하므로,
   고치는 사람은 끊어진 문자열이 아니라 기능 전체를 본다.
3. **표기 이력은 aliases 로 남긴다.** `wire-legacy`(와이어에 살아 있는 옛 이름,
   클라이언트가 파싱하므로 유지), `retired`(새 카피에 다시 나타나면 안 됨),
   `display`(사용자 표시 이름, 표면별 번역 허용).
4. **게이트는 의도를 정렬하지 철자를 정렬하지 않는다.** 형제 체크아웃이 없으면
   사유와 함께 SKIP(정직 스킵), 있는데 식별자가 없으면 FAIL — 절대 스킵으로
   위장하지 않는다.
5. 포인터가 낡았으면(파일 이동·심볼 리네임) 코드가 아니라 **맵을 고친다**.
   기능 자체가 사라졌으면 행을 지우지 말고 aliases 에 `retired` 로 강등한 뒤
   featureId 를 새 정본으로 갱신한다.

## 프로젝트별 맵 — 사이트맵과 같은 급의 프로젝트 맵 레이어

기능-의도 맵은 이 저장소 전용이 아니라 **모든 Agentlas 활성 프로젝트의 1급
프로젝트 맵**이다(sitemap.json·code-map·context-map 과 나란히).

- **위치**: 각 프로젝트의 `.agentlas/feature-map.json`. 스키마는
  `schemas/feature-map.schema.json`(`agentlas.feature-map.v1`).
- **시드**: sitemap 과 같은 첫-접촉 부트스트랩 경로(`project_bootstrap`)가
  `templates/feature-map.json.tpl` 로 빈 맵을 심는다 — 같은 동의 규칙, 즉
  따로 묻지 않는다. merge-only: 이미 있으면 절대 덮어쓰지 않는다.
- **다중 저장소**: surface 의 `repo` 는 맵이 속한 워크스페이스 기준 형제
  체크아웃(`../<repo>`)으로 푼다. 워크스페이스 자기 이름은 자기 자신이다 —
  `scripts/verify-feature-map.py` 와 동일한 규칙.
- **조회**: `hephaestus feature-map lookup <identifier>` (엔진 API:
  `agentlas_cloud/feature_map.py` 의 `lookup()`). 식별자·featureId·alias
  정확 일치가 matches, 없을 때만 부분 일치가 fuzzyMatches 로 따로 나온다.
- **게이트**: `python3 scripts/verify-feature-map.py --map
  <project>/.agentlas/feature-map.json`. jsonschema 가 import 되면 스키마
  검증까지, 안 되면 그 항목만 사유 있는 SKIP(선택 의존성 부재는 FAIL 이
  아니다).
- **이 저장소의 인스턴스**: `contracts/feature-map.json` 은 엔진 워크스페이스
  (Agentlas_F) 자신의 맵이다 — 계약 자료라 버전 관리되는 contracts/ 에 두고,
  `--map` 기본값이자 `verify-package.sh` 게이트 대상이다.
