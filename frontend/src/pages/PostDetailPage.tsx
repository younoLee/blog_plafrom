import { useEffect, useMemo, useRef, useState, type ComponentPropsWithoutRef } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import rehypeSlug from 'rehype-slug'
import type { Post, SeriesNav, Visibility } from '../types/post'
import type { Comment } from '../types/comment'
import { getPost, changeVisibility, fetchSeries } from '../api/posts'
import { fetchComments, addComment, deleteComment } from '../api/comments'
import { ServerAsleepError } from '../api/http'
import { fetchMySubscriptions, subscribeAuthor, unsubscribeAuthor } from '../api/subscriptions'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'
import { IconArrowLeft, IconLock, IconCheck } from '../components/icons'
import { Reveal } from '../components/Reveal'
import { Toc } from '../components/Toc'
import { SeriesBox, SeriesPrevNext } from '../components/SeriesBox'
import { readingTime, archiveUrlFor, excerpt, relatedPosts, type ArchivePost } from '../postUtils'
import { useHead } from '../useDocumentTitle'
import { CopyButton } from '../components/CopyButton'

const { input, btnPrimary, btnGhost } = ui

/** 코드블록 + 복사 버튼.
 *
 *  복사할 값을 마크다운 원문이 아니라 **렌더된 DOM의 innerText**에서 읽는다. 원문에는
 *  펜스(```)와 언어 태그가 섞여 있어 그대로 복사하면 붙여넣은 쪽에서 안 돌아간다.
 *
 *  `node`는 react-markdown이 주는 AST 노드다. DOM 속성이 아니라서 <pre>에 그대로
 *  펼치면 React가 경고를 뱉는다 — 여기서 떼어낸다. */
export function CodeBlock({ children, ...props }: ComponentPropsWithoutRef<'pre'> & { node?: unknown }) {
  const ref = useRef<HTMLPreElement>(null)
  // props는 rest로 만든 새 객체라 지워도 호출부에 영향이 없다.
  // (`{ node: _node, ... }`로 떼면 안 쓰는 변수가 되어 eslint가 막는다)
  delete props.node
  return (
    // ⚠️ **마진은 wrapper가 진다. `<pre>`는 my-0이다.** 감싸기만 하고 두면 세로 리듬이 깨진다:
    //    @tailwindcss/typography에 `.prose :where(h2+*,h3+*,h4+*,hr+*){margin-top:0}` 과
    //    `.prose>:first-child{margin-top:0}` / `:last-child{margin-bottom:0}` 이 있는데,
    //    이제 그 규칙들이 무는 건 `<pre>`가 아니라 이 div다. div의 마진을 0으로 만들어도
    //    안쪽 `<pre>`의 margin 1.71429em이 **마진 상쇄로 그대로 밖에 나온다**
    //    (`position:relative`는 BFC를 안 만들어 상쇄를 못 막는다). 그러면 소제목 바로 뒤
    //    코드블록에 없던 여백 ~27px이 생긴다.
    //    1.5em = pre의 1.71429em × pre의 font-size .875em (둘 다 typography 기본값).
    //
    //    📏 **여기 "이 블로그에서 가장 흔한 배치다"라고 적혀 있었는데 사실이 아니었다.**
    //    2026-08-15에 세어보니 content/devlog의 여는 코드펜스 **193개 중 소제목 바로 뒤는
    //    0개**다(99%가 보통 문단 뒤). 즉 이 wrapper가 실제로 막고 있는 건 `h2+*` 경로가
    //    아니라 **모든 코드블록의 위아래 간격**이다 — 마진 상쇄는 앞 요소가 무엇이든 난다.
    //    수정 자체는 옳다. 틀린 건 근거로 적어둔 문장이었고, 그 문장 때문에 "소제목 뒤를
    //    눈으로 확인하라"는 없는 숙제가 하나 생겨 있었다.
    <div className="group relative my-[1.5em] [&>pre]:my-0">
      <pre ref={ref} {...props}>
        {children}
      </pre>
      {/* 모바일엔 hover가 없다 — 작은 화면에서는 항상 보이고, 큰 화면에서만 hover로 나타난다. */}
      <CopyButton
        value={() => ref.current?.innerText ?? ''}
        label="복사"
        title="코드 복사"
        className="absolute right-2 top-2 rounded-md border border-white/15 bg-black/40 px-2 py-1 text-xs text-white/80 backdrop-blur transition hover:bg-black/60 hover:text-white focus:opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
      />
    </div>
  )
}

function PostDetailPage() {
  const { id } = useParams<{ id: string }>()
  const postId = Number(id)
  const { user } = useAuth()
  const [post, setPost] = useState<Post | null>(null)
  // 탭 제목·설명·canonical·OG는 archiveUrl이 정해진 **뒤에** 건다(아래 useHead).
  const [error, setError] = useState('')
  // 절전(서버 꺼짐)과 진짜 에러의 톤을 가른다. HomePage는 이미 그렇게 하는데
  // 여기만 절전도 빨간 "에러:"로 보여 고장처럼 읽혔다(2026-08-11 공백검사).
  const [asleep, setAsleep] = useState(false)
  const [subscribed, setSubscribed] = useState(false)
  const [series, setSeries] = useState<SeriesNav | null>(null)
  // 공유용 주소. **아래 리셋 블록보다 먼저 선언해야 한다** — 리셋은 렌더 중에 도는데
  // 선언이 그 아래 있으면 TDZ(초기화 전 접근)로 죽는다. 규칙은 postUtils.archiveUrlFor에.
  const [archiveUrl, setArchiveUrl] = useState<string | null>(null)
  // 같은 파일에서 '관련 글'도 만든다(아래 relatedPosts). 정적 인덱스라 서버와 무관하다.
  const [archiveIndex, setArchiveIndex] = useState<ArchivePost[] | null>(null)

  const [comments, setComments] = useState<Comment[]>([])
  const [author, setAuthor] = useState('')
  const [text, setText] = useState('')

  // **글이 바뀌면 렌더 중에 비운다.** 이게 없으면 연재 '다음 편'을 눌렀을 때 새 글이
  // 도착할 때까지(서버가 차가우면 최대 8초) **이전 글의 본문·댓글·목차가 그대로** 보인다.
  // 이전 글이 full height라 스크롤도 유지돼 새 글의 중간에 떨어지고, 사용자는 클릭이
  // 안 먹은 줄 알고 다시 누른다. (2026-08-11 공백검사)
  //
  // effect가 아니라 **렌더 중**인 이유: effect는 페인트 뒤에 돌아서 옛 글이 한 프레임
  // 그려진 뒤 지워진다 — 없애려는 그 잔상을 그대로 만든다. React가 권장하는
  // '프롭이 바뀔 때 상태 조정' 패턴이다(이 setState는 커밋 전에 리렌더로 흡수된다).
  //
  // ⚠️ **비교는 숫자(postId)가 아니라 URL 문자열(id)로 한다.** `Number("abc")`는 NaN이고
  //    `NaN !== NaN`은 **항상 참**이라, 숫자로 비교하면 렌더마다 setState가 다시 걸려
  //    무한 루프가 난다. React의 상태 bailout은 `Object.is`를 쓰고 `Object.is(NaN,NaN)`는
  //    true라 상태는 안 바뀌지만, **조건문이 매번 참**이라 루프는 그대로다.
  //    재현함(react-dom/server, 2026-08-11): id="12" 정상 / id="abc" → Too many re-renders.
  //    그러면 App 최상단 ErrorBoundary가 잡아 **헤더까지 통째로 사라진다** —
  //    `/blog/posts/abc` 같은 오타 하나로 앱 전체가 죽는다. 이 패턴을 넣기 전엔
  //    getPost(NaN)이 422를 받아 빨간 줄 하나로 끝났다(= 오늘 내가 만든 회귀다).
  const [shownId, setShownId] = useState(id)
  if (shownId !== id) {
    setShownId(id)
    setPost(null)
    setComments([])
    setSeries(null)
    setError('')
    setAsleep(false)
    setSubscribed(false) // 이게 빠져서 남의 글에 "구독중 ✓"이 남았다
    // 이것도 빠져 있었다(2026-08-12 검사에서 재현). 공유 주소는 `post`가 도착한 **뒤에야**
    // 조회를 시작하므로, 안 비우면 B 글이 그려진 화면에서 "링크 복사"가 **A 글의 주소**를
    // 준다. 연재 '다음 편' 클릭이 정확히 그 경로다. 위 목록에 한 줄 더 붙는 게 아니라,
    // **화면에 보이는 것과 짝이 안 맞는 상태는 전부 여기서 죽어야 한다**는 규칙의 일부다.
    setArchiveUrl(null)
  }

  useEffect(() => {
    // **숫자가 아닌 id는 요청조차 하지 않는다.** 리셋 판정은 문자열 `id`로 하는데
    // 이 effect의 deps는 `postId`(숫자)라, `/blog/posts/abc` → `/blog/posts/def`처럼
    // 둘 다 NaN이면 `Object.is(NaN, NaN)`이 true여서 effect가 안 돈다. 화면 표시는
    // 아래 `invalidId`로 렌더에서 직접 판정하므로(상태를 안 쓴다) 여기선 요청만 막는다.
    // 크래시를 고치면서 만든 짝이다(2026-08-11 병목검사).
    if (!Number.isFinite(postId)) return

    // **늦게 온 응답이 이미 넘어간 화면을 덮어쓰지 않게 한다.** 이 취소 플래그가
    // 없으면 A→B로 넘긴 뒤 A의 응답이 도착해 B 화면에 A의 본문·댓글이 그려진다
    // (차가운 서버는 8초까지 걸리니 겹칠 시간이 충분하다). 렌더 중 리셋은 화면을
    // 비우기만 할 뿐 in-flight 요청을 취소하지 못한다 — 둘 다 필요하다.
    let alive = true
    getPost(postId)
      .then((p) => alive && setPost(p))
      .catch((e) => {
        if (!alive) return
        setAsleep(e instanceof ServerAsleepError)
        setError((e as Error).message)
      })
    fetchComments(postId)
      .then((c) => alive && setComments(c))
      .catch((e) => {
        // 댓글 실패로 글 읽기의 에러 톤을 덮어쓰지 않는다 — 본문 쪽 상태가 우선이다.
        if (alive) setAsleep((prev) => prev || e instanceof ServerAsleepError)
      })
    // 연재는 부가정보 — 실패해도 글 읽기를 막지 않는다(fetchSeries가 null을 준다)
    fetchSeries(postId).then((s) => alive && setSeries(s))
    return () => {
      alive = false
    }
  }, [postId, id]) // id도 deps에 — 둘 다 NaN인 경로에서 effect가 안 도는 걸 막는다

  // 이 글의 작성자를 내가 구독 중인지 확인
  useEffect(() => {
    if (!user || !post?.owner_id) return
    fetchMySubscriptions()
      .then((ids) => setSubscribed(ids.includes(post.owner_id!)))
      .catch(() => {})
  }, [user, post?.owner_id])

  async function toggleSubscribe() {
    if (!post?.owner_id) return
    try {
      if (subscribed) await unsubscribeAuthor(post.owner_id)
      else await subscribeAuthor(post.owner_id)
      setSubscribed(!subscribed)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function handleAddComment(e: React.FormEvent) {
    e.preventDefault()
    // 로그인 사용자는 계정 이름(이메일 로컬파트)으로 고정 — 서버도 동일하게 강제(사칭 방지).
    // 익명만 입력칸의 author 사용.
    const name = user ? user.email.split('@')[0] : author.trim()
    if (!name || !text.trim()) return
    try {
      await addComment(postId, name, text)
      setText('')
      setComments(await fetchComments(postId))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // 글 작성자 본인 또는 관리자면 댓글 삭제(모더레이션) + 공개범위 변경 가능
  const canModerate = !!user && !!post && (user.role === 'admin' || post.owner_id === user.id)

  // 작성 후 공개범위 빠른 전환 (본인/관리자만)
  async function handleChangeVisibility(v: Visibility) {
    if (!post) return
    try {
      const updated = await changeVisibility(post.id, v)
      setPost(updated)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function handleDeleteComment(commentId: number) {
    try {
      await deleteComment(postId, commentId)
      setComments(await fetchComments(postId))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // 본문 마크다운은 '내용'이 바뀔 때만 다시 만든다(메모이즈). 댓글·구독·공개범위 등 다른 상태가
  // 바뀌어 페이지가 재렌더돼도 같은 엘리먼트 참조라 React가 이 큰 서브트리를 재조정하지 않음
  // → 자동번역으로 텍스트 노드가 바뀐 상태에서의 재조정 크래시를 예방.
  // content만 따로 빼서 의존성으로 둠(post 객체 참조가 아니라 내용 기준 → exhaustive-deps도 충족).
  // 잘못된 주소는 상태가 아니라 파생값이다 — effect에서 setError를 하면 eslint가
  // 옳게 잡는다(연쇄 렌더). 렌더에서 바로 판정하면 상태가 하나 줄고 경로도 짧다.
  const invalidId = !Number.isFinite(postId)

  // 목록은 빌드 산출물이라 /api가 아니라 정적 파일에서 읽는다. 로컬 dev에는 그 파일이
  // 없어서 404가 정상이고, 그때는 현재 주소로 공유한다.
  const postTitle = post?.title
  useEffect(() => {
    if (!postTitle) return
    let alive = true
    fetch('/devlog-index.json')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { posts?: ArchivePost[] } | null) => {
        if (!alive) return
        setArchiveUrl(archiveUrlFor(d?.posts, postTitle, window.location.origin))
        // 같은 재료로 '관련 글'도 만든다 — 이미 받은 파일이라 요청이 안 는다.
        setArchiveIndex(d?.posts ?? null)
      })
      .catch(() => {
        if (!alive) return
        setArchiveUrl(null)
        setArchiveIndex(null)
      })
    return () => {
      alive = false
    }
  }, [postTitle])

  const related = useMemo(
    () => relatedPosts(archiveIndex, post?.title, post?.tags),
    [archiveIndex, post?.title, post?.tags],
  )

  // **해시로 들어오면 그 자리로 데려간다.** 이 앱엔 해시 처리가 아예 없었다:
  //   - 브라우저의 기본 스크롤은 문서 로드 시점에 일어나는데, 이 화면은 본문이
  //     /api에서 **나중에** 온다. 그때 #comments도 #소제목도 DOM에 없다.
  //   - 앱 안에서의 이동은 라우터가 처리하므로 브라우저 스크롤이 아예 안 걸린다.
  // 그래서 댓글 알림(종·푸시)이 `#comments`로 보내도 글 맨 위에 떨어졌고,
  // 목차의 소제목 링크도 새로고침하면 안 먹었다. 본문이 붙은 뒤에 한 번 맞춘다.
  const hash = useLocation().hash
  const loadedId = post?.id
  useEffect(() => {
    if (!hash || !loadedId) return
    // 이 프레임엔 아직 마크다운 서브트리가 안 붙었을 수 있다(useMemo로 만들어
    // 같은 커밋에 들어가지만, 이미지·폰트로 높이가 더 자란다). 다음 프레임에 잰다.
    const id = requestAnimationFrame(() => {
      document
        .getElementById(decodeURIComponent(hash.slice(1)))
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
    return () => cancelAnimationFrame(id)
  }, [hash, loadedId])

  // 검색엔진·미리보기용 head. **canonical은 정적 아카이브를 가리킨다** — 같은 글이 두
  // 주소에 있는데(여기와 /devlog/*.html) 표준을 안 정하면 서로의 중복이 되고, EC2가
  // 평소 꺼져 있어 방문자에게도 정적 쪽이 실제로 열리는 주소다. 아카이브가 없는 일반
  // 글이면 canonical은 현재 주소가 된다(head.ts 기본값).
  //
  // 설명은 **공개글만** 넣는다. 구독자공개·비공개 글의 본문 발췌를 메타 태그로
  // 흘릴 이유가 없다(태그는 로그인 상태와 무관하게 DOM에 남는다).
  useHead({
    title: post?.title,
    description:
      post && post.visibility === 'public' ? excerpt(post.content, 160) : undefined,
    canonical: archiveUrl ?? undefined,
    type: post ? 'article' : 'website',
  })

  const content = post?.content
  const body = useMemo(
    () =>
      content != null ? (
        <ReactMarkdown
          // ⚠️ 보안: rehype-raw / allowDangerousHtml 를 추가하지 마라. 글 본문은 사용자·AI초안이
          // 만든 값이고 서버에서 HTML을 새니타이즈하지 않는다. react-markdown 기본값은 raw HTML을
          // 렌더 안 해(무해 텍스트) → 그게 유일한 저장형 XSS 방어선이다. 넣는 순간 공개 블로그에
          // <img onerror> 같은 게 실행된다(2026-07-24 인젝션 심층검사에서 확인).
          // rehypeHighlight를 뺐다(2026-08-10 심층검사). 이 블로그의 코드펜스는
          // content/devlog/*.md 260개가 **전부 언어 태그가 없고**(```만 쓴다), 렌더 결과에
          // language-* 클래스가 0건이다. rehype-highlight는 언어 클래스가 없고 detect가
          // 기본 false면 그냥 return하므로 **단 한 블록도 하이라이트하지 않고 있었다** —
          // 번들에서 highlight.js 159.8 KB(gzip 50.6)를 지고 하는 일이 0이었다.
          // 화면은 전혀 변하지 않는다. 앞으로 ```bash처럼 언어를 붙여 쓸 생각이면
          // 그때 {languages: {...}} 서브셋으로 되살려라(공통 37언어 전체는 172 KB, 7개면 52.9 KB).
          // rehypeSlug: 소제목에 id를 붙인다 → 목차(Toc)의 #앵커가 여기로 점프
          rehypePlugins={[rehypeSlug]}
          components={{
            // loading/decoding은 **예방**이다. 지금 공개 글 30편에 본문 이미지가 0건이라
            // 체감 효과가 없지만, 업로드는 원본을 그대로 서빙하므로(리사이즈 파이프라인 없음)
            // 첫 이미지 글이 올라가는 순간부터 화면 밖 사진까지 즉시 내려받게 된다.
            img: (props) => <img {...props} loading="lazy" decoding="async" className="rounded-lg" />,
            pre: CodeBlock,
          }}
        >
          {content}
        </ReactMarkdown>
      ) : null,
    [content],
  )

  return (
    /* 넓은 화면(xl↑)에서만 왼쪽에 목차 칸을 낸다.
       왜 xl인가 — 본문 폭(max-w-3xl ≈ 48rem)을 줄이지 않고 목차를 붙이려면 그만큼
       더 필요하다. 좁은 화면에서 억지로 2단을 만들면 본문 줄이 짧아져 읽기가 나빠지고,
       그건 목차가 주는 이득보다 크다. 그 아래에서는 지금까지처럼 본문 위에 한 덩어리로
       둔다(아래 Toc variant="inline").
       가운데 정렬: 목차 칸(13rem+간격)만큼 왼쪽으로 밀리지 않게 grid를 통째로 가운데 둔다. */
    <div className="mx-auto max-w-3xl xl:grid xl:max-w-[calc(48rem+16rem)] xl:grid-cols-[13rem_minmax(0,1fr)] xl:gap-x-12">
      <div className="xl:col-start-2">
      <Link to="/blog" className="inline-flex items-center gap-1 text-sm text-accent hover:underline">
        <IconArrowLeft className="h-4 w-4" />목록으로
      </Link>

      {/* 절전은 '고장'이 아니라 의도된 비용 절약이다 — HomePage와 같은 톤을 쓴다.
          여기만 빨간 "에러:"로 보여서, 링크를 타고 글로 바로 들어온 사람에게는
          이 사이트가 망가진 것처럼 보였다. 정적 아카이브로 안내해 읽을 길을 준다. */}
      {asleep && (
        <p className="mt-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          💤 서버가 절전 중이야. 비용을 아끼려고 안 쓸 땐 꺼두거든 — 글은 깨어난 뒤에 보여.{' '}
          <a href="/devlog.html" className="font-medium underline">
            개발일지 아카이브
          </a>
          는 서버 없이도 읽을 수 있어.
        </p>
      )}
      {invalidId && (
        <p role="alert" className="mt-4 text-sm text-red-600">
          글을 찾을 수 없어 — 주소가 올바른지 확인해줘.
        </p>
      )}
      {!invalidId && error && !asleep && (
        <p role="alert" className="mt-4 text-sm text-red-600">에러: {error}</p>
      )}

      {/* 아직 안 왔고 실패도 아니면 로딩이다. 예전엔 이 자리가 통째로 비어
          "목록으로" 링크 한 줄만 있는 백지였다. */}
      {!post && !error && !invalidId && (
        <div className="mt-4 space-y-3" aria-hidden>
          <div className="h-9 w-2/3 animate-pulse rounded-lg bg-black/[0.06] dark:bg-white/[0.08]" />
          <div className="h-64 animate-pulse rounded-2xl bg-black/[0.03] dark:bg-white/[0.04]" />
        </div>
      )}

      {post && (
        <Reveal>
        <article className="mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
          {post.cover_image && (
            <img src={post.cover_image} alt="" className="mb-6 aspect-[2/1] w-full rounded-xl object-cover" />
          )}
          <h1 className="flex items-center gap-2 text-3xl font-semibold tracking-tight">
            {post.title}
            {post.visibility === 'private' && (
              <span className="inline-flex items-center gap-1 rounded-btn bg-gray-100 px-2 py-1 text-sm text-gray-500 dark:bg-white/10 dark:text-gray-400">
                <IconLock className="h-3.5 w-3.5" />비공개
              </span>
            )}
            {post.visibility === 'subscribers' && (
              <span className="inline-flex items-center gap-1 rounded-btn bg-blue-50 px-2 py-1 text-sm text-accent">
                구독자공개
              </span>
            )}
          </h1>
          <div className="mt-2 flex items-center gap-3">
            <time className="text-sm text-gray-500 dark:text-gray-400">
              {new Date(post.created_at).toLocaleString()} · {readingTime(post.content)}분 읽기
            </time>
            <CopyButton
              value={() => archiveUrl ?? window.location.href}
              label="링크 복사"
              copiedLabel="복사됨 ✓"
              title={
                archiveUrl
                  ? '서버가 꺼져 있어도 열리는 주소를 복사한다 (미리보기 카드도 이 글로 뜬다)'
                  : '이 페이지 주소를 복사한다'
              }
              className="rounded-btn border border-black/[0.1] px-3 py-1 text-sm text-gray-500 transition hover:bg-black/[0.03] dark:border-white/15 dark:text-gray-400 dark:hover:bg-white/[0.06]"
            />
            {/* 로그인 + 남의 글이면 글쓴이 구독 버튼 (구독하면 그 사람 비공개글도 볼 수 있음) */}
            {user && post.owner_id && post.owner_id !== user.id && (
              <button type="button" onClick={toggleSubscribe} className={subscribed ? btnGhost : btnPrimary}>
                {/* 텍스트는 항상 span으로 감싸 맨 텍스트 노드 토글을 피함(insertBefore 크래시 방지) */}
                {subscribed && <IconCheck className="h-4 w-4" />}
                <span>{subscribed ? '구독중' : '+ 글쓴이 구독'}</span>
              </button>
            )}
            {/* 본인/관리자: 작성 후에도 공개범위를 여기서 바로 바꿀 수 있음 */}
            {canModerate && (
              <label className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400">
                공개범위:
                <select
                  value={post.visibility}
                  onChange={(e) => handleChangeVisibility(e.target.value as Visibility)}
                  className="rounded-lg border border-black/10 bg-white px-2 py-1 text-sm text-gray-700 dark:border-white/15 dark:bg-[#1c1c1e] dark:text-gray-200"
                  aria-label="공개범위 변경"
                >
                  <option value="public">전체공개</option>
                  <option value="subscribers">구독자공개</option>
                  <option value="private">비공개(나만)</option>
                </select>
              </label>
            )}
          </div>
          {post.tags.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {post.tags.map((t) => (
                <Link
                  key={t}
                  to={`/blog?tag=${encodeURIComponent(t)}`}
                  className="rounded-btn bg-black/[0.05] px-2.5 py-1 text-xs font-medium text-gray-600 transition hover:bg-accent/10 hover:text-accent dark:bg-white/10 dark:text-gray-300"
                >
                  #{t}
                </Link>
              ))}
            </div>
          )}
          {/* 목차(좁은 화면) — 본문 앞 한 덩어리. 넓은 화면에서는 왼쪽 고정본이 대신하므로
              숨긴다. 둘을 같이 그리면 같은 목차가 두 번 보인다.
              소제목이 2개 미만이면 Toc이 알아서 안 그린다. */}
          <div className="xl:hidden">
            <Toc content={post.content} />
          </div>
          {/* 마크다운 본문: prose로 자동 타이포그래피, 다크모드는 prose-invert */}
          <div className="prose prose-gray mt-6 max-w-none prose-headings:tracking-tight prose-a:text-accent prose-a:no-underline hover:prose-a:underline prose-img:rounded-xl dark:prose-invert">
            {body}
          </div>
        </article>
        </Reveal>
      )}

      {/* 연재: 본문 다 읽은 뒤에 '다음 편' + 전체 목록이 오게 본문 아래 배치 */}
      {series && (
        <>
          <SeriesPrevNext nav={series} />
          <SeriesBox nav={series} currentId={postId} />
        </>
      )}

      {/* 같은 주제의 다른 편. 링크는 SPA 주소가 아니라 **정적 아카이브**로 건다 —
          이 사이트는 EC2를 평소 꺼두므로 추천을 눌렀는데 안 열리면 추천이 아니다.
          겹치는 태그가 없으면 relatedPosts가 빈 배열을 주고 블록 자체가 안 나온다. */}
      {related.length > 0 && (
        <section className="mt-6 rounded-2xl border border-black/[0.07] bg-white p-6 dark:border-white/10 dark:bg-white/[0.06]">
          <h2 className="mb-4 text-lg font-semibold tracking-tight">비슷한 주제의 편</h2>
          <ul className="space-y-3">
            {related.map(({ post: r, shared }) => (
              <li key={r.slug}>
                <a
                  href={`/${r.slug.replace(/^\//, '')}`}
                  className="font-medium text-accent hover:underline"
                >
                  {r.title}
                </a>
                <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
                  {r.date} · {shared.join(' · ')}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section
        id="comments"
        className="mt-6 rounded-2xl border border-black/[0.07] bg-white p-6 dark:border-white/10 dark:bg-white/[0.06]"
      >
        <h2 className="mb-4 text-lg font-semibold tracking-tight">
          댓글 <span className="text-gray-500 dark:text-gray-400">({comments.length})</span>
        </h2>
        {comments.length === 0 && <p className="text-gray-500 dark:text-gray-400">아직 댓글이 없어. 첫 댓글을 남겨봐.</p>}
        <div className="space-y-3">
          {comments.map((c) => (
            <div key={c.id} className="rounded-xl bg-black/[0.03] p-3 dark:bg-white/[0.04]">
              <div className="flex items-baseline gap-2">
                <strong className="text-gray-800 dark:text-gray-100">{c.author}</strong>
                {/* 회원 표시는 **서버가 준 사실(is_member)에서만** 나온다. author는 표시값이라
                    익명이 같은 문자열을 칠 수 있다(2026-08-10 사칭 재현).
                    배지를 '회원' 쪽에 다는 방향인 게 중요하다 — 반대로 '익명'에만 표를 달면
                    그 표가 빠지는 순간 사칭이 다시 통한다(fail-open). */}
                {c.is_member ? (
                  <span className="rounded-btn bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                    회원
                  </span>
                ) : (
                  <span className="text-[10px] text-gray-500 dark:text-gray-400">익명</span>
                )}
                <time className="text-xs text-gray-500 dark:text-gray-400">{new Date(c.created_at).toLocaleString()}</time>
                {canModerate && (
                  <button
                    type="button"
                    onClick={() => handleDeleteComment(c.id)}
                    className="ml-auto text-xs text-gray-400 hover:text-red-500"
                    aria-label="댓글 삭제"
                  >
                    삭제
                  </button>
                )}
              </div>
              <p className="mt-1 whitespace-pre-wrap text-gray-700 dark:text-gray-300">{c.content}</p>
            </div>
          ))}
        </div>

        <form onSubmit={handleAddComment} className="mt-5 grid gap-2">
          {user ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              작성자: <strong className="text-gray-700 dark:text-gray-200">{user.email.split('@')[0]}</strong>
            </p>
          ) : (
            <input placeholder="이름" value={author} onChange={(e) => setAuthor(e.target.value)} className={`${input} max-w-xs`} />
          )}
          <textarea placeholder="댓글 내용" rows={3} value={text} onChange={(e) => setText(e.target.value)} className={input} />
          <button type="submit" className={`${btnPrimary} justify-self-start`}>댓글 작성</button>
        </form>
      </section>
      </div>

      {/* 왼쪽 고정 목차 — 넓은 화면에서만. **DOM에서는 본문 뒤에 둔다.**
          화면에서는 왼쪽(col-start-1)이지만, 읽는 순서와 탭 순서는 '본문 → 목차'가 맞다.
          목차를 앞에 두면 키보드 사용자가 글에 닿기 전에 목차 링크를 전부 지나야 한다
          (Layout이 '본문 바로가기'를 둔 것과 같은 이유다). */}
      {post && (
        <aside className="hidden xl:col-start-1 xl:row-start-1 xl:block">
          <Toc content={post.content} variant="aside" />
        </aside>
      )}
    </div>
  )
}

export default PostDetailPage
