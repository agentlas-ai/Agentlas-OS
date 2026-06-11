import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { detectClusterTables, type ClusterItem } from "../src/pdf/cluster-detector.js"

/** 헬퍼: 간단한 텍스트 아이템 생성 */
function item(text: string, x: number, y: number, w = 40, fontSize = 12): ClusterItem {
  return { text, x, y, w, h: fontSize, fontSize, fontName: "Test" }
}

describe("detectClusterTables", () => {
  it("2열 × 4행 정렬된 텍스트 → 테이블 감지", () => {
    // 2열 key-value 테이블 시뮬레이션
    const items: ClusterItem[] = [
      // col1(x=50), col2(x=200) — 갭이 fontSize*1.5 이상
      item("구분", 50, 400),    item("내용", 200, 400),
      item("이름", 50, 380),    item("홍길동", 200, 380),
      item("나이", 50, 360),    item("30세", 200, 360),
      item("주소", 50, 340),    item("서울시", 200, 340),
    ]

    const results = detectClusterTables(items, 1)
    assert.ok(results.length > 0, "테이블이 감지되어야 함")
    assert.equal(results[0].table.cols, 2)
    assert.ok(results[0].table.rows >= 3)
  })

  it("3열 × 3행 테���블 감지", () => {
    const items: ClusterItem[] = [
      item("번호", 50, 400), item("이름", 200, 400), item("금액", 350, 400),
      item("1", 50, 380),    item("사과", 200, 380), item("1000", 350, 380),
      item("2", 50, 360),    item("배", 200, 360),   item("2000", 350, 360),
    ]

    const results = detectClusterTables(items, 1)
    assert.ok(results.length > 0, "3열 테이블 감지")
    assert.equal(results[0].table.cols, 3)
  })

  it("단일 열 텍스트(문단) → 테이블 아님", () => {
    const items: ClusterItem[] = [
      item("첫째 줄 내용입니다", 50, 400, 200),
      item("둘째 줄 내용입니다", 50, 380, 200),
      item("셋째 줄 내용입니다", 50, 360, 200),
    ]

    const results = detectClusterTables(items, 1)
    assert.equal(results.length, 0, "단일 열은 테이블이 아님")
  })

  it("아이템이 너무 적으면 테이블 아님", () => {
    const items: ClusterItem[] = [
      item("A", 50, 400), item("B", 200, 400),
    ]
    const results = detectClusterTables(items, 1)
    assert.equal(results.length, 0)
  })

  it("빈 배열 → 빈 결과", () => {
    assert.deepEqual(detectClusterTables([], 1), [])
  })
})
