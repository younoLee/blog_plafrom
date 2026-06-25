import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import type { Post } from '../types/post'
import type { Comment } from '../types/comment'
import { getPost } from '../api/posts'
import { fetchComments, addComment } from '../api/comments'
import { fetchMySubscriptions, subscribeAuthor, unsubscribeAuthor } from '../api/subscriptions'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'
import { IconArrowLeft, IconLock, IconCheck } from '../components/icons'
import { Reveal } from '../components/Reveal'

const { input, btnPrimary, btnGhost } = ui

function PostDetailPage() {
  const { id } = useParams<{ id: string }>()
  const postId = Number(id)
  const { user } = useAuth()
  const [post, setPost] = useState<Post | null>(null)
  const [error, setError] = useState('')
  const [subscribed, setSubscribed] = useState(false)

  const [comments, setComments] = useState<Comment[]>([])
  const [author, setAuthor] = useState('')
  const [text, setText] = useState('')

  useEffect(() => {
    getPost(postId)
      .then(setPost)
      .catch((e) => setError((e as Error).message))
    fetchComments(postId)
      .then(setComments)
      .catch((e) => setError((e as Error).message))
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
    if (!author.trim() || !text.trim()) return
    try {
      await addComment(postId, author, text)
      setText('')
      setComments(await fetchComments(postId))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <>
      <Link to="/blog" className="inline-flex items-center gap-1 text-sm text-[#0071e3] hover:underline dark:text-[#0a84ff]">
        <IconArrowLeft className="h-4 w-4" />목록으로
      </Link>

      {error && <p className="mt-4 text-sm text-red-600">에러: {error}</p>}

      {post && (
        <Reveal>
        <article className="mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
          <h1 className="flex items-center gap-2 text-3xl font-semibold tracking-tight">
            {post.title}
            {post.visibility === 'private' && (
              <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-1 text-sm text-gray-500 dark:bg-white/10 dark:text-gray-400">
                <IconLock className="h-3.5 w-3.5" />비공개
              </span>
            )}
          </h1>
          <div className="mt-2 flex items-center gap-3">
            <time className="text-sm text-gray-500 dark:text-gray-400">
              {new Date(post.created_at).toLocaleString()}
            </time>
            {/* 로그인 + 남의 글이면 글쓴이 구독 버튼 (구독하면 그 사람 비공개글도 볼 수 있음) */}
            {user && post.owner_id && post.owner_id !== user.id && (
              <button type="button" onClick={toggleSubscribe} className={subscribed ? btnGhost : btnPrimary}>
                {subscribed ? <><IconCheck className="h-4 w-4" />구독중</> : '+ 글쓴이 구독'}
              </button>
            )}
          </div>
          {/* 마크다운 본문: prose로 자동 타이포그래피, 다크모드는 prose-invert */}
          <div className="prose prose-gray mt-6 max-w-none prose-headings:tracking-tight prose-a:text-[#0071e3] prose-a:no-underline hover:prose-a:underline prose-img:rounded-xl dark:prose-invert dark:prose-a:text-[#0a84ff]">
            <ReactMarkdown
              components={{
                img: (props) => <img {...props} className="rounded-lg" />,
              }}
            >
              {post.content}
            </ReactMarkdown>
          </div>
        </article>
        </Reveal>
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
                <time className="text-xs text-gray-500 dark:text-gray-400">{new Date(c.created_at).toLocaleString()}</time>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-gray-700 dark:text-gray-300">{c.content}</p>
            </div>
          ))}
        </div>

        <form onSubmit={handleAddComment} className="mt-5 grid gap-2">
          <input placeholder="이름" value={author} onChange={(e) => setAuthor(e.target.value)} className={`${input} max-w-xs`} />
          <textarea placeholder="댓글 내용" rows={3} value={text} onChange={(e) => setText(e.target.value)} className={input} />
          <button type="submit" className={`${btnPrimary} justify-self-start`}>댓글 작성</button>
        </form>
      </section>
    </>
  )
}

export default PostDetailPage
