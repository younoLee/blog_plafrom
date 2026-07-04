import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Post } from '../types/post'
import { fetchPosts, deletePost } from '../api/posts'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'
import { IconLock } from '../components/icons'
import { Reveal } from '../components/Reveal'
import { Sidebar } from '../components/Sidebar'
import { excerpt, readingTime } from '../postUtils'

function HomePage() {
  const { user } = useAuth()

  const [posts, setPosts] = useState<Post[]>([])
  const [error, setError] = useState('')

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
        {/* 새 글 이메일 구독·계정 구독은 전용 페이지에서 */}
        <p className="mx-auto mt-7 max-w-md text-sm text-gray-500 dark:text-gray-400">
          새 글 이메일 구독·계정 구독은{' '}
          <Link to="/subscriptions" className="text-[#0071e3] hover:underline dark:text-[#0a84ff]">
            구독 관리
          </Link>
          에서 할 수 있어.
        </p>
      </section>

      {error && <p className="mb-4 text-sm text-red-600">에러: {error}</p>}

      {/* 본문 + 우측 사이드바 2단. md(768px)+ = 옆으로(PC/태블릿), 그 아래(폰) = 세로 스택 */}
      <div className="grid gap-8 md:grid-cols-[1fr_18rem]">
      <div>
      <div className="mb-5 flex items-baseline justify-between">
        <h2 className="text-2xl font-semibold tracking-tight">최근 글</h2>
        <span className="text-sm text-gray-400 dark:text-gray-500">{posts.length}개</span>
      </div>

      {posts.length === 0 && (
        <p className="rounded-2xl border border-dashed border-black/10 p-12 text-center text-gray-400 dark:border-white/15 dark:text-gray-500">
          아직 글이 없어. 첫 글을 써봐!
        </p>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
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
                {excerpt(post.content)}
              </p>
            </Link>
            <div className="mt-4 flex items-center justify-between border-t border-black/[0.06] pt-3 dark:border-white/10">
              <time className="text-xs text-gray-400 dark:text-gray-500">
                {new Date(post.created_at).toLocaleDateString()} · {readingTime(post.content)}분 읽기
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
      </div>
      <Sidebar posts={posts} />
      </div>
    </>
  )
}

export default HomePage
