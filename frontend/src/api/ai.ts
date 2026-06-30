import { authHeaders } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

export interface AiModel {
  id: string
  label: string
  provider: string // claude / openai / gemini
}

export interface KeyStatus {
  provider: string
  has_key: boolean
  base_url?: string | null
}

// 내가 고를 수 있는 AI 모델 목록 + 기본값 (티어 + 내가 등록한 BYOK 키에 따라 다름)
export async function fetchAiModels(): Promise<{ models: AiModel[]; default: string }> {
  const res = await fetch(`${BASE}/ai/models`, { headers: authHeaders() })
  if (!res.ok) throw new Error('모델 목록을 불러오지 못했어')
  return res.json()
}

export interface AiUsage {
  daily_used: number
  daily_cap: number
  monthly_used: number
  monthly_cap: number
}

// 서버 모델(Claude) 사용량 — 오늘/이번 달 남은 횟수 표시용 (BYOK는 무제한이라 제외)
export async function fetchUsage(): Promise<AiUsage> {
  const res = await fetch(`${BASE}/ai/usage`, { headers: authHeaders() })
  if (!res.ok) throw new Error('사용량을 불러오지 못했어')
  return res.json()
}

// 내 BYOK 키 등록 현황 (값은 안 내려옴 — 있다/없다만)
export async function fetchKeys(): Promise<KeyStatus[]> {
  const res = await fetch(`${BASE}/ai/keys`, { headers: authHeaders() })
  if (!res.ok) throw new Error('키 현황을 불러오지 못했어')
  const data = await res.json()
  return data.keys as KeyStatus[]
}

// 키 저장(있으면 교체). provider = 'openai' | 'gemini' | 'compatible'
// compatible은 baseUrl(엔드포인트 주소)도 필요
export async function saveKey(provider: string, key: string, baseUrl?: string): Promise<void> {
  const res = await fetch(`${BASE}/ai/keys/${provider}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ key, base_url: baseUrl }),
  })
  if (res.status === 503) throw new Error('서버에 BYOK 암호화 키가 설정 안 됐어')
  if (res.status === 422) throw new Error('키 형식을 확인해줘 (10자 이상)')
  if (res.status === 400) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? '입력을 확인해줘')
  }
  if (!res.ok) throw new Error('키 저장에 실패했어')
}

// 키 삭제
export async function deleteKey(provider: string): Promise<void> {
  const res = await fetch(`${BASE}/ai/keys/${provider}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('키 삭제에 실패했어')
}

// 거친 메모 → AI가 정돈한 글 구조 마크다운. 로그인 필수(비용 보호).
// model 생략 시 서버 기본값. 커스텀(카탈로그에 없는) 모델이면 provider도 함께 보냄.
export async function generateDraft(memo: string, model?: string, provider?: string): Promise<string> {
  // 생성이 오래 걸려도 무한 대기하지 않게 90초 안전장치 → 명확한 메시지로 끝냄
  // (인앱 브라우저/네트워크가 응답을 끊고 멈춰버리는 것 방지)
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 90_000)
  let res: Response
  try {
    res = await fetch(`${BASE}/ai/draft`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ memo, model, provider }),
      signal: ctrl.signal,
    })
  } catch (e) {
    // 원본 에러를 cause로 보존해 디버깅 단서를 잃지 않게
    if (e instanceof DOMException && e.name === 'AbortError')
      throw new Error('생성이 너무 오래 걸려서 멈췄어. 더 짧은 메모로 다시 하거나 빠른 모델(Haiku)로 해줘', { cause: e })
    throw new Error('네트워크 문제로 초안 생성에 실패했어', { cause: e })
  } finally {
    clearTimeout(timer)
  }
  if (res.status === 401) throw new Error('로그인이 필요해')
  if (res.status === 403) throw new Error('이 모델을 쓸 권한이 없어 (결제 필요)')
  if (res.status === 429) {
    // 일일 캡(서버 detail) vs 레이트리밋(detail 없음 → 기본 문구) 구분해서 안내
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? 'AI 호출이 너무 잦아. 잠시 후 다시 해줘')
  }
  if (res.status === 503) throw new Error('AI 기능이 아직 설정 안 됐어 (서버에 API 키 필요)')
  if (!res.ok) throw new Error('AI 초안 생성에 실패했어')
  const data = await res.json()
  return data.markdown as string
}
