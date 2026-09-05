// @vitest-environment jsdom
//
// 401을 **한 자리에서** 처리한다는 규약을 잠근다. localStorage가 필요해서 jsdom이다.
//
// 왜 이 테스트가 있어야 하는가 — 이 처리는 서버 로그아웃(`POST /auth/logout`)의
// **선행 조건**이다. 로그아웃은 token_version을 올려 다른 기기의 토큰까지 죽이는데,
// 그 기기가 401에서 토큰을 안 지우면 '로그인된 것처럼 보이는데 아무것도 안 되는'
// 좀비가 된다. 그래서 여기가 깨지면 로그아웃 기능 자체가 사용자에게 해롭다.
//
// 잠그는 불변식 넷:
//   ① 인증 요청의 401 → 토큰 삭제 + 통지
//   ② **인증 없는 401 → 아무 일도 없다** (로그인 실패가 로그아웃이 되면 안 된다)
//   ③ 통지는 토큰이 있을 때 한 번만 (화면 하나가 401을 여러 개 받는 건 정상이다)
//   ④ apiFetch는 안 끊는다 (쓰기 규약: abort해도 서버 일은 안 되돌아간다)
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiFetch, fetchWithTimeout } from './http'
import { authHeaders, clearToken, getToken, onSessionExpired, setToken } from './session'

beforeEach(() => {
  clearToken()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

function stub401() {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })))
}

describe('인증 요청의 401', () => {
  it('토큰을 지우고 구독자에게 알린다', async () => {
    setToken('t1')
    const seen = vi.fn()
    onSessionExpired(seen)
    stub401()

    const res = await fetchWithTimeout('/x', { headers: { Authorization: 'Bearer t1' } })

    expect(res.status).toBe(401) // 응답은 그대로 — 호출부 안내 문구가 살아야 한다
    expect(getToken()).toBeNull()
    expect(seen).toHaveBeenCalledTimes(1)
  })

  it('쓰기 경로(apiFetch)에서도 같다 — 좀비가 살던 자리가 여기였다', async () => {
    setToken('t2')
    const seen = vi.fn()
    onSessionExpired(seen)
    stub401()

    await apiFetch('/x', { method: 'POST', headers: { Authorization: 'Bearer t2' } })

    expect(getToken()).toBeNull()
    expect(seen).toHaveBeenCalledTimes(1)
  })

  it('Headers 객체로 넘겨도 알아본다', async () => {
    setToken('t3')
    stub401()
    await apiFetch('/x', { headers: new Headers({ Authorization: 'Bearer t3' }) })
    expect(getToken()).toBeNull()
  })
})

describe('인증 없는 401', () => {
  it('토큰을 안 지우고 통지도 안 한다 — 로그인 실패(401)가 로그아웃이 되면 안 된다', async () => {
    setToken('keep-me')
    const seen = vi.fn()
    onSessionExpired(seen)
    stub401()

    // 로그인 요청에는 Authorization 헤더가 없다(아직 토큰이 없으니까).
    await fetchWithTimeout('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })

    expect(getToken()).toBe('keep-me')
    expect(seen).not.toHaveBeenCalled()
  })
})

describe('통지 횟수', () => {
  it('토큰이 없으면 통지하지 않는다 — 한 화면이 401을 여러 개 받아도 한 번만 나간다', async () => {
    setToken('t4')
    const seen = vi.fn()
    onSessionExpired(seen)
    stub401()

    const h = { Authorization: 'Bearer t4' }
    await Promise.all([apiFetch('/a', { headers: h }), apiFetch('/b', { headers: h })])

    expect(seen).toHaveBeenCalledTimes(1)
  })

  it('구독을 해제하면 더 안 온다', async () => {
    const seen = vi.fn()
    const off = onSessionExpired(seen)
    off()
    setToken('t5')
    stub401()

    await apiFetch('/x', { headers: { Authorization: 'Bearer t5' } })

    expect(getToken()).toBeNull() // 지우는 건 구독과 무관하다
    expect(seen).not.toHaveBeenCalled()
  })
})

describe('apiFetch는 안 끊는다', () => {
  it('8초가 지나도 abort하지 않는다 (쓰기 요청 규약)', async () => {
    vi.useFakeTimers()
    let signal: AbortSignal | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: RequestInit) => {
        signal = init.signal ?? undefined
        return new Response('', { status: 200 })
      }),
    )

    await apiFetch('/slow', { method: 'POST' })
    vi.advanceTimersByTime(60_000)

    expect(signal?.aborted).toBe(false)
  })
})

// ⑤ **저장소 접근 자체가 던지는 브라우저**(사파리 프라이빗 모드·쿠키 차단)에서도
// 익명 읽기는 살아 있어야 한다. 09-04 검사 FE-3 이 잡은 자리 — `authHeaders()` 는
// 로그인과 무관한 목록 조회도 부르므로, 여기서 던지면 **글 목록이 통째로** 브라우저의
// 영문 SecurityError 문구를 띄운 빨간 에러가 됐다.
describe('localStorage가 막힌 브라우저', () => {
  function blockStorage() {
    const boom = () => {
      throw new DOMException('The operation is insecure.', 'SecurityError')
    }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(boom)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(boom)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(boom)
  }

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('getToken은 던지지 않고 null을 준다', () => {
    blockStorage()
    expect(() => getToken()).not.toThrow()
    expect(getToken()).toBeNull()
  })

  it('authHeaders는 빈 객체다 — 익명 조회가 그대로 나간다', () => {
    blockStorage()
    expect(authHeaders()).toEqual({})
  })

  it('setToken·clearToken도 던지지 않는다 — 로그인만 안 될 뿐 화면은 산다', () => {
    blockStorage()
    expect(() => setToken('t')).not.toThrow()
    expect(() => clearToken()).not.toThrow()
  })
})
