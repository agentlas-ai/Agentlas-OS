/** OCR 프로바이더 인터페이스 테스트 (mock 기반) */

import { describe, it } from "node:test"
import assert from "node:assert/strict"
import type { OcrProvider } from "../src/types.js"

describe("OcrProvider 인터페이스", () => {
  it("타입 호환성 — async 함수로 구현 가능", async () => {
    const mockProvider: OcrProvider = async (pageImage, pageNumber, mimeType) => {
      assert.ok(pageImage instanceof Uint8Array || pageImage.length >= 0)
      assert.equal(typeof pageNumber, "number")
      assert.equal(mimeType, "image/png")
      return `페이지 ${pageNumber}의 OCR 결과`
    }

    const result = await mockProvider(new Uint8Array([1, 2, 3]), 1, "image/png")
    assert.equal(result, "페이지 1의 OCR 결과")
  })

  it("에러 throw 가능", async () => {
    const failProvider: OcrProvider = async () => {
      throw new Error("OCR 서비스 연결 실패")
    }

    await assert.rejects(
      () => failProvider(new Uint8Array([]), 1, "image/png"),
      (err: Error) => err.message.includes("OCR 서비스 연결 실패")
    )
  })

  it("빈 결과 반환 가능", async () => {
    const emptyProvider: OcrProvider = async () => ""
    const result = await emptyProvider(new Uint8Array([]), 1, "image/png")
    assert.equal(result, "")
  })
})
