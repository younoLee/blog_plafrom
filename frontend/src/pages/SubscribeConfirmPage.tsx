import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { confirmSubscription } from '../api/subscribers'
import { ui } from '../ui'

type Status = 'loading' | 'ok' | 'fail'

function SubscribeConfirmPage() {
  const [params] = useSearchParams()
  const [status, setStatus] = useState<Status>('loading')

  // 링크의 ?token= 으로 구독 확정 (한 번만)
  // setState는 전부 .then/.catch 안에서만 (effect 동기 setState 금지 룰)
  useEffect(() => {
    const token = params.get('token')
    Promise.resolve()
      .then(() => {
        if (!token) throw new Error('토큰 없음')
        return confirmSubscription(token)
      })
      .then(() => setStatus('ok'))
      .catch(() => setStatus('fail'))
  }, [params])

  return (
    <div className="relative mx-auto max-w-sm text-center">
      <div aria-hidden className={ui.glow} />
      <div className="rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
        {status === 'loading' && <p className="text-gray-500 dark:text-gray-400">구독 확인 중…</p>}
        {status === 'ok' && (
          <>
            <h1 className={`mb-3 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>구독 완료!</h1>
            <p className="text-sm text-gray-600 dark:text-gray-300">
              이제 새 공개글이 올라오면 이메일로 알림을 받아.
            </p>
            <Link to="/blog" className={`mt-6 inline-block ${ui.btnPrimary}`}>블로그로 가기</Link>
          </>
        )}
        {status === 'fail' && (
          <>
            <h1 className="mb-3 text-3xl font-semibold tracking-tight text-red-500">확인 실패</h1>
            <p className="text-sm text-gray-600 dark:text-gray-300">
              링크가 유효하지 않거나 만료됐어. 구독 신청을 다시 해줘.
            </p>
            <Link to="/subscriptions" className={`mt-6 inline-block ${ui.btnPrimary}`}>구독 관리로</Link>
          </>
        )}
      </div>
    </div>
  )
}

export default SubscribeConfirmPage
