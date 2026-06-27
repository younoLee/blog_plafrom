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
  const res = await fetch(`${BASE}/ai/draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ memo, model, provider }),
  })
  if (res.status === 401) throw new Error('로그인이 필요해')
  if (res.status === 403) throw new Error('이 모델을 쓸 권한이 없어 (결제 필요)')
  if (res.status === 429) throw new Error('AI 호출이 너무 잦아. 잠시 후 다시 해줘')
  if (res.status === 503) throw new Error('AI 기능이 아직 설정 안 됐어 (서버에 API 키 필요)')
  if (!res.ok) throw new Error('AI 초안 생성에 실패했어')
  const data = await res.json()
  return data.markdown as string
}
