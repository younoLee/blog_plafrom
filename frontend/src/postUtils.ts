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

export interface ArchivePost {
  title: string
  slug: string
  date?: string
  tags?: string[]
}

/** 같은 주제의 다른 편 고르기 — 겹치는 태그가 많은 순, 같으면 최신 순.
 *
 *  **재료가 API가 아니라 정적 인덱스(devlog-index.json)다.** `/api/posts?tag=`가
 *  있지만 이 사이트는 EC2를 평소 꺼두므로, 추천 블록 하나 때문에 잠든 서버를
 *  기다리게 되고 링크를 눌러도 안 열린다. 정적 인덱스는 S3에서 오고 가리키는
 *  아카이브 페이지도 서버 없이 열린다 — 추천이 실제로 닿는다.
 *
 *  `universal`(모든 편에 붙은 태그, 예: '개발일지')은 셈에서 뺀다. 안 빼면 아무
 *  두 편이나 1점씩 겹쳐 사실상 최신 3편 고정이 된다 — 추천처럼 보이지만 정보가 0이다. */
export function relatedPosts(
  posts: ArchivePost[] | undefined | null,
  title: string | undefined | null,
  tags: string[] | undefined | null,
  max = 3,
): { post: ArchivePost; shared: string[] }[] {
  if (!posts?.length || !tags?.length) return []
  const universal = new Set(
    (posts[0].tags ?? []).filter((t) => posts.every((p) => p.tags?.includes(t))),
  )
  const mine = new Set(tags.filter((t) => !universal.has(t)))
  if (!mine.size) return []
  return posts
    .filter((p) => p.title !== title)
    .map((p) => ({ post: p, shared: (p.tags ?? []).filter((t) => mine.has(t)) }))
    .filter((r) => r.shared.length > 0)
    .sort(
      (a, b) =>
        // 괄호 주의: `x || y ? 1 : -1`은 `(x||y) ? 1 : -1`로 묶여 겹침 수가 통째로 무시된다.
        b.shared.length - a.shared.length ||
        ((a.post.date ?? '') < (b.post.date ?? '') ? 1 : -1),
    )
    .slice(0, max)
}

/** 공유용 주소 고르기 — 같은 글의 **정적 아카이브** 주소가 있으면 그걸 준다.
 *
 *  SPA 주소(/blog/posts/41)를 공유하면 받는 쪽 미리보기 카드가 어느 글이든 똑같고
 *  (index.html의 og:*가 사이트 공통 1종, 봇은 JS를 안 돌린다), 이 사이트는 EC2를
 *  평소 꺼두므로 눌렀을 때 글이 안 보일 확률이 높다. 정적 아카이브는 편마다 제
 *  og:title·canonical을 갖고 서버 없이 열린다.
 *
 *  **제목으로 맞춘다.** 정적 아카이브 제목은 마크다운 H1이고 DB 글 제목은 발행
 *  스크립트가 같은 원고에서 넣은 값이라 같은 문자열이다. 날짜로 맞추면 소급 발행
 *  (created_at을 작업일로 되돌린다)과 얽혀 어긋난다.
 *
 *  못 찾으면 null — 부르는 쪽이 현재 주소를 쓴다(연재가 아닌 일반 글이 그렇다). */
export function archiveUrlFor(
  posts: { title: string; slug: string }[] | undefined | null,
  title: string | undefined | null,
  origin: string,
): string | null {
  if (!posts?.length || !title) return null
  const hit = posts.find((p) => p.title === title)
  return hit ? `${origin.replace(/\/$/, '')}/${hit.slug.replace(/^\//, '')}` : null
}

/* `coverLabel()`은 2026-08-18 오전에 만들었다가 같은 날 오후에 지웠다.
 *
 * 만든 이유: 커버 없는 글의 자리표시가 제목 첫 글자였는데, 이 블로그 글은 전부
 * `블로그 만들기 #NN`으로 시작해서 목록에 '블'이 도배됐다. 그래서 편 번호를 쓰게 했다.
 *
 * 지운 이유: **자리표시 자체를 없앴다.** 이 블로그는 글 대부분에 커버가 없어서
 * 목록 절반이 빈 상자였고, 그건 글자를 무엇으로 바꾸든 남는 문제였다. 카드 격자를
 * 목록으로 바꾸면서 커버가 있는 글만 그림을 그리게 했다(HomePage 주석 참고).
 * 그러자 이 함수를 부를 자리가 사라졌다.
 *
 * 남겨두지 않는 이유: 아무도 안 부르는 함수는 다음 사람이 "이런 게 있네" 하고
 * 자리표시를 되살리는 근거가 된다. 고친 건 글자가 아니라 형식이었다.
 */
