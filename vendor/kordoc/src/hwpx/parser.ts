/**
 * HWPX 파서 — manifest 멀티섹션, colSpan/rowSpan, 중첩테이블
 *
 * lexdiff 기반 + edu-facility-ai 손상ZIP 복구
 */

import JSZip from "jszip"
import { inflateRawSync } from "zlib"
import { DOMParser } from "@xmldom/xmldom"
import { buildTable, convertTableToText, blocksToMarkdown, MAX_COLS, MAX_ROWS } from "../table/builder.js"
import type { CellContext, IRBlock, IRCell, IRTable, DocumentMetadata, InternalParseResult, ParseOptions, ParseWarning, OutlineItem, InlineStyle, ExtractedImage } from "../types.js"
import { HEADING_RATIO_H1, HEADING_RATIO_H2, HEADING_RATIO_H3 } from "../types.js"
import { KordocError, isPathTraversal, sanitizeHref, precheckZipSize, stripDtd } from "../utils.js"
// 테스트 호환성 re-export
export { precheckZipSize } from "../utils.js"
import { parsePageRange } from "../page-range.js"
import { isComFallbackAvailable, isEncryptedHwpx, extractTextViaCom, comResultToParseResult } from "./com-fallback.js"
import { hmlToLatex } from "./equation.js"

/** 압축 해제 최대 크기 (100MB) — ZIP bomb 방지 */
const MAX_DECOMPRESS_SIZE = 100 * 1024 * 1024
/** 손상 ZIP 복구 시 최대 엔트리 수 */
const MAX_ZIP_ENTRIES = 500

/** colSpan/rowSpan을 안전한 범위로 클램핑 */
function clampSpan(val: number, max: number): number {
  return Math.max(1, Math.min(val, max))
}

/** XML DOM 재귀 최대 깊이 — 악성 파일의 스택 오버플로 방지 */
const MAX_XML_DEPTH = 200

/** 셀 컨텍스트 확장 — 중첩표/이미지/다중문단 블록과 제목셀 여부를 IRCell로 전달 (v3.0) */
interface CellCtxEx extends CellContext {
  blocks?: IRBlock[]
  /** 중첩표/이미지 등 구조 콘텐츠 존재 — true일 때만 IRCell.blocks로 attach */
  hasStructure?: boolean
  isHeader?: boolean
}

interface TableState {
  rows: CellContext[][]
  currentRow: CellContext[]
  cell: CellCtxEx | null
  /** hp:caption 텍스트 — IRTable.caption으로 전달 (v3.0) */
  caption?: string
}

/** 섹션 간 공유 상태 — 자동번호 카운터, 머리말/꼬리말, 변경추적 */
interface SectionShared {
  /** numbering id → 레벨별(1..10) 카운터. 0 = 미사용(start값으로 초기화) */
  numState: Map<string, number[]>
  pageText: { headers: string[]; footers: string[] }
  track: { deleteDepth: number; warned: boolean }
}

function createSectionShared(): SectionShared {
  return { numState: new Map(), pageText: { headers: [], footers: [] }, track: { deleteDepth: 0, warned: false } }
}

/** walk 함수들이 공유하는 파싱 컨텍스트 — 개별 optional 파라미터를 하나로 묶어 시그니처 안정화 */
interface WalkCtx {
  styleMap?: HwpxStyleMap
  warnings?: ParseWarning[]
  sectionNum?: number
  shared: SectionShared
  /** secPr outlineShapeIDRef — 개요(OUTLINE) 문단이 사용하는 numbering id */
  outlineNumId?: string
}

/** xmldom DOMParser 생성 — onError 콜백으로 malformed XML 경고 수집 */
function createXmlParser(warnings?: ParseWarning[]): DOMParser {
  return new DOMParser({
    onError(level: "warn" | "error" | "fatalError", msg: string) {
      if (level === "fatalError") throw new KordocError(`XML 파싱 실패: ${msg}`)
      warnings?.push({ code: "MALFORMED_XML", message: `XML ${level === "warn" ? "경고" : "오류"}: ${msg}` })
    },
  })
}

// ─── HWPX 스타일 정보 ──────────────────────────────

interface HwpxCharProperty {
  fontSize?: number  // 단위: pt (hwpx는 centi-pt → /100)
  bold?: boolean
  italic?: boolean
  fontName?: string
}

/** hh:numbering > hh:paraHead 한 수준의 정의 */
interface ParaHeadDef {
  numFormat: string  // DIGIT, HANGUL_SYLLABLE, CIRCLED_DIGIT 등
  text: string       // "^1." 같은 치환 형식 문자열
  start: number
}

/** hh:numbering 정의 — 레벨(1..10) → paraHead */
interface NumberingDef {
  heads: Map<number, ParaHeadDef>
}

/** hh:paraPr > hh:heading — 문단의 자동번호/글머리표/개요 연결 정보 */
interface ParaHeadingRef {
  type: "NUMBER" | "BULLET" | "OUTLINE"
  idRef: string
  level: number  // 0-based (level="0" → paraHead level 1)
}

interface HwpxStyleMap {
  charProperties: Map<string, HwpxCharProperty>  // id → property
  styles: Map<string, { name: string; charPrId?: string; paraPrId?: string }>  // id → style
  numberings: Map<string, NumberingDef>  // numbering id → 정의
  bullets: Map<string, string>           // bullet id → 글머리 문자
  paraHeadings: Map<string, ParaHeadingRef>  // paraPr id → heading 참조
}

/** head.xml 또는 header.xml에서 스타일 정보 추출 */
async function extractHwpxStyles(zip: JSZip, decompressed?: { total: number }): Promise<HwpxStyleMap> {
  const result: HwpxStyleMap = {
    charProperties: new Map(),
    styles: new Map(),
    numberings: new Map(),
    bullets: new Map(),
    paraHeadings: new Map(),
  }

  const headerPaths = ["Contents/header.xml", "header.xml", "Contents/head.xml", "head.xml"]
  for (const hp of headerPaths) {
    const hpLower = hp.toLowerCase()
    const file = zip.file(hp) || Object.values(zip.files).find(f => f.name.toLowerCase() === hpLower) || null
    if (!file) continue

    try {
      const xml = await file.async("text")
      if (decompressed) {
        decompressed.total += xml.length * 2
        if (decompressed.total > MAX_DECOMPRESS_SIZE) throw new KordocError("ZIP 압축 해제 크기 초과 (ZIP bomb 의심)")
      }
      const parser = createXmlParser()
      const doc = parser.parseFromString(stripDtd(xml), "text/xml")
      if (!doc.documentElement) continue

      // charProperties 파싱
      parseCharProperties(doc, result.charProperties)
      // styles 파싱
      parseStyleElements(doc, result.styles)
      // 자동번호/글머리표/개요 정의 파싱 (v3.0)
      const domDoc = doc as unknown as Document
      parseNumberings(domDoc, result.numberings)
      parseBullets(domDoc, result.bullets)
      parseParaHeadings(domDoc, result.paraHeadings)
      break
    } catch { continue }
  }

  return result
}

function parseCharProperties(doc: Document, map: Map<string, HwpxCharProperty>): void {
  // <hh:charPr> 또는 <charPr> 요소 탐색
  const tagNames = ["hh:charPr", "charPr", "hp:charPr"]
  for (const tagName of tagNames) {
    const elements = doc.getElementsByTagName(tagName)
    for (let i = 0; i < elements.length; i++) {
      const el = elements[i]
      const id = el.getAttribute("id") || el.getAttribute("IDRef") || ""
      if (!id) continue

      const prop: HwpxCharProperty = {}

      // height 속성 (centi-pt 단위)
      const height = el.getAttribute("height")
      if (height) {
        const parsedHeight = parseInt(height, 10)
        if (!isNaN(parsedHeight) && parsedHeight > 0) {
          prop.fontSize = parsedHeight / 100
        }
      }

      // bold/italic
      const bold = el.getAttribute("bold")
      if (bold === "true" || bold === "1") prop.bold = true
      const italic = el.getAttribute("italic")
      if (italic === "true" || italic === "1") prop.italic = true

      // 하위 요소에서 fontface 탐색
      const fontFaces = el.getElementsByTagName("*")
      for (let j = 0; j < fontFaces.length; j++) {
        const ff = fontFaces[j]
        const localTag = (ff.tagName || "").replace(/^[^:]+:/, "")
        if (localTag === "fontface" || localTag === "fontRef") {
          const face = ff.getAttribute("face") || ff.getAttribute("FontFace")
          if (face) { prop.fontName = face; break }
        }
      }

      map.set(id, prop)
    }
  }
}

function parseStyleElements(doc: Document, map: Map<string, { name: string; charPrId?: string; paraPrId?: string }>): void {
  const tagNames = ["hh:style", "style", "hp:style"]
  for (const tagName of tagNames) {
    const elements = doc.getElementsByTagName(tagName)
    for (let i = 0; i < elements.length; i++) {
      const el = elements[i]
      const id = el.getAttribute("id") || el.getAttribute("IDRef") || String(i)
      const name = el.getAttribute("name") || el.getAttribute("engName") || ""
      const charPrId = el.getAttribute("charPrIDRef") || undefined
      const paraPrId = el.getAttribute("paraPrIDRef") || undefined
      map.set(id, { name, charPrId, paraPrId })
    }
  }
}

/** header.xml의 hh:numbering(paraHead 7수준) 파싱 */
function parseNumberings(doc: Document, map: Map<string, NumberingDef>): void {
  const tagNames = ["hh:numbering", "numbering"]
  for (const tagName of tagNames) {
    const elements = doc.getElementsByTagName(tagName)
    for (let i = 0; i < elements.length; i++) {
      const el = elements[i]
      const id = el.getAttribute("id") || ""
      if (!id) continue
      const def: NumberingDef = { heads: new Map() }
      const children = el.childNodes
      for (let j = 0; j < children.length; j++) {
        const ch = children[j] as Element
        if (ch.nodeType !== 1) continue
        const tag = (ch.tagName || ch.localName || "").replace(/^[^:]+:/, "")
        if (tag !== "paraHead") continue
        const level = parseInt(ch.getAttribute("level") || "", 10)
        if (isNaN(level) || level < 1 || level > 10) continue
        const start = parseInt(ch.getAttribute("start") || "1", 10)
        def.heads.set(level, {
          numFormat: ch.getAttribute("numFormat") || "DIGIT",
          text: ch.textContent || "",
          start: isNaN(start) ? 1 : start,
        })
      }
      if (def.heads.size > 0) map.set(id, def)
    }
    if (map.size > 0) break
  }
}

/** header.xml의 hh:bullet 파싱 — id → 글머리 문자 (PUA는 builder의 mapPuaText가 치환) */
function parseBullets(doc: Document, map: Map<string, string>): void {
  const tagNames = ["hh:bullet", "bullet"]
  for (const tagName of tagNames) {
    const elements = doc.getElementsByTagName(tagName)
    for (let i = 0; i < elements.length; i++) {
      const el = elements[i]
      const id = el.getAttribute("id") || ""
      const char = el.getAttribute("char") || ""
      if (id && char) map.set(id, char)
    }
    if (map.size > 0) break
  }
}

/** header.xml의 hh:paraPr > hh:heading 파싱 — 문단 속성 id → NUMBER/BULLET/OUTLINE 참조 */
function parseParaHeadings(doc: Document, map: Map<string, ParaHeadingRef>): void {
  const tagNames = ["hh:paraPr", "paraPr"]
  for (const tagName of tagNames) {
    const elements = doc.getElementsByTagName(tagName)
    for (let i = 0; i < elements.length; i++) {
      const el = elements[i]
      const id = el.getAttribute("id") || ""
      if (!id) continue
      const heading = findChildByLocalName(el, "heading")
      if (!heading) continue
      const type = heading.getAttribute("type") || "NONE"
      if (type !== "NUMBER" && type !== "BULLET" && type !== "OUTLINE") continue
      const level = parseInt(heading.getAttribute("level") || "0", 10)
      map.set(id, {
        type,
        idRef: heading.getAttribute("idRef") || "0",
        level: isNaN(level) ? 0 : Math.max(0, Math.min(level, 9)),
      })
    }
    if (map.size > 0) break
  }
}

// ─── 자동번호 포맷 ───────────────────────────────────

const HANGUL_SYLLABLE_SEQ = "가나다라마바사아자차카타파하"
const HANGUL_JAMO_SEQ = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"

/** 1-based 숫자 → 로마 숫자 (대문자) */
function toRoman(n: number): string {
  if (n <= 0 || n >= 4000) return String(n)
  const table: [number, string][] = [
    [1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"], [90, "XC"],
    [50, "L"], [40, "XL"], [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"],
  ]
  let out = ""
  for (const [v, s] of table) { while (n >= v) { out += s; n -= v } }
  return out
}

/** 자동번호 카운터 값 → numFormat에 따른 표시 문자열 */
function formatHeadNumber(n: number, numFormat: string): string {
  if (n <= 0) n = 1
  switch (numFormat) {
    case "DIGIT": return String(n)
    case "CIRCLED_DIGIT": return n <= 20 ? String.fromCodePoint(0x2460 + n - 1) : `(${n})`
    case "HANGUL_SYLLABLE": return HANGUL_SYLLABLE_SEQ[(n - 1) % HANGUL_SYLLABLE_SEQ.length]
    case "CIRCLED_HANGUL_SYLLABLE": return n <= 14 ? String.fromCodePoint(0x326e + n - 1) : HANGUL_SYLLABLE_SEQ[(n - 1) % 14]
    case "HANGUL_JAMO": return HANGUL_JAMO_SEQ[(n - 1) % HANGUL_JAMO_SEQ.length]
    case "CIRCLED_HANGUL_JAMO": return n <= 14 ? String.fromCodePoint(0x3260 + n - 1) : HANGUL_JAMO_SEQ[(n - 1) % 14]
    case "LATIN_CAPITAL": return String.fromCharCode(0x41 + ((n - 1) % 26))
    case "LATIN_SMALL": return String.fromCharCode(0x61 + ((n - 1) % 26))
    case "CIRCLED_LATIN_CAPITAL": return n <= 26 ? String.fromCodePoint(0x24b6 + n - 1) : String.fromCharCode(0x41 + ((n - 1) % 26))
    case "CIRCLED_LATIN_SMALL": return n <= 26 ? String.fromCodePoint(0x24d0 + n - 1) : String.fromCharCode(0x61 + ((n - 1) % 26))
    case "ROMAN_CAPITAL": return toRoman(n)
    case "ROMAN_SMALL": return toRoman(n).toLowerCase()
    default: return String(n)
  }
}

/** 문단의 자동번호/글머리표/개요 해석 결과 */
interface ResolvedParaHeading {
  /** 문단 텍스트 앞에 붙일 접두 ("1.", "가.", "①", "-" 등) */
  prefix?: string
  /** OUTLINE 문단의 헤딩 레벨 (1-6) */
  headingLevel?: number
}

/**
 * hp:p paraPrIDRef → paraPr heading(NUMBER/BULLET/OUTLINE) 해석.
 * NUMBER/OUTLINE은 7수준 카운터 상태기계 사용 — 같은 numbering id에서
 * 레벨별 카운터 증가, 상위 레벨 증가 시 하위 리셋. 호출 시 카운터가
 * 증가하므로 텍스트가 있는 문단에서만 호출할 것.
 */
function resolveParaHeading(paraEl: Element, ctx: WalkCtx): ResolvedParaHeading | null {
  const sm = ctx.styleMap
  if (!sm) return null
  const prId = paraEl.getAttribute("paraPrIDRef")
  if (!prId) return null
  const ref = sm.paraHeadings.get(prId)
  if (!ref) return null

  if (ref.type === "BULLET") {
    const char = sm.bullets.get(ref.idRef)
    return char ? { prefix: char } : null
  }

  // NUMBER는 idRef가 numbering id, OUTLINE은 secPr outlineShapeIDRef가 numbering id
  const numId = ref.type === "OUTLINE" ? (ctx.outlineNumId || "1") : ref.idRef
  const level = Math.min(ref.level + 1, 10)  // 0-based 속성 → 1-based paraHead 레벨
  const headingLevel = ref.type === "OUTLINE" ? Math.min(ref.level + 1, 6) : undefined
  const numDef = sm.numberings.get(numId)
  if (!numDef) return headingLevel ? { headingLevel } : null

  let counters = ctx.shared.numState.get(numId)
  if (!counters) { counters = new Array(11).fill(0); ctx.shared.numState.set(numId, counters) }
  const head = numDef.heads.get(level)
  counters[level] = counters[level] === 0 ? (head?.start ?? 1) : counters[level] + 1
  for (let l = level + 1; l <= 10; l++) counters[l] = 0

  // ^N 치환 — 참조 레벨의 카운터를 그 레벨의 numFormat으로 변환 (예: "^1." → "1.")
  const fmtText = head?.text?.trim() || `^${level}.`
  const prefix = fmtText.replace(/\^(10|[1-9])/g, (_, d) => {
    const lv = parseInt(d, 10)
    const refHead = numDef.heads.get(lv)
    const n = counters![lv] || refHead?.start || 1
    return formatHeadNumber(n, refHead?.numFormat || "DIGIT")
  })
  return { prefix, headingLevel }
}

// stripDtd는 utils.js에서 import

export async function parseHwpxDocument(buffer: ArrayBuffer, options?: ParseOptions): Promise<InternalParseResult> {
  // Best-effort 사전 검증 — CD 선언 크기 기반 (위조 가능, 실제 방어는 per-file 누적 체크)
  precheckZipSize(buffer, MAX_DECOMPRESS_SIZE, MAX_ZIP_ENTRIES)

  let zip: JSZip

  try {
    zip = await JSZip.loadAsync(buffer)
  } catch {
    return extractFromBrokenZip(buffer)
  }

  // loadAsync 후 실제 엔트리 수 검증 — CD 위조와 무관한 진짜 방어선
  const actualEntryCount = Object.keys(zip.files).length
  if (actualEntryCount > MAX_ZIP_ENTRIES) {
    throw new KordocError("ZIP 엔트리 수 초과 (ZIP bomb 의심)")
  }

  // ── DRM 감지: manifest.xml에 encryption-data가 있으면 COM fallback ──
  const manifestFile = zip.file("META-INF/manifest.xml")
  if (manifestFile) {
    const manifestXml = await manifestFile.async("text")
    if (isEncryptedHwpx(manifestXml)) {
      // 파일 경로가 options에 있으면 COM fallback 시도
      if (isComFallbackAvailable() && options?.filePath) {
        const { pages, pageCount, warnings } = extractTextViaCom(options.filePath)
        if (pages.some(p => p && p.trim().length > 0)) {
          return comResultToParseResult(pages, pageCount, warnings)
        }
      }
      throw new KordocError("DRM 암호화된 HWPX 파일입니다. Windows + 한컴 오피스 설치 시 자동 추출됩니다.")
    }
  }

  // ZIP 전체 파일 누적 압축해제 크기 추적 (비섹션 파일 포함)
  const decompressed = { total: 0 }

  // 메타데이터 추출 (best-effort)
  const metadata: DocumentMetadata = {}
  await extractHwpxMetadata(zip, metadata, decompressed)

  // 스타일 정보 추출 (best-effort)
  const styleMap = await extractHwpxStyles(zip, decompressed)
  const warnings: ParseWarning[] = []

  const sectionPaths = await resolveSectionPaths(zip)
  if (sectionPaths.length === 0) throw new KordocError("HWPX에서 섹션 파일을 찾을 수 없습니다")

  metadata.pageCount = sectionPaths.length

  // 페이지 범위 필터링 (섹션 단위 근사치)
  const pageFilter = options?.pages ? parsePageRange(options.pages, sectionPaths.length) : null
  const totalTarget = pageFilter ? pageFilter.size : sectionPaths.length
  const blocks: IRBlock[] = []
  const shared = createSectionShared()
  let parsedSections = 0
  for (let si = 0; si < sectionPaths.length; si++) {
    if (pageFilter && !pageFilter.has(si + 1)) continue
    const file = zip.file(sectionPaths[si])
    if (!file) continue
    try {
      const xml = await file.async("text")
      decompressed.total += xml.length * 2
      if (decompressed.total > MAX_DECOMPRESS_SIZE) throw new KordocError("ZIP 압축 해제 크기 초과 (ZIP bomb 의심)")
      blocks.push(...parseSectionXml(xml, styleMap, warnings, si + 1, shared))
      parsedSections++
      options?.onProgress?.(parsedSections, totalTarget)
    } catch (secErr) {
      if (secErr instanceof KordocError) throw secErr
      warnings.push({ page: si + 1, message: `섹션 ${si + 1} 파싱 실패: ${secErr instanceof Error ? secErr.message : "알 수 없는 오류"}`, code: "PARTIAL_PARSE" })
    }
  }

  // 머리말/꼬리말 — 문서당 1회, 본문 앞/뒤에 자연스럽게 배치
  applyPageText(blocks, shared)

  // 이미지 블록에서 ZIP 바이너리 추출
  const images = await extractImagesFromZip(zip, blocks, decompressed, warnings)

  // 스타일 기반 헤딩 감지
  detectHwpxHeadings(blocks, styleMap)

  // outline 구축
  const outline: OutlineItem[] = blocks
    .filter(b => b.type === "heading" && b.level && b.text)
    .map(b => ({ level: b.level!, text: b.text!, pageNumber: b.pageNumber }))

  const markdown = blocksToMarkdown(blocks)
  return { markdown, blocks, metadata, outline: outline.length > 0 ? outline : undefined, warnings: warnings.length > 0 ? warnings : undefined, images: images.length > 0 ? images : undefined }
}

/** 수집된 머리말/꼬리말을 본문 앞/뒤 문단으로 배치 */
function applyPageText(blocks: IRBlock[], shared: SectionShared): void {
  const { headers, footers } = shared.pageText
  if (headers.length > 0) {
    blocks.unshift(...headers.map(t => ({ type: "paragraph" as const, text: t, pageNumber: 1 })))
  }
  if (footers.length > 0) {
    blocks.push(...footers.map(t => ({ type: "paragraph" as const, text: t })))
  }
}

// ─── 이미지 추출 ───────────────────────────────────

/** 확장자 → MIME 타입 */
function imageExtToMime(ext: string): string {
  switch (ext.toLowerCase()) {
    case "jpg": case "jpeg": return "image/jpeg"
    case "png": return "image/png"
    case "gif": return "image/gif"
    case "bmp": return "image/bmp"
    case "tif": case "tiff": return "image/tiff"
    case "wmf": return "image/wmf"
    case "emf": return "image/emf"
    case "svg": return "image/svg+xml"
    default: return "application/octet-stream"
  }
}

/** MIME → 확장자 */
function mimeToExt(mime: string): string {
  if (mime.includes("jpeg")) return "jpg"
  if (mime.includes("png")) return "png"
  if (mime.includes("gif")) return "gif"
  if (mime.includes("bmp")) return "bmp"
  if (mime.includes("tiff")) return "tif"
  if (mime.includes("wmf")) return "wmf"
  if (mime.includes("emf")) return "emf"
  if (mime.includes("svg")) return "svg"
  return "bin"
}

/** 이미지 블록 재귀 수집 — 표 셀 내부(IRCell.blocks)에 중첩된 이미지 포함 (v3.0) */
function collectImageBlocks(blocks: IRBlock[], out: { block: IRBlock; ownerCell?: IRCell }[], ownerCell?: IRCell, depth = 0): void {
  if (depth > MAX_XML_DEPTH) return
  for (const block of blocks) {
    if (block.type === "image") {
      out.push({ block, ownerCell })
    } else if (block.type === "table" && block.table) {
      for (const row of block.table.cells) {
        for (const cell of row) {
          if (cell.blocks?.length) collectImageBlocks(cell.blocks, out, cell, depth + 1)
        }
      }
    }
  }
}

/** blocks에서 type="image" 블록의 참조를 ZIP에서 실제 바이너리로 변환 */
async function extractImagesFromZip(
  zip: JSZip,
  blocks: IRBlock[],
  decompressed: { total: number },
  warnings?: ParseWarning[],
): Promise<ExtractedImage[]> {
  const images: ExtractedImage[] = []
  let imageIndex = 0

  const imageBlocks: { block: IRBlock; ownerCell?: IRCell }[] = []
  collectImageBlocks(blocks, imageBlocks)

  for (const { block, ownerCell } of imageBlocks) {
    if (block.type !== "image" || !block.text) continue

    const ref = block.text
    // BinData/ 폴더 내에서 참조 파일 찾기
    // HWPX binaryItemIDRef는 확장자 없이 오는 경우가 많음 (예: "image1" → "BinData/image1.bmp")
    const candidates = [
      `BinData/${ref}`,
      `Contents/BinData/${ref}`,
      ref, // 절대 경로일 수도 있음
    ]

    // 확장자 없는 ref인 경우 ZIP에서 매칭 파일 탐색
    let resolvedPath: string | null = null
    if (!ref.includes(".")) {
      const prefixes = [`BinData/${ref}`, `Contents/BinData/${ref}`]
      for (const prefix of prefixes) {
        const match = zip.file(new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\.[a-zA-Z0-9]+$`))
        if (match.length > 0) { resolvedPath = match[0].name; break }
      }
    }

    let found = false
    const allCandidates = resolvedPath ? [resolvedPath, ...candidates] : candidates
    for (const path of allCandidates) {
      if (isPathTraversal(path)) continue
      const file = zip.file(path)
      if (!file) continue

      try {
        const data = await file.async("uint8array")
        decompressed.total += data.length
        if (decompressed.total > MAX_DECOMPRESS_SIZE) throw new KordocError("ZIP 압축 해제 크기 초과 (ZIP bomb 의심)")

        const actualPath = path
        const ext = actualPath.includes(".") ? (actualPath.split(".").pop() || "png") : "png"
        const mimeType = imageExtToMime(ext)
        imageIndex++
        const filename = `image_${String(imageIndex).padStart(3, "0")}.${mimeToExt(mimeType)}`

        images.push({ filename, data, mimeType })
        // 블록 텍스트를 참조 파일명으로 교체
        block.text = filename
        block.imageData = { data, mimeType, filename: ref }
        // 셀 내부 이미지 — 셀 평탄화 텍스트의 참조도 파일명으로 갱신
        if (ownerCell) ownerCell.text = ownerCell.text.replace(`![image](${ref})`, `![image](${filename})`)
        found = true
        break
      } catch (err) {
        if (err instanceof KordocError) throw err
        // 개별 이미지 실패는 경고로 처리
      }
    }

    if (!found) {
      warnings?.push({ page: block.pageNumber, message: `이미지 파일 없음: ${ref}`, code: "SKIPPED_IMAGE" })
      // image 블록을 paragraph로 전환 (참조만 남김 — 사용자 그림설명이 있으면 함께)
      block.type = "paragraph"
      block.text = `[이미지: ${ref}]`
      if (ownerCell) ownerCell.text = ownerCell.text.replace(`![image](${ref})`, `[이미지: ${ref}]`)
    }
  }

  return images
}

// ─── 메타데이터 추출 (best-effort) ───────────────────

/**
 * HWPX ZIP 내 메타데이터 파일에서 Dublin Core 정보 추출.
 * 표준 경로: meta.xml, docProps/core.xml, META-INF/container.xml
 */
async function extractHwpxMetadata(zip: JSZip, metadata: DocumentMetadata, decompressed?: { total: number }): Promise<void> {
  try {
    // meta.xml (HWPX 표준) 또는 docProps/core.xml (OOXML 호환)
    const metaPaths = ["meta.xml", "META-INF/meta.xml", "docProps/core.xml"]
    for (const mp of metaPaths) {
      const file = zip.file(mp) || Object.values(zip.files).find(f => f.name.toLowerCase() === mp.toLowerCase()) || null
      if (!file) continue
      const xml = await file.async("text")
      if (decompressed) {
        decompressed.total += xml.length * 2
        if (decompressed.total > MAX_DECOMPRESS_SIZE) throw new KordocError("ZIP 압축 해제 크기 초과 (ZIP bomb 의심)")
      }
      parseDublinCoreMetadata(xml, metadata)
      if (metadata.title || metadata.author) return
    }
  } catch {
    // best-effort
  }
}

/** Dublin Core (dc:) 메타데이터 XML 파싱 */
function parseDublinCoreMetadata(xml: string, metadata: DocumentMetadata): void {
  const parser = createXmlParser()
  const doc = parser.parseFromString(stripDtd(xml), "text/xml")
  if (!doc.documentElement) return

  const getText = (tagNames: string[]): string | undefined => {
    for (const tag of tagNames) {
      const els = doc.getElementsByTagName(tag)
      if (els.length > 0) {
        const text = els[0].textContent?.trim()
        if (text) return text
      }
    }
    return undefined
  }

  metadata.title = metadata.title || getText(["dc:title", "title"])
  metadata.author = metadata.author || getText(["dc:creator", "creator", "cp:lastModifiedBy"])
  metadata.description = metadata.description || getText(["dc:description", "description", "dc:subject", "subject"])
  metadata.createdAt = metadata.createdAt || getText(["dcterms:created", "meta:creation-date"])
  metadata.modifiedAt = metadata.modifiedAt || getText(["dcterms:modified", "meta:date"])

  const keywords = getText(["dc:keyword", "cp:keywords", "meta:keyword"])
  if (keywords && !metadata.keywords) {
    metadata.keywords = keywords.split(/[,;]/).map(k => k.trim()).filter(Boolean)
  }
}

/** 메타데이터만 추출 (전체 파싱 없이) — MCP parse_metadata용 */
export async function extractHwpxMetadataOnly(buffer: ArrayBuffer): Promise<DocumentMetadata> {
  let zip: JSZip
  try {
    zip = await JSZip.loadAsync(buffer)
  } catch {
    throw new KordocError("HWPX ZIP을 열 수 없습니다")
  }

  const metadata: DocumentMetadata = {}
  await extractHwpxMetadata(zip, metadata)

  const sectionPaths = await resolveSectionPaths(zip)
  metadata.pageCount = sectionPaths.length

  return metadata
}

// ─── 손상 ZIP 복구 (edu-facility-ai에서 포팅) ──────────

function extractFromBrokenZip(buffer: ArrayBuffer): InternalParseResult {
  const data = new Uint8Array(buffer)
  const view = new DataView(buffer)
  let pos = 0
  const blocks: IRBlock[] = []
  const warnings: ParseWarning[] = [
    { code: "BROKEN_ZIP_RECOVERY", message: "손상된 ZIP 구조 — Local File Header 기반 복구 모드" },
  ]
  let totalDecompressed = 0
  let entryCount = 0
  let sectionNum = 0
  const shared = createSectionShared()

  while (pos < data.length - 30) {
    // PK\x03\x04 시그니처 확인 — 미매칭 시 다음 PK 시그니처까지 스캔 (중간 손상 복구)
    if (data[pos] !== 0x50 || data[pos + 1] !== 0x4b || data[pos + 2] !== 0x03 || data[pos + 3] !== 0x04) {
      pos++
      while (pos < data.length - 30) {
        if (data[pos] === 0x50 && data[pos + 1] === 0x4b && data[pos + 2] === 0x03 && data[pos + 3] === 0x04) break
        pos++
      }
      continue
    }

    if (++entryCount > MAX_ZIP_ENTRIES) break

    const method = view.getUint16(pos + 8, true)
    const compSize = view.getUint32(pos + 18, true)
    const nameLen = view.getUint16(pos + 26, true)
    const extraLen = view.getUint16(pos + 28, true)

    // nameLen 상한 — 비정상 값에 의한 대규모 버퍼 할당 방지
    if (nameLen > 1024 || extraLen > 65535) { pos += 30 + nameLen + extraLen; continue }

    const fileStart = pos + 30 + nameLen + extraLen
    // 범위 초과 검증 — OOB 및 무한 루프 방지
    if (fileStart + compSize > data.length) break
    if (compSize === 0 && method !== 0) { pos = fileStart; continue }

    const nameBytes = data.slice(pos + 30, pos + 30 + nameLen)
    const name = new TextDecoder().decode(nameBytes)

    // 경로 순회 방지 — 상위 디렉토리 참조 및 절대 경로 차단
    if (isPathTraversal(name)) { pos = fileStart + compSize; continue }
    const fileData = data.slice(fileStart, fileStart + compSize)
    pos = fileStart + compSize

    if (!name.toLowerCase().includes("section") || !name.endsWith(".xml")) continue

    try {
      let content: string
      if (method === 0) {
        content = new TextDecoder().decode(fileData)
      } else if (method === 8) {
        const decompressed = inflateRawSync(Buffer.from(fileData), { maxOutputLength: MAX_DECOMPRESS_SIZE })
        content = new TextDecoder().decode(decompressed)
      } else {
        continue
      }
      totalDecompressed += content.length * 2
      if (totalDecompressed > MAX_DECOMPRESS_SIZE) throw new KordocError("압축 해제 크기 초과")
      sectionNum++
      blocks.push(...parseSectionXml(content, undefined, warnings, sectionNum, shared))
    } catch {
      continue
    }
  }

  if (blocks.length === 0) throw new KordocError("손상된 HWPX에서 섹션 데이터를 복구할 수 없습니다")
  applyPageText(blocks, shared)
  const markdown = blocksToMarkdown(blocks)
  return { markdown, blocks, warnings: warnings.length > 0 ? warnings : undefined }
}

// ─── Manifest 해석 ───────────────────────────────────

async function resolveSectionPaths(zip: JSZip): Promise<string[]> {
  const manifestPaths = ["Contents/content.hpf", "content.hpf"]
  for (const mp of manifestPaths) {
    const mpLower = mp.toLowerCase()
    const file = zip.file(mp) || Object.values(zip.files).find(f => f.name.toLowerCase() === mpLower) || null
    if (!file) continue
    const xml = await file.async("text")
    const paths = parseSectionPathsFromManifest(xml)
    if (paths.length > 0) return paths
  }

  // fallback: section*.xml 직접 검색
  const sectionFiles = zip.file(/[Ss]ection\d+\.xml$/)
  return sectionFiles.map(f => f.name).sort()
}

function parseSectionPathsFromManifest(xml: string): string[] {
  const parser = createXmlParser()
  const doc = parser.parseFromString(stripDtd(xml), "text/xml")
  const items = doc.getElementsByTagName("opf:item")
  const spine = doc.getElementsByTagName("opf:itemref")

  const isSectionId = (id: string) => /^s/i.test(id) || id.toLowerCase().includes("section")
  const idToHref = new Map<string, string>()
  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    const id = item.getAttribute("id") || ""
    let href = item.getAttribute("href") || ""
    const mediaType = item.getAttribute("media-type") || ""
    if (!isSectionId(id) && !mediaType.includes("xml")) continue
    if (!href.startsWith("/") && !href.startsWith("Contents/") && isSectionId(id))
      href = "Contents/" + href
    idToHref.set(id, href)
  }

  if (spine.length > 0) {
    const ordered: string[] = []
    for (let i = 0; i < spine.length; i++) {
      const href = idToHref.get(spine[i].getAttribute("idref") || "")
      if (href) ordered.push(href)
    }
    if (ordered.length > 0) return ordered
  }
  return Array.from(idToHref.entries())
    .filter(([id]) => isSectionId(id))
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([, href]) => href)
}

// ─── 헤딩 감지 (스타일 기반) ────────────────────────

/** HWPX 스타일 기반 헤딩 감지 */
function detectHwpxHeadings(blocks: IRBlock[], styleMap: HwpxStyleMap): void {
  // outline(개요) 기반 헤딩이 이미 감지된 문서는 폰트크기 휴리스틱 생략 — outline이 권위 정보
  if (blocks.some(b => b.type === "heading")) return

  // 본문 폰트 크기 결정
  let baseFontSize = 0
  const sizeFreq = new Map<number, number>()
  for (const b of blocks) {
    if (b.style?.fontSize) {
      sizeFreq.set(b.style.fontSize, (sizeFreq.get(b.style.fontSize) || 0) + 1)
    }
  }
  let maxCount = 0
  for (const [size, count] of sizeFreq) {
    if (count > maxCount) { maxCount = count; baseFontSize = size }
  }

  for (const block of blocks) {
    if (block.type !== "paragraph" || !block.text) continue
    const text = block.text.trim()
    if (text.length === 0 || text.length > 200 || /^\d+$/.test(text)) continue

    let level = 0

    // 폰트 크기 기반
    if (baseFontSize > 0 && block.style?.fontSize) {
      const ratio = block.style.fontSize / baseFontSize
      if (ratio >= HEADING_RATIO_H1) level = 1
      else if (ratio >= HEADING_RATIO_H2) level = 2
      else if (ratio >= HEADING_RATIO_H3) level = 3
    }

    // "제N조/장/절" 패턴 — 균등배분 공백 허용 ("제 1 장" → "제1장")
    const compactText = text.replace(/\s+/g, "")
    if (/^제\d+[조장절편]/.test(compactText) && text.length <= 50) {
      if (level === 0) level = 3
    }

    if (level > 0) {
      block.type = "heading"
      block.level = level
    }
  }
}

// ─── 섹션 XML 파싱 ──────────────────────────────────

/**
 * TableState → IRTable 변환 — 캡션·셀 blocks(중첩표/이미지)·제목셀을 함께 attach (v3.0).
 * buildTable이 CellContext의 확장 필드를 복사하지 않으므로 cellAddr 좌표
 * (없으면 텍스트+스팬 매칭)로 결과 IRCell을 찾아 재부착한다.
 */
function buildTableWithCellMeta(state: TableState): IRTable {
  const table = buildTable(state.rows)
  if (state.caption) table.caption = state.caption

  const claimed = new Set<IRCell>()
  for (const row of state.rows) {
    for (const src of row as CellCtxEx[]) {
      const needsBlocks = src.hasStructure && src.blocks && src.blocks.length > 0
      if (!needsBlocks && !src.isHeader) continue

      // 1순위: cellAddr 절대좌표 (HWPX 표준은 항상 cellAddr 제공)
      let target: IRCell | undefined
      const trimmed = src.text.trim()
      if (src.rowAddr !== undefined && src.colAddr !== undefined) {
        const cand = table.cells[src.rowAddr]?.[src.colAddr]
        if (cand && cand.text === trimmed && !claimed.has(cand)) target = cand
      }
      // 2순위: 텍스트+스팬 매칭 (cellAddr 없는 비표준 파일)
      if (!target) {
        outer: for (const irRow of table.cells) {
          for (const cand of irRow) {
            if (!claimed.has(cand) && cand.text === trimmed && cand.colSpan === src.colSpan && cand.rowSpan === src.rowSpan) {
              target = cand
              break outer
            }
          }
        }
      }
      if (!target) continue
      claimed.add(target)
      if (needsBlocks) target.blocks = src.blocks
      if (src.isHeader) target.isHeader = true
    }
  }
  return table
}

/**
 * </tbl> 완료 처리 공통 로직 — walkSection/walkParagraphChildren 중복 제거.
 * 중첩표는 부모 IRCell.blocks에 IRBlock(type:'table')로 보존하고(v3.0 — 호이스팅/평탄화 제거),
 * 셀 텍스트에는 하위 호환용 평탄화 텍스트를 남긴다. 최상위 표는 블록으로 추가.
 */
function completeTable(
  newTable: TableState,
  tableStack: TableState[],
  blocks: IRBlock[],
  ctx: WalkCtx
): TableState | null {
  const parentTable = tableStack.length > 0 ? tableStack.pop()! : null
  if (newTable.rows.length === 0) {
    if (newTable.caption) blocks.push({ type: "paragraph", text: newTable.caption, pageNumber: ctx.sectionNum })
    return parentTable
  }
  const ir = buildTableWithCellMeta(newTable)
  const block: IRBlock = { type: "table", table: ir, pageNumber: ctx.sectionNum }
  if (parentTable?.cell) {
    const cell = parentTable.cell
    ;(cell.blocks ??= []).push(block)
    cell.hasStructure = true
    // 하위 호환: IRCell.text는 blocks의 평탄화 텍스트를 포함한다
    let flat = convertTableToText(newTable.rows)
    if (newTable.caption) flat = newTable.caption + (flat ? "\n" + flat : "")
    if (flat) cell.text += (cell.text ? "\n" : "") + flat
  } else {
    // 부모 표의 셀 밖(비정상 경로) 또는 최상위 — 블록으로 추가
    blocks.push(block)
  }
  return parentTable
}

function parseSectionXml(xml: string, styleMap?: HwpxStyleMap, warnings?: ParseWarning[], sectionNum?: number, shared?: SectionShared): IRBlock[] {
  const parser = createXmlParser(warnings)
  const doc = parser.parseFromString(stripDtd(xml), "text/xml")
  if (!doc.documentElement) return []

  const ctx: WalkCtx = { styleMap, warnings, sectionNum, shared: shared ?? createSectionShared() }
  // 변경추적 삭제 구간은 섹션 경계를 넘지 않음 — 비정상 파일에서 본문 전체 소실 방지
  ctx.shared.track.deleteDepth = 0

  // secPr outlineShapeIDRef — 개요 문단의 자동번호 정의 참조
  for (const tagName of ["hp:secPr", "secPr"]) {
    const els = doc.getElementsByTagName(tagName)
    if (els.length > 0) {
      const v = els[0].getAttribute("outlineShapeIDRef")
      if (v) ctx.outlineNumId = v
      break
    }
  }

  const blocks: IRBlock[] = []
  walkSection(doc.documentElement, blocks, null, [], ctx)
  return blocks
}

/** pic/shape 요소에서 이미지 참조 경로 추출 (binaryItemIDRef 또는 href) */
function extractImageRef(el: Element): string | null {
  // HWPX: <hp:imgRect> 또는 <hp:img> 내 binaryItemIDRef 속성
  // 또는 하위에서 img 관련 속성 탐색
  const children = el.childNodes
  if (!children) return null
  for (let i = 0; i < children.length; i++) {
    const child = children[i] as Element
    if (child.nodeType !== 1) continue
    const tag = (child.tagName || child.localName || "").replace(/^[^:]+:/, "")
    if (tag === "imgRect" || tag === "img" || tag === "imgClip") {
      const ref = child.getAttribute("binaryItemIDRef") || child.getAttribute("href") || ""
      if (ref) return ref
    }
    // lineShape > imgRect 같은 중첩 구조
    const nested = extractImageRef(child)
    if (nested) return nested
  }
  // 직접 속성 체크
  const directRef = el.getAttribute("binaryItemIDRef") || ""
  if (directRef) return directRef
  return null
}

function walkSection(
  node: Node, blocks: IRBlock[],
  tableCtx: TableState | null, tableStack: TableState[],
  ctx: WalkCtx, depth: number = 0
): void {
  if (depth > MAX_XML_DEPTH) return
  const children = node.childNodes
  if (!children) return

  for (let i = 0; i < children.length; i++) {
    const el = children[i] as Element
    if (el.nodeType !== 1) continue

    const tag = el.tagName || el.localName || ""
    const localTag = tag.replace(/^[^:]+:/, "")

    switch (localTag) {
      case "tbl": {
        if (tableCtx) tableStack.push(tableCtx)
        const newTable: TableState = { rows: [], currentRow: [], cell: null }
        walkSection(el, blocks, newTable, tableStack, ctx, depth + 1)
        tableCtx = completeTable(newTable, tableStack, blocks, ctx)
        break
      }

      // 표/도표 캡션 — IRTable.caption으로 보존 (v3.0, 기존 무음 드롭 수정)
      case "caption":
        if (tableCtx) {
          const capText = collectSubListText(el, ctx)
          if (capText) tableCtx.caption = (tableCtx.caption ? tableCtx.caption + "\n" : "") + capText
        }
        break

      case "tr":
        if (tableCtx) {
          tableCtx.currentRow = []
          walkSection(el, blocks, tableCtx, tableStack, ctx, depth + 1)
          if (tableCtx.currentRow.length > 0) tableCtx.rows.push(tableCtx.currentRow)
          tableCtx.currentRow = []
        }
        break

      case "tc":
        if (tableCtx) {
          tableCtx.cell = { text: "", colSpan: 1, rowSpan: 1 }
          if (el.getAttribute("header") === "1" || el.getAttribute("header") === "true") tableCtx.cell.isHeader = true
          walkSection(el, blocks, tableCtx, tableStack, ctx, depth + 1)
          if (tableCtx.cell) {
            tableCtx.currentRow.push(tableCtx.cell)
            tableCtx.cell = null
          }
        }
        break

      case "cellAddr":
        if (tableCtx?.cell) {
          const ca = parseInt(el.getAttribute("colAddr") || "", 10)
          const ra = parseInt(el.getAttribute("rowAddr") || "", 10)
          if (!isNaN(ca)) tableCtx.cell.colAddr = ca
          if (!isNaN(ra)) tableCtx.cell.rowAddr = ra
        }
        break

      case "cellSpan":
        if (tableCtx?.cell) {
          const rawCs = parseInt(el.getAttribute("colSpan") || "1", 10)
          const cs = isNaN(rawCs) ? 1 : rawCs
          const rawRs = parseInt(el.getAttribute("rowSpan") || "1", 10)
          const rs = isNaN(rawRs) ? 1 : rawRs
          tableCtx.cell.colSpan = clampSpan(cs, MAX_COLS)
          tableCtx.cell.rowSpan = clampSpan(rs, MAX_ROWS)
        }
        break

      case "p": {
        const { text: rawText, href, footnote, style } = extractParagraphInfo(el, ctx.styleMap, ctx)
        let text = rawText
        let headingLevel: number | undefined
        if (text) {
          // 자동번호/글머리표/개요 접두 재현 (v3.0)
          const ph = resolveParaHeading(el, ctx)
          if (ph?.prefix) text = ph.prefix + " " + text
          headingLevel = ph?.headingLevel
        }
        if (text) {
          if (tableCtx?.cell) {
            const cell = tableCtx.cell
            if (footnote) text += ` (주: ${footnote})`
            cell.text += (cell.text ? "\n" : "") + text
            ;(cell.blocks ??= []).push({ type: "paragraph", text, pageNumber: ctx.sectionNum })
          } else if (!tableCtx) {
            const block: IRBlock = { type: headingLevel ? "heading" : "paragraph", text, pageNumber: ctx.sectionNum }
            if (headingLevel) block.level = headingLevel
            if (style) block.style = style
            if (href) block.href = href
            if (footnote) block.footnoteText = footnote
            blocks.push(block)
          } else {
            // 표 내부지만 셀 밖(비정상 경로) — 무음 드롭 대신 본문 문단으로 보존
            blocks.push({ type: "paragraph", text, pageNumber: ctx.sectionNum })
          }
        }
        // <p> 내부의 <tbl>만 별도 처리 — extractParagraphInfo가 이미 텍스트를 추출했으므로
        // 전체 walkSection 재귀 대신 테이블/이미지 자식만 선택적으로 처리
        tableCtx = walkParagraphChildren(el, blocks, tableCtx, tableStack, ctx, depth + 1)
        break
      }

      // 이미지/그림/글상자 — 이미지·텍스트·캡션 병행 추출
      case "pic": case "shape": case "drawingObject": {
        if (tableCtx?.cell) {
          const sink: IRBlock[] = []
          handleShape(el, sink, ctx)
          mergeBlocksIntoCell(tableCtx.cell, sink)
        } else {
          handleShape(el, blocks, ctx)
        }
        break
      }

      // 메모 — 본문 혼입 차단 (v3.0)
      case "memogroup": case "memo": {
        if (ctx.warnings && extractTextFromNode(el)) {
          ctx.warnings.push({ page: ctx.sectionNum, message: "메모 텍스트 본문 제외: memogroup", code: "HIDDEN_TEXT_FILTERED" })
        }
        break
      }

      default:
        walkSection(el, blocks, tableCtx, tableStack, ctx, depth + 1)
        break
    }
  }
}

/**
 * 도형/그림 공통 처리 — 글상자 텍스트와 이미지를 병행 추출하고(기존 상호배타 수정),
 * 도형 캡션은 문단으로 보존한다. 둘 다 없으면 SKIPPED_IMAGE 경고.
 */
function handleShape(el: Element, sink: IRBlock[], ctx: WalkCtx): void {
  const imgRef = extractImageRef(el)
  const drawTextChild = findDescendant(el, "drawText")

  if (imgRef) {
    const block: IRBlock = { type: "image", text: imgRef, pageNumber: ctx.sectionNum }
    // 사용자 입력 그림 설명(alt) — builder가 image alt 출력을 지원할 때까지 IR에 보존,
    // 이미지 추출 실패 시 대체 문단의 각주로 표시된다
    const alt = userShapeComment(el)
    if (alt) block.footnoteText = alt
    sink.push(block)
  }
  if (drawTextChild) {
    extractDrawTextBlocks(drawTextChild, sink, ctx)
  }
  // 도형 캡션 (그림 캡션 등) — 이미지 아래 문단으로 보존
  const capEl = findChildByLocalName(el, "caption")
  if (capEl) {
    const capText = collectSubListText(capEl, ctx)
    if (capText) sink.push({ type: "paragraph", text: capText, pageNumber: ctx.sectionNum })
  }

  if (!imgRef && !drawTextChild && ctx.warnings && ctx.sectionNum) {
    const localTag = (el.tagName || el.localName || "").replace(/^[^:]+:/, "")
    ctx.warnings.push({ page: ctx.sectionNum, message: `스킵된 요소: ${localTag}`, code: "SKIPPED_IMAGE" })
  }
}

/** 도형의 사용자 입력 그림 설명 — 한컴 자동생성 대체텍스트("그림입니다." 등)는 제외 */
function userShapeComment(el: Element): string | undefined {
  const commentEl = findChildByLocalName(el, "shapeComment")
  if (!commentEl) return undefined
  const text = extractTextFromNode(commentEl)
  if (!text) return undefined
  if (/^그림입니다/.test(text)) return undefined
  if (/^(?:모서리가 둥근 |둥근 )?[^\n]{1,20}입니다\.?$/.test(text)) return undefined
  return text
}

/** 도형/중첩 콘텐츠 블록을 셀에 병합 — 텍스트는 cell.text에, 구조는 cell.blocks에 보존 */
function mergeBlocksIntoCell(cell: CellCtxEx, sink: IRBlock[]): void {
  for (const b of sink) {
    if ((b.type === "paragraph" || b.type === "heading") && b.text) {
      cell.text += (cell.text ? "\n" : "") + b.text
      ;(cell.blocks ??= []).push(b)
    } else if (b.type === "image" || b.type === "table") {
      if (b.type === "image" && b.text) {
        // GFM 표 경로는 cell.text만 출력하므로 인라인 이미지 참조를 남긴다
        // (extractImagesFromZip이 추출 후 실제 파일명으로 치환)
        cell.text += (cell.text ? "\n" : "") + `![image](${b.text})`
      }
      ;(cell.blocks ??= []).push(b)
      cell.hasStructure = true
    }
  }
}

/** caption/header/footer 등의 subList 내부 문단 텍스트 수집 */
function collectSubListText(el: Node, ctx: WalkCtx, depth = 0): string {
  if (depth > 10) return ""
  const parts: string[] = []
  const children = el.childNodes
  if (!children) return ""
  for (let i = 0; i < children.length; i++) {
    const ch = children[i] as Element
    if (ch.nodeType !== 1) continue
    const tag = (ch.tagName || ch.localName || "").replace(/^[^:]+:/, "")
    if (tag === "p" || tag === "para") {
      const t = extractParagraphInfo(ch, ctx.styleMap, ctx).text
      if (t) parts.push(t)
    } else if (tag === "tbl") {
      continue // 캡션/머리말 내 표는 미지원 — 텍스트만 수집
    } else {
      const t = collectSubListText(ch, ctx, depth + 1)
      if (t) parts.push(t)
    }
  }
  return parts.join("\n").trim()
}

/** <p> 내부에서 텍스트가 아닌 구조적 자식만 처리 (tbl, pic, shape). tableCtx 반환으로 상태 전파 */
function walkParagraphChildren(
  node: Node, blocks: IRBlock[],
  tableCtx: TableState | null, tableStack: TableState[],
  ctx: WalkCtx, depth: number = 0
): TableState | null {
  if (depth > MAX_XML_DEPTH) return tableCtx
  const children = node.childNodes
  if (!children) return tableCtx
  const walkChildren = (parent: Node, d: number) => {
    if (d > MAX_XML_DEPTH) return
    const kids = parent.childNodes
    if (!kids) return
    for (let i = 0; i < kids.length; i++) {
      const el = kids[i] as Element
      if (el.nodeType !== 1) continue
      const tag = el.tagName || el.localName || ""
      const localTag = tag.replace(/^[^:]+:/, "")

      if (localTag === "tbl") {
        // 테이블은 walkSection으로 위임
        if (tableCtx) tableStack.push(tableCtx)
        const newTable: TableState = { rows: [], currentRow: [], cell: null }
        walkSection(el, blocks, newTable, tableStack, ctx, d + 1)
        tableCtx = completeTable(newTable, tableStack, blocks, ctx)
      } else if (localTag === "pic" || localTag === "shape" || localTag === "drawingObject") {
        // 글상자 텍스트 + 이미지 병행 추출 — 셀 안이면 위치 보존을 위해 IRCell.blocks로
        if (tableCtx?.cell) {
          const sink: IRBlock[] = []
          handleShape(el, sink, ctx)
          mergeBlocksIntoCell(tableCtx.cell, sink)
        } else {
          handleShape(el, blocks, ctx)
        }
      } else if (localTag === "drawText") {
        // 글상자(TextBox) 안 텍스트 추출 — <hp:p> 순회
        if (tableCtx?.cell) {
          const sink: IRBlock[] = []
          extractDrawTextBlocks(el, sink, ctx)
          mergeBlocksIntoCell(tableCtx.cell, sink)
        } else {
          extractDrawTextBlocks(el, blocks, ctx)
        }
      } else if (localTag === "r" || localTag === "run" || localTag === "ctrl"
        || localTag === "rect" || localTag === "ellipse" || localTag === "polygon"
        || localTag === "line" || localTag === "arc" || localTag === "curve"
        || localTag === "connectLine" || localTag === "container") {
        // <hp:run>, <hp:ctrl>, 도형 요소 내부에 테이블/이미지/글상자가 포함될 수 있음 — 재귀
        walkChildren(el, d + 1)
      }
    }
  }
  walkChildren(node, depth)
  return tableCtx
}

/** 자손에서 특정 태그명의 첫 번째 요소 탐색 (최대 깊이 5) */
function findDescendant(node: Node, targetTag: string, depth = 0): Element | null {
  if (depth > 5) return null
  const children = node.childNodes
  if (!children) return null
  for (let i = 0; i < children.length; i++) {
    const child = children[i] as Element
    if (child.nodeType !== 1) continue
    const tag = (child.tagName || child.localName || "").replace(/^[^:]+:/, "")
    if (tag === targetTag) return child
    const found = findDescendant(child, targetTag, depth + 1)
    if (found) return found
  }
  return null
}

/** drawText(글상자) 내부의 <p> 요소들에서 텍스트를 추출하여 paragraph 블록 생성 */
function extractDrawTextBlocks(drawTextNode: Node, blocks: IRBlock[], ctx: WalkCtx): void {
  const children = drawTextNode.childNodes
  if (!children) return
  for (let i = 0; i < children.length; i++) {
    const child = children[i] as Element
    if (child.nodeType !== 1) continue
    const tag = (child.tagName || child.localName || "").replace(/^[^:]+:/, "")
    if (tag === "subList" || tag === "p" || tag === "para") {
      // subList 안의 <p>들을 순회
      if (tag === "subList") {
        extractDrawTextBlocks(child, blocks, ctx)
      } else {
        const info = extractParagraphInfo(child, ctx.styleMap, ctx)
        let text = info.text.trim()
        if (text) {
          const ph = resolveParaHeading(child, ctx)
          if (ph?.prefix) text = ph.prefix + " " + text
          const block: IRBlock = { type: "paragraph", text, style: info.style ?? undefined, pageNumber: ctx.sectionNum }
          if (info.href) block.href = info.href
          if (info.footnote) block.footnoteText = info.footnote
          blocks.push(block)
        }
        // 글상자 안 문단에 포함된 표/도형도 재귀 처리 — 조직도용 "글상자 안 표" 보존
        // (실증: 국방부 TF 5×7 조직표가 rect>drawText>p>tbl 구조로 통째 소실되던 케이스)
        walkParagraphChildren(child, blocks, null, [], ctx)
      }
    }
  }
}

interface ParagraphInfo {
  text: string
  href?: string
  footnote?: string
  style?: InlineStyle
}

/** fieldBegin이 HYPERLINK면 stringParam name="Path"에서 URL 추출 (살균 포함) */
function extractHyperlinkHref(fieldBegin: Element): string | undefined {
  if ((fieldBegin.getAttribute("type") || "").toUpperCase() !== "HYPERLINK") return undefined
  const params = findChildByLocalName(fieldBegin, "parameters")
  if (!params) return undefined
  const children = params.childNodes
  if (!children) return undefined
  for (let i = 0; i < children.length; i++) {
    const ch = children[i] as Element
    if (ch.nodeType !== 1) continue
    const tag = (ch.tagName || ch.localName || "").replace(/^[^:]+:/, "")
    if (tag !== "stringParam" || ch.getAttribute("name") !== "Path") continue
    let url = (ch.textContent || "").trim()
    if (!url) continue
    // 한컴이 중복 스킴을 저장하는 경우 정리 ("http://https://..." → "https://...")
    url = url.replace(/^https?:\/\/(?=https?:\/\/)/i, "")
    const safe = sanitizeHref(url)
    if (safe) return safe
  }
  return undefined
}

/** 변경추적 삭제 구간 내부 여부 */
function isInDeletedRange(ctx?: WalkCtx): boolean {
  return (ctx?.shared.track.deleteDepth ?? 0) > 0
}

function extractParagraphInfo(para: Element, styleMap?: HwpxStyleMap, ctx?: WalkCtx): ParagraphInfo {
  let text = ""
  let href: string | undefined
  let footnote: string | undefined
  let charPrId: string | undefined

  // 문단의 스타일 참조 → charPr로 간접 조회
  // HWPX <p>에는 paraPrIDRef/styleIDRef가 있고, charPrIDRef는 <r> 요소에 있음
  // 여기서는 일단 null — <r> 요소에서 charPrIDRef를 가져옴

  /** <hp:ctrl> 자식 선별 순회 — 머리말/꼬리말/각주/미주/하이퍼링크/변경추적 (v3.0) */
  const handleCtrl = (ctrlEl: Element) => {
    const kids = ctrlEl.childNodes
    if (!kids) return
    for (let j = 0; j < kids.length; j++) {
      const k = kids[j] as Element
      if (k.nodeType !== 1) continue
      const ktag = (k.tagName || k.localName || "").replace(/^[^:]+:/, "")
      switch (ktag) {
        // 머리말/꼬리말 — 문서당 1회 수집, 본문 앞/뒤 배치
        case "header": case "footer": {
          if (!ctx) break
          const t = collectSubListText(k, ctx)
          if (t) {
            const bucket = ktag === "header" ? ctx.shared.pageText.headers : ctx.shared.pageText.footers
            if (!bucket.includes(t)) bucket.push(t)
          }
          break
        }

        // 각주/미주 — 해당 문단의 footnote로 인라인 보존
        case "footNote": case "endNote": {
          const noteText = extractTextFromNode(k)
          if (noteText) footnote = (footnote ? footnote + "; " : "") + noteText
          break
        }

        // 하이퍼링크 — fieldBegin type=HYPERLINK의 Path 파라미터
        case "fieldBegin": {
          const url = extractHyperlinkHref(k)
          if (url && !href) href = url
          break
        }
        case "fieldEnd": break

        // 변경추적 — 삭제 구간(deleteBegin~End)의 텍스트는 출력 제외 (최종본 상태 재현)
        case "deleteBegin":
          if (ctx) ctx.shared.track.deleteDepth++
          break
        case "deleteEnd":
          if (ctx && ctx.shared.track.deleteDepth > 0) ctx.shared.track.deleteDepth--
          break
        case "insertBegin": case "insertEnd": break  // 삽입분은 최종본에 포함

        // 숨은 설명 — 본문 혼입 차단
        case "hiddenComment": {
          if (ctx?.warnings && extractTextFromNode(k)) {
            ctx.warnings.push({ page: ctx.sectionNum, message: "숨은 설명 텍스트 제외: hiddenComment", code: "HIDDEN_TEXT_FILTERED" })
          }
          break
        }

        // 콘텐츠 없는 제어 요소 — 스킵
        case "bookmark": case "pageNum": case "pageNumCtrl": case "pageHiding":
        case "newNum": case "autoNum": case "indexmark": case "colPr":
          break

        // 미지원 요소 — 텍스트를 가졌으면 무음 손실 대신 경고
        default: {
          if (ctx?.warnings && extractTextFromNode(k)) {
            ctx.warnings.push({ page: ctx.sectionNum, message: `미지원 제어 요소의 텍스트 손실: ${ktag}`, code: "UNSUPPORTED_ELEMENT" })
          }
        }
      }
    }
  }

  const walk = (node: Node) => {
    const children = node.childNodes
    if (!children) return
    for (let i = 0; i < children.length; i++) {
      const child = children[i] as Element
      if (child.nodeType === 3) {
        const t = child.textContent || ""
        if (isInDeletedRange(ctx)) {
          if (t && ctx && !ctx.shared.track.warned) {
            ctx.shared.track.warned = true
            ctx.warnings?.push({ page: ctx.sectionNum, message: "변경추적 삭제 텍스트 출력 제외", code: "HIDDEN_TEXT_FILTERED" })
          }
        } else {
          text += t
        }
        continue
      }
      if (child.nodeType !== 1) continue

      const tag = (child.tagName || child.localName || "").replace(/^[^:]+:/, "")
      switch (tag) {
        case "t": walk(child); break  // 자식 순회 (tab 등 하위 요소 처리)
        case "tab": {
          const leader = child.getAttribute("leader")
          if (leader && leader !== "0") {
            // 목차 리더 탭 (점선/실선 등) — 뒤에 페이지번호가 오므로 이후 텍스트 무시
            text += "\x1F"  // 특수 마커: 이후 텍스트 제거용
          } else {
            text += "\t"
          }
          break
        }
        case "br":
          if ((child.getAttribute("type") || "line") === "line") text += "\n"
          break
        case "lineBreak": text += "\n"; break // 강제 줄바꿈 — ref 추출기·소스맵 스캐너와 동일 모델
        case "fwSpace": case "hwSpace": text += " "; break
        case "tbl": break // 테이블은 walkSection에서 처리

        // 하이퍼링크
        case "hyperlink": {
          const url = child.getAttribute("url") || child.getAttribute("href") || ""
          if (url) {
            // XSS 방지: 추출 시점에서 href 살균
            const safe = sanitizeHref(url)
            if (safe) href = safe
          }
          // 하이퍼링크 내 텍스트 추출
          walk(child)
          break
        }

        // 각주/미주
        case "footNote": case "endNote": case "fn": case "en": {
          const noteText = extractTextFromNode(child)
          if (noteText) footnote = (footnote ? footnote + "; " : "") + noteText
          break
        }

        // 제어 요소 — 선별 순회 (머리말/꼬리말/각주/하이퍼링크/변경추적, v3.0)
        case "ctrl": handleCtrl(child); break

        // run 직계 fieldBegin (비표준 경로) — 하이퍼링크 URL만 추출
        case "fieldBegin": {
          const url = extractHyperlinkHref(child)
          if (url && !href) href = url
          break
        }

        // run 직계 변경추적 마커 (비표준 경로)
        case "deleteBegin": if (ctx) ctx.shared.track.deleteDepth++; break
        case "deleteEnd": if (ctx && ctx.shared.track.deleteDepth > 0) ctx.shared.track.deleteDepth--; break
        case "insertBegin": case "insertEnd": break

        case "fieldEnd":
        case "parameters": case "stringParam": case "integerParam":
        case "boolParam": case "floatParam":
        case "secPr":  // 섹션 속성 (페이지 설정 등)
        case "colPr":  // 다단 속성
        case "linesegarray": case "lineseg":  // 레이아웃 정보
        // 도형/이미지 요소 — 대체텍스트("사각형입니다." 등) 누출 방지 (walkParagraphChildren에서 처리)
        case "pic": case "shape": case "drawingObject":
        case "shapeComment": case "drawText":
          break

        // 수식: <hp:equation> 내부의 <hp:script> 에 HULK-style equation
        // 스크립트가 담겨 있음. hml-equation-parser 로 LaTeX 변환 후 `$...$`
        // 로 래핑. 실패/빈 스크립트면 무시 (대체 텍스트 누출 방지).
        case "equation": {
          const script = findChildByLocalName(child, "script")
          const raw = script ? extractTextFromNode(script) : ""
          if (raw.trim()) {
            try {
              const latex = hmlToLatex(raw).trim()
              if (latex) text += " $" + latex + "$ "
            } catch {
              // 변환 실패 시 조용히 드롭 — 텍스트 품질이 우선
            }
          }
          break
        }

        // run 요소에서 charPrIDRef 추출
        case "r": {
          const runCharPr = child.getAttribute("charPrIDRef")
          if (runCharPr && !charPrId) charPrId = runCharPr
          walk(child)
          break
        }

        default: walk(child); break
      }
    }
  }
  walk(para)

  // 목차 리더 마커(\x1F) 이후 텍스트(페이지번호) 제거
  const leaderIdx = text.indexOf("\x1F")
  if (leaderIdx >= 0) text = text.substring(0, leaderIdx)

  let cleanText = text.replace(/[ \t]+/g, " ").trim()

  // 한글 이미지 OLE 대체 텍스트 필터링 ("그림입니다. 원본 그림의 이름: ...")
  if (/^그림입니다\.?\s*원본\s*그림의\s*(이름|크기)/.test(cleanText)) cleanText = ""
  // 멀티라인으로 삽입된 OLE 대체 텍스트도 제거
  cleanText = cleanText.replace(/그림입니다\.?\s*원본\s*그림의\s*(이름|크기)[^\n]*(\n[^\n]*원본\s*그림의\s*(이름|크기)[^\n]*)*/g, "").trim()
  // HWP 도형/개체 대체텍스트 제거 ("사각형입니다.", "개체 입니다." 등)
  // NOTE: "수식" 은 제거 목록에서 빠져있음 — <hp:equation> 파싱으로 LaTeX 본문이 이미
  // `$...$` 형태로 삽입되기 때문에 여기서 지울 alt-text 는 존재하지 않는다.
  cleanText = cleanText.replace(/(?:모서리가 둥근 |둥근 )?(?:사각형|직사각형|정사각형|원|타원|삼각형|선|직선|곡선|화살표|오각형|육각형|팔각형|별|십자|구름|마름모|도넛|평행사변형|사다리꼴|개체|그리기\s?개체|묶음\s?개체|글상자|표|그림|OLE\s?개체)\s?입니다\.?/g, "").trim()

  // 스타일 정보 조회
  let style: InlineStyle | undefined
  if (styleMap && charPrId) {
    const charProp = styleMap.charProperties.get(charPrId)
    if (charProp) {
      style = {}
      if (charProp.fontSize) style.fontSize = charProp.fontSize
      if (charProp.bold) style.bold = true
      if (charProp.italic) style.italic = true
      if (charProp.fontName) style.fontName = charProp.fontName
      if (!style.fontSize && !style.bold && !style.italic) style = undefined
    }
  }

  return { text: cleanText, href, footnote, style }
}

/** 자식 중 지정된 localName(접두사 제거)을 가진 첫 번째 Element 반환 */
function findChildByLocalName(parent: Element, name: string): Element | null {
  const children = parent.childNodes
  if (!children) return null
  for (let i = 0; i < children.length; i++) {
    const ch = children[i] as Element
    if (ch.nodeType !== 1) continue
    const tag = (ch.tagName || ch.localName || "").replace(/^[^:]+:/, "")
    if (tag === name) return ch
  }
  return null
}

/** 노드 내 모든 텍스트를 재귀적으로 추출 */
function extractTextFromNode(node: Node): string {
  let result = ""
  const children = node.childNodes
  if (!children) return result
  for (let i = 0; i < children.length; i++) {
    const child = children[i]
    if (child.nodeType === 3) result += child.textContent || ""
    else if (child.nodeType === 1) result += extractTextFromNode(child)
  }
  return result.trim()
}
