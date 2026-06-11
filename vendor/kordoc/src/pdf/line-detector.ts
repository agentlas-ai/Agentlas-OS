/**
 * PDF 그래픽 명령에서 수평/수직 선을 추출하고,
 * 선 교차점(Vertex) 기반으로 테이블 그리드를 구성하는 모듈.
 *
 * 이 파일의 테이블 감지 알고리즘은 OpenDataLoader PDF의
 * TableBorderBuilder / LinesPreprocessingConsumer를 참고하여
 * TypeScript로 clean-room 재구현한 것입니다.
 *
 * v2: Vertex 기반 동적 tolerance, 선 전처리 파이프라인,
 *     정밀 병합 셀 감지 (ODL 알고리즘 충실 포팅)
 *
 * Original algorithm: Copyright 2025-2026 Hancom, Inc. (Apache 2.0)
 * https://github.com/opendataloader-project/opendataloader-pdf
 * Core algorithm concepts from veraPDF-wcag-algs (GPLv3+/MPLv2+)
 * This is an independent clean-room reimplementation in TypeScript.
 */

import { OPS } from "pdfjs-dist/legacy/build/pdf.mjs"

// ─── pdfjs-dist v5 DrawOPS ──
const enum DrawOPS {
  moveTo = 0,
  lineTo = 1,
  curveTo = 2,
  quadraticCurveTo = 3,
  closePath = 4,
}

// ─── 타입 ─────────────────────────────────────────────

export interface LineSegment {
  x1: number; y1: number
  x2: number; y2: number
  lineWidth: number
}

/** 선 교차점 (Vertex) — ODL의 핵심 개념 */
interface Vertex {
  x: number
  y: number
  /** 교차하는 선들의 최대 lineWidth → tolerance 계산에 사용 */
  radius: number
}

export interface TableGrid {
  /** 행 Y 좌표 경계 (위→아래 내림차순) */
  rowYs: number[]
  /** 열 X 좌표 경계 (좌→우 오름차순) */
  colXs: number[]
  /** 테이블 바운딩 박스 */
  bbox: { x1: number; y1: number; x2: number; y2: number }
  /** 그리드 내 교차점 반경 (동적 tolerance용) */
  vertexRadius: number
}

export interface ExtractedCell {
  row: number; col: number
  rowSpan: number; colSpan: number
  /** 셀 바운딩 박스 */
  bbox: { x1: number; y1: number; x2: number; y2: number }
}

// ─── 상수 ─────────────────────────────────────────────

/** 수평/수직 판별 허용 오차 (pt) */
const ORIENTATION_TOL = 2
/** 최소 선 길이 — 짧은 장식선(체크박스 테두리 등) 무시 */
const MIN_LINE_LENGTH = 15
/** 굵은 선 필터 — ODL: MAX_LINE_WIDTH = 5.0 (배경 채움/장식 사각형 제외) */
const MAX_LINE_WIDTH = 5.0
/** 두 선이 같은 테이블에 속하는지 판별하는 거리 */
const CONNECT_TOL = 5
/** 셀 경계 내부 판별 여유 (텍스트 매핑용) */
const CELL_PADDING = 2
/** 최소 열 폭 (pt) — 이보다 좁은 열은 인접 열과 병합 */
const MIN_COL_WIDTH = 15
/** 최소 행 높이 (pt) */
const MIN_ROW_HEIGHT = 6
/** Vertex 기반 좌표 병합 시 radius 배수 — ODL: VERTEX_TABLE_FACTOR */
const VERTEX_MERGE_FACTOR = 4
/** 좌표 병합 최소 tolerance (pt) — vertexRadius가 작아도 이 값 이하로 내려가지 않음 */
const MIN_COORD_MERGE_TOL = 8

// ─── 선 추출 ──────────────────────────────────────────

/**
 * pdfjs operatorList에서 수평/수직 선을 추출.
 * constructPath(91) 내의 moveTo→lineTo, rectangle 패턴을 인식.
 */
export function extractLines(
  fnArray: Uint32Array | number[],
  argsArray: unknown[][],
): { horizontals: LineSegment[]; verticals: LineSegment[] } {
  const horizontals: LineSegment[] = []
  const verticals: LineSegment[] = []
  let lineWidth = 1

  let currentPath: Array<{ x1: number; y1: number; x2: number; y2: number }> = []
  let pathStartX = 0, pathStartY = 0
  let curX = 0, curY = 0

  function pushRectangle(
    path: Array<{ x1: number; y1: number; x2: number; y2: number }>,
    rx: number, ry: number, rw: number, rh: number,
  ) {
    if (Math.abs(rh) < ORIENTATION_TOL * 2) {
      path.push({ x1: rx, y1: ry + rh / 2, x2: rx + rw, y2: ry + rh / 2 })
    } else if (Math.abs(rw) < ORIENTATION_TOL * 2) {
      path.push({ x1: rx + rw / 2, y1: ry, x2: rx + rw / 2, y2: ry + rh })
    } else {
      path.push(
        { x1: rx, y1: ry, x2: rx + rw, y2: ry },
        { x1: rx + rw, y1: ry, x2: rx + rw, y2: ry + rh },
        { x1: rx + rw, y1: ry + rh, x2: rx, y2: ry + rh },
        { x1: rx, y1: ry + rh, x2: rx, y2: ry },
      )
    }
  }

  function flushPath(isStroke: boolean) {
    if (!isStroke) { currentPath = []; return }
    for (const seg of currentPath) {
      classifyAndAdd(seg, lineWidth, horizontals, verticals)
    }
    currentPath = []
  }

  for (let i = 0; i < fnArray.length; i++) {
    const op = fnArray[i]
    const args = argsArray[i]

    switch (op) {
      case OPS.setLineWidth:
        lineWidth = (args as number[])[0] || 1
        break

      case OPS.constructPath: {
        const arg0 = args[0]

        if (Array.isArray(arg0)) {
          // ── pdfjs-dist v4 형식 ──
          const subOps = arg0 as number[]
          const coords = (args as [number[], number[]])[1]
          let ci = 0

          for (const subOp of subOps) {
            if (subOp === OPS.moveTo) {
              curX = coords[ci++]; curY = coords[ci++]
              pathStartX = curX; pathStartY = curY
            } else if (subOp === OPS.lineTo) {
              const x2 = coords[ci++], y2 = coords[ci++]
              currentPath.push({ x1: curX, y1: curY, x2, y2 })
              curX = x2; curY = y2
            } else if (subOp === OPS.rectangle) {
              const rx = coords[ci++], ry = coords[ci++]
              const rw = coords[ci++], rh = coords[ci++]
              pushRectangle(currentPath, rx, ry, rw, rh)
            } else if (subOp === OPS.closePath) {
              if (curX !== pathStartX || curY !== pathStartY) {
                currentPath.push({ x1: curX, y1: curY, x2: pathStartX, y2: pathStartY })
              }
              curX = pathStartX; curY = pathStartY
            } else if (subOp === OPS.curveTo) {
              ci += 6
            } else if (subOp === OPS.curveTo2 || subOp === OPS.curveTo3) {
              ci += 4
            }
          }
        } else {
          // ── pdfjs-dist v5 형식 ──
          const afterOp = arg0 as number
          const dataArr = args[1] as unknown[]
          const pathData = dataArr?.[0] as Record<number, number> | undefined
          if (pathData && typeof pathData === "object") {
            const len = Object.keys(pathData).length
            let di = 0
            while (di < len) {
              const drawOp = pathData[di++]
              if (drawOp === DrawOPS.moveTo) {
                curX = pathData[di++]; curY = pathData[di++]
                pathStartX = curX; pathStartY = curY
              } else if (drawOp === DrawOPS.lineTo) {
                const x2 = pathData[di++], y2 = pathData[di++]
                currentPath.push({ x1: curX, y1: curY, x2, y2 })
                curX = x2; curY = y2
              } else if (drawOp === DrawOPS.curveTo) {
                di += 6
              } else if (drawOp === DrawOPS.quadraticCurveTo) {
                di += 4
              } else if (drawOp === DrawOPS.closePath) {
                if (curX !== pathStartX || curY !== pathStartY) {
                  currentPath.push({ x1: curX, y1: curY, x2: pathStartX, y2: pathStartY })
                }
                curX = pathStartX; curY = pathStartY
              } else {
                break
              }
            }
          }

          if (afterOp === OPS.stroke || afterOp === OPS.closeStroke) {
            flushPath(true)
          } else if (afterOp === OPS.fill || afterOp === OPS.eoFill ||
                     afterOp === OPS.fillStroke || afterOp === OPS.eoFillStroke ||
                     afterOp === OPS.closeFillStroke || afterOp === OPS.closeEOFillStroke) {
            flushPath(true)
          } else if (afterOp === OPS.endPath) {
            flushPath(false)
          }
        }
        break
      }

      case OPS.stroke:
      case OPS.closeStroke:
        flushPath(true)
        break

      case OPS.fill:
      case OPS.eoFill:
      case OPS.fillStroke:
      case OPS.eoFillStroke:
      case OPS.closeFillStroke:
      case OPS.closeEOFillStroke:
        flushPath(true)
        break

      case OPS.endPath:
        flushPath(false)
        break
    }
  }

  return { horizontals, verticals }
}

// ─── 이미지 영역 추출 (정보손실 가시화용) ─────────────

/** 페이지 내 이미지 XObject가 그려진 영역 (PDF 사용자 공간 좌표) */
export interface ImageRegion {
  x1: number; y1: number; x2: number; y2: number
}

/** 2D 어파인 행렬 곱 — t 적용 후 m 적용 (pdfjs Util.transform과 동일 순서) */
function multiplyTransform(m: number[], t: number[]): number[] {
  return [
    m[0] * t[0] + m[2] * t[1],
    m[1] * t[0] + m[3] * t[1],
    m[0] * t[2] + m[2] * t[3],
    m[1] * t[2] + m[3] * t[3],
    m[0] * t[4] + m[2] * t[5] + m[4],
    m[1] * t[4] + m[3] * t[5] + m[5],
  ]
}

/**
 * pdfjs operatorList에서 이미지 paint 영역을 추출.
 * save/restore/transform으로 CTM을 추적하고, 이미지는 단위 정사각형(0,0)-(1,1)에
 * CTM을 적용한 bbox로 계산한다 (PDF 이미지 렌더링 규약).
 */
export function extractImageRegions(
  fnArray: Uint32Array | number[],
  argsArray: unknown[][],
): ImageRegion[] {
  const regions: ImageRegion[] = []
  let ctm = [1, 0, 0, 1, 0, 0]
  const stack: number[][] = []

  for (let i = 0; i < fnArray.length; i++) {
    const op = fnArray[i]
    switch (op) {
      case OPS.save:
        stack.push(ctm)
        break
      case OPS.restore:
        ctm = stack.pop() || [1, 0, 0, 1, 0, 0]
        break
      case OPS.transform: {
        const t = argsArray[i] as number[]
        if (Array.isArray(t) && t.length >= 6) ctm = multiplyTransform(ctm, t)
        break
      }
      case OPS.paintImageXObject:
      case OPS.paintInlineImageXObject:
      case OPS.paintImageMaskXObject:
      case OPS.paintImageXObjectRepeat: {
        // 단위 정사각형 4꼭짓점에 CTM 적용
        const corners = [[0, 0], [1, 0], [0, 1], [1, 1]]
        let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity
        for (const [u, v] of corners) {
          const x = ctm[0] * u + ctm[2] * v + ctm[4]
          const y = ctm[1] * u + ctm[3] * v + ctm[5]
          if (x < x1) x1 = x
          if (x > x2) x2 = x
          if (y < y1) y1 = y
          if (y > y2) y2 = y
        }
        if (x2 - x1 > 0 && y2 - y1 > 0) regions.push({ x1, y1, x2, y2 })
        break
      }
    }
  }
  return regions
}

function classifyAndAdd(
  seg: { x1: number; y1: number; x2: number; y2: number },
  lineWidth: number,
  horizontals: LineSegment[],
  verticals: LineSegment[],
) {
  const dx = Math.abs(seg.x2 - seg.x1)
  const dy = Math.abs(seg.y2 - seg.y1)
  const length = Math.sqrt(dx * dx + dy * dy)

  if (length < MIN_LINE_LENGTH) return

  if (dy <= ORIENTATION_TOL) {
    const y = (seg.y1 + seg.y2) / 2
    const x1 = Math.min(seg.x1, seg.x2)
    const x2 = Math.max(seg.x1, seg.x2)
    horizontals.push({ x1, y1: y, x2, y2: y, lineWidth })
  } else if (dx <= ORIENTATION_TOL) {
    const x = (seg.x1 + seg.x2) / 2
    const y1 = Math.min(seg.y1, seg.y2)
    const y2 = Math.max(seg.y1, seg.y2)
    verticals.push({ x1: x, y1, x2: x, y2, lineWidth })
  }
}

// ─── 선 전처리 파이프라인 (ODL LinesPreprocessingConsumer 포팅) ──

/**
 * 선 전처리: 굵은 선 필터 → 근접 선 병합 → 장식선 필터링
 * ODL의 LinesPreprocessingConsumer가 하는 핵심 로직.
 */
export function preprocessLines(
  horizontals: LineSegment[],
  verticals: LineSegment[],
): { horizontals: LineSegment[]; verticals: LineSegment[] } {
  // 1. 굵은 선 필터링 (배경 채움 사각형, 장식 테두리 등)
  let h = horizontals.filter(l => l.lineWidth <= MAX_LINE_WIDTH)
  let v = verticals.filter(l => l.lineWidth <= MAX_LINE_WIDTH)

  // 2. 근접 평행 선 병합 (인쇄 잔상, 이중선)
  h = mergeParallelLines(h, "h")
  v = mergeParallelLines(v, "v")

  return { horizontals: h, verticals: v }
}

/**
 * 근접 평행 선 병합 — 같은 방향의 가까운 선을 하나로 합침.
 * 이중선, 인쇄 잔상, PDF 렌더링 미세 차이로 인한 중복 선 제거.
 */
function mergeParallelLines(lines: LineSegment[], dir: "h" | "v"): LineSegment[] {
  if (lines.length <= 1) return lines

  // 수평선: y로 정렬, 수직선: x로 정렬
  const sorted = [...lines].sort((a, b) => {
    const posA = dir === "h" ? a.y1 : a.x1
    const posB = dir === "h" ? b.y1 : b.x1
    if (Math.abs(posA - posB) > 0.1) return posA - posB
    // 같은 위치면 시작 좌표로
    return dir === "h" ? (a.x1 - b.x1) : (a.y1 - b.y1)
  })

  const MERGE_TOL = 3 // 3pt 이내 평행 선 병합

  const result: LineSegment[] = [sorted[0]]
  for (let i = 1; i < sorted.length; i++) {
    const prev = result[result.length - 1]
    const curr = sorted[i]

    const prevPos = dir === "h" ? prev.y1 : prev.x1
    const currPos = dir === "h" ? curr.y1 : curr.x1

    if (Math.abs(prevPos - currPos) <= MERGE_TOL) {
      // 범위가 겹치는지 확인
      const prevStart = dir === "h" ? prev.x1 : prev.y1
      const prevEnd = dir === "h" ? prev.x2 : prev.y2
      const currStart = dir === "h" ? curr.x1 : curr.y1
      const currEnd = dir === "h" ? curr.x2 : curr.y2

      const overlap = Math.min(prevEnd, currEnd) - Math.max(prevStart, currStart)
      const minLen = Math.min(prevEnd - prevStart, currEnd - currStart)

      if (overlap > minLen * 0.3) {
        // 병합: 범위 확장, lineWidth는 최대값 유지
        if (dir === "h") {
          prev.x1 = Math.min(prev.x1, curr.x1)
          prev.x2 = Math.max(prev.x2, curr.x2)
          prev.y1 = (prev.y1 + curr.y1) / 2
          prev.y2 = prev.y1
        } else {
          prev.y1 = Math.min(prev.y1, curr.y1)
          prev.y2 = Math.max(prev.y2, curr.y2)
          prev.x1 = (prev.x1 + curr.x1) / 2
          prev.x2 = prev.x1
        }
        prev.lineWidth = Math.max(prev.lineWidth, curr.lineWidth)
        continue
      }
    }
    result.push(curr)
  }
  return result
}

// ─── 페이지 경계(클립) 선 필터링 ──────────────────────

export function filterPageBorderLines(
  horizontals: LineSegment[],
  verticals: LineSegment[],
  pageWidth: number,
  pageHeight: number,
): { horizontals: LineSegment[]; verticals: LineSegment[] } {
  const margin = 5
  return {
    horizontals: horizontals.filter(l =>
      !(Math.abs(l.y1) < margin || Math.abs(l.y1 - pageHeight) < margin) ||
      (l.x2 - l.x1) < pageWidth * 0.9
    ),
    verticals: verticals.filter(l =>
      !(Math.abs(l.x1) < margin || Math.abs(l.x1 - pageWidth) < margin) ||
      (l.y2 - l.y1) < pageHeight * 0.9
    ),
  }
}

// ─── Vertex(교차점) 생성 ─────────────────────────────

/**
 * 수평선과 수직선의 교차점(Vertex)을 생성.
 * ODL의 TableBorderBuilder.addLine()이 교차점을 자동 생성하는 것과 동일.
 * 각 Vertex는 교차하는 선들의 lineWidth로 radius를 계산 → 동적 tolerance.
 */
function buildVertices(horizontals: LineSegment[], verticals: LineSegment[]): Vertex[] {
  const vertices: Vertex[] = []
  const tol = CONNECT_TOL

  for (const h of horizontals) {
    for (const v of verticals) {
      // 수평선의 X범위에 수직선의 X가 포함되고
      // 수직선의 Y범위에 수평선의 Y가 포함되면 → 교차
      if (v.x1 >= h.x1 - tol && v.x1 <= h.x2 + tol &&
          h.y1 >= v.y1 - tol && h.y1 <= v.y2 + tol) {
        const radius = Math.max(h.lineWidth, v.lineWidth, 1)
        vertices.push({ x: v.x1, y: h.y1, radius })
      }
    }
  }

  return vertices
}

/**
 * 근접 Vertex 병합 — 같은 교차점의 미세 위치 차이를 하나로 합침.
 */
function mergeVertices(vertices: Vertex[]): Vertex[] {
  if (vertices.length <= 1) return vertices

  const merged: Vertex[] = []
  const used = new Array(vertices.length).fill(false)

  for (let i = 0; i < vertices.length; i++) {
    if (used[i]) continue
    let sumX = vertices[i].x, sumY = vertices[i].y
    let maxRadius = vertices[i].radius
    let count = 1

    for (let j = i + 1; j < vertices.length; j++) {
      if (used[j]) continue
      const mergeTol = VERTEX_MERGE_FACTOR * Math.max(maxRadius, vertices[j].radius)
      if (Math.abs(vertices[i].x - vertices[j].x) <= mergeTol &&
          Math.abs(vertices[i].y - vertices[j].y) <= mergeTol) {
        sumX += vertices[j].x
        sumY += vertices[j].y
        maxRadius = Math.max(maxRadius, vertices[j].radius)
        count++
        used[j] = true
      }
    }

    merged.push({ x: sumX / count, y: sumY / count, radius: maxRadius })
  }

  return merged
}

// ─── 테이블 그리드 구성 (Vertex 기반) ─────────────────

/**
 * 수평/수직 선에서 테이블 그리드를 추출.
 * ODL과 동일한 흐름:
 * 1. 선 전처리 (preprocessLines — 호출측에서 수행)
 * 2. 교차점(Vertex) 생성 + 병합
 * 3. 교차하는 선들을 그룹화 (연결 컴포넌트)
 * 4. 각 그룹에서 Vertex의 X/Y 좌표를 동적 tolerance로 클러스터링
 * 5. 그리드 검증 (최소 열 폭, 최소 행 높이)
 */
export function buildTableGrids(
  horizontals: LineSegment[],
  verticals: LineSegment[],
): TableGrid[] {
  if (horizontals.length < 2 || verticals.length < 2) return []

  // 1. 교차점 생성
  const allVertices = buildVertices(horizontals, verticals)
  const vertices = mergeVertices(allVertices)

  if (vertices.length < 4) return [] // 최소 4꼭짓점 필요 (사각형)

  // 전체 vertex의 대표 radius (동적 tolerance)
  const globalRadius = vertices.reduce((max, v) => Math.max(max, v.radius), 1)

  // 2. 선들을 교차 관계로 그룹화
  const allLines = [
    ...horizontals.map((l, i) => ({ ...l, type: "h" as const, id: i })),
    ...verticals.map((l, i) => ({ ...l, type: "v" as const, id: i + horizontals.length })),
  ]

  const groups = groupConnectedLines(allLines)
  const grids: TableGrid[] = []

  for (const group of groups) {
    const hLines = group.filter(l => l.type === "h")
    const vLines = group.filter(l => l.type === "v")

    if (hLines.length < 2 || vLines.length < 2) continue

    // 3. 이 그룹의 Vertex만 수집
    let gx1 = Infinity, gy1 = Infinity, gx2 = -Infinity, gy2 = -Infinity
    for (const l of vLines) { if (l.x1 < gx1) gx1 = l.x1; if (l.x1 > gx2) gx2 = l.x1 }
    for (const l of hLines) { if (l.y1 < gy1) gy1 = l.y1; if (l.y1 > gy2) gy2 = l.y1 }
    const groupBbox = {
      x1: gx1 - CONNECT_TOL,
      y1: gy1 - CONNECT_TOL,
      x2: gx2 + CONNECT_TOL,
      y2: gy2 + CONNECT_TOL,
    }

    const groupVertices = vertices.filter(v =>
      v.x >= groupBbox.x1 && v.x <= groupBbox.x2 &&
      v.y >= groupBbox.y1 && v.y <= groupBbox.y2
    )

    // 그룹 vertex의 대표 radius
    const groupRadius = groupVertices.length > 0
      ? groupVertices.reduce((max, v) => Math.max(max, v.radius), 1)
      : globalRadius

    // 4. Vertex 기반 좌표 클러스터링 (동적 tolerance)
    const coordMergeTol = Math.max(VERTEX_MERGE_FACTOR * groupRadius, MIN_COORD_MERGE_TOL)

    // Y좌표: 수평선 y + Vertex y
    const rawYs = [
      ...hLines.map(l => l.y1),
      ...groupVertices.map(v => v.y),
    ]
    const rowYs = clusterCoordinates(rawYs, coordMergeTol).sort((a, b) => b - a)

    // X좌표: 수직선 x + Vertex x
    const rawXs = [
      ...vLines.map(l => l.x1),
      ...groupVertices.map(v => v.x),
    ]
    const colXs = clusterCoordinates(rawXs, coordMergeTol).sort((a, b) => a - b)

    if (rowYs.length < 2 || colXs.length < 2) continue

    // 5. 그리드 검증: 최소 열 폭, 최소 행 높이
    const validColXs = enforceMinWidth(colXs, MIN_COL_WIDTH)
    const validRowYs = enforceMinHeight(rowYs, MIN_ROW_HEIGHT)

    if (validRowYs.length < 2 || validColXs.length < 2) continue

    const bbox = {
      x1: validColXs[0], y1: validRowYs[validRowYs.length - 1],
      x2: validColXs[validColXs.length - 1], y2: validRowYs[0],
    }

    grids.push({ rowYs: validRowYs, colXs: validColXs, bbox, vertexRadius: groupRadius })
  }

  return mergeAdjacentGrids(grids)
}

/** 최소 열 폭 보장 — 너무 좁은 열은 인접 열과 병합 */
function enforceMinWidth(colXs: number[], minWidth: number): number[] {
  if (colXs.length <= 2) return colXs
  const result: number[] = [colXs[0]]
  for (let i = 1; i < colXs.length; i++) {
    const prevX = result[result.length - 1]
    if (colXs[i] - prevX < minWidth && i < colXs.length - 1) {
      // 너무 좁으면 스킵 (다음 열과 병합)
      continue
    }
    result.push(colXs[i])
  }
  return result
}

/** 최소 행 높이 보장 — 너무 낮은 행은 인접 행과 병합 */
function enforceMinHeight(rowYs: number[], minHeight: number): number[] {
  if (rowYs.length <= 2) return rowYs
  // rowYs는 내림차순 (위→아래)
  const result: number[] = [rowYs[0]]
  for (let i = 1; i < rowYs.length; i++) {
    const prevY = result[result.length - 1]
    if (prevY - rowYs[i] < minHeight && i < rowYs.length - 1) {
      continue
    }
    result.push(rowYs[i])
  }
  return result
}

/** 같은 열 구조를 가진 인접 그리드를 병합 */
function mergeAdjacentGrids(grids: TableGrid[]): TableGrid[] {
  if (grids.length <= 1) return grids
  const sorted = [...grids].sort((a, b) => b.bbox.y2 - a.bbox.y2)
  const merged: TableGrid[] = [sorted[0]]

  for (let i = 1; i < sorted.length; i++) {
    const prev = merged[merged.length - 1]
    const curr = sorted[i]

    if (prev.colXs.length === curr.colXs.length) {
      const mergeTol = Math.max(VERTEX_MERGE_FACTOR * Math.max(prev.vertexRadius, curr.vertexRadius), 6) * 3
      const colMatch = prev.colXs.every((x, ci) => Math.abs(x - curr.colXs[ci]) <= mergeTol)
      const verticalGap = prev.bbox.y1 - curr.bbox.y2
      if (colMatch && verticalGap >= -CONNECT_TOL && verticalGap <= 20) {
        const allRowYs = [...new Set([...prev.rowYs, ...curr.rowYs])].sort((a, b) => b - a)
        merged[merged.length - 1] = {
          rowYs: allRowYs,
          colXs: prev.colXs,
          bbox: {
            x1: Math.min(prev.bbox.x1, curr.bbox.x1),
            y1: Math.min(prev.bbox.y1, curr.bbox.y1),
            x2: Math.max(prev.bbox.x2, curr.bbox.x2),
            y2: Math.max(prev.bbox.y2, curr.bbox.y2),
          },
          vertexRadius: Math.max(prev.vertexRadius, curr.vertexRadius),
        }
        continue
      }
    }
    merged.push(curr)
  }
  return merged
}

/** 좌표값 클러스터링 — 동적 tolerance 기반 (ODL의 vertex radius 반영) */
function clusterCoordinates(values: number[], tolerance: number): number[] {
  if (values.length === 0) return []
  const sorted = [...values].sort((a, b) => a - b)
  const clusters: { sum: number; count: number }[] = [{ sum: sorted[0], count: 1 }]

  for (let i = 1; i < sorted.length; i++) {
    const last = clusters[clusters.length - 1]
    const avg = last.sum / last.count
    if (Math.abs(sorted[i] - avg) <= tolerance) {
      last.sum += sorted[i]
      last.count++
    } else {
      clusters.push({ sum: sorted[i], count: 1 })
    }
  }

  return clusters.map(c => c.sum / c.count)
}

type TypedLine = LineSegment & { type: "h" | "v"; id: number }

/** 교차하는 선들을 Union-Find로 그룹화 */
function groupConnectedLines(lines: TypedLine[]): TypedLine[][] {
  const parent = lines.map((_, i) => i)

  function find(x: number): number {
    while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x] }
    return x
  }
  function union(a: number, b: number) {
    const ra = find(a), rb = find(b)
    if (ra !== rb) parent[ra] = rb
  }

  for (let i = 0; i < lines.length; i++) {
    for (let j = i + 1; j < lines.length; j++) {
      if (linesIntersect(lines[i], lines[j])) {
        union(i, j)
      }
    }
  }

  const groups = new Map<number, TypedLine[]>()
  for (let i = 0; i < lines.length; i++) {
    const root = find(i)
    if (!groups.has(root)) groups.set(root, [])
    groups.get(root)!.push(lines[i])
  }

  return [...groups.values()]
}

/** 수평선과 수직선의 교차 판정 (tolerance 포함) */
function linesIntersect(a: TypedLine, b: TypedLine): boolean {
  if (a.type === b.type) {
    if (a.type === "h") {
      if (Math.abs(a.y1 - b.y1) > CONNECT_TOL) return false
      return Math.min(a.x2, b.x2) >= Math.max(a.x1, b.x1) - CONNECT_TOL
    } else {
      if (Math.abs(a.x1 - b.x1) > CONNECT_TOL) return false
      return Math.min(a.y2, b.y2) >= Math.max(a.y1, b.y1) - CONNECT_TOL
    }
  }

  const h = a.type === "h" ? a : b
  const v = a.type === "h" ? b : a
  const tol = CONNECT_TOL

  return (
    v.x1 >= h.x1 - tol && v.x1 <= h.x2 + tol &&
    h.y1 >= v.y1 - tol && h.y1 <= v.y2 + tol
  )
}

// ─── 셀 구조 추출 (Vertex 기반 정밀 병합 셀 감지) ─────

/**
 * 테이블 그리드에서 셀 목록을 추출.
 * ODL의 createMatrix() 알고리즘:
 * - 수직선 존재 여부로 colSpan 감지 (75% 커버 기준)
 * - 수평선 존재 여부로 rowSpan 감지 (75% 커버 기준)
 * - 우하단→좌상단 propagation으로 병합 셀 정리
 * - 중복 행/열 제거
 */
export function extractCells(
  grid: TableGrid,
  horizontals: LineSegment[],
  verticals: LineSegment[],
): ExtractedCell[] {
  const { rowYs, colXs } = grid
  const numRows = rowYs.length - 1
  const numCols = colXs.length - 1
  if (numRows <= 0 || numCols <= 0) return []

  // 경계선 존재 여부를 행렬로 사전 계산
  // vBorders[r][c] = colXs[c]에 row r 구간의 수직선이 있는지
  const vBorders: boolean[][] = Array.from({ length: numRows },
    (_, r) => Array.from({ length: numCols + 1 },
      (_, c) => hasVerticalLine(verticals, colXs[c], rowYs[r], rowYs[r + 1], grid.vertexRadius)))

  // hBorders[r][c] = rowYs[r]에 col c 구간의 수평선이 있는지
  const hBorders: boolean[][] = Array.from({ length: numRows + 1 },
    (_, r) => Array.from({ length: numCols },
      (_, c) => hasHorizontalLine(horizontals, rowYs[r], colXs[c], colXs[c + 1], grid.vertexRadius)))

  // 셀이 이미 병합된 셀에 포함되는지 추적
  const occupied = Array.from({ length: numRows }, () => Array(numCols).fill(false))
  const cells: ExtractedCell[] = []

  for (let r = 0; r < numRows; r++) {
    for (let c = 0; c < numCols; c++) {
      if (occupied[r][c]) continue

      let colSpan = 1
      let rowSpan = 1

      // colSpan: 오른쪽 내부 경계에 수직선이 없으면 병합
      while (c + colSpan < numCols && !vBorders[r][c + colSpan]) {
        // 추가 검증: 확장하려는 영역의 모든 행에서 수직선이 없어야 함
        let canExpand = true
        for (let dr = 0; dr < rowSpan; dr++) {
          if (vBorders[r + dr][c + colSpan]) { canExpand = false; break }
        }
        if (!canExpand) break
        colSpan++
      }

      // rowSpan: 아래쪽 내부 경계에 수평선이 없으면 병합
      while (r + rowSpan < numRows) {
        let hasLine = false
        for (let dc = 0; dc < colSpan; dc++) {
          if (hBorders[r + rowSpan][c + dc]) { hasLine = true; break }
        }
        if (hasLine) break
        rowSpan++
      }

      // 병합 영역 마킹
      for (let dr = 0; dr < rowSpan; dr++) {
        for (let dc = 0; dc < colSpan; dc++) {
          occupied[r + dr][c + dc] = true
        }
      }

      cells.push({
        row: r, col: c, rowSpan, colSpan,
        bbox: {
          x1: colXs[c], y1: rowYs[r + rowSpan],
          x2: colXs[c + colSpan], y2: rowYs[r],
        },
      })
    }
  }

  return cells
}

/**
 * 특정 X 위치에 수직선이 Y 범위를 커버하는지 확인.
 * v2: 75% 커버 기준 + 동적 tolerance (vertex radius 기반)
 */
function hasVerticalLine(
  verticals: LineSegment[], x: number, topY: number, botY: number, vertexRadius: number,
): boolean {
  const tol = Math.max(VERTEX_MERGE_FACTOR * vertexRadius, 4)
  for (const v of verticals) {
    if (Math.abs(v.x1 - x) <= tol) {
      const cellH = Math.abs(topY - botY)
      if (cellH < 0.1) continue
      const overlapTop = Math.min(v.y2, topY)
      const overlapBot = Math.max(v.y1, botY)
      const overlap = overlapTop - overlapBot
      // 75% 커버 기준 (기존 50% → 병합 셀 내부 단선 오탐 방지)
      if (overlap >= cellH * 0.75) return true
    }
  }
  return false
}

/**
 * 특정 Y 위치에 수평선이 X 범위를 커버하는지 확인.
 * v2: 75% 커버 기준 + 동적 tolerance
 */
function hasHorizontalLine(
  horizontals: LineSegment[], y: number, leftX: number, rightX: number, vertexRadius: number,
): boolean {
  const tol = Math.max(VERTEX_MERGE_FACTOR * vertexRadius, 4)
  for (const h of horizontals) {
    if (Math.abs(h.y1 - y) <= tol) {
      const cellW = Math.abs(rightX - leftX)
      if (cellW < 0.1) continue
      const overlapLeft = Math.max(h.x1, leftX)
      const overlapRight = Math.min(h.x2, rightX)
      const overlap = overlapRight - overlapLeft
      if (overlap >= cellW * 0.75) return true
    }
  }
  return false
}

// ─── 텍스트→셀 매핑 ──────────────────────────────────

export interface TextItem {
  text: string
  x: number; y: number; w: number; h: number
  fontSize: number; fontName: string
  /** pdfjs 공백 아이템이 이 아이템 직전에 있었음 — 단어 경계 힌트 (parser.ts NormItem에서 전파) */
  hasSpaceBefore?: boolean
}

/**
 * 공백 삽입 갭 임계값 — 폰트 크기 비례.
 * 절대 px(3px) 기준은 Type3 폰트(예: fontSize 10.5에서 단어 갭 2.7px)에서 공백이
 * 소실되고, 작은 폰트에서는 과다 삽입됨. fontSize×0.17 비례 기준으로 교체
 * (veraPDF wcag-algs TEXT_LINE_SPACE_RATIO 아이디어의 클린룸 재구현 — 코드 비복사).
 */
export const SPACE_GAP_RATIO = 0.17

export function spaceGapThreshold(fontSize: number): number {
  return Math.max(fontSize * SPACE_GAP_RATIO, 1)
}

/**
 * 텍스트 아이템을 셀에 매핑.
 * v2: ODL의 getIntersectionPercent 방식 — 텍스트 bbox와 셀 bbox의 교차 비율로 판별.
 * 중심점만 보는 기존 방식보다 정확 (긴 텍스트가 셀 경계를 걸치는 경우 처리).
 */
export function mapTextToCells(
  items: TextItem[],
  cells: ExtractedCell[],
): Map<ExtractedCell, TextItem[]> {
  const result = new Map<ExtractedCell, TextItem[]>()
  for (const cell of cells) {
    result.set(cell, [])
  }

  for (const item of items) {
    const pad = CELL_PADDING

    let bestCell: ExtractedCell | null = null
    let bestScore = 0

    for (const cell of cells) {
      // 텍스트 bbox와 셀 bbox의 교차 영역 계산
      const ix1 = Math.max(item.x, cell.bbox.x1 - pad)
      const ix2 = Math.min(item.x + item.w, cell.bbox.x2 + pad)
      const iy1 = Math.max(item.y, cell.bbox.y1 - pad)
      const iy2 = Math.min(item.y + (item.h || item.fontSize), cell.bbox.y2 + pad)

      if (ix1 >= ix2 || iy1 >= iy2) continue

      const intersectArea = (ix2 - ix1) * (iy2 - iy1)
      const itemArea = Math.max(item.w, 1) * Math.max(item.h || item.fontSize, 1)
      const score = intersectArea / itemArea // ODL의 MIN_CELL_CONTENT_INTERSECTION_PERCENT

      if (score > bestScore) {
        bestScore = score
        bestCell = cell
      }
    }

    // 교차 비율 > 0.3이면 셀에 할당 (ODL은 0.6이지만 PDF 텍스트 좌표 오차 고려)
    if (bestCell && bestScore > 0.3) {
      result.get(bestCell)!.push(item)
    }
  }

  return result
}

/**
 * 셀 내 텍스트 아이템을 읽기 순서로 정렬 후 합치기.
 * Y 내림차순 (위→아래) → X 오름차순 (좌→우)
 */
export function cellTextToString(items: TextItem[]): string {
  if (items.length === 0) return ""
  if (items.length === 1) return items[0].text

  // Y좌표로 행 그룹핑 (tolerance: max(3, fontSize*0.6))
  const sorted = [...items].sort((a, b) => b.y - a.y || a.x - b.x)
  const lines: TextItem[][] = []
  let curLine: TextItem[] = [sorted[0]]
  let curY = sorted[0].y

  for (let i = 1; i < sorted.length; i++) {
    const tol = Math.max(3, Math.min(sorted[i].fontSize, curLine[0].fontSize) * 0.6)
    if (Math.abs(sorted[i].y - curY) <= tol) {
      curLine.push(sorted[i])
    } else {
      lines.push(curLine)
      curLine = [sorted[i]]
      curY = sorted[i].y
    }
  }
  lines.push(curLine)

  // 각 행을 텍스트로 변환 — 좌표 기반 균등배분 감지 포함
  const textLines = lines.map(line => {
    const s = line.sort((a, b) => a.x - b.x)
    if (s.length === 1) return s[0].text

    // 균등배분 구간 감지 (좌표 기반)
    const evenSpaced = detectEvenSpacedItems(s)

    let result = s[0].text
    for (let j = 1; j < s.length; j++) {
      // 균등배분 구간이면 무조건 공백 없이 합침
      if (evenSpaced[j]) {
        result += s[j].text
        continue
      }

      const gap = s[j].x - (s[j - 1].x + s[j - 1].w)
      const avgFs = (s[j].fontSize + s[j - 1].fontSize) / 2
      // pdfjs 공백 아이템 힌트 — 단어 경계 확정 (Type3 폰트 글자 분리 셀 텍스트 복원)
      if (s[j].hasSpaceBefore && gap >= avgFs * 0.05) {
        result += " " + s[j].text
      } else if (gap > spaceGapThreshold(avgFs)) {
        result += " " + s[j].text
      } else {
        result += s[j].text
      }
    }
    return result
  })

  return mergeCellTextLines(textLines)
}

/**
 * 좌표 기반 균등배분 감지 — TextItem 배열에서 한글 1~2자 아이템이
 * 일정 간격으로 3개+ 연속되면 균등배분으로 판단.
 * ODL TextLineProcessor의 핵심 로직을 좌표 기반으로 구현.
 */
function detectEvenSpacedItems(items: TextItem[]): boolean[] {
  const result = new Array(items.length).fill(false)
  if (items.length < 3) return result

  let runStart = -1
  for (let i = 0; i < items.length; i++) {
    // 균등배분 = 한글 1자 개별 배치. 2자 단어는 균등배분이 아니라 실제 단어.
    const isShortKorean = /^[가-힣]{1}$/.test(items[i].text) || /^[\d]{1}$/.test(items[i].text)

    // 명시적 공백 글리프가 직전에 있으면 단어 경계 — 균등배분 run 분리.
    // (Type3 폰트가 글자를 1자씩 배치하면서 공백 글리프를 따로 두는 경우,
    //  진짜 단어 경계를 균등배분으로 오판해 문장 전체가 붙는 것을 방지)
    if (isShortKorean && runStart >= 0 && items[i].hasSpaceBefore) {
      if (i - runStart >= 3) markEvenRun(items, result, runStart, i)
      runStart = i
      continue
    }

    // 이전 아이템과의 갭이 fontSize*3+ 이면 run 끊기 (다른 영역)
    if (isShortKorean && runStart >= 0 && i > 0) {
      const gap = items[i].x - (items[i - 1].x + items[i - 1].w)
      const maxRunGap = Math.max(items[i].fontSize * 3, 30)
      if (gap > maxRunGap) {
        if (i - runStart >= 3) markEvenRun(items, result, runStart, i)
        runStart = i
        continue
      }
    }

    if (isShortKorean) {
      if (runStart < 0) runStart = i
    } else {
      if (runStart >= 0 && i - runStart >= 3) {
        markEvenRun(items, result, runStart, i)
      }
      runStart = -1
    }
  }
  if (runStart >= 0 && items.length - runStart >= 3) {
    markEvenRun(items, result, runStart, items.length)
  }

  return result
}

function markEvenRun(items: TextItem[], result: boolean[], start: number, end: number): void {
  const gaps: number[] = []
  for (let i = start + 1; i < end; i++) {
    gaps.push(items[i].x - (items[i - 1].x + items[i - 1].w))
  }
  const posGaps = gaps.filter(g => g > 0)
  if (posGaps.length < 2) return

  let minGap = Infinity, maxGap = -Infinity
  for (const g of posGaps) { if (g < minGap) minGap = g; if (g > maxGap) maxGap = g }
  const avgFs = items[start].fontSize

  // 간격이 fontSize의 0.1~3배 사이이고, 최대/최소 비율 3배 이내
  if (minGap >= avgFs * 0.1 && maxGap <= avgFs * 3 && maxGap / Math.max(minGap, 0.1) <= 3) {
    for (let i = start + 1; i < end; i++) {
      result[i] = true
    }
  }
}

export { detectEvenSpacedItems }

// ─── 과소분할 표 재구성 (ODL TableStructureNormalizer 포팅) ──
//
// 행 구분선이 생략된 표(헤더 아래만 선이 있는 한국 공문서 표)는 본문 전체가
// 1~2행으로 합쳐진다. 셀 안에 텍스트 줄이 8개+ 뭉친 경우 줄의 centerY로
// row band를 재유도해 행을 복원한다. 품질이 개선될 때만 교체.
//
// Original work: Copyright 2025-2026 Hancom Inc. (Apache-2.0)
// https://github.com/opendataloader-project/opendataloader-pdf

const MAX_UNDERSEGMENTED_ROWS = 2
const MIN_UNDERSEGMENTED_COLUMNS = 3
const MIN_UNDERSEGMENTED_TEXT_LINES = 8
const MIN_ROW_BAND_MISMATCH = 2
const MIN_ROW_BAND_EPSILON = 3.0
const ROW_BAND_EPSILON_RATIO = 0.6

interface RowBand {
  centerY: number
  avgHeight: number
  topY: number
  bottomY: number
  lineCount: number
  /** 컬럼별 아이템 */
  itemsByCol: TextItem[][]
}

/** 아이템 중심 Y (h가 0이면 fontSize 대용) */
function itemCenterY(item: TextItem): number {
  return item.y + (item.h > 0 ? item.h : item.fontSize) / 2
}

function itemHeight(item: TextItem): number {
  return item.h > 0 ? item.h : item.fontSize
}

/** 아이템을 colXs 경계 기준 컬럼에 배정 (중심 X 기준, 범위 밖이면 최근접) */
function findColumnIndex(item: TextItem, colXs: number[]): number {
  const cx = item.x + item.w / 2
  for (let c = 0; c < colXs.length - 1; c++) {
    if (cx >= colXs[c] && cx <= colXs[c + 1]) return c
  }
  let best = 0
  let bestDist = Infinity
  for (let c = 0; c < colXs.length - 1; c++) {
    const center = (colXs[c] + colXs[c + 1]) / 2
    const d = Math.abs(cx - center)
    if (d < bestDist) { bestDist = d; best = c }
  }
  return best
}

/** 아이템들을 Y 기준 시각적 줄로 그룹핑 */
function groupItemsToVisualLines(items: TextItem[]): TextItem[][] {
  if (items.length === 0) return []
  const sorted = [...items].sort((a, b) => b.y - a.y || a.x - b.x)
  const lines: TextItem[][] = []
  let cur: TextItem[] = [sorted[0]]
  let curY = sorted[0].y
  for (let i = 1; i < sorted.length; i++) {
    const tol = Math.max(3, Math.min(sorted[i].fontSize, cur[0].fontSize) * 0.6)
    if (Math.abs(sorted[i].y - curY) <= tol) {
      cur.push(sorted[i])
    } else {
      lines.push(cur)
      cur = [sorted[i]]
      curY = sorted[i].y
    }
  }
  lines.push(cur)
  return lines
}

/**
 * 과소분할 표 재구성. 조건(행≤2 + 열≥3 + dense 컬럼 2개+)을 만족하고
 * row band 재유도가 품질을 개선할 때만 새 셀 행렬을 반환, 아니면 null.
 *
 * @param originalCells 기존 셀 행렬 (품질 비교용)
 * @param colXs 그리드 열 경계
 * @param items 표 영역 내 텍스트 아이템
 */
export function normalizeUndersegmentedTable(
  originalCells: { text: string }[][],
  colXs: number[],
  items: TextItem[],
): string[][] | null {
  const numRows = originalCells.length
  const numCols = colXs.length - 1
  if (numRows > MAX_UNDERSEGMENTED_ROWS || numCols < MIN_UNDERSEGMENTED_COLUMNS) return null
  if (items.length === 0) return null

  // 1) 컬럼별 의미있는 줄 수 — dense 컬럼(8줄+) 2개 이상이어야 과소분할로 판정
  const itemsByCol: TextItem[][] = Array.from({ length: numCols }, () => [])
  for (const item of items) {
    if (!item.text.trim()) continue
    itemsByCol[findColumnIndex(item, colXs)].push(item)
  }
  let denseColumns = 0
  for (const colItems of itemsByCol) {
    if (groupItemsToVisualLines(colItems).length >= MIN_UNDERSEGMENTED_TEXT_LINES) denseColumns++
  }
  if (denseColumns < 2) return null

  // 2) 전체 줄에서 row band 유도 — centerY 근접(epsilon) 또는 수직 겹침이면 같은 band
  const allLines = groupItemsToVisualLines(items.filter(i => i.text.trim()))
  const bands: RowBand[] = []
  for (const line of allLines) {
    let cy = 0, h = 0
    for (const it of line) { cy += itemCenterY(it); h += itemHeight(it) }
    cy /= line.length
    h /= line.length
    const top = cy + h / 2
    const bottom = cy - h / 2

    let matched: RowBand | null = null
    for (const band of bands) {
      const epsilon = Math.max(MIN_ROW_BAND_EPSILON, Math.min(band.avgHeight, h) * ROW_BAND_EPSILON_RATIO)
      if (Math.abs(band.centerY - cy) <= epsilon ||
          (bottom <= band.topY && top >= band.bottomY)) {
        matched = band
        break
      }
    }
    if (!matched) {
      matched = { centerY: 0, avgHeight: 0, topY: -Infinity, bottomY: Infinity, lineCount: 0, itemsByCol: Array.from({ length: numCols }, () => []) }
      bands.push(matched)
    }
    matched.centerY = (matched.centerY * matched.lineCount + cy) / (matched.lineCount + 1)
    matched.avgHeight = (matched.avgHeight * matched.lineCount + h) / (matched.lineCount + 1)
    matched.topY = Math.max(matched.topY, top)
    matched.bottomY = Math.min(matched.bottomY, bottom)
    matched.lineCount++
    for (const it of line) {
      matched.itemsByCol[findColumnIndex(it, colXs)].push(it)
    }
  }

  // 3) band 수가 기존 행 수 + 2 이상이어야 재구축 의미 있음
  if (bands.length < numRows + MIN_ROW_BAND_MISMATCH) return null

  bands.sort((a, b) => b.centerY - a.centerY)

  // 4) 셀 행렬 재구축
  const rebuilt: string[][] = bands.map(band =>
    band.itemsByCol.map(colItems => colItems.length > 0 ? cellTextToString(colItems) : ""),
  )

  // 5) 품질 검증: 비어있지 않은 행 수가 늘고, 비어있지 않은 열 수가 줄지 않아야 교체
  const countNonEmptyRows = (cells: { text: string }[][] | string[][]) =>
    cells.filter(row => row.some(c => (typeof c === "string" ? c : c.text).trim() !== "")).length
  const countNonEmptyCols = (cells: { text: string }[][] | string[][], cols: number) => {
    let n = 0
    for (let c = 0; c < cols; c++) {
      if (cells.some(row => row[c] != null && (typeof row[c] === "string" ? row[c] as string : (row[c] as { text: string }).text).trim() !== "")) n++
    }
    return n
  }

  if (countNonEmptyRows(rebuilt) <= countNonEmptyRows(originalCells)) return null
  if (countNonEmptyCols(rebuilt, numCols) < countNonEmptyCols(originalCells, numCols)) return null

  return rebuilt
}

/**
 * 셀 내 텍스트 아이템을 읽기 순서로 정렬 후 합치기 — 줄바꿈 병합 전용.
 * (cellTextToString 내부에서 사용)
 */
function mergeCellTextLines(textLines: string[]): string {
  // 셀 내 줄바꿈 병합 — 잘린 단어/숫자 조각 복구
  if (textLines.length <= 1) return textLines[0] || ""
  const merged: string[] = [textLines[0]]
  for (let i = 1; i < textLines.length; i++) {
    const prev = merged[merged.length - 1]
    const curr = textLines[i]
    if (/[가-힣]$/.test(prev) && /^[가-힣]+$/.test(curr) && curr.length <= 8 && !curr.includes(" ")) {
      merged[merged.length - 1] = prev + curr
    }
    else if (curr.trim().length <= 3 && /^[)\]%}]/.test(curr.trim())) {
      merged[merged.length - 1] = prev + curr.trim()
    }
    else if (/[,(]$/.test(prev.trim()) && curr.trim().length <= 15) {
      merged[merged.length - 1] = prev + curr.trim()
    }
    else if (/[\d,]$/.test(prev) && /^[\d,]+[)\]]?$/.test(curr.trim()) && curr.trim().length <= 10) {
      merged[merged.length - 1] = prev + curr.trim()
    }
    else {
      merged.push(curr)
    }
  }
  return merged.join("\n")
}
