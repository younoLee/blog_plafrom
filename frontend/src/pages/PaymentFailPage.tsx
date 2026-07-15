import { Link, useSearchParams } from 'react-router-dom'
import { ui } from '../ui'

// 토스 결제창 실패/취소 시 리다이렉트되는 곳. 토스가 code·message를 쿼리로 넘겨줌.
function PaymentFailPage() {
  const [params] = useSearchParams()
  const message = params.get('message') || '결제가 취소되었거나 실패했어'

  return (
    <div className="mx-auto max-w-md text-center">
      <h1 className="text-2xl font-bold tracking-tight text-red-500">결제 실패</h1>
      <p className="mt-3 text-sm text-gray-600 dark:text-gray-300">{message}</p>
      <div className="mt-6">
        <Link to="/pricing" className={ui.btnPrimary}>다시 시도</Link>
      </div>
    </div>
  )
}

export default PaymentFailPage
