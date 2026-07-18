import { authHeaders } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

export interface NotificationItem {
  id: number
  post_id: number
  title: string
  author: string
  read: boolean
  created_at: string
}
export interface NotificationList {
  items: NotificationItem[]
  unread: number
}

export async function fetchNotifications(): Promise<NotificationList> {
  const res = await fetch(`${BASE}/notifications`, { headers: authHeaders() })
  if (!res.ok) return { items: [], unread: 0 }
  return res.json()
}

export async function markAllRead(): Promise<void> {
  await fetch(`${BASE}/notifications/read`, { method: 'POST', headers: authHeaders() })
}
