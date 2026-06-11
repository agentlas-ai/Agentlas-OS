import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { cellTextToString, type TextItem } from "../src/pdf/line-detector.js"

/** 헬퍼: 텍스트 아이템 생성 */
function ti(text: string, x: number, y: number, w = 30, fontSize = 12): TextItem {
  return { text, x, y, w, h: fontSize, fontSize, fontName: "Test" }
}

describe("cellTextToString", () => {
  it("빈 배열 → 빈 문자열", () => {
    assert.equal(cellTextToString([]), "")
  })

  it("단일 아이템 → 그대로 반환", () => {
    assert.equal(cellTextToString([ti("안녕", 10, 100)]), "안녕")
  })

  it("같은 행의 아이템들이 합쳐짐", () => {
    const items = [ti("대한", 10, 100), ti("민국", 50, 100)]
    const result = cellTextToString(items)
    assert.ok(result.includes("대한") && result.includes("민국"))
  })

  it("한글 간 작은 갭(< fontSize*0.3) → 공백 없이 병합", () => {
    // fontSize=12, 0.3*12=3.6pt. 갭 = 40 - 10 - 30 = 0 < 3.6
    const items = [ti("기", 10, 100, 30, 12), ti("준", 40, 100, 30, 12)]
    const result = cellTextToString(items)
    assert.equal(result, "기준", "한글 작은 갭은 공백 없이 연결")
  })

  it("한글 간 큰 갭(> fontSize*0.3) → 공백 삽입", () => {
    // fontSize=12, 갭 = 80 - 10 - 30 = 40 > 3.6
    const items = [ti("이름", 10, 100, 30, 12), ti("주소", 80, 100, 30, 12)]
    const result = cellTextToString(items)
    assert.equal(result, "이름 주소")
  })

  it("줄바꿈 병합: 짧은 한글 조각 (5자 이하) → 이전 줄에 연결", () => {
    // y=100 (위), y=80 (아래) — "전자여" + "권" = "전자여권"
    const items = [ti("전자여", 10, 100), ti("권", 10, 80)]
    const result = cellTextToString(items)
    assert.equal(result, "전자여권")
  })

  it("줄바꿈 병합: 8자 이하 한글 조각도 병합", () => {
    const items = [ti("대한민국", 10, 100), ti("여권번호", 10, 80)]
    const result = cellTextToString(items)
    // "여권번호" = 4자 (8자 이하) → 병합
    assert.equal(result, "대한민국여권번호")
  })

  it("줄바꿈 병합: 9자 이상은 별도 줄로 유지", () => {
    const items = [ti("대한민국", 10, 100), ti("여권번호가들어갑니다", 10, 80)]
    const result = cellTextToString(items)
    assert.ok(result.includes("\n"), "9자 이상 텍스트는 줄바꿈 유지")
  })

  it("줄바꿈 병합: 공백 포함 한글은 병합하지 않음", () => {
    const items = [ti("대한민국", 10, 100), ti("서울 강남", 10, 80)]
    const result = cellTextToString(items)
    assert.ok(result.includes("\n"), "공백 포함 텍스트는 줄바꿈 유지")
  })

  it("단독 1글자 한글 (조사) → 이전 줄에 연결", () => {
    // "기준" + "을" → "기준을"
    const items = [ti("기준", 10, 100), ti("을", 10, 80)]
    const result = cellTextToString(items)
    assert.equal(result, "기준을")
  })
})
