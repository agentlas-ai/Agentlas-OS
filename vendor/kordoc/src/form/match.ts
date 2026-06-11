/** 양식 필드 매칭 공용 유틸 — filler.ts, filler-hwpx.ts에서 공유 */

import { LABEL_KEYWORDS } from "./recognize.js"

/** 라벨 정규화 — 콜론/공백/특수문자 제거, 비교용 */
export function normalizeLabel(label: string): string {
  return label.trim().replace(/[:：\s()（）·]/g, "")
}

/**
 * 정규화된 셀 라벨과 입력 값 맵에서 최적 매칭 키를 찾음.
 *
 * 매칭 우선순위:
 * 1. 정확 매칭 (normalizedCellLabel === key)
 * 2. 접두사 기반 매칭 (60% 이상 겹침 필요)
 */
export function findMatchingKey(
  cellLabel: string,
  values: Map<string, string>,
): string | undefined {
  // 1) 정확 매칭
  if (values.has(cellLabel)) return cellLabel

  // 2) 접두사 기반 매칭 — 가장 긴 매칭 우선 (= 가장 구체적)
  //    단, 길이 비율 60% 이상 겹쳐야 매칭 (오탐 방지)
  let bestKey: string | undefined
  let bestLen = 0

  for (const key of values.keys()) {
    if (cellLabel.startsWith(key)) {
      if (key.length >= cellLabel.length * 0.6 && key.length > bestLen) {
        bestLen = key.length
        bestKey = key
      }
    } else if (key.startsWith(cellLabel)) {
      if (cellLabel.length >= key.length * 0.6 && cellLabel.length > bestLen) {
        bestLen = cellLabel.length
        bestKey = key
      }
    }
  }

  return bestKey
}

/**
 * 값 셀이 키워드 라벨(섹션 헤더의 하위 라벨)인지 판별.
 * "성명", "주소" 같은 키워드 라벨이면 true → 스킵 대상.
 * "(한자：)" 같은 어노테이션이면 false → 채울 수 있음.
 */
export function isKeywordLabel(text: string): boolean {
  const trimmed = text.trim().replace(/[¹²³⁴⁵⁶⁷⁸⁹⁰*※]+$/g, "").trim()
  if (!trimmed || trimmed.length > 15) return false
  for (const kw of LABEL_KEYWORDS) {
    if (trimmed.includes(kw)) return true
  }
  return false
}

/**
 * 셀 텍스트에서 인셀 패턴을 찾아 교체 — 체크박스 + 괄호 빈칸.
 *
 * 지원 패턴:
 * 1. 괄호 빈칸: `일반(  )통` → 키 "일반통" 또는 "일반" 매칭 시 → `일반(값)통`
 * 2. 체크박스: `□부` → 키 "부" 매칭 시 → `☑부` (값이 "☑","✓","v","V","true","1" 등)
 *
 * @returns 교체된 텍스트 + 매칭된 키 목록. null이면 교체 없음.
 */
export function fillInCellPatterns(
  cellText: string,
  values: Map<string, string>,
  matchedLabels: Set<string>,
): { text: string; matches: Array<{ key: string; label: string; value: string }> } | null {
  let text = cellText
  const matches: Array<{ key: string; label: string; value: string }> = []

  // 1) 괄호 빈칸: keyword(\s+)suffix → keyword(value)suffix
  text = text.replace(
    /([가-힣A-Za-z]+)\(\s{1,}\)([가-힣A-Za-z]*)/g,
    (match, prefix: string, suffix: string) => {
      const label = prefix + suffix  // "일반" + "통" = "일반통"
      const normalizedLabel = normalizeLabel(label)
      // 정확 매칭 → 접두사만 매칭 순
      const matchKey = values.has(normalizedLabel)
        ? normalizedLabel
        : values.has(normalizeLabel(prefix))
          ? normalizeLabel(prefix)
          : undefined
      if (matchKey === undefined) return match

      const newValue = values.get(matchKey)!
      matchedLabels.add(matchKey)
      matches.push({ key: matchKey, label, value: newValue })
      return `${prefix}(${newValue})${suffix}`
    },
  )

  // 2) 체크박스: □keyword → ☑keyword (값이 truthy)
  text = text.replace(
    /□([가-힣A-Za-z]+)/g,
    (match, keyword: string) => {
      const normalizedKw = normalizeLabel(keyword)
      const matchKey = values.has(normalizedKw) ? normalizedKw : undefined
      if (matchKey === undefined) return match

      const val = values.get(matchKey)!
      const isTruthy = ["☑", "✓", "✔", "v", "V", "true", "1", "yes", "o", "O"].includes(val.trim()) || val.trim() === ""
      if (!isTruthy) return match

      matchedLabels.add(matchKey)
      matches.push({ key: matchKey, label: `□${keyword}`, value: "☑" })
      return `☑${keyword}`
    },
  )

  // 3) 어노테이션 빈칸: (keyword：\s+) → (keyword：value)
  //    예: "(한자：                  )" → "(한자：金民秀)"
  //    예: "(성명:        )" → "(성명: 홍길동)"
  text = text.replace(
    /\(([가-힣A-Za-z]+)[:：]\s{1,}\)/g,
    (match, keyword: string) => {
      const normalizedKw = normalizeLabel(keyword)
      const matchKey = values.has(normalizedKw) ? normalizedKw : undefined
      if (matchKey === undefined) return match

      const newValue = values.get(matchKey)!
      matchedLabels.add(matchKey)
      matches.push({ key: matchKey, label: keyword, value: newValue })
      return `(${keyword}：${newValue})`
    },
  )

  return matches.length > 0 ? { text, matches } : null
}

/** 입력 values 맵을 정규화된 키로 변환 */
export function normalizeValues(values: Record<string, string>): Map<string, string> {
  const map = new Map<string, string>()
  for (const [label, value] of Object.entries(values)) {
    map.set(normalizeLabel(label), value)
  }
  return map
}

/** 매칭 안 된 라벨을 원본 키로 복원 */
export function resolveUnmatched(
  normalizedValues: Map<string, string>,
  matchedLabels: Set<string>,
  originalValues: Record<string, string>,
): string[] {
  return [...normalizedValues.keys()]
    .filter(k => !matchedLabels.has(k))
    .map(k => {
      for (const orig of Object.keys(originalValues)) {
        if (normalizeLabel(orig) === k) return orig
      }
      return k
    })
}
