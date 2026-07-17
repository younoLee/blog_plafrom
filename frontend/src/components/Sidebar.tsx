import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { PostMetaResult } from '../api/posts'
import { ui } from '../ui'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 블로그 홈 우측 사이드바: 프로필 카드 + 최근 글 + 태그. 화면이 '꽉 찬 블로그'처럼 보이게 채워준다.
// 집계는 목록(현재 페이지)이 아니라 서버의 /posts/meta를 쓴다 — 목록이 페이지로 끊기므로
// 목록으로 세면 2쪽에서 글 수·태그가 그 페이지 기준으로 틀어진다.
export function Sidebar({ meta }: { meta: PostMetaResult | null }) {
  const [owner, setOwner] = useState<{ name: string | null }>({ name: null })

  useEffect(() => {
    fetch(`${BASE}/blog-owner`)
      .then((r) => r.json())
      .then((d) => setOwner({ name: d?.name ?? null }))
      .catch(() => {})
  }, [])

  const name = owner.name ?? 'DEV 블로그'
  const initial = (name[0] ?? 'D').toUpperCase()
  const recent = meta?.recent ?? []
  const topTags = meta?.tags ?? []
  const total = meta?.total ?? 0

  return (
    <aside className="space-y-5 md:sticky md:top-20">
      {/* 프로필 카드 */}
      <div className={ui.card}>
        <div className="flex flex-col items-center text-center">
          <div className="grid h-16 w-16 place-items-center rounded-full bg-gradient-to-tr from-[#0071e3] to-[#7c3aed] text-2xl font-semibold text-white">
            {initial}
          </div>
          <h3 className="mt-3 font-semibold tracking-tight">{name}</h3>
          <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
            인프라를 직접 만들며 배운 것을 남깁니다.
          </p>
          <Link
            to="/subscriptions"
            className="mt-3 inline-flex items-center gap-1 rounded-full bg-[#0071e3] px-4 py-1.5 text-xs font-medium text-white transition hover:bg-[#0077ed] dark:bg-[#0a84ff]"
          >
            + 이 블로그 구독
          </Link>
        </div>
        <div className="mt-4 border-t border-black/[0.06] pt-3 text-center dark:border-white/10">
          <span className="text-lg font-semibold tracking-tight">{total}</span>
          <span className="ml-1 text-xs text-gray-400 dark:text-gray-500">개의 글</span>
        </div>
      </div>

      {/* 최근 글 */}
      {recent.length > 0 && (
        <div className={ui.card}>
          <h4 className="mb-3 text-sm font-semibold tracking-tight">최근 글</h4>
          <ul className="space-y-3">
            {recent.map((p) => (
              <li key={p.id} className="flex gap-3">
                {p.cover_image && (
                  <Link to={`/blog/posts/${p.id}`} className="shrink-0 overflow-hidden rounded-lg">
                    <img src={p.cover_image} alt="" loading="lazy" className="h-11 w-11 object-cover" />
                  </Link>
                )}
                <div className="min-w-0">
                  <Link
                    to={`/blog/posts/${p.id}`}
                    className="line-clamp-1 text-sm text-gray-700 transition hover:text-[#0071e3] dark:text-gray-200 dark:hover:text-[#0a84ff]"
                  >
                    {p.title}
                  </Link>
                  <div className="text-xs text-gray-400 dark:text-gray-500">
                    {new Date(p.created_at).toLocaleDateString()}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 태그 목록 (클릭 시 그 태그 글만 보기) */}
      {topTags.length > 0 && (
        <div className={ui.card}>
          <h4 className="mb-3 text-sm font-semibold tracking-tight">태그</h4>
          <div className="flex flex-wrap gap-1.5">
            {topTags.map(({ tag, count }) => (
              <Link
                key={tag}
                to={`/blog?tag=${encodeURIComponent(tag)}`}
                className="inline-flex items-center gap-1 rounded-full bg-black/[0.05] px-2.5 py-1 text-xs text-gray-600 transition hover:bg-[#0071e3]/10 hover:text-[#0071e3] dark:bg-white/10 dark:text-gray-300 dark:hover:text-[#0a84ff]"
              >
                #{tag}
                <span className="text-gray-400 dark:text-gray-500">{count}</span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </aside>
  )
}
