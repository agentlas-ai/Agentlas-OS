/**
 * patchHwp (HWP5 서식 보존 라운드트립 패치) 테스트 — 합성 CFB 컨테이너 기반.
 *
 * 검증 항목: 문단 텍스트 교체(nChars/CHAR_SHAPE/LINE_SEG 연쇄 갱신), 표 셀 수정,
 * no-op 바이트 동일성, 컨트롤 문단 graceful skip, 암호화 거부, 특수문자/길이 변화,
 * 비수정 스트림 바이트 보존.
 */

import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { createRequire } from "module"
import { patchHwp } from "../src/roundtrip/hwp5-patch.js"
import { parseHwp5Document } from "../src/hwp5/parser.js"
import { FLAG_ENCRYPTED } from "../src/hwp5/record.js"

const require = createRequire(import.meta.url)
const CFB = require("cfb")

// ─── 합성 HWP 빌더 ───────────────────────────────────

function rec(tagId: number, level: number, data: Buffer): Buffer {
  const header = Buffer.alloc(4)
  header.writeUInt32LE((tagId & 0x3ff) | ((level & 0x3ff) << 10) | (data.length << 20), 0)
  return Buffer.concat([header, data])
}

function utf16(s: string): Buffer {
  return Buffer.from(s, "utf16le")
}

/** PARA_HEADER(24B) + PARA_TEXT(+0x0d) + CHAR_SHAPE(8B) + LINE_SEG(36B) */
function paragraph(text: string, level = 0): Buffer {
  const header = Buffer.alloc(24)
  header.writeUInt32LE(text.length + 1, 0) // nChars (문단끝 포함)
  header.writeUInt32LE(0, 4)               // ctrlMask
  header.writeUInt16LE(1, 12)              // charShapeCount
  header.writeUInt16LE(0, 14)              // rangeTagCount
  header.writeUInt16LE(1, 16)              // lineSegCount
  const textData = Buffer.concat([utf16(text), Buffer.from([0x0d, 0x00])])
  return Buffer.concat([
    rec(0x42, level, header),
    rec(0x43, level + 1, textData),
    rec(0x44, level + 1, Buffer.alloc(8)),
    rec(0x45, level + 1, Buffer.alloc(36)),
  ])
}

/** 탭(인라인 컨트롤) 포함 문단 — ctrlMask에 탭 비트 세팅 */
function paragraphWithTab(text: string): Buffer {
  const tab = Buffer.alloc(16)
  tab.writeUInt16LE(0x09, 0)
  const textData = Buffer.concat([tab, utf16(text), Buffer.from([0x0d, 0x00])])
  const header = Buffer.alloc(24)
  header.writeUInt32LE(textData.length / 2, 0)
  header.writeUInt32LE(1 << 9, 4) // ctrlMask: 탭
  header.writeUInt16LE(1, 12)
  header.writeUInt16LE(1, 16)
  return Buffer.concat([
    rec(0x42, 0, header),
    rec(0x43, 1, textData),
    rec(0x44, 1, Buffer.alloc(8)),
    rec(0x45, 1, Buffer.alloc(36)),
  ])
}

/** 2x2 표 (앵커 문단 + tbl 컨트롤 + 셀 4개) */
function table2x2(cells: string[][]): Buffer {
  const anchorHeader = Buffer.alloc(24)
  const ctrlChar = Buffer.alloc(16)
  ctrlChar.writeUInt16LE(0x0b, 0)
  ctrlChar.write(" lbt", 2, "ascii") // "tbl " LE on-disk
  ctrlChar.writeUInt16LE(0x0b, 14)
  const anchorText = Buffer.concat([ctrlChar, Buffer.from([0x0d, 0x00])])
  anchorHeader.writeUInt32LE(anchorText.length / 2, 0)
  anchorHeader.writeUInt32LE(1 << 11, 4) // ctrlMask: 개체
  anchorHeader.writeUInt16LE(1, 12)
  anchorHeader.writeUInt16LE(1, 16)

  const tableData = Buffer.alloc(8)
  tableData.writeUInt16LE(2, 4)
  tableData.writeUInt16LE(2, 6)

  const parts = [
    rec(0x42, 0, anchorHeader),
    rec(0x43, 1, anchorText),
    rec(0x44, 1, Buffer.alloc(8)),
    rec(0x45, 1, Buffer.alloc(36)),
    rec(0x47, 1, Buffer.concat([Buffer.from(" lbt", "ascii"), Buffer.alloc(42)])),
    rec(0x4d, 2, tableData),
  ]
  for (let r = 0; r < 2; r++) {
    for (let c = 0; c < 2; c++) {
      const lh = Buffer.alloc(34)
      lh.writeUInt16LE(1, 0)  // paraCount
      lh.writeUInt16LE(c, 8)  // colAddr
      lh.writeUInt16LE(r, 10) // rowAddr
      lh.writeUInt16LE(1, 12)
      lh.writeUInt16LE(1, 14)
      parts.push(rec(0x48, 2, lh))
      parts.push(paragraph(cells[r][c], 2))
    }
  }
  return Buffer.concat(parts)
}

/** 합성 HWP 파일 (무압축, CFB) */
function buildHwp(sectionParts: Buffer[], flags = 0): Uint8Array {
  const fileHeader = Buffer.alloc(256)
  fileHeader.write("HWP Document File", 0, "ascii")
  fileHeader[35] = 5
  fileHeader.writeUInt32LE(flags, 36)

  const cfb = CFB.utils.cfb_new()
  CFB.utils.cfb_add(cfb, "/FileHeader", fileHeader)
  CFB.utils.cfb_add(cfb, "/DocInfo", Buffer.alloc(0))
  CFB.utils.cfb_add(cfb, "/BodyText/Section0", Buffer.concat(sectionParts))
  CFB.utils.cfb_add(cfb, "/PrvText", utf16("미리보기"))
  return new Uint8Array(CFB.write(cfb, { type: "buffer" }) as Buffer)
}

// ─── 테스트 ──────────────────────────────────────────

describe("patchHwp — 문단 텍스트 교체", () => {
  it("문단 수정이 적용되고 재파싱에 반영된다", async () => {
    const hwp = buildHwp([paragraph("첫 번째 문단입니다"), paragraph("두 번째 문단입니다")])
    const md = parseHwp5Document(Buffer.from(hwp)).markdown
    const edited = md.replace("두 번째 문단입니다", "수정된 두 번째 문단")

    const r = await patchHwp(hwp, edited)
    assert.equal(r.success, true)
    assert.equal(r.applied, 1)
    assert.equal(r.skipped.length, 0)
    const reparsed = parseHwp5Document(Buffer.from(r.data!))
    assert.ok(reparsed.markdown.includes("수정된 두 번째 문단"))
    assert.ok(reparsed.markdown.includes("첫 번째 문단입니다"))
    assert.equal(r.verification?.stats.added, 0)
    assert.equal(r.verification?.stats.removed, 0)
    assert.equal(r.verification?.stats.modified, 0)
  })

  it("길이가 크게 달라져도 nChars/레코드 크기가 정합 (축소/확장)", async () => {
    const hwp = buildHwp([paragraph("원래 텍스트"), paragraph("바뀔 문단")])
    const md = parseHwp5Document(Buffer.from(hwp)).markdown
    const long = "이 텍스트는 원본보다 훨씬 길어서 레코드 크기 재계산을 시험합니다 ".repeat(20).trim()

    const r1 = await patchHwp(hwp, md.replace("바뀔 문단", long))
    assert.equal(r1.success, true)
    assert.equal(r1.applied, 1)
    assert.ok(parseHwp5Document(Buffer.from(r1.data!)).markdown.includes("시험합니다"))

    const r2 = await patchHwp(hwp, md.replace("바뀔 문단", "짧"))
    assert.equal(r2.success, true)
    assert.equal(r2.applied, 1)
    assert.ok(parseHwp5Document(Buffer.from(r2.data!)).markdown.includes("짧"))
  })

  it("특수문자/이모지(서로게이트 페어) 텍스트가 보존된다", async () => {
    const hwp = buildHwp([paragraph("교체 대상 문단")])
    const md = parseHwp5Document(Buffer.from(hwp)).markdown
    const special = "조건 x < 3 & \"y\" > 5 😀 별점"
    const r = await patchHwp(hwp, md.replace("교체 대상 문단", special))
    assert.equal(r.success, true)
    assert.equal(r.applied, 1)
    assert.ok(parseHwp5Document(Buffer.from(r.data!)).markdown.includes("😀"))
  })

  it("no-op 패치는 원본과 바이트 동일", async () => {
    const hwp = buildHwp([paragraph("그대로인 문단")])
    const md = parseHwp5Document(Buffer.from(hwp)).markdown
    const r = await patchHwp(hwp, md)
    assert.equal(r.success, true)
    assert.equal(r.applied, 0)
    assert.deepEqual(Buffer.from(r.data!), Buffer.from(hwp))
  })
})

describe("patchHwp — 표 셀", () => {
  it("GFM 표 셀 수정이 좌표 기반으로 적용된다", async () => {
    const hwp = buildHwp([
      paragraph("표 앞 문단"),
      table2x2([["항목", "값"], ["점수", "80"]]),
    ])
    const md = parseHwp5Document(Buffer.from(hwp)).markdown
    assert.ok(md.includes("| 점수 | 80 |"), `GFM 표 렌더 확인: ${md}`)
    const r = await patchHwp(hwp, md.replace("| 점수 | 80 |", "| 점수 | 95 |"))
    assert.equal(r.success, true)
    assert.equal(r.applied, 1)
    const reparsed = parseHwp5Document(Buffer.from(r.data!)).markdown
    assert.ok(reparsed.includes("| 점수 | 95 |"))
    assert.ok(reparsed.includes("| 항목 | 값 |"))
  })
})

describe("patchHwp — 안전 게이트", () => {
  it("컨트롤 문자(탭) 포함 문단은 graceful skip — 파일은 그대로", async () => {
    const hwp = buildHwp([paragraphWithTab("탭이 있는 문단")])
    const md = parseHwp5Document(Buffer.from(hwp)).markdown
    const target = md.split("\n\n").find(u => u.includes("탭이 있는 문단"))!
    const r = await patchHwp(hwp, md.replace(target, "탭 없는 새 문단"))
    assert.equal(r.success, true)
    assert.equal(r.applied, 0)
    assert.ok(r.skipped.length >= 1)
    assert.deepEqual(Buffer.from(r.data!), Buffer.from(hwp))
  })

  it("암호화 문서는 전체 거부", async () => {
    const hwp = buildHwp([paragraph("본문")], FLAG_ENCRYPTED)
    const r = await patchHwp(hwp, "아무 마크다운")
    assert.equal(r.success, false)
    assert.match(r.error!, /암호화|배포용|DRM/)
  })

  it("블록 추가/삭제는 skip으로 보고", async () => {
    const hwp = buildHwp([paragraph("하나"), paragraph("둘셋넷")])
    const md = parseHwp5Document(Buffer.from(hwp)).markdown
    const r = await patchHwp(hwp, md + "\n\n새로 추가된 문단")
    assert.equal(r.success, true)
    assert.ok(r.skipped.some(s => s.reason.includes("추가")))
  })

  it("비수정 스트림(PrvText 등)은 바이트 보존", async () => {
    const hwp = buildHwp([paragraph("수정될 문단"), paragraph("고정 문단")])
    const md = parseHwp5Document(Buffer.from(hwp)).markdown
    const r = await patchHwp(hwp, md.replace("수정될 문단", "바뀐 문단"))
    assert.equal(r.success, true)
    assert.equal(r.applied, 1)
    const c1 = CFB.parse(Buffer.from(hwp))
    const c2 = CFB.parse(Buffer.from(r.data!))
    for (const p of ["/FileHeader", "/DocInfo", "/PrvText"]) {
      const a = Buffer.from(CFB.find(c1, p).content)
      const b = Buffer.from(CFB.find(c2, p).content)
      assert.deepEqual(b, a, `${p} 스트림이 변경됨`)
    }
    // 이물질 엔트리 미주입 — 원본에 없던 엔트리가 패치본에 생기면 안 됨
    // (합성 원본은 테스트 빌더의 CFB.write가 넣은 Sh33tJ5를 이미 포함 — 그 이상 금지)
    const names1 = new Set<string>(c1.FullPaths)
    for (const p of c2.FullPaths as string[]) {
      assert.ok(names1.has(p), `원본에 없던 엔트리 주입됨: ${JSON.stringify(p)}`)
    }
  })
})
