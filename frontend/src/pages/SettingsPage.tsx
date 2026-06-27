import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { canWrite } from '../api/auth'
import { fetchKeys, saveKey, deleteKey, type KeyStatus } from '../api/ai'
import { ui } from '../ui'
import { IconCheck } from '../components/icons'

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
  const { user, loading } = useAuth()
  const [keys, setKeys] = useState<KeyStatus[]>([])
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [baseUrls, setBaseUrls] = useState<Record<string, string>>({}) // compatible용 주소
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (loading || !canWrite(user)) return
    fetchKeys().then(setKeys).catch((e) => setError(e.message))
  }, [user, loading])

  if (loading) return null
  // BYOK는 글쓰기 권한자(writer/admin)만 의미 있음
  if (!canWrite(user)) return <Navigate to="/blog" replace />

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
      <h1 className={`text-3xl font-bold tracking-tight ${ui.gradientText}`}>설정</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
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
                <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">{p.hint}</p>
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
