import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { ui } from '../ui'

// 가입은 초대제로 닫혀 있으므로, 방문자(면접관 등)가 로그인 뒤 화면 — 에디터·AI 초안·설정 —
// 을 직접 둘러볼 수 있게 미리 만든 '체험 계정'으로 로그인시킨다.
// 계정은 scripts/create_user.py --demo 로 만든다(writer, email_verified). 자격증명은 공개가 목적.
// AI는 유저당 캡(시간10/일20/월200)이 걸려 있고 데모 계정 하나를 다 함께 쓰므로 비용이 묶인다.
const DEMO_EMAIL = import.meta.env.VITE_DEMO_EMAIL ?? 'demo@example.com'
const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD ?? 'demo1234!'

function DemoLoginButton({ className = '' }: { className?: string }) {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleClick() {
    setError('')
    setLoading(true)
    try {
      await login(DEMO_EMAIL, DEMO_PASSWORD)
      navigate('/') // 로그인 상태로 홈에 — 헤더에 '글쓰기·설정'이 나타난다
    } catch {
      setError('체험 계정 로그인에 실패했어. 잠시 후 다시 시도해줘.')
      setLoading(false)
    }
  }

  return (
    <div className={className}>
      <button type="button" onClick={handleClick} disabled={loading} className={`${ui.btnGhost} w-full`}>
        {loading ? '들어가는 중…' : '체험 계정으로 둘러보기'}
      </button>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  )
}

export default DemoLoginButton
