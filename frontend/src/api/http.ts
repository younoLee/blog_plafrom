/**
 * 호출별 타임아웃이 붙은 fetch.
 *
 * 왜 필요한가: 이 블로그는 비용 습관상 서버(EC2)를 안 쓸 때 꺼둔다. 그러면
 * CloudFront가 오리진을 기다리다 504를 주는데, 오리진 타임아웃이 60초라
 * 방문자는 1분을 멍하니 기다린 뒤 빨간 에러를 본다 — 절전인데 고장으로 보인다.
 *
 * 그 60초는 AI 초안 생성(실측 ~10초, 모델에 따라 더)에 필요해서 인프라에서
 * 낮출 수 없다. 그래서 '호출별로' 다르게 준다: 목록·상태는 짧게 끊어 빨리
 * 안내하고, AI 초안만 길게 기다린다.
 *
 * 2026-08-14에 역할이 하나 늘었다 — **인증 요청의 401을 여기서 잡는다**(아래 request).
 */
import { sessionExpired } from './session'

/** 화면 조회용 기본 상한. 서버가 깨어 있으면 이보다 훨씬 빨리 온다. */
export const QUICK_TIMEOUT_MS = 8000

/** 서버가 안 깨어 있어 응답이 없는 경우. 일반 실패와 구분해 안내를 다르게 하려고 따로 둔다. */
export class ServerAsleepError extends Error {
  constructor() {
    super('서버가 절전 중이야')
    this.name = 'ServerAsleepError'
  }
}

/** 504/503도 오리진이 안 뜬 상태라 절전으로 본다(꺼둔 서버의 실제 응답이 504다). */
export function isAsleepStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504
}

/**
 * 요청이 Authorization 헤더를 달고 있었는가.
 *
 * **왜 헤더로 판단하는가** — 401을 무조건 '세션 만료'로 처리하면 로그인 실패가
 * 로그아웃 통지를 낸다(`POST /auth/login`은 비밀번호가 틀리면 401이다). 로그인
 * 요청은 토큰이 없으니 헤더도 없다. 즉 '토큰을 냈는데 거절당했다'만 만료다.
 */
function hasAuthHeader(init: RequestInit): boolean {
  const h = init.headers
  if (!h) return false
  if (h instanceof Headers) return h.has('Authorization')
  if (Array.isArray(h)) return h.some(([k]) => k.toLowerCase() === 'authorization')
  return Object.keys(h).some((k) => k.toLowerCase() === 'authorization')
}

/**
 * 모든 API 호출이 지나는 **한 자리**. 두 가지를 여기서만 판단한다:
 *   ① 절전(5xx·무응답) ② 세션 만료(인증 요청의 401)
 *
 * 왜 한 자리인가 — 2026-08-12 보안 수정이 얻은 결론 그대로다("필드가 아니라 뿌리에서
 * 막는다"). 401 처리를 호출부마다 적으면 새 호출을 추가할 때마다 다시 샌다. 실제로
 * 이 저장소는 401에서 토큰을 지우는 코드가 `fetchMe` **한 곳뿐**이었고, 그래서
 * 서버 로그아웃을 만들 수 없었다(다른 기기가 좀비가 된다).
 *
 * timeoutMs = null 이면 **안 끊는다.** 쓰기 요청의 규약이다 — abort는 내 기다림만
 * 끊을 뿐 서버가 하던 일은 안 되돌아가므로, 끊으면 '실패한 줄 알았는데 됐다'가 된다.
 */
async function request(
  url: string,
  init: RequestInit,
  timeoutMs: number | null,
): Promise<Response> {
  const ac = new AbortController()
  const timer = timeoutMs === null ? null : setTimeout(() => ac.abort(), timeoutMs)
  try {
    const res = await fetch(url, { ...init, signal: ac.signal })
    if (isAsleepStatus(res.status)) throw new ServerAsleepError()
    // 토큰을 냈는데 401 → 그 토큰은 더 이상 우리 것이 아니다. 지우고 화면에 알린다.
    // 응답 자체는 그대로 돌려준다 — 호출부의 안내 문구("로그인이 필요해")는 살아야 한다.
    if (res.status === 401 && hasAuthHeader(init)) sessionExpired()
    return res
  } catch (e) {
    // abort = 시간 안에 응답이 없음 → 켜지는 중이거나 꺼져 있음
    if (e instanceof DOMException && e.name === 'AbortError') throw new ServerAsleepError()
    throw e
  } finally {
    if (timer !== null) clearTimeout(timer)
  }
}

export async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  timeoutMs: number = QUICK_TIMEOUT_MS,
): Promise<Response> {
  return request(url, init, timeoutMs)
}

/**
 * 타임아웃 없는 호출 — **쓰기 전용**. 맨 `fetch` 대신 이걸 쓴다.
 *
 * 맨 `fetch`를 쓰면 위 401 처리를 건너뛴다. 이 저장소의 쓰기 경로(글·댓글·업로드·
 * 관리자·결제·푸시)는 전부 맨 fetch였고, 그게 정확히 '좀비 상태'가 사는 자리였다 —
 * 읽기만 하는 화면은 fetchMe가 정리해 주지만, 쓰기 화면은 아무도 안 정리했다.
 */
export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  return request(url, init, null)
}

/**
 * 실패한 응답에서 **서버가 보낸 이유**를 꺼내 던진다. 없으면 fallback.
 *
 * **왜 (2026-08-27)** — 백엔드는 거절 이유를 한국어 문장으로 보낸다. `admin.py:171`의
 * "관리자 계정은 차단할 수 없어", `subscriptions.py:125`의 "자기 자신은 구독할 수
 * 없어" 같은 것이다. 그런데 호출부 대부분이 `res.ok`만 보고 "차단에 실패했어"로
 * 덮어써서, 원인을 아는 쪽이 말을 하는데 듣는 쪽이 버리고 있었다. 사용자는 무엇을
 * 고쳐야 하는지 알 수 없고, 다시 눌러도 같은 결과가 나온다.
 *
 * 새 규칙이 아니라 **이미 있던 선례를 퍼뜨리는 것**이다. `api/skin.ts`의 `put` 헬퍼가
 * 진작 이렇게 하고 있었다(422의 배열 형태까지 다룬다). 한 곳에만 있으면 새 호출을
 * 추가할 때마다 다시 샌다 — 이 파일이 401 처리를 여기 모은 것과 같은 이유다.
 *
 * 422는 FastAPI가 `detail`을 **배열**로 준다(필드별 오류 목록). 첫 항목의 `msg`를 쓴다.
 * 본문이 JSON이 아닐 수도 있으므로(504는 CloudFront가 HTML을 준다) 파싱 실패는 삼킨다.
 */
export async function failWith(res: Response, fallback: string): Promise<never> {
  const parsed = await res.json().catch(() => null)
  const detail = (parsed as { detail?: unknown } | null)?.detail
  const msg = Array.isArray(detail)
    ? (detail[0] as { msg?: string } | undefined)?.msg
    : typeof detail === 'string'
      ? detail
      : undefined
  throw new Error(msg || fallback)
}
