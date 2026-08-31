// @vitest-environment jsdom
//
// 개인 블로그 화면(/@handle)에서 **페이지를 넘겨도 태그·연재 필터가 남는지** 잠근다.
//
// 왜 이 테스트가 있나 (2026-08-31): 페이지 이동이 `setSearchParams({ page })`라
// 쿼리스트링을 통째로 갈아치웠다. 그런데 tag·series는 searchParams에서만 읽고 목록
// effect의 의존성에 들어 있어서, 주소에서 빠지는 즉시 전체 목록으로 재조회가 돈다.
// 즉 `/@yuno?tag=aws`에서 '다음'을 누른 사람은 좁힌 목록의 2쪽을 기대하는데 필터가
// 풀린 전체를 보게 된다. 08-27에 이 화면에 필터를 넣으면서 페이지 이동 쪽을 같이
// 안 고친 자리이고, HomePage는 처음부터 병합해서 안 샜다. 같은 동작의 구현이 두 화면에
// 갈라져 새로 붙은 쪽만 틀린, 이 저장소의 단골 모양이다.
//
// 잠그는 것 둘:
//   ① '다음'을 누르면 주소에 page가 올라가고 **tag가 그대로 남는다**
//   ② 그 뒤 목록 재조회도 tag를 그대로 들고 간다 — 주소만 남고 조회가 안 물려가면
//      화면은 여전히 전체 목록이라 사용자가 겪는 증상은 똑같다
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import AuthorPage from './AuthorPage'
import { AuthContext, type AuthState } from '../auth/auth-context'

const fetchPostsMock = vi.fn()

vi.mock('../api/posts', async () => {
  const actual = await vi.importActual<typeof import('../api/posts')>('../api/posts')
  return { ...actual, fetchPosts: (...args: unknown[]) => fetchPostsMock(...args) }
})
vi.mock('../api/authors', () => ({
  fetchAuthor: async () => ({ id: 1, handle: 'yuno', display_name: '유노', bio: '', post_count: 24 }),
}))
// 스킨은 이 테스트의 관심사가 아니다. 되돌리기 함수만 돌려준다.
vi.mock('../api/skin', () => ({ applySkinFor: async () => () => {} }))

function makePosts(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    title: `글 ${i + 1}`,
    content: '본문',
    created_at: '2026-08-20T00:00:00Z',
    visibility: 'public',
    tags: ['aws'],
    owner_id: 1,
    author_handle: 'yuno',
    author_name: '유노',
  }))
}

const GUEST: AuthState = {
  user: null,
  loading: false,
  login: async () => {},
  logout: () => {},
  refresh: async () => {},
} as unknown as AuthState

let container: HTMLDivElement
let root: Root

/**
 * 주소창 대신 읽을 자리. 라우터 안에서만 useLocation을 쓸 수 있다.
 * 모듈 변수에 대입하지 않고 **DOM에 그려서** 읽는다 — 렌더 중 바깥 값을 건드리면
 * eslint의 react-hooks 규칙에 걸리고, 실제로도 렌더가 두 번 도는 StrictMode에서
 * 읽는 시점에 따라 값이 달라진다.
 */
function SearchProbe() {
  return <span data-testid="search">{useLocation().search}</span>
}

function currentSearch() {
  return container.querySelector('[data-testid="search"]')?.textContent ?? ''
}

beforeEach(() => {
  fetchPostsMock.mockReset()
  // 24편이라 10편씩 3쪽 — 페이지 이동 버튼이 그려진다.
  fetchPostsMock.mockResolvedValue({ items: makePosts(10), total: 24 })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

async function renderAt(url: string) {
  await act(async () => {
    root.render(
      <AuthContext.Provider value={GUEST}>
        <MemoryRouter initialEntries={[url]}>
          <SearchProbe />
          <Routes>
            <Route path="/:handle" element={<AuthorPage />} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>,
    )
  })
}

function clickNext() {
  const next = Array.from(container.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes('다음'),
  )
  expect(next, "'다음' 버튼이 없다 — 페이지가 하나뿐인 상태로 렌더된 것이다").toBeTruthy()
  return next as HTMLButtonElement
}

describe('AuthorPage 페이지 이동', () => {
  it('다음 쪽으로 가도 tag가 주소에 남는다', async () => {
    await renderAt('/@yuno?tag=aws')
    expect(currentSearch()).toContain('tag=aws')

    await act(async () => {
      clickNext().click()
    })

    expect(currentSearch()).toContain('page=2')
    expect(currentSearch(), '페이지를 넘기자 tag가 사라졌다 — 필터가 풀린 전체 목록이 된다').toContain(
      'tag=aws',
    )
  })

  it('다음 쪽 조회도 tag를 들고 간다', async () => {
    await renderAt('/@yuno?tag=aws')
    await act(async () => {
      clickNext().click()
    })

    const last = fetchPostsMock.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(last.author).toBe('yuno')
    expect(last.tag, '재조회에 tag가 안 실렸다 — 주소만 남고 목록은 전체가 된다').toBe('aws')
    expect(last.offset, '2쪽인데 offset이 0이다').toBe(10)
  })

  it('검색어를 넣으면 주소와 조회에 q가 실리고 1쪽으로 돌아간다', async () => {
    // 2026-08-31에 붙인 검색. 서버는 author+q를 함께 거를 수 있는데 이 화면만
    // q를 안 넘겨서 '이 사람 글 안에서 찾기'가 앱 안에 없었다.
    await renderAt('/@yuno?page=3')
    const input = container.querySelector('input[type="search"]') as HTMLInputElement
    expect(input, '검색 입력칸이 없다').toBeTruthy()

    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )!.set!
      setter.call(input, '테라폼')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => {
      input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })

    expect(currentSearch()).toContain('q=')
    expect(currentSearch(), '검색하면 1쪽부터 봐야 한다').not.toContain('page=3')
    const last = fetchPostsMock.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(last.q, '조회에 q가 안 실렸다 — 주소만 바뀌고 목록은 그대로다').toBe('테라폼')
    expect(last.offset, '검색인데 3쪽 offset 그대로다').toBe(0)
  })

  it('주소에 q가 있으면 첫 조회부터 그 값을 들고 간다', async () => {
    await renderAt('/@yuno?q=백업')
    const first = fetchPostsMock.mock.calls[0]?.[0] as Record<string, unknown>
    expect(first.q).toBe('백업')
    expect(first.author).toBe('yuno')
  })

  it("'✕ 전체보기'로 검색을 풀면 입력칸도 같이 비워진다", async () => {
    // 2026-08-31 검사에서 나온 것: 목록만 전체로 돌아가고 입력칸에는 검색어가 남아
    // 화면이 자기 주소와 다른 말을 하고 있었다. HomePage 에는 있던 동기화가 여기만 없었다.
    await renderAt('/@yuno?q=백업')
    const input = () => container.querySelector('input[type="search"]') as HTMLInputElement
    expect(input().value).toBe('백업')

    const clear = Array.from(container.querySelectorAll('a')).find((a) =>
      (a.textContent ?? '').includes('전체보기'),
    )
    expect(clear, "'✕ 전체보기' 링크가 없다").toBeTruthy()
    await act(async () => {
      clear!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }))
    })

    expect(currentSearch()).not.toContain('q=')
    expect(input().value, '주소에서 검색을 뺐는데 입력칸에 검색어가 남는다').toBe('')
  })

  it('필터가 없을 때도 페이지 이동은 그대로 된다', async () => {
    await renderAt('/@yuno')
    await act(async () => {
      clickNext().click()
    })
    expect(currentSearch()).toContain('page=2')
    expect(currentSearch()).not.toContain('tag=')
  })
})
