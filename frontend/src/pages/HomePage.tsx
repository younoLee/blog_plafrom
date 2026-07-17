import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { PostSummary } from '../types/post'
import type { PostMetaResult } from '../api/posts'
import { fetchPosts, fetchPostsMeta, deletePost, POSTS_PAGE_SIZE } from '../api/posts'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'
import { IconLock } from '../components/icons'
import { Reveal } from '../components/Reveal'
import { Sidebar } from '../components/Sidebar'

function HomePage() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const tag = searchParams.get('tag') || undefined // URL ?tag= 로 태그 필터
  const q = searchParams.get('q') || undefined // URL ?q= 로 검색
  // 쪽은 1부터(사람이 읽는 값), 서버엔 offset으로 변환해 보낸다
  const page = Math.max(1, Number(searchParams.get('page') ?? 1) || 1)

  const [posts, setPosts] = useState<PostSummary[]>([])
  const [total, setTotal] = useState(0)
  const [meta, setMeta] = useState<PostMetaResult | null>(null)
  const [error, setError] = useState('')
  // 검색창 입력값. 제출(Enter)할 때만 URL에 반영한다 — 타이핑마다 부르면
  // 서버 레이트리밋(60/분)에 걸리고 검색은 일반 조회보다 비싸다.
  const [queryInput, setQueryInput] = useState(q ?? '')

  async function loadPosts() {
    try {
      const res = await fetchPosts({ q, tag, offset: (page - 1) * POSTS_PAGE_SIZE })
      setPosts(res.items)
      setTotal(res.total)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  useEffect(() => {
    setQueryInput(q ?? '') // 뒤로가기 등으로 URL이 바뀌면 입력창도 맞춘다
  }, [q])

  useEffect(() => {
    loadPosts()
  }, [user, tag, q, page])

  // 사이드바 집계는 목록과 별개 — 페이지·검색과 무관하게 블로그 전체를 보여준다
  useEffect(() => {
    fetchPostsMeta()
      .then(setMeta)
      .catch(() => {})
  }, [user])

  function updateParams(next: Record<string, string | undefined>) {
    const params = new URLSearchParams(searchParams)
    for (const [k, v] of Object.entries(next)) {
      if (v) params.set(k, v)
      else params.delete(k)
    }
    setSearchParams(params)
  }

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    const v = queryInput.trim()
    // 서버가 q의 최소 길이를 2로 강제한다(1글자는 trigram 인덱스를 못 타 전체 스캔)
    if (v.length === 1) {
      setError('검색어는 2글자 이상 입력해줘')
      return
    }
    setError('')
    updateParams({ q: v || undefined, page: undefined }) // 검색이 바뀌면 1쪽부터
  }

  function goToPage(p: number) {
    updateParams({ page: p > 1 ? String(p) : undefined })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function handleDelete(id: number) {
    try {
      await deletePost(id)
      await loadPosts()
      setMeta(await fetchPostsMeta()) // 글이 줄었으니 사이드바 집계도 갱신
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const lastPage = Math.max(1, Math.ceil(total / POSTS_PAGE_SIZE))
  const first = total === 0 ? 0 : (page - 1) * POSTS_PAGE_SIZE + 1
  const last = Math.min(page * POSTS_PAGE_SIZE, total)

  return (
    <>
      {/* 히어로 */}
      <section className="relative mb-14 text-center">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 -top-16 -z-10 mx-auto h-56 max-w-xl rounded-full bg-gradient-to-tr from-[#0071e3]/20 via-purple-400/15 to-pink-400/15 blur-3xl dark:from-[#0a84ff]/20"
        />
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          최근 <span className={ui.gradientText}>이야기</span>
        </h1>
        <p className="mt-3 text-lg text-gray-500 dark:text-gray-400">인프라를 직접 만들며 배운 것을 남깁니다.</p>
        {/* 이메일 구독·새 글 알림은 전용 페이지에서 */}
        <p className="mx-auto mt-7 max-w-md text-sm text-gray-500 dark:text-gray-400">
          이메일 구독과 새 글 알림은{' '}
          <Link to="/subscriptions" className="text-[#0071e3] hover:underline dark:text-[#0a84ff]">
            구독
          </Link>
          에서 할 수 있어.
        </p>
      </section>

      {error && <p className="mb-4 text-sm text-red-600">에러: {error}</p>}

      {/* 본문 + 우측 사이드바 2단. md(768px)+ = 옆으로(PC/태블릿), 그 아래(폰) = 세로 스택 */}
      <div className="grid gap-8 md:grid-cols-[1fr_18rem]">
      <div>
      {/* 검색 — Enter로 제출. 검색어는 URL(?q=)에 남아 뒤로가기·공유가 된다 */}
      <form onSubmit={handleSearch} className="mb-5 flex gap-2">
        <input
          type="search"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder="제목·본문 검색 (2글자 이상)"
          aria-label="글 검색"
          className="min-w-0 flex-1 rounded-full border border-black/10 bg-white/70 px-4 py-2 text-sm outline-none transition placeholder:text-gray-400 focus:border-[#0071e3] dark:border-white/15 dark:bg-white/5 dark:focus:border-[#0a84ff]"
        />
        <button
          type="submit"
          className="shrink-0 rounded-full bg-[#0071e3] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#0077ed] dark:bg-[#0a84ff]"
        >
          검색
        </button>
      </form>

      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          {q ? (
            <>
              <span className="text-[#0071e3] dark:text-[#0a84ff]">"{q}"</span>
              <span className="text-base font-normal text-gray-400">검색 결과</span>
              <Link to={tag ? `/blog?tag=${encodeURIComponent(tag)}` : '/blog'} className="text-sm font-normal text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">✕ 검색 취소</Link>
            </>
          ) : tag ? (
            <>
              <span className="text-[#0071e3] dark:text-[#0a84ff]">#{tag}</span>
              <Link to="/blog" className="text-sm font-normal text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">✕ 전체보기</Link>
            </>
          ) : (
            '최근 글'
          )}
        </h2>
        <span className="text-sm text-gray-400 dark:text-gray-500">
          {total > 0 ? `${total}개 중 ${first}–${last}` : '0개'}
        </span>
      </div>

      {posts.length === 0 && (
        <p className="rounded-2xl border border-dashed border-black/10 p-12 text-center text-gray-400 dark:border-white/15 dark:text-gray-500">
          {q || tag ? '조건에 맞는 글이 없어.' : '아직 글이 없어. 첫 글을 써봐!'}
        </p>
      )}

      <div className="grid gap-5 lg:grid-cols-2 2xl:grid-cols-3">
        {posts.map((post, i) => (
          <Reveal key={post.id} delay={Math.min(i * 60, 300)}>
          <article className={`${ui.card} hover:-translate-y-0.5 hover:border-[#0071e3]/30 dark:hover:border-[#0a84ff]/30`}>
            {post.cover_image ? (
              <Link to={`/blog/posts/${post.id}`} className="mb-4 block overflow-hidden rounded-xl">
                <img src={post.cover_image} alt="" loading="lazy" className="aspect-[16/9] w-full object-cover transition duration-300 hover:scale-[1.03]" />
              </Link>
            ) : (
              // 커버 없는 글: 제목 이니셜 + 은은한 그라데이션으로 그리드를 안 휑하게
              <Link
                to={`/blog/posts/${post.id}`}
                className="mb-4 flex aspect-[16/9] items-center justify-center overflow-hidden rounded-xl bg-gradient-to-br from-[#0071e3]/10 via-purple-400/10 to-pink-400/10 dark:from-[#0a84ff]/15 dark:via-purple-500/10 dark:to-pink-500/10"
              >
                <span className="text-4xl font-bold text-[#0071e3]/35 dark:text-[#0a84ff]/40">
                  {post.title[0]?.toUpperCase() ?? '#'}
                </span>
              </Link>
            )}
            <h3 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <Link to={`/blog/posts/${post.id}`} className="transition hover:text-[#0071e3] dark:hover:text-[#0a84ff]">{post.title}</Link>
              {post.visibility === 'private' && (
                <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500 dark:bg-white/10 dark:text-gray-400">
                  <IconLock className="h-3 w-3" />비공개
                </span>
              )}
              {post.visibility === 'subscribers' && (
                <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-[#0071e3] dark:bg-[#0a84ff]/15 dark:text-[#0a84ff]">
                  구독자공개
                </span>
              )}
            </h3>
            <Link to={`/blog/posts/${post.id}`} className="mt-2 block text-gray-500 transition hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
              <p className="line-clamp-2 leading-relaxed">
                {post.excerpt}
              </p>
            </Link>
            {post.tags.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {post.tags.slice(0, 4).map((t) => (
                  <Link
                    key={t}
                    to={`/blog?tag=${encodeURIComponent(t)}`}
                    className="rounded-full bg-black/[0.05] px-2 py-0.5 text-xs text-gray-600 transition hover:bg-[#0071e3]/10 hover:text-[#0071e3] dark:bg-white/10 dark:text-gray-300 dark:hover:text-[#0a84ff]"
                  >
                    #{t}
                  </Link>
                ))}
              </div>
            )}
            <div className="mt-4 flex items-center justify-between border-t border-black/[0.06] pt-3 dark:border-white/10">
              <time className="text-xs text-gray-400 dark:text-gray-500">
                {new Date(post.created_at).toLocaleDateString()} · {post.reading_minutes}분 읽기
              </time>
              {/* 본인 글이거나 관리자면 수정·삭제 버튼 노출 */}
              {user && (post.owner_id === user.id || user.role === 'admin') && (
                <div className="flex gap-3 text-sm">
                  <Link to={`/blog/posts/${post.id}/edit`} className="text-[#0071e3] hover:underline dark:text-[#0a84ff]">수정</Link>
                  <button type="button" onClick={() => handleDelete(post.id)} className="text-red-500 hover:underline">삭제</button>
                </div>
              )}
            </div>
          </article>
          </Reveal>
        ))}
      </div>

      {/* 쪽 이동 — 글이 한 쪽을 넘을 때만 */}
      {lastPage > 1 && (
        <nav className="mt-8 flex items-center justify-center gap-3" aria-label="페이지 이동">
          <button
            type="button"
            onClick={() => goToPage(page - 1)}
            disabled={page <= 1}
            className="rounded-full border border-black/10 px-4 py-1.5 text-sm transition enabled:hover:border-[#0071e3] enabled:hover:text-[#0071e3] disabled:opacity-40 dark:border-white/15 dark:enabled:hover:border-[#0a84ff] dark:enabled:hover:text-[#0a84ff]"
          >
            ← 이전
          </button>
          <span className="text-sm text-gray-500 dark:text-gray-400">
            {page} / {lastPage}
          </span>
          <button
            type="button"
            onClick={() => goToPage(page + 1)}
            disabled={page >= lastPage}
            className="rounded-full border border-black/10 px-4 py-1.5 text-sm transition enabled:hover:border-[#0071e3] enabled:hover:text-[#0071e3] disabled:opacity-40 dark:border-white/15 dark:enabled:hover:border-[#0a84ff] dark:enabled:hover:text-[#0a84ff]"
          >
            다음 →
          </button>
        </nav>
      )}
      </div>
      <Sidebar meta={meta} />
      </div>
    </>
  )
}

export default HomePage
