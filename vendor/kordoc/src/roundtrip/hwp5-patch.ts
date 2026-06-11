/**
 * HWP 5.x 바이너리 서식 보존 무손실 라운드트립 패치 — patchHwpx의 HWP5 대응.
 *
 * parse()로 얻은 마크다운을 편집한 뒤 patchHwp()에 넘기면, 원본 HWP의
 * CFB/레코드 구조를 그대로 두고 변경된 문단/표 셀의 PARA_TEXT만 치환한다.
 * 연쇄 갱신: PARA_HEADER nChars, CHAR_SHAPE 위치, LINE_SEG 재구성, 레코드
 * 크기 재계산 → 섹션 스트림 재직렬화 → deflate 재압축 → CFB 재조립.
 *
 * 안전 게이트 (하나라도 깨지면 해당 수정은 graceful skip — 파일 무결성 우선):
 *  - 섹션 레코드 재직렬화가 원본과 바이트 동일해야 패치 허용
 *  - ctrlMask=0(순수 텍스트) + PARA_TEXT 1개 + 레코드 텍스트 재구성 일치 문단만 수정
 *  - 배포용/암호화/DRM 문서는 전체 거부
 *
 * 지원: 본문 문단/헤딩 텍스트 수정, GFM 표 셀 텍스트 수정 (좌표 기반).
 * 미지원(graceful skip): 블록 추가/삭제, 표 구조 변경, HTML 표 셀, 캡션·각주·
 * 머리말/꼬리말, 컨트롤(탭/개체/필드) 포함 문단. skipped[]에 사유 보고.
 */

import { deflateRawSync } from "zlib"
import { createRequire } from "module"
import { parseHwp5Document } from "../hwp5/parser.js"
import {
  decompressStream, parseFileHeader, createParaTextState, appendParaText,
  TAG_PARA_HEADER, TAG_PARA_TEXT, TAG_CHAR_SHAPE, TAG_CTRL_HEADER, TAG_LIST_HEADER, TAG_TABLE,
  FLAG_COMPRESSED, FLAG_ENCRYPTED, FLAG_DISTRIBUTION, FLAG_DRM,
} from "../hwp5/record.js"
import type { IRBlock, IRTable, PatchOptions, PatchResult, PatchSkip, DiffResult } from "../types.js"
import {
  buildOrigUnits, alignUnits, diffUnitLists, textUnitToPlain, type OrigUnit,
} from "./patcher.js"
import {
  splitMarkdownUnits, normForMatch, sanitizeText, parseGfmTable, unescapeGfmCell, unescapeGfm, escapeGfm, summarize,
  type MdUnit,
} from "./markdown-units.js"
import { stripCellTokens, extractCellTokens } from "./table-patch.js"
import { replaceOleStream } from "./ole-surgeon.js"

const require = createRequire(import.meta.url)
const CFB: CfbModule = require("cfb")

interface CfbEntry { name?: string; content?: Buffer | Uint8Array; size?: number }
interface CfbContainer { FileIndex: CfbEntry[]; FullPaths: string[] }
interface CfbModule {
  parse(data: Buffer): CfbContainer
  find(cfb: CfbContainer, path: string): CfbEntry | null
  write(cfb: CfbContainer, opts: { type: "buffer" }): Buffer
}

// 본문 레코드 태그 — record.ts의 TAG_PARA_SHAPE(0x45)는 본문 맥락에선 LINE_SEG
const TAG_PARA_LINE_SEG = 0x0045

/** 4바이트 ASCII → u32 컨트롤 ID ("tbl " → 0x74626c20) — parser.ts cid와 동일 */
function cid(s: string): number {
  return ((s.charCodeAt(0) << 24) | (s.charCodeAt(1) << 16) | (s.charCodeAt(2) << 8) | s.charCodeAt(3)) >>> 0
}
const CTRL_TBL = cid("tbl ")
const CTRL_GSO = cid("gso ")

function swap32(id: number): number {
  return (((id & 0xff) << 24) | (((id >>> 8) & 0xff) << 16) | (((id >>> 16) & 0xff) << 8) | ((id >>> 24) & 0xff)) >>> 0
}
function isCtrl(rec: RawRecord, id: number): boolean {
  if (rec.tagId !== TAG_CTRL_HEADER || rec.data.length < 4) return false
  const raw = rec.data.readUInt32LE(0)
  return raw === id || swap32(raw) === id
}

// ─── 레코드 입출력 (엄격 모드 + 재직렬화 동일성 게이트) ──

interface RawRecord { tagId: number; level: number; data: Buffer }

/** 스트림 끝까지 정확히 소비될 때만 성공 — 잔여/비정형 바이트가 있으면 null */
function readRecordsStrict(stream: Buffer): RawRecord[] | null {
  const recs: RawRecord[] = []
  let off = 0
  while (off < stream.length) {
    if (off + 4 > stream.length) return null
    const h = stream.readUInt32LE(off); off += 4
    const tagId = h & 0x3ff
    const level = (h >>> 10) & 0x3ff
    let size = (h >>> 20) & 0xfff
    if (size === 0xfff) {
      if (off + 4 > stream.length) return null
      size = stream.readUInt32LE(off); off += 4
    }
    if (off + size > stream.length) return null
    recs.push({ tagId, level, data: stream.subarray(off, off + size) })
    off += size
  }
  return recs
}

function serializeRecords(recs: RawRecord[], repl?: Map<number, Buffer>): Buffer {
  const parts: Buffer[] = []
  for (let i = 0; i < recs.length; i++) {
    const data = repl?.get(i) ?? recs[i].data
    const ext = data.length >= 0xfff
    const header = Buffer.alloc(ext ? 8 : 4)
    header.writeUInt32LE(((recs[i].tagId & 0x3ff) | ((recs[i].level & 0x3ff) << 10) | ((ext ? 0xfff : data.length) << 20)) >>> 0, 0)
    if (ext) header.writeUInt32LE(data.length, 4)
    parts.push(header, data)
  }
  return Buffer.concat(parts)
}

// ─── 섹션 스캔 ───────────────────────────────────────

interface ScanPara5 {
  sectionIndex: number
  headerIdx: number
  kind: "body" | "cell" | "other"
  /** PARA_TEXT 레코드 인덱스: -1=없음(빈 문단), -2=복수(미지원) */
  textIdx: number
  charShapeIdx: number
  lineSegIdx: number
  rangeTagCount: number
  ctrlMask: number
  nCharsRaw: number
  /** extractText 결과 (트림 전 원문) */
  rawText: string
}

interface ScanCell5 { paras: ScanPara5[] }

interface ScanTable5 {
  sectionIndex: number
  rows: number
  cols: number
  /** "row,col" → 셀 (앵커 좌표 기준) */
  cells: Map<string, ScanCell5>
}

interface SectionScan5 {
  records: RawRecord[]
  /** 재직렬화 바이트 동일성 통과 여부 — 실패 시 이 섹션 패치 금지 */
  safe: boolean
  paras: ScanPara5[]
  tables: ScanTable5[]
  compressed: boolean
  /** 수정 스테이징: 레코드 인덱스 → 새 데이터 */
  repl: Map<number, Buffer>
}

function scanSection(stream: Buffer, sectionIndex: number, compressed: boolean): SectionScan5 {
  const records = readRecordsStrict(stream)
  if (!records) return { records: [], safe: false, paras: [], tables: [], compressed, repl: new Map() }
  const safe = serializeRecords(records).equals(stream)

  // 부모 인덱스 계산 (level 기반 스택)
  const parent = new Int32Array(records.length).fill(-1)
  const stack: number[] = []
  for (let i = 0; i < records.length; i++) {
    while (stack.length > 0 && records[stack[stack.length - 1]].level >= records[i].level) stack.pop()
    parent[i] = stack.length > 0 ? stack[stack.length - 1] : -1
    stack.push(i)
  }
  const ancestorCtrl = (i: number, id: number): boolean => {
    for (let p = parent[i]; p >= 0; p = parent[p]) if (isCtrl(records[p], id)) return true
    return false
  }

  // 문단 수집
  const paras: ScanPara5[] = []
  const parasByHeader = new Map<number, ScanPara5>()
  for (let i = 0; i < records.length; i++) {
    const rec = records[i]
    if (rec.tagId !== TAG_PARA_HEADER || rec.data.length < 18) continue
    let textIdx = -1
    let charShapeIdx = -1
    let lineSegIdx = -1
    const state = createParaTextState()
    for (let j = i + 1; j < records.length && records[j].level > rec.level; j++) {
      if (records[j].level !== rec.level + 1) continue
      const t = records[j].tagId
      if (t === TAG_PARA_TEXT) {
        textIdx = textIdx === -1 ? j : -2
        appendParaText(state, records[j].data)
      } else if (t === TAG_CHAR_SHAPE && charShapeIdx === -1) charShapeIdx = j
      else if (t === TAG_PARA_LINE_SEG && lineSegIdx === -1) lineSegIdx = j
    }

    // 분류: 컨트롤 무관(또는 글상자 내부) → body, 그 외 → other.
    // 표 셀 문단은 아래 표 수집 패스에서 "cell"로 재분류된다 (셀 문단은
    // LIST_HEADER의 자식이 아니라 같은 레벨 형제 — 부모 체인으론 식별 불가).
    let ctrlSeen = false, nonGso = false
    for (let a = parent[i]; a >= 0; a = parent[a]) {
      if (records[a].tagId === TAG_CTRL_HEADER) {
        ctrlSeen = true
        if (!isCtrl(records[a], CTRL_GSO)) nonGso = true
      }
    }
    const kind: ScanPara5["kind"] = !ctrlSeen || !nonGso ? "body" : "other"

    const para: ScanPara5 = {
      sectionIndex, headerIdx: i, kind, textIdx, charShapeIdx, lineSegIdx,
      rangeTagCount: rec.data.readUInt16LE(14),
      ctrlMask: rec.data.readUInt32LE(4),
      nCharsRaw: rec.data.readUInt32LE(0),
      rawText: state.text,
    }
    paras.push(para)
    parasByHeader.set(i, para)
  }

  // 최상위 표 수집 (다른 tbl 내부에 중첩된 표 제외 — IR 최상위 표 서수와 정렬)
  const tables: ScanTable5[] = []
  for (let i = 0; i < records.length; i++) {
    if (!isCtrl(records[i], CTRL_TBL) || ancestorCtrl(i, CTRL_TBL)) continue
    const ctrlLevel = records[i].level
    let rows = 0, cols = 0, tableIdx = -1
    for (let j = i + 1; j < records.length && records[j].level > ctrlLevel; j++) {
      if (records[j].level === ctrlLevel + 1 && records[j].tagId === TAG_TABLE && records[j].data.length >= 8) {
        rows = records[j].data.readUInt16LE(4)
        cols = records[j].data.readUInt16LE(6)
        tableIdx = j
        break
      }
    }
    if (tableIdx < 0 || rows === 0 || cols === 0) continue
    // 셀 문단은 LIST_HEADER와 같은 레벨의 후속 형제 — parser.ts parseCell과 동일 경계
    const cells = new Map<string, ScanCell5>()
    let j = tableIdx + 1
    while (j < records.length && records[j].level > ctrlLevel) {
      if (records[j].tagId !== TAG_LIST_HEADER) { j++; continue }
      const lh = records[j]
      const cellLevel = lh.level
      const cellParas: ScanPara5[] = []
      let k = j + 1
      while (k < records.length) {
        const r = records[k]
        if (r.level < cellLevel) break
        if (r.level === cellLevel && (r.tagId === TAG_LIST_HEADER || r.tagId === TAG_TABLE)) break
        if (r.level === cellLevel && r.tagId === TAG_PARA_HEADER) {
          const cp = parasByHeader.get(k)
          if (cp) { cp.kind = "cell"; cellParas.push(cp) }
        }
        k++
      }
      if (lh.data.length >= 16) {
        cells.set(`${lh.data.readUInt16LE(10)},${lh.data.readUInt16LE(8)}`, { paras: cellParas })
      }
      j = k
    }
    tables.push({ sectionIndex, rows, cols, cells })
  }

  return { records, safe, paras, tables, compressed, repl: new Map() }
}

// ─── 메인 API ────────────────────────────────────────

/**
 * 원본 HWP 5.x와 편집된 마크다운으로 서식 보존 패치본을 만든다.
 *
 * @param original 원본 HWP 바이트 (OLE2/CFB)
 * @param editedMarkdown parse(original).markdown을 편집한 마크다운
 */
export async function patchHwp(
  original: Uint8Array,
  editedMarkdown: string,
  options?: PatchOptions,
): Promise<PatchResult> {
  const skipped: PatchSkip[] = []
  let applied = 0
  const originalBuf = Buffer.from(original.buffer, original.byteOffset, original.byteLength)

  // 1) CFB + FileHeader — 배포용/암호화 거부
  let cfb: CfbContainer
  try {
    cfb = CFB.parse(originalBuf)
  } catch (err) {
    return fail(`CFB 컨테이너 파싱 실패: ${msg(err)}`)
  }
  const fhEntry = CFB.find(cfb, "/FileHeader")
  if (!fhEntry?.content) return fail("FileHeader 스트림이 없습니다 — HWP 5.x 파일이 아닙니다")
  let flags: number
  try {
    flags = parseFileHeader(Buffer.from(fhEntry.content)).flags
  } catch (err) {
    return fail(`FileHeader 파싱 실패: ${msg(err)}`)
  }
  if (flags & (FLAG_ENCRYPTED | FLAG_DISTRIBUTION | FLAG_DRM)) {
    return fail("암호화/배포용/DRM 문서는 패치를 지원하지 않습니다")
  }
  const compressed = (flags & FLAG_COMPRESSED) !== 0

  // 2) 원본 파싱 (기존 파서 그대로 — IR 블록 확보)
  let origBlocks: IRBlock[]
  try {
    origBlocks = parseHwp5Document(originalBuf).blocks
  } catch (err) {
    return fail(`원본 HWP 파싱 실패: ${msg(err)}`)
  }

  // 3) 섹션 스트림 스캔
  const sectionPaths = cfb.FullPaths
    .map(p => p.replace(/^Root Entry/, ""))
    .filter(p => /^\/BodyText\/Section\d+$/.test(p))
    .sort((a, b) => Number(a.match(/\d+$/)![0]) - Number(b.match(/\d+$/)![0]))
  if (sectionPaths.length === 0) return fail("BodyText 섹션 스트림을 찾을 수 없습니다")

  const scans: SectionScan5[] = []
  for (let i = 0; i < sectionPaths.length; i++) {
    const entry = CFB.find(cfb, sectionPaths[i])
    if (!entry?.content) return fail(`섹션 스트림 읽기 실패: ${sectionPaths[i]}`)
    let stream: Buffer
    try {
      stream = compressed ? decompressStream(Buffer.from(entry.content)) : Buffer.from(entry.content)
    } catch (err) {
      return fail(`섹션 압축 해제 실패: ${msg(err)}`)
    }
    scans.push(scanSection(stream, i, compressed))
  }

  // 4) 유닛 구성 + 정렬 (HWPX 패처와 동일한 마크다운 도메인 diff)
  const origUnits = buildOrigUnits(origBlocks)
  const editedUnits = splitMarkdownUnits(editedMarkdown)
  const pairs = alignUnits(origUnits.map(u => u.raw), editedUnits.map(u => u.raw))

  const paraMap = resolveParaMappings(origBlocks, scans)
  const scanTables = scans.flatMap(s => s.tables)
  const obTableOrdinals = new Map<number, number>()
  {
    let ordinal = 0
    for (let i = 0; i < origBlocks.length; i++) {
      if (origBlocks[i].type === "table" && origBlocks[i].table) obTableOrdinals.set(i, ordinal++)
    }
  }

  // 5) 변경 적용 (스테이징)
  for (const [oi, ei] of pairs) {
    if (oi !== null && ei !== null) {
      const orig = origUnits[oi]
      const edited = editedUnits[ei]
      if (orig.raw === edited.raw) continue
      applied += handleModified(orig, edited, {
        origBlocks, paraMap, scans, scanTables, obTableOrdinals, skipped,
      })
    } else if (oi !== null) {
      skipped.push({ reason: "블록 삭제는 미지원 (v1) — 원본 유지", before: summarize(origUnits[oi].raw) })
    } else if (ei !== null) {
      skipped.push({ reason: "블록 추가는 미지원 (v1)", after: summarize(editedUnits[ei].raw) })
    }
  }

  // 6) 섹션 재직렬화 + 재압축 + 섹터 레벨 in-place 교체 — 컨테이너 전체 재조립 없음
  //    (수정된 섹션의 데이터 섹터/FAT 체인/디렉토리 start·size 외에는 원본 바이트 유지)
  let data: Uint8Array
  const dirty = scans.some(s => s.repl.size > 0)
  if (!dirty) {
    data = new Uint8Array(original)
  } else {
    try {
      let out = originalBuf
      for (let i = 0; i < scans.length; i++) {
        if (scans[i].repl.size === 0) continue
        const newStream = serializeRecords(scans[i].records, scans[i].repl)
        const content = compressed ? deflateRawSync(newStream) : newStream
        out = replaceOleStream(out, sectionPaths[i], content)
      }
      data = new Uint8Array(out)
    } catch (err) {
      return { success: false, applied: 0, skipped, error: `HWP 섹터 수술 실패: ${msg(err)}` }
    }
  }

  // 7) 자동 검증 — 패치본 재파싱 vs 편집 마크다운
  let verification: DiffResult | undefined
  if (options?.verify !== false) {
    try {
      const reparsed = parseHwp5Document(Buffer.from(data))
      verification = diffUnitLists(splitMarkdownUnits(reparsed.markdown), editedUnits)
    } catch (err) {
      return { success: false, applied, skipped, error: `패치본 재파싱 실패 — 패치 중단: ${msg(err)}` }
    }
  }

  return { success: true, data, applied, skipped, verification }

  function fail(error: string): PatchResult {
    return { success: false, applied: 0, skipped, error }
  }
}

function msg(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

// ─── 문단 매핑 (IR 블록 ↔ 스캔 문단) ─────────────────

interface ParaMapping5 {
  para?: ScanPara5
  /** 자동번호/글머리 접두가 IR 텍스트에 붙어 있었음 (레코드 텍스트에는 없음) */
  prefixStripped?: boolean
}

/**
 * 같은 정규화 텍스트끼리 등장 순서대로 페어링 (중복 문단 대응) — HWPX 패처와 동일 방식.
 * 셀 문단도 버킷에 포함 (flattenLayoutTables로 해체된 레이아웃 표 문단이 IR에선 문단 블록).
 * 단, 같은 텍스트가 여러 위치에 있고 본문 문단만으로 구성되지 않으면 모호 — 매핑 포기.
 */
function resolveParaMappings(blocks: IRBlock[], scans: SectionScan5[]): Map<number, ParaMapping5> {
  const buckets = new Map<string, ScanPara5[]>()
  for (const scan of scans) {
    for (const para of scan.paras) {
      if (para.kind === "other") continue
      const key = normForMatch(para.rawText)
      if (!key) continue
      let list = buckets.get(key)
      if (!list) buckets.set(key, (list = []))
      list.push(para)
    }
  }
  /** 중복 텍스트는 전부 본문 문단일 때만 등장 순서 페어링 신뢰 가능 */
  const usable = (list: ScanPara5[]): boolean =>
    list.length === 1 || list.every(p => p.kind === "body")

  const counters = new Map<string, number>()
  const result = new Map<number, ParaMapping5>()
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i]
    if ((b.type !== "paragraph" && b.type !== "heading") || !b.text) continue
    let key = normForMatch(b.text)
    let prefixStripped = false
    if (!buckets.has(key)) {
      // 자동번호/글머리 접두 제거 후 재시도 (파서가 붙인 headMarker)
      const sp = b.text.indexOf(" ")
      if (sp > 0) {
        const alt = normForMatch(b.text.slice(sp + 1))
        if (alt && buckets.has(alt)) { key = alt; prefixStripped = true }
      }
    }
    const list = buckets.get(key)
    if (!list || !usable(list)) { result.set(i, {}); continue }
    const occ = counters.get(key) ?? 0
    counters.set(key, occ + 1)
    result.set(i, occ < list.length ? { para: list[occ], prefixStripped } : {})
  }
  return result
}

// ─── 변경 처리 ───────────────────────────────────────

interface PatchCtx5 {
  origBlocks: IRBlock[]
  paraMap: Map<number, ParaMapping5>
  scans: SectionScan5[]
  scanTables: ScanTable5[]
  obTableOrdinals: Map<number, number>
  skipped: PatchSkip[]
}

function handleModified(orig: OrigUnit, edited: MdUnit, ctx: PatchCtx5): number {
  const block = ctx.origBlocks[orig.blockIdx]
  const skip = (reason: string) => {
    ctx.skipped.push({ reason, before: summarize(orig.raw), after: summarize(edited.raw) })
    return 0
  }

  if (orig.role === "caption") return skip("표 캡션 수정은 미지원 (v1)")
  if (orig.kind === "separator" || orig.kind === "image") return skip("이미지/구분선 변경은 미지원")
  if (!block) return skip("블록 매핑 실패")
  if (orig.fragment) return skip("문단 분절(강제 줄바꿈/병합 유닛) — 부분 수정은 미지원 (v1)")

  if (block.type === "table" && block.table) {
    if (orig.kind !== edited.kind) return skip("표 ↔ 비표 변경은 미지원 (표 구조 변경)")
    if (ctx.obTableOrdinals.size !== ctx.scanTables.length) return skip("표 개수 불일치 — 소스맵 신뢰 불가")
    const ordinal = ctx.obTableOrdinals.get(orig.blockIdx)
    const scanTable = ordinal !== undefined ? ctx.scanTables[ordinal] : undefined
    if (!scanTable) return skip("표 소스맵 매핑 실패")
    if (orig.kind === "gfm-table") return patchGfmCells(scanTable, orig, edited, ctx, skip)
    if (orig.kind === "html-table") return skip("HTML 표(병합/줄바꿈 셀) 수정은 HWP5 미지원 (v1)")
    return patchTextChunk5(block.table, scanTable, orig, edited, ctx, skip)
  }

  if ((block.type === "paragraph" || block.type === "heading") && orig.kind === "text" && edited.kind === "text") {
    return patchParagraph(block, orig, edited, ctx, skip)
  }

  return skip("지원하지 않는 블록 유형 변경")
}

// ── 문단 ──

function patchParagraph(
  block: IRBlock, orig: OrigUnit, edited: MdUnit, ctx: PatchCtx5,
  skip: (reason: string) => number,
): number {
  const mapping = ctx.paraMap.get(orig.blockIdx)
  if (!mapping?.para) return skip("문단 소스맵 매핑 실패 (머리말/글상자/캡션 영역이거나 텍스트 불일치)")
  if (block.text && block.text.includes("\n")) {
    return skip("문단 내 강제 줄바꿈 포함 — 수정 시 줄바꿈 보존 불가로 미지원 (v1)")
  }

  let newPlain = textUnitToPlain(edited.raw, block)

  // 각주 표기 — 본문이 아닌 각주 컨트롤에 있으므로 분리
  if (block.footnoteText) {
    const noteMatch = newPlain.match(/\s*\(주: ([\s\S]*)\)$/)
    if (noteMatch) {
      newPlain = newPlain.slice(0, noteMatch.index).trimEnd()
      if (normForMatch(noteMatch[1]) !== normForMatch(block.footnoteText)) {
        ctx.skipped.push({ reason: "각주 텍스트 수정은 미지원 — 본문만 적용", before: block.footnoteText, after: noteMatch[1] })
      }
    } else {
      ctx.skipped.push({ reason: "각주 표기 삭제는 미지원 — 각주 유지, 본문만 적용", before: `(주: ${block.footnoteText})` })
    }
  }

  // 자동번호 접두 — 레코드에 없는 텍스트이므로 떼고 기록
  if (mapping.prefixStripped) {
    const origPrefix = block.text!.split(" ", 1)[0]
    const sp = newPlain.indexOf(" ")
    const newFirst = sp > 0 ? newPlain.slice(0, sp) : newPlain
    if (newFirst === origPrefix || /^(?:[0-9０-９a-zA-Z가-힣]{1,6}[.)\]:]|[([][0-9０-９a-zA-Z가-힣]{1,6}[)\]][.:]?|[ⅰ-ⅹⅠ-Ⅹ①-⑮][.)\]:]?)$/u.test(newFirst)) {
      newPlain = sp > 0 ? newPlain.slice(sp + 1) : ""
    } else {
      ctx.skipped.push({ reason: "자동번호 접두 식별 실패 — 번호 포함 텍스트로 적용 (뷰어에서 중복 표시 가능)", after: summarize(newPlain) })
    }
  }

  const origPlain = textUnitToPlain(orig.raw, block)
  if (newPlain === origPlain) return skip("텍스트 외 변경(헤딩 레벨/서식)만 감지 — 스타일 변경은 미지원")
  if (sanitizeText(newPlain) !== newPlain) {
    return skip("공백 정규화 불안정 텍스트 — 패치 시 원문 보존 불가로 미지원")
  }

  return stageParaPatch(ctx.scans[mapping.para.sectionIndex], mapping.para, newPlain, skip)
}

// ── GFM 표 셀 ──

function patchGfmCells(
  scanTable: ScanTable5, orig: OrigUnit, edited: MdUnit, ctx: PatchCtx5,
  skip: (reason: string) => number,
): number {
  const origRows = parseGfmTable(orig.lines)
  const editedRows = parseGfmTable(edited.lines)
  if (origRows.length !== editedRows.length || origRows.some((r, i) => r.length !== editedRows[i].length)) {
    return skip("표 구조 변경(행/열 수)은 미지원 (v1)")
  }

  let applied = 0
  for (let r = 0; r < origRows.length; r++) {
    for (let c = 0; c < origRows[r].length; c++) {
      if (origRows[r][c] === editedRows[r][c]) continue
      const cellSkip = (reason: string) => {
        ctx.skipped.push({ reason, before: summarize(origRows[r][c]), after: summarize(editedRows[r][c]) })
        return 0
      }
      const before = gfmCellToPlain(origRows[r][c])
      const after = gfmCellToPlain(editedRows[r][c])
      if (before === null || after === null) { cellSkip("서식/링크/이미지 포함 셀 수정은 미지원 (v1)"); continue }
      if (after.includes("\n")) { cellSkip("셀 내 줄바꿈 추가는 미지원 (v1)"); continue }

      const cell = scanTable.cells.get(`${r},${c}`)
      if (!cell) { cellSkip("병합 영역 셀 — 앵커 셀이 아니므로 미지원"); continue }
      if (cell.paras.length !== 1) { cellSkip("복수 문단 셀 수정은 미지원 (v1)"); continue }
      const para = cell.paras[0]
      if (normForMatch(para.rawText) !== normForMatch(before)) { cellSkip("셀 텍스트 불일치 — 소스맵 신뢰 불가"); continue }
      if (sanitizeText(after) !== after) { cellSkip("공백 정규화 불안정 텍스트 — 미지원"); continue }

      applied += stageParaPatch(ctx.scans[para.sectionIndex], para, after, cellSkip)
    }
  }
  return applied
}

// ── 1x1 / 1열 표 (텍스트 청크 렌더) — HWPX patchTextChunkTable 미러 ──

function patchTextChunk5(
  table: IRTable, scanTable: ScanTable5, orig: OrigUnit, edited: MdUnit, ctx: PatchCtx5,
  skip: (reason: string) => number,
): number {
  if (table.rows === 1 && table.cols === 1) {
    // builder 1x1 경로 재현 (라인별 장식 포함, 유닛 분할 시 트림됨)
    const content = sanitizeText(table.cells[0][0].text)
    const replicaLines = content.split(/\n/).map(line => {
      const t = line.trim()
      if (!t) return ""
      if (/^\d+\.\s/.test(t)) return `**${escapeGfm(t)}**`
      return escapeGfm(t)
    }).filter(Boolean)
    if (replicaLines.join("\n") !== orig.lines.join("\n")) return skip("표 좌표 재현 불일치 — 매핑 신뢰 불가")
    if (extractCellTokens(orig.raw) !== extractCellTokens(edited.raw)) return skip("셀 내 이미지 변경은 미지원")
    const newLines = edited.lines.map(l => {
      // builder는 /^\d+\.\s/ 라인에만 '**' 볼드를 부여 — 그 경우만 벗기고 리터럴 '**...**'는 보존
      const m = l.match(/^\*\*([\s\S]*)\*\*$/)
      const unwrap = m && /^\d+\.\s/.test(unescapeGfm(m[1]))
      return stripCellTokens(unescapeGfm(unwrap ? m![1] : l)).trim()
    }).filter(Boolean)
    return applyCellEdit5(table, scanTable, 0, 0, newLines, ctx, orig.raw, edited.raw, orig.lines.length)
  }

  if (table.cols === 1 && table.rows >= 2) {
    const replica: { line: string; gridR: number }[] = []
    for (let r = 0; r < table.rows; r++) {
      const line = escapeGfm(sanitizeText(table.cells[r][0].text)).replace(/\n/g, " ")
      if (line) replica.push({ line, gridR: r })
    }
    if (replica.map(x => x.line).join("\n") !== orig.lines.join("\n")) return skip("표 좌표 재현 불일치 — 매핑 신뢰 불가")
    if (edited.lines.length !== replica.length) return skip("표 행 추가/삭제는 미지원 (표 구조 변경)")
    let applied = 0
    for (let i = 0; i < replica.length; i++) {
      if (replica[i].line === edited.lines[i]) continue
      if (extractCellTokens(replica[i].line) !== extractCellTokens(edited.lines[i])) {
        skip("셀 내 이미지 변경은 미지원")
        continue
      }
      const newLines = [stripCellTokens(unescapeGfm(edited.lines[i])).trim()].filter(Boolean)
      applied += applyCellEdit5(table, scanTable, replica[i].gridR, 0, newLines, ctx, replica[i].line, edited.lines[i], 1)
    }
    return applied
  }

  return skip("표 렌더 경로 식별 실패")
}

/**
 * 격자 좌표 (gridR, gridC) 셀에 새 텍스트 라인 적용 — 라인 ↔ 셀 내 비어있지 않은
 * 문단 순서 매핑 (HWPX applyCellEdit과 동일 정책, 바이너리 스테이징판).
 */
function applyCellEdit5(
  table: IRTable, scanTable: ScanTable5, gridR: number, gridC: number,
  newLines: string[], ctx: PatchCtx5, before: string, after: string,
  origLineCount?: number,
): number {
  const skip = (reason: string) => {
    ctx.skipped.push({ reason, before: summarize(before), after: summarize(after) })
    return 0
  }
  const cell = scanTable.cells.get(`${gridR},${gridC}`)
  if (!cell) return skip("셀 좌표 매핑 실패 (병합 영역의 빈 칸이거나 좌표 불일치)")

  // 셀 콘텐츠 검증 — 스캔 문단 합산과 IR 셀 텍스트의 정규화 일치
  const irCell = table.cells[gridR]?.[gridC]
  const scanJoined = cell.paras.map(p => p.rawText).filter(t => normForMatch(t)).join("\n")
  if (irCell && normForMatch(scanJoined) !== normForMatch(stripCellTokens(irCell.text))) {
    if (normForMatch(irCell.text) !== "" || normForMatch(scanJoined) !== "") {
      const flatBlocks = (irCell.blocks ?? []).filter(b => b.type === "paragraph" || b.type === "heading")
      const flatJoined = flatBlocks.map(b => b.text ?? "").join("\n")
      if (normForMatch(scanJoined) !== normForMatch(flatJoined)) {
        return skip("셀 콘텐츠 구조 복잡 (중첩표/글상자) — 매핑 신뢰 불가")
      }
    }
  }

  const nonEmpty = cell.paras.filter(p => normForMatch(p.rawText) !== "")
  if (origLineCount !== undefined && nonEmpty.length > 0 && origLineCount !== nonEmpty.length) {
    return skip("셀 줄 경계 매핑 모호 (문단 내 줄바꿈) — 미지원")
  }
  const unstable = newLines.find(l => sanitizeText(l) !== l)
  if (unstable !== undefined) return skip("공백 정규화 불안정 텍스트 — 패치 시 원문 보존 불가로 미지원")

  if (nonEmpty.length === 0) return skip("빈 셀 텍스트 채우기는 HWP5 미지원 (v1) — 문단 생성 필요")

  // 라인 → 문단 순서 매핑 (넘치는 줄은 마지막 문단에 병합, 줄어든 줄은 비움)
  const assigned: string[] = []
  for (let i = 0; i < nonEmpty.length; i++) {
    if (i < newLines.length) {
      assigned.push(i === nonEmpty.length - 1 && newLines.length > nonEmpty.length
        ? newLines.slice(i).join(" ")
        : newLines[i])
    } else {
      assigned.push("")
    }
  }
  if (newLines.length > nonEmpty.length) {
    ctx.skipped.push({ reason: "셀 내 줄 추가는 문단 생성 미지원 — 마지막 문단에 병합 적용", after: summarize(after) })
  }
  let staged = 0
  for (let i = 0; i < nonEmpty.length; i++) {
    if (assigned[i] === nonEmpty[i].rawText || normForMatch(assigned[i]) === normForMatch(nonEmpty[i].rawText)) continue
    staged += stageParaPatch(ctx.scans[nonEmpty[i].sectionIndex], nonEmpty[i], assigned[i], skip)
  }
  return staged > 0 ? 1 : 0
}

/** GFM 셀 마크다운 → 평문. 굵게 래핑(**…**)은 벗기되 내부 서식은 미지원(null) */
function gfmCellToPlain(md: string): string | null {
  let t = md.trim()
  const bold = t.match(/^\*\*([\s\S]+)\*\*$/)
  if (bold) t = bold[1]
  if (/[*`]|!\[|\]\(|<(?!br\s*\/?>)/i.test(t)) return null
  return unescapeGfm(unescapeGfmCell(t))
}

// ─── 바이너리 패치 스테이징 ──────────────────────────

const PARA_BREAK = Buffer.from([0x0d, 0x00])

/**
 * 문단 텍스트 교체를 섹션 repl 맵에 스테이징.
 * PARA_TEXT 치환 + PARA_HEADER nChars + CHAR_SHAPE/LINE_SEG 정합화.
 */
function stageParaPatch(
  scan: SectionScan5, para: ScanPara5, newPlain: string,
  skip: (reason: string) => number,
): number {
  if (!scan.safe) return skip("섹션 레코드 재직렬화 불일치 — 안전을 위해 이 섹션은 미지원")
  if (para.textIdx === -1) return skip("빈 문단 텍스트 추가는 미지원 (v1)")
  if (para.textIdx === -2) return skip("복수 PARA_TEXT 레코드 문단 — 미지원 (v1)")
  if (para.ctrlMask !== 0) return skip("컨트롤 문자 포함 문단(탭/개체/필드/특수공백) — 미지원 (v1)")
  if (para.rangeTagCount > 0) return skip("범위 태그(형광펜/교정부호) 문단 — 미지원 (v1)")
  if (para.charShapeIdx < 0 || para.lineSegIdx < 0) return skip("문단 레코드 구성 비정형 — 미지원")
  if (scan.repl.has(para.headerIdx)) return skip("동일 문단 중복 수정 — 첫 수정만 적용")
  if (/[\u0000-\u001f]/.test(newPlain)) return skip("새 텍스트에 제어문자 포함 — 미지원")

  const records = scan.records
  const headerRec = records[para.headerIdx]
  const textRec = records[para.textIdx]
  const charShapeRec = records[para.charShapeIdx]
  const lineSegRec = records[para.lineSegIdx]
  if (charShapeRec.data.length < 8 || lineSegRec.data.length < 36) {
    return skip("CHAR_SHAPE/LINE_SEG 레코드 비정형 — 미지원")
  }

  // 무결성 게이트: rawText로 PARA_TEXT를 바이트 단위 재구성할 수 있어야 함
  const hadBreak = textRec.data.length >= 2 && textRec.data.readUInt16LE(textRec.data.length - 2) === 0x000d
  const expect = hadBreak
    ? Buffer.concat([Buffer.from(para.rawText, "utf16le"), PARA_BREAK])
    : Buffer.from(para.rawText, "utf16le")
  if (!expect.equals(textRec.data)) return skip("PARA_TEXT 재구성 불일치 — 원문 보존 불가로 미지원")

  // 원문 leading/trailing 공백 보존 (IR은 트림된 텍스트)
  const lead = para.rawText.match(/^\s*/)![0]
  const trail = para.rawText.match(/\s*$/)![0]
  const newRaw = para.rawText.trim() === para.rawText ? newPlain : lead + newPlain + trail

  // PARA_TEXT
  const newText = hadBreak
    ? Buffer.concat([Buffer.from(newRaw, "utf16le"), PARA_BREAK])
    : Buffer.from(newRaw, "utf16le")
  scan.repl.set(para.textIdx, newText)

  // PARA_HEADER — nChars(플래그 비트 보존) + charShapeCount/lineSegCount
  const newHeader = Buffer.from(headerRec.data)
  const nChars = newRaw.length + (hadBreak ? 1 : 0)
  newHeader.writeUInt32LE(((para.nCharsRaw & 0x80000000) | nChars) >>> 0, 0)

  // CHAR_SHAPE — 여러 run이면 첫 run 스타일로 통일 (HWPX 패처와 동일 정책)
  if (charShapeRec.data.length > 8) {
    newHeader.writeUInt16LE(1, 12)
    scan.repl.set(para.charShapeIdx, Buffer.from(charShapeRec.data.subarray(0, 8)))
  }
  const csData = scan.repl.get(para.charShapeIdx) ?? Buffer.from(charShapeRec.data)
  if (csData.readUInt32LE(0) !== 0) {
    csData.writeUInt32LE(0, 0)
    scan.repl.set(para.charShapeIdx, csData)
  }

  // LINE_SEG — 단일 세그먼트로 재구성 (레이아웃 캐시, 한/글이 열 때 재계산)
  if (lineSegRec.data.length > 36 || lineSegRec.data.readUInt32LE(0) !== 0) {
    const seg = Buffer.from(lineSegRec.data.subarray(0, 36))
    seg.writeUInt32LE(0, 0)
    newHeader.writeUInt16LE(1, 16)
    scan.repl.set(para.lineSegIdx, seg)
  }

  scan.repl.set(para.headerIdx, newHeader)
  return 1
}
