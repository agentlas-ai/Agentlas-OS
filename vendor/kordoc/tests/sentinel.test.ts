import { test } from "node:test"
import { strictEqual } from "node:assert"
import { isDistributionSentinel } from "../src/hwp5/sentinel.js"

test("배포용 경고 문구만 있으면 sentinel=true", () => {
  const md = `이 문서는 상위 버전의 배포용 문서입니다. 문서를 읽으려면 최신 버전의 한글 또는 한글 전용 뷰어가 필요합니다.
(주의! 현재 상태에서 문서를 저장하는 경우 원래 문서의 내용이 사라집니다.)`
  strictEqual(isDistributionSentinel(md), true)
})

test("정상 본문이 섞인 문서는 sentinel=false", () => {
  const md = `# 회의록

참석자: 홍길동, 이순신

본문 내용이 길게 이어집니다. 이 문서는 회의록이며 실제 안건이 많이 들어 있습니다.
안건 1. 분기 목표 검토
안건 2. 예산 배정
안건 3. 다음 회의 일정
추가로 실무자 배정 및 기타 논의사항 정리`
  strictEqual(isDistributionSentinel(md), false)
})

test("빈 문자열은 sentinel=false", () => {
  strictEqual(isDistributionSentinel(""), false)
})

test("경고 문구 없이 짧은 본문은 sentinel=false", () => {
  strictEqual(isDistributionSentinel("간단한 메모"), false)
})
