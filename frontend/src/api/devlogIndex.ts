/** 빌드가 만든 정적 개발일지 목록(dist/devlog-index.json)을 읽는다. **API가 아니다.**
 *
 *  이 사이트는 EC2를 평소 꺼둔다. 그래서 글 목록이 /api에서만 오면 방문자가 가장 흔하게
 *  보는 상태가 빈 화면이 된다. 이 파일은 S3에 정적으로 놓여 서버와 무관하게 산다.
 *  생성 근거는 frontend/scripts/gen-static.mjs의 '2-B' 절 주석 참고.
 *
 *  왜 모듈로 뗐나 (2026-08-17): 랜딩(/)이 08-12부터 이걸 쓰고 있었는데, 정작 글 목록
 *  화면(/blog)은 절전 중에 비어 있었다. 그 자리에 같은 fetch·같은 타입을 한 벌 더 쓰면
 *  언젠가 갈라진다 — 이 저장소가 반복해서 당한 병이다. 그래서 읽는 자리를 하나로 둔다.
 *
 *  ⚠️ 링크는 `slug`(예: `devlog/2026-08-15.html`)를 쓴다. SPA 라우트(/blog/posts/:id)로
 *  바꾸면 **서버가 꺼진 날 클릭이 죽어** 목록을 그린 의미가 사라진다.
 */
export type DevlogIndexPost = {
  date: string
  title: string
  slug: string
  summary: string
  /** 08-12 생성분엔 없었다. 옛 산출물이 S3에 남아 있을 수 있어 선택으로 둔다. */
  tags?: string[]
}

export type DevlogIndex = {
  total: number
  chars: number
  posts: DevlogIndexPost[]
}

/** 못 읽으면 null. 로컬 dev 서버엔 이 파일이 없어서 404가 정상이라 던지지 않는다.
 *  모양이 틀려도 null — 부른 쪽이 '없다'와 '깨졌다'를 같게 다루면 화면이 안 멈춘다
 *  (뼈대만 영원히 남는 고장을 2026-08-12에 실측했다). */
export async function fetchDevlogIndex(): Promise<DevlogIndex | null> {
  try {
    const res = await fetch('/devlog-index.json')
    if (!res.ok) return null
    const data = (await res.json()) as DevlogIndex
    return Array.isArray(data?.posts) ? data : null
  } catch {
    return null
  }
}
