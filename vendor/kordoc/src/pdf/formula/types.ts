/**
 * PDF 수식 OCR 공통 타입
 *
 * 파이프라인:
 *   PDF 페이지 → PDFium 렌더 (RGBA) → MFD (YOLOv8) → 수식 영역(BBox)
 *     → 각 영역 crop → MFR (DeiT encoder + TrOCR decoder) → LaTeX
 *     → post-process → $...$ / $$...$$ 래핑
 *
 * 모델 출처: breezedeus/pix2text-mfd (Apache 2.0), breezedeus/pix2text-mfr (MIT)
 */

export type FormulaKind = "inline" | "display"

/** 단일 수식 영역 + 인식 결과 */
export interface FormulaRegion {
  /** 원본 이미지 좌표계 기준 bbox (x1, y1, x2, y2) */
  bbox: { x1: number; y1: number; x2: number; y2: number }
  /** 수식 종류 (inline = `$...$`, display = `$$...$$`) */
  kind: FormulaKind
  /** YOLO confidence */
  score: number
  /** 인식된 LaTeX (빈 문자열이면 인식 실패) */
  latex: string
}

/** 페이지 단위 결과 */
export interface FormulaPageResult {
  pageNumber: number
  regions: FormulaRegion[]
}

/** RGBA 픽셀 버퍼 + 크기 */
export interface PixelFrame {
  width: number
  height: number
  /** RGBA8 (4 bytes per pixel, row-major) */
  data: Uint8Array
}
