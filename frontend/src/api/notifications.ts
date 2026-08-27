import { authHeaders } from './auth'
import { apiFetch, fetchWithTimeout } from './http'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

export interface NotificationItem {
  id: number
  // **null 이면 글에 안 매인 알림**(구독 신청). 2026-08-27부터 nullable 이다.
  // 종류는 어느 칸이 채워졌는가로 가른다(backend models/notification.py):
  //   post_id 있음 + comment_id 없음 → 새 글
  //   post_id 있음 + comment_id 있음 → 새 댓글
  //   post_id 없음                   → 구독 신청
  post_id: number | null
  title: string | null
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
