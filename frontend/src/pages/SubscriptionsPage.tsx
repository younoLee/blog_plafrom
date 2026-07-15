import { useEffect, useState } from 'react'
import { useAuth } from '../auth/auth-context'
import {
  fetchAuthors,
  fetchMySubscriptionsDetail,
  subscribeAuthor,
  unsubscribeAuthor,
  type SubscribedAuthor,
} from '../api/subscriptions'
import {
  fetchMySubscription,
  subscribeMe,
  unsubscribeMe,
  fetchSubscribers,
  deleteSubscriber,
  type SubscriberRow,
} from '../api/subscribers'
import { ui } from '../ui'
import { IconCheck } from '../components/icons'

function SubscriptionsPage() {
  const { user } = useAuth()

  // 구독 이메일(내 계정 이메일) 상태 — '새 글 알림' 잠금 여부를 정함
  const [subscribed, setSubscribed] = useState(false)
  // 새 글 알림(글쓴이별 계정 구독)
  const [authors, setAuthors] = useState<SubscribedAuthor[]>([])
  const [subs, setSubs] = useState<SubscribedAuthor[]>([])
  // 관리자용 구독자 목록
  const [subscribers, setSubscribers] = useState<SubscriberRow[]>([])

  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  // 내 구독 상태 + 구독 가능한 글쓴이 + 내 구독 목록 (비로그인은 자동 비움)
  useEffect(() => {
    if (!user) {
      // effect 안 '동기' setState 금지 룰 → 마이크로태스크로 미룸
      Promise.resolve().then(() => {
        setSubscribed(false)
        setAuthors([])
        setSubs([])
      })
      return
    }
    fetchMySubscription().then((m) => setSubscribed(m?.subscribed ?? false)).catch(() => setSubscribed(false))
    fetchAuthors().then(setAuthors).catch(() => setAuthors([]))
    fetchMySubscriptionsDetail().then(setSubs).catch(() => setSubs([]))
  }, [user])

  // 이메일 구독자 목록은 관리자만
  useEffect(() => {
    if (user?.role !== 'admin') {
      // 비관리자는 목록 없음. effect 안 '동기' setState 금지 룰 → 마이크로태스크로 미룸
      Promise.resolve().then(() => setSubscribers([]))
      return
    }
    fetchSubscribers().then(setSubscribers).catch(() => setSubscribers([]))
  }, [user])

  async function toggleEmailSubscription() {
    setError('')
    setMsg('')
    try {
      if (subscribed) {
        await unsubscribeMe()
        setSubscribed(false)
        setMsg('구독을 취소했어')
      } else {
        await subscribeMe()
        setSubscribed(true)
        setMsg('구독했어! 이제 새 글 알림을 설정할 수 있어.')
      }
      if (user?.role === 'admin') setSubscribers(await fetchSubscribers())
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function toggleAuthor(authorId: number) {
    if (!subscribed) return // 구독 전에는 새 글 알림 설정 불가
    const on = subs.some((s) => s.id === authorId)
    setError('')
    setMsg('')
    try {
      if (on) await unsubscribeAuthor(authorId)
      else await subscribeAuthor(authorId)
      setSubs(await fetchMySubscriptionsDetail())
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function handleDeleteSubscriber(id: number) {
    setError('')
    setMsg('')
    try {
      await deleteSubscriber(id)
      setSubscribers(await fetchSubscribers())
      setMsg('구독자를 삭제했어')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div>
      <h1 className={`text-3xl font-bold tracking-tight ${ui.gradientText}`}>구독</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
        이메일로 구독하면, 원하는 글쓴이의 새 글 알림을 설정할 수 있어.
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
            로그인하면 구독하고 새 글 알림을 받을 수 있어.
          </p>
        ) : (
          <>
            {/* 1) 구독 이메일 (내 계정 이메일) */}
            <div>
              <h2 className="text-lg font-semibold tracking-tight">구독 이메일</h2>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                내 계정 이메일(<span className="font-medium text-gray-700 dark:text-gray-200">{user.email}</span>)로
                구독해. 새 공개글이 올라오면 이 주소로 알림이 가.
              </p>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                {subscribed ? (
                  <>
                    <span className="inline-flex items-center gap-1 text-sm font-medium text-emerald-600 dark:text-emerald-400">
                      <IconCheck className="h-4 w-4" /> 구독 중
                    </span>
                    <button type="button" onClick={toggleEmailSubscription} className={`${ui.btnGhost} text-sm`}>
                      구독 해제
                    </button>
                  </>
                ) : (
                  <button type="button" onClick={toggleEmailSubscription} className={ui.btnPrimary}>
                    내 계정 이메일로 구독
                  </button>
                )}
              </div>
            </div>

            {/* 구분선 */}
            <div className="my-6 border-t border-black/[0.06] dark:border-white/10" />

            {/* 2) 새 글 알림 (글쓴이별 계정 구독) — 구독 전에는 잠김 */}
            <div className={subscribed ? '' : 'pointer-events-none select-none opacity-50'}>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold tracking-tight">새 글 알림</h2>
                {!subscribed && (
                  <span className="rounded-full bg-black/[0.06] px-2 py-0.5 text-xs text-gray-500 dark:bg-white/10 dark:text-gray-400">
                    구독하면 설정 가능
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                구독할 글쓴이를 고르면 그 사람의 ‘구독자공개’ 글도 볼 수 있어. 다시 누르면 해제돼.
              </p>
              {authors.length === 0 ? (
                <p className="mt-4 text-sm text-gray-400 dark:text-gray-500">구독할 수 있는 다른 글쓴이가 아직 없어.</p>
              ) : (
                <div className="mt-4 flex flex-wrap gap-2">
                  {authors.map((a) => {
                    const on = subs.some((s) => s.id === a.id)
                    return (
                      <button
                        key={a.id}
                        type="button"
                        disabled={!subscribed}
                        onClick={() => toggleAuthor(a.id)}
                        className={`${on ? ui.btnGhost : ui.btnPrimary} text-sm`}
                        aria-label={`${a.name} ${on ? '알림 해제' : '알림 받기'}`}
                      >
                        {on ? `✓ ${a.name} 알림중` : `+ ${a.name} 알림`}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            {/* 관리자만: 구독자 목록 + 삭제 */}
            {user.role === 'admin' && (
              <div className="mt-6 border-t border-black/[0.06] pt-6 dark:border-white/10">
                <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  구독자 목록 ({subscribers.length})
                </h3>
                {subscribers.length === 0 ? (
                  <p className="mt-2 text-sm text-gray-400 dark:text-gray-500">아직 구독자가 없어.</p>
                ) : (
                  <ul className="mt-2 divide-y divide-black/5 dark:divide-white/10">
                    {subscribers.map((s) => (
                      <li key={s.id} className="flex items-center justify-between py-2 text-sm">
                        <span className="text-gray-700 dark:text-gray-200">
                          {s.email}
                          {!s.confirmed && (
                            <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-400/15 dark:text-amber-300">
                              확인 대기
                            </span>
                          )}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleDeleteSubscriber(s.id)}
                          className="text-gray-400 transition hover:text-red-500"
                          aria-label={`${s.email} 구독자 삭제`}
                        >
                          삭제
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}

export default SubscriptionsPage
