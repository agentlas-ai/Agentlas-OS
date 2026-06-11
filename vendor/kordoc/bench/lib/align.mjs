// 정렬 엔진 — 2-포인터 그리디 + consume 마스킹(multiset 보장, pitfall #11) + 부분 점수.
//
// 마스킹은 문자열 치환 대신 "소비 구간(interval)" 집합으로 구현 — O(n) 복사 없이
// indexOf 탐색 시 소비 구간과 겹치면 다음 위치로 건너뛴다.

/** 밴드 Levenshtein — O(n*d). maxDist 초과 시 maxDist+1 반환 */
export function levBand(a, b, maxDist = Infinity) {
  if (a === b) return 0
  const n = a.length, m = b.length
  if (n === 0) return m
  if (m === 0) return n
  if (Math.abs(n - m) > maxDist) return maxDist + 1
  const d = Math.min(maxDist, Math.max(n, m))
  // band 폭 2d+1
  const INF = d + 1
  let prev = new Float64Array(m + 1).fill(INF)
  let cur = new Float64Array(m + 1).fill(INF)
  for (let j = 0; j <= Math.min(m, d); j++) prev[j] = j
  for (let i = 1; i <= n; i++) {
    const lo = Math.max(1, i - d), hi = Math.min(m, i + d)
    cur.fill(INF)
    if (i - d <= 0) cur[0] = i
    let rowMin = INF
    for (let j = lo; j <= hi; j++) {
      const cost = a.charCodeAt(i - 1) === b.charCodeAt(j - 1) ? 0 : 1
      let v = prev[j - 1] + cost
      const del = prev[j] + 1
      if (del < v) v = del
      const ins = cur[j - 1] + 1
      if (ins < v) v = ins
      cur[j] = Math.min(v, INF)
      if (cur[j] < rowMin) rowMin = cur[j]
    }
    if (i - d <= 0 && cur[0] < rowMin) rowMin = cur[0]
    if (rowMin > d) return d + 1
    ;[prev, cur] = [cur, prev]
  }
  const res = prev[m]
  return res > d ? d + 1 : res
}

/** 배열(ID 시퀀스) Levenshtein — order NED용 */
export function levArr(a, b) {
  const n = a.length, m = b.length
  if (n === 0) return m
  if (m === 0) return n
  let prev = new Int32Array(m + 1)
  let cur = new Int32Array(m + 1)
  for (let j = 0; j <= m; j++) prev[j] = j
  for (let i = 1; i <= n; i++) {
    cur[0] = i
    for (let j = 1; j <= m; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      cur[j] = Math.min(prev[j - 1] + cost, prev[j] + 1, cur[j - 1] + 1)
    }
    ;[prev, cur] = [cur, prev]
  }
  return prev[m]
}

/** ref와 ir(임의 부분 문자열) 간 semi-global 편집거리 — ir 양끝 잉여는 무비용 */
export function subLev(ref, hay) {
  const n = ref.length, m = hay.length
  if (n === 0) return 0
  if (m === 0) return n
  let prev = new Int32Array(m + 1) // 첫 행 0 (hay 접두 스킵 무비용)
  let cur = new Int32Array(m + 1)
  for (let i = 1; i <= n; i++) {
    cur[0] = i
    for (let j = 1; j <= m; j++) {
      const cost = ref.charCodeAt(i - 1) === hay.charCodeAt(j - 1) ? 0 : 1
      cur[j] = Math.min(prev[j - 1] + cost, prev[j] + 1, cur[j - 1] + 1)
    }
    ;[prev, cur] = [cur, prev]
  }
  let best = n
  for (let j = 0; j <= m; j++) if (prev[j] < best) best = prev[j]
  return best
}

/** Longest Increasing Subsequence 길이 — O(n log n) */
export function lisLength(arr) {
  const tails = []
  for (const x of arr) {
    let lo = 0, hi = tails.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (tails[mid] <= x) lo = mid + 1
      else hi = mid
    }
    tails[lo] = x
  }
  return tails.length
}

/** 소비 구간 추적 버퍼 */
export class ConsumeBuffer {
  constructor(text) {
    this.text = text
    this.intervals = [] // [start, end) 정렬 유지
  }

  _overlapIdx(start, end) {
    const iv = this.intervals
    let lo = 0, hi = iv.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (iv[mid][1] <= start) lo = mid + 1
      else hi = mid
    }
    if (lo < iv.length && iv[lo][0] < end) return lo
    return -1
  }

  isFree(start, end) {
    return this._overlapIdx(start, end) === -1
  }

  consume(start, end) {
    const iv = this.intervals
    let lo = 0, hi = iv.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (iv[mid][1] < start) lo = mid + 1
      else hi = mid
    }
    // merge adjacent/overlapping
    let s = start, e = end, del = 0
    while (lo + del < iv.length && iv[lo + del][0] <= e) {
      s = Math.min(s, iv[lo + del][0])
      e = Math.max(e, iv[lo + del][1])
      del++
    }
    iv.splice(lo, del, [s, e])
  }

  /** needle을 from 위치 이후 미소비 구간에서 탐색 */
  find(needle, from = 0) {
    let idx = this.text.indexOf(needle, from)
    while (idx !== -1) {
      const ov = this._overlapIdx(idx, idx + needle.length)
      if (ov === -1) return idx
      // 좌→우 탐색이므로 이 구간과 겹치지 않는 다음 후보는 구간 끝 이후뿐
      idx = this.text.indexOf(needle, this.intervals[ov][1])
    }
    return -1
  }

  consumedChars() {
    return this.intervals.reduce((s, [a, b]) => s + (b - a), 0)
  }

  /** 미소비 구간 목록 (스니펫 추출용) */
  unconsumed() {
    const out = []
    let pos = 0
    for (const [a, b] of this.intervals) {
      if (a > pos) out.push([pos, a])
      pos = Math.max(pos, b)
    }
    if (pos < this.text.length) out.push([pos, this.text.length])
    return out
  }
}

const MIN_FRAG = 3 // 부분 매칭 최소 조각 길이 (한글 3자 ≈ 의미 단위)

/**
 * 부분 매칭 — 유닛 t의 부분 문자열을 그리디로 최장 우선 소비.
 * Levenshtein 부분 점수와 등가의 "매칭 문자수"를 빠르게 근사하고,
 * 연속 누락 run(구조적 누락 신호)을 함께 산출한다.
 */
export function partialConsume(buf, t) {
  let matched = 0
  let runMiss = 0
  let curMissStart = -1
  let missRunBest = [0, 0]
  let firstPos = -1
  let i = 0
  while (i < t.length) {
    const L = longestMatchFrom(buf, t, i)
    if (L >= MIN_FRAG) {
      const idx = buf.find(t.substr(i, L))
      // (longestMatchFrom이 방금 확인했으므로 idx는 항상 유효)
      buf.consume(idx, idx + L)
      if (firstPos === -1) firstPos = idx
      matched += L
      if (curMissStart !== -1) {
        const len = i - curMissStart
        if (len > runMiss) { runMiss = len; missRunBest = [curMissStart, i] }
        curMissStart = -1
      }
      i += L
    } else {
      if (curMissStart === -1) curMissStart = i
      i++
    }
  }
  if (curMissStart !== -1) {
    const len = t.length - curMissStart
    if (len > runMiss) { runMiss = len; missRunBest = [curMissStart, t.length] }
  }
  const missSnippet = runMiss > 0 ? t.slice(missRunBest[0], Math.min(missRunBest[1], missRunBest[0] + 80)) : ""
  return { matched, runMiss, missSnippet, pos: firstPos }
}

/** t[i..] 의 접두사 중 buf 미소비 구간에 존재하는 최장 길이 (지수+이분 탐색) */
function longestMatchFrom(buf, t, i) {
  const maxLen = t.length - i
  if (maxLen < MIN_FRAG) {
    return buf.find(t.substr(i, maxLen)) !== -1 ? maxLen : 0
  }
  if (buf.find(t.substr(i, MIN_FRAG)) === -1) return 0
  // 지수 확장
  let lo = MIN_FRAG, hi = Math.min(maxLen, MIN_FRAG * 2)
  while (hi < maxLen && buf.find(t.substr(i, hi)) !== -1) {
    lo = hi
    hi = Math.min(maxLen, hi * 2)
  }
  if (buf.find(t.substr(i, hi)) !== -1) return hi
  // 이분 탐색: lo 가능, hi 불가능
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1
    if (buf.find(t.substr(i, mid)) !== -1) lo = mid
    else hi = mid
  }
  return lo
}

/**
 * 유닛 정렬 — units: [{id, kind, text(normKey 적용 전 원문 아님 — 호출측에서 normKey 적용)}]
 * mdKey: normKey 적용된 출력 평문.
 * 반환: perUnit 결과 + ConsumeBuffer (phantom 산출용 재사용)
 */
export function alignUnits(units, mdKey) {
  const buf = new ConsumeBuffer(mdKey)
  const perUnit = new Array(units.length)
  const pending = [] // 정확 매칭 실패한 긴 유닛 인덱스

  // 짧은 유닛(중복 빈도 높음: "위원", "1" 등)은 긴 유닛의 부분 매칭까지 끝난 뒤
  // 위치 인지(2-포인터) 탐색으로 처리 — 멀리 떨어진 동일 문구를 가로채 긴 유닛에
  // 거짓 miss + 그 자리 거짓 phantom 쌍을 만드는 것을 방지한다.
  const SHORT = 8
  const isShort = i => units[i].text.length > 0 && units[i].text.length < SHORT

  // ── Pass 1: 정확 매칭 (긴 유닛만, 긴 순) ──
  // 긴/고유 유닛이 영역을 먼저 차지하게 하여, 짧은 중복 조각이 긴 유닛의 유일 occurrence를
  // 가로채는 greedy 거짓-누락을 방지한다 (consume 마스킹으로 multiset 1:1은 유지).
  const order = units.map((_, i) => i).sort((a, b) => units[b].text.length - units[a].text.length)
  for (const i of order) {
    const u = units[i]
    const t = u.text
    if (!t) { perUnit[i] = { id: u.id, kind: u.kind, pos: -2, matched: 0, total: 0, runMiss: 0 }; continue }
    if (isShort(i)) continue
    const pos = buf.find(t, 0)
    if (pos !== -1) {
      buf.consume(pos, pos + t.length)
      perUnit[i] = { id: u.id, kind: u.kind, pos, matched: t.length, total: t.length, runMiss: 0 }
    } else {
      pending.push(i)
    }
  }

  // ── Pass 2: 긴 유닛 부분 매칭 (문서 순서) ──
  pending.sort((a, b) => a - b)
  for (const i of pending) {
    const u = units[i]
    const r = partialConsume(buf, u.text)
    perUnit[i] = {
      id: u.id, kind: u.kind, pos: r.pos, matched: r.matched, total: u.text.length,
      runMiss: r.runMiss, missSnippet: r.missSnippet,
    }
  }

  // ── Pass 3: 짧은 유닛 (문서 순서, 직전 매칭 위치 이후 우선 — 2-포인터 그리디) ──
  // 구간 제약: 짧은 유닛은 문서순 가정에서 [직전 매칭 pos, 다음 매칭 pos] 사이에
  // 있어야 한다. 구간 내 탐색을 우선하고 실패 시에만 전체 폴백 — 단일 숫자 셀("5",
  // "2")이 멀리 떨어진 다른 유닛("50~70", "27")의 본문 글자를 가로채 글자 단위로
  // 찢고 거짓 miss + 거짓 phantom 쌍을 만드는 것을 차단한다.
  for (let i = 0; i < units.length; i++) {
    if (perUnit[i] || !isShort(i)) continue
    const u = units[i]
    const t = u.text
    // 문서 순서상 직전에 매칭된 유닛의 시작 위치 이후를 먼저 탐색
    let from = 0
    for (let j = i - 1; j >= 0; j--) {
      const p = perUnit[j]
      if (p && p.pos >= 0) { from = p.pos; break }
    }
    // 문서 순서상 다음에 이미 매칭된 유닛의 끝 위치까지를 정상 구간으로
    let until = buf.text.length
    for (let j = i + 1; j < units.length; j++) {
      const p = perUnit[j]
      if (p && p.pos >= 0) { until = p.pos + units[j].text.length; break }
    }
    // 탐색 우선순위: ① from 이후 + 구간 안 → ② 문서 앞쪽 + 구간 안 → ③ 기존 동작
    // (from 이후 아무 곳 → 처음부터). 거부 없이 우선순위만 바꿔 신규 미스를 만들지 않는다.
    let pos = buf.find(t, from)
    if (pos !== -1 && pos + t.length > until) pos = -1
    if (pos === -1) {
      const p0 = buf.find(t, 0)
      if (p0 !== -1 && p0 + t.length <= until) pos = p0
    }
    if (pos === -1) {
      pos = buf.find(t, from)
      if (pos === -1) pos = buf.find(t, 0)
    }
    if (pos !== -1) {
      buf.consume(pos, pos + t.length)
      perUnit[i] = { id: u.id, kind: u.kind, pos, matched: t.length, total: t.length, runMiss: 0 }
    } else {
      const r = partialConsume(buf, t)
      perUnit[i] = {
        id: u.id, kind: u.kind, pos: r.pos, matched: r.matched, total: t.length,
        runMiss: r.runMiss, missSnippet: r.missSnippet,
      }
    }
  }

  return { perUnit, buf }
}
