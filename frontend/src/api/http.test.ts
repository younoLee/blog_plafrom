/**
 * `fetchWithTimeout`의 절전 판정 — **이 프로젝트에서 가장 자주 실행되는 분기**인데
 * 테스트가 0줄이었다(2026-08-11 동료 리뷰).
 *
 * 이 블로그는 비용 때문에 서버를 평소 꺼둔다. 그래서 방문자가 실제로 만나는 화면은
 * 대부분 이 파일이 만드는 것이다 — README가 자랑하는 "8초 안에 절전이라고 알려준다"가
 * 여기 있다. 백엔드는 4,390줄의 테스트가 지키는데 이 자리는 무방비였다.
 *
 * 잠그는 불변식 셋:
 *   ① 5xx 중 **어느 것을** 절전으로 볼 것인가 (넓히면 진짜 장애를 절전으로 안내한다)
 *   ② 시간이 지나면 절전으로 끊는다 (안 끊으면 CloudFront 상한 60초까지 매달린다)
 *   ③ **쓰기에는 이걸 쓰면 안 된다**는 규약이 있으므로, 여기서 abort가 요청을
 *      되돌리지 않는다는 사실을 명시적으로 남긴다
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ASLEEP_MEMORY_MS,
  QUICK_TIMEOUT_MS,
  ServerAsleepError,
  apiFetch,
  fetchWithTimeout,
  forgetAsleep,
  isAsleepStatus,
} from './http'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  // 절전 기억은 **모듈 변수**라 테스트 사이에 넘어간다. 안 지우면 앞 테스트가 남긴
  // 절전 때문에 뒤 테스트의 fetch 가 아예 안 불려 결과가 조용히 뒤바뀐다.
  forgetAsleep()
})

describe('isAsleepStatus', () => {
  it('502·503·504만 절전으로 본다', () => {
    for (const s of [502, 503, 504]) expect(isAsleepStatus(s)).toBe(true)
  })

  it('4xx와 500은 절전이 아니다 — 넓히면 진짜 장애가 "잠시 후 다시"로 안내된다', () => {
    for (const s of [200, 400, 401, 403, 404, 422, 429, 500]) {
      expect(isAsleepStatus(s)).toBe(false)
    }
  })
})

describe('fetchWithTimeout', () => {
  it('정상 응답은 그대로 돌려준다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })))
    const res = await fetchWithTimeout('/x')
    expect(res.status).toBe(200)
  })

  it('503을 ServerAsleepError로 바꾼다 (호출부가 절전 안내를 하는 근거)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 503 })))
    await expect(fetchWithTimeout('/x')).rejects.toBeInstanceOf(ServerAsleepError)
  })

  it('404는 그대로 통과시킨다 — 없는 글을 절전이라고 하면 안 된다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404 })))
    const res = await fetchWithTimeout('/x')
    expect(res.status).toBe(404)
  })

  it('응답이 없으면 절전으로 끊는다 (abort → ServerAsleepError)', async () => {
    // signal이 abort되면 실제 fetch처럼 AbortError를 던지는 가짜
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            )
          }),
      ),
    )
    await expect(fetchWithTimeout('/x', {}, 5)).rejects.toBeInstanceOf(ServerAsleepError)
  })

  it('기본 상한은 8초 — CloudFront 오리진 상한 60초보다 훨씬 짧아야 안내가 빨라진다', () => {
    expect(QUICK_TIMEOUT_MS).toBe(8000)
    expect(QUICK_TIMEOUT_MS).toBeLessThan(60000)
  })

  it('네트워크 오류는 절전으로 바꾸지 않는다 — 원인을 덮으면 진단이 어긋난다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await expect(fetchWithTimeout('/x')).rejects.toBeInstanceOf(TypeError)
  })
})

/**
 * **절전을 기억한다** (2026-09-02).
 *
 * 판정은 08-11부터 있었는데 그 사실을 아무도 안 들고 있었다. 목록에서 8초를 내고
 * 절전 안내를 본 사람이 글을 누르면 또 8초, 뒤로 가서 태그를 누르면 또 8초다.
 * 서버가 꺼져 있는 게 이 사이트의 평상시라 그 낭비가 기본 경로였다.
 *
 * 잠그는 것 넷:
 *   ① 절전을 확인한 뒤에는 fetch 를 **부르지도 않는다** (기다림이 0이 된다)
 *   ② 상한 없는 쓰기(apiFetch)도 같은 기억을 본다 — 거기가 제일 오래 매달리는 자리다
 *   ③ 응답이 오면 기억을 버린다 (서버가 켜졌는데 앱만 우기는 창이 없어야 한다)
 *   ④ 기억은 60초짜리다 — 영구히 들고 있으면 켜진 서버를 못 만난다
 */
describe('절전 기억', () => {
  it('① 한 번 절전을 보면 다음 요청은 보내지도 않는다', async () => {
    const f = vi.fn(async () => new Response('', { status: 504 }))
    vi.stubGlobal('fetch', f)
    await expect(fetchWithTimeout('/x')).rejects.toBeInstanceOf(ServerAsleepError)
    await expect(fetchWithTimeout('/y')).rejects.toBeInstanceOf(ServerAsleepError)
    expect(f).toHaveBeenCalledTimes(1) // 두 번째는 네트워크를 안 탄다
  })

  it('② 상한 없는 쓰기(apiFetch)도 같은 기억에 걸린다', async () => {
    const f = vi.fn(async () => new Response('', { status: 503 }))
    vi.stubGlobal('fetch', f)
    await expect(apiFetch('/write')).rejects.toBeInstanceOf(ServerAsleepError)
    await expect(apiFetch('/write')).rejects.toBeInstanceOf(ServerAsleepError)
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('③ 응답이 한 번 오면 기억을 버린다 — 404도 서버가 만든 답이다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 504 })))
    await expect(fetchWithTimeout('/x')).rejects.toBeInstanceOf(ServerAsleepError)
    const f = vi.fn(async () => new Response('', { status: 404 }))
    vi.stubGlobal('fetch', f)
    forgetAsleep() // 사람이 새로고침을 누른 경우(StatusPage)
    expect((await fetchWithTimeout('/x')).status).toBe(404)
    // 404를 받았으니 서버는 살아 있다 → 그다음 요청도 실제로 나간다
    await fetchWithTimeout('/y')
    expect(f).toHaveBeenCalledTimes(2)
  })

  it('④ 60초가 지나면 다시 물어본다', async () => {
    vi.useFakeTimers()
    const f = vi.fn(async () => new Response('', { status: 504 }))
    vi.stubGlobal('fetch', f)
    await expect(fetchWithTimeout('/x')).rejects.toBeInstanceOf(ServerAsleepError)
    vi.advanceTimersByTime(ASLEEP_MEMORY_MS + 1)
    await expect(fetchWithTimeout('/x')).rejects.toBeInstanceOf(ServerAsleepError)
    expect(f).toHaveBeenCalledTimes(2) // 이번엔 실제로 다시 물었다
  })

  it('네트워크 오류는 기억하지 않는다 — 서버 상태를 말해 주는 신호가 아니다', async () => {
    const f = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    vi.stubGlobal('fetch', f)
    await expect(fetchWithTimeout('/x')).rejects.toBeInstanceOf(TypeError)
    await expect(fetchWithTimeout('/x')).rejects.toBeInstanceOf(TypeError)
    expect(f).toHaveBeenCalledTimes(2)
  })
})

/**
 * **절전 판정이 너무 넓었다** (2026-09-05, 09-04 검사의 FE-1·FE-2).
 *
 * 09-02에 절전 기억을 넣으면서 502·503·504를 전부 "오리진이 안 떴다"로 접었는데,
 * 그 셋이 항상 오리진 실패는 아니다. 이 파일 맨 위가 이미 경고한 것과 같은 병이다:
 * 판정을 넓히면 진짜 장애가 절전으로 안내된다.
 *
 *   ① 앱이 스스로 낸 503 — 백엔드는 서로 다른 503을 셋 낸다(서버 키 없음 · BYOK
 *      복호화 실패 · 업스트림 도달 실패). `ai.ts`가 그 셋을 구분해 안내하는 코드를
 *      08-11에 넣었는데, 09-02 이후 그 분기가 **도달 불가**가 됐다. 사용자는
 *      "키를 다시 등록해줘" 대신 "서버가 절전 중이야"를 본다.
 *   ② 오래 기다린 끝의 504 — 주차된 오리진은 1초 안에 504를 낸다(연결 시도 1회 ·
 *      연결 상한 1초, 09-04 실측 1.38초). 60초를 다 쓰고 온 504는 오리진이 살아서
 *      붙잡고 있었다는 뜻이다. 그걸 절전으로 기억하면 서버가 깨어 있는데 60초 동안
 *      쓰기가 막힌다 — AI 초안은 1분 넘게 걸리는 게 예정된 경로다.
 *   ③ 호출부가 건 signal — `{ ...init, signal: ac.signal }`이 스프레드 뒤라
 *      호출부 signal을 덮어썼다. `ai.ts`의 90초 안전장치가 fetch에 연결되지 않아
 *      죽어 있었고, 그 AbortError 분기도 도달 불가였다.
 */
describe('절전 판정의 경계', () => {
  it('① 앱이 JSON으로 답한 503은 절전이 아니다 — 서버가 말을 하고 있다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: '설정에서 키를 다시 등록해줘' }), {
            status: 503,
            headers: { 'content-type': 'application/json' },
          }),
      ),
    )
    const res = await apiFetch('/ai/draft')
    expect(res.status).toBe(503)
    expect((await res.json()).detail).toContain('다시 등록')
  })

  it('① JSON 503을 받아도 절전 기억이 남지 않는다 — 다음 요청이 실제로 나간다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response('{"detail":"x"}', {
            status: 503,
            headers: { 'content-type': 'application/json' },
          }),
      ),
    )
    await apiFetch('/ai/draft')
    const f = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', f)
    expect((await apiFetch('/posts')).status).toBe(200)
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('② 60초를 다 쓰고 온 504는 절전으로 기억하지 않는다', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        vi.advanceTimersByTime(61_000) // 오리진이 붙잡고 있던 시간
        return new Response('', { status: 504 })
      }),
    )
    const res = await apiFetch('/ai/draft')
    expect(res.status).toBe(504)
    const f = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', f)
    expect((await apiFetch('/posts')).status).toBe(200)
    expect(f).toHaveBeenCalledTimes(1) // 기억이 남았다면 안 불렸을 것이다
  })

  it('② 1초 만에 온 504는 그대로 절전이다 — 주차된 오리진의 실제 응답', async () => {
    const f = vi.fn(async () => new Response('', { status: 504 }))
    vi.stubGlobal('fetch', f)
    await expect(apiFetch('/posts')).rejects.toBeInstanceOf(ServerAsleepError)
    await expect(apiFetch('/posts')).rejects.toBeInstanceOf(ServerAsleepError)
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('③ 호출부가 건 signal이 살아 있다 — abort하면 실제로 끊긴다', async () => {
    const f = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          )
        }),
    )
    vi.stubGlobal('fetch', f)
    const ctrl = new AbortController()
    const p = apiFetch('/ai/draft', { signal: ctrl.signal })
    ctrl.abort()
    await expect(p).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('③ 호출부의 abort는 절전이 아니다 — 서버 상태를 말해 주는 신호가 아니다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            )
          }),
      ),
    )
    const ctrl = new AbortController()
    const p = apiFetch('/ai/draft', { signal: ctrl.signal })
    ctrl.abort()
    await expect(p).rejects.toMatchObject({ name: 'AbortError' })
    // 절전으로 기억했다면 다음 요청이 네트워크를 안 탄다
    const f = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', f)
    expect((await apiFetch('/posts')).status).toBe(200)
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('③ 우리 상한이 끊은 것은 여전히 절전이다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            )
          }),
      ),
    )
    await expect(fetchWithTimeout('/x', {}, 5)).rejects.toBeInstanceOf(ServerAsleepError)
  })
})
