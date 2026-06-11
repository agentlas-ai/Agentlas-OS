// PDF 교차검증 — pdftotext(poppler) + pdfjs raw 의 '합의(consensus)' 3-gram 대비 커버리지.
// 두 추출기가 모두 동의한 내용만 신뢰 기준으로 쓰고(pitfall #12), 읽기 순서는
// 추출기마다 달라 n-gram bag 비교만 수행한다 (순서 비교 금지).

import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { normPdf, normText } from "../lib/normalize.mjs"

const execFileP = promisify(execFile)
const PDFTOTEXT_CANDIDATES = ["/opt/homebrew/bin/pdftotext", "pdftotext"]

let pdftotextBin = null
async function resolvePdftotext() {
  if (pdftotextBin !== null) return pdftotextBin
  for (const bin of PDFTOTEXT_CANDIDATES) {
    try {
      await execFileP(bin, ["-v"])
      pdftotextBin = bin
      return bin
    } catch (err) {
      if (err?.stderr?.includes("pdftotext version")) { pdftotextBin = bin; return bin }
    }
  }
  pdftotextBin = false
  return false
}

/** pdftotext — 페이지별 텍스트 (form-feed 구분) */
async function pdftotextPages(filePath) {
  const bin = await resolvePdftotext()
  if (!bin) return null
  try {
    const { stdout } = await execFileP(bin, ["-enc", "UTF-8", "-q", filePath, "-"], {
      maxBuffer: 256 * 1024 * 1024,
    })
    const pages = stdout.split("\f")
    if (pages[pages.length - 1] === "") pages.pop()
    return pages
  } catch {
    return null
  }
}

let pdfjsMod = null
async function loadPdfjs() {
  if (pdfjsMod !== null) return pdfjsMod
  try {
    pdfjsMod = await import("pdfjs-dist/legacy/build/pdf.mjs")
  } catch {
    pdfjsMod = false
  }
  return pdfjsMod
}

/** pdfjs getTextContent raw — 페이지별 텍스트 */
async function pdfjsPages(buffer) {
  const pdfjs = await loadPdfjs()
  if (!pdfjs) return null
  let doc
  try {
    doc = await pdfjs.getDocument({
      // 독립 ArrayBuffer로 복사 — kordoc parse가 원본을 detach해도 안전
      data: Uint8Array.from(buffer),
      disableFontFace: true,
      isEvalSupported: false,
      useSystemFonts: true,
      verbosity: 0,
    }).promise
  } catch {
    return null
  }
  const pages = []
  try {
    for (let p = 1; p <= doc.numPages; p++) {
      try {
        const page = await doc.getPage(p)
        const tc = await page.getTextContent()
        pages.push(tc.items.map(it => it.str + (it.hasEOL ? "\n" : " ")).join(""))
        page.cleanup()
      } catch {
        pages.push("")
      }
    }
  } finally {
    await doc.destroy().catch(() => {})
  }
  return pages
}

/** 전 페이지 반복 라인(머리글/바닥글) 제거 — ≥ratio 페이지에 등장하는 정규화 라인 (pitfall #13) */
function dropRepeatedLines(pages, ratio = 0.7) {
  if (pages.length < 3) return pages
  const lineCount = new Map()
  const norm = l => normText(l).replace(/\d+/g, "#") // 페이지번호 가변부 무시
  for (const pg of pages) {
    const seen = new Set()
    for (const line of pg.split("\n")) {
      const k = norm(line)
      if (k.length >= 2 && !seen.has(k)) { seen.add(k); lineCount.set(k, (lineCount.get(k) ?? 0) + 1) }
    }
  }
  const threshold = Math.ceil(pages.length * ratio)
  const repeated = new Set([...lineCount.entries()].filter(([, n]) => n >= threshold).map(([k]) => k))
  if (repeated.size === 0) return pages
  return pages.map(pg => pg.split("\n").filter(l => !repeated.has(norm(l))).join("\n"))
}

/** 문자 3-gram multiset (normPdf 적용 후) — Map<gram, count> */
function trigramBag(texts) {
  const bag = new Map()
  for (const t of texts) {
    const s = normPdf(t)
    for (let i = 0; i + 3 <= s.length; i++) {
      const g = s.substr(i, 3)
      bag.set(g, (bag.get(g) ?? 0) + 1)
    }
  }
  return bag
}

function intersectBag(a, b) {
  const out = new Map()
  const [small, big] = a.size <= b.size ? [a, b] : [b, a]
  for (const [k, n] of small) {
    const m = big.get(k)
    if (m) out.set(k, Math.min(n, m))
  }
  return out
}

const bagSize = bag => { let s = 0; for (const n of bag.values()) s += n; return s }

/**
 * PDF 교차검증 커버리지.
 * @param filePath PDF 경로 (pdftotext용)
 * @param buffer   PDF 버퍼 (pdfjs용)
 * @param kordocPlainText kordoc 마크다운의 평문 (mdToPlain 적용 후)
 * @param needsOcrPages   kordoc pageQuality 기준 OCR 필요 페이지 집합(1-based) — 모수 격리 (pitfall #14)
 */
export async function pdfCrossCoverage(filePath, buffer, kordocPlainText, needsOcrPages = new Set()) {
  const [popplerPages, pdfjsPagesArr] = await Promise.all([
    pdftotextPages(filePath),
    pdfjsPages(buffer),
  ])

  if (!popplerPages && !pdfjsPagesArr) {
    return { status: "no-reference", coverage: null, weak: true }
  }

  const filterOcr = pages =>
    pages ? pages.filter((_, i) => !needsOcrPages.has(i + 1)) : null

  const a = popplerPages ? dropRepeatedLines(filterOcr(popplerPages)) : null
  const b = pdfjsPagesArr ? dropRepeatedLines(filterOcr(pdfjsPagesArr)) : null

  let consensus
  let weak = false
  if (a && b) {
    consensus = intersectBag(trigramBag(a), trigramBag(b))
  } else {
    consensus = trigramBag(a ?? b)
    weak = true // 단일 추출기 — 보고만, 게이트 제외
  }

  const consensusSize = bagSize(consensus)
  if (consensusSize < 50) {
    return { status: "tiny-consensus", coverage: null, weak: true, consensusSize }
  }

  const kordocBag = trigramBag([kordocPlainText])
  const covered = bagSize(intersectBag(kordocBag, consensus))
  const coverage = covered / consensusSize

  // 미커버 3-gram 상위 샘플 (디버깅용)
  const missing = []
  for (const [g, n] of consensus) {
    const have = kordocBag.get(g) ?? 0
    if (have < n) missing.push([g, n - have])
  }
  missing.sort((x, y) => y[1] - x[1])

  return {
    status: "ok",
    coverage,
    weak,
    consensusSize,
    coveredSize: covered,
    excludedOcrPages: [...needsOcrPages],
    topMissing: missing.slice(0, 10).map(([g, n]) => `${g}×${n}`),
  }
}
