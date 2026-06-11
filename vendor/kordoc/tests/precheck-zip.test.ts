/**
 * precheckZipSize 단위 테스트 — EOCD/CD 파싱, 경계 조건, 악성 입력 방어
 */

import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { precheckZipSize, parseHwpxDocument } from "../src/hwpx/parser.js"

// ─── 헬퍼: 최소 유효 ZIP 생성 (빈 ZIP) ──────────────────

function makeMinimalZip(entries: { name: string; uncompressedSize: number }[]): ArrayBuffer {
  const parts: Buffer[] = []
  const cdEntries: Buffer[] = []
  let localOffset = 0

  for (const entry of entries) {
    const nameBytes = Buffer.from(entry.name, "utf-8")
    // Local File Header (30 + nameLen)
    const lfh = Buffer.alloc(30 + nameBytes.length)
    lfh.writeUInt32LE(0x04034b50, 0)     // PK\x03\x04
    lfh.writeUInt16LE(20, 4)              // version needed
    lfh.writeUInt32LE(0, 18)              // compressed size = 0
    lfh.writeUInt32LE(entry.uncompressedSize, 22)  // uncompressed size
    lfh.writeUInt16LE(nameBytes.length, 26)
    nameBytes.copy(lfh, 30)
    parts.push(lfh)

    // Central Directory entry (46 + nameLen)
    const cd = Buffer.alloc(46 + nameBytes.length)
    cd.writeUInt32LE(0x02014b50, 0)       // PK\x01\x02
    cd.writeUInt16LE(20, 4)               // version made by
    cd.writeUInt16LE(20, 6)               // version needed
    cd.writeUInt32LE(0, 20)               // compressed size = 0
    cd.writeUInt32LE(entry.uncompressedSize, 24)  // uncompressed size
    cd.writeUInt16LE(nameBytes.length, 28)
    cd.writeUInt32LE(localOffset, 42)     // relative offset of local header
    nameBytes.copy(cd, 46)
    cdEntries.push(cd)

    localOffset += lfh.length
  }

  const cdOffset = localOffset
  const cdBuf = Buffer.concat(cdEntries)
  const cdSize = cdBuf.length

  // End of Central Directory (22 bytes)
  const eocd = Buffer.alloc(22)
  eocd.writeUInt32LE(0x06054b50, 0)       // PK\x05\x06
  eocd.writeUInt16LE(entries.length, 8)   // total entries on disk
  eocd.writeUInt16LE(entries.length, 10)  // total entries
  eocd.writeUInt32LE(cdSize, 12)          // CD size
  eocd.writeUInt32LE(cdOffset, 16)        // CD offset

  const full = Buffer.concat([...parts, cdBuf, eocd])
  return full.buffer.slice(full.byteOffset, full.byteOffset + full.byteLength)
}

// ─── 테스트 ──────────────────────────────────────────────

describe("precheckZipSize", () => {
  it("유효한 ZIP: 엔트리 수와 비압축 크기 정확히 반환", () => {
    const zip = makeMinimalZip([
      { name: "a.xml", uncompressedSize: 1000 },
      { name: "b.xml", uncompressedSize: 2000 },
    ])
    const result = precheckZipSize(zip)
    assert.equal(result.entryCount, 2)
    assert.equal(result.totalUncompressed, 3000)
  })

  it("빈 ZIP (엔트리 0개)", () => {
    const zip = makeMinimalZip([])
    const result = precheckZipSize(zip)
    assert.equal(result.entryCount, 0)
    assert.equal(result.totalUncompressed, 0)
  })

  it("빈 버퍼 → 안전한 기본값 반환", () => {
    const result = precheckZipSize(new ArrayBuffer(0))
    assert.equal(result.totalUncompressed, 0)
    assert.equal(result.entryCount, 0)
  })

  it("22바이트 미만 버퍼 → 안전한 기본값 (RangeError 없음)", () => {
    const result = precheckZipSize(new ArrayBuffer(10))
    assert.equal(result.totalUncompressed, 0)
    assert.equal(result.entryCount, 0)
  })

  it("EOCD 시그니처 없는 버퍼 → 안전한 기본값", () => {
    const buf = Buffer.alloc(100, 0xff)
    const result = precheckZipSize(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength))
    assert.equal(result.totalUncompressed, 0)
    assert.equal(result.entryCount, 0)
  })

  it("CD offset이 버퍼 범위 초과 → entryCount만 반환, totalUncompressed=0", () => {
    // EOCD를 수동 생성하되 cdOffset을 큰 값으로 설정
    const eocd = Buffer.alloc(22)
    eocd.writeUInt32LE(0x06054b50, 0)
    eocd.writeUInt16LE(1, 10)             // 1 entry
    eocd.writeUInt32LE(100, 12)           // cdSize
    eocd.writeUInt32LE(99999, 16)         // cdOffset — 범위 초과
    const result = precheckZipSize(eocd.buffer.slice(eocd.byteOffset, eocd.byteOffset + eocd.byteLength))
    assert.equal(result.entryCount, 1)
    assert.equal(result.totalUncompressed, 0)
  })

  it("거짓 비압축 크기 선언 → precheck는 그대로 신뢰 (한계)", () => {
    // 공격자가 CD에 비압축 크기를 1로 거짓 기재한 경우
    const zip = makeMinimalZip([
      { name: "bomb.bin", uncompressedSize: 1 },  // 실제로는 1GB일 수 있음
    ])
    const result = precheckZipSize(zip)
    assert.equal(result.totalUncompressed, 1)  // precheck는 속음 — 이것이 문서화된 한계
  })

  it("CD 시그니처가 잘못된 경우 조기 중단", () => {
    const zip = makeMinimalZip([
      { name: "a.xml", uncompressedSize: 500 },
      { name: "b.xml", uncompressedSize: 500 },
    ])
    // CD 시작 위치의 시그니처를 변조
    const buf = Buffer.from(zip)
    // CD는 Local File Headers 다음에 오므로, 첫 CD entry의 시그니처 위치 찾기
    const eocdOffset = buf.length - 22
    const cdOffset = buf.readUInt32LE(eocdOffset + 16)
    buf.writeUInt32LE(0xdeadbeef, cdOffset)  // 잘못된 시그니처

    const result = precheckZipSize(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength))
    assert.equal(result.entryCount, 2)      // EOCD에서 읽은 값
    assert.equal(result.totalUncompressed, 0) // CD 파싱 조기 중단
  })
})

// ─── 간접 통합 테스트: parseHwpxDocument를 통한 방어 검증 ──────

describe("precheckZipSize — parseHwpxDocument 간접 검증", () => {
  it("CD 선언 비압축 크기 초과 → ZIP bomb 에러", async () => {
    // CD에 비압축 크기를 200MB로 선언한 ZIP 생성
    const zip = makeMinimalZip([
      { name: "section0.xml", uncompressedSize: 200 * 1024 * 1024 },
    ])
    await assert.rejects(
      () => parseHwpxDocument(zip),
      (err: Error) => err.message.includes("ZIP 비압축 크기 초과"),
    )
  })

  it("CD 엔트리 수 초과 → ZIP bomb 에러", async () => {
    // 501개 엔트리를 CD에 선언한 ZIP 생성
    const entries = Array.from({ length: 501 }, (_, i) => ({
      name: `f${i}.xml`,
      uncompressedSize: 100,
    }))
    const zip = makeMinimalZip(entries)
    await assert.rejects(
      () => parseHwpxDocument(zip),
      (err: Error) => err.message.includes("ZIP 엔트리 수 초과"),
    )
  })
})
