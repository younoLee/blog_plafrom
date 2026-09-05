import { useState } from 'react'
import { Link } from 'react-router-dom'
import { forgotPassword } from '../api/auth'
import { ui } from '../ui'
import { IconArrowLeft } from '../components/icons'
import { Reveal } from '../components/Reveal'
import { useDocumentTitle } from '../useDocumentTitle'

const { input, btnPrimary } = ui

function ForgotPasswordPage() {
  useDocumentTitle('비밀번호 찾기')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)
  // 진행 표시가 없으면 사용자가 버튼을 다시 누른다 → 서버의 5/hour 리밋에 걸려
  // "시도가 너무 많아"를 만난다. **자기가 만든 실패**라 원인을 알 수 없고, 하필
  // 이 화면은 '지금 못 하면 계정이 잠긴 것과 같은' 자리다. LoginPage 가 같은 이유로
  // 진작 busy 를 들고 있었는데 여기와 재설정 화면만 빠져 있었다(09-04 검사 FE-14).
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return // 엔터 연타 방어(버튼 disabled와 별개로 폼 submit이 또 들어온다)
    setError('')
    setBusy(true)
    try {
      await forgotPassword(email)
      setSent(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative mx-auto max-w-sm">
      <Link to="/login" className="inline-flex items-center gap-1 text-sm text-accent hover:underline">
        <IconArrowLeft className="h-4 w-4" />로그인으로
      </Link>
      <Reveal className="mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]">
        {sent ? (
          <div className="text-center">
            <h1 className={`mb-3 text-3xl font-semibold tracking-tight ${ui.pageTitle}`}>메일을 확인해줘</h1>
            <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
              가입된 이메일이라면 재설정 링크를 보냈어.<br />
              메일의 링크를 눌러 새 비밀번호를 설정해줘 (1시간 안에).
            </p>
            <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">(로컬은 Mailpit http://localhost:8025)</p>
          </div>
        ) : (
          <>
            <h1 className={`mb-2 text-3xl font-semibold tracking-tight ${ui.pageTitle}`}>비밀번호 찾기</h1>
            <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">가입한 이메일을 입력하면 재설정 링크를 보내줄게.</p>
            <form onSubmit={handleSubmit} className="grid gap-3">
              <input type="email" placeholder="이메일" aria-label="이메일" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
              <button type="submit" className={btnPrimary} disabled={busy} aria-busy={busy}>
                {busy ? '보내는 중…' : '재설정 링크 받기'}
              </button>
              {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
            </form>
          </>
        )}
      </Reveal>
    </div>
  )
}

export default ForgotPasswordPage
