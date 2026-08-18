import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { updateDisplayName, updateHandle } from '../api/auth'
import { canWrite } from '../api/auth'
import { fetchKeys, saveKey, deleteKey, type KeyStatus } from '../api/ai'
import { ui } from '../ui'
import { IconCheck } from '../components/icons'
import SkinEditor from '../components/SkinEditor'
import SlotEditor from '../components/SlotEditor'

// provider별 색 점 (시각적 구분용)
const DOT: Record<string, string> = {
  openai: 'bg-emerald-500',
  gemini: 'bg-blue-500',
  compatible: 'bg-violet-500',
  anthropic: 'bg-orange-500',
  cohere: 'bg-pink-500',
}

// BYOK 제공자 표시 정보. needsBaseUrl=true면 주소(base URL)도 입력받음
const PROVIDERS: { id: string; name: string; hint: string; needsBaseUrl?: boolean }[] = [
  { id: 'openai', name: 'OpenAI (GPT)', hint: 'platform.openai.com → API keys (sk-... 형태)' },
  { id: 'gemini', name: 'Google (Gemini)', hint: 'aistudio.google.com → API key (AIza... 형태)' },
  {
    id: 'compatible',
    name: 'OpenAI 호환 (Grok·DeepSeek·OpenRouter·로컬 등)',
    hint: '주소(base URL)+키. 예: Grok=https://api.x.ai/v1, DeepSeek=https://api.deepseek.com, OpenRouter=https://openrouter.ai/api/v1',
    needsBaseUrl: true,
  },
  {
    id: 'anthropic',
    name: 'Anthropic (내 Claude 키)',
    hint: 'console.anthropic.com → 자기 키로 Claude(Opus 포함) 직접. 모델ID 예: claude-opus-4-8',
  },
  { id: 'cohere', name: 'Cohere', hint: 'dashboard.cohere.com → API key. 모델ID 예: command-r-plus' },
]

function SettingsPage() {
  const { user, loading, refreshUser } = useAuth()
  const [keys, setKeys] = useState<KeyStatus[]>([])
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [baseUrls, setBaseUrls] = useState<Record<string, string>>({}) // compatible용 주소
  // 서버 값을 state로 **복사하지 않는다.** null이면 '아직 안 건드림' → 서버 값을 그대로 보여준다.
  // 복사하면 effect로 동기화해야 하고(이 저장소가 금지하는 패턴), 저장 후 되돌리기도 번거롭다.
  const [nameDraft, setNameDraft] = useState<string | null>(null)
  const [savingName, setSavingName] = useState(false)
  // 표시명과 같은 방식 — null이면 '아직 안 건드림'이라 서버 값을 그대로 보여준다
  const [handleDraft, setHandleDraft] = useState<string | null>(null)
  const [savingHandle, setSavingHandle] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (loading || !canWrite(user)) return
    fetchKeys().then(setKeys).catch((e) => setError(e.message))
  }, [user, loading])

  if (loading) return null
  // 로그인 자체가 없으면 볼 것이 없다.
  // ⚠️ 예전엔 여기서 canWrite가 아니면 통째로 돌려보냈는데, 그러면 **표시명조차 못 정한다**
  // (댓글·구독 목록에 이름이 보이는 건 권한과 무관하다). BYOK 구역만 권한으로 가린다.
  if (!user) return <Navigate to="/login" replace />

  const name = nameDraft ?? user?.display_name ?? ''
  const handle = handleDraft ?? user?.handle ?? ''

  async function handleSaveName() {
    setError(''); setMsg('')
    setSavingName(true)
    try {
      const updated = await updateDisplayName(name.trim())
      setNameDraft(null) // 다시 서버 값을 따라가게 한다
      await refreshUser() // 헤더·다른 화면이 즉시 같은 이름을 쓰게 한다
      setMsg(updated.display_name ? `표시명을 '${updated.display_name}'로 바꿨어` : '표시명을 지웠어')
    } catch (e) {
      setError(e instanceof Error ? e.message : '표시명 변경 실패')
    } finally {
      setSavingName(false)
    }
  }

  async function handleSaveHandle() {
    setError(''); setMsg('')
    setSavingHandle(true)
    try {
      const updated = await updateHandle(handle.trim())
      setHandleDraft(null)
      await refreshUser()
      setMsg(updated.handle ? `주소를 /@${updated.handle} 로 정했어` : '블로그 주소를 없앴어')
    } catch (e) {
      setError(e instanceof Error ? e.message : '주소 변경 실패')
    } finally {
      setSavingHandle(false)
    }
  }

  const keyOf = (provider: string) => keys.find((k) => k.provider === provider)
  const hasKey = (provider: string) => keyOf(provider)?.has_key ?? false

  async function handleSave(provider: string, needsBaseUrl?: boolean) {
    const key = (inputs[provider] || '').trim()
    if (!key) return
    const baseUrl = (baseUrls[provider] || '').trim()
    if (needsBaseUrl && !baseUrl) {
      setError('이 provider는 주소(base URL)도 입력해야 해'); return
    }
    setError(''); setMsg('')
    try {
      await saveKey(provider, key, baseUrl || undefined)
      setInputs((p) => ({ ...p, [provider]: '' }))
      setKeys(await fetchKeys())
      setMsg(`${provider} 키를 저장했어`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  async function handleDelete(provider: string) {
    setError(''); setMsg('')
    try {
      await deleteKey(provider)
      setKeys(await fetchKeys())
      setMsg(`${provider} 키를 삭제했어`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '삭제 실패')
    }
  }

  return (
    <div>
      <h1 className={`text-3xl font-bold tracking-tight ${ui.pageTitle}`}>설정</h1>
      {/* 표시명 — 구독 목록·댓글·알림에 나가는 이름.
          이 칸이 없던 동안 모든 계정이 "회원"으로 보여서 구독 화면에서 누가 누군지
          구분이 안 됐다(2026-08-14 신고). 정하는 통로가 없으면 폴백이 아무리 좋아도
          영원히 폴백이다. */}
      <section className={`${ui.card} mt-6`}>
        <h2 className="text-lg font-semibold tracking-tight">표시명</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          댓글·구독 목록에 보이는 이름이야. <span className="font-medium">공개돼</span> —
          이메일은 어디에도 안 쓰이니 아무 이름이나 정하면 돼.
          <br />
          <span className="text-xs">비워서 저장하면 '안 정함'으로 돌아가고, 화면엔 `회원 #{user.id}`로 보여.</span>
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input
            className={`${ui.input} max-w-xs`}
            value={name}
            maxLength={50}
            placeholder="예: 유노"
            onChange={(e) => setNameDraft(e.target.value)}
          />
          <button type="button" className={ui.btnPrimary} onClick={handleSaveName} disabled={savingName}>
            {savingName ? '저장 중…' : '저장'}
          </button>
        </div>
      </section>

      {/* 블로그 주소 — 이게 있어야 `/@handle` 화면이 열린다.
          표시명과 나눠 둔 이유: 이건 주소라 형식·중복 검사가 붙고 실패 사유가 다르다.
          한 칸에 묶으면 이름을 바꾸려다 주소 검증에 걸려 둘 다 못 바꾸게 된다. */}
      {canWrite(user) && (
        <section className={`${ui.card} mt-6`}>
          <h2 className="text-lg font-semibold tracking-tight">블로그 주소</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            정하면 <span className="font-medium">내 글만 모아 보는 주소</span>가 생겨. 스킨도 여기에 걸려.
            <br />
            <span className="text-xs">
              영소문자·숫자·하이픈·밑줄 2~20자. 비워서 저장하면 주소를 없애.
            </span>
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="text-sm text-gray-400">/@</span>
            <input
              className={`${ui.input} max-w-xs`}
              value={handle}
              maxLength={20}
              placeholder="yuno"
              autoComplete="off"
              onChange={(e) => setHandleDraft(e.target.value)}
            />
            <button type="button" className={ui.btnPrimary} onClick={handleSaveHandle} disabled={savingHandle}>
              {savingHandle ? '저장 중…' : '저장'}
            </button>
            {user.handle && (
              <a href={`/@${user.handle}`} className="text-sm text-accent hover:underline">
                열어보기 →
              </a>
            )}
          </div>
        </section>
      )}

      {/* 블로그 스킨 — 글쓰기 권한자 전체에게 연다.
          08-18 오전엔 admin만이었다. 그땐 블로그 주소가 /blog 하나뿐이라 글쓴이에게
          열어주면 '저장은 되는데 화면엔 안 나오는' 칸이 됐기 때문이다. 같은 날 오후에
          `/@handle`이 생기면서 저장한 값이 실제로 보일 자리가 생겼다 — 그래서 넓혔다.
          주인이 저장한 것은 사이트 스킨(`/blog`)이 되고, 글쓴이 것은 자기 블로그에 걸린다. */}
      {canWrite(user) && <SkinEditor />}
      {/* 스킨 바로 아래에 둔다 — 둘은 같은 것의 양면이고(어떻게 보이나 / 무엇이
          적히나) `class`로 서로를 참조한다. 떨어뜨려 놓으면 그 관계가 안 보인다. */}
      {canWrite(user) && <SlotEditor />}

      <p className="mt-8 text-sm text-gray-500 dark:text-gray-400">
        내 API 키를 등록하면 글쓰기에서 GPT·Gemini·Grok 등 다른 모델로도 초안을 만들 수 있어.
        키는 암호화해서 저장되고, 화면엔 등록 여부만 보여(원문은 다시 안 보임).
      </p>

      {msg && (
        <p className="mt-4 inline-flex items-center gap-1 text-sm text-emerald-600 dark:text-emerald-400">
          <IconCheck className="h-4 w-4" />{msg}
        </p>
      )}
      {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

      <div className="mt-6 space-y-4">
        {PROVIDERS.map((p) => (
          <div key={p.id} className={ui.card}>
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="flex items-center gap-2 font-medium">
                  <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT[p.id] ?? 'bg-gray-400'}`} />
                  {p.name}
                </p>
                <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{p.hint}</p>
              </div>
              {hasKey(p.id) ? (
                <span className="inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                  등록됨
                </span>
              ) : (
                <span className="inline-block rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500 dark:bg-white/10 dark:text-gray-400">
                  미등록
                </span>
              )}
            </div>
            {/* OpenAI 호환은 주소(base URL) 먼저 */}
            {p.needsBaseUrl && (
              <input
                type="text"
                placeholder={keyOf(p.id)?.base_url ? `현재: ${keyOf(p.id)?.base_url} (바꾸려면 입력)` : '주소(base URL) 예: https://api.x.ai/v1'}
                value={baseUrls[p.id] || ''}
                onChange={(e) => setBaseUrls((prev) => ({ ...prev, [p.id]: e.target.value }))}
                className={`${ui.input} mt-3 max-w-md`}
                autoComplete="off"
              />
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input
                type="password"
                placeholder={hasKey(p.id) ? '새 키로 교체하려면 입력' : '여기에 API 키 붙여넣기'}
                value={inputs[p.id] || ''}
                onChange={(e) => setInputs((prev) => ({ ...prev, [p.id]: e.target.value }))}
                className={`${ui.input} max-w-md`}
                autoComplete="off"
              />
              <button type="button" onClick={() => handleSave(p.id, p.needsBaseUrl)} className={ui.btnPrimary}>
                {hasKey(p.id) ? '키 교체' : '키 저장'}
              </button>
              {hasKey(p.id) && (
                <button type="button" onClick={() => handleDelete(p.id)} className={ui.btnGhost}>
                  삭제
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default SettingsPage
