import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { previewInvite, type InvitePreview } from '../api/auth'
import { ServerAsleepError } from '../api/http'
import { ui } from '../ui'
import { IconArrowLeft } from '../components/icons'
import { Reveal } from '../components/Reveal'
import { useDocumentTitle } from '../useDocumentTitle'

const { input, btnPrimary } = ui

// 이 페이지는 상태가 둘이다. 라우트를 나누지 않은 이유: 초대 없이 온 사람과 초대로
// 온 사람이 같은 곳(/register)에 도착하는 게 자연스럽고, 안내 문구도 한곳에 모인다.
//
//   /register            → 닫혀 있다는 안내 + 체험 계정  (아래 ClosedNotice)
//   /register?token=xxx  → 실제 가입 폼                  (아래 InviteForm)
//
// **폼을 항상 띄우지 않는 게 핵심이다.** 늘 보이는 폼은 '초대 코드' 입력칸을 요구하고,
// 그러면 사람이 손으로 칠 만큼 짧아야 하고, 짧으면 대입을 막을 장치가 또 필요해진다
// (캡차·짧은 코드는 열린 가입을 전제한 계획이라 2026-08-04에 기각됐다).
// 링크 자체가 초대장이면 칠 게 없고, 칠 게 없으면 추측할 것도 없다.

const card = 'mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 dark:border-white/10 dark:bg-white/[0.06]'

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative mx-auto max-w-sm">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-accent hover:underline">
        <IconArrowLeft className="h-4 w-4" />홈으로
      </Link>
      {children}
    </div>
  )
}

// 안내 카드 셋(닫힘·무효·확인실패)이 문구만 다르고 껍데기가 같아서 하나로 묶는다.
function Notice({ title, children, gradient = false }: { title: string; children: React.ReactNode; gradient?: boolean }) {
  return (
    <Reveal className={`${card} text-center`}>
      <h1 className={`mb-3 text-2xl font-semibold tracking-tight ${gradient ? `text-3xl ${ui.pageTitle}` : ''}`}>{title}</h1>
      {children}
    </Reveal>
  )
}

// 가입은 현재 '초대제'로 닫아둔 상태다. 열어두면 봇이 존재하지 않는 주소로 가입 →
// 하드 바운스 누적 → SES 발송 정지 위험이 생긴다. 그래서 폼을 없애고 '의도적으로
// 닫았다'는 걸 방문자에게 명확히 보여준다 (예전엔 202 + "메일 확인해줘"만 주고
// 메일은 영영 안 왔다 → 깨진 사이트처럼 보였다).
//
// 2026-08-07: 공개 체험 계정(demo@example.com)을 없애면서 그 버튼도 뺐다. 이제
// 로그인 뒤 화면을 보려면 초대를 받아야 한다 — 방문자에게 없는 문을 가리키지 않도록
// 문구도 '읽기는 열려 있다' 쪽으로 고쳤다.
function ClosedNotice() {
  return (
    <Notice title="현재 초대제로 운영 중" gradient>
      <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
        이 블로그는 개인 포트폴리오 프로젝트라, 새 계정 가입은 지금 닫아뒀어.<br />
        글은 로그인 없이 자유롭게 읽고, 댓글도 남길 수 있어.
      </p>
      <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
        초대 링크를 받았다면 그 링크에서 바로 가입돼.
      </p>
      <div className="mt-6 flex flex-col items-center gap-2">
        <Link to="/" className="text-sm text-accent hover:underline">그냥 글만 보러 가기</Link>
        <Link to="/login" className="text-sm text-gray-500 hover:underline dark:text-gray-400">
          초대받은 계정으로 로그인
        </Link>
      </div>
    </Notice>
  )
}

function InviteForm({ token, invite }: { token: string; invite: InvitePreview }) {
  const { redeemInvite } = useAuth()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await redeemInvite(token, password)
      navigate('/') // 이메일 인증 대기가 없으므로 곧장 로그인된 홈으로
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <Reveal className={card}>
      <h1 className={`mb-2 text-3xl font-semibold tracking-tight ${ui.pageTitle}`}>초대 가입</h1>
      <p className="mb-6 text-sm text-gray-600 dark:text-gray-300">
        비밀번호만 정하면 끝이야. 확인 메일을 기다릴 필요 없어.
      </p>
      <form onSubmit={handleSubmit} className="grid gap-3">
        {/* 이메일은 토큰에 묶여 있어 고칠 수 없다. 서버는 요청 본문에서 이메일을 아예
            받지 않으므로, 여기서 바꿔봐야 반영될 곳이 없다 — 그래서 readOnly로 보여만 준다. */}
        <label className="text-xs text-gray-500 dark:text-gray-400">
          초대받은 주소
          <input
            type="email"
            value={invite.email}
            readOnly
            aria-readonly="true"
            className={`${input} mt-1 cursor-not-allowed bg-black/[0.03] text-gray-500 dark:bg-white/[0.03] dark:text-gray-400`}
          />
        </label>
        <input
          type="password"
          placeholder="비밀번호 (8자 이상)"
          aria-label="비밀번호"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
          className={input}
        />
        <button type="submit" disabled={busy} className={btnPrimary}>
          {busy ? '가입하는 중…' : '가입하고 시작하기'}
        </button>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      </form>
      {invite.role === 'pending' && (
        <p className="mt-4 text-xs text-gray-500 dark:text-gray-400">
          가입 직후엔 읽기·댓글만 돼. 글쓰기 권한은 관리자가 따로 켜줘.
        </p>
      )}
    </Reveal>
  )
}

// 링크를 버리라는 안내다. **"확인에 실패했다"와 절대 섞으면 안 된다** —
// 멀쩡한 초대를 만료됐다고 말하면 받은 사람이 진짜로 버린다.
function InvalidNotice() {
  return (
    <Notice title="쓸 수 없는 초대 링크야">
      <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
        만료됐거나 이미 사용된 링크야.<br />
        초대해준 사람에게 새 링크를 받아줘.
      </p>
      <div className="mt-6 flex flex-col items-center gap-2">
        <Link to="/" className="text-sm text-accent hover:underline">그냥 글만 보러 가기</Link>
        <Link to="/login" className="text-sm text-gray-500 hover:underline dark:text-gray-400">이미 계정이 있어</Link>
      </div>
    </Notice>
  )
}

// 확인 중 · 유효 · 무효 · 절전 · 확인실패.
// 상태를 하나의 유니온으로 두는 이유: 앞서 `InvitePreview | false | null` + 별도
// asleep 불리언으로 뒀더니 '무효'와 '확인 실패'가 같은 칸에 눌려 들어갔다. 그래서
// 429(미리보기 30/hour)나 500이 나면 **멀쩡한 초대에 "만료됐다"고 답했다** — 바로
// 위 주석이 막겠다고 한 그 일이다. 상태가 늘어날 때 눌러 담을 자리가 없어야 한다.
type State =
  | { k: 'loading' }
  | { k: 'ok'; invite: InvitePreview }
  | { k: 'invalid' }
  | { k: 'asleep' }
  | { k: 'failed' }

function RegisterPage() {
  useDocumentTitle('초대 가입')
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [state, setState] = useState<State>({ k: 'loading' })

  useEffect(() => {
    if (!token) return
    previewInvite(token)
      .then((r) => setState(r ? { k: 'ok', invite: r } : { k: 'invalid' }))
      .catch((e) => setState({ k: e instanceof ServerAsleepError ? 'asleep' : 'failed' }))
  }, [token])

  if (!token) return <Shell><ClosedNotice /></Shell>

  switch (state.k) {
    case 'loading':
      return (
        <Shell>
          <p className="mt-8 text-center text-sm text-gray-500 dark:text-gray-400">초대를 확인하는 중…</p>
        </Shell>
      )
    case 'ok':
      return <Shell><InviteForm token={token} invite={state.invite} /></Shell>
    case 'invalid':
      return <Shell><InvalidNotice /></Shell>
    case 'asleep':
      return (
        <Shell>
          <Notice title="서버가 절전 중이야">
            <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
              개인 프로젝트라 안 쓸 땐 서버를 꺼둬. <span className="font-medium">초대 링크가 만료된 건 아니니까</span><br />
              잠시 뒤에 다시 열어줘.
            </p>
          </Notice>
        </Shell>
      )
    case 'failed':
      return (
        <Shell>
          <Notice title="초대를 확인하지 못했어">
            <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
              링크에 문제가 있는 게 아니라 확인이 안 된 거야.<br />
              잠시 뒤에 다시 열어줘.
            </p>
          </Notice>
        </Shell>
      )
  }
}

export default RegisterPage
