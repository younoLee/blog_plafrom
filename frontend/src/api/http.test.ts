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

import { QUICK_TIMEOUT_MS, ServerAsleepError, fetchWithTimeout, isAsleepStatus } from './http'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
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
