/** 페이지/섹션 범위 파싱 유틸리티 */

/**
 * 페이지 범위 지정을 1-based Set<number>로 변환.
 *
 * @param spec - [1,2,3] 또는 "1-3" 또는 "1,3,5-7"
 * @param maxPages - 최대 페이지 수 (클램핑 상한)
 * @returns 1-based 페이지 번호 Set
 */
export function parsePageRange(spec: number[] | string, maxPages: number): Set<number> {
  const result = new Set<number>()
  if (maxPages <= 0) return result

  if (Array.isArray(spec)) {
    for (const n of spec) {
      const page = Math.round(n)
      if (page >= 1 && page <= maxPages) result.add(page)
    }
    return result
  }

  if (typeof spec !== "string" || spec.trim() === "") return result

  const parts = spec.split(",")
  for (const part of parts) {
    const trimmed = part.trim()
    if (!trimmed) continue

    const rangeMatch = trimmed.match(/^(\d+)\s*-\s*(\d+)$/)
    if (rangeMatch) {
      const start = Math.max(1, parseInt(rangeMatch[1], 10))
      const end = Math.min(maxPages, parseInt(rangeMatch[2], 10))
      for (let i = start; i <= end; i++) result.add(i)
    } else {
      const page = parseInt(trimmed, 10)
      if (!isNaN(page) && page >= 1 && page <= maxPages) result.add(page)
    }
  }

  return result
}
