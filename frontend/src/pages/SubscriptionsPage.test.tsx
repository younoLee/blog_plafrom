// @vitest-environment jsdom
//
// 구독 화면이 **모르는 것을 없다고 말하지 않는지** 잠근다.
//
// 왜 (09-04 검사 FE-5): fetchAuthors 가 실패에서 `[]` 를 돌려주고 화면도 catch 에서
// `[]` 를 넣어서, 서버가 꺼져 있거나 500이어도 "구독할 수 있는 다른 글쓴이가 아직 없어"가
// **사실처럼** 떴다. 이 사이트는 EC2를 평소 꺼두므로 그게 예외가 아니라 기본 경로다 —
// 방문자에게는 기능이 없는 블로그로 보인다. HomePage 가 loaded 플래그로 이미 막아둔
// 같은 결함("0개는 사실 주장이다")이 이 화면에만 남아 있었다.
//
// 잠그는 것 셋:
//   ① 절전(504) → 절전 안내, '아직 없어'는 안 뜬다
//   ② 진짜 실패(500) → 에러 줄, '아직 없어'는 안 뜬다
//   ③ 진짜 빈 목록(200 []) → 그때만 '아직 없어'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import SubscriptionsPage from './SubscriptionsPage'
import { forgetAsleep } from '../api/http'
import { AuthContext, type AuthState } from '../auth/auth-context'

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

// 이 화면이 user 에게서 보는 건 '로그인했는가' 하나다.
const LOGGED_IN = {
  user: { id: 1, email: 'me@example.com', role: 'writer' },
  loading: false,
} as unknown as AuthState

/** /subscriptions/authors 만 주어진 상태로, 나머지 조회는 빈 배열로 답한다. */
function stubFetch(authorsStatus: number, authorsBody = '[]') {
  vi.stubGlobal(
    'fetch',
    vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async (input) => {
      const url = String(input)
      if (url.includes('/subscriptions/authors'))
        return new Response(authorsBody, { status: authorsStatus })
      return new Response('[]', { status: 200 })
    }),
  )
}

async function mount() {
  await act(async () => {
    root.render(
      <StrictMode>
        <AuthContext.Provider value={LOGGED_IN}>
          <SubscriptionsPage />
        </AuthContext.Provider>
      </StrictMode>,
    )
  })
  // 조회 → setState 까지 한 틱 더 준다.
  await act(async () => {
    await Promise.resolve()
  })
}

beforeEach(() => {
  // http.ts 는 절전을 60초 기억한다 — 모듈 변수라 테스트 사이에 넘어간다(HomePage.test 와 같은 처리).
  forgetAsleep()
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

const NONE = '구독할 수 있는 다른 글쓴이가 아직 없어'

describe('SubscriptionsPage — 모르는 것을 없다고 말하지 않는다', () => {
  it('① 절전(504)이면 절전 안내를 띄운다', async () => {
    stubFetch(504)
    await mount()

    expect(container.textContent).toContain('서버가 절전 중이야')
    expect(container.textContent).not.toContain(NONE)
  })

  it('② 진짜 실패(500)면 에러 줄을 띄운다 — 낭독기에도 읽히게 role="alert"', async () => {
    stubFetch(500)
    await mount()

    const alert = container.querySelector('[role="alert"]')
    expect(alert?.textContent).toContain('글쓴이 목록을 불러오지 못했어')
    expect(container.textContent).not.toContain(NONE)
  })

  it('③ 진짜로 빈 목록(200 [])일 때만 "아직 없어"라고 한다', async () => {
    stubFetch(200, '[]')
    await mount()

    expect(container.textContent).toContain(NONE)
  })

  it('목록이 오면 글쓴이를 그린다', async () => {
    stubFetch(200, JSON.stringify([{ id: 7, name: '유노' }]))
    await mount()

    expect(container.textContent).toContain('유노')
    expect(container.textContent).not.toContain(NONE)
  })
})
