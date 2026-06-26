import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Post } from '../types/post'
import { fetchPosts, deletePost } from '../api/posts'
import { subscribe } from '../api/subscribers'
import { fetchBlogOwner, fetchMySubscriptions, subscribeAuthor, unsubscribeAuthor } from '../api/subscriptions'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'
import { IconLock } from '../components/icons'
import { Reveal } from '../components/Reveal'

function HomePage() {
  const { user } = useAuth()

  const [posts, setPosts] = useState<Post[]>([])
  const [error, setError] = useState('')
  const [email, setEmail] = useState('')
  const [subMsg, setSubMsg] = useState('')
  // '이 블로그 구독'(주인장 구독) — 구독하면 주인장의 일부공개 글이 보임
  const [ownerId, setOwnerId] = useState<number | null>(null)
  const [subToOwner, setSubToOwner] = useState(false)

  async function loadPosts() {
    try {
      setPosts(await fetchPosts())
    } catch (e) {
      setError((e as Error).message)
    }
  }

  useEffect(() => {
    fetchPosts()
      .then(setPosts)
      .catch((e) => setError((e as Error).message))
  }, [user])

  // 블로그 주인(admin) id
  useEffect(() => {
    fetchBlogOwner()
      .then((o) => setOwnerId(o.id))
      .catch(() => {})
  }, [])

  // 내가 주인을 구독 중인지 (비로그인은 자동 [] → false)
  useEffect(() => {
    if (ownerId == null) return
    fetchMySubscriptions()
      .then((ids) => setSubToOwner(ids.includes(ownerId)))
      .catch(() => setSubToOwner(false))
  }, [user, ownerId])

  async function toggleBlogSub() {
    if (ownerId == null) return
    try {
      if (subToOwner) await unsubscribeAuthor(ownerId)
      else await subscribeAuthor(ownerId)
      setSubToOwner(!subToOwner)
      await loadPosts() // 일부공개 글 반영
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function handleDelete(id: number) {
    try {
      await deletePost(id)
      await loadPosts()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function handleSubscribe(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    try {
      await subscribe(email)
      setEmail('')
      setSubMsg('구독 완료! 새 글 알림을 받게 돼.')
    } catch (e) {
      setSubMsg((e as Error).message)
    }
  }

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
        {/* 구독 */}
        <form onSubmit={handleSubscribe} className="mx-auto mt-7 flex max-w-md gap-2">
          <input type="email" placeholder="이메일로 새 글 구독하기" value={email} onChange={(e) => setEmail(e.target.value)} className={ui.input} />
          <button type="submit" className={`${ui.btnPrimary} shrink-0`}>구독</button>
        </form>
        {subMsg && <p className="mt-2 text-sm text-[#0071e3] dark:text-[#0a84ff]">{subMsg}</p>}
        {/* 이 블로그 구독: 로그인 + 본인(주인장)이 아닐 때. 구독하면 일부공개 글이 열림 */}
        {user && ownerId != null && user.id !== ownerId && (
          <div className="mt-4">
            <button type="button" onClick={toggleBlogSub} className={subToOwner ? ui.btnGhost : ui.btnPrimary}>
              {subToOwner ? '✓ 이 블로그 구독중' : '+ 이 블로그 구독'}
            </button>
            <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">구독하면 일부공개 글도 볼 수 있어</p>
          </div>
        )}
      </section>

      {error && <p className="mb-4 text-sm text-red-600">에러: {error}</p>}

      <div className="mb-5 flex items-baseline justify-between">
        <h2 className="text-2xl font-semibold tracking-tight">최근 글</h2>
        <span className="text-sm text-gray-400 dark:text-gray-500">{posts.length}개</span>
      </div>

      {posts.length === 0 && (
        <p className="rounded-2xl border border-dashed border-black/10 p-12 text-center text-gray-400 dark:border-white/15 dark:text-gray-500">
          아직 글이 없어. 첫 글을 써봐!
        </p>
      )}

      <div className="space-y-4">
        {posts.map((post, i) => (
          <Reveal key={post.id} delay={Math.min(i * 60, 300)}>
          <article className={`${ui.card} hover:-translate-y-0.5 hover:border-[#0071e3]/30 dark:hover:border-[#0a84ff]/30`}>
            <h3 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <Link to={`/blog/posts/${post.id}`} className="transition hover:text-[#0071e3] dark:hover:text-[#0a84ff]">{post.title}</Link>
              {post.visibility === 'private' && (
                <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500 dark:bg-white/10 dark:text-gray-400">
                  <IconLock className="h-3 w-3" />비공개
                </span>
              )}
            </h3>
            <Link to={`/blog/posts/${post.id}`} className="mt-2 block text-gray-500 transition hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
              <p className="line-clamp-2 whitespace-pre-wrap leading-relaxed">
                {post.content.length > 120 ? post.content.slice(0, 120) + '…' : post.content}
              </p>
            </Link>
            <div className="mt-4 flex items-center justify-between border-t border-black/[0.06] pt-3 dark:border-white/10">
              <time className="text-xs text-gray-400 dark:text-gray-500">{new Date(post.created_at).toLocaleDateString()}</time>
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
    </>
  )
}

export default HomePage
