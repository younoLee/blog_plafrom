import { authHeaders } from './auth'
import { fetchWithTimeout } from './http'

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
  const res = await fetchWithTimeout(`${BASE}/ai/models`, { headers: authHeaders() })
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
  const res = await fetchWithTimeout(`${BASE}/ai/usage`, { headers: authHeaders() })
  if (!res.ok) throw new Error('사용량을 불러오지 못했어')
  return res.json()
}

// 내 BYOK 키 등록 현황 (값은 안 내려옴 — 있다/없다만)
export async function fetchKeys(): Promise<KeyStatus[]> {
  const res = await fetchWithTimeout(`${BASE}/ai/keys`, { headers: authHeaders() })
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
  if (res.status === 503) {
    // **서버 문구를 그대로 쓴다.** 백엔드는 서로 다른 503을 **셋** 낸다:
    //   ① 서버 키 없음  ② BYOK 복호화 실패 → "설정에서 키를 **다시 등록**해줘"
    //   ③ 업스트림 도달 실패 → "잠시 후 다시 시도해줘"
    // 예전엔 이 한 줄이 셋을 전부 "서버에 API 키 필요"로 덮었다. ②는 사용자가 할 일이
    // 정확히 있는 상태인데 그 안내가 화면에 도달하지 않았고, ③은 엉뚱한 곳을 고치라고
    // 시켰다 — 07-28 카오스 훈련이 백엔드에서 잡아 고친 그 병이 프론트에 남아 있었다.
    // (2026-08-11 동료 리뷰. 이게 '501 분리'보다 값이 큰 수정이라는 게 변론의 결론)
    const d = await res.json().catch(() => null)
    throw new Error(
      typeof d?.detail === 'string' ? d.detail : 'AI 기능이 아직 설정 안 됐어 (서버에 API 키 필요)',
    )
  }
  if (res.status === 422) {
    // 서버 가드에 걸렸거나(출력이 초안 형식이 아님·프롬프트 유출 의심) 입력 검증 실패.
    // FastAPI의 요청 검증 실패도 422인데 그쪽 detail은 **배열**이라 그대로 쓰면
    // "[object Object]"가 뜬다 → 문자열일 때만 서버 문구를 쓴다.
    const d = await res.json().catch(() => null)
    throw new Error(typeof d?.detail === 'string' ? d.detail : '메모를 다시 확인해줘')
  }
  if (!res.ok) throw new Error('AI 초안 생성에 실패했어')
  const data = await res.json()
  return data.markdown as string
}
