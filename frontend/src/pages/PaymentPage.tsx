import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { loadTossPayments } from '@tosspayments/tosspayments-sdk'
import { useAuth } from '../auth/auth-context'
import { createCheckout, fetchMyPayments, unsubscribe, type PaymentRow } from '../api/payments'
import { ui } from '../ui'
import { useDocumentTitle } from '../useDocumentTitle'

// 토스 클라이언트키(프론트 공개용 — 비밀 아님).
// 라이브 전환: 빌드 시 VITE_TOSS_CLIENT_KEY에 라이브 클라이언트키(live_ck_...)를 주입하면 됨.
// 미설정(빈 값)이면 토스 공개 테스트 키로 폴백 → 실제 청구 안 됨.
// (|| 사용: 빈 문자열도 폴백되게. 백엔드 시크릿키와 같은 상점의 키 쌍이어야 승인됨)
const TOSS_CLIENT_KEY =
  import.meta.env.VITE_TOSS_CLIENT_KEY || 'test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq'

// Pro 구독에서 해금되는 것들 (AI 초안의 상위 모델)
const PERKS = [
  { title: 'Claude Opus 4.8', desc: '고품질 장문·복잡한 글 구조 초안' },
  { title: 'Claude Fable 5', desc: '가장 강력한 최신 모델. 어려운 주제도 정돈해줘' },
  { title: '기본 모델도 그대로', desc: 'Sonnet·Haiku는 무료로 계속 사용' },
]

const STATUS_LABEL: Record<string, string> = {
  paid: '결제 완료',
  // **확인 중은 실패가 아니다.** 토스 승인을 기다리는 짧은 상태이고, 실패로 읽히면
  // 사용자가 다시 결제해서 두 번 낼 수 있다(backend models/payment.py).
  confirming: '확인 중',
  pending: '결제 안 함',
  failed: '실패',
}

/**
 * 내 결제 내역.
 *
 * **왜 필요한가 (09-04 검사 GAP-7)** — 그전까지 '얼마를 언제 냈나'를 확인할 방법이
 * 카드사 명세서뿐이었다. 결제는 이 사이트에서 돈이 오가는 유일한 자리다.
 * 실패·대기 주문도 보여준다 — 성공만 보여주면 '결제가 안 됐는데 돈이 빠져나간 것
 * 같다'는 상황에서 화면이 아무 말도 안 하게 된다.
 */
function PaymentHistory() {
  const [rows, setRows] = useState<PaymentRow[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    fetchMyPayments()
      .then(setRows)
      .catch(() => setFailed(true))
  }, [])

  if (failed) {
    return (
      <section className="mt-8">
        <h2 className="mb-2 text-lg font-semibold tracking-tight">결제 내역</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          지금은 못 불러왔어 (서버 정지 또는 장애).
        </p>
      </section>
    )
  }
  if (rows === null) return null

  return (
    <section className="mt-8">
      <h2 className="mb-2 text-lg font-semibold tracking-tight">결제 내역</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">아직 결제한 적이 없어.</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((p) => (
            <li
              key={p.order_id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-black/[0.07] bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-white/[0.06]"
            >
              <span className="font-medium">{p.amount.toLocaleString('ko-KR')}원</span>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {STATUS_LABEL[p.status] ?? p.status}
              </span>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {new Date(p.paid_at ?? p.created_at).toLocaleDateString('ko-KR')}
              </span>
              {p.receipt_url && (
                <a
                  href={p.receipt_url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-auto text-xs font-medium text-accent underline"
                >
                  영수증
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function PaymentPage() {
  useDocumentTitle('유료 구독')
  const { user, loading, refreshUser } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // '며칠 남음' 계산용 '지금' 시각을 마운트 시 한 번만 스냅샷 (렌더 중 Date.now() 직접 호출 = 비순수).
  const [now] = useState(() => Date.now())

  if (loading) return null

  // 로그인 안 했으면 안내
  if (!user) {
    return (
      <div className="mx-auto max-w-md text-center">
        <h1 className={`text-3xl font-bold tracking-tight ${ui.pageTitle}`}>Pro 구독</h1>
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
          구독하려면 먼저 로그인해줘.
        </p>
        <div className="mt-6">
          <Link to="/login" className={ui.btnPrimary}>로그인</Link>
        </div>
      </div>
    )
  }

  const isPro = user.is_pro || user.role === 'admin'

  async function handleSubscribe() {
    setBusy(true)
    setError('')
    try {
      // 1) 서버가 주문 생성(orderId·금액 확정)
      const { order_id, amount, order_name } = await createCheckout()
      // 2) 토스 결제창 열기 → 성공 시 successUrl로 리다이렉트(거기서 서버 승인검증)
      const toss = await loadTossPayments(TOSS_CLIENT_KEY)
      const payment = toss.payment({ customerKey: `user_${user!.id}` })
      await payment.requestPayment({
        method: 'CARD',
        amount: { currency: 'KRW', value: amount },
        orderId: order_id,
        orderName: order_name,
        customerEmail: user!.email,
        successUrl: `${window.location.origin}/payment/success`,
        failUrl: `${window.location.origin}/payment/fail`,
      })
      // 정상 흐름이면 위에서 리다이렉트되어 아래는 실행되지 않음
    } catch (e) {
      // 사용자가 결제창을 닫거나 실패 시 여기로 옴
      const msg = e instanceof Error ? e.message : '결제를 진행하지 못했어'
      // 토스 SDK의 사용자 취소는 조용히 넘어가도 되지만, 그 외엔 표시
      if (!/취소|cancel/i.test(msg)) setError(msg)
      setBusy(false)
    }
  }

  async function handleUnsubscribe() {
    // **남은 기간이 즉시 사라진다는 사실을 적는다** (09-04 검사 GAP-7).
    // 환불이 없으므로 이 동작은 '다음 결제를 안 한다'가 아니라 '지금 산 것을 지금
    // 버린다'에 가깝다. 그 차이를 안 적으면 사용자는 만료일까지는 쓸 수 있다고 믿는다.
    const left =
      user?.pro_until != null
        ? Math.max(0, Math.ceil((new Date(user.pro_until).getTime() - now) / 86400000))
        : null
    const warning =
      left != null
        ? `정말 구독을 해지할까? 남은 ${left}일이 바로 사라지고 환불은 없어. 상위 AI 모델(Opus·Fable 5)도 다시 잠겨.`
        : '정말 구독을 해지할까? 상위 AI 모델(Opus·Fable 5)이 다시 잠겨.'
    if (!window.confirm(warning)) return
    setBusy(true)
    setError('')
    try {
      await unsubscribe()
      await refreshUser()
    } catch (e) {
      setError(e instanceof Error ? e.message : '해지에 실패했어')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-lg">
      <div className="relative text-center">
        <h1 className={`text-4xl font-bold tracking-tight ${ui.pageTitle}`}>Pro 구독</h1>
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
          결제하면 AI 초안에서 최상위 Claude 모델을 쓸 수 있어.
        </p>
      </div>

      {/* 요금 카드 */}
      <div className={`${ui.card} mt-8`}>
        <div className="flex items-baseline justify-between">
          <div>
            <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Pro 플랜</p>
            <p className="mt-1 text-3xl font-bold tracking-tight">
              ₩9,900<span className="text-base font-normal text-gray-500 dark:text-gray-400"> / 월</span>
            </p>
          </div>
          {isPro && (
            <div className="text-right">
              <span className="inline-block rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                구독 중
              </span>
              {user.pro_until && (
                <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
                  {new Date(user.pro_until).toLocaleDateString('ko-KR')}까지
                  {(() => {
                    const days = Math.ceil(
                      (new Date(user.pro_until).getTime() - now) / 86400000,
                    )
                    return days > 0 ? ` (${days}일 남음)` : ''
                  })()}
                </p>
              )}
            </div>
          )}
        </div>

        <ul className="mt-5 space-y-3">
          {PERKS.map((p) => (
            <li key={p.title} className="flex gap-3">
              <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-accent/10 text-accent">
                ✓
              </span>
              <div>
                <p className="text-sm font-medium">{p.title}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">{p.desc}</p>
              </div>
            </li>
          ))}
        </ul>

        {error && <p role="alert" className="mt-5 text-sm text-red-500">{error}</p>}
        {/* '결제 완료!' 문구가 여기 있었는데 **켜질 경로가 없었다** — setDone(true)가
            저장소 어디에도 없고, 유일한 호출이 해지 경로의 setDone(false)였다
            (09-04 검사 FE-9). 성공 안내는 결제 뒤 돌아오는 PaymentSuccessPage 가 한다.
            도달 불가능한 UI 는 '있다'고 착각하게 만들어서, 없느니만 못하다. */}

        <div className="mt-6">
          {isPro ? (
            user.role === 'admin' ? (
              <p className="text-sm text-gray-500 dark:text-gray-400">
                관리자 계정은 이미 모든 모델을 쓸 수 있어.
              </p>
            ) : (
              <button
                type="button"
                onClick={handleUnsubscribe}
                disabled={busy}
                className={`${ui.btnGhost} w-full disabled:opacity-50`}
              >
                {busy ? '처리 중…' : '구독 해지'}
              </button>
            )
          ) : (
            <button
              type="button"
              onClick={handleSubscribe}
              disabled={busy}
              className={`${ui.btnPrimary} w-full disabled:opacity-50`}
            >
              {busy ? '결제창 여는 중…' : '결제하고 구독하기'}
            </button>
          )}
        </div>
      </div>

      <PaymentHistory />

      <p className="mt-4 text-center text-xs text-gray-500 dark:text-gray-400">
        ※ 토스페이먼츠 테스트 모드라 실제 카드 승인은 나지만 <b>실제 돈은 청구되지 않아</b>.
        <br />테스트 카드 아무거나 넣으면 돼 (예: 카드번호 4242-4242-4242-4242).
      </p>
    </div>
  )
}

export default PaymentPage
