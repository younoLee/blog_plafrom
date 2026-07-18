import { useEffect, useState } from 'react'
import { useAuth } from '../auth/auth-context'
import {
  fetchAuthors,
  fetchMySubscriptionsDetail,
  subscribeAuthor,
  unsubscribeAuthor,
  setNotify,
  fetchRequests,
  approveRequest,
  rejectRequest,
  type SubscribedAuthor,
  type PendingRequest,
} from '../api/subscriptions'
import { ui } from '../ui'
import { IconCheck } from '../components/icons'

function SubscriptionsPage() {
  const { user } = useAuth()
  // 내가 구독 가능한 글쓴이 전체 / 내가 신청·구독한 것(승인·알림 포함) / 나에게 온 신청
  const [authors, setAuthors] = useState<SubscribedAuthor[]>([])
  const [subs, setSubs] = useState<SubscribedAuthor[]>([])
  const [requests, setRequests] = useState<PendingRequest[]>([])
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user) {
      // effect 안 '동기' setState 금지 룰 → 마이크로태스크로 미룸
      Promise.resolve().then(() => {
        setAuthors([])
        setSubs([])
        setRequests([])
      })
      return
    }
    fetchAuthors().then(setAuthors).catch(() => setAuthors([]))
    fetchMySubscriptionsDetail().then(setSubs).catch(() => setSubs([]))
    fetchRequests().then(setRequests).catch(() => setRequests([]))
  }, [user])

  // 구독 신청/취소 (글쓴이마다 독립)
  async function toggleAuthor(authorId: number) {
    setError('')
    setMsg('')
    try {
      if (subs.some((s) => s.id === authorId)) {
        await unsubscribeAuthor(authorId)
      } else {
        await subscribeAuthor(authorId)
        setMsg('구독을 신청했어. 글쓴이가 승인하면 열려.')
      }
      setSubs(await fetchMySubscriptionsDetail())
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // 새 글 알림 켜기/끄기 (승인된 뒤에만 가능)
  async function toggleNotify(authorId: number, notify: boolean) {
    setError('')
    setMsg('')
    try {
      await setNotify(authorId, notify)
      setSubs(await fetchMySubscriptionsDetail())
      setMsg(notify ? '알림을 켰어' : '알림을 껐어')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // 나(글쓴이)에게 온 신청 승인/거절
  async function handleRequest(subscriberId: number, approve: boolean) {
    setError('')
    setMsg('')
    try {
      if (approve) await approveRequest(subscriberId)
      else await rejectRequest(subscriberId)
      setRequests(await fetchRequests())
      setMsg(approve ? '구독을 승인했어' : '구독 신청을 거절했어')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div>
      <h1 className={`text-3xl font-bold tracking-tight ${ui.gradientText}`}>구독</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
        글쓴이에게 구독을 ‘신청’하면 글쓴이가 승인한 뒤 그 사람의 ‘구독자공개’ 글을 볼 수 있어.
        승인되면 🔔로 새 글 알림도 켤 수 있어. (글쓴이마다 따로)
      </p>

      {msg && (
        <p className="mt-4 inline-flex items-center gap-1 text-sm text-emerald-600 dark:text-emerald-400">
          <IconCheck className="h-4 w-4" />
          {msg}
        </p>
      )}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {/* 받은 구독 신청 (글쓴이용) — 신청이 있을 때만 뜬다 */}
      {user && requests.length > 0 && (
        <section className={`${ui.card} mt-6`}>
          <h2 className="text-lg font-semibold tracking-tight">받은 구독 신청 ({requests.length})</h2>
          <ul className="mt-3 divide-y divide-black/[0.06] dark:divide-white/10">
            {requests.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3 py-2">
                <span className="font-medium text-gray-800 dark:text-gray-100">{r.name}</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleRequest(r.id, true)}
                    className={`${ui.btnPrimary} text-sm`}
                  >
                    승인
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRequest(r.id, false)}
                    className={`${ui.btnGhost} text-sm`}
                  >
                    거절
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 구독할 글쓴이 목록 */}
      <section className={`${ui.card} mt-6`}>
        {!user ? (
          <p className="text-sm text-gray-400 dark:text-gray-500">
            로그인하면 글쓴이를 구독 신청하고 새 글 알림을 받을 수 있어.
          </p>
        ) : authors.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-gray-500">
            구독할 수 있는 다른 글쓴이가 아직 없어.
          </p>
        ) : (
          <ul className="divide-y divide-black/[0.06] dark:divide-white/10">
            {authors.map((a) => {
              const sub = subs.find((s) => s.id === a.id)
              const on = !!sub
              const approved = sub?.approved ?? false
              const notifyOn = sub?.notify ?? false
              return (
                <li key={a.id} className="flex items-center justify-between gap-3 py-3">
                  <span className="font-medium text-gray-800 dark:text-gray-100">{a.name}</span>
                  <div className="flex items-center gap-2">
                    {/* 승인 대기 배지 */}
                    {on && !approved && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-400/15 dark:text-amber-300">
                        승인 대기중
                      </span>
                    )}
                    {/* 알림 벨 — 승인된 구독에만 */}
                    {on && approved && (
                      <button
                        type="button"
                        onClick={() => toggleNotify(a.id, !notifyOn)}
                        title={notifyOn ? '새 글 알림 켜짐 (누르면 끔)' : '새 글 알림 꺼짐 (누르면 켬)'}
                        className={`${notifyOn ? ui.btnPrimary : ui.btnGhost} text-sm`}
                        aria-label={`${a.name} 새 글 알림 ${notifyOn ? '끄기' : '켜기'}`}
                        aria-pressed={notifyOn}
                      >
                        {/* 종 모양(🔔)이 보이면 켜진 것, 음소거 종(🔕)이면 꺼진 것 */}
                        {notifyOn ? '🔔' : '🔕'}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => toggleAuthor(a.id)}
                      className={`${on ? ui.btnGhost : ui.btnPrimary} text-sm`}
                      aria-label={`${a.name} ${on ? '구독 취소' : '구독 신청'}`}
                    >
                      {on ? (approved ? '✓ 구독 중' : '신청 취소') : '+ 구독'}
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}

export default SubscriptionsPage
