import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchNotifications, markAllRead, type NotificationList } from '../api/notifications'

// 헤더 알림 종 — 안 읽음 배지 + 드롭다운 목록. 열면 전부 읽음 처리.
export function NotificationBell() {
  const [data, setData] = useState<NotificationList>({ items: [], unread: 0 })
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // 안 읽음 수를 주기적으로 갱신(30초). 새 글 알림이 곧 배지로 뜬다.
  useEffect(() => {
    let alive = true
    const load = () =>
      fetchNotifications()
        .then((d) => {
          if (alive) setData(d)
        })
        .catch(() => {})
    load()
    const t = setInterval(load, 30000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  // 바깥을 클릭하면 드롭다운 닫기
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  async function toggleOpen() {
    const next = !open
    setOpen(next)
    // 열 때 안 읽음이 있으면 전부 읽음 처리(배지 사라짐)
    if (next && data.unread > 0) {
      await markAllRead()
      setData((d) => ({ unread: 0, items: d.items.map((i) => ({ ...i, read: true })) }))
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={toggleOpen}
        aria-label={`알림${data.unread > 0 ? ` (안 읽음 ${data.unread})` : ''}`}
        className="relative grid h-9 w-9 place-items-center rounded-full text-gray-600 transition hover:bg-black/[0.06] dark:text-gray-300 dark:hover:bg-white/10"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-5 w-5"
        >
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {data.unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
            {data.unread > 9 ? '9+' : data.unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 w-72 overflow-hidden rounded-xl border border-black/10 bg-white shadow-lg dark:border-white/10 dark:bg-[#1c1c1e]">
          <div className="border-b border-black/5 px-3 py-2 text-xs font-medium text-gray-500 dark:border-white/10 dark:text-gray-400">
            알림
          </div>
          {data.items.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-gray-400 dark:text-gray-500">
              새 알림이 없어
            </p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {data.items.map((n) => (
                <li key={n.id}>
                  <Link
                    to={`/blog/posts/${n.post_id}`}
                    onClick={() => setOpen(false)}
                    className="block px-3 py-2.5 text-sm hover:bg-black/[0.04] dark:hover:bg-white/5"
                  >
                    <div>
                      <span className="font-medium text-gray-800 dark:text-gray-100">{n.author}</span>
                      <span className="text-gray-500 dark:text-gray-400">님의 새 글</span>
                    </div>
                    <div className="truncate text-gray-600 dark:text-gray-300">{n.title}</div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
