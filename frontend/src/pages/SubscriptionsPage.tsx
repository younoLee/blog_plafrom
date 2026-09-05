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
import { ServerAsleepError } from '../api/http'
import { AsleepNotice } from '../components/AsleepNotice'
import { ui } from '../ui'
import { IconCheck } from '../components/icons'
import PushToggle from '../components/PushToggle'
import { useDocumentTitle } from '../useDocumentTitle'

function SubscriptionsPage() {
  useDocumentTitle('구독')
  const { user } = useAuth()
  // 내가 구독 가능한 글쓴이 전체 / 내가 신청·구독한 것(승인·알림 포함) / 나에게 온 신청
  //
  // authors 만 `null` 을 갖는다 = **아직 모른다.** 빈 배열은 "구독할 수 있는 다른
  // 글쓴이가 아직 없어"라는 사실 주장을 화면에 띄우는데, 조회가 실패했을 때도 같은
  // 문장이 떴다(09-04 검사 FE-5). 이 사이트는 서버가 평소 꺼져 있어서 그 실패가
  // 예외가 아니라 **기본 경로**다 — 그 상태에서 이 화면은 '기능이 없는 블로그'로 보였다.
  const [authors, setAuthors] = useState<SubscribedAuthor[] | null>(null)
  const [subs, setSubs] = useState<SubscribedAuthor[]>([])
  const [requests, setRequests] = useState<PendingRequest[]>([])
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  // 목록 조회가 실패했다 — 절전(노란 안내)과 진짜 실패(빨간 줄)를 갈라 담는다.
  const [asleep, setAsleep] = useState(false)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    if (!user) {
      // effect 안 '동기' setState 금지 룰 → 마이크로태스크로 미룸
      Promise.resolve().then(() => {
        setAuthors(null)
        setSubs([])
        setRequests([])
        setAsleep(false)
        setLoadError('')
      })
      return
    }
    // 늦게 온 응답이 로그아웃·계정 전환 뒤의 화면을 덮지 않게 한다(HomePage 와 같은 규칙).
    let alive = true
    fetchAuthors()
      .then((list) => {
        if (!alive) return
        setAuthors(list)
        setAsleep(false)
        setLoadError('')
      })
      .catch((e) => {
        if (!alive) return
        // 실패는 실패로 남긴다 — authors 를 []로 접으면 다시 '없어'가 된다.
        setAuthors(null)
        setAsleep(e instanceof ServerAsleepError)
        setLoadError((e as Error).message)
      })
    fetchMySubscriptionsDetail()
      .then((s) => alive && setSubs(s))
      .catch(() => alive && setSubs([]))
    fetchRequests()
      .then((r) => alive && setRequests(r))
      .catch(() => alive && setRequests([]))
    return () => {
      alive = false
    }
  }, [user])

  // 구독 신청/취소 (글쓴이마다 독립)
  async function toggleAuthor(authorId: number) {
    setError('')
    setMsg('')
    try {
      const current = subs.find((s) => s.id === authorId)
      if (current) {
        // **승인된 구독 해지는 되돌릴 수 없다.** 서버가 소프트 삭제가 아니라 행을 지우고
        // (subscriptions.py의 db.delete), 관리자에게도 복구 경로가 없다 — 재신청 + 재승인
        // 2단계를 다시 밟아야 하고, 그건 운영자가 서버를 켠 날까지 미뤄진다.
        // 그런데 이 버튼은 '✓ 구독 중'이라 **상태 라벨처럼 생겼고** 확인창이 없었다
        // (2026-08-17 검사). 승인 전 '신청 취소'는 잃을 게 없으므로 그대로 즉시 처리한다.
        if (current.approved && !window.confirm('구독을 취소하면 승인이 사라져서 다시 신청하고 승인을 받아야 해. 취소할까?')) return
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
      <h1 className={`text-3xl font-bold tracking-tight ${ui.pageTitle}`}>구독</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
        글쓴이에게 구독을 ‘신청’하면 글쓴이가 승인한 뒤 그 사람의 ‘구독자공개’ 글을 볼 수 있어.
        승인되면 🔔로 새 글 알림도 켤 수 있어. (글쓴이마다 따로)
      </p>

      {msg && (
        <p role="status" className="mt-4 inline-flex items-center gap-1 text-sm text-emerald-600 dark:text-emerald-400">
          <IconCheck className="h-4 w-4" />
          {msg}
        </p>
      )}
      {error && <p role="alert" className="mt-4 text-sm text-red-600">{error}</p>}

      {/* 알림 '경로'. 위 🔔이 '누구의 알림을 받을지'라면 이건 '어디로 받을지'다.
          SettingsPage가 아니라 여기 두는 이유: 저쪽은 BYOK·스킨처럼 글쓰기 권한이
          필요한 설정이 본체라, 알림 경로를 거기 두면 성격이 다른 것이 섞인다.
          (2026-08-27 정정) 예전 이유는 "저쪽은 canWrite 게이트가 있어 구독자가 못
          본다"였는데 그건 더 이상 사실이 아니다. SettingsPage는 로그인만 요구하고
          (SettingsPage.tsx:63) 헤더의 설정 링크도 canWrite 밖으로 나왔다. */}
      {user && <PushToggle />}

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
          <p className="text-sm text-gray-500 dark:text-gray-400">
            로그인하면 글쓴이를 구독 신청하고 새 글 알림을 받을 수 있어.
          </p>
        ) : asleep ? (
          <AsleepNotice>구독 신청과 승인은 깨어난 뒤에 돼.</AsleepNotice>
        ) : loadError ? (
          <p role="alert" className="text-sm text-red-600">
            {loadError}
          </p>
        ) : authors === null ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">글쓴이 목록을 불러오는 중이야…</p>
        ) : authors.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">
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
                        {notifyOn ? '🔔 알림 켬' : '🔕 알림 꺼짐'}
                      </button>
                    )}
                    {/* title은 옆의 🔔 버튼과 같은 형식이다 — 그 버튼엔 있고 이 버튼엔
                        없어서, 되돌릴 수 없는 쪽만 무엇을 하는 버튼인지 안 알려줬다. */}
                    <button
                      type="button"
                      onClick={() => toggleAuthor(a.id)}
                      title={on ? (approved ? '구독 중 (누르면 취소)' : '승인 대기중 (누르면 신청 취소)') : '구독 신청하기'}
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
