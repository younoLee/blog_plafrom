/**
 * api/posts.ts — 쿼리 조립·상태코드별 메시지·하위호환 shim 검증.
 *
 * 왜 여기부터인가: 이 파일엔 "실제 사고를 겪고 넣은 코드"가 있는데 아무것도 그걸
 * 지키지 않았다. 특히 fetchPosts의 배열/객체 호환 분기는 프론트가 백엔드보다
 * 먼저 배포돼 사이드바가 비었던 사고(PROGRESS:915) 때문에 생긴 것이라,
 * 조용히 지워지면 같은 사고가 재발한다.
 *
 * 컴포넌트 테스트가 아니라 jsdom·testing-library 없이 돈다(의존성 추가 없음).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { POSTS_PAGE_SIZE, fetchPosts, getPost } from './posts'

// authHeaders()가 토큰을 localStorage에서 읽는데 vitest 기본 환경(node)엔 없다.
// jsdom을 새로 들이는 대신 필요한 만큼만 stub한다(의존성 추가 0).
beforeEach(() => {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  })
})

/** fetch를 가로채 호출 URL을 기록하고 지정한 응답을 돌려준다. */
function stubFetch(res: { status?: number; ok?: boolean; json?: unknown }) {
  const calls: string[] = []
  const status = res.status ?? 200
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url)
      return {
        status,
        ok: res.ok ?? (status >= 200 && status < 300),
        json: async () => res.json,
      }
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchPosts — 쿼리 조립', () => {
  it('limit/offset을 안 주면 기본값을 넣는다', async () => {
    const calls = stubFetch({ json: { items: [], total: 0, limit: 10, offset: 0 } })
    await fetchPosts()
    expect(calls[0]).toContain(`limit=${POSTS_PAGE_SIZE}`)
    expect(calls[0]).toContain('offset=0')
  })

  it('q·tag는 값이 있을 때만 붙는다 (빈 문자열이면 생략)', async () => {
    const calls = stubFetch({ json: { items: [], total: 0, limit: 10, offset: 0 } })
    await fetchPosts({ q: '', tag: '개발일지' })
    expect(calls[0]).not.toContain('q=')
    expect(calls[0]).toContain('tag=')
  })

  it('검색어의 특수문자를 인코딩한다 (그대로 붙이면 쿼리가 깨진다)', async () => {
    const calls = stubFetch({ json: { items: [], total: 0, limit: 10, offset: 0 } })
    await fetchPosts({ q: 'a&b=c' })
    expect(calls[0]).toContain('q=a%26b%3Dc')
    expect(calls[0]).not.toContain('q=a&b=c')
  })
})

describe('fetchPosts — 하위호환 shim', () => {
  // 프론트가 백엔드보다 먼저 배포되면 구버전이 '배열'을 준다(PROGRESS:915).
  // 이 분기가 없으면 목록이 통째로 깨진다.
  it('배열 응답(구버전 백엔드)을 봉투 모양으로 감싼다', async () => {
    stubFetch({ json: [{ id: 1 }, { id: 2 }] })
    const r = await fetchPosts()
    expect(r.items).toHaveLength(2)
    expect(r.total).toBe(2)
    expect(r.offset).toBe(0)
  })

  it('객체 응답(현행)은 그대로 통과시킨다', async () => {
    stubFetch({ json: { items: [{ id: 1 }], total: 42, limit: 10, offset: 20 } })
    const r = await fetchPosts()
    expect(r.total).toBe(42) // items.length(1)가 아니라 서버가 준 42
    expect(r.offset).toBe(20)
  })
})

describe('상태코드 → 사용자 메시지', () => {
  it('429는 전용 안내를 준다 (일반 실패 메시지로 뭉뚱그리지 않음)', async () => {
    stubFetch({ status: 429 })
    await expect(fetchPosts()).rejects.toThrow(/너무 잦아/)
  })

  it('그 외 실패는 일반 메시지', async () => {
    stubFetch({ status: 500 })
    await expect(fetchPosts()).rejects.toThrow(/목록 불러오기 실패/)
  })

  it('getPost의 404는 "찾을 수 없어"로 구분된다', async () => {
    stubFetch({ status: 404 })
    await expect(getPost(1)).rejects.toThrow(/찾을 수 없어/)
  })
})
