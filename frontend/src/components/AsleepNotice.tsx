/**
 * 서버 절전 안내 — 공통 문장을 한 자리에 둔다.
 *
 * **왜 컴포넌트로 뽑았나 (2026-08-27)** — 같은 한 문장이 다섯 파일에 손으로 복제돼
 * 있었고, 이미 다섯 갈래로 갈라져 있었다. 💤 를 붙인 곳과 안 붙인 곳, 문장을 마침표로
 * 끊은 곳과 em 대시로 이은 곳, `rounded-lg` 와 `rounded-card` 가 섞여 있었다.
 * 복제가 갈라지면 같은 상태를 화면마다 다르게 설명하게 되는데, 절전은 이 사이트의
 * **평상시 상태**라 그게 곧 첫인상이다(HomePage 주석, 2026-08-17).
 *
 * 갈라진 김에 em 대시도 셋 늘어나 있었다. 지침 1번이 가장 크게 지목한 장치인데,
 * 한 문장이 다섯 벌이면 한 번 쓸 때마다 다섯 개가 생긴다.
 *
 * 톤: 절전은 **고장이 아니라 의도된 비용 절약**이라 빨간 에러가 아니라 노란 안내다.
 * 이 규약을 화면마다 다시 정하지 않게 색도 여기서 고정한다.
 *
 * `children` 은 화면마다 다른 뒷말이다. 앞 문장은 공통이고 뒷말만 갈린다 —
 * 갈려야 하는 것만 갈리게 두는 게 이 컴포넌트의 요점이다.
 */
export function AsleepNotice({
  children,
  className = '',
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={`rounded-card bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200 ${className}`}
    >
      💤 서버가 절전 중이야. 비용을 아끼려고 안 쓸 땐 꺼두거든. {children}
    </div>
  )
}

/** 절전 중에도 열리는 정적 아카이브 링크. 안내마다 이 링크를 다시 적지 않게 뽑았다. */
export function ArchiveLink({ children = '개발일지 아카이브' }: { children?: React.ReactNode }) {
  return (
    <a href="/devlog.html" className="font-medium underline">
      {children}
    </a>
  )
}
