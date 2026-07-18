import { useEffect } from 'react'

const SITE = 'DEV 블로그'

// 페이지별 브라우저 탭 제목을 설정한다. title이 비면 사이트 기본 제목으로.
// SPA라 라우트가 바뀌어도 <title>이 그대로라 탭·북마크·검색결과가 전부 똑같이 보이던 걸 고침.
export function useDocumentTitle(title?: string | null) {
  useEffect(() => {
    document.title = title ? `${title} — ${SITE}` : SITE
    // 언마운트 시 기본값으로 되돌려 다음 페이지에 이전 제목이 잔상으로 안 남게
    return () => {
      document.title = SITE
    }
  }, [title])
}
