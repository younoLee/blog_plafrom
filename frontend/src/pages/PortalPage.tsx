import { Link } from 'react-router-dom'
import { IconNote, IconActivity, IconArrowRight } from '../components/icons'
import { Reveal } from '../components/Reveal'
import { ui } from '../ui'

// 통합 랜딩(포털): 블로그 / 상태정보 두 군데로 가는 입구
function PortalPage() {
  return (
    <div className="relative py-12">
      {/* 히어로 뒤 오로라: 두 겹 색 번짐을 겹쳐 깊이감 */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-28 -z-10 mx-auto h-80 max-w-3xl">
        <div className="absolute left-1/4 top-0 h-64 w-64 -translate-x-1/2 rounded-full bg-[#0071e3]/30 blur-3xl dark:bg-[#0a84ff]/25" />
        <div className="absolute right-1/4 top-6 h-64 w-64 translate-x-1/2 rounded-full bg-pink-400/25 blur-3xl dark:bg-pink-500/20" />
        <div className="absolute left-1/2 top-2 h-56 w-56 -translate-x-1/2 rounded-full bg-purple-400/25 blur-3xl dark:bg-purple-500/20" />
      </div>

      {/* 대형 그라데이션 헤드라인 */}
      <Reveal className="text-center">
        <h1 className="text-5xl font-semibold tracking-tight sm:text-7xl">
          기록하는{' '}
          <span className={ui.gradientText}>개발자</span>.
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-lg text-gray-500 dark:text-gray-400 sm:text-xl">
          인프라를 직접 만들며 배운 것을 남깁니다.
        </p>
      </Reveal>

      <div className="mt-16 grid gap-5 sm:grid-cols-2">
        {/* 블로그 입구 */}
        <Reveal delay={120}>
          <Link
            to="/blog"
            className="group block h-full rounded-3xl border border-black/[0.07] bg-white p-8 transition hover:-translate-y-1 hover:shadow-[0_12px_40px_rgba(0,0,0,0.1)] dark:border-white/10 dark:bg-white/[0.06]"
          >
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[#0071e3]/10 text-[#0071e3] dark:bg-[#0a84ff]/15 dark:text-[#0a84ff]">
              <IconNote className="h-6 w-6" />
            </div>
            <h2 className="mt-5 text-2xl font-semibold tracking-tight">블로그</h2>
            <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400">
              글 읽고 쓰기, 구독, 댓글
            </p>
            <span className="mt-5 inline-flex items-center gap-1 text-sm font-medium text-[#0071e3] dark:text-[#0a84ff]">
              들어가기 <IconArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
            </span>
          </Link>
        </Reveal>

        {/* 상태정보 입구 */}
        <Reveal delay={220}>
          <Link
            to="/status"
            className="group block h-full rounded-3xl border border-black/[0.07] bg-white p-8 transition hover:-translate-y-1 hover:shadow-[0_12px_40px_rgba(0,0,0,0.1)] dark:border-white/10 dark:bg-white/[0.06]"
          >
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <IconActivity className="h-6 w-6" />
            </div>
            <h2 className="mt-5 text-2xl font-semibold tracking-tight">상태정보</h2>
            <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400">
              서비스 가동 상태 + 통계
            </p>
            <span className="mt-5 inline-flex items-center gap-1 text-sm font-medium text-emerald-600 dark:text-emerald-400">
              보러가기 <IconArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
            </span>
          </Link>
        </Reveal>
      </div>
    </div>
  )
}

export default PortalPage
