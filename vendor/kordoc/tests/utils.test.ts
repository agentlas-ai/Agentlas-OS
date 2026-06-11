import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { toArrayBuffer } from "../src/utils.js"

describe("toArrayBuffer", () => {
  it("Buffer를 독립 ArrayBuffer로 변환", () => {
    const buf = Buffer.from("hello")
    const ab = toArrayBuffer(buf)
    assert.ok(ab instanceof ArrayBuffer)
    assert.equal(ab.byteLength, 5)
    assert.equal(new TextDecoder().decode(ab), "hello")
  })

  it("pool Buffer의 offset 처리", () => {
    // Buffer.alloc(1024)에서 slice하면 offset > 0
    const big = Buffer.alloc(1024)
    big.write("test", 512)
    const slice = big.subarray(512, 516)

    const ab = toArrayBuffer(slice)
    assert.equal(ab.byteLength, 4)
    assert.equal(new TextDecoder().decode(ab), "test")
  })

  it("빈 Buffer", () => {
    const ab = toArrayBuffer(Buffer.alloc(0))
    assert.equal(ab.byteLength, 0)
  })
})
