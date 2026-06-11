/**
 * 서버리스/Node.js 환경에서 pdfjs-dist가 요구하는 브라우저 API polyfill.
 * pdfjs-dist import보다 먼저 실행되어야 함 (ES 모듈 호이스팅 대응으로 별도 파일 분리).
 *
 * 1. DOMMatrix / Path2D polyfill — pdfjs-dist가 참조하지만 Node.js에 없음
 * 2. pdfjsWorker 사전 주입 — fake worker의 동적 import를 우회
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const g = globalThis as any

if (typeof g.DOMMatrix === "undefined") {
  g.DOMMatrix = class DOMMatrix {
    m: number[] = [1, 0, 0, 1, 0, 0]
    constructor(init?: number[]) { if (init) this.m = init }
  }
}

if (typeof g.Path2D === "undefined") {
  g.Path2D = class Path2D {}
}

// worker 모듈 static import → fake worker가 동적 import를 건너뜀
// @ts-expect-error pdfjs-dist worker has no type declarations
import * as pdfjsWorker from "pdfjs-dist/legacy/build/pdf.worker.mjs"
g.pdfjsWorker = pdfjsWorker
