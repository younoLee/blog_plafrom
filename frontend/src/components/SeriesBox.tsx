import { Link } from 'react-router-dom'
import type { SeriesNav } from '../types/post'
import { ui } from '../ui'

// 글 상세의 연재 안내 — 이 글이 몇 편인지 + 전체 목록(현재 편 강조).
// 목록은 서버가 '내가 볼 수 있는 글'만 주므로 여기서 따로 거를 게 없다.
export function SeriesBox({ nav, currentId }: { nav: SeriesNav; currentId: number }) {
  return (
    <section className={`${ui.card} my-8`} aria-label="연재 목록">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-tight">
          연재 · <span className="text-[#0071e3] dark:text-[#0a84ff]">{nav.series}</span>
        </h2>
        <span className="text-xs text-gray-400 dark:text-gray-500">
          {nav.index} / {nav.total}편
        </span>
      </div>
      <ol className="space-y-1">
        {nav.items.map((item, i) => {
          const isCurrent = item.id === currentId
          return (
            <li key={item.id} className="flex gap-2 text-sm">
              <span className="w-6 shrink-0 text-right text-xs text-gray-400 dark:text-gray-500">
                {i + 1}.
              </span>
              {isCurrent ? (
                // 현재 글은 링크가 아니라 강조 — 자기 자신으로 가는 링크는 의미가 없다
                <span aria-current="true" className="font-semibold text-[#0071e3] dark:text-[#0a84ff]">
                  {item.title}
                </span>
              ) : (
                <Link
                  to={`/blog/posts/${item.id}`}
                  className="text-gray-600 transition hover:text-[#0071e3] dark:text-gray-300 dark:hover:text-[#0a84ff]"
                >
                  {item.title}
                </Link>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

// 본문 끝의 이전/다음 편 이동. 한쪽만 있어도(첫 편·마지막 편) 자리가 안 무너지게 배치한다.
export function SeriesPrevNext({ nav }: { nav: SeriesNav }) {
  if (!nav.prev && !nav.next) return null

  const box =
    'group flex-1 rounded-2xl border border-black/[0.07] p-4 transition hover:border-[#0071e3]/40 dark:border-white/10 dark:hover:border-[#0a84ff]/40'

  return (
    <nav className="my-8 flex flex-col gap-3 sm:flex-row" aria-label="연재 이동">
      {nav.prev ? (
        <Link to={`/blog/posts/${nav.prev.id}`} className={box}>
          <div className="text-xs text-gray-400 dark:text-gray-500">← 이전 편</div>
          <div className="mt-1 line-clamp-2 text-sm font-medium transition group-hover:text-[#0071e3] dark:group-hover:text-[#0a84ff]">
            {nav.prev.title}
          </div>
        </Link>
      ) : (
        <div className="hidden flex-1 sm:block" aria-hidden />
      )}
      {nav.next ? (
        <Link to={`/blog/posts/${nav.next.id}`} className={`${box} sm:text-right`}>
          <div className="text-xs text-gray-400 dark:text-gray-500">다음 편 →</div>
          <div className="mt-1 line-clamp-2 text-sm font-medium transition group-hover:text-[#0071e3] dark:group-hover:text-[#0a84ff]">
            {nav.next.title}
          </div>
        </Link>
      ) : (
        <div className="hidden flex-1 sm:block" aria-hidden />
      )}
    </nav>
  )
}
