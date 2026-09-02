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
