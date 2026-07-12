import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { listUsers, approveUser, revokeUser, banUser, unbanUser, deleteUser, toggleProUser, fetchInfra, type InfraStatus } from '../api/admin'
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
const ACTIONS = { approve: approveUser, revoke: revokeUser, ban: banUser, unban: unbanUser, pro: toggleProUser }

// 서버 부하 미터: 값에 따라 초록(<60)/노랑(<85)/빨강(>=85)
function Meter({ label, percent, detail }: { label: string; percent: number; detail: string }) {
  const p = Math.min(100, Math.max(0, Math.round(percent)))
  const color = p >= 85 ? 'bg-red-500' : p >= 60 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className={ui.card}>
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-gray-600 dark:text-gray-300">{label}</span>
        <span className="text-lg font-semibold tracking-tight">{p}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-black/[0.06] dark:bg-white/10">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${p}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">{detail}</p>
    </div>
  )
}

function formatUptime(s: number): string {
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  return d > 0 ? `${d}일 ${h}시간` : h > 0 ? `${h}시간 ${m}분` : `${m}분`
}

function AdminPage() {
  const { user, loading } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [infra, setInfra] = useState<InfraStatus | null>(null)
  const [error, setError] = useState('')

  // 가입자 목록 불러오기 (관리자일 때만)
  useEffect(() => {
    if (user?.role !== 'admin') return
    listUsers().then(setUsers).catch((e) => setError(e.message))
  }, [user])

  // 인프라 상태: 10초마다 폴링 (관리자일 때만)
  useEffect(() => {
    if (user?.role !== 'admin') return
    let alive = true
    const load = () => fetchInfra().then((d) => alive && setInfra(d)).catch(() => {})
    load()
    const t = setInterval(load, 10000)
    return () => {
      alive = false
      clearInterval(t)
    }
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

  // 영구 삭제 (글·댓글까지) — 되돌릴 수 없으니 확인창
  async function handleDelete(id: number, email: string) {
    if (!window.confirm(`정말 ${email} 계정을 삭제할까?\n이 사람의 글·댓글도 영구 삭제되고 되돌릴 수 없어.`)) return
    try {
      await deleteUser(id)
      setUsers((prev) => prev.filter((u) => u.id !== id))
    } catch (e) {
      setError(e instanceof Error ? e.message : '삭제 실패')
    }
  }

  return (
    <div>
      <h1 className={`text-3xl font-bold tracking-tight ${ui.gradientText}`}>관리자</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
        가입자를 승인하면 글을 쓸 수 있어. 승인 취소하면 다시 막혀(기존 글은 남음).
      </p>

      {/* 인프라 상태 대시보드 (서버 EC2 + DB 실측, 10초 폴링). 관리자만 봄 */}
      {infra && (
        <section className="mt-6">
          <h2 className="mb-3 flex items-baseline gap-2 text-xl font-semibold tracking-tight">
            인프라 상태
            <span className="text-xs font-normal text-gray-400 dark:text-gray-500">서버·DB 실측 · 10초마다 갱신</span>
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Meter label="CPU" percent={infra.cpu_percent} detail={`부하 ${infra.load_avg['1m']} · ${infra.cpu_count}코어`} />
            <Meter label="메모리" percent={infra.memory.percent} detail={`${infra.memory.used_mb} / ${infra.memory.total_mb} MB`} />
            <Meter label="디스크" percent={infra.disk.percent} detail={`${infra.disk.used_gb} / ${infra.disk.total_gb} GB`} />
            <Meter
              label="DB 커넥션"
              percent={infra.db.max_connections ? ((infra.db.connections ?? 0) / infra.db.max_connections) * 100 : 0}
              detail={infra.db.connections != null ? `${infra.db.connections} / ${infra.db.max_connections}` : '조회 불가'}
            />
          </div>
          <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">서버 가동시간: {formatUptime(infra.uptime_seconds)}</p>
        </section>
      )}

      {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

      <h2 className="mb-3 mt-8 text-xl font-semibold tracking-tight">가입자 관리</h2>
      <ul className="space-y-3">
        {users.map((u) => {
          const meta = ROLE_META[u.role]
          return (
            <li key={u.id} className={`${ui.card} flex items-center justify-between gap-3`}>
              <div className="min-w-0">
                <p className="truncate font-medium">{u.email}</p>
                <span className={`mt-1 mr-1 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${meta.badge}`}>
                  {meta.label}
                </span>
                {u.is_pro && (
                  <span className="mt-1 inline-block rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-500/15 dark:text-violet-300">
                    유료(Opus)
                  </span>
                )}
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
                {/* admin은 이미 전 모델 사용 가능 → 그 외 계정에만 유료 토글 */}
                {u.role !== 'admin' && (
                  <button type="button" onClick={() => handle(u.id, 'pro')} className={ui.btnGhost}>
                    {u.is_pro ? '유료 회수' : '유료 부여'}
                  </button>
                )}
                {/* admin 외 모든 계정에 영구 삭제 버튼 */}
                {u.role !== 'admin' && (
                  <button
                    type="button"
                    onClick={() => handleDelete(u.id, u.email)}
                    className="rounded-full px-4 py-2 text-sm font-medium text-red-600 transition hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-500/10"
                  >
                    삭제
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
