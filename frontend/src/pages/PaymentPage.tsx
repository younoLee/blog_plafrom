import { useState } from 'react'
import { Link } from 'react-router-dom'
import { loadTossPayments } from '@tosspayments/tosspayments-sdk'
import { useAuth } from '../auth/auth-context'
import { createCheckout, unsubscribe } from '../api/payments'
import { ui } from '../ui'

// 토스 클라이언트키(프론트 공개용 — 비밀 아님).
// 라이브 전환: 빌드 시 VITE_TOSS_CLIENT_KEY에 라이브 클라이언트키(live_ck_...)를 주입하면 됨.
// 미설정(빈 값)이면 토스 공개 테스트 키로 폴백 → 실제 청구 안 됨.
// (|| 사용: 빈 문자열도 폴백되게. 백엔드 시크릿키와 같은 상점의 키 쌍이어야 승인됨)
const TOSS_CLIENT_KEY =
  import.meta.env.VITE_TOSS_CLIENT_KEY || 'test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq'

// Pro 구독에서 해금되는 것들 (AI 초안의 상위 모델)
const PERKS = [
  { title: 'Claude Opus 4.8', desc: '고품질 장문·복잡한 글 구조 초안' },
  { title: 'Claude Fable 5', desc: '가장 강력한 최신 모델 — 어려운 주제도 정돈' },
  { title: '기본 모델도 그대로', desc: 'Sonnet·Haiku는 무료로 계속 사용' },
]

function PaymentPage() {
  const { user, loading, refreshUser } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  if (loading) return null

  // 로그인 안 했으면 안내
  if (!user) {
    return (
      <div className="mx-auto max-w-md text-center">
        <h1 className={`text-3xl font-bold tracking-tight ${ui.gradientText}`}>Pro 구독</h1>
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
    if (!window.confirm('정말 구독을 해지할까? 상위 AI 모델(Opus·Fable 5)이 다시 잠겨.')) return
    setBusy(true)
    setError('')
    try {
      await unsubscribe()
      await refreshUser()
      setDone(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : '해지에 실패했어')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-lg">
      <div className="relative text-center">
        <div className={ui.glow} />
        <h1 className={`text-4xl font-bold tracking-tight ${ui.gradientText}`}>Pro 구독</h1>
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
              ₩9,900<span className="text-base font-normal text-gray-400"> / 월</span>
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
                      (new Date(user.pro_until).getTime() - Date.now()) / 86400000,
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
              <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[#0071e3]/10 text-[#0071e3] dark:bg-[#0a84ff]/15 dark:text-[#0a84ff]">
                ✓
              </span>
              <div>
                <p className="text-sm font-medium">{p.title}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">{p.desc}</p>
              </div>
            </li>
          ))}
        </ul>

        {error && <p className="mt-5 text-sm text-red-500">{error}</p>}
        {done && !error && (
          <p className="mt-5 text-sm text-emerald-600 dark:text-emerald-400">
            결제 완료! 이제 글쓰기에서 Opus·Fable 5를 선택할 수 있어.
          </p>
        )}

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

      <p className="mt-4 text-center text-xs text-gray-400 dark:text-gray-500">
        ※ 토스페이먼츠 테스트 모드라 실제 카드 승인은 나지만 <b>실제 돈은 청구되지 않아</b>.
        <br />테스트 카드 아무거나 넣으면 돼 (예: 카드번호 4242-4242-4242-4242).
      </p>
    </div>
  )
}

export default PaymentPage
