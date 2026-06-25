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
      <div aria-hidden className={ui.glow} />
      <Reveal className="rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
        {done ? (
          <div className="text-center">
            <h1 className={`mb-3 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>변경 완료!</h1>
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
            <h1 className={`mb-6 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>새 비밀번호</h1>
            <form onSubmit={handleSubmit} className="grid gap-3">
              <input type="password" placeholder="새 비밀번호" value={password} onChange={(e) => setPassword(e.target.value)} className={input} />
              <button type="submit" className={btnPrimary}>비밀번호 변경</button>
              {error && <p className="text-sm text-red-600">{error}</p>}
            </form>
          </>
        )}
      </Reveal>
    </div>
  )
}

export default ResetPasswordPage
