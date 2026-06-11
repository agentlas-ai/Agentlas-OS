# Active Context — kordoc 본체

**마지막 업데이트**: 2026-06-11 (v3.0.0 릴리스 완료)
**상태**: 커밋 1f3ef33 + 태그 v3.0.0 푸시 + npm publish 완료 (kordoc@3.0.0 = latest). pnpm-lock.yaml/pnpm-workspace.yaml은 잔여물이라 커밋 제외(untracked로 남음 — 정리 여부 사용자 판단)

---

## v3.0.0 완료 상태 (2026-06-11)

### 최종 수치 (검증: npm run build && npm test && node bench/score.mjs — 전체 PASS ✅)
- HWPX recallMicro **0.999978** / recallDoc 미달 0 / 표 exact **100%**(1,421표·중첩 343) / phantom 0.000057
- PDF coverage **0.99164** / HWP5쌍 유사도 **0.9994** (policy.mjs 정식 게이트 승격)
- 테스트 **458/458** / 라운드트립 풀스윕: 무변경=바이트동일 전수, 문단수정 128건 무손상(깨끗한 적용 108, 나머지 정직한 skip)
- 베이스라인 박제: bench/out/score-baseline-v3.0.0.json

### 이번 세션 작업 (커밋 1f3ef33에 포함)
1. **Wave 3 라운드트립 완성**: tests/roundtrip-e2e.test.ts(실파일 9케이스) + tests/roundtrip-guards.test.ts 신규
2. **적대적 리뷰 31-에이전트 워크플로 → 확정 26건 전부 수정** (critical 4: 각주 body 오분류/대형문서 시프트 오적용/리터럴 </td> 셀 경계/Buffer view 오염): src/roundtrip/* 전반 + src/hwpx/parser.ts(lineBreak→\n) + src/table/builder.ts(라벨 행 소실)
3. **신규 코퍼스 120건**: bench/corpus/seoul2(60, 정보소통광장 11p~)/seoul-old(60, rangeDate=custom 2014-2016). 수집기 파라미터화
4. **채점기 함정 3종 수정**(bench/): 링크 정규식 스킴 한정, 마스킹-only 유닛 모수 제외, 짧은유닛 구간-우선 탐색(개선 3/악화 0) + .hwpx 확장자 OLE2 매직 라우팅
5. **릴리스 준비 완료**: package.json 3.0.0 / CHANGELOG 3.0.0 항목 / README v3.0.0 섹션+patchHwpx API / baseline 박제

### 다음 작업
- 남은 백로그: PDF ODL Phase 3 잔여(ClusterTable 완전판/TOC), HWP3 표 복원, 옛한글 PUA 5,659항, 라운드트립 Tier2(HWP5), MCP patchHwpx 도구 노출(킬러 데모), korea-kr2 빈 디렉토리 정리됨
- 함정 동일: 균등배분 1자 기준 불가침 / PDF 98.5% 합격선 / stale dist / score-baseline-*.json 덮어쓰기 금지

---

## 핵심 파일 (신규/대수정)
| 파일 | 역할 |
|------|------|
| bench/score.mjs + ref/ + lib/ | 정확도 채점기 (게이트: policy.mjs) |
| bench/collect-{korea-kr,opengov}.mjs | 코퍼스 수집기 |
| src/shared/pua.ts | 한컴 PUA→유니코드 (rhwp 검증 테이블) |
| src/hwp5/{numbering,images}.ts | 글머리 카운터 / BinData 이미지 |
| src/roundtrip/*.ts | 라운드트립 patchHwpx (v3.0 완성 — 5파일 + e2e/가드 테스트) |
| .claude/plans/v3.0.0-master-plan.md | 마스터플랜 + 진단 전문 위치 |
| .claude/plans/next-session-prompt.md | **다음 세션 프롬프트 (인계 문서)** |

## 주의 (lessons 추가분)
- 균등배분 1자 기준 불가침 / 휴리스틱 변경 시 코퍼스 정량 전후 비교 필수
- PDF 첨자(①·*) 별도 행 분리 → 표 오탐 전력 (mergeOverlappingRows 회귀 주의)
- 채점기 stale dist 함정: src 수정 후 빌드 없이 score.mjs 돌리면 구버전 채점
- bench/out/score-baseline-v2.9.1.json 덮어쓰기 금지

## 이전 컨텍스트 (참조용 유지)
- v2.7.0 XLS+Print (Phase 1, 커밋 f41da76) → v2.9.1까지 릴리스됨
- PDF ODL 업그레이드 Phase 1+2는 v2.x에서 완료, Phase 3는 v3.0 백로그로 승계
