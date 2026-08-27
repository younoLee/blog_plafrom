import { Link } from 'react-router-dom'
import { useDocumentTitle } from '../useDocumentTitle'

// 없는 주소로 들어온 사람에게 보여주는 화면.
//
// ⚠️ **HTTP 상태코드는 200이다.** 이 사이트는 S3+CloudFront 정적 호스팅이고,
// CloudFront Function(terraform/spa-routing-function.js)이 "마지막 경로 조각에 점이
// 없으면 /index.html"로 되돌린다 — SPA 딥링크(/blog/posts/41)가 살아 있는 이유가 그것이다.
// 그래서 오리진에 404가 날 자리가 없고, 없는 경로도 200으로 이 화면이 뜬다.
//
// 진짜 404를 주려면 CloudFront 커스텀 에러 응답이 필요한데, 그건 "없는 경로"와
// "SPA 라우트"를 엣지에서 구별해야 한다는 뜻이라 라우트 목록을 함수 안에 복제하게 된다
// (= 라우트를 추가할 때마다 두 곳을 고쳐야 하고, 안 고치면 멀쩡한 페이지가 404가 된다).
// 지금은 사람이 길을 잃지 않는 것까지만 한다. 크롤러 쪽은 sitemap이 정적 페이지만
// 가리키고 있어서 없는 주소를 색인하라고 부르는 경로 자체가 없다.
function NotFoundPage() {
  useDocumentTitle('찾을 수 없는 페이지')

  return (
    <div className="mx-auto max-w-lg py-20 text-center">
      <p className="font-mono text-sm text-gray-500 dark:text-gray-400">404</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">이 주소에는 아무것도 없어.</h1>
      <p className="mt-3 text-gray-500 dark:text-gray-400">
        주소가 바뀌었거나, 지워진 글일 수 있어.
      </p>

      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link
          to="/blog"
          className="rounded-btn bg-accent px-5 py-2.5 text-sm font-medium text-on-accent transition hover:brightness-110"
        >
          글 목록으로
        </Link>
        <Link
          to="/"
          className="rounded-btn border border-black/[0.1] px-5 py-2.5 text-sm font-medium transition hover:bg-black/[0.03] dark:border-white/15 dark:hover:bg-white/[0.06]"
        >
          첫 화면
        </Link>
      </div>

      {/* 서버가 꺼져 있으면 위 두 링크의 목적지도 비어 보인다. 그때도 읽히는 길을 같이 준다. */}
      <p className="mt-8 text-sm text-gray-500 dark:text-gray-400">
        서버가 절전 중이어도 읽을 수 있는 곳:{' '}
        <a href="/devlog.html" className="text-accent hover:underline">
          개발일지 아카이브
        </a>
      </p>
    </div>
  )
}

export default NotFoundPage
