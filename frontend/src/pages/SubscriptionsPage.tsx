import { useEffect, useState } from 'react'
import { useAuth } from '../auth/auth-context'
import {
  fetchAuthors,
  fetchMySubscriptionsDetail,
  subscribeAuthor,
  unsubscribeAuthor,
  setNotify,
  type SubscribedAuthor,
} from '../api/subscriptions'
import { ui } from '../ui'
import { IconCheck } from '../components/icons'

function SubscriptionsPage() {
  const { user } = useAuth()
  // 구독 가능한 글쓴이 전체 + 내가 구독 중인 글쓴이(알림여부 포함)
  const [authors, setAuthors] = useState<SubscribedAuthor[]>([])
  const [subs, setSubs] = useState<SubscribedAuthor[]>([])
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user) {
      // effect 안 '동기' setState 금지 룰 → 마이크로태스크로 미룸
      Promise.resolve().then(() => {
        setAuthors([])
        setSubs([])
      })
      return
    }
    fetchAuthors().then(setAuthors).catch(() => setAuthors([]))
    fetchMySubscriptionsDetail().then(setSubs).catch(() => setSubs([]))
  }, [user])

  // 글쓴이 구독/해제 (글쓴이마다 독립)
  async function toggleAuthor(authorId: number) {
    setError('')
    setMsg('')
    try {
      if (subs.some((s) => s.id === authorId)) await unsubscribeAuthor(authorId)
      else await subscribeAuthor(authorId)
      setSubs(await fetchMySubscriptionsDetail())
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // 그 글쓴이의 새 글 이메일 알림 켜기/끄기 (구독한 뒤에만 가능)
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

  return (
    <div>
      <h1 className={`text-3xl font-bold tracking-tight ${ui.gradientText}`}>구독</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
        글쓴이를 구독하면 그 사람의 ‘구독자공개’ 글을 볼 수 있어. 구독한 뒤 🔔을 켜면 그 글쓴이의
        새 글이 올라올 때 이메일로 알림받아. (글쓴이마다 따로)
      </p>

      {msg && (
        <p className="mt-4 inline-flex items-center gap-1 text-sm text-emerald-600 dark:text-emerald-400">
          <IconCheck className="h-4 w-4" />
          {msg}
        </p>
      )}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <section className={`${ui.card} mt-6`}>
        {!user ? (
          <p className="text-sm text-gray-400 dark:text-gray-500">
            로그인하면 글쓴이를 구독하고 새 글 알림을 받을 수 있어.
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
              const notifyOn = sub?.notify ?? false
              return (
                <li key={a.id} className="flex items-center justify-between gap-3 py-3">
                  <span className="font-medium text-gray-800 dark:text-gray-100">{a.name}</span>
                  <div className="flex items-center gap-2">
                    {/* 알림 벨 — 구독한 글쓴이에만 뜬다(구독이 먼저) */}
                    {on && (
                      <button
                        type="button"
                        onClick={() => toggleNotify(a.id, !notifyOn)}
                        className={`${notifyOn ? ui.btnPrimary : ui.btnGhost} text-sm`}
                        aria-label={`${a.name} 새 글 알림 ${notifyOn ? '끄기' : '켜기'}`}
                      >
                        {notifyOn ? '🔔 알림 켬' : '🔕 알림 꺼짐'}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => toggleAuthor(a.id)}
                      className={`${on ? ui.btnGhost : ui.btnPrimary} text-sm`}
                      aria-label={`${a.name} ${on ? '구독 해제' : '구독'}`}
                    >
                      {on ? '✓ 구독 중' : '+ 구독'}
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
