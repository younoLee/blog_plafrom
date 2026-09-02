import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
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

// ── 초안 임시보관 ────────────────────────────────────────────────────────────
// **왜 (2026-08-27)** — title·content가 useState에만 살아서, 세션이 풀리는 순간
// (NotificationBell이 30초마다 폴링하다 401을 받으면 그렇게 된다) 아래 인증 effect가
// 사용자가 아무것도 안 눌렀는데 navigate했다. 30분 쓴 글이 흔적 없이 사라진다.
//
// 서버에 초안 테이블을 두는 게 제대로 된 해법이지만 스키마·API·목록 UI가 따라온다.
// 여기서는 브라우저에만 남긴다. **이건 백업이지 저장이 아니다** — 다른 기기에서는
// 안 보이고, 방문자가 저장소를 비우면 같이 사라진다. 그래서 복구는 자동이 아니라
// 제안이다(아래 복구 배너). 자동으로 덮으면 수정 모드에서 서버 본문을 낡은 초안이
// 조용히 밀어낼 수 있다.
type Draft = {
  title: string
  content: string
  coverImage: string
  tags: string[]
  series: string
  visibility: Visibility
  savedAt: number
}

/** 새 글과 수정은 다른 칸을 쓴다. 한 칸을 나눠 쓰면 새 글을 쓰다 만 뒤 남의 글을
 *  수정하러 들어갔을 때 복구 제안이 엉뚱한 글을 들이민다. */
function draftKey(editingId: number | null): string {
  return editingId === null ? 'draft:new' : `draft:post:${editingId}`
}

/** 저장할 만큼 달라졌는지 비교하는 지문. 자동저장과 beforeunload가 **같은 함수**를
 *  써야 한다 — 두 곳에서 필드 순서가 어긋나면 지문이 항상 달라 매번 쓴다. */
function snapshotOf(d: Omit<Draft, 'savedAt'>): string {
  return JSON.stringify([d.title, d.content, d.coverImage, d.tags, d.series, d.visibility])
}

// localStorage는 시크릿 창·저장 차단 설정에서 **접근 자체가 throw한다.** 초안 백업이
// 화면을 못 뜨게 만들면 안 하느니만 못하므로 세 함수 모두 실패를 삼킨다.
function readDraft(key: string): Draft | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const d = JSON.parse(raw) as Draft
    // 모양 검사. 예전 형식이나 손으로 건드린 값이 들어오면 복구 배너가 깨진다.
    if (typeof d?.title !== 'string' || typeof d?.content !== 'string') return null
    if (!Array.isArray(d?.tags) || typeof d?.savedAt !== 'number') return null
    return d
  } catch {
    return null
  }
}

function writeDraft(key: string, d: Draft) {
  try {
    localStorage.setItem(key, JSON.stringify(d))
  } catch {
    /* 용량 초과 또는 저장 차단. 초안은 편의지 계약이 아니라 조용히 포기한다. */
  }
}

function clearDraft(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    /* 위와 같다 */
  }
}

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
  // 저장 진행 중 — 중복 제출을 막는다(같은 글이 여러 개 생기던 자리)
  const [saving, setSaving] = useState(false)
  // 이미지 업로드 진행 중. 세 입구(버튼·붙여넣기·드롭)가 같은 표시를 쓴다.
  // 붙여넣기·드롭에는 누른 버튼이 없어서, 표시가 없으면 아무 일도 안 일어난 것처럼 보인다.
  const [uploading, setUploading] = useState(false)

  // 초안 임시보관. key는 새 글/수정에 따라 다르다(draftKey 주석).
  const key = draftKey(editingId)
  // **진입 시점에 한 번만** 읽는다. 아래 자동저장이 곧 이 칸을 덮으므로 그 전에 잡아야 한다.
  const [recovered, setRecovered] = useState<Draft | null>(() => readDraft(draftKey(id ? Number(id) : null)))
  const [draftAt, setDraftAt] = useState<number | null>(null) // 마지막 임시보관 시각
  // 수정 모드에서 서버가 준 원본의 지문. 아직 아무것도 안 고쳤으면 임시보관하지 않는다
  // (안 그러면 글을 열었다 그냥 나가도 다음 방문에 쓸모없는 복구 배너가 뜬다).
  const serverSnapshot = useRef<string | null>(null)
  // 저장·취소로 초안을 버린 뒤, **아직 안 터진 자동보관 타이머가 그걸 되살리면 안 된다.**
  // 마지막 타이핑 1초 안에 저장을 누르면 실제로 그 순서가 된다(clearDraft → 타이머 발화).
  // 그러면 저장이 끝났는데 다음 방문에 "쓰다 만 글이 있어" 배너가 뜬다.
  // 두 자리 모두 곧바로 navigate하므로 다시 false로 돌릴 일은 없다.
  const discarded = useRef(false)

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

  // 쓰던 내용이 있는가. 자동보관·이탈 확인·아래 인증 effect가 모두 이걸 기준으로 판단한다.
  const dirty = title.trim() !== '' || content.trim() !== ''

  // 로그인 안 했으면 로그인 페이지로, 로그인했지만 승인 안 된 pending이면 블로그로
  // (새로고침 시 인증 복구가 끝날 때까지 기다림 — loading 중엔 판단 보류, 안 그러면 로그인창으로 튕김)
  //
  // **2026-08-27: 쓰던 글이 있으면 안 떠난다.** 세션 만료는 NotificationBell의 30초
  // 폴링이 401을 받는 순간 아무 예고 없이 온다. 그때 navigate하면 사용자가 아무것도
  // 안 눌렀는데 편집 중이던 글이 사라진다. 초안은 이미 브라우저에 있으므로(위 helpers)
  // 여기서는 떠나는 대신 알린다. 권한이 사라진 경우도 같다.
  useEffect(() => {
    if (loading) return
    if (user && canWrite(user)) return
    if (dirty) return // 쓰던 글이 있으면 안 떠난다. 안내는 아래 lockedOut이 그린다.
    navigate(user ? '/blog' : '/login')
  }, [user, loading, navigate, dirty])

  // 권한을 잃었는데 쓰던 내용이 있는 상태. **state가 아니라 파생값이다** — effect 안에서
  // setError를 하면 렌더가 연쇄되고 eslint(react-hooks/set-state-in-effect)가 막는다.
  // PostDetailPage가 '잘못된 주소'를 같은 이유로 파생값으로 두고 있다.
  const lockedOut = !loading && dirty && (!user || !canWrite(user))

  // 자동 임시보관. 한 글자마다 쓰면 긴 본문에서 직렬화가 잦아지므로 1초 쉴 때만 쓴다.
  // 수정 모드에서 서버 원본과 지문이 같으면 건너뛴다(그냥 열어보고 나간 경우).
  const snapshot = snapshotOf({ title, content, coverImage, tags, series, visibility })
  useEffect(() => {
    if (!dirty) return
    if (serverSnapshot.current === snapshot) return
    const t = setTimeout(() => {
      if (discarded.current) return
      const at = Date.now()
      writeDraft(key, { title, content, coverImage, tags, series, visibility, savedAt: at })
      setDraftAt(at)
    }, 1000)
    return () => clearTimeout(t)
    // snapshot이 모든 필드를 덮으므로 개별 필드를 의존성에 또 넣지 않는다.
  }, [key, dirty, snapshot, title, content, coverImage, tags, series, visibility])

  // 탭을 닫거나 새로고침할 때. 자동보관이 1초 지연이라 **마지막 1초는 아직 안 쓰였을 수
  // 있어** 여기서 한 번 더 쓰고, 브라우저 기본 확인창을 띄운다.
  useEffect(() => {
    if (!dirty) return
    if (serverSnapshot.current === snapshot) return
    function onBeforeUnload(e: BeforeUnloadEvent) {
      if (discarded.current) return
      writeDraft(key, { title, content, coverImage, tags, series, visibility, savedAt: Date.now() })
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [key, dirty, snapshot, title, content, coverImage, tags, series, visibility])

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
        // 아직 아무것도 안 고친 상태의 지문. 이것과 같으면 임시보관하지 않는다.
        serverSnapshot.current = snapshotOf({
          title: p.title,
          content: p.content,
          coverImage: p.cover_image ?? '',
          tags: p.tags ?? [],
          series: p.series ?? '',
          visibility: p.visibility,
        })
      })
      .catch((e) => setError((e as Error).message))
  }, [editingId])

  // alt 를 파일 이름으로 채운다(2026-08-31). 예전에는 `![](url)` 로 **항상 빈 값**이라
  // 화면낭독기가 본문의 그 이미지를 통째로 건너뛰었다. 같은 uploadImage 를 쓰는
  // SlotEditor 는 처음부터 파일명으로 채우고 그 이유까지 주석에 적어뒀는데, 정작
  // 더 많이 쓰는 본문 쪽에 그 규약이 안 닿아 있었다.
  // 마음에 안 들면 고치면 된다 — 무엇을 고쳐야 하는지가 눈에 보이는 게 중요하다.
  // 대괄호는 마크다운 링크 문법을 깨므로 뺀다.
  function altFrom(name: string): string {
    return name.replace(/\.[^.]+$/, '').replace(/[[\]]/g, '').slice(0, 60)
  }

  /**
   * 업로드해서 본문에 `![alt](url)` 로 넣는다. **세 입구가 여기 하나로 모인다** —
   * 첨부 버튼, 붙여넣기, 드래그드롭. (2026-09-02)
   *
   * 왜 지금까지 붙여넣기·드롭이 없었나: 재료는 다 있었는데 입구가 없었다. 업로드
   * 함수도, 커서 위치 삽입(insertAt)도 진작 있었고 스크린샷을 붙여넣는 건 글 쓰다
   * 가장 흔한 동작인데, 그때 브라우저 기본 동작은 **이미지를 그냥 버리는 것**이다
   * (textarea 에 파일을 떨구면 그 파일로 페이지를 이동해 쓰던 글이 날아가기도 한다).
   *
   * `at` 이 null 이면 본문 끝에 붙인다(첨부 버튼의 기존 동작). 숫자면 그 자리에
   * 넣는다 — 붙여넣기·드롭은 커서가 있는 자리가 사용자가 기대하는 자리다.
   *
   * setContent 를 **함수형으로** 부른다. 업로드는 초 단위라 그동안 사용자가 계속
   * 타이핑할 수 있는데, 렌더 시점의 content 를 닫아 쓰면 그 타이핑이 통째로 날아간다.
   */
  async function uploadAndInsert(files: File[], at: number | null) {
    if (files.length === 0 || uploading) return
    setUploading(true)
    setError('')
    let pos = at
    try {
      for (const file of files) {
        const url = await uploadImage(file)
        const md = `\n![${altFrom(file.name)}](${url})\n`
        const insertAtPos = pos
        setContent((prev) =>
          insertAtPos === null ? `${prev}${md}` : prev.slice(0, insertAtPos) + md + prev.slice(insertAtPos),
        )
        if (pos !== null) {
          pos += md.length
          const caret = pos
          requestAnimationFrame(() => {
            const ta = contentRef.current
            if (!ta) return
            ta.focus()
            ta.selectionStart = ta.selectionEnd = caret
          })
        }
      }
    } catch (err) {
      // 실패 처리는 버튼 경로와 같다 — 폼 아래 빨간 줄 하나(아래 error).
      setError((err as Error).message)
    } finally {
      setUploading(false)
    }
  }

  /** 클립보드·드롭에서 **이미지 파일만** 골라낸다. 나머지는 손대지 않는다. */
  function imageFilesOf(dt: DataTransfer | null): File[] {
    if (!dt) return []
    return Array.from(dt.files).filter((f) => f.type.startsWith('image/'))
  }

  async function handleImagePick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    // 같은 파일을 연달아 고를 수 있게 먼저 비운다(await 뒤엔 target 이 이미 바뀔 수 있다).
    e.target.value = ''
    if (!file) return
    await uploadAndInsert([file], null)
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
    // **본문이 있으면 확인받는다.** 이 버튼은 제목·본문을 통째로 덮어쓰는데 되돌리는 길이
    // 없다. 제목에는 아래에 '비어 있을 때만 채운다'는 가드가 이미 있는데(`!title.trim()`),
    // 정작 분량이 훨씬 큰 본문에는 그 가드가 없었다. (2026-08-27)
    if (content.trim() && !window.confirm('AI 초안이 지금 쓰던 본문을 덮어써. 되돌릴 수 없어. 계속할까?')) return
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
    // **중복 제출 방어.** 예전엔 busy 상태도 disabled도 없었고 createPost에 타임아웃도
    // 없어서(CloudFront 오리진 상한 60초), 느릴 때 두세 번 누르면 **같은 글이 여러 개
    // 생성됐다.** 글 생성은 30/h 리밋 안이라 서버도 안 막는다. (2026-08-11 공백검사)
    // 같은 페이지의 AI 초안만 disabled·스피너·타임아웃이 제대로 돼 있었는데, 정작
    // 글을 저장하는 동작에는 없었다.
    if (saving) return
    setSaving(true)
    try {
      const cover = coverImage.trim() || null
      // 입력 중이던 태그도 마지막에 반영
      const finalTags = tagInput.trim() && !tags.includes(tagInput.trim()) ? [...tags, tagInput.trim()].slice(0, 10) : tags
      // 빈칸이면 연재 없음(null) — 서버도 ''를 None으로 정규화하지만 여기서도 맞춰 보낸다
      const finalSeries = series.trim() || null
      const saved =
        editingId === null
          ? await createPost(title, content, cover, finalTags, finalSeries, visibility)
          : await updatePost(editingId, title, content, cover, finalTags, finalSeries, visibility)
      discarded.current = true
      clearDraft(key) // 서버에 들어갔으니 임시본은 버린다
      // **목록 1쪽이 아니라 방금 저장한 글로 간다.** 예전엔 `/blog`로 보내서, 쓴 글을
      // 확인하려면 목록에서 다시 찾아 들어가야 했다(2쪽으로 밀렸으면 더 나쁘다).
      // id는 createPost·updatePost의 반환값에 원래부터 있었는데 버리고 있었다.
      navigate(`/blog/posts/${saved.id}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-accent hover:underline">
        <IconArrowLeft className="h-4 w-4" />홈으로
      </Link>
      <div className="mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
      <h1 className={`mb-6 text-3xl font-semibold tracking-tight ${ui.pageTitle}`}>
        {editingId === null ? '새 글 쓰기' : '글 수정'}
      </h1>

      {/* 복구 제안. **자동으로 안 덮는다** — 수정 모드에서 낡은 초안이 서버 본문을 조용히
          밀어내면 그건 유실을 막는 게 아니라 다른 유실이다. 고르는 건 사람이 한다. */}
      {recovered && (
        <div
          role="status"
          className="mb-6 rounded-2xl border border-amber-500/25 bg-amber-50 p-4 dark:border-amber-400/25 dark:bg-amber-400/[0.08]"
        >
          <p className="text-sm text-gray-700 dark:text-gray-200">
            쓰다 만 글이 이 브라우저에 남아 있어. {new Date(recovered.savedAt).toLocaleString()} 기준, 제목은
            {' '}‘{recovered.title.trim() || '(제목 없음)'}’ 이고 본문은 {recovered.content.length}자야.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className={btnPrimary}
              onClick={() => {
                setTitle(recovered.title)
                setContent(recovered.content)
                setCoverImage(recovered.coverImage ?? '')
                setTags(recovered.tags ?? [])
                setSeries(recovered.series ?? '')
                setVisibility(recovered.visibility ?? 'public')
                // 불러온 뒤에는 서버 지문을 지운다. 안 그러면 수정 모드에서 '원본과 같다'는
                // 판정에 걸려 불러온 내용이 다시 임시보관되지 않는다.
                serverSnapshot.current = null
                setRecovered(null)
              }}
            >
              이어서 쓰기
            </button>
            <button
              type="button"
              className={btnGhost}
              onClick={() => {
                clearDraft(key)
                setRecovered(null)
              }}
            >
              버리기
            </button>
          </div>
        </div>
      )}

      {/* AI 초안 잡기: 거친 메모 → 정돈된 글 구조를 제목·본문에 채움 */}
      <div className="mb-6 rounded-2xl border border-accent/15 bg-accent/[0.05] p-5/[0.07]">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-accent/10 text-accent">
            <IconSparkles className="h-4 w-4" />
          </span>
          <p className="text-sm font-medium text-accent">AI로 초안 잡기</p>
        </div>
        <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
          떠오르는 메모를 대충 적고 누르면 제목·소제목·초안으로 정리해줘. (제목/본문을 덮어써)
        </p>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          생성에 길면 1분쯤 걸려. 디스코드·인스타 같은 앱 안 브라우저에선 멈출 수 있으니 크롬 등 일반 브라우저에서 써줘.
        </p>
        {/* 서버 모델(Claude) 남은 횟수. BYOK(내 키)는 한도 없음 */}
        {usage && (
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            서버 모델 남은 횟수 · 오늘{' '}
            <span className={usage.daily_used >= usage.daily_cap ? 'font-medium text-red-500' : ''}>
              {Math.max(0, usage.daily_cap - usage.daily_used)}/{usage.daily_cap}
            </span>{' · '}이번 달{' '}
            <span className={usage.monthly_used >= usage.monthly_cap ? 'font-medium text-red-500' : ''}>
              {Math.max(0, usage.monthly_cap - usage.monthly_used)}/{usage.monthly_cap}
            </span>
          </p>
        )}
        {/* placeholder 는 라벨이 아니다 — 입력을 시작하면 사라지고, 화면낭독기는 칸
            이름을 못 읽는다. 이 파일이 이미 쓰는 방식(aria-label)을 그대로 쓴다.
            (2026-08-11 검사 9번의 잔여 6칸, 09-02 정리) */}
        <textarea
          placeholder="예: 오늘 AWS Summit 갔다왔는데 EKS 세션이 인상깊었음. 비용 얘기도 나왔고…"
          aria-label="AI 초안용 메모"
          rows={3}
          maxLength={MEMO_MAX}
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
          className={`${input} mt-3`}
        />
        {memo.length > 0 && (
          <p className="mt-1 text-right text-xs text-gray-500 dark:text-gray-400">{memo.length}/{MEMO_MAX}</p>
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
                        {PROVIDER_LABEL[prov] ?? prov} 모델 직접 입력
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
              <IconChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500 dark:text-gray-400" />
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
              <p className="text-xs text-gray-500 dark:text-gray-400">Opus(고품질)는 결제 후 쓸 수 있어.</p>
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
        <input
          placeholder="제목"
          aria-label="제목"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className={`${input} text-lg`}
        />
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
            연재 (선택). 같은 이름을 쓴 글끼리 묶여 이전/다음 편이 생겨:
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
                <span key={t} className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent">
                  #{t}
                  <button type="button" onClick={() => removeTag(t)} className="leading-none text-accent/60 hover:text-accent" aria-label={`${t} 삭제`}>×</button>
                </span>
              ))}
            </div>
          )}
          <input
            value={tagInput}
            aria-label="태그 추가"
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
            <span className="px-1 text-xs text-gray-500 dark:text-gray-400">미리보기 중이야. 꾸미려면 ‘편집으로’ 눌러</span>
          )}
          <button
            type="button"
            onClick={() => setPreview((v) => !v)}
            className={`ml-auto rounded-lg px-2.5 py-1 text-xs font-medium transition ${preview ? 'bg-accent text-on-accent' : 'text-gray-600 hover:bg-black/[0.06] dark:text-gray-300 dark:hover:bg-white/10'}`}
          >
            {preview ? '편집으로' : '미리보기'}
          </button>
        </div>
        {preview ? (
          // 미리보기: 실제 글 화면과 같은 방식(ReactMarkdown)으로 '꾸며진' 결과를 보여줌
          <div className="prose prose-gray min-h-[18rem] max-w-none rounded-xl border border-black/10 bg-white p-5 prose-headings:tracking-tight prose-a:text-accent prose-img:rounded-xl dark:prose-invert dark:border-white/15 dark:bg-white/[0.03]">
            {/* ⚠️ 보안: rehype-raw/allowDangerousHtml 금지 — 본문은 사용자·AI초안 값이고 서버가
                HTML을 새니타이즈 안 한다. react-markdown이 raw HTML을 안 렌더하는 게 저장형 XSS
                방어선. (PostDetailPage에 같은 주석) */}
            {content.trim() ? (
              <ReactMarkdown>{content}</ReactMarkdown>
            ) : (
              <p className="text-gray-500 dark:text-gray-400">미리볼 내용이 없어. 먼저 내용을 써봐.</p>
            )}
          </div>
        ) : (
          <textarea
            ref={contentRef}
            id="content-input"
            aria-label="본문"
            placeholder="내용 (위 버튼으로 꾸미거나 마크다운 직접 입력. 이미지는 붙여넣거나 끌어다 놓으면 커서 자리에 들어가)"
            rows={14}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            // **이미지가 아닌 붙여넣기는 기본 동작을 막지 않는다.** 글 쓰는 칸에서
            // 가장 흔한 붙여넣기는 그냥 텍스트라, 여기서 preventDefault 를 먼저 부르면
            // 평범한 복사·붙여넣기가 통째로 죽는다. 이미지가 있을 때만 가로챈다.
            onPaste={(e) => {
              const files = imageFilesOf(e.clipboardData)
              if (files.length === 0) return
              e.preventDefault()
              void uploadAndInsert(files, e.currentTarget.selectionStart)
            }}
            // dragover 에서 기본 동작을 막아야 drop 이 우리에게 온다. 안 막으면 브라우저가
            // **그 파일로 페이지를 이동해** 쓰던 글이 통째로 날아간다(초안 백업이 있어도
            // 겪을 이유가 없는 사고다). 파일 드래그일 때만 막는다.
            onDragOver={(e) => {
              if (Array.from(e.dataTransfer.types).includes('Files')) e.preventDefault()
            }}
            onDrop={(e) => {
              const files = imageFilesOf(e.dataTransfer)
              if (files.length === 0) return
              e.preventDefault()
              void uploadAndInsert(files, e.currentTarget.selectionStart)
            }}
            className={`${input} font-mono`}
          />
        )}
        <label className="flex flex-wrap items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300">
          <IconImage className="h-4 w-4" />이미지 첨부:
          <input
            type="file"
            accept="image/*"
            onChange={handleImagePick}
            disabled={uploading}
            className="text-sm"
          />
          {/* 자리를 항상 잡아 둔다 — 형제 노드가 생겼다 사라지면 번역기·인앱 브라우저에서
              재조정이 깨진다(이 파일의 AI 상태줄이 같은 이유로 고정 컨테이너다). */}
          <span aria-live="polite" className="text-gray-600 dark:text-gray-300">
            {uploading ? '이미지 올리는 중…' : ''}
          </span>
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
          <button type="submit" className={btnPrimary} disabled={saving} aria-busy={saving}>
            {saving ? '저장 중…' : editingId === null ? '글 작성' : '수정 저장'}
          </button>
          <button
            type="button"
            onClick={() => {
              // 취소는 되돌릴 수 없다(임시본까지 지운다). 쓰던 게 있으면 확인받는다.
              if (dirty && !window.confirm('쓰던 내용을 버리고 나갈까? 임시 보관본도 같이 지워져.')) return
              discarded.current = true
              clearDraft(key)
              navigate('/blog')
            }}
            className={btnGhost}
          >
            취소
          </button>
        </div>
        {/* 임시보관은 저장이 아니다. 그래서 '저장됨'이라고 안 적는다 — 그렇게 적으면
            브라우저를 바꿔도 남아 있다고 읽힌다. */}
        {draftAt && (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            이 브라우저에 임시 보관됨 ({new Date(draftAt).toLocaleTimeString()}). 저장하려면 아래 버튼을 눌러줘.
          </p>
        )}
        {lockedOut && (
          <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">
            {user
              ? '글쓰기 권한이 사라졌어. 쓰던 내용은 이 브라우저에 임시 보관해뒀어.'
              : '로그인이 풀렸어. 쓰던 내용은 이 브라우저에 임시 보관했으니, 다시 로그인하고 이 화면으로 돌아오면 이어서 쓸 수 있어.'}
          </p>
        )}
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      </form>
      </div>
    </div>
  )
}

export default WritePostPage
