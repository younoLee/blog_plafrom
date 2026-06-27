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
  subscribe as subscribeEmail,
  unsubscribeEmail,
  fetchSubscribers,
  deleteSubscriber,
  type SubscriberRow,
} from '../api/subscribers'
import { ui } from '../ui'
import { IconCheck } from '../components/icons'

function SubscriptionsPage() {
  const { user } = useAuth()

  // 계정 구독
  const [authors, setAuthors] = useState<SubscribedAuthor[]>([])
  const [subs, setSubs] = useState<SubscribedAuthor[]>([])
  // 이메일(새 글) 구독
  const [email, setEmail] = useState('')
  const [subscribers, setSubscribers] = useState<SubscriberRow[]>([])

  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  // 구독 가능한 글쓴이 + 내 구독 목록 (비로그인은 자동 [])
  useEffect(() => {
    fetchAuthors().then(setAuthors).catch(() => setAuthors([]))
    fetchMySubscriptionsDetail().then(setSubs).catch(() => setSubs([]))
  }, [user])

  // 이메일 구독자 목록은 관리자만
  useEffect(() => {
    if (user?.role !== 'admin') {
      setSubscribers([])
      return
    }
    fetchSubscribers().then(setSubscribers).catch(() => setSubscribers([]))
  }, [user])

  async function toggleAuthor(authorId: number) {
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

  async function handleEmailSubscribe(e: React.FormEvent) {
    e.preventDefault()
    const v = email.trim()
    if (!v) return
    setError('')
    setMsg('')
    try {
      await subscribeEmail(v)
      setEmail('')
      setMsg('이메일 구독을 등록했어')
      if (user?.role === 'admin') setSubscribers(await fetchSubscribers())
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function handleEmailUnsubscribe() {
    const v = email.trim()
    if (!v) return
    setError('')
    setMsg('')
    try {
      await unsubscribeEmail(v)
      setEmail('')
      setMsg('이메일 구독을 취소했어')
      if (user?.role === 'admin') setSubscribers(await fetchSubscribers())
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
      <h1 className={`text-3xl font-bold tracking-tight ${ui.gradientText}`}>구독 관리</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
        다른 글쓴이 계정을 구독하거나, 이메일로 새 글 알림 받는 걸 여기서 관리해.
      </p>

      {msg && (
        <p className="mt-4 inline-flex items-center gap-1 text-sm text-emerald-600 dark:text-emerald-400">
          <IconCheck className="h-4 w-4" />
          {msg}
        </p>
      )}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {/* 1) 계정 구독 */}
      <section className={`${ui.card} mt-6`}>
        <h2 className="text-lg font-semibold tracking-tight">계정 구독</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          구독하면 그 사람의 ‘구독자공개’ 글도 볼 수 있어. 다시 누르면 해제돼.
        </p>
        {!user ? (
          <p className="mt-4 text-sm text-gray-400 dark:text-gray-500">로그인하면 계정을 구독할 수 있어.</p>
        ) : authors.length === 0 ? (
          <p className="mt-4 text-sm text-gray-400 dark:text-gray-500">구독할 수 있는 다른 글쓴이가 아직 없어.</p>
        ) : (
          <div className="mt-4 flex flex-wrap gap-2">
            {authors.map((a) => {
              const on = subs.some((s) => s.id === a.id)
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => toggleAuthor(a.id)}
                  className={`${on ? ui.btnGhost : ui.btnPrimary} text-sm`}
                  aria-label={`${a.name} ${on ? '구독 해제' : '구독'}`}
                >
                  {on ? `✓ ${a.name} 구독중` : `+ ${a.name} 구독`}
                </button>
              )
            })}
          </div>
        )}
      </section>

      {/* 2) 새 글 이메일 구독 */}
      <section className={`${ui.card} mt-4`}>
        <h2 className="text-lg font-semibold tracking-tight">새 글 이메일 구독</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          이메일을 등록하면 새 공개글이 올라올 때 알림을 보내.
        </p>
        <form onSubmit={handleEmailSubscribe} className="mt-4 flex flex-wrap gap-2">
          <input
            type="email"
            placeholder="이메일 주소"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={`${ui.input} min-w-0 flex-1`}
          />
          <button type="submit" className={`${ui.btnPrimary} shrink-0`}>
            구독
          </button>
          <button type="button" onClick={handleEmailUnsubscribe} className={`${ui.btnGhost} shrink-0`}>
            구독 취소
          </button>
        </form>
        <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
          이미 구독한 이메일은 같은 주소를 넣고 ‘구독 취소’를 누르면 삭제돼.
        </p>

        {/* 관리자만: 구독자 목록 + 삭제 */}
        {user?.role === 'admin' && (
          <div className="mt-6">
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">
              구독자 목록 ({subscribers.length})
            </h3>
            {subscribers.length === 0 ? (
              <p className="mt-2 text-sm text-gray-400 dark:text-gray-500">아직 구독자가 없어.</p>
            ) : (
              <ul className="mt-2 divide-y divide-black/5 dark:divide-white/10">
                {subscribers.map((s) => (
                  <li key={s.id} className="flex items-center justify-between py-2 text-sm">
                    <span className="text-gray-700 dark:text-gray-200">{s.email}</span>
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
      </section>
    </div>
  )
}

export default SubscriptionsPage
