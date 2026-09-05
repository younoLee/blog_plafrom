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
  // 진행 표시가 없으면 사용자가 버튼을 다시 누른다 → 서버의 10/min 리밋에 걸려
  // "로그인 시도가 너무 많아"를 만난다. **자기가 만든 실패**라 원인을 알 수 없다.
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return // 엔터 연타 방어(버튼 disabled와 별개로 폼 submit이 또 들어온다)
    setError('')
    setBusy(true)
    try {
      await login(email, password)
      navigate('/blog')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative mx-auto max-w-sm">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-accent hover:underline">
        <IconArrowLeft className="h-4 w-4" />홈으로
      </Link>
      <Reveal className="mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
        <h1 className={`mb-6 text-3xl font-semibold tracking-tight ${ui.pageTitle}`}>로그인</h1>
        <form onSubmit={handleSubmit} className="grid gap-3">
          {/* placeholder 는 라벨이 아니다 — 입력을 시작하면 사라지고, 화면낭독기는 칸
              이름을 못 읽는다. 이 저장소가 PostDetailPage·WritePostPage 에 적어둔 규약인데
              정작 로그인 화면이 빠져 있었다(09-04 검사 FQ-4). autoComplete 도 같이 붙인다 —
              비밀번호 관리자가 이 칸을 못 알아보면 사람이 매번 손으로 친다. */}
          <input type="email" placeholder="이메일" aria-label="이메일" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
          <input type="password" placeholder="비밀번호" aria-label="비밀번호" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={input} />
          <button type="submit" className={btnPrimary} disabled={busy} aria-busy={busy}>
            {busy ? '로그인 중…' : '로그인'}
          </button>
          {/* 에러는 스크린리더에도 읽혀야 한다 — 조용히 나타나면 안 보이는 사용자에겐 아무 일도 안 일어난 것이다 */}
          {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        </form>
        <p className="mt-4 text-sm">
          <Link to="/forgot" className="text-gray-500 hover:underline dark:text-gray-400">비밀번호를 잊었어?</Link>
        </p>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          가입은 현재{' '}
          <Link to="/register" className="font-medium text-accent hover:underline">초대제</Link>
          로 운영 중이야
        </p>
      </Reveal>
    </div>
  )
}

export default LoginPage
