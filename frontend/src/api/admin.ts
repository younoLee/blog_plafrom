import { authHeaders, type User } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 가입자 전원 목록 (관리자만 호출 가능 — 백엔드가 require_admin으로 검사)
export async function listUsers(): Promise<User[]> {
  const res = await fetch(`${BASE}/admin/users`, { headers: authHeaders() })
  if (!res.ok) throw new Error('가입자 목록을 불러오지 못했어')
  return res.json()
}

// 승인: pending → writer (글쓰기 허용)
export async function approveUser(id: number): Promise<User> {
  const res = await fetch(`${BASE}/admin/users/${id}/approve`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('승인에 실패했어')
  return res.json()
}

// 승인 취소: writer → pending (글쓰기 차단)
export async function revokeUser(id: number): Promise<User> {
  const res = await fetch(`${BASE}/admin/users/${id}/revoke`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('승인 취소에 실패했어')
  return res.json()
}

// 차단: role → banned (로그인·토큰 무효)
export async function banUser(id: number): Promise<User> {
  const res = await fetch(`${BASE}/admin/users/${id}/ban`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('차단에 실패했어')
  return res.json()
}

// 차단 해제: banned → pending
export async function unbanUser(id: number): Promise<User> {
  const res = await fetch(`${BASE}/admin/users/${id}/unban`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('차단 해제에 실패했어')
  return res.json()
}

// 유료(pro) 토글: AI 초안에서 Opus 등 상위 모델 해금/회수
export async function toggleProUser(id: number): Promise<User> {
  const res = await fetch(`${BASE}/admin/users/${id}/toggle-pro`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('유료 토글에 실패했어')
  return res.json()
}

// 영구 삭제: 계정 + 그 사람의 글·댓글까지 (되돌리기 불가)
export async function deleteUser(id: number): Promise<void> {
  const res = await fetch(`${BASE}/admin/users/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('삭제에 실패했어')
}

// --- 초대 (초대제 가입의 실제 절차) ---

export interface Invite {
  id: number
  email: string
  role: 'pending' | 'writer'
  created_at: string
  expires_at: string
  used_at: string | null
  // 누가 발급했고 누가 그 링크로 들어왔는지. 발급자·가입계정이 지워졌으면 null
  // (FK가 SET NULL이라 초대 기록 자체는 남는다).
  created_by_email: string | null
  used_by_email: string | null
}

// 발급 응답에만 url이 실린다. 서버는 토큰 해시만 저장하므로 이 값은 다시 볼 수 없다.
export interface InviteCreated extends Invite {
  url: string
}

export async function listInvites(): Promise<Invite[]> {
  const res = await fetch(`${BASE}/admin/invites`, { headers: authHeaders() })
  if (!res.ok) throw new Error('초대 목록을 불러오지 못했어')
  return res.json()
}

export async function createInvite(
  email: string,
  role: 'pending' | 'writer',
): Promise<InviteCreated> {
  const res = await fetch(`${BASE}/admin/invites`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, role }),
  })
  // 400=이미 가입된 주소, 409=아직 안 쓴 초대가 남아 있음 — 둘 다 관리자에겐
  // 그대로 알려주는 게 맞다(가입자 목록을 볼 수 있는 사람이라 노출될 정보가 없다).
  if (res.status === 400 || res.status === 409) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? '초대를 발급하지 못했어')
  }
  if (res.status === 422) throw new Error('이메일 형식을 확인해줘')
  if (!res.ok) throw new Error('초대를 발급하지 못했어')
  return res.json()
}

export async function revokeInvite(id: number): Promise<void> {
  const res = await fetch(`${BASE}/admin/invites/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('초대를 취소하지 못했어')
}

// 관리자 인프라 대시보드: 서버(EC2)+DB 실측 지표
export interface InfraStatus {
  cpu_percent: number
  cpu_count: number
  load_avg: { '1m': number; '5m': number; '15m': number }
  memory: { percent: number; used_mb: number; total_mb: number }
  disk: { percent: number; used_gb: number; total_gb: number }
  uptime_seconds: number
  db: { connections: number | null; max_connections: number | null }
}

export async function fetchInfra(): Promise<InfraStatus> {
  const res = await fetch(`${BASE}/admin/infra`, { headers: authHeaders() })
  if (!res.ok) throw new Error('인프라 상태를 불러오지 못했어')
  return res.json()
}
