import { Link } from 'react-router-dom'

// 통합 랜딩(포털): 블로그 / 상태정보 두 군데로 가는 입구
function PortalPage() {
  return (
    <div className="space-y-10">
      <div className="text-center">
        <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-white">
          환영해 👋
        </h1>
        <p className="mt-2 text-gray-500 dark:text-gray-400">어디로 들어갈까?</p>
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        {/* 블로그 입구 */}
        <Link
          to="/blog"
          className="group rounded-xl border border-gray-200 bg-white p-8 shadow-sm transition hover:-translate-y-1 hover:shadow-md dark:border-gray-800 dark:bg-gray-800"
        >
          <div className="text-4xl">📝</div>
          <h2 className="mt-4 text-xl font-bold text-gray-900 dark:text-white">블로그</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            글 읽고 쓰기, 구독, 댓글
          </p>
          <span className="mt-4 inline-block text-sm font-medium text-indigo-600 transition group-hover:translate-x-1 dark:text-indigo-400">
            들어가기 →
          </span>
        </Link>

        {/* 상태정보 입구 */}
        <Link
          to="/status"
          className="group rounded-xl border border-gray-200 bg-white p-8 shadow-sm transition hover:-translate-y-1 hover:shadow-md dark:border-gray-800 dark:bg-gray-800"
        >
          <div className="text-4xl">📊</div>
          <h2 className="mt-4 text-xl font-bold text-gray-900 dark:text-white">상태정보</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            서비스 가동 상태 + 통계
          </p>
          <span className="mt-4 inline-block text-sm font-medium text-indigo-600 transition group-hover:translate-x-1 dark:text-indigo-400">
            보러가기 →
          </span>
        </Link>
      </div>
    </div>
  )
}

export default PortalPage
