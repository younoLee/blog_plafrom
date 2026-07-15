const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'
const TOKEN_KEY = 'token'

// 권한: pending(승인 대기) / writer(글쓰기 가능) / admin(관리자) / banned(차단)
export type Role = 'pending' | 'writer' | 'admin' | 'banned'

export interface User {
  id: number
  email: string
  role: Role
  is_pro: boolean // 유료(고급 AI 모델 해금) 여부
  pro_until?: string | null // 구독 만료 시각(ISO). 없으면 null
  created_at: string
}

// 글쓰기 가능한 권한인지 (writer나 admin)
export function canWrite(user: User | null): boolean {
  return user?.role === 'writer' || user?.role === 'admin'
}

// --- 토큰 저장/조회 (localStorage) ---
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// 로그인했으면 Authorization 헤더, 아니면 빈 객체 (다른 api에서 가져다 씀)
export function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

// --- 인증 요청 ---
export async function register(email: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  // 기존 이메일도 409로 안 흘림(enumeration 방지) → 신규/기존 모두 동일하게 성공 화면.
  // 실제 안내(인증/이미가입)는 메일로만 감.
  if (res.status === 422) throw new Error('이메일 형식·비밀번호(8~72자)를 확인해줘')
  if (res.status === 429) throw new Error('가입 시도가 너무 많아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('회원가입 실패')
}

// 메일 링크의 토큰으로 이메일 인증 처리
export async function verifyEmail(token: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/verify?token=${encodeURIComponent(token)}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('유효하지 않거나 만료된 인증 링크야')
}

// 비밀번호 재설정 요청 (재설정 링크 메일 발송)
export async function forgotPassword(email: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (res.status === 429) throw new Error('요청이 너무 많아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('요청에 실패했어')
}

// 메일 링크의 토큰으로 새 비밀번호 설정
export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, new_password: newPassword }),
  })
  if (!res.ok) throw new Error('유효하지 않거나 만료된 링크야')
}

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (res.status === 401) throw new Error('이메일 또는 비밀번호가 틀렸어')
  // 403 = 미인증/차단 (백엔드 메시지 그대로 보여줌), 429 = 너무 잦은 시도
  if (res.status === 403) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? '로그인할 수 없는 계정이야')
  }
  if (res.status === 429) throw new Error('로그인 시도가 너무 많아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('로그인 실패')
  const data = await res.json()
  setToken(data.access_token)
}

export async function fetchMe(): Promise<User | null> {
  const t = getToken()
  if (!t) return null
  const res = await fetch(`${BASE}/auth/me`, { headers: authHeaders() })
  // 401(만료/위조)일 때만 토큰 정리. 5xx 같은 일시적 서버 오류엔 토큰을 지우지 않음
  // (안 그러면 서버가 잠깐 흔들릴 때 사용자가 강제 로그아웃돼 재로그인해야 함)
  if (res.status === 401) {
    clearToken()
    return null
  }
  if (!res.ok) return null // 일시 오류: 토큰 유지, 다음 새로고침에 복구
  return res.json()
}
