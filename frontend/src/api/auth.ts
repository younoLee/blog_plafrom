const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'
const TOKEN_KEY = 'token'

// 권한: pending(승인 대기) / writer(글쓰기 가능) / admin(관리자) / banned(차단)
export type Role = 'pending' | 'writer' | 'admin' | 'banned'

export interface User {
  id: number
  email: string
  role: Role
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
  if (res.status === 409) throw new Error('이미 가입된 이메일이야')
  if (res.status === 422) throw new Error('이메일 형식이 올바르지 않아')
  if (!res.ok) throw new Error('회원가입 실패')
}

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (res.status === 401) throw new Error('이메일 또는 비밀번호가 틀렸어')
  if (!res.ok) throw new Error('로그인 실패')
  const data = await res.json()
  setToken(data.access_token)
}

export async function fetchMe(): Promise<User | null> {
  const t = getToken()
  if (!t) return null
  const res = await fetch(`${BASE}/auth/me`, { headers: authHeaders() })
  if (!res.ok) {
    clearToken() // 만료/위조 토큰이면 정리
    return null
  }
  return res.json()
}
