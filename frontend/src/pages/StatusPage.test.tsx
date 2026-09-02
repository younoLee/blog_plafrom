// @vitest-environment jsdom
//
// 상태 페이지가 **절전과 고장을 가르는지** 잠근다.
//
// 왜 이 테스트가 있어야 하는가 (2026-08-17 검사): 이 사이트는 EC2를 평소 꺼둔다.
// HomePage는 `ServerAsleepError`를 보고 노란 안내로 톤을 낮추는데, 이 화면만 그 규약을
// 안 지켜서 `.catch`가 전부 빨간 에러였다 — **랜딩의 두 입구 중 하나가 평상시에
// 고장난 것처럼** 보였다는 뜻이다. 절전은 이 사이트의 정상 상태다.
//
// 잠그는 것 셋:
//   ① 절전(504)이면 노란 안내 — 빨간 에러가 아니다
//   ② 절전 안내는 서버 없이 읽을 수 있는 곳으로 길을 준다(정적 아카이브·교훈 색인)
//   ③ **진짜 고장(500)이면 빨간 에러다** — 톤을 낮추다가 고장까지 조용해지면 안 된다
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import StatusPage from './StatusPage'
import { forgetAsleep } from '../api/http'

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

function stubFetch(status: number) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status })),
  )
}

async function mount() {
  await act(async () => {
    root.render(
      <StrictMode>
        <MemoryRouter>
          <StatusPage />
        </MemoryRouter>
      </StrictMode>,
    )
  })
  await act(async () => {
    await Promise.resolve()
  })
}

beforeEach(() => {
  // http.ts 는 절전을 60초 기억한다(2026-09-02). 모듈 변수라 **테스트 사이에 넘어가서**,
  // 안 지우면 앞 테스트의 504 때문에 뒤 테스트가 fetch 를 타지도 못하고 절전으로 끝난다.
  // head.ts 의 resetHeadBaseline 과 같은 자리의 같은 처리다.
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

describe('StatusPage — 절전은 고장이 아니다', () => {
  it('① 504면 노란 절전 안내가 뜬다 (빨간 에러 아님)', async () => {
    stubFetch(504)
    await mount()

    expect(container.textContent).toContain('서버가 절전 중이야')
    expect(container.textContent).not.toContain('백엔드에 연결할 수 없어')
    expect(container.querySelector('.text-red-700, .text-red-300')).toBeNull()
  })

  it('② 절전 중엔 서버 없이 읽을 수 있는 곳으로 보낸다', async () => {
    stubFetch(504)
    await mount()

    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'))
    expect(hrefs).toContain('/devlog.html')
    expect(hrefs).toContain('/lessons.html')
  })

  it('③ 500(진짜 고장)이면 빨간 에러다', async () => {
    stubFetch(500)
    await mount()

    expect(container.textContent).toContain('백엔드에 연결할 수 없어')
    expect(container.textContent).not.toContain('서버가 절전 중이야')
  })
})
