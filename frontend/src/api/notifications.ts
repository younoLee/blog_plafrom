import { authHeaders } from './auth'
import { apiFetch, fetchWithTimeout } from './http'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

export interface NotificationItem {
  id: number
  post_id: number
  title: string
  /** 이 알림을 일으킨 사람 — 새 글이면 글쓴이, 새 댓글이면 댓글 쓴 사람. */
  author: string
  read: boolean
  created_at: string
  /** 값이 있으면 '새 댓글' 알림, null이면 '새 글' 알림. */
  comment_id?: number | null
}
export interface NotificationList {
  items: NotificationItem[]
  unread: number
}

export async function fetchNotifications(): Promise<NotificationList> {
  const res = await fetchWithTimeout(`${BASE}/notifications`, { headers: authHeaders() })
  if (!res.ok) return { items: [], unread: 0 }
  return res.json()
}

export async function markAllRead(): Promise<void> {
  await apiFetch(`${BASE}/notifications/read`, { method: 'POST', headers: authHeaders() })
}
