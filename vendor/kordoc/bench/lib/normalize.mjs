// 정규화 — 채점 전 양쪽(참조/출력)에 동일 적용. 비대칭 정규화 금지 (pitfall #9).
//
// normText: 사람이 읽을 수 있는 형태 유지 (공백 1칸으로 붕괴) — 셀 내용 NED·스니펫용
// normKey : normText에서 공백 전부 제거 — 정렬(align) 매칭 키.
//           공백 제거 이유: 파서의 균등배분 결합("현 장" → "현장"), lineBreak 무공백 연결,
//           탭/전각공백 변환 차이를 전부 흡수. 양쪽 동일 적용이라 가짜 일치 위험은
//           유닛 경계에 한정되며 무시 가능 수준.

/** 마크다운 이스케이프 역변환 (\| \* \~ \[ 등) */
export function unescapeMd(s) {
  return s.replace(/\\([\\`*_{}[\]()#+\-.!|>~])/g, "$1")
}

// ─── 한컴 PUA → 표준 유니코드 매핑 (파서 정책 미러 — whitelist: pua-map) ───
// 파서는 src/shared/pua.ts(mapPuaText, rhwp 시각 검증 테이블)로 PUA 글머리표를 매핑해
// 출력한다. 참조 텍스트에도 동일 매핑을 적용해야 정규화가 대칭이 된다 (pitfall #9).
// 데이터 출처: rhwp paragraph_layout.rs map_pua_bullet_char (MIT) — 코드 공유가 아닌
// 동일한 외부 검증 데이터의 미러. 매핑 없는 BMP PUA는 원본 유지(한양PUA 옛한글 가능성).
const PUA_BMP = {
  0x6c: "●", 0x6d: "●", 0x6e: "■", 0x6f: "□", 0x70: "□", 0x71: "□", 0x72: "□",
  0x73: "⬧", 0x74: "⧫", 0x75: "◆", 0x76: "❖", 0x77: "⬥",
  0x9e: "·", 0x9f: "•", 0xa0: "·", 0xa1: "⚪", 0xa2: "○", 0xa3: "○", 0xa4: "◉",
  0xa5: "◎", 0xa7: "▪", 0xa8: "◻", 0xaa: "✦", 0xab: "★", 0xac: "✶", 0xad: "✴", 0xae: "✹",
  0x45: "☜", 0x46: "☞", 0x47: "☝", 0x48: "☟",
  0xfb: "✗", 0xfc: "✔", 0xfd: "☒", 0xfe: "☑",
  0xe8: "➔", 0xef: "⇦", 0xf0: "⇨", 0xf1: "⇧", 0xf2: "⇩",
  0x22: "✂", 0x36: "⌛", 0x4a: "☺", 0x4e: "☠", 0x52: "☼", 0x54: "❄", 0x58: "✠", 0x59: "✡",
}
const PUA_SUPP = {
  0xf003b: "↓", 0xf02ef: "·", 0xf0854: "《", 0xf0855: "》",
  0xf00da: "▸", 0xf080f: "━", 0xf0827: "■",
}

function mapPua(s) {
  if (!/[\uF020-\uF0FF\u{F0000}-\u{F09FF}]/u.test(s)) return s
  let out = ""
  for (const ch of s) {
    const code = ch.codePointAt(0)
    if (code >= 0xf020 && code <= 0xf0ff) out += PUA_BMP[code - 0xf000] ?? ch
    else if (code >= 0xf0000 && code <= 0xf09ff) out += PUA_SUPP[code] ?? ch
    else out += ch
  }
  return out
}

const ZERO_WIDTH_RE = /[\u200B-\u200F\u2028\u2029\u2060\uFEFF\u00AD\x00-\x08\x0B\x0C\x0E-\x1F]/g
const SPACE_RE = /[\s\u00A0\u3000]+/g

export function normText(s) {
  if (!s) return ""
  return mapPua(s)
    .normalize("NFC")
    // 매핑 안 된 Supplementary PUA — 파서가 의도 제거 (builder sanitizeText와 대칭)
    .replace(/[\u{F0000}-\u{FFFFD}]/gu, "")
    // zero-width, BOM, soft hyphen, 제어문자(\x1F 리더탭 마커 포함; \n \t는 아래 공백 처리)
    .replace(ZERO_WIDTH_RE, "")
    // 모든 공백류(전각공백 U+3000, NBSP 포함) → 단일 공백
    .replace(SPACE_RE, " ")
    .trim()
}

export function normKey(s) {
  return normText(s).replace(/ /g, "")
}

/**
 * kordoc 마크다운 → 본문 평문.
 * 마크다운 문법 토큰과 "의도적 아티팩트"(중첩표 마커, 이미지 참조)를 제거하고
 * 수식 $...$ 블록은 개수만 센 뒤 제거(presence 채점 분리 — pitfall #5).
 */
export function mdToPlain(md) {
  let eqCount = 0
  let footnoteCount = 0
  let s = md ?? ""

  // 이미지 참조 ![image](file) — GFM 표 셀/본문 인라인 (whitelist: img-inline)
  s = s.replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
  // HTML 표 셀 내 인라인 이미지 <img src="..." alt="image"> — v3.0 (whitelist: img-inline)
  s = s.replace(/<img\b[^>]*>/gi, " ")
  // 의도적 아티팩트: 중첩 테이블 마커, 누락 이미지 플레이스홀더
  s = s.replace(/\[중첩 테이블[^\]\n]*\]/g, " ")
  s = s.replace(/\[이미지:[^\]\n]*\]/g, " ")

  // 수식: $$...$$ → $...$ 순서로 카운트 후 제거
  s = s.replace(/\$\$[^$]+\$\$/g, () => { eqCount++; return " " })
  s = s.replace(/(^|[^\\$])\$(?!\s)((?:\\.|[^$\n])+?)\$/g, (_m, pre) => { eqCount++; return pre + " " })

  // 각주 인라인 "(주: ...)" — 개수만 셈 (텍스트는 본문에 남겨 recall 매칭 가능하게)
  footnoteCount = (s.match(/\(주: /g) ?? []).length
  s = s.replace(/\(주: /g, " (")

  // HTML 테이블 태그(병합표 출력) + <br>
  s = s.replace(/<\/?(?:table|thead|tbody|tr|td|th)\b[^>]*>/gi, " ")
  s = s.replace(/<br\s*\/?>/gi, "\n")

  // 표 구분행 | --- | --- |
  s = s.replace(/^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$/gm, " ")
  // 링크 [text](url) → text — kordoc이 생성하는 스킴(sanitizeHref)만.
  // 본문 평문에 우연히 [라벨](식별자) 꼴이 있으면 (예: "[국민신문고](SPP-...)")
  // 링크가 아니므로 보존해야 한다.
  s = s.replace(/\[([^\]]*)\]\((?:https?:|mailto:|tel:|#)[^)\s]*\)/gi, "$1")
  // 파이프 (이스케이프 \| 보호)
  s = s.replace(/\\\|/g, "\x01").replace(/\|/g, " ").replace(/\x01/g, "|")
  // 헤딩 prefix, 수평선
  s = s.replace(/^#{1,6}\s+/gm, "")
  s = s.replace(/^\s*---\s*$/gm, " ")
  // 굵게/기울임 래퍼(**, *)는 굳이 제거하지 않는다.
  // 래핑된 본문은 정렬 시 부분 문자열로 그대로 매칭되고, 잔여 별표는 구두점이라
  // phantom(문자/숫자만 카운트)에 포함되지 않는다. 정규식 unwrap은 리터럴 별표
  // 마스킹('****9****' 결재문서 등)을 훼손하므로 사용하지 않는다.
  // 마크다운 이스케이프 역변환
  s = unescapeMd(s)

  return { text: s, eqCount, footnoteCount }
}

/** PDF 추출 텍스트 공통 정규화 — 리거처 분해 + 하이픈 줄바꿈 결합 + normKey */
export function normPdf(s) {
  if (!s) return ""
  return normKey(
    s
      .replace(/ﬁ/g, "fi").replace(/ﬂ/g, "fl").replace(/ﬀ/g, "ff")
      .replace(/ﬃ/g, "ffi").replace(/ﬄ/g, "ffl")
      .replace(/(\S)-[ \t]*\n[ \t]*(?=[a-z가-힣])/g, "$1")
  )
}
