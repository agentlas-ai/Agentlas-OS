/**
 * 라운드트립 마크다운 유닛 — blocksToMarkdown 출력과 호환되는 블록 단위 분할.
 *
 * 원본 마크다운(=blocksToMarkdown 출력)과 편집된 마크다운을 같은 규칙으로
 * 분할해 유닛 단위 diff를 수행한다. 표는 builder.ts의 GFM/HTML 렌더링을
 * 좌표 추적(provenance) 버전으로 재현해, 편집된 셀 → IRTable 격자 좌표를
 * 역산한다. 재현 결과가 원본 마크다운과 다르면 해당 표는 graceful skip
 * 대상이 된다 (builder와의 드리프트 자기 검증).
 */

import type { IRTable } from "../types.js"
import { mapPuaText } from "../shared/pua.js"

// ─── 유닛 분할 ───────────────────────────────────────

export type UnitKind = "text" | "gfm-table" | "html-table" | "separator" | "image"

export interface MdUnit {
  kind: UnitKind
  /** 원문 그대로 (트림된 라인 조인) */
  raw: string
  /** 라인 배열 */
  lines: string[]
}

/** blocksToMarkdown 출력 호환 마크다운 블록 분할 */
export function splitMarkdownUnits(md: string): MdUnit[] {
  const lines = md.split("\n")
  const units: MdUnit[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }

    // HTML 표 — <table> ~ 짝이 맞는 </table>
    if (line.trim().startsWith("<table>")) {
      const collected: string[] = []
      let depth = 0
      while (i < lines.length) {
        const l = lines[i]
        collected.push(l)
        depth += (l.match(/<table>/g) || []).length
        depth -= (l.match(/<\/table>/g) || []).length
        i++
        if (depth <= 0) break
      }
      units.push({ kind: "html-table", raw: collected.join("\n"), lines: collected })
      continue
    }

    // GFM 표 — 연속된 | 시작 라인
    if (line.trimStart().startsWith("|")) {
      const collected: string[] = []
      while (i < lines.length && lines[i].trimStart().startsWith("|")) {
        collected.push(lines[i])
        i++
      }
      units.push({ kind: "gfm-table", raw: collected.join("\n"), lines: collected })
      continue
    }

    // 구분선
    if (/^-{3,}\s*$/.test(line.trim())) {
      units.push({ kind: "separator", raw: line.trim(), lines: [line.trim()] })
      i++
      continue
    }

    // 이미지 단독 라인
    if (/^!\[image\]\([^)]*\)\s*$/.test(line.trim())) {
      units.push({ kind: "image", raw: line.trim(), lines: [line.trim()] })
      i++
      continue
    }

    // 일반 텍스트 — 연속 비공백 라인 묶음 (1x1/1열 표 청크 포함)
    const collected: string[] = []
    while (i < lines.length && lines[i].trim()
      && !lines[i].trimStart().startsWith("|")
      && !lines[i].trim().startsWith("<table>")) {
      collected.push(lines[i].trim())
      i++
    }
    units.push({ kind: "text", raw: collected.join("\n"), lines: collected })
  }

  return units
}

// ─── builder.ts 텍스트 변환 재현 (드리프트 시 자기 검증으로 skip) ─────

/** GFM 특수문자 이스케이프 — builder.ts escapeGfm과 동일 */
export function escapeGfm(text: string): string {
  return text.replace(/~/g, "\\~")
}

/** builder.ts HWP_SHAPE_ALT_TEXT_RE와 동일 */
const HWP_SHAPE_ALT_TEXT_RE = /(?:모서리가 둥근 |둥근 )?(?:사각형|직사각형|정사각형|원|타원|삼각형|이등변 삼각형|직각 삼각형|선|직선|곡선|화살표|굵은 화살표|이중 화살표|오각형|육각형|팔각형|별|[4-8]점별|십자|십자형|구름|구름형|마름모|도넛|평행사변형|사다리꼴|부채꼴|호|반원|물결|번개|하트|빗금|블록 화살표|수식|표|그림|개체|그리기\s?개체|묶음\s?개체|글상자|수식\s?개체|OLE\s?개체)\s?입니다\.?/g

/** builder.ts sanitizeText와 동일 (PUA 매핑 + 대체텍스트 제거 + 균등배분 정리) */
export function sanitizeText(text: string): string {
  let result = mapPuaText(text)
    .replace(/[\u{F0000}-\u{FFFFD}]/gu, "")
    .replace(HWP_SHAPE_ALT_TEXT_RE, "")
    .replace(/  +/g, " ")
    .trim()
  if (result.length <= 30 && result.includes(" ")) {
    const tokens = result.split(" ")
    const koreanSingleCharCount = tokens.filter(t => t.length === 1 && /[가-힯ㄱ-ㆎ]/.test(t)).length
    if (tokens.length >= 3 && koreanSingleCharCount / tokens.length >= 0.7) {
      result = tokens.join("")
    }
  }
  return result
}

/** 매칭용 정규화 — sanitize + 공백 붕괴. 스캔 텍스트(IR 변환 전)와 IR 텍스트 양쪽에 적용 */
export function normForMatch(text: string): string {
  return sanitizeText(text).replace(/\s+/g, " ").trim()
}

/** 편집된 마크다운 텍스트 → 평문 (escapeGfm 역변환) */
export function unescapeGfm(text: string): string {
  return text.replace(/\\~/g, "~")
}

/** 스킵 보고용 내용 요약 (최대 80자) */
export function summarize(text: string): string {
  const t = text.replace(/\s+/g, " ").trim()
  return t.length > 80 ? t.slice(0, 77) + "..." : t
}

// ─── GFM 표 — 좌표 추적 렌더 재현 + 파서 ────────────

export interface MappedCell {
  text: string
  gridR: number
  gridC: number
}

/**
 * builder.ts tableToMarkdown의 GFM 경로 재현 — 출력 셀마다 격자 좌표 기록.
 * (병합/중첩 표는 HTML 경로이므로 여기 오지 않음. 1x1/1열 표는 별도 처리)
 * 반환 null이면 GFM 경로가 아니라는 뜻.
 */
export function replicateGfmTable(table: IRTable): MappedCell[][] | null {
  const { cells, rows: numRows, cols: numCols } = table
  if (numRows === 0 || numCols === 0) return null
  if (numRows === 1 && numCols === 1) return null
  if (numCols === 1) return null

  const display: MappedCell[][] = Array.from({ length: numRows }, (_, r) =>
    Array.from({ length: numCols }, (_, c) => ({ text: "", gridR: r, gridC: c })))
  const skip = new Set<string>()

  for (let r = 0; r < numRows; r++) {
    for (let c = 0; c < numCols; c++) {
      if (skip.has(`${r},${c}`)) continue
      const cell = cells[r]?.[c]
      if (!cell) continue
      display[r][c] = {
        text: escapeGfm(sanitizeText(cell.text)).replace(/\|/g, "\\|").replace(/\n/g, "<br>"),
        gridR: r,
        gridC: c,
      }
      for (let dr = 0; dr < cell.rowSpan; dr++) {
        for (let dc = 0; dc < cell.colSpan; dc++) {
          if (dr === 0 && dc === 0) continue
          if (r + dr < numRows && c + dc < numCols) skip.add(`${r + dr},${c + dc}`)
        }
      }
      c += cell.colSpan - 1
    }
  }

  // builder.ts와 동일한 빈 행 제거/첫 열 전파 (보류 행 소실 방지 포함)
  const uniqueRows: MappedCell[][] = []
  let pendingLabelRow: MappedCell[] | null = null
  for (let r = 0; r < display.length; r++) {
    const row = display[r]
    if (row.every(cell => cell.text === "")) continue

    const nonEmptyCols = row.filter(cell => cell.text !== "")
    const hasSkipInRow = row.some((_, c) => skip.has(`${r},${c}`))
    if (!hasSkipInRow && nonEmptyCols.length === 1 && row[0].text !== "" && row.slice(1).every(c => c.text === "")) {
      if (pendingLabelRow) uniqueRows.push(pendingLabelRow)
      pendingLabelRow = row
      continue
    }
    if (pendingLabelRow) {
      if (row[0].text === "") row[0] = pendingLabelRow[0]
      else uniqueRows.push(pendingLabelRow)
      pendingLabelRow = null
    }
    uniqueRows.push(row)
  }
  if (pendingLabelRow) uniqueRows.push(pendingLabelRow)
  return uniqueRows.length > 0 ? uniqueRows : null
}

/** GFM 표 유닛 파싱 — 구분 행 제거, 이스케이프된 파이프 보존 분할 */
export function parseGfmTable(lines: string[]): string[][] {
  const rows: string[][] = []
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed.startsWith("|")) continue
    // 이스케이프되지 않은 | 로만 분할
    const cells = trimmed.split(/(?<!\\)\|/).slice(1, -1).map(c => c.trim())
    if (cells.length === 0) continue
    // 구분 행 — builder는 셀당 '---'만 방출. '| - | - |' 같은 단일 대시 데이터 행
    // ('해당없음' 표기)을 구분 행으로 오인하지 않도록 셀 패턴으로 판정
    if (cells.every(c => /^:?-{3,}:?$/.test(c))) continue
    rows.push(cells)
  }
  return rows
}

/** GFM 셀 텍스트 → 평문 */
export function unescapeGfmCell(text: string): string {
  return text.replace(/<br\s*\/?>/gi, "\n").replace(/\\\|/g, "|").replace(/\\~/g, "~")
}

// ─── HTML 표 — 좌표 추적 렌더 재현 + 파서 ───────────

export interface HtmlCellInfo {
  /** 태그 안 콘텐츠 원문 */
  inner: string
  colSpan: number
  rowSpan: number
  /** 재현 시에만: 격자 좌표 */
  gridR?: number
  gridC?: number
}

/** 셀 내부 콘텐츠 → HTML — builder.ts cellInnerHtml과 동일 */
function replicateCellInnerHtml(cell: IRTable["cells"][number][number]): string {
  if (cell.blocks?.length) {
    return cell.blocks
      .map(b => {
        if (b.type === "table" && b.table) {
          const cap = b.table.caption ? sanitizeText(b.table.caption) : ""
          return (cap ? cap + "<br>" : "") + replicateTableToHtml(b.table)
        }
        if (b.type === "image" && b.text) return `<img src="${b.text}" alt="image">`
        const t = sanitizeText(b.text ?? "")
        return t ? t.replace(/\n/g, "<br>") : ""
      })
      .filter(Boolean)
      .join("<br>")
  }
  return sanitizeText(cell.text).replace(/\n/g, "<br>")
}

/** builder.ts tableToHtml과 동일한 문자열 출력 (자기 검증용) */
export function replicateTableToHtml(table: IRTable): string {
  const rows = replicateHtmlTable(table)
  const lines: string[] = ["<table>"]
  for (let r = 0; r < rows.length; r++) {
    const tag = rows[r].tag
    const rowHtml = rows[r].cells.map(cell => {
      const attrs: string[] = []
      if (cell.colSpan > 1) attrs.push(`colspan="${cell.colSpan}"`)
      if (cell.rowSpan > 1) attrs.push(`rowspan="${cell.rowSpan}"`)
      const attrStr = attrs.length ? " " + attrs.join(" ") : ""
      return `<${tag}${attrStr}>${cell.inner}</${tag}>`
    })
    if (rowHtml.length) lines.push(`<tr>${rowHtml.join("")}</tr>`)
  }
  lines.push("</table>")
  return lines.join("\n")
}

export interface HtmlRowInfo {
  tag: "th" | "td"
  cells: HtmlCellInfo[]
}

/** builder.ts tableToHtml의 셀 방출 순서 재현 — 좌표 포함 */
export function replicateHtmlTable(table: IRTable): HtmlRowInfo[] {
  const { cells, rows: numRows, cols: numCols } = table
  const skip = new Set<string>()
  const result: HtmlRowInfo[] = []

  for (let r = 0; r < numRows; r++) {
    const tag = r === 0 ? "th" : "td"
    const rowCells: HtmlCellInfo[] = []
    for (let c = 0; c < numCols; c++) {
      if (skip.has(`${r},${c}`)) continue
      const cell = cells[r]?.[c]
      if (!cell) continue
      for (let dr = 0; dr < cell.rowSpan; dr++) {
        for (let dc = 0; dc < cell.colSpan; dc++) {
          if (dr === 0 && dc === 0) continue
          if (r + dr < numRows && c + dc < numCols) skip.add(`${r + dr},${c + dc}`)
        }
      }
      rowCells.push({
        inner: replicateCellInnerHtml(cell),
        colSpan: cell.colSpan,
        rowSpan: cell.rowSpan,
        gridR: r,
        gridC: c,
      })
    }
    if (rowCells.length) result.push({ tag, cells: rowCells })
  }
  return result
}

/**
 * HTML 표 유닛 파싱 — 중첩 <table> 인지 토크나이저.
 * 최상위 표의 <tr>/<td|th>만 행/셀로 취급하고 중첩 표는 셀 inner에 원문 보존.
 */
export function parseHtmlTable(raw: string): HtmlRowInfo[] | null {
  const re = /<(\/?)(table|tr|td|th)((?:"[^"]*"|'[^']*'|[^>"'])*?)>/gi
  let depth = 0
  let currentRow: HtmlCellInfo[] | null = null
  let cellStart = -1
  let cellInfo: { colSpan: number; rowSpan: number } | null = null
  const rows: HtmlRowInfo[] = []
  let m: RegExpExecArray | null

  while ((m = re.exec(raw)) !== null) {
    const isClose = m[1] === "/"
    const tag = m[2].toLowerCase()
    const attrs = m[3] || ""

    if (tag === "table") {
      depth += isClose ? -1 : 1
      if (depth < 0) return null
      continue
    }
    if (depth !== 1) continue // 중첩 표 내부는 inner 원문으로 흡수

    if (tag === "tr") {
      if (!isClose) currentRow = []
      else if (currentRow) {
        rows.push({ tag: rows.length === 0 ? "th" : "td", cells: currentRow })
        currentRow = null
      }
    } else { // td | th
      if (!isClose) {
        const cs = parseInt(attrs.match(/colspan\s*=\s*"(\d+)"/i)?.[1] || "1", 10)
        const rs = parseInt(attrs.match(/rowspan\s*=\s*"(\d+)"/i)?.[1] || "1", 10)
        cellStart = m.index + m[0].length
        cellInfo = { colSpan: isNaN(cs) ? 1 : cs, rowSpan: isNaN(rs) ? 1 : rs }
      } else if (cellStart >= 0 && cellInfo && currentRow) {
        currentRow.push({ inner: raw.slice(cellStart, m.index), colSpan: cellInfo.colSpan, rowSpan: cellInfo.rowSpan })
        cellStart = -1
        cellInfo = null
      }
    }
  }
  if (depth !== 0) return null
  return rows
}

/** HTML 셀 inner → 평문 라인 — <br> 분리, <img>/중첩표 토큰 제외 */
export function htmlCellInnerToLines(inner: string): { lines: string[]; hadNonText: boolean } {
  let hadNonText = false
  let work = inner
  if (/<table[\s>]/i.test(work)) {
    hadNonText = true
    // 중첩 표 통째 제거 (짝 맞는 닫힘까지)
    work = removeNestedTables(work)
  }
  if (/<img\s/i.test(work)) {
    hadNonText = true
    work = work.replace(/<img\s(?:"[^"]*"|'[^']*'|[^>"'])*?>/gi, "")
  }
  const lines = work.split(/<br\s*\/?>/gi).map(s => s.trim()).filter(s => s.length > 0)
  return { lines, hadNonText }
}

/** 셀 inner의 최상위 <table>...</table> 부분문자열들 (문서 순서, 짝 맞는 닫힘까지) */
export function extractTopLevelTables(html: string): string[] {
  const result: string[] = []
  let depth = 0
  let start = -1
  const re = /<(\/?)table(?:[\s>]|>)/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    if (m[1] !== "/") {
      if (depth === 0) start = m.index
      depth++
    } else {
      depth--
      if (depth === 0 && start >= 0) {
        result.push(html.slice(start, m.index + m[0].length))
        start = -1
      }
      if (depth < 0) depth = 0
    }
  }
  return result
}

function removeNestedTables(html: string): string {
  let result = ""
  let depth = 0
  const re = /<(\/?)table(?:[\s>]|>)/gi
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    if (m[1] !== "/") {
      if (depth === 0) result += html.slice(last, m.index)
      depth++
    } else {
      depth--
      if (depth === 0) last = m.index + m[0].length
      if (depth < 0) depth = 0
    }
  }
  if (depth === 0) result += html.slice(last)
  return result
}
