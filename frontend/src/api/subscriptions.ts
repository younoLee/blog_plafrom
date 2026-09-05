import { authHeaders } from './auth'
import { apiFetch, failWith, fetchWithTimeout } from './http'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 이 블로그 주인(관리자) 정보 — '이 블로그 구독' 버튼이 이 id를 구독함
export interface BlogOwner {
  id: number | null
  name: string | null
}
export async function fetchBlogOwner(): Promise<BlogOwner> {
  const res = await fetchWithTimeout(`${BASE}/blog-owner`)
  if (!res.ok) return { id: null, name: null }
  return res.json()
}

// 내가 구독(신청)한 글쓴이 — /detail은 approved+notify 포함, /authors는 미포함
export interface SubscribedAuthor {
  id: number
  name: string
  approved?: boolean // 글쓴이가 승인했는지 (false=승인 대기)
  notify?: boolean
}

// 나(글쓴이)에게 온 구독 신청 (승인 대기)
export interface PendingRequest {
  id: number // 신청한 사용자 id
  name: string
}
export async function fetchRequests(): Promise<PendingRequest[]> {
  const res = await fetchWithTimeout(`${BASE}/subscriptions/requests`, { headers: authHeaders() })
  if (!res.ok) return []
  return res.json()
}
export async function approveRequest(subscriberId: number): Promise<void> {
  const res = await apiFetch(`${BASE}/subscriptions/requests/${subscriberId}/approve`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) await failWith(res, '승인 실패')
}
export async function rejectRequest(subscriberId: number): Promise<void> {
  const res = await apiFetch(`${BASE}/subscriptions/requests/${subscriberId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) await failWith(res, '거절 실패')
}

// 구독한 글쓴이의 새 글 이메일 알림 켜기/끄기 (구독한 뒤에만 가능 — 아니면 404)
export async function setNotify(authorId: number, notify: boolean): Promise<void> {
  const res = await apiFetch(`${BASE}/subscriptions/${authorId}/notify`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ notify }),
  })
  if (!res.ok) await failWith(res, '알림 설정 실패')
}
export async function fetchMySubscriptionsDetail(): Promise<SubscribedAuthor[]> {
  const res = await fetchWithTimeout(`${BASE}/subscriptions/detail`, { headers: authHeaders() })
  if (!res.ok) return []
  return res.json()
}

// 구독할 수 있는 글쓴이 목록 (writer/admin, 나 제외)
// 이 파일의 다른 조회는 전부 fetchWithTimeout인데 여기만 맨 fetch였다 → 8초 규칙 밖이라
// 서버가 꺼져 있으면 CloudFront 오리진 상한 60초까지 매달렸다. 호출부가 실패를 []로
// 삼키므로(SubscriptionsPage) 화면엔 "구독할 수 있는 다른 글쓴이가 아직 없어"가 뜬다 —
// 1분을 기다린 끝에 **거짓 사실**을 보는 셈이었다. (2026-08-11 공백검사)
//
// 그때 줄인 건 기다리는 시간뿐이고 **거짓 문장은 그대로 남아 있었다**(09-04 검사 FE-5).
// `[]`는 '없다'는 사실 주장인데 실패는 '모른다'다. 둘을 같은 값으로 돌려주면 호출부가
// 아무리 잘 짜도 가를 수 없으므로, 여기서 던진다 — 이 저장소가 목록 화면에서 이미
// 세워둔 규칙이다(HomePage의 loaded 주석: "0개는 사실 주장이다").
export async function fetchAuthors(): Promise<SubscribedAuthor[]> {
  const res = await fetchWithTimeout(`${BASE}/subscriptions/authors`, { headers: authHeaders() })
  if (!res.ok) await failWith(res, '글쓴이 목록을 불러오지 못했어')
  return res.json()
}

// 내가 구독 중인 글쓴이 id 목록
export async function fetchMySubscriptions(): Promise<number[]> {
  const res = await fetchWithTimeout(`${BASE}/subscriptions`, { headers: authHeaders() })
  if (!res.ok) return []
  return res.json()
}

export async function subscribeAuthor(authorId: number): Promise<void> {
  const res = await apiFetch(`${BASE}/subscriptions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ author_id: authorId }),
  })
  if (!res.ok) await failWith(res, '구독 실패')
}

export async function unsubscribeAuthor(authorId: number): Promise<void> {
  const res = await apiFetch(`${BASE}/subscriptions/${authorId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) await failWith(res, '구독 해제 실패')
}
