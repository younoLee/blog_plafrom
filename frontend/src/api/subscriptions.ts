import { authHeaders } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 이 블로그 주인(관리자) 정보 — '이 블로그 구독' 버튼이 이 id를 구독함
export interface BlogOwner {
  id: number | null
  name: string | null
}
export async function fetchBlogOwner(): Promise<BlogOwner> {
  const res = await fetch(`${BASE}/blog-owner`)
  if (!res.ok) return { id: null, name: null }
  return res.json()
}

// 내가 구독 중인 글쓴이 (id + 이름) — '구독 중인 블로그' 목록용
export interface SubscribedAuthor {
  id: number
  name: string
}
export async function fetchMySubscriptionsDetail(): Promise<SubscribedAuthor[]> {
  const res = await fetch(`${BASE}/subscriptions/detail`, { headers: authHeaders() })
  if (!res.ok) return []
  return res.json()
}

// 구독할 수 있는 글쓴이 목록 (writer/admin, 나 제외)
export async function fetchAuthors(): Promise<SubscribedAuthor[]> {
  const res = await fetch(`${BASE}/subscriptions/authors`, { headers: authHeaders() })
  if (!res.ok) return []
  return res.json()
}

// 내가 구독 중인 글쓴이 id 목록
export async function fetchMySubscriptions(): Promise<number[]> {
  const res = await fetch(`${BASE}/subscriptions`, { headers: authHeaders() })
  if (!res.ok) return []
  return res.json()
}

export async function subscribeAuthor(authorId: number): Promise<void> {
  const res = await fetch(`${BASE}/subscriptions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ author_id: authorId }),
  })
  if (!res.ok) throw new Error('구독 실패')
}

export async function unsubscribeAuthor(authorId: number): Promise<void> {
  const res = await fetch(`${BASE}/subscriptions/${authorId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('구독 해제 실패')
}
