/** 양식 서식 필드 값 채우기 — IRBlock[] 기반 in-place 교체 */

import type { IRBlock, IRTable, FormField } from "../types.js"
import { isLabelCell } from "./recognize.js"
import { normalizeLabel, findMatchingKey, normalizeValues, resolveUnmatched, isKeywordLabel, fillInCellPatterns } from "./match.js"

/** 필드 채우기 결과 */
export interface FillResult {
  /** 값이 교체된 IRBlock[] */
  blocks: IRBlock[]
  /** 실제 채워진 필드 목록 */
  filled: FormField[]
  /** 매칭 실패한 라벨 (입력에는 있지만 서식에서 못 찾은 것) */
  unmatched: string[]
}

/**
 * IRBlock[]에서 양식 필드를 찾아 값을 교체.
 *
 * @param blocks 원본 IRBlock[] (변경하지 않음 — deep clone)
 * @param values 채울 값 맵 (라벨 → 새 값). 라벨은 접두사 매칭 지원.
 * @returns FillResult
 *
 * @example
 * ```ts
 * const result = await parse("신청서.hwp")
 * if (!result.success) throw new Error(result.error)
 * const { blocks, filled } = fillFormFields(result.blocks, {
 *   "성명": "홍길동",
 *   "전화번호": "010-1234-5678",
 *   "주소": "서울시 강남구",
 * })
 * ```
 */
export function fillFormFields(
  blocks: IRBlock[],
  values: Record<string, string>,
): FillResult {
  // deep clone — 원본 불변
  const cloned = structuredClone(blocks)
  const filled: FormField[] = []
  const matchedLabels = new Set<string>()

  const normalizedValues = normalizeValues(values)

  // 1) 인셀 패턴 먼저 (체크박스, 괄호 빈칸, 어노테이션) — 전략 2가 덮어쓰기 전에
  const patternFilledCells = new Set<string>()  // "r,c" 키
  for (const block of cloned) {
    if (block.type !== "table" || !block.table) continue
    for (let r = 0; r < block.table.rows; r++) {
      for (let c = 0; c < block.table.cols; c++) {
        const cell = block.table.cells[r]?.[c]
        if (!cell) continue
        const result = fillInCellPatterns(cell.text, normalizedValues, matchedLabels)
        if (result) {
          cell.text = result.text
          patternFilledCells.add(`${r},${c}`)
          for (const m of result.matches) {
            filled.push({ label: m.label, value: m.value, row: r, col: c })
          }
        }
      }
    }
  }

  // 2) 테이블 기반 필드 교체 (라벨-값 셀 패턴)
  for (const block of cloned) {
    if (block.type !== "table" || !block.table) continue
    fillTable(block.table, normalizedValues, filled, matchedLabels, patternFilledCells)
  }

  // 3) 인라인 "라벨: 값" 패턴 교체
  for (const block of cloned) {
    if (block.type !== "paragraph" || !block.text) continue
    const newText = fillInlineFields(block.text, normalizedValues, filled, matchedLabels)
    if (newText !== block.text) block.text = newText
  }

  const unmatched = resolveUnmatched(normalizedValues, matchedLabels, values)
  return { blocks: cloned, filled, unmatched }
}

/** 테이블 셀에서 라벨-값 패턴을 찾아 값 교체 */
function fillTable(
  table: IRTable,
  values: Map<string, string>,
  filled: FormField[],
  matchedLabels: Set<string>,
  patternFilledCells?: Set<string>,
): void {
  if (table.cols < 2) return

  // 전략 1: 인접 라벨-값 셀 패턴
  for (let r = 0; r < table.rows; r++) {
    for (let c = 0; c < table.cols - 1; c++) {
      const labelCell = table.cells[r][c]
      const valueCell = table.cells[r][c + 1]
      if (!labelCell || !valueCell) continue

      if (!isLabelCell(labelCell.text)) continue

      if (isKeywordLabel(valueCell.text)) continue

      const normalizedCellLabel = normalizeLabel(labelCell.text)
      if (!normalizedCellLabel) continue

      const matchKey = findMatchingKey(normalizedCellLabel, values)
      if (matchKey === undefined) continue

      const newValue = values.get(matchKey)!
      // 이미 인셀 패턴이 처리된 셀이면 앞에 삽입 (어노테이션 보존)
      if (patternFilledCells?.has(`${r},${c + 1}`)) {
        valueCell.text = newValue + " " + valueCell.text
      } else {
        valueCell.text = newValue
      }
      matchedLabels.add(matchKey)
      filled.push({
        label: labelCell.text.trim().replace(/[:：]\s*$/, ""),
        value: newValue,
        row: r,
        col: c,
      })
    }
  }

  // 전략 2: 헤더+데이터 행 패턴 (첫 행이 전부 라벨이면)
  // 전략 1에서 이미 채운 필드는 스킵 (matchedLabels 검사)
  if (table.rows >= 2 && table.cols >= 2) {
    const headerRow = table.cells[0]
    const allLabels = headerRow.every(cell => {
      const t = cell.text.trim()
      return t.length > 0 && t.length <= 20 && isLabelCell(t)
    })
    if (!allLabels) return

    for (let r = 1; r < table.rows; r++) {
      for (let c = 0; c < table.cols; c++) {
        const headerLabel = normalizeLabel(headerRow[c].text)
        const matchKey = findMatchingKey(headerLabel, values)
        if (matchKey === undefined) continue
        if (matchedLabels.has(matchKey)) continue

        const newValue = values.get(matchKey)!
        table.cells[r][c].text = newValue
        matchedLabels.add(matchKey)
        filled.push({
          label: headerRow[c].text.trim(),
          value: newValue,
          row: r,
          col: c,
        })
      }
    }
  }
}

/** 인라인 "라벨: 값" 패턴 교체 */
function fillInlineFields(
  text: string,
  values: Map<string, string>,
  filled: FormField[],
  matchedLabels: Set<string>,
): string {
  return text.replace(
    /([가-힣A-Za-z]{2,10})\s*[:：]\s*([^\n,;]{0,100})/g,
    (match, rawLabel: string, _oldValue: string) => {
      const normalized = normalizeLabel(rawLabel)
      const matchKey = findMatchingKey(normalized, values)
      if (matchKey === undefined) return match

      const newValue = values.get(matchKey)!
      matchedLabels.add(matchKey)
      filled.push({
        label: rawLabel.trim(),
        value: newValue,
        row: -1,
        col: -1,
      })
      return `${rawLabel}: ${newValue}`
    },
  )
}
