// @vitest-environment jsdom
//
// 랜딩(/)이 **서버 없이** 글 목록을 그리는지 잠근다.
//
// 왜 이 테스트가 있나 (2026-08-12 진단): 이 사이트는 EC2를 평소 꺼둔다. 그런데 첫 화면의
// 글 목록이 /api에서 오면 방문자가 가장 흔하게 보는 상태가 **빈 화면**이 된다. 그래서
// 목록을 빌드 산출물(dist/devlog-index.json)에서 읽고, 링크도 SPA 라우트가 아니라
// 정적 아카이브(/devlog/*.html)로 건다. 이 두 성질이 이 화면의 존재 이유다.
//
// 잠그는 것 셋:
//   ① 목록을 /devlog-index.json에서 읽는다 — /api/* 를 부르지 않는다
//      ("성능 개선"이라며 api/posts.ts로 갈아끼우면 서버 꺼진 날 첫 화면이 다시 빈다)
//   ② 링크가 정적 아카이브를 가리킨다 — react-router <Link to="/blog/posts/..">로 바꾸면
//      서버가 꺼진 날 클릭이 죽는다(그러면 목록을 그린 의미가 없어진다)
//   ③ 목록을 못 받아도 입구 카드는 남는다 — 정적 파일 하나 때문에 랜딩 전체가 비면 안 된다
//
// react-dom/client로 직접 마운트한다(@testing-library/react를 새로 들이지 않는다).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import PortalPage from './PortalPage'

// ⚠️ **픽스처는 6편 이상이어야 한다.** 2편만 두면 `slice(0, PREVIEW)`가 아무 일도 안 해서
// PREVIEW를 5→3으로 바꿔도 테스트가 통과한다(2026-08-12 뮤테이션 검사에서 실측).
// 6편이면 '5편만 보이고 6번째는 안 보인다'가 실제 단언이 된다.
const INDEX = {
  total: 29,
  chars: 237993,
  posts: [
    { date: '2026-08-11', title: '블로그 만들기 #29 — 검사가 실패하지 않은 것과 통과한 것은 다르다', slug: 'devlog/2026-08-11.html', summary: '타입 검사를 처음 돌려 결함 둘을 찾았다.' },
    { date: '2026-08-10', title: '블로그 만들기 #28 — 고친 자리 옆에 안 쓸린 입구가 있다', slug: 'devlog/2026-08-10.html', summary: '고친 자리 옆의 안 쓸린 입구.' },
    { date: '2026-08-09', title: '블로그 만들기 #27 — 안 한 일 목록이 먼저 썩는다', slug: 'devlog/2026-08-09.html', summary: '목록이 코드보다 먼저 낡는다.' },
    { date: '2026-08-07', title: '블로그 만들기 #26 — 초록불이 세 번 거짓말했다', slug: 'devlog/2026-08-07.html', summary: '초록불의 조건을 재봤다.' },
    { date: '2026-08-04', title: '블로그 만들기 #25 — 빨간불 네 개, 처방이 네 개 달랐다', slug: 'devlog/2026-08-04.html', summary: '같은 빨간불이 아니었다.' },
    { date: '2026-08-03', title: '블로그 만들기 #24 — 막는 것과 뚫렸는지 아는 것', slug: 'devlog/2026-08-03.html', summary: '여섯 번째 편이라 첫 화면에 안 나와야 한다.' },
  ],
}

let container: HTMLDivElement
let root: Root

// React 19의 act()는 이 플래그를 본다. 없으면 "not wrapped in act(...)" 경고가 뜬다.
declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

async function mount() {
  await act(async () => {
    root.render(
      <StrictMode>
        <MemoryRouter>
          <PortalPage />
        </MemoryRouter>
      </StrictMode>,
    )
  })
}

// jsdom에는 IntersectionObserver가 없다. Reveal(입구 카드가 쓴다)이 이걸 부르므로
// 없으면 화면 전체가 못 뜬다 — 즉 이 스텁이 없으면 테스트가 랜딩이 아니라 jsdom을 검사한다.
// **바로 보이는 것으로 친다**: 이 테스트가 보는 것은 애니메이션이 아니라 '무엇이 그려지나'다.
// (파라미터 프로퍼티 `constructor(private cb)`는 tsconfig의 erasableSyntaxOnly에 걸린다 —
//  타입만 지우면 실행되는 문법이어야 한다는 규칙이라 필드를 따로 둔다.)
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

describe('PortalPage — 서버 없이 뜨는 첫 화면', () => {
  it('① 정적 목록을 읽고 그린다 — /api를 부르지 않는다', async () => {
    // 인자 타입은 **제네릭으로** 준다. 인자 없는 화살표로 두면 calls의 원소가 빈 튜플이라
    // c[0]에서 tsc가 막고(빌드가 테스트까지 타입 검사한다), 안 쓰는 파라미터를 적으면
    // 이번엔 eslint가 막는다. 둘 다 피하는 자리가 여기다.
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(
      async () => new Response(JSON.stringify(INDEX), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await mount()

    const urls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(urls).toContain('/devlog-index.json')
    expect(urls.some((u) => u.includes('/api/'))).toBe(false)

    expect(container.textContent).toContain('최근 개발일지')
    expect(container.textContent).toContain('검사가 실패하지 않은 것과 통과한 것은 다르다')
    expect(container.textContent).toContain('고친 자리 옆에 안 쓸린 입구가 있다')
    // 자산의 크기가 첫 화면에 드러나는가 (237,993자 → "약 24만 자", 29편)
    expect(container.textContent).toContain('24만 자')
    expect(container.textContent).toContain('29편')

    // **5편만 그린다.** 6번째가 새면 첫 화면이 목록 페이지가 된다.
    expect(container.textContent).not.toContain('여섯 번째 편이라')
    const items = container.querySelectorAll('section li')
    expect(items.length).toBe(5)

    // **최신이 위.** 정렬을 뒤집으면 '최근 개발일지'가 가장 오래된 편이 된다.
    expect(items[0].textContent).toContain('2026-08-11')
    expect(items[4].textContent).toContain('2026-08-04')
  })

  it('①-B 200인데 목록이 아니면 조용히 뼈대로 남지 않는다', async () => {
    // 뼈대는 '아직 오는 중'이라는 뜻이다. 영원히 남으면 그건 로딩이 아니라 고장이다.
    vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ total: 0, chars: 0 }), { status: 200 }))

    await mount()

    expect(container.textContent).not.toContain('최근 개발일지')
    expect(container.textContent).toContain('블로그') // 입구 카드는 남는다
  })

  it('② 링크가 정적 아카이브를 가리킨다 (서버가 꺼져도 열리는 경로)', async () => {
    vi.stubGlobal('fetch', async () => new Response(JSON.stringify(INDEX), { status: 200 }))

    await mount()

    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'))
    expect(hrefs).toContain('/devlog/2026-08-11.html')
    expect(hrefs).toContain('/devlog.html')
    // SPA 글 라우트로 걸면 서버가 꺼진 날 죽는다
    expect(hrefs.some((h) => h?.startsWith('/blog/posts/'))).toBe(false)
  })

  it('③ 목록을 못 받아도 입구 카드는 남는다', async () => {
    vi.stubGlobal('fetch', async () => new Response('not found', { status: 404 }))

    await mount()

    expect(container.textContent).toContain('블로그')
    expect(container.textContent).toContain('상태정보')
    expect(container.textContent).not.toContain('최근 개발일지')
  })
})
