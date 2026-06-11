import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { detectFormat, isHwpxFile, isOldHwpFile, isPdfFile } from "../src/detect.js"

describe("detectFormat", () => {
  it("ZIP 매직바이트(PK\\x03\\x04)를 hwpx로 감지", () => {
    const buf = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0, 0, 0, 0]).buffer
    assert.equal(detectFormat(buf), "hwpx")
    assert.equal(isHwpxFile(buf), true)
    assert.equal(isOldHwpFile(buf), false)
    assert.equal(isPdfFile(buf), false)
  })

  it("OLE2 매직바이트(\\xD0\\xCF\\x11\\xE0)를 hwp로 감지", () => {
    const buf = new Uint8Array([0xd0, 0xcf, 0x11, 0xe0, 0, 0, 0, 0]).buffer
    assert.equal(detectFormat(buf), "hwp")
    assert.equal(isOldHwpFile(buf), true)
  })

  it("%PDF 매직바이트를 pdf로 감지", () => {
    const buf = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34]).buffer
    assert.equal(detectFormat(buf), "pdf")
    assert.equal(isPdfFile(buf), true)
  })

  it("알 수 없는 바이트는 unknown 반환", () => {
    const buf = new Uint8Array([0xff, 0xfe, 0x00, 0x00]).buffer
    assert.equal(detectFormat(buf), "unknown")
  })

  it("빈 버퍼도 unknown 반환 (크래시 없음)", () => {
    const buf = new ArrayBuffer(0)
    assert.equal(detectFormat(buf), "unknown")
  })

  it("3바이트 미만 버퍼도 안전하게 처리", () => {
    const buf = new Uint8Array([0x50, 0x4b]).buffer
    assert.equal(detectFormat(buf), "unknown")
  })
})
