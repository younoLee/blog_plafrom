import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import type { PostSummary } from '../types/post'
import { fetchPosts, deletePost, POSTS_PAGE_SIZE } from '../api/posts'
import { fetchAuthor, type AuthorProfile } from '../api/authors'
import { applySkinFor } from '../api/skin'
import { useAuth } from '../auth/auth-context'
import { ServerAsleepError } from '../api/http'
import { HtmlSlot } from '../components/HtmlSlot'
import { PostRow } from '../components/PostRow'
import { useDocumentTitle } from '../useDocumentTitle'
import NotFoundPage from './NotFoundPage'
import { ui } from '../ui'

/**
 * 한 사람의 블로그 — `/@handle`.
 *
 * 이 화면이 `/blog`(전체 모아보기)와 다른 점은 셋이다:
 *   ① 그 사람 글만 보인다 (목록 API의 `author=`)
 *   ② 그 사람 스킨이 걸린다 (`GET /api/skin?handle=`), 떠날 때 사이트 스킨으로 되돌린다
 *   ③ **절전 중 정적 목록 폴백이 없다.** 정적 아카이브(devlog-index.json)에는 글쓴이
 *      정보가 없어서 누구의 글인지 못 가른다. 없는 정보를 있는 척 그리느니 안 그린다 —
 *      전체를 보여주면 '이 사람 글'이라는 화면의 약속이 거짓이 된다. 대신 `/blog`로
 *      가는 안내를 준다. 그쪽은 서버 없이도 읽힌다.
 *
 * 라우트는 `/:handle`이다. `/@:handle` 같은 부분 세그먼트는 React Router가 안 받는다
 * (2026-08-18에 matchPath로 확인했다 — `/@:handle`은 매칭 자체가 안 된다).
 * 그래서 `@`로 시작하는지 여기서 보고, 아니면 없는 주소로 넘긴다.
 */
function AuthorPage() {
  const { handle: raw } = useParams()
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = Math.max(1, Number(searchParams.get('page') ?? 1) || 1)

  // `/@yuno` → 'yuno'. @가 없으면 이 화면의 주소가 아니다.
  const handle = raw?.startsWith('@') ? raw.slice(1) : null

  const [author, setAuthor] = useState<AuthorProfile | null>(null)
  const [posts, setPosts] = useState<PostSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loaded, setLoaded] = useState(false)
  const [missing, setMissing] = useState(false)
  const [asleep, setAsleep] = useState(false)
  const [error, setError] = useState('')

  // 늦게 온 응답이 이미 바뀐 조건의 결과를 덮지 않게(HomePage와 같은 이유).
  const reqSeq = useRef(0)

  useEffect(() => {
    if (!handle) return
    let cancelled = false
    let restore: (() => void) | undefined
    // 이 사람의 스킨을 바르고, 화면을 떠날 때 사이트 스킨으로 되돌린다.
    // `() => cancelled`를 넘기는 이유: `/@a`의 응답이 `/@b`로 옮긴 뒤에 도착하면
    // 지금 보고 있는 b의 화면이 a의 색·문장으로 덮인다. 목록이 `reqSeq`로 막는 것과
    // 같은 일이고, 스킨 쪽에만 그 가드가 없었다(2026-08-19 검사).
    applySkinFor(handle, () => cancelled).then((fn) => {
      if (cancelled) fn() // 이미 떠났으면 바로 되돌린다
      else restore = fn
    })
    return () => {
      cancelled = true
      restore?.()
    }
  }, [handle])

  // 조회는 effect 밖에서 정의한다 — HomePage의 loadPosts와 같은 이유다.
  // (deps에 넣으면 매 렌더 재생성으로 무한 루프가 되고, 안 넣으면 lint가 경고한다)
  async function load(h: string, p: number) {
    const seq = ++reqSeq.current
    setLoaded(false)
    try {
      const [who, list] = await Promise.all([
        fetchAuthor(h),
        fetchPosts({ author: h, offset: (p - 1) * POSTS_PAGE_SIZE }),
      ])
      if (seq !== reqSeq.current) return
      setMissing(who === null)
      setAuthor(who)
      setPosts(list.items)
      setTotal(list.total)
      setAsleep(false)
      setError('')
    } catch (e) {
      if (seq !== reqSeq.current) return
      setAsleep(e instanceof ServerAsleepError)
      setError((e as Error).message)
    } finally {
      if (seq === reqSeq.current) setLoaded(true)
    }
  }

  useEffect(() => {
    if (!handle) return
    // setState는 전부 await 뒤에 일어난다(실제로는 비동기다). HomePage와 같은 처리.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load(handle, page)
  }, [handle, page])

  useDocumentTitle(author ? `${author.name}의 블로그` : null)

  // @로 시작하지 않는 한 글자짜리 주소(/foo)이거나, 그런 사람이 없을 때.
  if (!handle || (loaded && missing)) return <NotFoundPage />

  const lastPage = Math.max(1, Math.ceil(total / POSTS_PAGE_SIZE))

  return (
    <div className="mx-auto max-w-3xl">
      {/* 프로필 머리말 — 누구의 블로그인지가 이 화면의 첫 정보다 */}
      <section data-skin="hero" className="mb-8 border-b border-black/[0.08] pb-5 dark:border-white/10">
        <h1 className={`text-2xl font-bold tracking-tight ${ui.pageTitle}`}>
          {author?.name ?? `@${handle}`}
        </h1>
        <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400">
          @{handle}
          {author && ` · 글 ${author.posts}편`}
          <span className="mx-1.5">·</span>
          <Link to="/blog" className="text-accent hover:underline">
            전체 글 보기
          </Link>
        </p>
        {/* 이 사람이 쓴 머리말과 소개. applySkinFor가 스킨과 **함께** 갈아 끼우고,
            받아오기 전에는 슬롯을 비워 두므로 여기 나오는 건 이 핸들의 문장이거나
            아무것도 아니다. (전에는 "항상 이 블로그 주인의 문장"이라고 적혀 있었는데
            그게 사실이 아니었다 — 서버가 꺼져 있으면 사이트 주인 문장이 남았다.)

            `aside`를 여기 그리는 이유: 그 칸의 뜻은 '프로필 소개'인데, 그리는 곳이
            Sidebar 하나뿐이었고 Sidebar는 `/blog`에만 붙는다. 그리고 `/blog`가 쓰는
            문장은 항상 사이트(주인) 것이다. 그래서 **글쓴이가 쓴 소개는 저장은 되는데
            어느 화면에도 안 나왔다**(2026-08-19 검사). 이 화면에는 사이드바가 없으므로
            같은 뜻을 가진 자리(이름 아래)에 둔다. */}
        <HtmlSlot slot="intro" className="mt-3 text-sm" />
        <HtmlSlot slot="aside" className="mt-2 text-sm text-gray-500 dark:text-gray-400" />
      </section>

      {asleep && (
        <p className="mb-4 rounded-card bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          서버가 절전 중이야. 비용을 아끼려고 안 쓸 땐 꺼두거든. 이 화면은 서버가 있어야
          누구의 글인지 가릴 수 있어서 지금은 목록을 못 그려 —{' '}
          <a href="/devlog.html" className="underline">
            개발일지 아카이브
          </a>
          는 서버 없이도 열려.
        </p>
      )}
      {error && !asleep && <p className="mb-4 text-sm text-red-600">에러: {error}</p>}

      {loaded && !asleep && posts.length === 0 && (
        <p className="rounded-card border border-dashed border-black/10 p-12 text-center text-gray-500 dark:border-white/15 dark:text-gray-400">
          아직 쓴 글이 없어.
        </p>
      )}

      <div
        data-skin="post-grid"
        className="divide-y divide-black/[0.08] border-b border-black/[0.08] dark:divide-white/10 dark:border-white/10"
      >
        {posts.map((post) => (
          <PostRow
            key={post.id}
            post={post}
            canEdit={!!user && (post.owner_id === user.id || user.role === 'admin')}
            onDelete={async (id) => {
              await deletePost(id)
              setPosts((prev) => prev.filter((p) => p.id !== id))
              setTotal((n) => Math.max(0, n - 1))
            }}
          />
        ))}
      </div>

      {lastPage > 1 && (
        <nav className="mt-8 flex items-center justify-center gap-3" aria-label="페이지 이동">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setSearchParams({ page: String(page - 1) })}
            className="rounded-btn border border-black/10 px-4 py-1.5 text-sm transition enabled:hover:border-accent enabled:hover:text-accent disabled:opacity-40 dark:border-white/15"
          >
            ← 이전
          </button>
          <span className="text-sm text-gray-500 dark:text-gray-400">
            {page} / {lastPage}
          </span>
          <button
            type="button"
            disabled={page >= lastPage}
            onClick={() => setSearchParams({ page: String(page + 1) })}
            className="rounded-btn border border-black/10 px-4 py-1.5 text-sm transition enabled:hover:border-accent enabled:hover:text-accent disabled:opacity-40 dark:border-white/15"
          >
            다음 →
          </button>
        </nav>
      )}
    </div>
  )
}

export default AuthorPage
