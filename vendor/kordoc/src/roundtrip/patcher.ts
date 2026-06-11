/**
 * HWPX 서식 보존 무손실 라운드트립 패치 — v3.0 킬러기능.
 *
 * parse()로 얻은 마크다운을 편집한 뒤 patchHwpx()에 넘기면, 원본 HWPX의
 * ZIP/XML 구조를 그대로 두고 변경된 문단/셀의 텍스트만 in-place 치환한다.
 * 스타일·이미지·표 구조·설정은 1바이트도 건드리지 않는다 (section XML 외
 * ZIP 엔트리는 원본 바이트 그대로, 변경 문단도 run 구조·charPr 보존).
 *
 * 지원: 문단/헤딩 텍스트 수정, 표 셀 텍스트 수정 (GFM·HTML·1x1·1열 표).
 * 미지원(graceful skip): 블록 추가/삭제/순서 변경, 표 구조 변경, 캡션·각주·
 * 머리말/꼬리말·이미지 변경. skipped[]에 사유와 함께 보고된다.
 */

import JSZip from "jszip"
import { parseHwpxDocument } from "../hwpx/parser.js"
import { blocksToMarkdown } from "../table/builder.js"
import { normalizedSimilarity } from "../diff/text-diff.js"
import type { IRBlock, IRTable, PatchOptions, PatchResult, PatchSkip, DiffResult, BlockDiff } from "../types.js"
import {
  scanSectionXml, buildParagraphSplices, applySplices,
  type SectionScan, type ScanParagraph, type ScanCell, type ScanTable, type SpliceEdit,
} from "./source-map.js"
import { patchZipEntries } from "./zip-patch.js"
import {
  splitMarkdownUnits, normForMatch, sanitizeText, unescapeGfm, summarize,
  type MdUnit,
} from "./markdown-units.js"
import { patchGfmTable, patchHtmlTable, patchTextChunkTable } from "./table-patch.js"

export type { PatchOptions, PatchResult, PatchSkip } from "../types.js"

// ─── 메인 API ────────────────────────────────────────

/**
 * 원본 HWPX와 편집된 마크다운으로 서식 보존 패치본을 만든다.
 *
 * @param original 원본 HWPX 바이트
 * @param editedMarkdown parse(original).markdown을 편집한 마크다운
 */
export async function patchHwpx(
  original: Uint8Array,
  editedMarkdown: string,
  options?: PatchOptions,
): Promise<PatchResult> {
  const skipped: PatchSkip[] = []
  let applied = 0

  // 1) 원본 파싱 (기존 파서 그대로 — IR 블록과 마크다운 확보)
  let origBlocks: IRBlock[]
  try {
    const parsed = await parseHwpxDocument(u8ToArrayBuffer(original))
    origBlocks = parsed.blocks
  } catch (err) {
    return { success: false, applied: 0, skipped, error: `원본 HWPX 파싱 실패: ${err instanceof Error ? err.message : String(err)}` }
  }

  // 2) 소스맵 — section XML 직접 스캔 (DOM 재직렬화 없음)
  let zip: JSZip
  try {
    zip = await JSZip.loadAsync(original)
  } catch {
    return { success: false, applied: 0, skipped, error: "ZIP 로드 실패" }
  }
  const sectionPaths = await resolveSectionEntryNames(zip)
  if (sectionPaths.length === 0) {
    return { success: false, applied: 0, skipped, error: "HWPX 섹션 파일을 찾을 수 없습니다" }
  }
  const scans: SectionScan[] = []
  for (let i = 0; i < sectionPaths.length; i++) {
    const xml = await zip.file(sectionPaths[i])!.async("text")
    scans.push(scanSectionXml(xml, i))
  }

  // 3) 유닛 구성 + 정렬 (마크다운 도메인 diff)
  const origUnits = buildOrigUnits(origBlocks)
  const editedUnits = splitMarkdownUnits(editedMarkdown)
  const pairs = alignUnits(origUnits.map(u => u.raw), editedUnits.map(u => u.raw))

  // 4) 본문 문단 ↔ 소스맵 문단 매핑 (정규화 텍스트 + 등장 순서)
  const paraMap = resolveParagraphMappings(origBlocks, scans)
  const scanTables = scans.flatMap(s => s.tables.filter(t => t.rows.length > 0))
  const obTableOrdinals = buildTableOrdinals(origBlocks)

  // 5) 변경 적용
  const sectionSplices: SpliceEdit[][] = scans.map(() => [])
  for (const [oi, ei] of pairs) {
    if (oi !== null && ei !== null) {
      const orig = origUnits[oi]
      const edited = editedUnits[ei]
      if (orig.raw === edited.raw) continue
      applied += handleModifiedUnit(orig, edited, {
        origBlocks, paraMap, scans, scanTables, obTableOrdinals, sectionSplices, skipped,
      })
    } else if (oi !== null) {
      skipped.push({ reason: "블록 삭제는 미지원 (v1) — 원본 유지", before: summarize(origUnits[oi].raw) })
    } else if (ei !== null) {
      skipped.push({ reason: "블록 추가는 미지원 (v1)", after: summarize(editedUnits[ei].raw) })
    }
  }

  // 6) ZIP 재조립 — 수정된 섹션만 교체, 나머지는 원본 바이트 그대로
  const replacements = new Map<string, Uint8Array>()
  const encoder = new TextEncoder()
  try {
    for (let i = 0; i < scans.length; i++) {
      if (sectionSplices[i].length === 0) continue
      const newXml = applySplices(scans[i].xml, sectionSplices[i])
      replacements.set(sectionPaths[i], encoder.encode(newXml))
    }
  } catch (err) {
    return { success: false, applied: 0, skipped, error: `소스맵 splice 실패: ${err instanceof Error ? err.message : String(err)}` }
  }

  let data: Uint8Array
  if (replacements.size === 0) {
    data = new Uint8Array(original) // Buffer.slice는 view라 명시적 복사
  } else {
    try {
      data = patchZipEntries(original, replacements)
    } catch (err) {
      return { success: false, applied: 0, skipped, error: `ZIP 재조립 실패: ${err instanceof Error ? err.message : String(err)}` }
    }
  }

  // 7) 자동 검증 — 패치본 재파싱 vs 편집 마크다운
  let verification: DiffResult | undefined
  if (options?.verify !== false) {
    try {
      const reparsed = await parseHwpxDocument(u8ToArrayBuffer(data))
      verification = diffUnitLists(splitMarkdownUnits(reparsed.markdown), editedUnits)
    } catch (err) {
      return { success: false, applied, skipped, error: `패치본 재파싱 실패 — 패치 중단: ${err instanceof Error ? err.message : String(err)}` }
    }
  }

  return { success: true, data, applied, skipped, verification }
}

// ─── 유닛 구성 ───────────────────────────────────────

export interface OrigUnit extends MdUnit {
  /** 출처 IR 블록 인덱스 */
  blockIdx: number
  role?: "caption"
  /** 한 문단 블록이 여러 유닛으로 갈라짐 (강제 줄바꿈 \n\n, 문단 내 '|' 줄, [별표] 2블록
   *  병합) — 유닛 하나의 수정이 문단 전체를 덮어쓰므로 부분 수정 미지원 처리 */
  fragment?: boolean
}

/**
 * IR 블록별 개별 렌더링으로 유닛 생성 — blocksToMarkdown의 [별표 N] 2블록
 * 병합 규칙을 재현해 전체 렌더와 동일한 분할을 보장한다.
 */
export function buildOrigUnits(blocks: IRBlock[]): OrigUnit[] {
  const units: OrigUnit[] = []
  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i]
    let consume = 1
    let chunk: string
    if (block.type === "paragraph" && block.text && /^\[별표\s*\d+/.test(sanitizeText(block.text))) {
      const next = blocks[i + 1]
      if (next?.type === "paragraph" && next.text && /관련\)?$/.test(next.text)) consume = 2
      chunk = blocksToMarkdown(blocks.slice(i, i + consume))
    } else {
      chunk = blocksToMarkdown([block])
    }
    if (chunk) {
      const subUnits = splitMarkdownUnits(chunk)
      // 문단/헤딩 블록이 여러 유닛으로 갈라지거나 [별표] 2블록 병합이면 부분 수정 불가
      const isFragment = consume === 2
        || ((block.type === "paragraph" || block.type === "heading") && subUnits.length > 1)
      for (let s = 0; s < subUnits.length; s++) {
        const u: OrigUnit = { ...subUnits[s], blockIdx: i, fragment: isFragment || undefined }
        // 표 캡션 — 표 유닛 앞의 **...** 텍스트 유닛
        if (block.type === "table" && block.table?.caption && s === 0 && subUnits.length > 1 && u.kind === "text" && u.raw.startsWith("**")) {
          u.role = "caption"
        }
        units.push(u)
      }
    }
    i += consume - 1
  }
  return units
}

/** OB 표 블록 인덱스 → 최상위 표 서수 */
function buildTableOrdinals(blocks: IRBlock[]): Map<number, number> {
  const map = new Map<number, number>()
  let ordinal = 0
  for (let i = 0; i < blocks.length; i++) {
    if (blocks[i].type === "table" && blocks[i].table) map.set(i, ordinal++)
  }
  return map
}

// ─── 유닛 정렬 (정확 일치 LCS + 갭 유사도 페어링) ────

export type AlignedPair = [number | null, number | null]

export function alignUnits(a: string[], b: string[]): AlignedPair[] {
  const m = a.length, n = b.length
  if (m * n > 4_000_000) {
    // 대형 문서 보호 — dense LCS 불가. 공통 prefix/suffix만 정확 일치로 페어링하고
    // 가운데 구간은 길이가 같을 때만 인덱스 페어링, 다르면(블록 추가/삭제) 전부
    // 추가/삭제로 보고해 시프트 오적용(전 문단이 한 칸씩 밀려 덮어써짐)을 차단한다.
    const result: AlignedPair[] = []
    let pre = 0
    while (pre < m && pre < n && a[pre] === b[pre]) { result.push([pre, pre]); pre++ }
    let suf = 0
    while (suf < m - pre && suf < n - pre && a[m - 1 - suf] === b[n - 1 - suf]) suf++
    const aMid = m - pre - suf, bMid = n - pre - suf
    if (aMid === bMid) {
      for (let i = 0; i < aMid; i++) result.push([pre + i, pre + i])
    } else {
      for (let i = 0; i < aMid; i++) result.push([pre + i, null])
      for (let j = 0; j < bMid; j++) result.push([null, pre + j])
    }
    for (let s = suf - 1; s >= 0; s--) result.push([m - 1 - s, n - 1 - s])
    return result
  }

  // 정확 일치 LCS
  const dp: Int32Array[] = Array.from({ length: m + 1 }, () => new Int32Array(n + 1))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = a[i - 1] === b[j - 1]
        ? dp[i - 1][j - 1] + 1
        : Math.max(dp[i - 1][j], dp[i][j - 1])
    }
  }
  const matches: [number, number][] = []
  let i = m, j = n
  while (i > 0 && j > 0) {
    if (a[i - 1] === b[j - 1] && dp[i][j] === dp[i - 1][j - 1] + 1) {
      matches.push([i - 1, j - 1]); i--; j--
    } else if (dp[i - 1][j] >= dp[i][j - 1]) i--
    else j--
  }
  matches.reverse()

  // 갭 구간 페어링 — 양쪽 갭 크기가 같으면 위치 기반(전면 재작성 인정),
  // 다르면 유사도 기반으로 수정/추가/삭제 구분
  const result: AlignedPair[] = []
  let ai = 0, bi = 0
  const flushGap = (aEnd: number, bEnd: number) => {
    if (aEnd - ai === bEnd - bi) {
      while (ai < aEnd) result.push([ai++, bi++])
      return
    }
    while (ai < aEnd && bi < bEnd) {
      const sim = normalizedSimilarity(a[ai], b[bi])
      if (sim >= 0.4) {
        // 갭이 긴 쪽에 더 나은 후보가 있으면 현재 항목은 삭제/추가로 밀어낸다 —
        // 비슷한 두 문단 중 하나를 지운 편집에서 남은 문단이 덮어써지는 것을 방지
        if (aEnd - ai > bEnd - bi && bestSimInRange(a, ai + 1, ai + (aEnd - ai) - (bEnd - bi), b[bi]) > sim) {
          result.push([ai++, null])
        } else if (bEnd - bi > aEnd - ai && bestSimInRange(b, bi + 1, bi + (bEnd - bi) - (aEnd - ai), a[ai]) > sim) {
          result.push([null, bi++])
        } else {
          result.push([ai++, bi++])
        }
      } else if (aEnd - ai >= bEnd - bi) result.push([ai++, null])
      else result.push([null, bi++])
    }
    while (ai < aEnd) result.push([ai++, null])
    while (bi < bEnd) result.push([null, bi++])
  }
  for (const [pi, pj] of matches) {
    flushGap(pi, pj)
    result.push([ai++, bi++])
  }
  flushGap(m, n)
  return result
}

/** [from, to] 범위에서 target과의 최고 유사도 */
function bestSimInRange(arr: string[], from: number, to: number, target: string): number {
  let best = 0
  for (let k = from; k <= to && k < arr.length; k++) {
    const s = normalizedSimilarity(arr[k], target)
    if (s > best) best = s
  }
  return best
}

// ─── 문단 매핑 ───────────────────────────────────────

interface ParaMapping {
  para?: ScanParagraph
  /** 자동번호 접두가 IR 텍스트에 붙어 있었음 (스캔 텍스트에는 없음) */
  prefixStripped?: boolean
}

/**
 * OB 문단/헤딩 블록 → 스캔 문단 매핑.
 * 같은 정규화 텍스트끼리 등장 순서대로 페어링 (중복 문단 대응).
 * 머리말/꼬리말로 배치된 선두/말미 블록은 매핑에서 제외.
 */
function resolveParagraphMappings(blocks: IRBlock[], scans: SectionScan[]): Map<number, ParaMapping> {
  const buckets = new Map<string, ScanParagraph[]>()
  for (const scan of scans) {
    for (const para of scan.bodyParagraphs) {
      const key = normForMatch(para.text)
      if (!key) continue
      let list = buckets.get(key)
      if (!list) buckets.set(key, (list = []))
      list.push(para)
    }
  }
  const headerNorms = new Set(scans.flatMap(s => s.headerTexts.map(normForMatch)).filter(Boolean))
  const footerNorms = new Set(scans.flatMap(s => s.footerTexts.map(normForMatch)).filter(Boolean))

  // applyPageText가 선두/말미에 배치한 머리말/꼬리말 블록 식별
  // (detectHwpxHeadings가 pageText 블록을 heading으로 재타입할 수 있어 heading도 검사)
  const pageText = new Set<number>()
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i]
    if ((b.type !== "paragraph" && b.type !== "heading") || !b.text || !headerNorms.has(normForMatch(b.text))) break
    pageText.add(i)
  }
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i]
    if ((b.type !== "paragraph" && b.type !== "heading") || !b.text || !footerNorms.has(normForMatch(b.text))) break
    pageText.add(i)
  }

  const counters = new Map<string, number>()
  const result = new Map<number, ParaMapping>()
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i]
    if ((b.type !== "paragraph" && b.type !== "heading") || !b.text) continue
    if (pageText.has(i)) { result.set(i, {}); continue }

    let key = normForMatch(b.text)
    let prefixStripped = false
    if (!buckets.has(key)) {
      // 자동번호/글머리 접두 제거 후 재시도 (resolveParaHeading가 붙인 prefix)
      const sp = b.text.indexOf(" ")
      if (sp > 0) {
        const alt = normForMatch(b.text.slice(sp + 1))
        if (alt && buckets.has(alt)) { key = alt; prefixStripped = true }
      }
    }
    const list = buckets.get(key)
    if (!list) { result.set(i, {}); continue }
    const occ = counters.get(key) ?? 0
    counters.set(key, occ + 1)
    result.set(i, occ < list.length ? { para: list[occ], prefixStripped } : {})
  }
  return result
}

// ─── 변경 처리 ───────────────────────────────────────

interface PatchCtx {
  origBlocks: IRBlock[]
  paraMap: Map<number, ParaMapping>
  scans: SectionScan[]
  scanTables: ScanTable[]
  obTableOrdinals: Map<number, number>
  sectionSplices: SpliceEdit[][]
  skipped: PatchSkip[]
}

/** 변경된 유닛 쌍 처리 — 적용 건수 반환 */
function handleModifiedUnit(orig: OrigUnit, edited: MdUnit, ctx: PatchCtx): number {
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
    // IR 최상위 표 수 ≠ 스캔 최상위 표 수면 서수가 밀려 엉뚱한 표가 수정될 수 있음
    if (ctx.obTableOrdinals.size !== ctx.scanTables.length) return skip("표 개수 불일치 — 소스맵 신뢰 불가")
    const ordinal = ctx.obTableOrdinals.get(orig.blockIdx)
    const scanTable = ordinal !== undefined ? ctx.scanTables[ordinal] : undefined
    if (!scanTable) return skip("표 소스맵 매핑 실패")
    if (orig.kind === "gfm-table") return patchGfmTable(block.table, scanTable, orig, edited, ctx, skip)
    if (orig.kind === "html-table") return patchHtmlTable(block.table, scanTable, orig, edited, ctx, skip)
    return patchTextChunkTable(block.table, scanTable, orig, edited, ctx, skip)
  }

  if ((block.type === "paragraph" || block.type === "heading") && orig.kind === "text" && edited.kind === "text") {
    return patchParagraphUnit(block, orig, edited, ctx, skip)
  }

  return skip("지원하지 않는 블록 유형 변경")
}

// ── 문단 ──

function patchParagraphUnit(
  block: IRBlock, orig: OrigUnit, edited: MdUnit, ctx: PatchCtx,
  skip: (reason: string) => number,
): number {
  const mapping = ctx.paraMap.get(orig.blockIdx)
  if (!mapping?.para) return skip("문단 소스맵 매핑 실패 (머리말/글상자/캡션 영역이거나 텍스트 불일치)")

  // 문단 내 강제 줄바꿈(<hp:br/>/<hp:lineBreak/>) — 평문 치환 시 줄바꿈이 공백으로
  // 변해 무손실 약속이 깨지므로 미지원 (v1)
  if (block.text && block.text.includes("\n")) {
    return skip("문단 내 강제 줄바꿈 포함 — 수정 시 줄바꿈 보존 불가로 미지원 (v1)")
  }

  // 편집 마크다운 → 평문
  const origPlain = textUnitToPlain(orig.raw, block)
  let newPlain = textUnitToPlain(edited.raw, block)

  // 각주 표기 처리 — 본문이 아닌 각주 ctrl에 있으므로 분리
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

  // 자동번호 접두 — XML에 없는 텍스트이므로 떼고 기록
  if (mapping.prefixStripped) {
    const origPrefix = block.text!.split(" ", 1)[0]
    const sp = newPlain.indexOf(" ")
    const newFirst = sp > 0 ? newPlain.slice(0, sp) : newPlain
    // 번호 형식: 끝 구두점 필수("1." "가)" "(2)") 또는 단일 원문자/로마자 — 맨 단어 오인 방지
    if (newFirst === origPrefix || /^(?:[0-9０-９a-zA-Z가-힣]{1,6}[.)\]:]|[([][0-9０-９a-zA-Z가-힣]{1,6}[)\]][.:]?|[ⅰ-ⅹⅠ-Ⅹ①-⑮][.)\]:]?)$/u.test(newFirst)) {
      newPlain = sp > 0 ? newPlain.slice(sp + 1) : ""
    } else {
      ctx.skipped.push({ reason: "자동번호 접두 식별 실패 — 번호 포함 텍스트로 적용 (뷰어에서 중복 표시 가능)", after: summarize(newPlain) })
    }
  }

  if (newPlain === origPlain) return skip("텍스트 외 변경(헤딩 레벨/서식)만 감지 — 스타일 변경은 미지원")

  // 단일 hp:t로 합쳐 기록하면 재파싱 sanitize에서 변형되는 텍스트(run 경계 이중 공백 등)
  // — 기록 후 동일 렌더가 보장되지 않으므로 미지원
  if (sanitizeText(newPlain) !== newPlain) {
    return skip("공백 정규화 불안정 텍스트 — 패치 시 원문 보존 불가로 미지원")
  }

  const splices = buildParagraphSplices(mapping.para, newPlain, ctx.scans[mapping.para.sectionIndex]?.xml)
  if (splices === null) return skip("문단에 텍스트 노드를 만들 수 없음")
  ctx.sectionSplices[mapping.para.sectionIndex].push(...splices)
  return 1
}

/** 텍스트 유닛 마크다운 → 평문 (builder 렌더링의 역변환) */
export function textUnitToPlain(raw: string, block: IRBlock): string {
  // 여러 줄(soft-wrap)은 한 문단으로
  let text = raw.split("\n").map(l => l.trim()).filter(Boolean).join(" ")
  // 헤딩 접두 — 헤딩/[별표] 블록만 (리터럴 '# '로 시작하는 일반 문단은 보존)
  if (block.type === "heading" || (block.text && /^\[별표\s*\d+/.test(sanitizeText(block.text)))) {
    text = text.replace(/^#{1,6}\s+/, "")
  }
  // 링크 — 원본이 href 블록일 때 표시 텍스트만
  if (block.href) {
    const linkMatch = text.match(/^\[([\s\S]*)\]\([^)]*\)$/)
    if (linkMatch) text = linkMatch[1]
  }
  // *(...관련)* 이탤릭 래핑
  if (/^\*[^*][\s\S]*\*$/.test(text) && block.text && /^\([^)]*조[^)]*관련\)$/.test(sanitizeText(block.text))) {
    text = text.slice(1, -1)
  }
  return unescapeGfm(text)
}

// ─── 검증 diff ───────────────────────────────────────

/** 유닛 목록 diff → DiffResult (검증 리포트용) */
export function diffUnitLists(a: MdUnit[], b: MdUnit[]): DiffResult {
  const pairs = alignUnits(a.map(u => u.raw), b.map(u => u.raw))
  const stats = { added: 0, removed: 0, modified: 0, unchanged: 0 }
  const diffs: BlockDiff[] = []
  for (const [ai, bi] of pairs) {
    if (ai !== null && bi !== null) {
      if (a[ai].raw === b[bi].raw) { stats.unchanged++; continue }
      stats.modified++
      diffs.push({ type: "modified", before: unitToBlock(a[ai]), after: unitToBlock(b[bi]), similarity: normalizedSimilarity(a[ai].raw, b[bi].raw) })
    } else if (ai !== null) {
      stats.removed++
      diffs.push({ type: "removed", before: unitToBlock(a[ai]) })
    } else if (bi !== null) {
      stats.added++
      diffs.push({ type: "added", after: unitToBlock(b[bi]) })
    }
  }
  return { stats, diffs }
}

function unitToBlock(u: MdUnit): IRBlock {
  return { type: "paragraph", text: u.raw }
}

// ─── 헬퍼 ────────────────────────────────────────────

function u8ToArrayBuffer(u8: Uint8Array): ArrayBuffer {
  return u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength) as ArrayBuffer
}

/** manifest(content.hpf) 기반 섹션 엔트리명 해석 — parser.ts resolveSectionPaths와 동일하게
 *  zip 엔트리 정확 일치만 포함 (대소문자 보정 금지 — 파서가 못 본 섹션이 스캔에 끼면
 *  중복 텍스트 문단 수정이 비가시 섹션에 적용되는 cross-section bleed 발생) */
async function resolveSectionEntryNames(zip: JSZip): Promise<string[]> {
  for (const mp of ["Contents/content.hpf", "content.hpf"]) {
    const f = zip.file(mp)
    if (!f) continue
    const xml = await f.async("text")
    const paths = sectionPathsFromManifest(xml).filter(p => zip.file(p) !== null)
    if (paths.length > 0) return paths
  }
  return Object.keys(zip.files).filter(n => /[Ss]ection\d+\.xml$/.test(n)).sort()
}

function sectionPathsFromManifest(xml: string): string[] {
  const isSectionId = (id: string) => /^s/i.test(id) || id.toLowerCase().includes("section")
  const attr = (tag: string, name: string): string => {
    const m = tag.match(new RegExp(`(?:^|\\s)${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)')`))
    return m ? (m[1] ?? m[2]) : ""
  }
  const idToHref = new Map<string, string>()
  for (const m of xml.matchAll(/<opf:item(\s(?:"[^"]*"|'[^']*'|[^>"'])*?)\/?>/g)) {
    const id = attr(m[1], "id")
    let href = attr(m[1], "href")
    const mediaType = attr(m[1], "media-type")
    if (!isSectionId(id) && !mediaType.includes("xml")) continue
    if (!href.startsWith("/") && !href.startsWith("Contents/") && isSectionId(id)) href = "Contents/" + href
    if (id) idToHref.set(id, href)
  }
  const ordered: string[] = []
  for (const m of xml.matchAll(/<opf:itemref(\s(?:"[^"]*"|'[^']*'|[^>"'])*?)\/?>/g)) {
    const href = idToHref.get(attr(m[1], "idref"))
    if (href) ordered.push(href)
  }
  if (ordered.length > 0) return ordered
  return Array.from(idToHref.entries())
    .filter(([id]) => isSectionId(id))
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([, href]) => href)
}
