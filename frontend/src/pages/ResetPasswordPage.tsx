import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { resetPassword } from '../api/auth'
import { ui } from '../ui'
import { Reveal } from '../components/Reveal'

const { input, btnPrimary } = ui

function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    try {
      await resetPassword(token, password)
      setDone(true)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="relative mx-auto max-w-sm">
      <Reveal className="rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
        {done ? (
          <div className="text-center">
            <h1 className={`mb-3 text-3xl font-semibold tracking-tight ${ui.pageTitle}`}>변경 완료!</h1>
            <p className="text-sm text-gray-600 dark:text-gray-300">새 비밀번호로 로그인할 수 있어.</p>
            <Link to="/login" className={`mt-6 inline-block ${btnPrimary}`}>로그인하러 가기</Link>
          </div>
        ) : !token ? (
          <div className="text-center">
            <h1 className="mb-3 text-3xl font-semibold tracking-tight text-red-500">잘못된 링크</h1>
            <p className="text-sm text-gray-600 dark:text-gray-300">토큰이 없어. 재설정 메일의 링크로 다시 들어와줘.</p>
            <Link to="/forgot" className={`mt-6 inline-block ${btnPrimary}`}>비밀번호 찾기</Link>
          </div>
        ) : (
          <>
            <h1 className={`mb-6 text-3xl font-semibold tracking-tight ${ui.pageTitle}`}>새 비밀번호</h1>
            <form onSubmit={handleSubmit} className="grid gap-3">
              {/* 길이를 브라우저가 먼저 막는다 — 서버까지 갔다가 422를 받는 것보다 낫고,
                  그 422가 "링크 만료"로 잘못 번역되던 자리이기도 하다(api/auth.ts 주석). */}
              <input type="password" placeholder="새 비밀번호 (8자 이상)" aria-label="새 비밀번호" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} maxLength={72} required className={input} />
              <button type="submit" className={btnPrimary}>비밀번호 변경</button>
              {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
            </form>
          </>
        )}
      </Reveal>
    </div>
  )
}

export default ResetPasswordPage
