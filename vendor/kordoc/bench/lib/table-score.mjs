// 표 채점 — XML 참조 그리드 vs kordoc IR 그리드 (markdown이 아닌 IR 단계, pitfall #10)
//
// 참조 그리드: bench/ref/hwpx-ref.mjs 가 만든 {rows, cols, cells:[{r,c,rs,cs,text,hasNested}]}
// IR 그리드 : ParseSuccess.blocks 의 IRTable → 앵커 튜플 재계산 (renderer와 동일한 skip-walk)
// 중첩표(v3.0): IRCell.blocks 의 IRBlock(type:'table')을 재귀 수집 — ref XML 중첩 tbl과
// 같은 경계(post-order, 자식 먼저)로 비교하고 부모 셀 텍스트에서는 제외 (이중 카운트 금지)

import { levBand } from "./align.mjs"
import { normText, normKey } from "./normalize.mjs"

/**
 * IR 셀의 "자기 텍스트" — blocks가 있으면 문단 블록만 join (중첩표 평탄화 텍스트·
 * ![image] 참조가 섞인 하위 호환 cell.text 대신). 중첩표 텍스트는 자식 그리드에서 채점.
 */
function cellOwnText(cell) {
  if (cell.blocks?.length) {
    return cell.blocks
      .filter(b => b.type !== "table" && b.type !== "image")
      .map(b => b.text ?? "")
      .filter(Boolean)
      .join("\n")
  }
  return cell.text ?? ""
}

/** IRTable.cells[][] → 앵커 셀 목록 (tableToHtml과 동일한 skip-set 워크) */
export function irAnchors(irTable) {
  const { rows, cols, cells } = irTable
  const anchors = []
  const skip = new Set()
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (skip.has(r * 100000 + c)) continue
      const cell = cells[r]?.[c]
      if (!cell) continue
      anchors.push({ r, c, rs: cell.rowSpan, cs: cell.colSpan, text: cellOwnText(cell) })
      for (let dr = 0; dr < cell.rowSpan; dr++) {
        for (let dc = 0; dc < cell.colSpan; dc++) {
          if (dr === 0 && dc === 0) continue
          if (r + dr < rows && c + dc < cols) skip.add((r + dr) * 100000 + (c + dc))
        }
      }
    }
  }
  return { rows, cols, anchors }
}

/**
 * IRBlock[] → IR 그리드 목록 (post-order: 셀 내부 중첩표 먼저, 부모 나중).
 * ref 추출기의 tables[] 적재 순서(processCell 즉시 처리 = 자식 먼저)와 동일한 경계.
 */
export function collectIrGrids(blocks) {
  const grids = []
  const visitTable = (table, depth = 0) => {
    if (depth > 12) return
    // 앵커 워크와 동일한 row-major 순서로 셀 내부 중첩표 재귀
    const { rows, cols, cells } = table
    const skip = new Set()
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (skip.has(r * 100000 + c)) continue
        const cell = cells[r]?.[c]
        if (!cell) continue
        for (const b of cell.blocks ?? []) {
          if (b.type === "table" && b.table) visitTable(b.table, depth + 1)
        }
        for (let dr = 0; dr < cell.rowSpan; dr++) {
          for (let dc = 0; dc < cell.colSpan; dc++) {
            if (dr === 0 && dc === 0) continue
            if (r + dr < rows && c + dc < cols) skip.add((r + dr) * 100000 + (c + dc))
          }
        }
      }
    }
    grids.push(irAnchors(table))
  }
  for (const b of blocks ?? []) {
    if (b.type === "table" && b.table) visitTable(b.table)
  }
  return grids
}

function cellTextBag(grid) {
  const bag = new Map()
  for (const a of grid.anchors ?? grid.cells) {
    const k = normKey(a.text)
    if (k) bag.set(k, (bag.get(k) ?? 0) + 1)
  }
  return bag
}

function bagSim(a, b) {
  let inter = 0, total = 0
  for (const [k, n] of a) { total += n; inter += Math.min(n, b.get(k) ?? 0) }
  for (const [, n] of b) total += n
  if (total === 0) return 0.5 // 둘 다 빈 표 — 중립
  return (2 * inter) / total
}

function dimSim(a, b) {
  const ra = a.rows, ca = a.cols, rb = b.rows, cb = b.cols
  return 1 - (Math.abs(ra - rb) + Math.abs(ca - cb)) / Math.max(1, ra + ca + rb + cb)
}

/**
 * 표 1:1 대응 — 문서 순서 보존 DP 정렬 + 유사도(셀 텍스트 bag + 치수).
 * 분할표 보정: 미매칭 ref에 대해 연속 미매칭 IR 병합 후보 시도 (pitfall #18).
 */
export function matchTables(refTables, irGrids) {
  const n = refTables.length, m = irGrids.length
  const sim = []
  const refBags = refTables.map(t => cellTextBag(t))
  const irBags = irGrids.map(g => cellTextBag(g))
  for (let i = 0; i < n; i++) {
    sim.push(new Float64Array(m))
    for (let j = 0; j < m; j++) {
      sim[i][j] = 0.75 * bagSim(refBags[i], irBags[j]) + 0.25 * dimSim(refTables[i], irGrids[j])
    }
  }
  const MIN_SIM = 0.2
  // DP: 순서 보존 최대 가중 매칭
  const dp = Array.from({ length: n + 1 }, () => new Float64Array(m + 1))
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      let best = Math.max(dp[i - 1][j], dp[i][j - 1])
      if (sim[i - 1][j - 1] >= MIN_SIM) best = Math.max(best, dp[i - 1][j - 1] + sim[i - 1][j - 1])
      dp[i][j] = best
    }
  }
  const pairs = new Array(n).fill(-1)
  const usedIr = new Set()
  {
    let i = n, j = m
    while (i > 0 && j > 0) {
      if (sim[i - 1][j - 1] >= MIN_SIM && Math.abs(dp[i][j] - (dp[i - 1][j - 1] + sim[i - 1][j - 1])) < 1e-12) {
        pairs[i - 1] = j - 1
        usedIr.add(j - 1)
        i--; j--
      } else if (dp[i - 1][j] >= dp[i][j - 1]) i--
      else j--
    }
  }
  // 분할표 병합 보정: 미매칭 ref ↔ 연속 미매칭 IR 2~3개 행방향 병합
  const merged = new Map() // refIdx → [irIdx...]
  for (let i = 0; i < n; i++) {
    if (pairs[i] !== -1) continue
    const ref = refTables[i]
    for (let j = 0; j + 1 < m; j++) {
      if (usedIr.has(j) || usedIr.has(j + 1)) continue
      for (let k = 2; k <= 3 && j + k <= m; k++) {
        const grp = []
        let ok = true, rowsSum = 0
        for (let q = j; q < j + k; q++) {
          if (usedIr.has(q)) { ok = false; break }
          grp.push(irGrids[q]); rowsSum += irGrids[q].rows
        }
        if (!ok) continue
        if (rowsSum === ref.rows && grp.every(g => g.cols === ref.cols)) {
          const mergedGrid = mergeGrids(grp)
          if (bagSim(refBags[i], cellTextBag(mergedGrid)) >= MIN_SIM) {
            merged.set(i, { irIdxs: grp.map((_, q) => j + q), grid: mergedGrid })
            for (let q = j; q < j + k; q++) usedIr.add(q)
            break
          }
        }
      }
      if (merged.has(i)) break
    }
  }
  return { pairs, merged, usedIr }
}

function mergeGrids(grids) {
  const cols = grids[0].cols
  let rows = 0
  const anchors = []
  for (const g of grids) {
    for (const a of g.anchors) anchors.push({ ...a, r: a.r + rows })
    rows += g.rows
  }
  return { rows, cols, anchors }
}

const tupleKey = a => `${a.r},${a.c},${a.rs},${a.cs}`

/**
 * 표 채점 본체.
 * refTables: ref 추출기의 전체 표 목록 — 중첩표 포함 (post-order = collectIrGrids 순서)
 * 반환: 표 단위 exact, 셀 단위 F1(GriTS-Top 등가), 셀 내용 exact/NED + 상세
 */
export function scoreTables(refTables, irGrids) {
  const { pairs, merged, usedIr } = matchTables(refTables, irGrids)
  const details = []
  let exactCount = 0
  const f1s = []
  let cellTotal = 0, cellExact = 0
  let contentNum = 0, contentDen = 0
  let splitTables = 0

  for (let i = 0; i < refTables.length; i++) {
    const ref = refTables[i]
    let ir = pairs[i] !== -1 ? irGrids[pairs[i]] : null
    let wasMerged = false
    if (!ir && merged.has(i)) {
      ir = merged.get(i).grid
      wasMerged = true
      splitTables++
    }

    const refSet = new Map(ref.cells.map(a => [tupleKey(a), a]))
    const irSet = ir ? new Map(ir.anchors.map(a => [tupleKey(a), a])) : new Map()
    let inter = 0
    for (const k of refSet.keys()) if (irSet.has(k)) inter++
    const f1 = (2 * inter) / Math.max(1, refSet.size + irSet.size)
    f1s.push(f1)
    const exact = !!ir && !wasMerged && ref.rows === ir.rows && ref.cols === ir.cols
      && inter === refSet.size && refSet.size === irSet.size
    if (exact) exactCount++

    // 셀 내용 — 좌표(r,c) 대응
    const irByPos = new Map()
    if (ir) for (const a of ir.anchors) irByPos.set(`${a.r},${a.c}`, a)
    const cellMisses = []
    for (const rc of ref.cells) {
      const ic = irByPos.get(`${rc.r},${rc.c}`)
      // 공백은 신뢰 불가(파서 균등배분 결합·셀 내 개행 등) → spaceless 비교 (pitfall #9)
      const a = normKey(rc.text)
      const b = normKey(ic?.text ?? "")
      cellTotal++
      const maxLen = Math.max(a.length, b.length, 1)
      // 중첩표 보유 셀도 일반 비교 — irAnchors가 부모 셀 "자기 텍스트"만 추출하므로(v3.0)
      // 양쪽 모두 중첩표 텍스트가 제외된 동일 경계다 (자식 그리드에서 별도 채점).
      let dist
      if (a === b) { cellExact++; dist = 0 }
      else dist = levBand(a, b, Math.min(maxLen, 4000))
      contentNum += maxLen - Math.min(dist, maxLen)
      contentDen += maxLen
      if (dist > 0) cellMisses.push({ r: rc.r, c: rc.c, ref: a.slice(0, 60), ir: ic ? b.slice(0, 60) : "(셀 없음)" })
    }

    details.push({
      refIdx: i,
      irIdx: pairs[i],
      merged: wasMerged,
      matched: !!ir,
      nested: !!ref.nested,
      refDims: `${ref.rows}x${ref.cols}`,
      irDims: ir ? `${ir.rows}x${ir.cols}` : null,
      exact, f1: +f1.toFixed(4),
      cellMisses: cellMisses.slice(0, 5),
      cellMissCount: cellMisses.length,
    })
  }

  return {
    tableCount: refTables.length,
    irTableCount: irGrids.length,
    exactCount,
    exactRate: refTables.length ? exactCount / refTables.length : 1,
    cellF1: f1s.length ? f1s.reduce((s, x) => s + x, 0) / f1s.length : 1,
    cellTotal, cellExact,
    cellExactRate: cellTotal ? cellExact / cellTotal : 1,
    contentNum, contentDen,
    contentNED: contentDen ? contentNum / contentDen : 1,
    splitTables,
    unmatchedRef: details.filter(d => !d.matched).length,
    unmatchedIr: irGrids.length - usedIr.size,
    details,
  }
}
