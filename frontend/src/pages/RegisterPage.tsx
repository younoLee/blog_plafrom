import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'

const { input, btnPrimary } = ui

function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    try {
      await register(email, password)
      navigate('/blog')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="mx-auto max-w-sm">
      <Link to="/" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">← 홈으로</Link>
      <div className="mt-4 rounded-xl border border-gray-200 bg-white p-8 shadow-sm dark:border-gray-800 dark:bg-gray-800">
        <h1 className="mb-6 text-2xl font-bold text-gray-900 dark:text-white">회원가입</h1>
        <form onSubmit={handleSubmit} className="grid gap-3">
          <input type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
          <input type="password" placeholder="비밀번호" value={password} onChange={(e) => setPassword(e.target.value)} className={input} />
          <button type="submit" className={btnPrimary}>회원가입</button>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </form>
        <p className="mt-5 text-sm text-gray-500 dark:text-gray-400">
          이미 계정이 있어?{' '}
          <Link to="/login" className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">로그인</Link>
        </p>
      </div>
    </div>
  )
}

export default RegisterPage
