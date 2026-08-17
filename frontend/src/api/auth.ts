import { QUICK_TIMEOUT_MS, fetchWithTimeout } from './http'
import { authHeaders, clearToken, getToken, setToken } from './session'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 권한: pending(승인 대기) / writer(글쓰기 가능) / admin(관리자) / banned(차단)
export type Role = 'pending' | 'writer' | 'admin' | 'banned'

export interface User {
  id: number
  email: string
  role: Role
  // 화면에 보일 이름. 안 정했으면 null → 서버가 "회원 #id"로 폴백한다
  display_name?: string | null
  is_pro: boolean // 유료(고급 AI 모델 해금) 여부
  pro_until?: string | null // 구독 만료 시각(ISO). 없으면 null
  created_at: string
}

// 글쓰기 가능한 권한인지 (writer나 admin)
export function canWrite(user: User | null): boolean {
  return user?.role === 'writer' || user?.role === 'admin'
}

// --- 토큰 저장/조회 ---
// 실체는 session.ts로 옮겼다(http.ts가 401에서 토큰을 지워야 하는데, auth.ts를 import하면
// 순환이 된다). 여기서 다시 내보내는 이유는 기존 호출부(`from './auth'`)를 안 건드리기
// 위해서다 — 한 자리로 모으는 변경에 호출부 40곳 수정을 얹으면 위험이 섞인다.
export { authHeaders, clearToken, getToken } from './session'

// --- 인증 요청 ---
export async function register(email: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  // 기존 이메일도 409로 안 흘림(enumeration 방지) → 신규/기존 모두 동일하게 성공 화면.
  // 실제 안내(인증/이미가입)는 메일로만 감.
  if (res.status === 422) throw new Error('이메일 형식·비밀번호(8~72자)를 확인해줘')
  if (res.status === 429) throw new Error('가입 시도가 너무 많아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('회원가입 실패')
}

// 메일 링크의 토큰으로 이메일 인증 처리
export async function verifyEmail(token: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/verify?token=${encodeURIComponent(token)}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('유효하지 않거나 만료된 인증 링크야')
}

// 비밀번호 재설정 요청 (재설정 링크 메일 발송)
export async function forgotPassword(email: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (res.status === 429) throw new Error('요청이 너무 많아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('요청에 실패했어')
}

// 메일 링크의 토큰으로 새 비밀번호 설정
export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, new_password: newPassword }),
  })
  // **422를 만료로 말하면 안 된다.** 422는 pydantic이 라우트에 들어가기도 전에 잡는 것이라
  // 토큰은 **아직 소각되지 않았다** = 링크가 살아 있다. 그런데 예전엔 `!res.ok`를 전부
  // "유효하지 않거나 만료된 링크야"로 뭉갰다: 8자 미만을 치면 멀쩡한 링크를 버리라는
  // 안내가 나가고, /forgot으로 돌아가 새 링크를 받아도 같은 비밀번호를 다시 쳐서 또
  // "만료"를 본다 — 사용자가 스스로 못 빠져나오는 닫힌 고리였다(2026-08-17 실측).
  // 이 저장소는 RegisterPage에 "멀쩡한 초대를 만료됐다고 말하면 받은 사람이 진짜로
  // 버린다"고 적어두고 초대 경로에서만 지키고 있었다. 같은 규칙을 여기에도 적용한다.
  if (res.status === 422) throw new Error('비밀번호는 8~72자로 정해줘')
  if (res.status === 429) throw new Error('요청이 너무 많아. 잠시 후 다시 해줘')
  if (res.status === 400) {
    // 400도 서버는 두 가지를 구분해 말한다(서명·만료 / 이미 사용한 링크).
    // 하드코딩하면 그 구분이 사라져 원인을 알 유일한 단서가 없어진다.
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? '유효하지 않거나 만료된 링크야')
  }
  if (!res.ok) throw new Error('비밀번호를 바꾸지 못했어')
}

/**
 * 로그인 타임아웃을 목록(8초)보다 길게 준다 — bcrypt cost 12가 서버에서 도는데,
 * 차가운 t2.micro면 목록 조회보다 느릴 수 있다. 그렇다고 무제한이면 안 된다:
 * 예전엔 타임아웃이 아예 없어 CloudFront 오리진 상한 60초까지 매달렸고,
 * 화면에 busy 표시도 없어 사용자가 버튼을 다시 눌렀다 → **자기가 만든 429**를 만났다
 * ("로그인 시도가 너무 많아"). 원인을 알 수 없는 형태의 실패라 특히 나쁘다.
 */
const LOGIN_TIMEOUT_MS = 20000

export async function login(email: string, password: string): Promise<void> {
  const res = await fetchWithTimeout(
    `${BASE}/auth/login`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    },
    LOGIN_TIMEOUT_MS,
  )
  if (res.status === 401) throw new Error('이메일 또는 비밀번호가 틀렸어')
  // 403 = 미인증/차단 (백엔드 메시지 그대로 보여줌), 429 = 너무 잦은 시도
  if (res.status === 403) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? '로그인할 수 없는 계정이야')
  }
  if (res.status === 429) throw new Error('로그인 시도가 너무 많아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('로그인 실패')
  const data = await res.json()
  setToken(data.access_token)
}

// --- 초대제 가입 ---
// 열린 가입(register)과 달리 이쪽은 실패 사유를 분명히 말해줘야 쓸 수 있다.
// register는 enumeration 방지로 신규/기존을 안 가리고 항상 성공처럼 응답하지만,
// 초대는 유효한 토큰을 쥔 사람만 오므로 숨길 게 없다.

export interface InvitePreview {
  email: string
  role: Role
}

/** 초대 링크의 토큰으로 '어떤 주소로 가입되는지'를 확인. 무효/만료/사용됨은 전부 null.
 *
 * 읽기인데 POST인 건 서버 사정이다 — 토큰이 자격증명이라 URL에 실으면 액세스 로그에
 * 평문으로 남는다. 본문으로 보내면 안 남는다. */
export async function previewInvite(token: string): Promise<InvitePreview | null> {
  const res = await fetchWithTimeout(`${BASE}/auth/invite`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (res.status === 404) return null // 서버가 셋을 구분해주지 않는다(오라클 방지)
  if (!res.ok) throw new Error('초대 정보를 확인하지 못했어')
  return res.json()
}

/** 초대 토큰 소각 + 계정 생성. 성공하면 그대로 로그인 상태가 된다(토큰 저장).
 *
 * **여기엔 fetchWithTimeout을 쓰지 않는다.** abort는 내 기다림만 끊을 뿐 서버 일을
 * 되돌리지 않는다 — 8초에 끊어도 소각과 계정 생성은 그대로 끝난다. 그러면 상대는
 * "서버가 절전 중"을 보고 새로고침하고, 이번엔 "더 이상 쓸 수 없는 링크"를 만난다.
 * 1회용이라 그걸로 끝이고 관리자만 되살릴 수 있다. 하필 갓 건넨 링크를 누르는 순간이
 * 오리진이 차가울 확률이 제일 높은 때다(거기에 bcrypt까지 얹힌다).
 * 이 저장소가 읽기에만 타임아웃을 거는 것도 같은 이유다(api/http.ts). */
export async function redeemInvite(token: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/register/invite`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, password }),
  })
  if (res.status === 422) throw new Error('비밀번호는 8~72자로 정해줘')
  if (res.status === 429) throw new Error('시도가 너무 많아. 잠시 후 다시 해줘')
  if (res.status === 400) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? '이 초대 링크는 더 이상 쓸 수 없어')
  }
  if (!res.ok) throw new Error('가입에 실패했어')
  const data = await res.json()
  setToken(data.access_token)
}

export async function fetchMe(): Promise<User | null> {
  const t = getToken()
  if (!t) return null
  // 순수 읽기라 읽기 규칙(http.ts)대로 8초에 끊는다. 쓰기에 타임아웃을 안 거는 예외
  // 사유("abort해도 서버 일은 안 되돌아간다")는 여기 해당하지 않는다.
  //
  // 안 끊으면 무슨 일이 나는가 (2026-08-10 심층검사): AuthProvider가 부팅 때 이걸 부르고
  // 그동안 loading=true인데, AdminPage·SettingsPage·PaymentPage·WritePostPage가 전부
  // `if (loading) return null`이다. 서버가 꺼져 있으면 CloudFront origin_read_timeout
  // (60초)까지 네 화면이 **헤더 아래 통째로 백지**가 된다 — 스피너도 절전 안내도 없이.
  // 서버를 필요할 때만 켜는 운영이라 그게 평상시 상태이고, 익명 방문자는 토큰이 없어
  // 요청 자체를 안 하므로 **로그인한 사람(=블로그 주인)만 정확히 맞는 버그**였다.
  let res: Response
  try {
    res = await fetchWithTimeout(`${BASE}/auth/me`, { headers: authHeaders() })
  } catch {
    // 절전이든 네트워크 오류든 '지금은 모른다' → 아래 5xx와 같은 처리로 간다:
    // **토큰은 지우지 않고** 비로그인으로 그린다. 서버가 깨면 새로고침에 복구된다.
    // 예외를 여기서 삼키는 게 중요하다 — 호출부(AuthProvider)는 .catch가 없어서
    // 던지면 unhandled rejection이 되고 loading이 영영 안 풀린다.
    return null
  }
  // 401(만료/위조)일 때만 토큰 정리. 5xx 같은 일시적 서버 오류엔 토큰을 지우지 않음
  // (안 그러면 서버가 잠깐 흔들릴 때 사용자가 강제 로그아웃돼 재로그인해야 함)
  if (res.status === 401) {
    // http.ts의 request()가 이미 지우고 통지했다. 여기서 한 번 더 부르는 건 무해하고,
    // 이 함수만 따로 쓰는 호출부가 생겨도 계약이 유지된다.
    clearToken()
    return null
  }
  if (!res.ok) return null // 일시 오류: 토큰 유지, 다음 새로고침에 복구
  return res.json()
}

/**
 * 표시명 바꾸기. **비밀번호는 안 건드린다.**
 *
 * 이게 생기기 전까지 display_name을 정할 방법은 `create_user.py --display-name` 하나였는데,
 * 그 스크립트는 같은 실행에서 비밀번호를 새로 만들어 덮어쓴다 — 이름 하나 바꾸려다
 * 로그인을 잃는 구조였다. 그래서 화면에서 이름이 전부 "회원"으로 보였다.
 *
 * 빈 문자열을 보내면 '안 정함'으로 되돌아간다(서버가 NULL로 저장).
 */
export async function updateDisplayName(displayName: string): Promise<User> {
  const res = await fetchWithTimeout(
    `${BASE}/auth/me`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ display_name: displayName }),
    },
    QUICK_TIMEOUT_MS,
  )
  if (res.status === 422) throw new Error('이름은 50자까지야')
  if (!res.ok) throw new Error('표시명을 바꾸지 못했어')
  return res.json()
}

/**
 * 서버 로그아웃 — 이 계정의 **모든 기기**에서 토큰을 무효화한다.
 *
 * 왜 '이 기기만'이 아닌가: 이 앱의 토큰은 서명된 JWT이고 서버에 세션 표가 없다.
 * 개별 토큰을 지목해 죽이려면 폐기 목록(jti)이라는 표가 하나 더 필요하다. 지금 있는
 * 레버는 `token_version` 하나뿐이고 그건 계정 단위다. 그래서 계정 단위로 정직하게
 * 만들고 화면에도 그렇게 적는다 — '이 기기만'인 척하는 게 더 나쁘다(기기를 잃어버려서
 * 누르는 게 로그아웃의 진짜 용도인데, 그때 안 끊기면 아무 의미가 없다).
 *
 * 실패해도 삼킨다: 서버가 꺼져 있어도 **로컬 로그아웃은 되어야 한다**. 이 블로그는
 * 평소 서버를 꺼두므로 그게 예외가 아니라 기본 상태다.
 *
 * ⚠️ **쓰기인데 타임아웃을 건다** — 이 저장소의 규약(쓰기엔 안 건다)의 유일한 예외다.
 * 규약의 근거는 "abort해도 서버 일은 안 되돌아가니, 끊으면 실패한 줄 알았는데 됐다가
 * 된다"인데, 로그아웃은 그 위험이 **뒤집힌다**: 끊긴 뒤에 서버가 무효화를 마쳐도
 * 사용자가 원한 그대로다. 반대로 안 걸면, 서버가 절전일 때 로그아웃 버튼이
 * CloudFront 상한(60초)까지 멈춘 채 여전히 로그인 상태로 보인다.
 */
export async function logout(): Promise<void> {
  const headers = authHeaders()
  if (!headers.Authorization) return
  // **보내기 전에 지운다.** 그래야 이 요청이 401을 받아도(이미 죽은 토큰으로 눌렀을 때)
  // '세션이 끊겼다' 안내가 안 뜬다 — sessionExpired()는 토큰이 없으면 아무 일도 안 한다.
  // 내가 누른 로그아웃과 남이 끊은 세션은 화면에서 달라야 한다.
  clearToken()
  try {
    await fetchWithTimeout(
      `${BASE}/auth/logout`,
      { method: 'POST', headers },
      QUICK_TIMEOUT_MS,
    )
  } catch {
    // 절전·네트워크 오류: 서버 쪽 무효화는 못 했지만 이 기기에서는 나간다.
  }
}
