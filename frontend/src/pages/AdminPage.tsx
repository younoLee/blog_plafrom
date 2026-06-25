import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { listUsers, approveUser, revokeUser, banUser, unbanUser } from '../api/admin'
import type { User, Role } from '../api/auth'
import { ui } from '../ui'

// role별 한글 라벨 + 뱃지 색
const ROLE_META: Record<Role, { label: string; badge: string }> = {
  pending: { label: '승인 대기', badge: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300' },
  writer: { label: '글쓰기 가능', badge: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' },
  admin: { label: '관리자', badge: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300' },
  banned: { label: '차단됨', badge: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300' },
}

// 액션 → 호출할 API 함수
const ACTIONS = { approve: approveUser, revoke: revokeUser, ban: banUser, unban: unbanUser }

function AdminPage() {
  const { user, loading } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [error, setError] = useState('')

  // 가입자 목록 불러오기 (관리자일 때만)
  useEffect(() => {
    if (user?.role !== 'admin') return
    listUsers().then(setUsers).catch((e) => setError(e.message))
  }, [user])

  // 로그인 상태 복구 중에는 잠깐 대기
  if (loading) return null
  // 관리자가 아니면 접근 불가 → 블로그로 보냄
  if (user?.role !== 'admin') return <Navigate to="/blog" replace />

  // 승인/해제/차단 후 그 사용자만 목록에서 갱신
  async function handle(id: number, action: keyof typeof ACTIONS) {
    try {
      const updated = await ACTIONS[action](id)
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
    } catch (e) {
      setError(e instanceof Error ? e.message : '처리 실패')
    }
  }

  return (
    <div>
      <h1 className={`text-3xl font-bold tracking-tight ${ui.gradientText}`}>관리자</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
        가입자를 승인하면 글을 쓸 수 있어. 승인 취소하면 다시 막혀(기존 글은 남음).
      </p>

      {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

      <ul className="mt-6 space-y-3">
        {users.map((u) => {
          const meta = ROLE_META[u.role]
          return (
            <li key={u.id} className={`${ui.card} flex items-center justify-between gap-3`}>
              <div className="min-w-0">
                <p className="truncate font-medium">{u.email}</p>
                <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${meta.badge}`}>
                  {meta.label}
                </span>
              </div>
              {/* admin은 변경 불가. pending=승인+차단, writer=해제+차단, banned=해제 */}
              <div className="flex shrink-0 gap-2">
                {u.role === 'pending' && (
                  <button type="button" onClick={() => handle(u.id, 'approve')} className={ui.btnPrimary}>
                    승인
                  </button>
                )}
                {u.role === 'writer' && (
                  <button type="button" onClick={() => handle(u.id, 'revoke')} className={ui.btnGhost}>
                    승인 취소
                  </button>
                )}
                {(u.role === 'pending' || u.role === 'writer') && (
                  <button
                    type="button"
                    onClick={() => handle(u.id, 'ban')}
                    className="rounded-full px-4 py-2 text-sm font-medium text-red-600 transition hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-500/10"
                  >
                    차단
                  </button>
                )}
                {u.role === 'banned' && (
                  <button type="button" onClick={() => handle(u.id, 'unban')} className={ui.btnPrimary}>
                    차단 해제
                  </button>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default AdminPage
