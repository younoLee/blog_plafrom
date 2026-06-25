import { useEffect, useState } from 'react'
import {
  fetchStatus,
  fetchHistory,
  type StatusInfo,
  type UptimeHistory,
  type ServiceUptime,
} from '../api/status'
import { ui } from '../ui'

// 서비스 한 줄 표시 (이름 + 초록/빨강 점 + 정상/중단)
function ServiceRow({ name, ok }: { name: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between border-b border-gray-100 py-3 last:border-0 dark:border-gray-700">
      <span className="font-medium text-gray-800 dark:text-gray-100">{name}</span>
      <span className="flex items-center gap-2">
        <span
          className={`h-2.5 w-2.5 rounded-full ${ok ? 'bg-green-500' : 'bg-red-500'}`}
        />
        <span
          className={`text-sm font-medium ${ok ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}
        >
          {ok ? '정상' : '중단'}
        </span>
      </span>
    </div>
  )
}

// 업타임 비율 → 막대 색 (null=데이터 없음=회색)
function uptimeColor(u: number | null): string {
  if (u === null) return 'bg-gray-200 dark:bg-gray-700'
  if (u >= 0.999) return 'bg-green-500'
  if (u >= 0.95) return 'bg-amber-400'
  return 'bg-red-500'
}

function pct(u: number | null): string {
  return u === null ? '데이터 없음' : (u * 100).toFixed(1) + '%'
}

// 서비스 한 개의 업타임 줄: 라벨 + 전체 % + 날짜별 막대
function UptimeRow({ service }: { service: ServiceUptime }) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
          {service.label}
        </span>
        <span className="text-sm font-bold text-green-600 dark:text-green-400">
          {service.overall_uptime === null
            ? '—'
            : (service.overall_uptime * 100).toFixed(2) + '%'}
        </span>
      </div>
      <div className="mt-1.5 flex items-end gap-[2px]">
        {service.days.map((d) => (
          <div
            key={d.date}
            title={`${d.date} · ${pct(d.uptime)}`}
            className={`h-7 flex-1 rounded-sm ${uptimeColor(d.uptime)}`}
          />
        ))}
      </div>
    </div>
  )
}

function StatusPage() {
  const [status, setStatus] = useState<StatusInfo | null>(null)
  const [history, setHistory] = useState<UptimeHistory | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 새로고침 버튼 전용 (이벤트 핸들러라 동기 setState 허용)
  async function load() {
    setLoading(true)
    setError('')
    try {
      const [s, h] = await Promise.all([fetchStatus(), fetchHistory(30)])
      setStatus(s)
      setHistory(h)
    } catch {
      setError('백엔드에 연결할 수 없어 (서버가 꺼져 있을 수 있음)')
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  // 마운트 시 1회 자동 조회 (effect 안에서는 .then 패턴 — 코드베이스 규칙)
  useEffect(() => {
    fetchStatus()
      .then(setStatus)
      .catch(() => setError('백엔드에 연결할 수 없어 (서버가 꺼져 있을 수 있음)'))
      .finally(() => setLoading(false))
    fetchHistory(30)
      .then(setHistory)
      .catch(() => {})
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">📊 서비스 상태</h1>
        <button type="button" onClick={load} disabled={loading} className={ui.btnGhost}>
          {loading ? '확인 중…' : '🔄 새로고침'}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {/* 지금 상태 */}
      {status && (
        <div className={ui.card}>
          <ServiceRow name="백엔드 (API)" ok={status.backend === 'ok'} />
          <ServiceRow name="데이터베이스 (PostgreSQL)" ok={status.database === 'ok'} />
          <ServiceRow name="메일 (Mailpit / SMTP)" ok={status.mail === 'ok'} />
        </div>
      )}

      {/* 업타임 (서비스별 · 최근 30일 막대) */}
      {history && (
        <div className={ui.card}>
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-gray-800 dark:text-gray-100">
              업타임 · 최근 30일
            </h2>
            <span className="text-xs text-gray-400 dark:text-gray-500">
              총 {history.total_checks}회 점검
            </span>
          </div>

          {/* 서비스별로 한 줄씩 (마우스 올리면 날짜·% 툴팁) */}
          <div className="mt-4 space-y-4">
            {history.services.map((s) => (
              <UptimeRow key={s.name} service={s} />
            ))}
          </div>

          <div className="mt-2 flex justify-between text-xs text-gray-400 dark:text-gray-500">
            <span>30일 전</span>
            <span>오늘</span>
          </div>

          {/* 범례 */}
          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-green-500" /> 정상
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-amber-400" /> 일부 장애
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-red-500" /> 장애
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-gray-200 dark:bg-gray-700" /> 데이터 없음
            </span>
          </div>
        </div>
      )}

      {/* 간단 통계 */}
      {status && (
        <div className="grid grid-cols-2 gap-4">
          <div className={ui.card}>
            <p className="text-sm text-gray-500 dark:text-gray-400">전체 글</p>
            <p className="mt-1 text-3xl font-bold text-indigo-600 dark:text-indigo-400">
              {status.stats.posts ?? '—'}
            </p>
          </div>
          <div className={ui.card}>
            <p className="text-sm text-gray-500 dark:text-gray-400">구독자</p>
            <p className="mt-1 text-3xl font-bold text-indigo-600 dark:text-indigo-400">
              {status.stats.subscribers ?? '—'}
            </p>
          </div>
        </div>
      )}

      {status && (
        <p className="text-center text-xs text-gray-400 dark:text-gray-500">
          마지막 점검: {new Date(status.checked_at).toLocaleString('ko-KR')}
        </p>
      )}
    </div>
  )
}

export default StatusPage
