/**
 * 세션 하나만 아는 모듈 — 토큰 보관과 '세션이 끝났다'는 통지.
 *
 * 왜 auth.ts에서 떼어냈는가: 401을 **모든 호출에서** 처리하려면 http.ts가 토큰을
 * 지울 수 있어야 하는데, auth.ts는 이미 http.ts를 import한다. 그대로 두면 순환
 * import가 된다. 이 파일은 아무것도 import하지 않으므로 양쪽이 안전하게 쓴다.
 *
 * 왜 통지가 필요한가 (2026-08-12 검사가 로그아웃을 '선행조건 있음'으로 미룬 이유):
 * 서버 로그아웃은 `token_version`을 올려 **모든 기기의 토큰을 한 번에 무효화**한다.
 * 그런데 401에서 토큰을 지우는 코드가 저장소에 `fetchMe` 한 곳뿐이었다. 다른 기기는
 * 401을 받고도 토큰을 그대로 들고 있어서 **로그인된 것처럼 보이는데 아무것도 안 되는**
 * 좀비가 된다. 화면이 그걸 알아야 하므로, 지우는 것만으로는 부족하고 알려야 한다.
 */

const TOKEN_KEY = 'token'

/**
 * localStorage 접근 자체가 던진다 — 그게 이 세 함수가 전부 try/catch인 이유다.
 *
 * 사파리 프라이빗 모드·쿠키(저장소) 차단 브라우저에서는 `localStorage`를 **읽기만
 * 해도** SecurityError가 난다. 이 저장소는 그걸 전제로 skin.ts cached()·
 * WritePostPage readDraft·http.ts 주석까지 전부 감싸 뒀는데 여기만 맨살이었다.
 * 하필 여기가 제일 넓게 불린다 — `authHeaders()`는 로그인과 무관한 목록 조회도
 * 부르므로(posts.ts fetchPosts), 그 브라우저에서는 **익명 방문자의 글 목록**이
 * 브라우저의 영문 SecurityError 문구를 그대로 띄운 빨간 에러가 됐다.
 * 부팅 시 fetchMe도 같은 자리에서 던져 unhandled rejection이 된다. (09-04 검사 FE-3)
 *
 * 실패하면 '토큰이 없다'로 본다. 저장소가 막힌 브라우저에서 로그인 유지는 어차피
 * 안 되지만, 익명으로 읽는 것까지 못 하게 만들 이유는 없다.
 */
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(t: string) {
  try {
    localStorage.setItem(TOKEN_KEY, t)
  } catch {
    /* 저장이 막힌 브라우저에서는 로그인 유지가 애초에 불가능하다. 여기서 던져 봐야
       읽기 화면까지 같이 죽을 뿐이라, 로그인만 안 되는 쪽으로 남긴다 */
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* 애초에 저장이 안 됐다면 지울 것도 없다 */
  }
}

/** 로그인했으면 Authorization 헤더, 아니면 빈 객체 */
export function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

type Listener = () => void
const listeners = new Set<Listener>()

/** 세션 만료를 구독한다. 반환값을 부르면 구독 해제(React cleanup에 그대로 쓴다). */
export function onSessionExpired(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

/**
 * 인증된 요청이 401을 받았다 = 이 토큰은 더 이상 우리 것이 아니다.
 * 토큰을 지우고 화면에 알린다.
 *
 * 토큰이 이미 없으면 아무것도 안 한다 — 화면 하나에서 동시에 여러 요청이 401을 받는 게
 * 정상이라(목록·알림·내정보), 안 막으면 같은 통지가 여러 번 나간다.
 */
export function sessionExpired() {
  if (!getToken()) return
  clearToken()
  for (const fn of listeners) fn()
}
