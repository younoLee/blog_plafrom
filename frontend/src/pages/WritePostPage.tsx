import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
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

// 서식 툴바 버튼 공통 스타일
const toolBtn =
  'rounded-lg px-2.5 py-1 text-xs text-gray-700 transition hover:bg-black/[0.06] dark:text-gray-200 dark:hover:bg-white/10'

const { input, btnPrimary, btnGhost } = ui

function WritePostPage() {
  const { id } = useParams<{ id: string }>()
  const editingId = id ? Number(id) : null // id 있으면 수정 모드
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const contentRef = useRef<HTMLTextAreaElement>(null) // 툴바 서식 삽입용
  const [preview, setPreview] = useState(false) // 미리보기 토글
  const [visibility, setVisibility] = useState<Visibility>('public')
  const [coverImage, setCoverImage] = useState('') // 커버(대표) 이미지 URL, 선택
  const [tags, setTags] = useState<string[]>([]) // 태그 목록
  const [series, setSeries] = useState('') // 연재 이름(선택). 같은 이름끼리 한 시리즈
  const [tagInput, setTagInput] = useState('') // 태그 입력 중인 값
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
        setCoverImage(p.cover_image ?? '')
        setTags(p.tags ?? [])
        setSeries(p.series ?? '')
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

  // 커버 이미지: 업로드해서 URL만 보관 (본문엔 안 넣음). 홈 카드 썸네일 + 글 상단에 크게 표시됨
  async function handleCoverPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      setCoverImage(await uploadImage(file))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      e.target.value = ''
    }
  }

  // --- 서식 툴바: 마크다운을 본문 커서 위치에 삽입 (무거운 에디터 없이 '꾸미기') ---
  // 선택 텍스트를 마커로 감쌈 (굵게/기울임/코드/링크)
  function wrap(before: string, after = before, ph = '') {
    const ta = contentRef.current
    if (!ta) return
    const s = ta.selectionStart
    const en = ta.selectionEnd
    const sel = content.slice(s, en) || ph
    setContent(content.slice(0, s) + before + sel + after + content.slice(en))
    requestAnimationFrame(() => {
      ta.focus()
      ta.selectionStart = s + before.length
      ta.selectionEnd = s + before.length + sel.length
    })
  }
  // 현재 줄 맨 앞에 접두어 (제목/목록/인용)
  function linePrefix(prefix: string) {
    const ta = contentRef.current
    if (!ta) return
    const s = ta.selectionStart
    const lineStart = content.lastIndexOf('\n', s - 1) + 1
    setContent(content.slice(0, lineStart) + prefix + content.slice(lineStart))
    requestAnimationFrame(() => {
      ta.focus()
      ta.selectionStart = ta.selectionEnd = s + prefix.length
    })
  }
  // 커서에 그대로 삽입 (구분선 등)
  function insertAt(text: string) {
    const ta = contentRef.current
    if (!ta) return
    const s = ta.selectionStart
    setContent(content.slice(0, s) + text + content.slice(s))
    requestAnimationFrame(() => {
      ta.focus()
      ta.selectionStart = ta.selectionEnd = s + text.length
    })
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

  // 태그 추가(Enter/쉼표) — 공백정리·중복·개수(10) 제한은 서버도 하지만 UI에서도
  function addTag(raw: string) {
    const t = raw.trim().replace(/,+$/, '').trim()
    if (t && !tags.includes(t) && tags.length < 10) setTags([...tags, t])
    setTagInput('')
  }
  function removeTag(t: string) {
    setTags(tags.filter((x) => x !== t))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim() || !content.trim()) return
    try {
      const cover = coverImage.trim() || null
      // 입력 중이던 태그도 마지막에 반영
      const finalTags = tagInput.trim() && !tags.includes(tagInput.trim()) ? [...tags, tagInput.trim()].slice(0, 10) : tags
      // 빈칸이면 연재 없음(null) — 서버도 ''를 None으로 정규화하지만 여기서도 맞춰 보낸다
      const finalSeries = series.trim() || null
      if (editingId === null) await createPost(title, content, cover, finalTags, finalSeries, visibility)
      else await updatePost(editingId, title, content, cover, finalTags, finalSeries, visibility)
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
        {/* 커버(대표) 이미지: 홈 목록 카드 썸네일 + 글 상단에 크게 노출 */}
        <div className="grid gap-2">
          <label className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400">
            <IconImage className="h-4 w-4" />커버 이미지 (선택):
            <input type="file" accept="image/*" onChange={handleCoverPick} className="text-sm" />
          </label>
          {coverImage && (
            <div className="relative overflow-hidden rounded-xl">
              <img src={coverImage} alt="커버 미리보기" className="aspect-[2/1] w-full object-cover" />
              <button
                type="button"
                onClick={() => setCoverImage('')}
                className="absolute right-2 top-2 rounded-full bg-black/60 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-black/75"
              >
                제거
              </button>
            </div>
          )}
        </div>
        {/* 연재: 같은 이름을 쓴 글끼리 한 시리즈가 되고, 순서는 작성일 */}
        <div className="grid gap-2">
          <label htmlFor="series-input" className="text-sm text-gray-500 dark:text-gray-400">
            연재 (선택) — 같은 이름을 쓴 글끼리 묶여 이전/다음 편이 생겨:
          </label>
          <input
            id="series-input"
            value={series}
            onChange={(e) => setSeries(e.target.value)}
            maxLength={100}
            placeholder="예: 블로그 만들기"
            className={ui.input}
          />
        </div>

        {/* 태그: 칩으로 추가/삭제 (Enter 또는 쉼표로 추가) */}
        <div className="grid gap-2">
          <label className="text-sm text-gray-500 dark:text-gray-400">태그 (선택, 최대 10개 · Enter로 추가):</label>
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {tags.map((t) => (
                <span key={t} className="inline-flex items-center gap-1 rounded-full bg-[#0071e3]/10 px-2.5 py-1 text-xs font-medium text-[#0071e3] dark:bg-[#0a84ff]/15 dark:text-[#0a84ff]">
                  #{t}
                  <button type="button" onClick={() => removeTag(t)} className="leading-none text-[#0071e3]/60 hover:text-[#0071e3] dark:text-[#0a84ff]/70" aria-label={`${t} 삭제`}>×</button>
                </span>
              ))}
            </div>
          )}
          <input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault()
                addTag(tagInput)
              }
            }}
            placeholder="예: AWS, Terraform, DevOps"
            className={`${input} max-w-sm`}
          />
        </div>
        {/* 서식 툴바: 선택/커서에 마크다운 삽입 + 미리보기 토글 */}
        <div className="flex flex-wrap items-center gap-1 rounded-xl border border-black/10 bg-black/[0.02] p-1.5 dark:border-white/15 dark:bg-white/5">
          {/* 서식 버튼은 '편집 모드'에서만 노출 — 미리보기 땐 편집칸이 없어 버튼이 안 먹으므로 숨겨서 혼동 방지 */}
          {!preview ? (
            <>
              <button type="button" title="굵게" onClick={() => wrap('**', '**', '굵은 글씨')} className={`${toolBtn} font-bold`}>굵게</button>
              <button type="button" title="기울임" onClick={() => wrap('*', '*', '기울임')} className={`${toolBtn} italic`}>기울임</button>
              <span className="mx-1 h-4 w-px bg-black/10 dark:bg-white/15" />
              <button type="button" title="제목(H2)" onClick={() => linePrefix('## ')} className={toolBtn}>제목</button>
              <button type="button" title="불릿 목록" onClick={() => linePrefix('- ')} className={toolBtn}>목록</button>
              <button type="button" title="인용문" onClick={() => linePrefix('> ')} className={toolBtn}>인용</button>
              <button type="button" title="인라인 코드" onClick={() => wrap('`', '`', '코드')} className={`${toolBtn} font-mono`}>코드</button>
              <button type="button" title="링크" onClick={() => wrap('[', '](https://)', '링크텍스트')} className={toolBtn}>링크</button>
              <button type="button" title="가로 구분선" onClick={() => insertAt('\n\n---\n\n')} className={toolBtn}>구분선</button>
            </>
          ) : (
            <span className="px-1 text-xs text-gray-500 dark:text-gray-400">미리보기 중 — 꾸미려면 ‘편집으로’ 눌러</span>
          )}
          <button
            type="button"
            onClick={() => setPreview((v) => !v)}
            className={`ml-auto rounded-lg px-2.5 py-1 text-xs font-medium transition ${preview ? 'bg-[#0071e3] text-white dark:bg-[#0a84ff]' : 'text-gray-600 hover:bg-black/[0.06] dark:text-gray-300 dark:hover:bg-white/10'}`}
          >
            {preview ? '편집으로' : '미리보기'}
          </button>
        </div>
        {preview ? (
          // 미리보기: 실제 글 화면과 같은 방식(ReactMarkdown)으로 '꾸며진' 결과를 보여줌
          <div className="prose prose-gray min-h-[18rem] max-w-none rounded-xl border border-black/10 bg-white p-5 prose-headings:tracking-tight prose-a:text-[#0071e3] prose-img:rounded-xl dark:prose-invert dark:border-white/15 dark:bg-white/[0.03] dark:prose-a:text-[#0a84ff]">
            {content.trim() ? (
              <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{content}</ReactMarkdown>
            ) : (
              <p className="text-gray-400 dark:text-gray-500">미리볼 내용이 없어. 먼저 내용을 써봐.</p>
            )}
          </div>
        ) : (
          <textarea
            ref={contentRef}
            placeholder="내용 — 위 버튼으로 꾸미거나 마크다운 직접 입력 (이미지 첨부하면 ![](url) 삽입)"
            rows={14}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className={`${input} font-mono`}
          />
        )}
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
