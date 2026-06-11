/** Watch 모드 유닛 테스트 — WatchOptions 타입 검증 */

import { describe, it } from "node:test"
import assert from "node:assert/strict"
import type { WatchOptions } from "../src/types.js"

describe("WatchOptions 타입", () => {
  it("필수 필드만으로 유효", () => {
    const opts: WatchOptions = { dir: "./incoming" }
    assert.equal(opts.dir, "./incoming")
    assert.equal(opts.outDir, undefined)
    assert.equal(opts.webhook, undefined)
  })

  it("모든 필드 지정 가능", () => {
    const opts: WatchOptions = {
      dir: "./incoming",
      outDir: "./output",
      webhook: "https://api.example.com/hook",
      format: "json",
      pages: "1-3",
      silent: true,
    }
    assert.equal(opts.format, "json")
    assert.equal(opts.pages, "1-3")
    assert.equal(opts.silent, true)
  })
})
