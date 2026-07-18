import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { confirmPayment } from '../api/payments'
import { ui } from '../ui'

// 토스 결제창 성공 후 리다이렉트되는 곳.
// 쿼리(paymentKey·orderId·amount)를 서버로 넘겨 승인을 '검증'한 뒤에야 구독이 켜진다.
function PaymentSuccessPage() {
  const [params] = useSearchParams()
  const { refreshUser } = useAuth()
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading')
  const [error, setError] = useState('')
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current) return // StrictMode 이중 실행 방지 (승인은 한 번만)
    ran.current = true
    const paymentKey = params.get('paymentKey')
    const orderId = params.get('orderId')
    const amount = Number(params.get('amount'))
    if (!paymentKey || !orderId || !amount) {
      // 마운트 1회 검증(ran.current 가드)에서 잘못된 쿼리면 즉시 에러 표시 — 의도된 동기 setState.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setState('error')
      setError('결제 정보가 올바르지 않아')
      return
    }
    confirmPayment(paymentKey, orderId, amount)
      .then(async () => {
        await refreshUser()
        setState('ok')
      })
      .catch((e) => {
        setState('error')
        setError(e instanceof Error ? e.message : '결제 승인에 실패했어')
      })
  }, [params, refreshUser])

  return (
    <div className="mx-auto max-w-md text-center">
      {state === 'loading' && (
        <>
          <h1 className="text-2xl font-bold tracking-tight">결제 승인 중…</h1>
          <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">잠깐만 기다려줘.</p>
        </>
      )}
      {state === 'ok' && (
        <>
          <h1 className={`text-3xl font-bold tracking-tight ${ui.gradientText}`}>결제 완료 🎉</h1>
          <p className="mt-3 text-sm text-gray-600 dark:text-gray-300">
            Pro 구독이 켜졌어. 이제 글쓰기에서 <b>Opus 4.8·Fable 5</b>를 선택할 수 있어.
          </p>
          <div className="mt-6 flex justify-center gap-2">
            <Link to="/blog/new" className={ui.btnPrimary}>글쓰기로 가기</Link>
            <Link to="/pricing" className={ui.btnGhost}>구독 화면</Link>
          </div>
        </>
      )}
      {state === 'error' && (
        <>
          <h1 className="text-2xl font-bold tracking-tight text-red-500">결제 승인 실패</h1>
          <p className="mt-3 text-sm text-gray-600 dark:text-gray-300">{error}</p>
          <div className="mt-6">
            <Link to="/pricing" className={ui.btnPrimary}>다시 시도</Link>
          </div>
        </>
      )}
    </div>
  )
}

export default PaymentSuccessPage
