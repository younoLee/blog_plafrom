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
import { clearToken, getToken, onSessionExpired, setToken } from './session'

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
