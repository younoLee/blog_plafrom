import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { verifyEmail } from '../api/auth'
import { ui } from '../ui'

type Status = 'loading' | 'ok' | 'fail'

function VerifyPage() {
  const [params] = useSearchParams()
  const [status, setStatus] = useState<Status>('loading')

  // 링크의 ?token= 으로 인증 처리 (한 번만)
  // setState는 전부 .then/.catch 안에서만 (effect 동기 setState 금지 룰)
  useEffect(() => {
    const token = params.get('token')
    Promise.resolve()
      .then(() => {
        if (!token) throw new Error('토큰 없음')
        return verifyEmail(token)
      })
      .then(() => setStatus('ok'))
      .catch(() => setStatus('fail'))
  }, [params])

  return (
    <div className="relative mx-auto max-w-sm text-center">
      <div aria-hidden className={ui.glow} />
      <div className="rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
        {status === 'loading' && <p className="text-gray-500 dark:text-gray-400">인증 처리 중…</p>}
        {status === 'ok' && (
          <>
            <h1 className={`mb-3 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>인증 완료!</h1>
            <p className="text-sm text-gray-600 dark:text-gray-300">
              이메일 인증이 끝났어. 이제 로그인할 수 있어.<br />
              (글쓰기는 관리자 승인 후 가능해)
            </p>
            <Link to="/login" className={`mt-6 inline-block ${ui.btnPrimary}`}>로그인하러 가기</Link>
          </>
        )}
        {status === 'fail' && (
          <>
            <h1 className="mb-3 text-3xl font-semibold tracking-tight text-red-500">인증 실패</h1>
            <p className="text-sm text-gray-600 dark:text-gray-300">
              링크가 유효하지 않거나 만료됐어. 로그인해 보거나 관리자에게 문의해줘.
            </p>
            <Link to="/login" className={`mt-6 inline-block ${ui.btnPrimary}`}>로그인하러 가기</Link>
          </>
        )}
      </div>
    </div>
  )
}

export default VerifyPage
