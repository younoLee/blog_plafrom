/**
 * 목록 쪽 이동 — 한 벌만 둔다.
 *
 * **왜 컴포넌트로 뽑았나 (09-04 검사 FQ-9)** — HomePage 와 AuthorPage 가 같은 마크업을
 * 통째로 복제해 두고 있었고, 복제는 이미 갈라져 있었다: HomePage 는 쪽을 옮기면 맨 위로
 * 스크롤하는데(`goToPage`) AuthorPage 는 안 했다. 그래서 글쓴이 화면에서 '다음'을 누르면
 * **읽던 자리에 그대로 머문 채 목록만 바뀌어서**, 화면이 안 바뀐 것처럼 보인다.
 * 같은 화면 요소가 화면마다 다르게 동작하는 것은 그 자체로 버그다.
 *
 * 이 저장소는 같은 이유로 PostRow(목록 한 줄)와 AsleepNotice(절전 안내)를 이미 뽑아뒀다.
 * 마크업 계약을 한 곳에 두면 갈라질 자리가 없어진다.
 */
export function Pager({
  page,
  lastPage,
  onGo,
}: {
  page: number
  lastPage: number
  /** 쪽 번호를 받아 URL 을 바꾸는 쪽. 스크롤은 여기서 한다(화면마다 다를 이유가 없다). */
  onGo: (page: number) => void
}) {
  if (lastPage <= 1) return null // 한 쪽뿐이면 그리지 않는다

  function go(p: number) {
    onGo(p)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const btn =
    'rounded-btn border border-black/10 px-4 py-1.5 text-sm transition enabled:hover:border-accent enabled:hover:text-accent disabled:opacity-40 dark:border-white/15'

  return (
    <nav className="mt-8 flex items-center justify-center gap-3" aria-label="페이지 이동">
      <button type="button" onClick={() => go(page - 1)} disabled={page <= 1} className={btn}>
        ← 이전
      </button>
      <span className="text-sm text-gray-500 dark:text-gray-400">
        {page} / {lastPage}
      </span>
      <button type="button" onClick={() => go(page + 1)} disabled={page >= lastPage} className={btn}>
        다음 →
      </button>
    </nav>
  )
}
