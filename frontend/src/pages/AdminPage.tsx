import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import {
  listUsers,
  approveUser,
  revokeUser,
  banUser,
  unbanUser,
  deleteUser,
  toggleProUser,
  fetchInfra,
  fetchAiUsage,
  listInvites,
  createInvite,
  revokeInvite,
  type InfraStatus,
  type AiUsageSummary,
  type Invite,
  type InviteCreated,
  fetchAiGuard,
  type AiGuardSummary,
} from '../api/admin'
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
//
// `ok` 를 주면 **그 판정이 이긴다** (2026-08-27). 디스크가 그렇다 — 서버가
// services/status.py 의 disk_is_ok 로 판정한 값을 실어 보낸다. 미터가 스스로 85% 로
// 판정하면 /api/status 와 같은 순간에 다른 답을 낸다(8GiB 루트 기준 81.25~85% 구간).
// CPU·메모리는 그대로 미터가 판정한다. 저 둘은 '혼잡도'라 임계가 취향이지만 디스크는
// 꽉 차면 Postgres 가 죽는 자리라 판정에 주인이 있어야 한다.
function Meter({
  label,
  percent,
  detail,
  ok,
}: {
  label: string
  percent: number
  detail: string
  ok?: boolean
}) {
  const p = Math.min(100, Math.max(0, Math.round(percent)))
  const color =
    ok === false
      ? 'bg-red-500'
      : ok === true
        ? 'bg-emerald-500'
        : p >= 85
          ? 'bg-red-500'
          : p >= 60
            ? 'bg-amber-500'
            : 'bg-emerald-500'
  return (
    <div className={ui.card}>
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-gray-600 dark:text-gray-300">{label}</span>
        <span className="text-lg font-semibold tracking-tight">{p}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-black/[0.06] dark:bg-white/10">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${p}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">{detail}</p>
    </div>
  )
}

function formatUptime(s: number): string {
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  return d > 0 ? `${d}일 ${h}시간` : h > 0 ? `${h}시간 ${m}분` : `${m}분`
}

// 초대 상태를 한 단어로. 순서가 중요하다 — 사용됨이 만료보다 먼저다(쓰고 나서
// 만료 시각이 지난 초대는 '만료'가 아니라 '사용됨'으로 읽혀야 한다).
function inviteState(inv: Invite): { label: string; badge: string } {
  if (inv.used_at) return { label: '사용됨', badge: 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300' }
  if (new Date(inv.expires_at) <= new Date())
    return { label: '만료', badge: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300' }
  return { label: '대기 중', badge: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' }
}

const nf = new Intl.NumberFormat('ko-KR')

/** AI 초안 사용량. **숫자를 돈으로 바꾸지 않는다** — 모델 단가를 프론트에 박으면
 *  단가가 바뀌는 날부터 조용히 틀린 금액을 보여주는데, 틀린 금액은 없는 것보다 나쁘다.
 *  청구에 비례하는 토큰 수와 **그 상한**만 보여준다(상한이 없으면 많은지 적은지 모른다).
 *
 *  왜 이 화면이 필요한가: Anthropic 청구는 AWS 밖이라 watch.sh가 보는 AWS Budgets가
 *  원리적으로 못 본다. 이 숫자를 안 보면 다음 명세서까지 아무도 모른다. */
/**
 * AI 가드에 걸린 시도와, 그 때문에 자동 제한된 계정.
 *
 * **왜 화면에 내놓나 (2026-08-27)** — `ai_guard_violation` 테이블은 진작 있었고 임계를
 * 넘으면 서버가 429로 막는데, **그 사실이 화면에 한 줄도 없었다.** 남는 건 로그 한 줄
 * 뿐이라 "왜 초안 생성이 안 되냐"는 문의가 오면 psql을 켜야 알 수 있었다.
 *
 * 그리고 제한은 사용자에게 뭉뚱그려 안내된다 — 몇 번 걸렸고 몇 번 남았는지 알려주면
 * 공격자에겐 계기판이 되기 때문이다(routers/ai.py 주석). 그래서 **관리자조차 못 보면
 * 아무도 못 본다.**
 *
 * 정상 사용자는 평생 0이라 이 목록은 대개 비어 있다. 비어 있음 자체가 정보다.
 */
function AiGuardSection() {
  const [data, setData] = useState<AiGuardSummary | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    fetchAiGuard()
      .then(setData)
      .catch(() => setFailed(true))
  }, [])

  if (failed || !data) return null

  return (
    <section className="mt-8">
      <h2 className="mb-1 text-xl font-semibold tracking-tight">AI 가드</h2>
      <p className="mb-3 text-sm text-gray-500 dark:text-gray-400">
        프롬프트 인젝션 가드에 걸린 시도야. 시간당 {data.cap}번을 넘기면 그 시간 동안
        초안 생성이 자동으로 막혀. 정상 사용자는 여기 안 나와.
      </p>
      {data.items.length === 0 ? (
        <p className={`${ui.card} text-sm text-gray-500 dark:text-gray-400`}>
          이번 시간창에 걸린 시도가 없어.
        </p>
      ) : (
        <ul className={`${ui.card} divide-y divide-black/[0.06] dark:divide-white/10`}>
          {data.items.map((it) => (
            <li key={it.user_id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="truncate">{it.name}</span>
              <span className="flex shrink-0 items-center gap-2">
                <span className="text-gray-500 dark:text-gray-400">{it.count}회</span>
                {/* 판정은 서버가 한다 — 화면이 cap과 비교해 스스로 정하면 백엔드가
                    임계를 바꿔도 여기는 옛 기준으로 그린다. */}
                {it.blocked && (
                  <span className="rounded-btn bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600 dark:bg-red-950 dark:text-red-300">
                    제한 중
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        지금 시간창({new Date(data.hour).toLocaleString('ko-KR')} 기준)만 보여줘. 자동 제한도
        그 창을 기준으로 걸려.
      </p>
    </section>
  )
}

function AiUsageSection() {
  const [data, setData] = useState<AiUsageSummary | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    fetchAiUsage()
      .then(setData)
      .catch(() => setFailed(true))
  }, [])

  // 서버가 꺼져 있으면 못 가져온다. 인프라 카드와 달리 폴링하지 않으므로
  // '마지막 성공값이 남아 초록으로 보이는' 문제는 없다 — 실패는 실패로 말한다.
  if (failed) {
    return (
      <section className="mt-8">
        <h2 className="mb-1 text-xl font-semibold tracking-tight">AI 사용량</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          지금은 못 불러왔어 (서버 정지 또는 장애).
        </p>
      </section>
    )
  }
  if (!data) return null

  const { today, daily, top_users_month: top, caps } = data
  const peak = Math.max(1, ...daily.map((d) => d.input_tokens + d.output_tokens))

  return (
    <section className="mt-8">
      <h2 className="mb-1 flex items-baseline gap-2 text-xl font-semibold tracking-tight">
        AI 사용량
        <span className="text-xs font-normal text-gray-500 dark:text-gray-400">
          서버키(Claude) 호출만 · BYOK는 사용자 비용이라 안 셈
        </span>
      </h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Meter
          label="오늘 호출"
          percent={(today.calls / today.calls_cap) * 100}
          detail={`${nf.format(today.calls)} / ${nf.format(today.calls_cap)}회 (서비스 전체 일일 캡)`}
        />
        <Meter
          label="오늘 토큰"
          percent={(today.tokens / today.tokens_cap) * 100}
          detail={`${nf.format(today.tokens)} / ${nf.format(today.tokens_cap)} (입력+출력)`}
        />
      </div>

      <h3 className="mb-2 mt-6 text-sm font-medium text-gray-600 dark:text-gray-300">
        최근 14일 토큰
      </h3>
      {daily.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">아직 기록이 없어.</p>
      ) : (
        <ul className="space-y-1">
          {daily.map((d) => {
            const total = d.input_tokens + d.output_tokens
            return (
              <li key={d.day} className="flex items-center gap-3 text-xs">
                <span className="w-20 shrink-0 tabular-nums text-gray-500 dark:text-gray-400">
                  {d.day.slice(5)}
                </span>
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-black/[0.06] dark:bg-white/10">
                  <span
                    className="block h-full rounded-full bg-indigo-500"
                    style={{ width: `${(total / peak) * 100}%` }}
                  />
                </span>
                <span className="w-28 shrink-0 text-right tabular-nums text-gray-600 dark:text-gray-300">
                  {nf.format(total)} · {d.calls}회
                </span>
              </li>
            )
          })}
        </ul>
      )}

      {top.length > 0 && (
        <>
          <h3 className="mb-2 mt-6 text-sm font-medium text-gray-600 dark:text-gray-300">
            이번 달 사용자별
          </h3>
          <ul className="space-y-1 text-sm">
            {top.map((u) => (
              <li key={u.user_id} className="flex justify-between gap-3">
                {/* 이메일은 안 보여준다 — 표시명 규칙(display_name_of)을 서버가 이미 적용했다 */}
                <span className="truncate">{u.name}</span>
                <span className="shrink-0 tabular-nums text-gray-500 dark:text-gray-400">
                  {nf.format(u.tokens)} · {u.calls}회
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
        1인 캡: 시간당 {caps.per_user_hourly}회 · 하루 {caps.per_user_daily}회 · 한 달{' '}
        {caps.per_user_monthly}회. 금액이 아니라 토큰으로 보여주는 이유는 단가가 바뀌면
        박아둔 금액이 조용히 틀리기 때문이야.
      </p>
    </section>
  )
}

// 초대 발급/취소. '초대제'라는 말에 실체를 주는 화면이다 — 그전까지 초대는
// 관리자가 DB를 직접 만지는 것이었다.
function InviteSection() {
  const [invites, setInvites] = useState<Invite[]>([])
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'pending' | 'writer'>('pending')
  const [issued, setIssued] = useState<InviteCreated | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // 불러오기가 '끝났는지'를 따로 안다. 실패해도 invites는 []라서, 이걸 구분하지
  // 않으면 못 불러온 상태에서 "아직 발급한 초대가 없어"라고 단언하게 된다
  // (HomePage가 절전 중에 '글이 없다'를 안 띄우는 것과 같은 이유).
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    listInvites()
      .then(setInvites)
      .catch((e) => setError(e.message))
      .finally(() => setLoaded(true))
  }, [])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const created = await createInvite(email.trim(), role)
      const { url, ...row } = created
      setIssued(created)
      setCopied(false)
      // 목록엔 url을 **뺀** 것만 넣는다. 원문 토큰이 두 군데 살아 있으면 아래
      // setIssued(null)이 '토큰을 화면에서 지웠다'는 뜻이 아니게 된다.
      void url
      setInvites((prev) => [row, ...prev])
      setEmail('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '발급 실패')
    } finally {
      setBusy(false)
    }
  }

  async function handleRevoke(id: number, target: string) {
    if (!window.confirm(`${target}에게 보낸 초대를 취소할까?\n이미 건넨 링크는 즉시 무효가 돼.`)) return
    try {
      await revokeInvite(id)
      setInvites((prev) => prev.filter((i) => i.id !== id))
      if (issued?.id === id) setIssued(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '취소 실패')
    }
  }

  return (
    <section className="mt-8">
      <h2 className="mb-1 text-xl font-semibold tracking-tight">초대</h2>
      <p className="mb-3 text-sm text-gray-500 dark:text-gray-400">
        발급한 링크를 직접 건네줘(카톡·메일 등). 링크를 연 사람은 비밀번호만 정하면 가입돼.
        확인 메일이 없어서 SES 샌드박스에서도 그대로 동작해.
      </p>

      <form onSubmit={handleCreate} className="flex flex-wrap items-center gap-2">
        <input
          type="email"
          required
          placeholder="초대할 이메일"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={`${ui.input} flex-1 basis-56`}
        />
        <select value={role} onChange={(e) => setRole(e.target.value as 'pending' | 'writer')} className={`${ui.select} basis-40`}>
          <option value="pending">승인 대기로</option>
          <option value="writer">글쓰기 가능으로</option>
        </select>
        <button type="submit" disabled={busy} className={ui.btnPrimary}>
          {busy ? '발급 중…' : '초대 발급'}
        </button>
      </form>

      {/* 원문 토큰이 나오는 건 이 응답 하나뿐이다. 서버는 해시만 저장하므로
          이 카드를 닫으면 링크를 다시 볼 방법이 없다 — 그 사실을 분명히 적는다. */}
      {issued && (
        <div className="mt-3 rounded-xl border border-amber-300/60 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
          <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
            {issued.email} 초대 링크. 지금 복사해둬, 다시 볼 수 없어.
          </p>
          {/* 초대제는 가입에 메일을 한 통도 안 쓴다. 그래서 주소가 틀려도 침묵으로
              지나가고, 비번 재설정이 필요해지는 날까지 아무도 모른다. 여기가
              말해줄 수 있는 유일한 지점이다. null(모름)일 땐 아무 말도 안 한다. */}
          {issued.recipient_verified === false && (
            <p className="mt-2 rounded-lg bg-white/60 px-3 py-2 text-xs leading-relaxed text-amber-900 dark:bg-black/20 dark:text-amber-200">
              ⚠️ 이 주소는 <span className="font-medium">SES에 검증돼 있지 않아</span>. 실재하는
              주소인지 확인된 적이 없어. 초대는 그대로 유효하지만(가입에 메일이 필요 없어),
              나중에 <span className="font-medium">비밀번호 재설정 메일이 안 닿아.</span>
              <br />
              확인하려면: <code className="rounded bg-black/10 px-1 dark:bg-white/10">
                scripts/ses_verify_recipients.sh {issued.email}
              </code> → 상대가 AWS 확인 메일의 링크를 누르면 끝.
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="flex-1 basis-64 overflow-x-auto rounded-lg bg-white/70 px-3 py-2 text-xs dark:bg-black/30">
              {issued.url}
            </code>
            <button
              type="button"
              onClick={() => navigator.clipboard.writeText(issued.url).then(() => setCopied(true))}
              className={ui.btnGhost}
            >
              {copied ? '복사됨' : '복사'}
            </button>
          </div>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-red-500">{error}</p>}

      <ul className="mt-4 space-y-2">
        {invites.map((inv) => {
          const st = inviteState(inv)
          return (
            <li
              key={inv.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-black/[0.07] bg-white px-4 py-3 dark:border-white/10 dark:bg-white/[0.06]"
            >
              <span className="text-sm font-medium">{inv.email}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${st.badge}`}>{st.label}</span>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {inv.role === 'writer' ? '글쓰기 가능' : '승인 대기'}로 · 만료 {new Date(inv.expires_at).toLocaleDateString()}
              </span>
              {/* 사용된 초대는 지우지 않는다 — '누가 이 계정을 들였나'가 초대제의 감사 기록이다 */}
              {!inv.used_at && (
                <button
                  type="button"
                  onClick={() => handleRevoke(inv.id, inv.email)}
                  className="ml-auto text-xs text-red-500 hover:underline"
                >
                  취소
                </button>
              )}
              {/* 그 감사 기록을 실제로 보여주는 줄. 이게 없으면 위 주석이 근거로 삼는
                  답을 psql로만 볼 수 있다. 계정이 지워지면 null이라 '(삭제됨)'으로 적는다. */}
              <span className="basis-full text-xs text-gray-500 dark:text-gray-400">
                발급 {inv.created_by_email ?? '(삭제된 계정)'}
                {inv.used_at && ` · 가입 ${inv.used_by_email ?? '(삭제된 계정)'} · ${new Date(inv.used_at).toLocaleDateString()}`}
              </span>
            </li>
          )
        })}
        {loaded && !error && invites.length === 0 && (
          <li className="text-sm text-gray-500 dark:text-gray-400">아직 발급한 초대가 없어.</li>
        )}
      </ul>
    </section>
  )
}

function AdminPage() {
  const { user, loading } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [infra, setInfra] = useState<InfraStatus | null>(null)
  // 게이지가 '지금'을 보여주는지 '마지막으로 살아 있던 때'를 보여주는지 구분하기 위한 둘
  const [infraStale, setInfraStale] = useState(false)
  const [infraAt, setInfraAt] = useState<Date | null>(null)
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
    // `.catch(() => {})`만 두면 실패해도 infra state가 **마지막 성공값 그대로** 남아,
    // 서버가 꺼진 뒤에도 CPU 12%·메모리 40%가 초록으로 떠 있다. 이 프로젝트는
    // 서버를 껐다 켜는 게 운영 방식이라 **정확히 그 순간에 틀린다**(2026-08-11 공백검사).
    // 실패를 상태로 만들고, 마지막 갱신 시각도 같이 보여준다.
    const load = () =>
      fetchInfra()
        .then((d) => {
          if (!alive) return
          setInfra(d)
          setInfraAt(new Date())
          setInfraStale(false)
        })
        .catch(() => alive && setInfraStale(true))
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
      <h1 className={`text-3xl font-bold tracking-tight ${ui.pageTitle}`}>관리자</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
        가입자를 승인하면 글을 쓸 수 있어. 승인 취소하면 다시 막혀(기존 글은 남음).
      </p>

      {/* 인프라 상태 대시보드 (서버 EC2 + DB 실측, 10초 폴링). 관리자만 봄 */}
      {infraStale && (
        <p className="mt-6 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          ⚠️ 인프라 상태를 못 가져오고 있어 (서버 정지 또는 장애). 아래 값은
          {infraAt ? ` ${infraAt.toLocaleTimeString()} 기준 옛 값` : ' 갱신되지 않은 값'}이야.
        </p>
      )}
      {infra && (
        <section className="mt-6">
          <h2 className="mb-3 flex items-baseline gap-2 text-xl font-semibold tracking-tight">
            인프라 상태
            <span className="text-xs font-normal text-gray-500 dark:text-gray-400">서버·DB 실측 · 10초마다 갱신</span>
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Meter label="CPU" percent={infra.cpu_percent} detail={`부하 ${infra.load_avg['1m']} · ${infra.cpu_count}코어`} />
            <Meter label="메모리" percent={infra.memory.percent} detail={`${infra.memory.used_mb} / ${infra.memory.total_mb} MB`} />
            <Meter label="디스크" percent={infra.disk.percent} detail={`${infra.disk.used_gb} / ${infra.disk.total_gb} GB`} ok={infra.disk.ok} />
            <Meter
              label="DB 커넥션"
              percent={infra.db.max_connections ? ((infra.db.connections ?? 0) / infra.db.max_connections) * 100 : 0}
              detail={infra.db.connections != null ? `${infra.db.connections} / ${infra.db.max_connections}` : '조회 불가'}
            />
          </div>
          <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
            서버 가동시간: {formatUptime(infra.uptime_seconds)}
            {infraAt && ` · 갱신 ${infraAt.toLocaleTimeString()}`}
          </p>

          {/* 마지막 알림 발송 (2026-08-27). 이 숫자는 여태 **로그에만** 있었고, 그
              로그는 대부분 꺼져 있는 EC2 안에 있었다. "알림이 안 왔다"는 말이 나왔을 때
              서버를 켜고 SSH로 들어가야만 확인할 수 있었다.
              08-26 훈련이 찾은 '앞 5대만 계속 받는' 불공정도 로그를 사람이 읽어야 보였다. */}
          {infra.last_push && (
            <div className={`${ui.card} mt-3`}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-gray-600 dark:text-gray-300">
                  마지막 알림 발송
                </span>
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {new Date(infra.last_push.at).toLocaleString('ko-KR')}
                </span>
              </div>
              <p className="mt-1 text-sm">
                기기 {infra.last_push.targets}대 중 {infra.last_push.tried}대에 보내
                {' '}
                <span
                  className={
                    infra.last_push.ok < infra.last_push.tried
                      ? 'font-semibold text-red-500'
                      : 'font-semibold text-emerald-600 dark:text-emerald-400'
                  }
                >
                  {infra.last_push.ok}대 성공
                </span>
                {infra.last_push.gone > 0 && ` · 만료 ${infra.last_push.gone}대 정리`}
              </p>
              {/* 예산에 걸리면 남은 기기는 그 발행을 못 받는다. 아무 에러도 안 나는
                  자리라 여기서 말하지 않으면 아무도 모른다. */}
              {infra.last_push.budget_hit && (
                <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                  45초 예산에 걸려 {infra.last_push.targets - infra.last_push.tried}대는 이번
                  발행을 못 받았어. 벤더가 느리거나 응답이 없다는 뜻이야.
                </p>
              )}
              {infra.last_push.ok < infra.last_push.tried && !infra.last_push.budget_hit && (
                <p className="mt-1 text-xs text-red-600 dark:text-red-400">
                  시도한 {infra.last_push.tried}대 중 {infra.last_push.tried - infra.last_push.ok}
                  대가 실패했어.
                </p>
              )}
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                마지막 한 건만 기억해. 서버를 재시작하면 사라져.
              </p>
            </div>
          )}
        </section>
      )}

      {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

      <AiUsageSection />

      <AiGuardSection />

      <InviteSection />

      <h2 className="mb-3 mt-8 text-xl font-semibold tracking-tight">가입자 관리</h2>
      <ul className="space-y-3">
        {users.map((u) => {
          const meta = ROLE_META[u.role]
          return (
            // 좁은 화면(360~390px)에서 writer 행은 버튼이 4개가 되는데 버튼 묶음이
            // `shrink-0`이라 줄지도 줄바꿈하지도 않아 **가로 스크롤이 생겼다**.
            // 같은 파일의 초대 폼에는 flex-wrap이 있어 대비됐다(2026-08-11 공백검사).
            <li key={u.id} className={`${ui.card} flex flex-wrap items-center justify-between gap-3`}>
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
              <div className="flex shrink-0 flex-wrap gap-2">
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
