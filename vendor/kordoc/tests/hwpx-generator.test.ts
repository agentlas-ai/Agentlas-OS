/** HWPX 역변환 (generator) 테스트 — 라운드트립 검증 */

import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { markdownToHwpx } from "../src/hwpx/generator.js"
import { parse } from "../src/index.js"

describe("markdownToHwpx", () => {
  it("단순 텍스트 → HWPX → 라운드트립", async () => {
    const md = "대한민국 헌법 제1조"
    const hwpxBuf = await markdownToHwpx(md)

    assert.ok(hwpxBuf instanceof ArrayBuffer, "ArrayBuffer 반환")
    assert.ok(hwpxBuf.byteLength > 0, "비어있지 않음")

    // 라운드트립: 생성된 HWPX를 다시 파싱
    const result = await parse(hwpxBuf)
    assert.equal(result.success, true, `파싱 실패: ${result.success === false ? result.error : ""}`)
    if (result.success) {
      assert.ok(result.markdown.includes("대한민국 헌법 제1조"), "원본 텍스트 보존")
    }
  })

  it("멀티 단락 → 라운드트립", async () => {
    const md = "첫 번째 단락\n\n두 번째 단락\n\n세 번째 단락"
    const hwpxBuf = await markdownToHwpx(md)
    const result = await parse(hwpxBuf)

    assert.equal(result.success, true)
    if (result.success) {
      assert.ok(result.markdown.includes("첫 번째 단락"))
      assert.ok(result.markdown.includes("두 번째 단락"))
      assert.ok(result.markdown.includes("세 번째 단락"))
    }
  })

  it("테이블 → HWPX → 라운드트립", async () => {
    const md = "| 이름 | 직급 |\n| --- | --- |\n| 홍길동 | 과장 |"
    const hwpxBuf = await markdownToHwpx(md)
    const result = await parse(hwpxBuf)

    assert.equal(result.success, true)
    if (result.success) {
      assert.ok(result.markdown.includes("이름"), "헤더 보존")
      assert.ok(result.markdown.includes("홍길동"), "데이터 보존")
      // table 블록 존재
      assert.ok(result.blocks.some(b => b.type === "table"), "테이블 블록 존재")
    }
  })

  it("헤딩 + 본문 혼합", async () => {
    const md = "# 제1장 총강\n\n대한민국은 민주공화국이다.\n\n# 제2장 권리\n\n모든 국민은 법 앞에 평등하다."
    const hwpxBuf = await markdownToHwpx(md)
    const result = await parse(hwpxBuf)

    assert.equal(result.success, true)
    if (result.success) {
      assert.ok(result.markdown.includes("제1장 총강"))
      assert.ok(result.markdown.includes("민주공화국"))
      assert.ok(result.markdown.includes("제2장 권리"))
    }
  })

  it("빈 마크다운 → 유효한 HWPX (빈 내용)", async () => {
    const hwpxBuf = await markdownToHwpx("")
    assert.ok(hwpxBuf.byteLength > 0, "ZIP은 생성됨")

    const result = await parse(hwpxBuf)
    // 빈 섹션이면 파싱은 성공하지만 내용 없음
    assert.equal(result.success, true)
  })

  it("특수문자 XML 이스케이프", async () => {
    const md = "A < B & C > D \"E\""
    const hwpxBuf = await markdownToHwpx(md)
    const result = await parse(hwpxBuf)

    assert.equal(result.success, true)
    if (result.success) {
      assert.ok(result.markdown.includes("A < B"), "< 보존")
      assert.ok(result.markdown.includes("& C"), "& 보존")
    }
  })
})
