import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { PostMetaResult } from '../api/posts'
import { fetchBlogOwner } from '../api/subscriptions'
import { useSlots } from '../api/slots'
import { ui } from '../ui'
import { HtmlSlot } from './HtmlSlot'


// 블로그 홈 우측 사이드바: 프로필 카드 + 최근 글 + 태그. 화면이 '꽉 찬 블로그'처럼 보이게 채워준다.
// 집계는 목록(현재 페이지)이 아니라 서버의 /posts/meta를 쓴다 — 목록이 페이지로 끊기므로
// 목록으로 세면 2쪽에서 글 수·태그가 그 페이지 기준으로 틀어진다.
export function Sidebar({ meta }: { meta: PostMetaResult | null }) {
  const [owner, setOwner] = useState<{ name: string | null }>({ name: null })
  // 자기 소개를 직접 쓴 사람이면 아래 고정 문장 대신 그것을 쓴다.
  const intro = useSlots().aside

  useEffect(() => {
    // 같은 엔드포인트를 부르는 fetchBlogOwner()가 이미 있고 그건 타임아웃이 붙어 있다.
    // 여기서만 맨 fetch를 복제해 두는 바람에, 서버가 꺼진 동안 이 요청 하나가 60초를
    // 무음으로 매달려 있었다(.catch로 화면엔 안 보인다). 2026-08-10 심층검사.
    fetchBlogOwner()
      .then((d) => setOwner({ name: d?.name ?? null }))
      .catch(() => {})
  }, [])

  const name = owner.name ?? '블로그 만들기'
  const initial = (name[0] ?? 'D').toUpperCase()
  const recent = meta?.recent ?? []
  const topTags = meta?.tags ?? []
  const total = meta?.total ?? 0

  return (
    <aside data-skin="sidebar" className="space-y-5 md:sticky md:top-20">
      {/* 프로필 카드 */}
      <div data-skin="sidebar-profile" className={ui.card}>
        <div className="flex flex-col items-center text-center">
{/* select-none: 아바타가 이미지가 아니라 이름 첫 글자를 그린 div라, 브라우저가
              이걸 본문 글자로 보고 마우스를 올리면 텍스트 선택 커서(I-빔)를 준다.
              프로필 사진 위에서 글자를 고르는 커서가 뜨는 건 눌러도 되는 것처럼
              보이게 만든다(2026-08-17 사용자 지적). 고를 글자가 아니므로 잠근다. */}
          <div className="grid h-16 w-16 select-none place-items-center rounded-full bg-gradient-to-tr from-accent to-accent-2 text-2xl font-semibold text-white">
            {initial}
          </div>
          <h3 className="mt-3 font-semibold tracking-tight">{name}</h3>
          {/* 소개를 직접 쓴 사람은 그 문장이, 안 쓴 사람은 기본 한 줄이 나온다.
              **둘 다 보여주지 않는다** — 자기 소개를 썼는데 그 위에 남이 정한 문장이
              그대로 남아 있으면, 쓴 사람 입장에선 자기 글이 안 들어간 것으로 보인다. */}
          {intro ? (
            <HtmlSlot slot="aside" className="mt-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400" />
          ) : (
            <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
              서버를 직접 굴리면서 부딪힌 것을 적는다.
            </p>
          )}
          {/* 이미 구독 중인 사람에게도 '+ 이 블로그 구독'이라 말하고 있었다. 그걸 누르면
              도착하는 화면의 다음 버튼이 **되돌릴 수 없는 해지**라, 신청하려던 사람이
              해지 버튼 앞에 서게 되는 경로였다(2026-08-17). 여기서는 상태를 모르므로
              (사이드바는 구독 정보를 안 받는다) 중립적인 이름으로 보낸다. */}
          <Link
            to="/subscriptions"
            className="mt-3 inline-flex items-center gap-1 rounded-btn bg-accent px-4 py-1.5 text-xs font-medium text-on-accent transition hover:bg-accent-hi"
          >
            구독 관리
          </Link>
        </div>
        {/* **집계를 못 받았으면 숫자를 말하지 않는다.** `meta ?? 0`이라 절전(서버 꺼짐)
            중엔 "0개의 글"이 떴는데, 바로 옆 본문은 정적 목록 32편을 그리고 있었다 —
            같은 화면이 서로 반대되는 말을 한 셈이다. 0은 '모름'이 아니라 사실 주장이다
            (본문의 '불러오는 중…'·'0개' 처리와 같은 규칙, 2026-08-17). */}
        {meta && (
          <div className="mt-4 border-t border-black/[0.06] pt-3 text-center dark:border-white/10">
            <span className="text-lg font-semibold tracking-tight">{total}</span>
            <span className="ml-1 text-xs text-gray-500 dark:text-gray-400">개의 글</span>
          </div>
        )}
      </div>

      {/* 최근 글 */}
      {recent.length > 0 && (
        <div data-skin="sidebar-recent" className={ui.card}>
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
                    className="line-clamp-1 text-sm text-gray-700 transition hover:text-accent dark:text-gray-200"
                  >
                    {p.title}
                  </Link>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
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
        <div data-skin="sidebar-tags" className={ui.card}>
          <h4 className="mb-3 text-sm font-semibold tracking-tight">태그</h4>
          <div className="flex flex-wrap gap-1.5">
            {topTags.map(({ tag, count }) => (
              <Link
                key={tag}
                to={`/blog?tag=${encodeURIComponent(tag)}`}
                className="inline-flex items-center gap-1 rounded-btn bg-black/[0.05] px-2.5 py-1 text-xs text-gray-600 transition hover:bg-accent/10 hover:text-accent dark:bg-white/10 dark:text-gray-300"
              >
                #{tag}
                <span className="text-gray-500 dark:text-gray-400">{count}</span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </aside>
  )
}
