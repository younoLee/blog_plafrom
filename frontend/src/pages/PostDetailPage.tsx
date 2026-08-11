import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
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
import { readingTime } from '../postUtils'
import { useDocumentTitle } from '../useDocumentTitle'

const { input, btnPrimary, btnGhost } = ui

function PostDetailPage() {
  const { id } = useParams<{ id: string }>()
  const postId = Number(id)
  const { user } = useAuth()
  const [post, setPost] = useState<Post | null>(null)
  // 브라우저 탭/북마크/검색결과에 글 제목이 뜨도록 (글 로딩 전엔 사이트 기본 제목)
  useDocumentTitle(post?.title)
  const [error, setError] = useState('')
  // 절전(서버 꺼짐)과 진짜 에러의 톤을 가른다. HomePage는 이미 그렇게 하는데
  // 여기만 절전도 빨간 "에러:"로 보여 고장처럼 읽혔다(2026-08-11 공백검사).
  const [asleep, setAsleep] = useState(false)
  const [subscribed, setSubscribed] = useState(false)
  const [series, setSeries] = useState<SeriesNav | null>(null)

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
  const [shownId, setShownId] = useState(postId)
  if (shownId !== postId) {
    setShownId(postId)
    setPost(null)
    setComments([])
    setSeries(null)
    setError('')
    setAsleep(false)
  }

  useEffect(() => {
    getPost(postId)
      .then(setPost)
      .catch((e) => {
        setAsleep(e instanceof ServerAsleepError)
        setError((e as Error).message)
      })
    fetchComments(postId)
      .then(setComments)
      .catch((e) => {
        // 댓글 실패로 글 읽기의 에러 톤을 덮어쓰지 않는다 — 본문 쪽 상태가 우선이다.
        setAsleep((prev) => prev || e instanceof ServerAsleepError)
      })
    // 연재는 부가정보 — 실패해도 글 읽기를 막지 않는다(fetchSeries가 null을 준다)
    fetchSeries(postId).then(setSeries)
  }, [postId])

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
          components={{ img: (props) => <img {...props} className="rounded-lg" /> }}
        >
          {content}
        </ReactMarkdown>
      ) : null,
    [content],
  )

  return (
    <div className="mx-auto max-w-3xl">
      <Link to="/blog" className="inline-flex items-center gap-1 text-sm text-[#0071e3] hover:underline dark:text-[#0a84ff]">
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
      {error && !asleep && <p role="alert" className="mt-4 text-sm text-red-600">에러: {error}</p>}

      {/* 아직 안 왔고 실패도 아니면 로딩이다. 예전엔 이 자리가 통째로 비어
          "목록으로" 링크 한 줄만 있는 백지였다. */}
      {!post && !error && (
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
              <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-1 text-sm text-gray-500 dark:bg-white/10 dark:text-gray-400">
                <IconLock className="h-3.5 w-3.5" />비공개
              </span>
            )}
            {post.visibility === 'subscribers' && (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-1 text-sm text-[#0071e3] dark:bg-[#0a84ff]/15 dark:text-[#0a84ff]">
                구독자공개
              </span>
            )}
          </h1>
          <div className="mt-2 flex items-center gap-3">
            <time className="text-sm text-gray-500 dark:text-gray-400">
              {new Date(post.created_at).toLocaleString()} · {readingTime(post.content)}분 읽기
            </time>
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
                  className="rounded-full bg-black/[0.05] px-2.5 py-1 text-xs font-medium text-gray-600 transition hover:bg-[#0071e3]/10 hover:text-[#0071e3] dark:bg-white/10 dark:text-gray-300 dark:hover:text-[#0a84ff]"
                >
                  #{t}
                </Link>
              ))}
            </div>
          )}
          {/* 목차: 본문 앞. 소제목이 2개 미만이면 Toc이 알아서 안 그린다 */}
          <Toc content={post.content} />
          {/* 마크다운 본문: prose로 자동 타이포그래피, 다크모드는 prose-invert */}
          <div className="prose prose-gray mt-6 max-w-none prose-headings:tracking-tight prose-a:text-[#0071e3] prose-a:no-underline hover:prose-a:underline prose-img:rounded-xl dark:prose-invert dark:prose-a:text-[#0a84ff]">
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

      <section className="mt-6 rounded-2xl border border-black/[0.07] bg-white p-6 dark:border-white/10 dark:bg-white/[0.06]">
        <h2 className="mb-4 text-lg font-semibold tracking-tight">
          댓글 <span className="text-gray-400 dark:text-gray-500">({comments.length})</span>
        </h2>
        {comments.length === 0 && <p className="text-gray-400 dark:text-gray-500">아직 댓글이 없어. 첫 댓글을 남겨봐.</p>}
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
                  <span className="rounded-full bg-[#0071e3]/10 px-1.5 py-0.5 text-[10px] font-medium text-[#0071e3] dark:text-[#0a84ff]">
                    회원
                  </span>
                ) : (
                  <span className="text-[10px] text-gray-400 dark:text-gray-500">익명</span>
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
  )
}

export default PostDetailPage
