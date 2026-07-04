// 글 카드용 유틸: 마크다운을 벗긴 발췌 + 읽기시간

// 본문 마크다운에서 기호를 벗겨 '읽을 수 있는' 요약 텍스트로.
// (# 헤딩, - 불릿, **강조**, `코드`, [링크](url), ![이미지](url) 등을 정리)
export function excerpt(md: string, max = 120): string {
  const text = md
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '') // 이미지 통째 제거
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1') // 링크는 표시 텍스트만 남김
    .replace(/^#{1,6}\s+/gm, '') // 헤딩 기호
    .replace(/^\s*[-*+]\s+/gm, '') // 불릿 기호
    .replace(/^\s*>\s?/gm, '') // 인용 기호
    .replace(/[*_~`]/g, '') // 강조·코드 마커
    .replace(/\s+/g, ' ') // 개행·연속공백 → 한 칸
    .trim()
  return text.length > max ? text.slice(0, max).trim() + '…' : text
}

// 읽기 시간(분) 추정 — 한글 기준 분당 약 500자
export function readingTime(md: string): number {
  return Math.max(1, Math.round(md.length / 500))
}
