import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { PostSummary } from '../types/post'
import type { PostMetaResult } from '../api/posts'
import { fetchPosts, fetchPostsMeta, deletePost, POSTS_PAGE_SIZE } from '../api/posts'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'
import { IconLock } from '../components/icons'
import { Reveal } from '../components/Reveal'
import { Sidebar } from '../components/Sidebar'
import { ServerAsleepError } from '../api/http'
import { fetchDevlogIndex, type DevlogIndexPost } from '../api/devlogIndex'

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
  // 서버 절전(꺼둠) 상태 — 에러와 톤을 구분해 안내한다.
  const [asleep, setAsleep] = useState(false)
  // 절전 중에 보여줄 **정적** 목록(빌드 산출물). 랜딩(/)은 2026-08-12부터 이걸 써서
  // 서버 없이도 글이 보였는데, 정작 '글 목록' 화면인 이 페이지는 안내문만 띄우고
  // 비어 있었다 — 방문자가 '블로그' 입구로 들어오면 자산 32편이 0편으로 보였다.
  // 절전은 이 사이트의 **평상시 상태**라 그게 첫인상이 된다 (2026-08-17).
  const [staticPosts, setStaticPosts] = useState<DevlogIndexPost[] | null>(null)
  // 검색창 입력값. 제출(Enter)할 때만 URL에 반영한다 — 타이핑마다 부르면
  // 서버 레이트리밋(60/분)에 걸리고 검색은 일반 조회보다 비싸다.
  const [queryInput, setQueryInput] = useState(q ?? '')
  // **한 번이라도 응답을 받았는가.** 이게 없으면 `posts=[]`·`asleep=false`인 첫 페인트부터
  // 응답이 오거나 8초 타임아웃이 끝날 때까지 화면이 "아직 글이 없어. 첫 글을 써봐!" + "0개"를
  // **확정적으로** 띄운다 — 이 사이트는 서버가 평소 꺼져 있어 그 8초가 흔한 상태다.
  // 방문자에게 첫인상이 '빈 블로그'가 된다. (AdminPage는 같은 문제를 loaded 플래그로
  // 이미 막아뒀는데, 정작 제일 많이 보는 이 화면에만 없었다 — 2026-08-11 공백검사)
  const [loaded, setLoaded] = useState(false)

  // **늦게 온 응답이 이미 바뀐 조건의 결과를 덮어쓰지 않게 한다.** 검색어를 A→B로
  // 바꿨을 때 A의 응답이 나중에 오면 제목줄은 B("aws 검색 결과")인데 카드는 A가
  // 깔린다. 차가운 서버는 8초까지 걸리니 겹칠 시간이 충분하다.
  const reqSeq = useRef(0)

  async function loadPosts() {
    const seq = ++reqSeq.current
    setLoaded(false) // 조건이 바뀌면 다시 '모르는 상태'다 — 아래 개수 표시가 거짓말하지 않게
    try {
      const res = await fetchPosts({ q, tag, offset: (page - 1) * POSTS_PAGE_SIZE })
      if (seq !== reqSeq.current) return // 더 최신 요청이 이미 나갔다
      // 범위 밖 쪽으로 남으면 "3 / 2 쪽"과 "아직 글이 없어"가 같이 뜬다 — 마지막 쪽의
      // 마지막 글을 지웠거나 누가 ?page=99로 들어온 경우다. 조용히 마지막 쪽으로 되돌린다.
      const lastP = Math.max(1, Math.ceil(res.total / POSTS_PAGE_SIZE))
      if (res.items.length === 0 && page > lastP) {
        updateParams({ page: lastP > 1 ? String(lastP) : undefined })
        return // 이 setState들은 건너뛴다 — 곧 새 요청이 돈다
      }
      setPosts(res.items)
      setTotal(res.total)
      setAsleep(false)
      // **성공하면 옛 에러를 지운다.** 이게 없어서, 절전 중에 들어와 에러가 남은 상태로
      // 서버가 깨어나면 `{error && !asleep}` 줄이 그제야 드러나 **멀쩡한 목록 위에
      // 빨간 "에러: 서버가 절전 중이야"가 떴다** — 노란 안내가 빨간 에러로 승격되는 셈이라
      // 오늘 만든 톤 구분이 정확히 반대로 작동했다.
      setError('')
    } catch (e) {
      if (seq !== reqSeq.current) return
      // 절전(서버 꺼짐)과 진짜 에러를 구분해 안내 톤을 다르게 한다.
      const sleeping = e instanceof ServerAsleepError
      setAsleep(sleeping)
      setError((e as Error).message)
      // 절전일 때만 정적 목록을 읽는다. 진짜 에러(500 등)엔 안 읽는다 — 그건 서버가
      // 살아 있는데 뭔가 잘못된 것이라, 정적 목록을 깔면 고장을 정상처럼 덮는다.
      // 한 번 받으면 다시 안 읽는다(태그·쪽 이동마다 같은 파일을 또 받지 않게).
      if (sleeping && !staticPosts) {
        const idx = await fetchDevlogIndex()
        if (seq === reqSeq.current && idx) setStaticPosts(idx.posts)
      }
    } finally {
      if (seq === reqSeq.current) setLoaded(true)
    }
  }

  useEffect(() => {
    // URL의 q가 바뀌면(뒤로가기 등) 검색 입력창을 그 값으로 되돌리는 의도된 동기화.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setQueryInput(q ?? '')
  }, [q])

  useEffect(() => {
    // deps가 `user`(객체)가 아니라 `user?.id`인 이유: 로그인 상태면 첫 렌더에 user=null로
    // 한 번 돌고, fetchMe가 도착해 user가 객체로 바뀌면 같은 effect가 또 돈다 → 매 방문마다
    // /posts를 2회 요청했다(2026-08-10 심층검사). 익명은 setUser(null)이 같은 값이라
    // 재실행되지 않아 영향이 없었고, 그래서 **로그인한 사람에게만** 두 배로 나갔다.
    // 목록 결과를 바꾸는 건 사용자의 신원(비공개 글 가시성)이므로 id만 보면 충분하다.
    //
    // 필터/페이지 변화 시 목록 재조회. loadPosts는 액션 후에도 재사용해 effect 밖에 두므로
    // deps에서 제외(넣으면 매 렌더 재생성으로 무한루프). setState는 await 뒤라 실제론 비동기.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadPosts()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, tag, q, page])

  // 사이드바 집계는 목록과 별개 — 페이지·검색과 무관하게 블로그 전체를 보여준다
  useEffect(() => {
    fetchPostsMeta()
      .then(setMeta)
      .catch(() => {})
    // 위 목록 effect와 같은 이유로 user 객체가 아니라 id를 본다(중복 요청 방지).
  }, [user?.id])

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

  // 절전 목록은 **태그만** 걸러낸다. 검색(q)은 서버가 본문까지 보고 판단하는데 정적
  // 목록엔 본문이 없다 — 제목·요약으로 흉내내면 "조건에 맞는 글이 없어"가 거짓이 된다.
  // 그래서 검색 중엔 거르지 않고, 본문까지 뒤지는 정적 아카이브로 안내한다.
  const sleepList = (staticPosts ?? []).filter((p) => !tag || (p.tags ?? []).includes(tag))

  const lastPage = Math.max(1, Math.ceil(total / POSTS_PAGE_SIZE))
  const first = total === 0 ? 0 : (page - 1) * POSTS_PAGE_SIZE + 1
  const last = Math.min(page * POSTS_PAGE_SIZE, total)

  return (
    <>
      {/* 목록 머리말.
          전에는 화면 절반을 쓰는 가운데 정렬 히어로였다 — 흐르는 그라데이션 제목,
          그 뒤의 색 번짐, "인프라를 직접 만들며 배운 것을 남깁니다"라는 아무 블로그에나
          붙는 문장, 그리고 구독 안내 한 문단. 넷 다 랜딩 페이지의 문법이지 **글 목록**의
          문법이 아니다. 참고로 본 D2와 velog는 목록 화면에 이런 구역 자체가 없다.
          첫 화면에서 제일 먼저 보여야 하는 건 글 제목이다.

          구독 안내를 지우지 않고 한 줄로 줄였다. 지우면 그 화면으로 가는 입구가
          사이드바 버튼 하나만 남는다. */}
      <section data-skin="hero" className="mb-8 border-b border-black/[0.08] pb-5 dark:border-white/10">
        <h1 className={`text-2xl font-bold tracking-tight ${ui.pageTitle}`}>글</h1>
        <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400">
          만들면서 겪은 것을 남긴다. 새 글 알림은{' '}
          <Link to="/subscriptions" className="text-accent hover:underline">
            구독
          </Link>
          에서.
        </p>
      </section>

      {/* 절전은 '고장'이 아니라 의도된 비용 절약이라 톤을 구분한다(빨강 에러 X). */}
      {asleep && (
        <p className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          💤 서버가 절전 중이야. 비용을 아끼려고 안 쓸 땐 꺼두거든 — 댓글·로그인은 깨어난 뒤에
          되고,{' '}
          {sleepList.length > 0 ? (
            '개발일지는 아래에서 지금 바로 읽을 수 있어.'
          ) : (
            <>
              개발일지는{' '}
              <a href="/devlog.html" className="underline">
                정적 아카이브
              </a>
              에서 지금 바로 읽을 수 있어.
            </>
          )}
        </p>
      )}
      {error && !asleep && <p className="mb-4 text-sm text-red-600">에러: {error}</p>}

      {/* 본문 + 우측 사이드바 2단. md(768px)+ = 옆으로(PC/태블릿), 그 아래(폰) = 세로 스택 */}
      <div data-skin="layout" className="grid gap-8 md:grid-cols-[1fr_18rem]">
      <div>
      {/* 검색 — Enter로 제출. 검색어는 URL(?q=)에 남아 뒤로가기·공유가 된다 */}
      <form onSubmit={handleSearch} className="mb-5 flex gap-2">
        <input
          type="search"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder="제목·본문 검색 (2글자 이상)"
          aria-label="글 검색"
          className="min-w-0 flex-1 rounded-btn border border-black/10 bg-white/70 px-4 py-2 text-sm outline-none transition placeholder:text-gray-400 focus:border-accent dark:border-white/15 dark:bg-white/5"
        />
        <button
          type="submit"
          className="shrink-0 rounded-btn bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent-hi"
        >
          검색
        </button>
      </form>

      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          {q ? (
            <>
              <span className="text-accent">"{q}"</span>
              <span className="text-base font-normal text-gray-400">검색 결과</span>
              <Link to={tag ? `/blog?tag=${encodeURIComponent(tag)}` : '/blog'} className="text-sm font-normal text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">✕ 검색 취소</Link>
            </>
          ) : tag ? (
            <>
              <span className="text-accent">#{tag}</span>
              <Link to="/blog" className="text-sm font-normal text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">✕ 전체보기</Link>
            </>
          ) : (
            '최근 글'
          )}
        </h2>
        {/* 로딩 중엔 개수를 단언하지 않는다 — '0개'는 사실 주장이다 */}
        <span className="text-sm text-gray-500 dark:text-gray-400">
          {/* 절전 중엔 '0개'가 거짓이다 — 서버에서 못 받았을 뿐 글은 있고, 바로 아래에
              그중 몇 편을 실제로 그리고 있다. 그럴 땐 그 수를 말한다. */}
          {!loaded
            ? '불러오는 중…'
            : asleep
              ? sleepList.length > 0
                ? `정적 목록 ${sleepList.length}편`
                : ''
              : total > 0
                ? `${total}개 중 ${first}–${last}`
                : '0개'}
        </span>
      </div>

      {/* 로딩 중 자리를 잡아두는 스켈레톤.
          **`posts.length === 0`도 봐야 한다.** 이게 없으면 재조회(2쪽 이동·태그·검색)마다
          기존 카드 10장 **위에** 스켈레톤 4장이 끼어들어 모바일 기준 약 700px이 밀렸다가
          응답이 오면 되돌아온다 — 레이아웃이 안 튀게 하려고 넣은 것이 정확히 반대로
          작동했다. 첫 진입에서만 의도대로였다. (2026-08-11 병목검사)
          기존 목록이 있으면 그걸 그대로 두는 게 맞다(stale-while-revalidate). */}
      {!loaded && posts.length === 0 && (
        <div className="grid gap-5 lg:grid-cols-2 2xl:grid-cols-3" aria-hidden>
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-40 animate-pulse rounded-2xl border border-black/[0.07] bg-black/[0.03] dark:border-white/10 dark:bg-white/[0.04]"
            />
          ))}
        </div>
      )}

      {/* 절전 중엔 목록이 비는 게 당연하므로 '글이 없다'는 안내를 겹쳐 띄우지 않는다.
          **`loaded`도 봐야 한다** — 첫 응답 전에는 '없다'가 아직 참이 아니다. */}
      {loaded && posts.length === 0 && !asleep && (
        <p className="rounded-2xl border border-dashed border-black/10 p-12 text-center text-gray-500 dark:border-white/15 dark:text-gray-400">
          {q || tag ? '조건에 맞는 글이 없어.' : '아직 글이 없어. 첫 글을 써봐!'}
        </p>
      )}

      {/* 절전 중 정적 목록. **링크는 SPA 라우트가 아니라 /devlog/*.html이다** —
          <Link to="/blog/posts/:id">로 바꾸면 서버가 꺼진 날 클릭이 죽어서, 목록을
          그린 의미가 사라진다(랜딩에서 같은 이유로 이미 한 번 잠가둔 성질이다). */}
      {asleep && sleepList.length > 0 && (
        <section aria-labelledby="static-devlog">
          <h3 id="static-devlog" className="sr-only">
            서버 없이 읽을 수 있는 개발일지
          </h3>
          {q && (
            <p className="mb-4 rounded-lg bg-black/[0.03] px-4 py-3 text-sm text-gray-600 dark:bg-white/[0.06] dark:text-gray-300">
              {/* 이 안내는 한때 거짓이었다 — 아카이브 검색이 제목·요약만 보던 때 "본문까지
                  찾으려면 저기서"라고 보냈다(2026-08-17 검사에서 잡혔다). 같은 날 그 검색이
                  본문을 읽게 고쳐서 지금은 사실이다. **한쪽만 되돌리면 다시 거짓이 된다.** */}
              검색은 서버가 있어야 해서 절전 중엔 못 해 — 아래는 검색어를 반영하지 않은 전체
              목록이야. 지금 찾고 싶으면{' '}
              <a href="/devlog.html" className="text-accent hover:underline">
                개발일지 아카이브
              </a>
              에서 찾아줘(제목·본문까지 뒤지고, 서버 없이 돌아).
            </p>
          )}
          <ul className="divide-y divide-black/[0.07] border-y border-black/[0.07] dark:divide-white/10 dark:border-white/10">
            {sleepList.map((p) => (
              <li key={p.date}>
                <a href={`/${p.slug}`} className="group block py-4">
                  <div className="flex items-baseline gap-3">
                    <time className="shrink-0 font-mono text-xs text-gray-500 dark:text-gray-400">
                      {p.date}
                    </time>
                    <h4 className="font-medium group-hover:text-accent">
                      {p.title}
                    </h4>
                  </div>
                  {p.summary && (
                    <p className="mt-1.5 line-clamp-2 text-sm text-gray-500 dark:text-gray-400">
                      {p.summary}
                    </p>
                  )}
                </a>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
            이 목록과 링크는 서버 없이 동작해 ·{' '}
            <a href="/devlog.html" className="hover:underline">
              전체 아카이브
            </a>{' '}
            ·{' '}
            <a href="/rss.xml" className="hover:underline">
              RSS
            </a>
          </p>
        </section>
      )}

      {/* 글 목록 — 격자가 아니라 한 줄씩 쌓는 목록이다.
          전에는 2~3열 카드 격자였고, 커버 없는 글은 16:9 자리표시를 크게 그렸다.
          그런데 이 블로그 글은 **거의 다 커버가 없어서** 목록 한 화면의 절반이
          빈 회색 상자가 됐다. 카드 격자는 각 칸에 그림이 있을 때 성립하는 형식이다.
          글만 있는 블로그는 목록이 맞다(D2·velog의 목록 화면이 그렇고, 무엇보다
          제목이 먼저 읽힌다). 커버가 **있는** 글만 오른쪽에 작게 붙인다. */}
      <div data-skin="post-grid" className="divide-y divide-black/[0.08] border-b border-black/[0.08] dark:divide-white/10 dark:border-white/10">
        {posts.map((post, i) => (
          <Reveal key={post.id} delay={Math.min(i * 60, 300)}>
          <article
            data-skin="post-card"
            className={`grid gap-x-6 py-6 ${post.cover_image ? 'sm:grid-cols-[1fr_10rem]' : 'grid-cols-1'}`}
          >
            {/* 커버가 있을 때만 그린다. 없으면 **아무것도 안 그린다** — 예전엔 편 번호를
                큰 상자에 얹어 자리를 채웠는데, 채울 것이 없는데 자리를 채우면 그게 곧
                빈 상자다. 목록에서는 제목이 그 자리를 대신한다. */}
            {post.cover_image && (
              <Link
                data-skin="post-thumb"
                to={`/blog/posts/${post.id}`}
                className="order-first mb-3 block overflow-hidden rounded-field sm:order-none sm:col-start-2 sm:row-start-1 sm:row-end-[-1] sm:mb-0 sm:self-start"
              >
                <img src={post.cover_image} alt="" loading="lazy" className="aspect-[16/9] w-full object-cover" />
              </Link>
            )}
            <h3 data-skin="post-title" className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <Link to={`/blog/posts/${post.id}`} className="transition hover:text-accent">{post.title}</Link>
              {post.visibility === 'private' && (
                <span className="inline-flex items-center gap-1 rounded-btn bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500 dark:bg-white/10 dark:text-gray-400">
                  <IconLock className="h-3 w-3" />비공개
                </span>
              )}
              {post.visibility === 'subscribers' && (
                <span className="inline-flex items-center gap-1 rounded-btn bg-blue-50 px-2 py-0.5 text-xs font-medium text-accent">
                  구독자공개
                </span>
              )}
            </h3>
            <Link data-skin="post-excerpt" to={`/blog/posts/${post.id}`} className="mt-2 block text-gray-500 transition hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
              <p className="line-clamp-2 leading-relaxed">
                {post.excerpt}
              </p>
            </Link>
            {post.tags.length > 0 && (
              <div data-skin="post-tags" className="mt-3 flex flex-wrap gap-1.5">
                {post.tags.slice(0, 4).map((t) => (
                  <Link
                    key={t}
                    to={`/blog?tag=${encodeURIComponent(t)}`}
                    className="rounded-btn bg-black/[0.05] px-2 py-0.5 text-xs text-gray-600 transition hover:bg-accent/10 hover:text-accent dark:bg-white/10 dark:text-gray-300"
                  >
                    #{t}
                  </Link>
                ))}
              </div>
            )}
            <div data-skin="post-meta" className="mt-3 flex items-center justify-between">
              <time className="text-xs text-gray-500 dark:text-gray-400">
                {new Date(post.created_at).toLocaleDateString()} · {post.reading_minutes}분 읽기
              </time>
              {/* 본인 글이거나 관리자면 수정·삭제 버튼 노출 */}
              {user && (post.owner_id === user.id || user.role === 'admin') && (
                <div className="flex gap-3 text-sm">
                  <Link to={`/blog/posts/${post.id}/edit`} className="text-accent hover:underline">수정</Link>
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
            className="rounded-btn border border-black/10 px-4 py-1.5 text-sm transition enabled:hover:border-accent enabled:hover:text-accent disabled:opacity-40 dark:border-white/15"
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
            className="rounded-btn border border-black/10 px-4 py-1.5 text-sm transition enabled:hover:border-accent enabled:hover:text-accent disabled:opacity-40 dark:border-white/15"
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
