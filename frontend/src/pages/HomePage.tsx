import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Post } from '../types/post'
import { fetchPosts, deletePost } from '../api/posts'
import { subscribe } from '../api/subscribers'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'

function HomePage() {
  const { user } = useAuth()

  const [posts, setPosts] = useState<Post[]>([])
  const [error, setError] = useState('')
  const [email, setEmail] = useState('')
  const [subMsg, setSubMsg] = useState('')

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
      <section className="mb-10 text-center">
        <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 dark:text-white">기록하는 개발자</h1>
        <p className="mt-3 text-gray-600 dark:text-gray-300">인프라를 직접 만들며 배운 것을 남깁니다.</p>
        {/* 구독 */}
        <form onSubmit={handleSubscribe} className="mx-auto mt-6 flex max-w-md gap-2">
          <input type="email" placeholder="이메일로 새 글 구독하기" value={email} onChange={(e) => setEmail(e.target.value)} className={ui.input} />
          <button type="submit" className={`${ui.btnPrimary} shrink-0`}>구독</button>
        </form>
        {subMsg && <p className="mt-2 text-sm text-indigo-600">{subMsg}</p>}
      </section>

      {error && <p className="mb-4 text-sm text-red-600">에러: {error}</p>}

      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">최근 글</h2>
        <span className="text-sm text-gray-500 dark:text-gray-400">{posts.length}개</span>
      </div>

      {posts.length === 0 && (
        <p className="rounded-xl border border-dashed border-gray-300 p-10 text-center text-gray-500 dark:border-gray-700 dark:text-gray-400">
          아직 글이 없어. 첫 글을 써봐!
        </p>
      )}

      <div className="space-y-5">
        {posts.map((post) => (
          <article key={post.id} className={ui.card}>
            <h3 className="flex items-center gap-2 text-xl font-bold">
              <Link to={`/blog/posts/${post.id}`} className="text-gray-900 transition hover:text-indigo-600 dark:text-gray-100 dark:hover:text-indigo-400">{post.title}</Link>
              {post.visibility === 'private' && (
                <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600 dark:bg-red-900/30 dark:text-red-400">🔒 비공개</span>
              )}
            </h3>
            <Link to={`/blog/posts/${post.id}`} className="mt-2 block text-gray-600 transition hover:text-gray-800 dark:text-gray-300 dark:hover:text-gray-100">
              <p className="line-clamp-2 whitespace-pre-wrap leading-relaxed">
                {post.content.length > 120 ? post.content.slice(0, 120) + '…' : post.content}
              </p>
            </Link>
            <div className="mt-4 flex items-center justify-between border-t border-gray-100 pt-3 dark:border-gray-700">
              <time className="text-xs text-gray-500 dark:text-gray-400">{new Date(post.created_at).toLocaleDateString()}</time>
              {user && post.owner_id === user.id && (
                <div className="flex gap-3 text-sm">
                  <Link to={`/blog/posts/${post.id}/edit`} className="text-indigo-600 hover:underline">수정</Link>
                  <button type="button" onClick={() => handleDelete(post.id)} className="text-red-600 hover:underline">삭제</button>
                </div>
              )}
            </div>
          </article>
        ))}
      </div>
    </>
  )
}

export default HomePage
