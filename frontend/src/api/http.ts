/**
 * 호출별 타임아웃이 붙은 fetch.
 *
 * 왜 필요한가: 이 블로그는 비용 습관상 서버(EC2)를 안 쓸 때 꺼둔다. 그러면
 * CloudFront가 오리진에 못 닿아 504를 주는데, 그게 나오기까지 방문자는 30초를
 * 멍하니 기다린다. 절전인데 고장으로 보인다.
 *
 * 📏 **그 30초가 어디서 오는지를 2026-09-02까지 여기 틀리게 적어뒀다.** 원인이
 * "오리진 read timeout 60초"라고 되어 있었는데 그 값은 이 경로와 무관하다.
 * 꺼둔 서버는 읽기까지 못 간다 — TCP 연결에서 막힌다. CloudFront 기본값이
 * 연결 시도 3회 × 연결 대기 10초라 30초를 채우고 504가 된다.
 * 실측(2026-09-02): `/api/posts` 가 504를 30.1초에 냈다. 60초가 아니다.
 * 틀린 진단은 고칠 자리도 틀리게 가리킨다 — read timeout 을 아무리 줄여도
 * 이 30초는 1초도 안 줄어든다(줄이는 자리는 terraform 쪽 연결 설정이다).
 *
 * read timeout 60초 자체는 그대로 필요하다. AI 초안 생성이 실측 ~10초, 모델에
 * 따라 더 걸린다. 그래서 '호출별로' 다르게 준다: 목록·상태는 짧게 끊어 빨리
 * 안내하고, AI 초안만 길게 기다린다.
 *
 * 2026-08-14에 역할이 하나 늘었다 — **인증 요청의 401을 여기서 잡는다**(아래 request).
 * 2026-09-02에 하나 더 — **절전을 기억한다**(아래 forgetAsleep 주석).
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
 * 절전을 확인한 뒤 이 시간 동안은 요청을 **보내지 않고** 바로 거절한다.
 *
 * **왜 (2026-09-02)** — 절전 판정은 있었는데 그 사실을 아무도 안 들고 있었다.
 * 그래서 목록에서 8초를 내고 절전 안내를 본 사람이, 글을 누르면 또 8초를 내고
 * 뒤로 갔다가 태그를 누르면 또 8초를 낸다. 같은 답을 이미 아는데 화면마다 다시
 * 물어보는 셈이다. 서버가 꺼져 있는 게 이 사이트의 평상시라 이 낭비가 예외가
 * 아니라 기본 경로다.
 *
 * 60초인 이유: 이 서버는 사람이 켠다. 켜지는 데 걸리는 시간이 분 단위라 60초는
 * 짧은 축이고, 틀렸을 때의 손해도 작다 — 최악이 '켜진 지 1분 안 된 서버를
 * 자고 있다고 말하는 것'이고 다음 요청에 저절로 풀린다.
 *
 * **모듈 변수로 둔다(탭 간 공유 안 함).** 공유하려면 저장소가 필요한데,
 * localStorage 는 시크릿 창에서 접근 자체가 throw 하고(WritePostPage 의 초안
 * 백업이 같은 이유로 실패를 삼킨다) 탭마다 다른 시각 기준이 섞인다. 안 나누고
 * 치르는 값은 '탭 하나당 8초 한 번'이고, 잘못 나눴을 때 치르는 값은 '서버가
 * 멀쩡한 탭에서 절전 화면을 보는 것'이다. 뒤쪽이 더 비싸다.
 */
export const ASLEEP_MEMORY_MS = 60000

/** 마지막으로 절전을 확인한 시각. null 이면 '자고 있다고 알고 있는 바 없음'. */
let asleepAt: number | null = null

/**
 * 절전 기억을 버린다.
 *
 * 두 자리에서 부른다: ① 응답이 실제로 왔을 때(서버가 켜졌다는 뜻) ② 사람이
 * 직접 다시 확인을 눌렀을 때(StatusPage 의 새로고침). ②가 없으면 그 버튼이
 * 60초 동안 아무것도 안 하고 절전만 되풀이해서, 확인하려고 누른 사람에게
 * 확인을 안 해 준다.
 */
export function forgetAsleep(): void {
  asleepAt = null
}

function knownAsleep(): boolean {
  return asleepAt !== null && Date.now() - asleepAt < ASLEEP_MEMORY_MS
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
  // 방금 절전을 확인했으면 보내지 않는다. 보내봐야 같은 답을 30초 걸려 받는다.
  // 쓰기(timeoutMs === null)에도 똑같이 건다 — 안 보낸 요청은 서버에서 아무 일도
  // 일으키지 않으므로, 쓰기에 타임아웃을 안 거는 이유("abort해도 서버 일은 안
  // 되돌아간다")가 여기엔 해당하지 않는다.
  if (knownAsleep()) throw new ServerAsleepError()
  const ac = new AbortController()
  const timer = timeoutMs === null ? null : setTimeout(() => ac.abort(), timeoutMs)
  try {
    const res = await fetch(url, { ...init, signal: ac.signal })
    if (isAsleepStatus(res.status)) {
      asleepAt = Date.now()
      throw new ServerAsleepError()
    }
    // 응답이 왔다 = 오리진이 살아 있다. 404든 401이든 마찬가지다 — 그 답을 만든 건
    // 서버다. 기억을 여기서 지워야 '켜졌는데 앱만 자고 있다고 우기는' 창이 안 생긴다.
    forgetAsleep()
    // 토큰을 냈는데 401 → 그 토큰은 더 이상 우리 것이 아니다. 지우고 화면에 알린다.
    // 응답 자체는 그대로 돌려준다 — 호출부의 안내 문구("로그인이 필요해")는 살아야 한다.
    if (res.status === 401 && hasAuthHeader(init)) sessionExpired()
    return res
  } catch (e) {
    // abort = 시간 안에 응답이 없음 → 켜지는 중이거나 꺼져 있음
    if (e instanceof DOMException && e.name === 'AbortError') {
      asleepAt = Date.now()
      throw new ServerAsleepError()
    }
    // 네트워크 오류(끊긴 와이파이 등)는 기억하지 않는다. 서버 상태를 말해 주는
    // 신호가 아니라서, 이걸 절전으로 접으면 원인 진단이 어긋난다(http.test.ts 가 잠근다).
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
 *
 * 2026-09-02에 얻는 게 하나 더 생겼다: 절전 기억을 여기서도 본다. 타임아웃이 없는
 * 요청일수록 절전일 때 오래 매달리므로, 이미 아는 답이면 안 보내는 이득이 크다.
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
