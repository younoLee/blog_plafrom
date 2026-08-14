import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeSlug from 'rehype-slug'

import { fetchWithTimeout } from '../api/http'
import { useDocumentTitle } from '../useDocumentTitle'

/**
 * 소개(About).
 *
 * **글은 여기 없다.** `content/about.md` 한 벌이 원본이고, 빌드가 그것을 두 표면으로 낸다:
 *   - `/about.html`  정적 페이지 (서버도 JS도 없이 열린다)
 *   - `/about.md`    원문 그대로 — 이 화면이 받아서 렌더한다
 *
 * 왜 컴포넌트에 글을 안 박았나: 두 벌이 되면 반드시 갈라진다. 이 저장소는 문서와 코드가
 * 어긋난 자리를 반복해서 고쳐 왔고(‘안 한 일 목록’이 다섯 번 낡았다), 소개글은 특히
 * 오래 방치되는 종류다.
 *
 * 왜 import(?raw)가 아니라 fetch인가: content/는 저장소 루트에 있는데 프론트 Docker
 * 이미지의 빌드 컨텍스트는 frontend/뿐이라 빌드 타임에 안 보인다. import로 묶으면
 * 로컬 compose의 프론트 빌드가 깨진다. fetch면 S3에 놓인 정적 파일을 받으므로
 * **서버(EC2)가 꺼져 있어도** 동작한다 — 이 사이트의 기본 상태가 그것이다.
 *
 * 본문 서식은 글 상세와 같은 prose 클래스를 쓴다.
 * remark-gfm은 안 쓴다(번들 +11.2 KB). 그래서 about.md에 표·취소선·체크박스를 쓰면
 * 이 화면에서만 원문이 그대로 보인다 — gen-static.mjs의 가드가 빌드에서 막는다.
 */
export default function AboutPage() {
  useDocumentTitle('소개')
  const [md, setMd] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    fetchWithTimeout('/about.md')
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((t) => alive && setMd(t))
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [])

  if (failed) {
    // 개발 서버(npm run dev)에는 /about.md가 없다 — gen-static이 빌드 때 만든다.
    // 배포본에서 이 안내가 보인다면 정적 산출물이 안 올라간 것이다.
    return (
      <article className="mx-auto max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight">소개</h1>
        <p className="mt-4 text-gray-500 dark:text-gray-400">
          소개글을 불러오지 못했어. 정적 페이지로 열어볼 수 있어 —{' '}
          <a href="/about.html" className="text-[#0071e3] hover:underline dark:text-[#0a84ff]">
            /about.html
          </a>
        </p>
      </article>
    )
  }

  return (
    <article className="mx-auto max-w-3xl">
      {md === null ? (
        <p className="text-gray-500 dark:text-gray-400">불러오는 중…</p>
      ) : (
        <div className="prose prose-gray mt-6 max-w-none prose-headings:tracking-tight prose-a:text-[#0071e3] prose-a:no-underline hover:prose-a:underline dark:prose-invert dark:prose-a:text-[#0a84ff]">
          <ReactMarkdown rehypePlugins={[rehypeSlug]}>{md}</ReactMarkdown>
        </div>
      )}
    </article>
  )
}
