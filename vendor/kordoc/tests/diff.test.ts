/** 문서 비교 (Diff) 테스트 */

import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { similarity, normalizedSimilarity, textDiff } from "../src/diff/text-diff.js"
import { diffBlocks } from "../src/diff/compare.js"
import type { IRBlock } from "../src/types.js"

describe("text-diff: similarity", () => {
  it("동일 문자열 → 1.0", () => {
    assert.equal(similarity("안녕하세요", "안녕하세요"), 1)
  })

  it("빈 문자열 비교 → 0", () => {
    assert.equal(similarity("", "abc"), 0)
    assert.equal(similarity("abc", ""), 0)
  })

  it("양쪽 빈 → 1", () => {
    assert.equal(similarity("", ""), 1)
  })

  it("유사한 문자열 → 높은 유사도", () => {
    const sim = similarity("대한민국 헌법 제1조", "대한민국 헌법 제2조")
    assert.ok(sim > 0.8, `유사도: ${sim}`)
  })

  it("완전히 다른 문자열 → 낮은 유사도", () => {
    const sim = similarity("abcdef", "xyz123")
    assert.ok(sim < 0.3, `유사도: ${sim}`)
  })
})

describe("text-diff: normalizedSimilarity", () => {
  it("공백 차이 무시", () => {
    const sim = normalizedSimilarity("대한민국  헌법", "대한민국 헌법")
    assert.equal(sim, 1)
  })
})

describe("text-diff: textDiff", () => {
  it("동일 텍스트 → equal만", () => {
    const diffs = textDiff("a b c", "a b c")
    assert.ok(diffs.every(d => d.type === "equal"))
  })

  it("삽입 감지", () => {
    const diffs = textDiff("a c", "a b c")
    assert.ok(diffs.some(d => d.type === "insert"), "insert 존재")
  })

  it("삭제 감지", () => {
    const diffs = textDiff("a b c", "a c")
    assert.ok(diffs.some(d => d.type === "delete"), "delete 존재")
  })
})

describe("diffBlocks", () => {
  it("동일 블록 → unchanged", () => {
    const blocks: IRBlock[] = [{ type: "paragraph", text: "테스트 문단" }]
    const result = diffBlocks(blocks, blocks)
    assert.equal(result.stats.unchanged, 1)
    assert.equal(result.stats.added, 0)
    assert.equal(result.stats.removed, 0)
  })

  it("추가된 블록 감지", () => {
    const a: IRBlock[] = [{ type: "paragraph", text: "원본" }]
    const b: IRBlock[] = [{ type: "paragraph", text: "원본" }, { type: "paragraph", text: "추가됨" }]
    const result = diffBlocks(a, b)
    assert.equal(result.stats.added, 1)
    assert.ok(result.diffs.some(d => d.type === "added"))
  })

  it("삭제된 블록 감지", () => {
    const a: IRBlock[] = [{ type: "paragraph", text: "원본" }, { type: "paragraph", text: "삭제될 것" }]
    const b: IRBlock[] = [{ type: "paragraph", text: "원본" }]
    const result = diffBlocks(a, b)
    assert.equal(result.stats.removed, 1)
  })

  it("수정된 블록 감지", () => {
    const a: IRBlock[] = [{ type: "paragraph", text: "제1조 대한민국은 민주공화국이다" }]
    const b: IRBlock[] = [{ type: "paragraph", text: "제1조 대한민국은 자유민주공화국이다" }]
    const result = diffBlocks(a, b)
    assert.equal(result.stats.modified, 1)
    assert.ok(result.diffs[0].similarity! > 0.5)
  })

  it("빈 블록 배열 비교", () => {
    const result = diffBlocks([], [])
    assert.equal(result.stats.added, 0)
    assert.equal(result.diffs.length, 0)
  })

  it("테이블 블록 modified → cellDiffs 생성", () => {
    const tableA: IRBlock = { type: "table", table: { rows: 1, cols: 2, cells: [[{ text: "이름", colSpan: 1, rowSpan: 1 }, { text: "홍길동", colSpan: 1, rowSpan: 1 }]], hasHeader: false } }
    const tableB: IRBlock = { type: "table", table: { rows: 1, cols: 2, cells: [[{ text: "이름", colSpan: 1, rowSpan: 1 }, { text: "김철수", colSpan: 1, rowSpan: 1 }]], hasHeader: false } }
    const result = diffBlocks([tableA], [tableB])
    assert.equal(result.stats.modified, 1)
    const diff = result.diffs[0]
    assert.ok(diff.cellDiffs, "cellDiffs 존재")
    assert.equal(diff.cellDiffs![0][0].type, "unchanged") // "이름" 동일
    assert.equal(diff.cellDiffs![0][1].type, "modified") // 값 변경
  })
})
