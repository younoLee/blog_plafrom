import { authHeaders } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 이메일 구독자 한 명 (관리자 목록용)
export interface SubscriberRow {
  id: number
  email: string
  confirmed: boolean // 더블옵트인 확인 여부 (false면 '확인 대기')
  created_at: string
}

// 구독 신청 → 서버가 '확인 메일'을 보냄(더블옵트인). 링크를 눌러야 구독 완료.
// 응답은 신규/기존 구분 없이 동일 → 그 이메일의 구독 여부가 노출되지 않음.
export async function subscribe(email: string): Promise<void> {
  const res = await fetch(`${BASE}/subscribers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (res.status === 422) throw new Error('이메일 형식이 올바르지 않아')
  if (res.status === 429) throw new Error('요청이 너무 잦아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('구독 실패')
}

// 확인메일 링크의 토큰으로 구독 확정
export async function confirmSubscription(token: string): Promise<void> {
  const res = await fetch(
    `${BASE}/subscribers/confirm?token=${encodeURIComponent(token)}`,
    { method: 'POST' },
  )
  if (!res.ok) throw new Error('구독 확인 실패')
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

// 내 계정 이메일의 구독 상태 (로그인 필요). '새 글 알림' 잠금 판단용
export interface MySubscription {
  email: string
  subscribed: boolean
}
export async function fetchMySubscription(): Promise<MySubscription | null> {
  const res = await fetch(`${BASE}/subscribers/me`, { headers: authHeaders() })
  if (!res.ok) return null
  return res.json()
}

// 내 계정 이메일로 구독 (로그인 필요). 확인메일 없이 즉시 구독 완료
export async function subscribeMe(): Promise<MySubscription> {
  const res = await fetch(`${BASE}/subscribers/me`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('구독 실패')
  return res.json()
}

// 내 계정 이메일 구독 해제 (로그인 필요)
export async function unsubscribeMe(): Promise<void> {
  const res = await fetch(`${BASE}/subscribers/me`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('구독 해제 실패')
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
