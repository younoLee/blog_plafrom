import { authHeaders } from './auth'
import { apiFetch, fetchWithTimeout } from './http'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

export interface NotificationItem {
  id: number
  // **null 이면 글에 안 매인 알림**(구독 신청). 2026-08-27부터 nullable 이다.
  // 종류는 어느 칸이 채워졌는가로 가른다(backend models/notification.py):
  //   post_id 있음 + comment_id 없음 → 새 글
  //   post_id 있음 + comment_id 있음 → 새 댓글
  //   post_id 없음                   → 아래 kind 가 가른다
  post_id: number | null
  title: string | null
  /** 이 알림을 일으킨 사람 — 새 글이면 글쓴이, 새 댓글이면 댓글 쓴 사람. */
  author: string
  read: boolean
  created_at: string
  /** 값이 있으면 '새 댓글' 알림, null이면 '새 글' 알림. */
  comment_id?: number | null
  /**
   * **post_id 가 null 일 때만 읽는다.** 글에 안 매인 알림이 둘이다(2026-09-05):
   *   'subscribe_request'  → 내가 글쓴이다. 눌러서 승인·거절한다.
   *   'subscribe_approved' → 내 신청이 승인됐다. 이제 구독자공개 글이 열린다.
   * 둘은 서버에서 모양이 완전히 같아서(post_id 없음 + actor) 이 값 없이는 못 가른다 —
   * 없으면 신청자에게 '눌러서 승인하거나 거절할 수 있어'가 뜬다(09-04 검사 GAP-3).
   * 옛 행은 null 일 수 있고, 그때는 '구독 신청'으로 읽는다(그 종류밖에 없었다).
   */
  kind?: string | null
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
