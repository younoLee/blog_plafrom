import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { IconNote, IconActivity, IconArrowRight } from '../components/icons'
import { Reveal } from '../components/Reveal'
import { ui } from '../ui'

// 통합 랜딩(포털): 최근 개발일지 + 블로그/상태정보 두 입구

/** 빌드가 만든 정적 목록(dist/devlog-index.json). **API가 아니다** —
 *  이 사이트는 EC2를 평소 꺼두므로, 첫 화면이 서버에 의존하면 방문자가 가장 흔하게
 *  보는 상태가 빈 화면이 된다. 그래서 S3에 정적으로 놓인 파일을 읽는다.
 *  생성 근거는 frontend/scripts/gen-static.mjs의 '2-B' 절 주석 참고. */
type DevlogIndex = {
  total: number
  chars: number
  posts: { date: string; title: string; slug: string; summary: string }[]
}

const PREVIEW = 5

function PortalPage() {
  const [index, setIndex] = useState<DevlogIndex | null>(null)
  // 실패해도 포털은 그대로 뜬다(입구 카드는 이 데이터와 무관하다). 로컬 dev 서버에는
  // 이 파일이 없어서 404가 정상이다 — 그때 콘솔을 더럽히지 않도록 조용히 접는다.
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    fetch('/devlog-index.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: DevlogIndex) => {
        if (alive && Array.isArray(d?.posts)) setIndex(d)
      })
      .catch(() => {
        if (alive) setFailed(true)
      })
    return () => {
      alive = false
    }
  }, [])

  const recent = index?.posts.slice(0, PREVIEW) ?? []

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
        {index && (
          <p className="mt-3 text-sm text-gray-400 dark:text-gray-500">
            개발일지 {index.total}편 · 약 {Math.round(index.chars / 10000)}만 자
          </p>
        )}
      </Reveal>

      {/* 최근 개발일지 — **입구 카드보다 위에 둔다.** 방문자가 첫 화면에서 봐야 하는
          것은 '어디로 갈까'가 아니라 '무엇이 있나'다.
          링크는 SPA 라우트가 아니라 정적 아카이브다 — 서버가 꺼져 있어도 열린다.
          위 목록에 Reveal(opacity-0 시작)을 씌우지 않은 것도 같은 이유다. */}
      {!failed && (
        <section className="mt-14" aria-labelledby="recent-devlog">
          <div className="flex items-baseline justify-between gap-4">
            <h2 id="recent-devlog" className="text-xl font-semibold tracking-tight">
              최근 개발일지
            </h2>
            <a
              href="/devlog.html"
              className="shrink-0 text-sm font-medium text-[#0071e3] hover:underline dark:text-[#0a84ff]"
            >
              전체 보기 →
            </a>
          </div>

          <ul className="mt-4 divide-y divide-black/[0.07] border-y border-black/[0.07] dark:divide-white/10 dark:border-white/10">
            {(index ? recent : Array.from({ length: PREVIEW }, () => null)).map((p, i) => (
              <li key={p ? p.date : i}>
                {p ? (
                  <a href={`/${p.slug}`} className="group block py-4">
                    <div className="flex items-baseline gap-3">
                      <time className="shrink-0 font-mono text-xs text-gray-400 dark:text-gray-500">
                        {p.date}
                      </time>
                      <h3 className="font-medium group-hover:text-[#0071e3] dark:group-hover:text-[#0a84ff]">
                        {p.title}
                      </h3>
                    </div>
                    {p.summary && (
                      <p className="mt-1.5 line-clamp-2 text-sm text-gray-500 dark:text-gray-400">
                        {p.summary}
                      </p>
                    )}
                  </a>
                ) : (
                  // 뼈대: 목록이 늦게 와도 아래 카드가 밀려 올라갔다 내려오지 않게 자리를 잡아둔다
                  <div className="py-4" aria-hidden>
                    <div className="h-4 w-2/3 rounded bg-black/[0.06] dark:bg-white/10" />
                    <div className="mt-2.5 h-3 w-full rounded bg-black/[0.04] dark:bg-white/[0.06]" />
                  </div>
                )}
              </li>
            ))}
          </ul>

          <p className="mt-3 text-xs text-gray-400 dark:text-gray-500">
            이 목록과 링크는 서버 없이 동작합니다 · <a href="/rss.xml" className="hover:underline">RSS</a>
          </p>
        </section>
      )}

      <div className="mt-14 grid gap-5 sm:grid-cols-2">
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
