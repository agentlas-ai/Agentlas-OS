/**
 * CI용 더미 fixture 생성 스크립트
 * 실행: npx tsx tests/fixtures/generate.ts
 *
 * 실제 한컴오피스 문서가 아닌, 프로그래밍적으로 생성한 최소 유효 문서.
 * 저장소에 커밋하여 CI에서도 통합 테스트가 skip 없이 동작하도록 함.
 */

import JSZip from "jszip"
import { writeFileSync } from "fs"
import { resolve, dirname } from "path"
import { fileURLToPath } from "url"

const __dirname = dirname(fileURLToPath(import.meta.url))

async function generateHwpx() {
  const zip = new JSZip()

  const sectionXml = `<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2016/HwpMl"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2016/HwpMl">
  <hp:p><hp:run><hp:t>서면자문 의견서</hp:t></hp:run></hp:p>
  <hp:p><hp:run><hp:t>1. 자문 개요</hp:t></hp:run></hp:p>
  <hp:p><hp:run><hp:t>본 의견서는 테스트 목적으로 작성된 더미 문서입니다.</hp:t></hp:run></hp:p>
  <hp:tbl>
    <hp:tr>
      <hp:tc><hp:cellSpan colSpan="1" rowSpan="1" /><hp:p><hp:run><hp:t>항목</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:cellSpan colSpan="1" rowSpan="1" /><hp:p><hp:run><hp:t>내용</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc><hp:cellSpan colSpan="1" rowSpan="1" /><hp:p><hp:run><hp:t>자문위원</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:cellSpan colSpan="1" rowSpan="1" /><hp:p><hp:run><hp:t>홍길동</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
  </hp:tbl>
  <hp:p><hp:run><hp:t>2. 자문 의견</hp:t></hp:run></hp:p>
  <hp:p><hp:run><hp:t>해당 사업은 적정하게 추진되고 있으며, 향후 보완이 필요합니다.</hp:t></hp:run></hp:p>
</hs:sec>`

  const manifest = `<?xml version="1.0" encoding="UTF-8"?>
<opf:package xmlns:opf="http://www.idpf.org/2007/opf">
  <opf:manifest>
    <opf:item id="s0" href="section0.xml" media-type="application/xml" />
  </opf:manifest>
  <opf:spine>
    <opf:itemref idref="s0" />
  </opf:spine>
</opf:package>`

  zip.file("Contents/content.hpf", manifest)
  zip.file("Contents/section0.xml", sectionXml)

  const buf = await zip.generateAsync({ type: "nodebuffer" })
  writeFileSync(resolve(__dirname, "dummy.hwpx"), buf)
  console.log("generated: dummy.hwpx")
}

generateHwpx()
