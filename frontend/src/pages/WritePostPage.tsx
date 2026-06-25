import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import type { Visibility } from '../types/post'
import { getPost, createPost, updatePost } from '../api/posts'
import { uploadImage } from '../api/uploads'
import { generateDraft } from '../api/ai'
import { useAuth } from '../auth/auth-context'
import { canWrite } from '../api/auth'
import { ui } from '../ui'
import { IconArrowLeft, IconSparkles, IconImage, IconLock } from '../components/icons'

const { input, btnPrimary, btnGhost } = ui

function WritePostPage() {
  const { id } = useParams<{ id: string }>()
  const editingId = id ? Number(id) : null // id 있으면 수정 모드
  const { user } = useAuth()
  const navigate = useNavigate()

  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [visibility, setVisibility] = useState<Visibility>('public')
  const [error, setError] = useState('')

  // AI 초안 생성용
  const [memo, setMemo] = useState('')
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState('')

  // 로그인 안 했으면 로그인 페이지로, 로그인했지만 승인 안 된 pending이면 블로그로
  useEffect(() => {
    if (!user) navigate('/login')
    else if (!canWrite(user)) navigate('/blog')
  }, [user, navigate])

  // 수정 모드면 기존 글 불러와 폼에 채움
  useEffect(() => {
    if (editingId === null) return
    getPost(editingId)
      .then((p) => {
        setTitle(p.title)
        setContent(p.content)
        setVisibility(p.visibility)
      })
      .catch((e) => setError((e as Error).message))
  }, [editingId])

  async function handleImagePick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const url = await uploadImage(file)
      setContent((prev) => `${prev}\n![](${url})\n`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      e.target.value = ''
    }
  }

  // 메모 → AI 초안. 결과의 첫 '# 제목' 줄은 제목 칸으로 빼고 나머지는 본문에
  async function handleGenerate() {
    if (!memo.trim()) return
    setAiError('')
    setAiLoading(true)
    try {
      const md = await generateDraft(memo)
      const lines = md.split('\n')
      const i = lines.findIndex((l) => l.startsWith('# '))
      if (i !== -1 && !title.trim()) {
        setTitle(lines[i].replace(/^#\s+/, '').trim())
        lines.splice(i, 1)
        setContent(lines.join('\n').trim())
      } else {
        setContent(md)
      }
    } catch (err) {
      setAiError((err as Error).message)
    } finally {
      setAiLoading(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim() || !content.trim()) return
    try {
      if (editingId === null) await createPost(title, content, visibility)
      else await updatePost(editingId, title, content, visibility)
      navigate('/blog') // 끝나면 홈으로
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div>
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-[#0071e3] hover:underline dark:text-[#0a84ff]">
        <IconArrowLeft className="h-4 w-4" />홈으로
      </Link>
      <div className="mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
      <h1 className={`mb-6 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>
        {editingId === null ? '새 글 쓰기' : '글 수정'}
      </h1>

      {/* AI 초안 잡기: 거친 메모 → 정돈된 글 구조를 제목·본문에 채움 */}
      <div className="mb-6 rounded-2xl border border-[#0071e3]/20 bg-[#0071e3]/[0.06] p-4 dark:border-[#0a84ff]/25 dark:bg-[#0a84ff]/[0.08]">
        <p className="flex items-center gap-1.5 text-sm font-medium text-[#0071e3] dark:text-[#0a84ff]">
          <IconSparkles className="h-4 w-4" />AI로 초안 잡기
        </p>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          떠오르는 메모를 대충 적고 누르면 제목·소제목·초안으로 정리해줘. (제목/본문을 덮어써)
        </p>
        <textarea
          placeholder="예: 오늘 AWS Summit 갔다왔는데 EKS 세션이 인상깊었음. 비용 얘기도 나왔고…"
          rows={3}
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
          className={`${input} mt-3`}
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={aiLoading || !memo.trim()}
            className={`${btnPrimary} disabled:opacity-50`}
          >
            {aiLoading ? '생성 중…' : <><IconSparkles className="h-4 w-4" />초안 생성</>}
          </button>
          {aiError && <span className="text-sm text-red-600">{aiError}</span>}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="grid gap-3">
        <input placeholder="제목" value={title} onChange={(e) => setTitle(e.target.value)} className={`${input} text-lg`} />
        <textarea
          placeholder="내용 (이미지 첨부하면 ![](url) 로 삽입돼)"
          rows={12}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className={input}
        />
        <label className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400">
          <IconImage className="h-4 w-4" />이미지 첨부:
          <input type="file" accept="image/*" onChange={handleImagePick} className="text-sm" />
        </label>
        <div className="flex gap-4 text-sm text-gray-700 dark:text-gray-300">
          <span>공개범위:</span>
          <label className="flex items-center gap-1">
            <input type="radio" checked={visibility === 'public'} onChange={() => setVisibility('public')} /> 전체공개
          </label>
          <label className="flex items-center gap-1">
            <input type="radio" checked={visibility === 'private'} onChange={() => setVisibility('private')} />
            <IconLock className="h-3.5 w-3.5" /> 일부공개(나만)
          </label>
        </div>
        <div className="flex gap-2">
          <button type="submit" className={btnPrimary}>{editingId === null ? '글 작성' : '수정 저장'}</button>
          <button type="button" onClick={() => navigate('/blog')} className={btnGhost}>취소</button>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>
      </div>
    </div>
  )
}

export default WritePostPage
