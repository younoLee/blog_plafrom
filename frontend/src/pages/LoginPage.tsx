import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'
import { IconArrowLeft } from '../components/icons'
import { Reveal } from '../components/Reveal'

const { input, btnPrimary } = ui

function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    try {
      await login(email, password)
      navigate('/blog')
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
        <h1 className={`mb-6 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>로그인</h1>
        <form onSubmit={handleSubmit} className="grid gap-3">
          <input type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
          <input type="password" placeholder="비밀번호" value={password} onChange={(e) => setPassword(e.target.value)} className={input} />
          <button type="submit" className={btnPrimary}>로그인</button>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </form>
        <p className="mt-4 text-sm">
          <Link to="/forgot" className="text-gray-500 hover:underline dark:text-gray-400">비밀번호를 잊었어?</Link>
        </p>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          계정이 없어?{' '}
          <Link to="/register" className="font-medium text-[#0071e3] hover:underline dark:text-[#0a84ff]">회원가입</Link>
        </p>
      </Reveal>
    </div>
  )
}

export default LoginPage
