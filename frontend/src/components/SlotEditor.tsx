import { useEffect, useRef, useState } from 'react'
import { fetchMine, saveSlots, previewSlots, restoreSiteSkin } from '../api/skin'
import { EMPTY_SLOTS, SLOT_KEYS, type SlotKey, type Slots } from '../api/slots'
import { uploadImage } from '../api/uploads'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'
import { IconCheck, IconImage, IconSpinner } from './icons'

/**
 * '내 문장' 편집기 — 제목 아래·사이드바·푸터에 자기 HTML을 넣는다.
 *
 * 스킨 편집기(SkinEditor)와 짝이다. 저건 '어떻게 보이나', 이건 '무엇이 적히나'.
 * 둘을 잇는 건 `class`다 — 여기서 `<p class="인사">`를 쓰고 스킨에서 `.인사 { ... }`를
 * 쓰면 된다. 그래서 아래 안내에도 그 이야기를 적어 뒀다.
 *
 * 미리보기는 SkinEditor와 같은 방식이다: **지금 이 화면에** 바로 반영하고, 저장 없이
 * 떠나면 되돌린다. 다만 문장은 세 자리가 이 화면 밖(헤더 아래 목록, 사이드바, 푸터)에
 * 있어서, 설정 화면에서는 푸터 하나만 실제로 눈에 들어온다. 그래서 칸마다 **작은
 * 미리보기 상자**를 따로 둔다 — 화면 미리보기만으로는 보이지 않는 자리가 있다.
 */

const FIELDS: { key: SlotKey; label: string; where: string; placeholder: string }[] = [
  {
    key: 'intro',
    label: '머리말',
    where: '블로그 제목 바로 아래',
    placeholder: '<p>백엔드를 직접 굴리면서 부딪힌 것을 적습니다.</p>',
  },
  {
    key: 'aside',
    // 이름과 위치를 같이 고쳤다(2026-08-19). '사이드바 소개'는 사이트 주인에게만 맞는
    // 말이었다 — 사이드바는 `/blog`에만 있고 `/blog`는 항상 주인 문장을 쓴다. 그래서
    // 글쓴이가 여기 쓴 건 **저장은 되는데 어느 화면에도 안 나왔다.** 지금은
    // `/@주소`의 이름 아래에 그린다(AuthorPage). 같은 뜻의 자리이고 화면마다 있다.
    label: '프로필 소개',
    where: '/@주소는 이름 아래 · 사이트 첫 화면은 사이드바',
    placeholder: '<p>서울 · 백엔드</p>\n<p><a href="https://github.com/">GitHub</a></p>',
  },
  {
    key: 'footer',
    label: '푸터',
    where: '화면 맨 아래',
    placeholder: '<p>문의: <a href="mailto:me@example.com">메일</a></p>',
  },
]

// 저장할 때 사라지는 것들. 서버가 허용 목록으로 다시 쓰므로 여기 적힌 게 전부는
// 아니지만(모르는 태그는 전부 사라진다), 사람들이 실제로 넣어 보는 것이 이 셋이다.
const ALLOWED_HINT =
  'p br strong em b i u s small span div h2 h3 h4 ul ol li blockquote code pre figure figcaption a img'

function SlotEditor() {
  const { user } = useAuth()
  const isSite = user?.role === 'admin'

  const [draft, setDraft] = useState<Slots>(EMPTY_SLOTS)
  const [saved, setSaved] = useState<Slots>(EMPTY_SLOTS)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState<SlotKey | null>(null)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  // 어느 칸에 이미지를 넣을지 — 파일 선택창이 열린 뒤에도 알아야 한다.
  const pendingSlot = useRef<SlotKey | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  // 칸마다 커서 위치를 기억한다. 이미지는 **커서 자리에** 들어가야 한다 —
  // 항상 끝에 붙이면 문단 사이에 사진을 넣을 방법이 없다.
  const areas = useRef<Partial<Record<SlotKey, HTMLTextAreaElement | null>>>({})

  useEffect(() => {
    fetchMine()
      .then((mine) => {
        setDraft(mine.slots)
        setSaved(mine.slots)
      })
      .catch((e) => setError(e instanceof Error ? e.message : '내 문장을 못 불러왔어'))
      .finally(() => setLoading(false))
  }, [])

  // 떠날 때는 **사이트 외형**으로 되돌린다(내가 저장한 것이 아니라).
  // 이유는 api/skin.ts의 restoreSiteSkin 주석에 있다 — 주인이 아닌 글쓴이가
  // 자기 문장이 사이트에 걸린 줄 착각하는 걸 막는다.
  useEffect(() => restoreSiteSkin, [])

  function edit(key: SlotKey, value: string) {
    const next = { ...draft, [key]: value }
    setDraft(next)
    previewSlots(next) // 타이핑하는 대로 화면(푸터 등)이 바뀐다
    setMsg('')
  }

  /** 커서 자리에 문자열을 끼워 넣는다. 선택 영역이 있으면 그것을 대체한다. */
  function insertAt(key: SlotKey, snippet: string) {
    const el = areas.current[key]
    const value = draft[key]
    const start = el?.selectionStart ?? value.length
    const end = el?.selectionEnd ?? value.length
    const next = value.slice(0, start) + snippet + value.slice(end)
    edit(key, next)
    // 상태 반영 뒤에 커서를 끼운 것의 끝으로 옮긴다. 안 하면 커서가 맨 앞으로
    // 튀어서 다음에 넣는 이미지가 글 맨 앞에 쌓인다.
    requestAnimationFrame(() => {
      const node = areas.current[key]
      if (!node) return
      node.focus()
      node.setSelectionRange(start + snippet.length, start + snippet.length)
    })
  }

  function pickImage(key: SlotKey) {
    pendingSlot.current = key
    fileInput.current?.click()
  }

  async function handleFile(file: File | undefined) {
    const key = pendingSlot.current
    // 같은 파일을 두 번 고를 수 있게 값을 비운다(안 그러면 change가 안 난다).
    if (fileInput.current) fileInput.current.value = ''
    if (!file || !key) return
    setUploading(key)
    setError('')
    try {
      const url = await uploadImage(file)
      // alt를 파일 이름으로 채운다. 빈 alt로 두면 화면낭독기가 그냥 지나치는데,
      // 사람이 넣은 사진은 보통 뜻이 있다. 마음에 안 들면 고치면 된다 —
      // 무엇을 고쳐야 하는지가 눈에 보이는 게 중요하다.
      const alt = file.name.replace(/\.[^.]+$/, '').slice(0, 60)
      insertAt(key, `<img src="${url}" alt="${escapeAttr(alt)}">`)
      setMsg('이미지를 넣었어. 아직 저장 전이야.')
    } catch (e) {
      setError(e instanceof Error ? e.message : '업로드 실패')
    } finally {
      setUploading(null)
    }
  }

  async function handleSave() {
    setBusy(true)
    setError('')
    setMsg('')
    try {
      const result = await saveSlots(draft, isSite)
      // **서버가 씻은 결과로 입력칸을 다시 채운다.** 보낸 것과 다를 수 있고, 그
      // 차이가 곧 "뭐가 지워졌는지"다. 원문을 그대로 두면 저장한 것과 화면에 보이는
      // 것이 달라지고, 사람은 자기 글이 멀쩡히 저장된 줄 안다.
      setDraft(result.slots)
      setSaved(result.slots)
      const cleaned = SLOT_KEYS.some((k) => result.slots[k] !== draft[k])
      setMsg(
        cleaned
          ? '저장했어. 쓸 수 없는 태그·속성은 지웠고, 지금 칸에 보이는 게 실제로 저장된 내용이야.'
          : '저장했어. 방문자에게도 이대로 보여.',
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    } finally {
      setBusy(false)
    }
  }

  function handleRevert() {
    setDraft(saved)
    previewSlots(saved)
    setMsg('저장된 문장으로 되돌렸어.')
  }

  if (loading) return null

  const dirty = SLOT_KEYS.some((k) => draft[k] !== saved[k])

  return (
    <section className={`${ui.card} mt-6`}>
      <h2 className="text-lg font-semibold tracking-tight">내 문장</h2>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        블로그 세 자리에 직접 쓴 문장을 넣어. 스킨이 '어떻게 보이나'라면 이건 '무엇이
        적히나'야 — <code>&lt;p class="인사"&gt;</code>처럼 클래스를 붙이고 스킨에서{' '}
        <code>.인사</code>를 꾸미면 둘이 이어져.
        <br />
        <span className="text-xs">
          쓸 수 있는 태그: <code>{ALLOWED_HINT}</code> · 나머지와{' '}
          <code>&lt;script&gt;</code>·<code>on*</code>·<code>&lt;iframe&gt;</code>은 저장할 때 지워져.
        </span>
      </p>

      {/* 파일 선택창은 하나만 두고 어느 칸에서 눌렀는지는 ref로 기억한다.
          칸마다 <input type="file">을 두면 같은 것이 셋이 된다. */}
      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => void handleFile(e.target.files?.[0])}
      />

      <div className="mt-5 space-y-6">
        {FIELDS.map((f) => (
          <div key={f.key}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <label htmlFor={`slot-${f.key}`} className="text-sm font-medium">
                {f.label}
                <span className="ml-2 text-xs font-normal text-gray-500 dark:text-gray-400">
                  {f.where}
                </span>
              </label>
              <button
                type="button"
                onClick={() => pickImage(f.key)}
                disabled={uploading !== null}
                className={ui.btnGhost}
              >
                {uploading === f.key ? (
                  <IconSpinner className="h-4 w-4 animate-spin" />
                ) : (
                  <IconImage className="h-4 w-4" />
                )}
                이미지 넣기
              </button>
            </div>
            <textarea
              id={`slot-${f.key}`}
              ref={(el) => {
                areas.current[f.key] = el
              }}
              value={draft[f.key]}
              onChange={(e) => edit(f.key, e.target.value)}
              spellCheck={false}
              rows={4}
              placeholder={f.placeholder}
              className={`${ui.input} mt-2 font-mono text-xs leading-relaxed`}
            />
            {/* 칸별 미리보기. 세 자리 중 둘은 이 화면에 없어서(목록 머리말·사이드바)
                화면 미리보기만으로는 확인이 안 된다.
                여기 그리는 값은 **저장 전 원문**이라 아직 안 씻긴 상태다. 그래서
                HtmlSlot을 쓰지 않고 글자 그대로 보여준다 — 미리보기 상자 하나 때문에
                안 씻긴 HTML을 실행하는 경로를 만들지 않는다. */}
            {draft[f.key].trim() !== '' && (
              <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
                저장을 누르면 씻은 결과가 이 칸에 다시 채워져. 그게 실제로 나가는 내용이야.
              </p>
            )}
          </div>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <button type="button" onClick={handleSave} disabled={busy || !dirty} className={ui.btnPrimary}>
          {busy ? '저장 중…' : dirty ? '저장' : '저장됨'}
        </button>
        {dirty && (
          <button type="button" onClick={handleRevert} className={ui.btnGhost}>
            되돌리기
          </button>
        )}
        {user?.handle && (
          <a href={`/@${user.handle}`} className="text-sm text-accent hover:underline">
            /@{user.handle} 에서 보기
          </a>
        )}
      </div>

      {!isSite && (
        <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
          여기 쓴 문장은 <strong>내 블로그(/@주소)</strong>에만 나와. 사이트 첫 화면에
          나오는 건 주인이 쓴 문장이야.
        </p>
      )}

      {msg && (
        <p className="mt-3 inline-flex items-start gap-1 text-sm text-emerald-600 dark:text-emerald-400">
          <IconCheck className="mt-0.5 h-4 w-4 shrink-0" />
          {msg}
        </p>
      )}
      {error && <p className="mt-3 text-sm text-red-500">{error}</p>}
    </section>
  )
}

/** 속성값에 들어갈 문자열을 안전하게 — 따옴표가 들어가면 태그가 깨진다. */
function escapeAttr(v: string): string {
  return v.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
}

export default SlotEditor
