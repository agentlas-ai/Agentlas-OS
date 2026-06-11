import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { cleanPdfText } from "../src/pdf/parser.js"

describe("cleanPdfText", () => {
  it("페이지 번호 패턴 제거: - 1 -", () => {
    const input = "본문 텍스트\n- 1 -\n다음 텍스트"
    const result = cleanPdfText(input)
    assert.ok(!result.includes("- 1 -"))
    assert.ok(result.includes("본문 텍스트"))
    assert.ok(result.includes("다음 텍스트"))
  })

  it("페이지 번호 패턴 제거: — 25 —", () => {
    const result = cleanPdfText("텍스트\n— 25 —\n끝")
    assert.ok(!result.includes("25"))
  })

  it("페이지 번호 패턴 제거: 3 / 10", () => {
    const result = cleanPdfText("텍스트\n3 / 10\n다음")
    assert.ok(!result.includes("3 / 10"))
  })

  it("한국어 줄바꿈 병합", () => {
    const input = "대한민국\n헌법"
    const result = cleanPdfText(input)
    assert.equal(result, "대한민국 헌법")
  })

  it("영어-한글 줄바꿈은 병합 안 함", () => {
    const input = "English\n한글"
    const result = cleanPdfText(input)
    assert.ok(result.includes("English\n한글"))
  })

  it("3줄 이상 연속 빈 줄을 2줄로 축소", () => {
    const input = "A\n\n\n\n\nB"
    const result = cleanPdfText(input)
    assert.ok(!result.includes("\n\n\n"))
    assert.ok(result.includes("A\n\nB"))
  })

  it("앞뒤 공백 제거", () => {
    const result = cleanPdfText("  hello  ")
    assert.equal(result, "hello")
  })

  it("빈 문자열 입력", () => {
    assert.equal(cleanPdfText(""), "")
  })

  // ─── 리스트/번호 패턴 보호 ────────────────────────────

  it("한글 번호 리스트는 병합하지 않음 (가. 나. 다.)", () => {
    const input = "항목 내용\n가. 첫째 항목\n나. 둘째 항목"
    const result = cleanPdfText(input)
    assert.ok(result.includes("\n가. 첫째"), `리스트 마커 '가.' 앞 줄바꿈 유지: ${result}`)
    assert.ok(result.includes("\n나. 둘째"), `리스트 마커 '나.' 앞 줄바꿈 유지: ${result}`)
  })

  it("숫자 번호 리스트는 병합하지 않음 (1. 2. 3.)", () => {
    const input = "다음과 같다\n1. 첫째\n2. 둘째"
    const result = cleanPdfText(input)
    assert.ok(result.includes("\n1. 첫째"), `숫자 리스트 '1.' 앞 줄바꿈 유지: ${result}`)
  })

  it("괄호 번호 리스트는 병합하지 않음 ((1) (가))", () => {
    const input = "규정에 따라\n(1) 첫째 사항\n(가) 세부 사항"
    const result = cleanPdfText(input)
    assert.ok(result.includes("\n(1) 첫째"), `괄호 리스트 '(1)' 앞 줄바꿈 유지: ${result}`)
    assert.ok(result.includes("\n(가) 세부"), `괄호 리스트 '(가)' 앞 줄바꿈 유지: ${result}`)
  })

  it("기호 리스트는 병합하지 않음 (○ ● ※)", () => {
    const input = "주의사항\n○ 첫째 주의\n※ 참고사항"
    const result = cleanPdfText(input)
    assert.ok(result.includes("\n○ 첫째"), `기호 리스트 '○' 앞 줄바꿈 유지: ${result}`)
    assert.ok(result.includes("\n※ 참고"), `기호 리스트 '※' 앞 줄바꿈 유지: ${result}`)
  })

  it("일반 한글 줄바꿈은 여전히 병합됨", () => {
    const input = "대한민국\n헌법"
    const result = cleanPdfText(input)
    assert.equal(result, "대한민국 헌법")
  })

  // ─── 법령 조항 보호 ──────────────────────────────────

  it("제N조 뒤 줄은 병합하지 않음 (독립 조항 헤더)", () => {
    const input = "제1조\n국민의 권리와 의무"
    const result = cleanPdfText(input)
    assert.ok(result.includes("제1조\n국민의"), `제N조 뒤 줄바꿈 유지: ${result}`)
  })

  it("제N조(목적) 뒤 줄은 병합하지 않음", () => {
    const input = "제2조(정의)\n이 법에서 사용하는"
    const result = cleanPdfText(input)
    assert.ok(result.includes("제2조(정의)\n이"), `제N조(목적) 뒤 줄바꿈 유지: ${result}`)
  })

  it("다음 줄이 제N조로 시작하면 병합하지 않음", () => {
    const input = "전문을 살펴보면\n제3조 다음 각 호의"
    const result = cleanPdfText(input)
    assert.ok(result.includes("\n제3조"), `제N조 시작 줄바꿈 유지: ${result}`)
  })

  // ─── 마커 뒤 공백 없는 케이스 ──────────────────────────

  it("공백 없는 숫자 마커도 병합하지 않음 (1.첫째)", () => {
    const input = "다음과 같다\n1.첫째 항목"
    const result = cleanPdfText(input)
    assert.ok(result.includes("\n1.첫째"), `공백 없는 마커 보호: ${result}`)
  })

  it("공백 없는 한글 마커도 병합하지 않음 (가.첫째)", () => {
    const input = "항목 내용\n가.첫째 사항"
    const result = cleanPdfText(input)
    assert.ok(result.includes("\n가.첫째"), `공백 없는 한글 마커 보호: ${result}`)
  })

  // ─── 독립 헤더 경계 케이스 ─────────────────────────────

  it("제N조 + 긴 본문도 마커 줄이므로 병합 안 됨", () => {
    // "제1조"로 시작하는 줄은 startsWithMarker가 true → 병합하지 않음 (조항 보호)
    const input = "제1조 이 법은 국민의 기본적 권리와 의무를 보장하기 위하여 제정한다\n다만 예외가 있다"
    const result = cleanPdfText(input)
    assert.ok(result.includes("제정한다\n다만"), `제N조 마커 줄은 병합 안 됨: ${result}`)
  })

  it("제N조(괄호제목) 짧은 헤더는 병합 안 됨", () => {
    const input = "제5조(적용범위)\n이 법은 모든"
    const result = cleanPdfText(input)
    assert.ok(result.includes("제5조(적용범위)\n이"), `짧은 조항 헤더 보호: ${result}`)
  })
})
