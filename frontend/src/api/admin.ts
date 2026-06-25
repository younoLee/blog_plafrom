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

// 영구 삭제: 계정 + 그 사람의 글·댓글까지 (되돌리기 불가)
export async function deleteUser(id: number): Promise<void> {
  const res = await fetch(`${BASE}/admin/users/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('삭제에 실패했어')
}
