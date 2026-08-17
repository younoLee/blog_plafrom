// @vitest-environment jsdom
//
// 랜딩(/)이 **입구만** 보여주는지 잠근다.
//
// 이력이 중요하다. 2026-08-12에 이 화면은 정반대를 잠그고 있었다 — 서버가 꺼진 날
// 첫 화면이 비지 않도록 정적 목록(devlog-index.json)을 읽어 최근 5편과 분량 배지를
// 그렸고, 그 테스트가 '목록을 API가 아니라 정적 파일에서 읽는다'를 지켰다.
// 2026-08-17에 사용자 결정으로 그 섹션을 걷어냈다: 랜딩은 서비스 입구만 둔다.
//
// **읽는 경로를 대신 어디가 지키는가** — 지우기 전에 확인한 것이다:
//   · /blog가 절전 중 정적 목록을 그린다 → pages/HomePage.test.tsx가 잠근다
//   · 푸터의 '개발일지 아카이브'(/devlog.html)·RSS는 그대로다
// 그래서 여기서 목록이 사라져도 서버 꺼진 날 방문자가 글까지 가는 길은 남는다.
//
// 잠그는 것 둘:
//   ① 랜딩은 **아무것도 부르지 않는다** — /api/*도, /devlog-index.json도.
//      (첫 화면에 데이터 의존을 되돌리면 절전 중 로딩·빈 자리가 다시 생긴다)
//   ② 입구 카드 둘(블로그·상태정보)이 뜨고 각각 제 라우트를 가리킨다
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import PortalPage from './PortalPage'

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

// jsdom에는 IntersectionObserver가 없다. Reveal(헤드라인·입구 카드가 쓴다)이 이걸
// 부르므로 없으면 화면 전체가 못 뜬다 — 즉 이 스텁이 없으면 테스트가 랜딩이 아니라
// jsdom을 검사한다. **바로 보이는 것으로 친다**(관심사는 애니메이션이 아니라 '무엇이 그려지나').
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

describe('PortalPage — 입구만 있는 첫 화면', () => {
  it('① 아무것도 부르지 않는다 (API도, 정적 목록도)', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(
      async () => new Response('{}', { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await mount()

    expect(fetchMock).not.toHaveBeenCalled()
    // 걷어낸 것들이 실제로 사라졌는가
    expect(container.textContent).not.toContain('최근 개발일지')
    expect(container.textContent).not.toContain('전체 보기')
    expect(container.textContent).not.toContain('만 자')
  })

  it('② 입구 카드 둘이 제 라우트를 가리킨다', async () => {
    await mount()

    expect(container.textContent).toContain('기록하는')
    expect(container.textContent).toContain('블로그')
    expect(container.textContent).toContain('상태정보')

    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'))
    expect(hrefs).toContain('/blog')
    expect(hrefs).toContain('/status')
  })
})
