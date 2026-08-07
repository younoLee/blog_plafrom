import { fetchWithTimeout } from './http'

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

// --- 초대제 가입 ---
// 열린 가입(register)과 달리 이쪽은 실패 사유를 분명히 말해줘야 쓸 수 있다.
// register는 enumeration 방지로 신규/기존을 안 가리고 항상 성공처럼 응답하지만,
// 초대는 유효한 토큰을 쥔 사람만 오므로 숨길 게 없다.

export interface InvitePreview {
  email: string
  role: Role
}

/** 초대 링크의 토큰으로 '어떤 주소로 가입되는지'를 확인. 무효/만료/사용됨은 전부 null.
 *
 * 읽기인데 POST인 건 서버 사정이다 — 토큰이 자격증명이라 URL에 실으면 액세스 로그에
 * 평문으로 남는다. 본문으로 보내면 안 남는다. */
export async function previewInvite(token: string): Promise<InvitePreview | null> {
  const res = await fetchWithTimeout(`${BASE}/auth/invite`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (res.status === 404) return null // 서버가 셋을 구분해주지 않는다(오라클 방지)
  if (!res.ok) throw new Error('초대 정보를 확인하지 못했어')
  return res.json()
}

/** 초대 토큰 소각 + 계정 생성. 성공하면 그대로 로그인 상태가 된다(토큰 저장).
 *
 * **여기엔 fetchWithTimeout을 쓰지 않는다.** abort는 내 기다림만 끊을 뿐 서버 일을
 * 되돌리지 않는다 — 8초에 끊어도 소각과 계정 생성은 그대로 끝난다. 그러면 상대는
 * "서버가 절전 중"을 보고 새로고침하고, 이번엔 "더 이상 쓸 수 없는 링크"를 만난다.
 * 1회용이라 그걸로 끝이고 관리자만 되살릴 수 있다. 하필 갓 건넨 링크를 누르는 순간이
 * 오리진이 차가울 확률이 제일 높은 때다(거기에 bcrypt까지 얹힌다).
 * 이 저장소가 읽기에만 타임아웃을 거는 것도 같은 이유다(api/http.ts). */
export async function redeemInvite(token: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/register/invite`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, password }),
  })
  if (res.status === 422) throw new Error('비밀번호는 8~72자로 정해줘')
  if (res.status === 429) throw new Error('시도가 너무 많아. 잠시 후 다시 해줘')
  if (res.status === 400) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? '이 초대 링크는 더 이상 쓸 수 없어')
  }
  if (!res.ok) throw new Error('가입에 실패했어')
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
