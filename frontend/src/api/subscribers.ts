import { authHeaders } from './auth'

// 이메일 뉴스레터 구독은 2026-07-31에 폐지됐다(backend routers/subscribers.py의 사유 참고).
// 새 글 알림은 계정 구독(api/subscriptions.ts)이 담당한다. 여기 남은 건 관리자가
// 폐지 전에 쌓인 구독자 주소(개인정보)를 확인하고 지우는 경로뿐이다.
//
// 지운 것: subscribe · confirmSubscription · unsubscribeEmail
//          fetchMySubscription · subscribeMe · unsubscribeMe

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 이메일 구독자 한 명 (관리자 목록용)
export interface SubscriberRow {
  id: number
  email: string
  confirmed: boolean // 폐지 전 더블옵트인 확인 여부 (false면 '확인 대기'였던 것)
  created_at: string
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
