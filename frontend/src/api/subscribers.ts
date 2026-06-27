import { authHeaders } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 이메일 구독자 한 명 (관리자 목록용)
export interface SubscriberRow {
  id: number
  email: string
  created_at: string
}

// 구독 등록. 성공 시 등록된 구독자 반환, 실패 시 상태별 메시지로 에러
export async function subscribe(email: string): Promise<void> {
  const res = await fetch(`${BASE}/subscribers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (res.status === 409) throw new Error('이미 구독 중인 이메일이야')
  if (res.status === 422) throw new Error('이메일 형식이 올바르지 않아')
  if (!res.ok) throw new Error('구독 실패')
}

// 이메일로 구독 취소 (누구나, 본인확인 없이). 존재 여부는 서버가 노출 안 함
export async function unsubscribeEmail(email: string): Promise<void> {
  const res = await fetch(`${BASE}/subscribers/unsubscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (res.status === 422) throw new Error('이메일 형식이 올바르지 않아')
  if (res.status === 429) throw new Error('요청이 너무 잦아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('구독 취소 실패')
}

// 이메일 구독자 목록 (관리자 전용). 권한 없으면 빈 배열
export async function fetchSubscribers(): Promise<SubscriberRow[]> {
  const res = await fetch(`${BASE}/subscribers`, { headers: authHeaders() })
  if (!res.ok) return []
  return res.json()
}

// 이메일 구독자 삭제 (관리자 전용)
export async function deleteSubscriber(id: number): Promise<void> {
  const res = await fetch(`${BASE}/subscribers/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('구독자 삭제 실패')
}
