import { fetchWithTimeout } from './http'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

/** `/@handle` 화면이 그릴 사람 정보. 이메일은 담기지 않는다(서버가 안 준다). */
export interface AuthorProfile {
  handle: string
  /** 표시명. 안 정했으면 서버가 핸들을 넣어 준다 — 이메일로 되돌아가지 않는다. */
  name: string
  /** 공개 글 수. 로그인 여부와 무관하게 같은 값이다(비공개 글 존재가 새지 않게). */
  posts: number
}

/**
 * 없는 핸들이면 **null**을 준다(예외를 던지지 않는다).
 *
 * 404는 이 화면에선 '고장'이 아니라 '그런 블로그가 없다'는 정상적인 답이다. 예외로
 * 만들면 호출부가 그걸 다시 정상 흐름으로 되돌려야 하고, 절전(서버 꺼짐)과도 구분이
 * 안 된다. 절전은 예외로 남겨 둔다 — 그건 '나중에 다시 오면 있다'는 뜻이라 화면이
 * 달라야 한다.
 */
export async function fetchAuthor(handle: string): Promise<AuthorProfile | null> {
  const res = await fetchWithTimeout(`${BASE}/authors/${encodeURIComponent(handle)}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error('블로그 정보를 못 불러왔어')
  return res.json()
}
