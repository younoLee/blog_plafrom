import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'
import { IconArrowLeft } from '../components/icons'
import { Reveal } from '../components/Reveal'

const { input, btnPrimary } = ui

function RegisterPage() {
  const { register } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false) // 가입 성공 → 확인메일 안내 화면

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    try {
      await register(email, password)
      setSent(true)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="relative mx-auto max-w-sm">
      <div aria-hidden className={ui.glow} />
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-[#0071e3] hover:underline dark:text-[#0a84ff]">
        <IconArrowLeft className="h-4 w-4" />홈으로
      </Link>
      <Reveal className="mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
        {sent ? (
          // 가입 후: 메일 인증 안내 (자동 로그인 안 함)
          <div className="text-center">
            <h1 className={`mb-3 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>메일을 확인해줘</h1>
            <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
              <span className="font-medium">{email}</span> 으로 인증 링크를 보냈어.<br />
              메일의 링크를 누르면 가입이 완료돼.
            </p>
            <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
              (로컬 개발 중엔 Mailpit http://localhost:8025 에서 확인)
            </p>
            <Link to="/login" className={`mt-6 inline-block ${btnPrimary}`}>로그인하러 가기</Link>
          </div>
        ) : (
          <>
            <h1 className={`mb-6 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>회원가입</h1>
            <form onSubmit={handleSubmit} className="grid gap-3">
              <input type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
              <input type="password" placeholder="비밀번호 (8자 이상)" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} className={input} />
              <button type="submit" className={btnPrimary}>회원가입</button>
              {error && <p className="text-sm text-red-600">{error}</p>}
            </form>
            <p className="mt-5 text-sm text-gray-500 dark:text-gray-400">
              이미 계정이 있어?{' '}
              <Link to="/login" className="font-medium text-[#0071e3] hover:underline dark:text-[#0a84ff]">로그인</Link>
            </p>
          </>
        )}
      </Reveal>
    </div>
  )
}

export default RegisterPage
