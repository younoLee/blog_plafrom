// @vitest-environment jsdom
//
// 글 목록 화면(/blog)이 **서버가 꺼져 있어도** 읽을 것을 내놓는지 잠근다.
//
// 왜 이 테스트가 있나 (2026-08-17 진단): 이 사이트는 EC2를 평소 꺼둔다. 랜딩(/)은
// 08-12부터 정적 목록(devlog-index.json)을 읽어 서버 없이도 글이 보였는데, 정작
// '블로그' 입구를 눌러 들어오는 이 화면은 절전 안내만 띄우고 **비어 있었다**.
// 자산 32편·26만 자가 방문자에게 0편으로 보이는 상태였고, 절전이 평상시라 그게 첫인상이다.
//
// 잠그는 것 넷:
//   ① 절전(504)이면 정적 목록을 읽어 그린다 — 목록이 비지 않는다
//   ② 링크가 정적 아카이브(/devlog/*.html)다 — SPA 라우트로 바꾸면 서버 꺼진 날
//      클릭이 죽어서 목록을 그린 의미가 사라진다
//   ③ 태그 필터는 정적 목록에도 적용된다 — 안 하면 #AWS를 눌렀는데 전부 나온다
//   ④ **진짜 에러(500)에는 정적 목록을 깔지 않는다** — 서버는 살아 있는데 뭔가
//      잘못된 것이라, 목록을 깔면 고장을 정상처럼 덮는다
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import HomePage from './HomePage'
import { forgetAsleep } from '../api/http'
import { AuthContext, type AuthState } from '../auth/auth-context'

const INDEX = {
  total: 3,
  chars: 30000,
  posts: [
    {
      date: '2026-08-15',
      title: '블로그 만들기 #32 — 처방이 이 집에서만 안 들었다',
      slug: 'devlog/2026-08-15.html',
      summary: '남은 11건을 전부 닫기로 하고 앉았다.',
      tags: ['개발일지', 'AWS'],
    },
    {
      date: '2026-08-14',
      title: '블로그 만들기 #31 — 있는데 닿지 않았다',
      slug: 'devlog/2026-08-14.html',
      summary: '도는 것과 닿는 것은 다르다.',
      tags: ['개발일지'],
    },
    {
      date: '2026-08-12',
      title: '블로그 만들기 #30 — 내가 만든 검사가 나를 안심시켰다',
      slug: 'devlog/2026-08-12.html',
      summary: '감시가 로컬에서만 초록이었다.',
      tags: ['개발일지'],
    },
  ],
}

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

// 로그인 상태는 이 테스트의 관심사가 아니다. useAuth는 Provider 밖에서 던지므로
// 익명 사용자 한 명분만 채워 넣는다(화면이 보는 건 user?.id 하나다).
const ANON = { user: null, loading: false } as unknown as AuthState

async function mount(initial = '/blog') {
  await act(async () => {
    root.render(
      <StrictMode>
        <MemoryRouter initialEntries={[initial]}>
          <AuthContext.Provider value={ANON}>
            <HomePage />
          </AuthContext.Provider>
        </MemoryRouter>
      </StrictMode>,
    )
  })
  // 절전 판정 → 정적 목록 fetch → setState 까지 한 틱 더 준다.
  await act(async () => {
    await Promise.resolve()
  })
}

/** /api/* 는 주어진 상태로, /devlog-index.json 은 정적 목록으로 답한다. */
function stubFetch(apiStatus: number) {
  const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async (input) => {
    const url = String(input)
    if (url.includes('/devlog-index.json'))
      return new Response(JSON.stringify(INDEX), { status: 200 })
    return new Response('{}', { status: apiStatus })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

// jsdom엔 IntersectionObserver가 없다(Reveal이 부른다). 없으면 화면이 못 떠서
// 이 테스트가 목록이 아니라 jsdom을 검사하게 된다.
class IOStub {
  cb: IntersectionObserverCallback
  constructor(cb: IntersectionObserverCallback) {
    this.cb = cb
  }
  observe(el: Element) {
    this.cb([{ isIntersecting: true, target: el } as IntersectionObserverEntry], this as never)
  }
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  // http.ts 는 절전을 60초 기억한다(2026-09-02). 모듈 변수라 **테스트 사이에 넘어가서**,
  // 안 지우면 앞 테스트의 504 때문에 뒤 테스트가 fetch 를 타지도 못하고 절전으로 끝난다.
  // head.ts 의 resetHeadBaseline 과 같은 자리의 같은 처리다.
  forgetAsleep()
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.stubGlobal('IntersectionObserver', IOStub)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('HomePage — 절전 중에도 읽을 것이 있다', () => {
  it('① 절전(504)이면 정적 목록을 그린다', async () => {
    stubFetch(504)
    await mount()

    expect(container.textContent).toContain('서버가 절전 중이야')
    expect(container.textContent).toContain('처방이 이 집에서만 안 들었다')
    expect(container.textContent).toContain('있는데 닿지 않았다')
    // 절전인데 '아직 글이 없어'가 같이 뜨면 안 된다 — 글은 있다.
    expect(container.textContent).not.toContain('아직 글이 없어')
    // '0개'도 거짓이다. 실제로 그린 편수를 말해야 한다.
    expect(container.textContent).not.toContain('0개')
    expect(container.textContent).toContain('정적 목록 3편')
  })

  it('② 링크가 정적 아카이브다 — 서버 없이 클릭이 산다', async () => {
    stubFetch(504)
    await mount()

    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'))
    expect(hrefs).toContain('/devlog/2026-08-15.html')
    // SPA 라우트로 새어 나가면 안 된다(그 주소는 서버가 켜져야 내용이 찬다).
    expect(hrefs.some((h) => h?.startsWith('/blog/posts/'))).toBe(false)
  })

  it('③ 태그 필터가 정적 목록에도 걸린다', async () => {
    stubFetch(504)
    await mount('/blog?tag=AWS')

    expect(container.textContent).toContain('처방이 이 집에서만 안 들었다')
    expect(container.textContent).not.toContain('있는데 닿지 않았다')
    expect(container.textContent).toContain('정적 목록 1편')
  })

  it('④ 진짜 에러(500)면 정적 목록을 깔지 않는다 — 고장을 덮지 않는다', async () => {
    const fetchMock = stubFetch(500)
    await mount()

    expect(container.textContent).not.toContain('처방이 이 집에서만 안 들었다')
    // **오류가 화면에 뜨는가**를 본다. 예전엔 '에러'라는 낱말을 찾았는데, 그건 화면에
    // 붙어 있던 `에러:` 접두사를 단언한 것이라 문구를 고치면 같이 깨진다(2026-08-27에
    // 그 접두사를 지우면서 실제로 깨졌다). 이 테스트가 지키려는 것은 낱말이 아니라
    // '고장을 조용히 덮지 않는다'이므로, 경고 역할이 있는 자리에 서버가 준 이유가
    // 들어 있는지를 본다.
    const alert = container.querySelector('[role="alert"]')
    expect(alert).not.toBeNull()
    expect(alert?.textContent).toContain('목록 불러오기 실패')
    // 읽으러 가지도 않아야 한다(절전일 때만 읽는다).
    const urls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(urls.some((u) => u.includes('/devlog-index.json'))).toBe(false)
  })
})
