/**
 * PDF 페이지별 텍스트 품질 신호 수집.
 *
 * pdfjs가 텍스트층을 추출했더라도, 폰트의 ToUnicode/CMap이 불완전하면
 * 한글이 PUA(Private Use Area) 글리프 코드로 그대로 떨어진다. 또 일부 PDF는
 * NUL/제어문자가 본문에 섞여 있다. 본 모듈은 그런 신호를 페이지 단위로 수집해
 * "OCR 검토 필요" 판정에 사용한다.
 */

export interface PageQuality {
  /** 1-based 페이지 번호 */
  page: number
  /** 공백 제외 문자 수 */
  textChars: number
  /** 한글 음절(0xAC00-0xD7A3) 비율 (0~1) */
  hangulRatio: number
  /** C0/C1 제어문자 비율 (tab/newline/CR 제외) */
  controlCharRatio: number
  /** U+FFFD replacement character 비율 */
  replacementCharRatio: number
  /** PUA 비율 — 글꼴 매핑 실패의 핵심 신호 */
  puaRatio: number
  /** OCR 검토 권장 여부 */
  needsOcr: boolean
  /** needsOcr=true일 때 사유 (단일 신호로 충분, 가장 강한 신호 선택) */
  ocrReason?: "low_text" | "high_pua" | "high_control" | "high_replacement"
}

/** 페이지 텍스트에서 품질 메트릭을 계산한다. */
export function computePageQuality(page: number, text: string): PageQuality {
  let total = 0
  let hangul = 0
  let control = 0
  let replacement = 0
  let pua = 0

  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i)
    // 공백류는 분모에서 제외
    if (code === 0x20 || code === 0x09 || code === 0x0a || code === 0x0d) continue
    total++

    // C0 제어문자 (0x00-0x1F 중 tab/lf/cr 제외) + DEL(0x7F) + C1(0x80-0x9F)
    if ((code < 0x20) || code === 0x7f || (code >= 0x80 && code <= 0x9f)) {
      control++
      continue
    }
    if (code === 0xfffd) {
      replacement++
      continue
    }
    // 한글 음절
    if (code >= 0xac00 && code <= 0xd7a3) {
      hangul++
      continue
    }
    // PUA: BMP(E000-F8FF) + SPUA-A(F0000-FFFFD) + SPUA-B(100000-10FFFD)
    // 서로게이트 페어는 high만 검사해도 충분 (Plane 15/16 high surrogate 범위 DB80-DBFF)
    if ((code >= 0xe000 && code <= 0xf8ff) || (code >= 0xdb80 && code <= 0xdbff)) {
      pua++
      continue
    }
  }

  const denom = total || 1
  const puaRatio = pua / denom
  const controlCharRatio = control / denom
  const replacementCharRatio = replacement / denom

  let needsOcr = false
  let ocrReason: PageQuality["ocrReason"] | undefined
  // 우선순위: low_text > high_pua > high_control > high_replacement
  if (total < LOW_TEXT_THRESHOLD) { needsOcr = true; ocrReason = "low_text" }
  else if (puaRatio >= HIGH_PUA_THRESHOLD) { needsOcr = true; ocrReason = "high_pua" }
  else if (controlCharRatio >= HIGH_CONTROL_THRESHOLD) { needsOcr = true; ocrReason = "high_control" }
  else if (replacementCharRatio >= HIGH_REPLACEMENT_THRESHOLD) { needsOcr = true; ocrReason = "high_replacement" }

  return {
    page,
    textChars: total,
    hangulRatio: hangul / denom,
    controlCharRatio,
    replacementCharRatio,
    puaRatio,
    needsOcr,
    ocrReason,
  }
}

/** 페이지별 품질에서 문서 단위 요약을 계산한다. */
export interface DocumentQualitySummary {
  totalPages: number
  totalTextChars: number
  avgHangulRatio: number
  avgControlCharRatio: number
  avgReplacementCharRatio: number
  avgPuaRatio: number
  /** textChars 매우 적은 페이지 수 (이미지/빈 페이지 후보) */
  lowTextPageCount: number
  /** PUA 비율 임계 초과 페이지 수 (글꼴 매핑 깨짐 후보) */
  highPuaPageCount: number
  /** 문서 전체에 OCR 검토가 권장되는지 — needsOcr 페이지 비율 또는 평균 신호 기반 */
  needsOcr: boolean
  /** needsOcr=true인 페이지 번호 목록 */
  ocrCandidatePages: number[]
}

const LOW_TEXT_THRESHOLD = 20
const HIGH_PUA_THRESHOLD = 0.2
const HIGH_CONTROL_THRESHOLD = 0.05
const HIGH_REPLACEMENT_THRESHOLD = 0.05
/** 페이지 중 needsOcr 비율이 이 값 이상이면 문서 전체에 OCR 권장 */
const DOC_NEEDS_OCR_PAGE_RATIO = 0.3

/**
 * 비표시 제어문자를 제거한다. C0(NUL 등, tab/lf/cr 제외) + DEL + C1.
 * PUA는 사용자가 글꼴 매핑 실패를 시각적으로 확인할 수 있도록 보존.
 */
export function stripControlChars(text: string): string {
  // eslint-disable-next-line no-control-regex
  return text.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\x80-\x9F]/g, "")
}

export function summarizeDocumentQuality(pages: PageQuality[]): DocumentQualitySummary {
  if (pages.length === 0) {
    return {
      totalPages: 0,
      totalTextChars: 0,
      avgHangulRatio: 0,
      avgControlCharRatio: 0,
      avgReplacementCharRatio: 0,
      avgPuaRatio: 0,
      lowTextPageCount: 0,
      highPuaPageCount: 0,
      needsOcr: false,
      ocrCandidatePages: [],
    }
  }

  let textChars = 0
  let hangul = 0
  let control = 0
  let replacement = 0
  let pua = 0
  let lowText = 0
  let highPua = 0
  const ocrCandidatePages: number[] = []

  for (const p of pages) {
    textChars += p.textChars
    hangul += p.hangulRatio
    control += p.controlCharRatio
    replacement += p.replacementCharRatio
    pua += p.puaRatio
    if (p.textChars < LOW_TEXT_THRESHOLD) lowText++
    if (p.puaRatio >= HIGH_PUA_THRESHOLD) highPua++
    if (p.needsOcr) ocrCandidatePages.push(p.page)
  }

  const n = pages.length
  return {
    totalPages: n,
    totalTextChars: textChars,
    avgHangulRatio: hangul / n,
    avgControlCharRatio: control / n,
    avgReplacementCharRatio: replacement / n,
    avgPuaRatio: pua / n,
    lowTextPageCount: lowText,
    highPuaPageCount: highPua,
    needsOcr: ocrCandidatePages.length / n >= DOC_NEEDS_OCR_PAGE_RATIO,
    ocrCandidatePages,
  }
}
