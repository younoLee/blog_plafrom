import { useEffect, useState } from 'react'
import {
  fetchStatus,
  fetchHistory,
  type StatusInfo,
  type UptimeHistory,
  type ServiceUptime,
} from '../api/status'
import { ui } from '../ui'
import { IconActivity, IconRefresh } from '../components/icons'

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

// 막대 색과 같은 임계값을 글자색으로 (초록 하드코딩을 대신한다)
function uptimeTextColor(u: number | null): string {
  if (u === null) return 'text-gray-500 dark:text-gray-400'
  if (u >= 0.999) return 'text-green-600 dark:text-green-400'
  if (u >= 0.95) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

function pct(u: number | null): string {
  return u === null ? '데이터 없음' : (u * 100).toFixed(1) + '%'
}

// 서비스 한 개의 업타임 줄: 라벨 + 전체 % + 기록 범위 + 날짜별 막대
//
// **분모를 줄마다 말한다.** 예전엔 헤더에 "총 N회 점검"을 한 번만 찍었는데, 그 N은 네 줄의
// 합이라 disk 줄 옆에도 그 값이 붙었다 — 실측(2026-08-17) backend/database/mail은 30일 중
// 16일·3,364회 기록이고 disk는 **6일·872회**였다. 즉 disk의 100.00% 옆에 약 3.9배 부풀린
// 신뢰도가 적혀 있었다. 서버가 평소 꺼져 있어 안 잰 날이 많은 것은 이 사이트의 정상 상태고,
// 숨길 것이 아니라 **밝혀야 하는 값**이다(services/status.py가 데이터 계층에서 이미 안 잰 날을
// null로 갈라두었는데, 표시 직전에 그 구분이 무너지고 있었다).
function UptimeRow({ service }: { service: ServiceUptime }) {
  const measured = service.days.filter((d) => d.checks > 0)
  const checks = measured.reduce((n, d) => n + d.checks, 0)
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
          {service.label}
        </span>
        <span className="flex items-baseline gap-2">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {service.days.length}일 중 {measured.length}일 기록 · {checks.toLocaleString()}회
          </span>
          {/* 색을 하드코딩하지 않는다 — 오늘은 전부 1.0이라 화면이 그대로지만,
              mail_ok는 실제로 false가 될 수 있어서 그때 초록으로 남으면 안 된다. */}
          <span className={`text-sm font-bold ${uptimeTextColor(service.overall_uptime)}`}>
            {service.overall_uptime === null
              ? '—'
              : (service.overall_uptime * 100).toFixed(2) + '%'}
          </span>
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
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <IconActivity className="h-6 w-6 text-emerald-500" />
          <span className={ui.gradientText}>서비스 상태</span>
        </h1>
        <button type="button" onClick={load} disabled={loading} className={ui.btnGhost}>
          {/* 텍스트는 항상 span으로 감싸 맨 텍스트 노드 토글을 피함(insertBefore 크래시 방지) */}
          {!loading && <IconRefresh className="h-4 w-4" />}
          <span>{loading ? '확인 중…' : '새로고침'}</span>
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
          {/* 백엔드는 08-10부터 disk를 보내는데 이 카드에만 없었다 — 같은 페이지
              아래 업타임 막대에는 "디스크" 줄이 뜨고 있어서, 한 화면이 스스로
              어긋났다(위는 "다 정상", 아래는 디스크 장애). pgdata가 루트 볼륨에
              살아서 이 1비트가 서버 안을 보는 유일한 창이다.
              값이 없을 때는 줄을 안 그린다 — 옛 백엔드로 롤백해도 거짓 빨간불이 안 뜬다. */}
          {status.disk !== undefined && (
            <ServiceRow name="디스크 (여유 공간)" ok={status.disk === 'ok'} />
          )}
        </div>
      )}

      {/* 업타임 (서비스별 · 최근 30일 막대) */}
      {history && (
        <div className={ui.card}>
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-gray-800 dark:text-gray-100">
              업타임 · 최근 30일
            </h2>
            {/* 합계는 '전체'라고 말한다 — 줄별 분모는 각 줄이 스스로 밝힌다(UptimeRow 주석) */}
            <span className="text-xs text-gray-500 dark:text-gray-400">
              전체 {history.total_checks.toLocaleString()}회 점검
            </span>
          </div>

          {/* 서비스별로 한 줄씩 (마우스 올리면 날짜·% 툴팁) */}
          <div className="mt-4 space-y-4">
            {history.services.map((s) => (
              <UptimeRow key={s.name} service={s} />
            ))}
          </div>

          <div className="mt-2 flex justify-between text-xs text-gray-500 dark:text-gray-400">
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

          {/* **자기참조를 밝힌다.** 점검 기록은 백엔드 안에서 만들어지므로(status.py의
              backend_ok는 상수다 — 이 코드가 도는 것 자체가 백엔드 동작이라는 뜻),
              백엔드 줄의 100%는 "안 죽었다"가 아니라 "재는 동안 켜져 있었다"는 뜻이다.
              바깥에서 가동률을 재는 수단이 이 집에는 없다(EC2 알람은 켜진 동안의 하드웨어
              고장만 잡는다). 그러니 지우지 말고, 무슨 뜻인지 적어둔다. */}
          <p className="mt-3 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
            이 기록은 서버 안에서 만들어져. 서버는 비용을 아끼려고 평소 꺼두는데, 꺼져 있는
            동안은 점검 자체가 없어서 회색(데이터 없음)으로 남아 — 그래서 백엔드 줄의 비율은
            &lsquo;한 번도 안 죽었다&rsquo;가 아니라 &lsquo;재는 동안 켜져 있었다&rsquo;는 뜻이야.
          </p>
        </div>
      )}

      {/* 간단 통계 */}
      {status && (
        <div className="grid grid-cols-2 gap-4">
          <div className={ui.card}>
            <p className="text-sm text-gray-500 dark:text-gray-400">전체 글</p>
            <p className={`mt-1 text-4xl font-semibold ${ui.gradientText}`}>
              {status.stats.posts ?? '—'}
            </p>
          </div>
          <div className={ui.card}>
            <p className="text-sm text-gray-500 dark:text-gray-400">구독자</p>
            <p className="mt-1 bg-gradient-to-r from-emerald-500 to-teal-400 bg-clip-text text-4xl font-semibold text-transparent">
              {status.stats.subscribers ?? '—'}
            </p>
          </div>
        </div>
      )}

      {status && (
        <p className="text-center text-xs text-gray-500 dark:text-gray-400">
          마지막 점검: {new Date(status.checked_at).toLocaleString('ko-KR')}
        </p>
      )}
    </div>
  )
}

export default StatusPage
