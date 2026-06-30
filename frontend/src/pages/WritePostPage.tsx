import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import type { Visibility } from '../types/post'
import { getPost, createPost, updatePost } from '../api/posts'
import { uploadImage } from '../api/uploads'
import { generateDraft, fetchAiModels, fetchKeys, fetchUsage, type AiModel, type AiUsage } from '../api/ai'

// BYOK provider → 직접입력 옵션에 보일 이름
const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI',
  gemini: 'Gemini',
  compatible: 'OpenAI 호환',
  anthropic: 'Anthropic(내 키)',
  cohere: 'Cohere',
}

// 드롭다운 optgroup(카탈로그 모델) 묶음 라벨
const GROUP_LABEL: Record<string, string> = { claude: 'Claude', openai: 'OpenAI', gemini: 'Gemini' }
import { useAuth } from '../auth/auth-context'
import { canWrite } from '../api/auth'
import { ui } from '../ui'
import { IconArrowLeft, IconSparkles, IconImage, IconLock, IconChevronDown, IconSpinner, IconCheck } from '../components/icons'

const MEMO_MAX = 5000

const { input, btnPrimary, btnGhost } = ui

function WritePostPage() {
  const { id } = useParams<{ id: string }>()
  const editingId = id ? Number(id) : null // id 있으면 수정 모드
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [visibility, setVisibility] = useState<Visibility>('public')
  const [error, setError] = useState('')

  // AI 초안 생성용
  const [memo, setMemo] = useState('')
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState('')
  const [aiDone, setAiDone] = useState('') // 생성 완료 확인줄
  // 고를 수 있는 AI 모델(티어에 따라 다름) + 현재 선택
  const [models, setModels] = useState<AiModel[]>([])
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('') // 직접 입력 모드의 모델 ID
  const [byokProviders, setByokProviders] = useState<string[]>([]) // 내가 키 등록한 provider
  const [usage, setUsage] = useState<AiUsage | null>(null) // 서버 모델(Claude) 남은 횟수

  // 로그인 안 했으면 로그인 페이지로, 로그인했지만 승인 안 된 pending이면 블로그로
  // (새로고침 시 인증 복구가 끝날 때까지 기다림 — loading 중엔 판단 보류, 안 그러면 로그인창으로 튕김)
  useEffect(() => {
    if (loading) return
    if (!user) navigate('/login')
    else if (!canWrite(user)) navigate('/blog')
  }, [user, loading, navigate])

  // 쓸 수 있는 AI 모델 목록 가져오기 (티어 게이팅 — 일반=소넷, 결제=+Opus, 관리자=전부)
  useEffect(() => {
    if (loading || !canWrite(user)) return
    fetchAiModels()
      .then(({ models, default: def }) => {
        setModels(models)
        setModel(def)
      })
      .catch(() => {})
    // 직접입력 가능한 provider(=키 등록된 것) 목록
    fetchKeys()
      .then((ks) => setByokProviders(ks.filter((k) => k.has_key).map((k) => k.provider)))
      .catch(() => {})
    // 서버 모델 남은 횟수
    fetchUsage()
      .then(setUsage)
      .catch(() => {})
  }, [user, loading])

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
    // 직접 입력 모드(custom:openai / custom:gemini)면 provider+커스텀 모델ID로 호출
    let useModel = model
    let useProvider: string | undefined
    if (model.startsWith('custom:')) {
      useProvider = model.slice('custom:'.length)
      useModel = customModel.trim()
      if (!useModel) {
        setAiError('모델 ID를 입력해줘 (예: gpt-4o, o3, gemini-2.5-pro)')
        return
      }
    }
    setAiError('')
    setAiDone('')
    setAiLoading(true)
    try {
      const md = await generateDraft(memo, useModel || undefined, useProvider)
      const lines = md.split('\n')
      const i = lines.findIndex((l) => l.startsWith('# '))
      if (i !== -1 && !title.trim()) {
        setTitle(lines[i].replace(/^#\s+/, '').trim())
        lines.splice(i, 1)
        setContent(lines.join('\n').trim())
      } else {
        setContent(md)
      }
      const label = model.startsWith('custom:') ? useModel : models.find((m) => m.id === model)?.label ?? useModel
      setAiDone(`'${label}'로 초안을 채웠어`)
      // 서버 모델(Claude)을 썼으면 남은 횟수 갱신 (BYOK는 캡 없음)
      fetchUsage().then(setUsage).catch(() => {})
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
      <div className="mb-6 rounded-2xl border border-[#0071e3]/15 bg-[#0071e3]/[0.05] p-5 dark:border-[#0a84ff]/20 dark:bg-[#0a84ff]/[0.07]">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-[#0071e3]/10 text-[#0071e3] dark:bg-[#0a84ff]/15 dark:text-[#0a84ff]">
            <IconSparkles className="h-4 w-4" />
          </span>
          <p className="text-sm font-medium text-[#0071e3] dark:text-[#0a84ff]">AI로 초안 잡기</p>
        </div>
        <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
          떠오르는 메모를 대충 적고 누르면 제목·소제목·초안으로 정리해줘. (제목/본문을 덮어써)
        </p>
        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
          생성에 길면 1분쯤 걸려. 디스코드·인스타 같은 앱 안 브라우저에선 멈출 수 있으니 크롬 등 일반 브라우저에서 써줘.
        </p>
        {/* 서버 모델(Claude) 남은 횟수. BYOK(내 키)는 한도 없음 */}
        {usage && (
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
            서버 모델 남은 횟수 · 오늘{' '}
            <span className={usage.daily_used >= usage.daily_cap ? 'font-medium text-red-500' : ''}>
              {Math.max(0, usage.daily_cap - usage.daily_used)}/{usage.daily_cap}
            </span>{' · '}이번 달{' '}
            <span className={usage.monthly_used >= usage.monthly_cap ? 'font-medium text-red-500' : ''}>
              {Math.max(0, usage.monthly_cap - usage.monthly_used)}/{usage.monthly_cap}
            </span>
          </p>
        )}
        <textarea
          placeholder="예: 오늘 AWS Summit 갔다왔는데 EKS 세션이 인상깊었음. 비용 얘기도 나왔고…"
          rows={3}
          maxLength={MEMO_MAX}
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
          className={`${input} mt-3`}
        />
        {memo.length > 0 && (
          <p className="mt-1 text-right text-xs text-gray-400 dark:text-gray-500">{memo.length}/{MEMO_MAX}</p>
        )}
        {/* 모델 선택 (애플풍 드롭다운, provider별 그룹) + 직접입력 칸 */}
        {models.length > 0 && (
          <div className="mt-4 grid gap-2 sm:max-w-sm">
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400">모델</label>
            <div className="relative">
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className={ui.select}
                aria-label="AI 모델 선택"
              >
                {/* 카탈로그 모델을 provider별 그룹으로 */}
                {(['claude', 'openai', 'gemini'] as const).map((prov) => {
                  const group = models.filter((m) => m.provider === prov)
                  if (group.length === 0) return null
                  return (
                    <optgroup key={prov} label={GROUP_LABEL[prov]}>
                      {group.map((m) => (
                        <option key={m.id} value={m.id}>{m.label}</option>
                      ))}
                    </optgroup>
                  )
                })}
                {/* 내가 키를 등록한 BYOK provider — '직접 입력' 그룹 */}
                {byokProviders.length > 0 && (
                  <optgroup label="직접 입력 (내 키)">
                    {byokProviders.map((prov) => (
                      <option key={`custom:${prov}`} value={`custom:${prov}`}>
                        {PROVIDER_LABEL[prov] ?? prov} — 모델 직접 입력
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
              <IconChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            </div>
            {/* 직접 입력 모드면 모델 ID 입력 칸 */}
            {model.startsWith('custom:') && (
              <input
                placeholder="모델 ID (예: gpt-4o, gemini-2.5-pro, command-r-plus)"
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                className={input}
                aria-label="커스텀 모델 ID"
              />
            )}
            {/* Opus가 목록에 없으면(=비유료) 결제 안내 */}
            {!models.some((m) => m.id === 'claude-opus-4-8') && (
              <p className="text-xs text-gray-400 dark:text-gray-500">Opus(고품질)는 결제 후 쓸 수 있어.</p>
            )}
          </div>
        )}

        {/* 생성 버튼 + 에러 */}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={aiLoading || !memo.trim()}
            className={`${btnPrimary} disabled:opacity-50`}
          >
            {/* 구조 고정: [아이콘][텍스트span]를 항상 유지하고 내용만 바꿈.
                fragment로 [아이콘+맨텍스트]를 통째 토글하면, 인앱 브라우저/번역기가
                맨 텍스트 노드를 감쌌을 때 React 재조정이 insertBefore 에러로 깨진다. */}
            {aiLoading ? <IconSpinner className="h-4 w-4 animate-spin" /> : <IconSparkles className="h-4 w-4" />}
            <span>{aiLoading ? '생성 중…' : '초안 생성'}</span>
          </button>
          {/* 상태 메시지: 항상 렌더되는 고정 컨테이너 → 형제 노드가 생겼다 사라지며
              DOM 트리가 깨지는 것 방지. 안의 내용만 바뀐다. */}
          <span className="text-sm" aria-live="polite">
            {aiError ? (
              <span className="text-red-600">{aiError}</span>
            ) : aiDone ? (
              <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                <IconCheck className="h-4 w-4" />
                <span>{aiDone}</span>
              </span>
            ) : null}
          </span>
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
        <div className="flex flex-wrap gap-4 text-sm text-gray-700 dark:text-gray-300">
          <span>공개범위:</span>
          <label className="flex items-center gap-1">
            <input type="radio" checked={visibility === 'public'} onChange={() => setVisibility('public')} /> 전체공개
          </label>
          <label className="flex items-center gap-1">
            <input type="radio" checked={visibility === 'subscribers'} onChange={() => setVisibility('subscribers')} /> 구독자공개
          </label>
          <label className="flex items-center gap-1">
            <input type="radio" checked={visibility === 'private'} onChange={() => setVisibility('private')} />
            <IconLock className="h-3.5 w-3.5" /> 비공개(나만)
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
