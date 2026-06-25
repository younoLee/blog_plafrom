import { useState } from 'react'
import { Link } from 'react-router-dom'
import { forgotPassword } from '../api/auth'
import { ui } from '../ui'
import { IconArrowLeft } from '../components/icons'
import { Reveal } from '../components/Reveal'

const { input, btnPrimary } = ui

function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    try {
      await forgotPassword(email)
      setSent(true)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="relative mx-auto max-w-sm">
      <div aria-hidden className={ui.glow} />
      <Link to="/login" className="inline-flex items-center gap-1 text-sm text-[#0071e3] hover:underline dark:text-[#0a84ff]">
        <IconArrowLeft className="h-4 w-4" />로그인으로
      </Link>
      <Reveal className="mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
        {sent ? (
          <div className="text-center">
            <h1 className={`mb-3 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>메일을 확인해줘</h1>
            <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
              가입된 이메일이라면 재설정 링크를 보냈어.<br />
              메일의 링크를 눌러 새 비밀번호를 설정해줘 (1시간 안에).
            </p>
            <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">(로컬은 Mailpit http://localhost:8025)</p>
          </div>
        ) : (
          <>
            <h1 className={`mb-2 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>비밀번호 찾기</h1>
            <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">가입한 이메일을 입력하면 재설정 링크를 보내줄게.</p>
            <form onSubmit={handleSubmit} className="grid gap-3">
              <input type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
              <button type="submit" className={btnPrimary}>재설정 링크 받기</button>
              {error && <p className="text-sm text-red-600">{error}</p>}
            </form>
          </>
        )}
      </Reveal>
    </div>
  )
}

export default ForgotPasswordPage
