import { Link } from 'react-router-dom'
import { ui } from '../ui'
import { IconArrowLeft } from '../components/icons'
import { Reveal } from '../components/Reveal'
import DemoLoginButton from '../components/DemoLoginButton'

// 가입은 현재 '초대제'로 닫아둔 상태다. 열어두면 봇이 존재하지 않는 주소로 가입 →
// 하드 바운스 누적 → SES 발송 정지 위험이 생기고, 포트폴리오 시연에는 검증된 주소로 충분하다.
// 그래서 폼을 없애고 '의도적으로 닫았다'는 걸 방문자에게 명확히 보여준다
// (예전엔 202 + "메일 확인해줘"만 주고 메일은 영영 안 왔다 → 깨진 사이트처럼 보였다).
function RegisterPage() {
  return (
    <div className="relative mx-auto max-w-sm">
      <div aria-hidden className={ui.glow} />
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-[#0071e3] hover:underline dark:text-[#0a84ff]">
        <IconArrowLeft className="h-4 w-4" />홈으로
      </Link>
      <Reveal className="mt-4 rounded-2xl border border-black/[0.07] bg-white p-8 text-center dark:border-white/10 dark:bg-white/[0.06]">
        <h1 className={`mb-3 text-3xl font-semibold tracking-tight ${ui.gradientText}`}>현재 초대제로 운영 중</h1>
        <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
          이 블로그는 개인 포트폴리오 프로젝트라, 새 계정 가입은 지금 닫아뒀어.<br />
          글은 로그인 없이 자유롭게 읽고, 댓글도 남길 수 있어.<br />
          글쓰기·AI 초안 같은 로그인 화면이 궁금하면 <span className="font-medium">체험 계정</span>으로 둘러봐.
        </p>
        <DemoLoginButton className="mt-6" />
        <div className="mt-4 flex flex-col items-center gap-2">
          <Link to="/" className="text-sm text-[#0071e3] hover:underline dark:text-[#0a84ff]">그냥 글만 보러 가기</Link>
          <Link to="/login" className="text-sm text-gray-500 hover:underline dark:text-gray-400">
            초대받은 계정으로 로그인
          </Link>
        </div>
      </Reveal>
    </div>
  )
}

export default RegisterPage
