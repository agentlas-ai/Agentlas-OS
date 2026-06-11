/**
 * HWP 5.x 배포용 문서 "상위 버전" 경고 플레이스홀더 감지.
 *
 * 배포용(열람 제한) HWP 파일은 본문을 암호화하고, 복호화 실패 시 한컴에서 삽입한
 * 고정 경고 문자열이 노출된다. 이 문자열이 파싱 결과의 대부분을 차지하면 COM API
 * fallback으로 전환해야 한다.
 *
 * 이슈 #25 참고.
 */

// 배포용 HWP의 고정 경고 문구 (버전·지역에 따라 미세 차이 가능 → 핵심 키만 매칭)
const SENTINEL_PATTERNS: RegExp[] = [
  /상위\s*버전의\s*배포용\s*문서/,
  /최신\s*버전의\s*한글.*뷰어/,
  /문서를\s*읽으려면/,
]

/**
 * 본문이 배포용 플레이스홀더로만 채워졌는지 판정.
 *
 * 기준:
 *  - 패턴이 한 번 이상 매치
 *  - 패턴을 제거한 나머지 의미 있는 텍스트가 매우 짧음 (공백·개행 제외 120자 미만)
 *
 * → 정상 본문이 섞여 있으면 false (COM fallback 불필요)
 */
export function isDistributionSentinel(markdown: string): boolean {
  if (!markdown) return false
  const hit = SENTINEL_PATTERNS.some(p => p.test(markdown))
  if (!hit) return false

  // 경고 문구 라인 제거 후 실질 내용이 짧은지
  const stripped = markdown
    .split(/\r?\n/)
    .filter(line => !SENTINEL_PATTERNS.some(p => p.test(line)))
    .join("")
    .replace(/\s+/g, "")

  return stripped.length < 120
}
