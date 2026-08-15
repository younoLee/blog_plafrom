import { useEffect } from 'react'
import { applyHead, type HeadMeta } from './head'

// 페이지별 브라우저 탭 제목을 설정한다. title이 비면 사이트 기본 제목으로.
// SPA라 라우트가 바뀌어도 <title>이 그대로라 탭·북마크·검색결과가 전부 똑같이 보이던 걸 고침.
export function useDocumentTitle(title?: string | null) {
  useHead({ title })
}

/** 제목뿐 아니라 설명·canonical·OG까지 화면 단위로 바꾼다.
 *
 *  의존성은 **객체가 아니라 원시값**으로 편다. 호출부는 보통 리터럴을 넘기는데,
 *  객체를 그대로 의존성에 두면 렌더마다 새 참조라 effect가 매번 돌고
 *  (setTag → 되돌리기 → setTag) 태그가 깜빡인다. */
export function useHead(meta: HeadMeta) {
  const { title, description, canonical, type } = meta
  useEffect(
    () => applyHead({ title, description, canonical, type }),
    [title, description, canonical, type],
  )
}
