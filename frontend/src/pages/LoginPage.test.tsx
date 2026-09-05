// @vitest-environment jsdom
//
// 인증 화면에 시험이 0건이었다 (09-04 검사 GAP-10).
//
// 로그인은 이 사이트에서 사람이 가장 자주 실패하는 화면이고, 실패했을 때 화면이 무엇을
// 말하는지가 전부다. 여기서 잠그는 것 넷:
//   ① 실패 문구가 **낭독기에 읽히는 자리**(role="alert")에 뜬다 — 조용히 나타나면
//      안 보이는 사용자에게는 아무 일도 안 일어난 것이다(이 화면의 오랜 규약).
//   ② 진행 중에는 다시 못 누른다 — 연타하면 서버의 10/분 리밋에 스스로 걸린다.
//   ③ 입력칸에 라벨과 autoComplete 이 있다(placeholder 는 라벨이 아니다).
//   ④ 성공하면 로그인 요청이 한 번만 나간다.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from './LoginPage'
import { AuthContext, type AuthState } from '../auth/auth-context'
import { forgetAsleep } from '../api/http'

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

function authState(login: (email: string, pw: string) => Promise<void>) {
  return { user: null, loading: false, login } as unknown as AuthState
}

async function mount(auth: AuthState) {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <AuthContext.Provider value={auth}>
          <LoginPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )
  })
}

function submit() {
  const form = container.querySelector('form')
  if (!form) throw new Error('폼이 없다')
  form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
}

// jsdom 엔 IntersectionObserver 가 없다(Reveal 이 부른다). 없으면 화면이 못 떠서
// 이 시험이 로그인 폼이 아니라 jsdom 을 검사하게 된다(HomePage.test 와 같은 처리).
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

describe('로그인 화면', () => {
  it('실패 문구가 낭독기에 읽히는 자리에 뜬다', async () => {
    await mount(authState(vi.fn(async () => { throw new Error('이메일 또는 비밀번호가 틀렸어') })))

    await act(async () => submit())

    const alert = container.querySelector('[role="alert"]')
    expect(alert?.textContent).toContain('이메일 또는 비밀번호가 틀렸어')
  })

  it('진행 중에는 다시 안 보낸다 — 연타가 서버 리밋을 태운다', async () => {
    let resolve: () => void = () => {}
    const login = vi.fn(() => new Promise<void>((r) => { resolve = r }))
    await mount(authState(login))

    await act(async () => submit())
    await act(async () => submit()) // 엔터 연타
    expect(login).toHaveBeenCalledTimes(1)

    const btn = container.querySelector('button[type="submit"]') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.getAttribute('aria-busy')).toBe('true')

    await act(async () => {
      resolve()
    })
  })

  it('입력칸에 라벨과 autoComplete 이 있다', async () => {
    await mount(authState(vi.fn(async () => {})))

    const email = container.querySelector('input[type="email"]')
    const pw = container.querySelector('input[type="password"]')
    expect(email?.getAttribute('aria-label')).toBe('이메일')
    expect(email?.getAttribute('autocomplete')).toBe('email')
    expect(pw?.getAttribute('aria-label')).toBe('비밀번호')
    expect(pw?.getAttribute('autocomplete')).toBe('current-password')
  })

  it('성공하면 한 번만 부른다', async () => {
    const login = vi.fn(async () => {})
    await mount(authState(login))
    await act(async () => submit())
    expect(login).toHaveBeenCalledTimes(1)
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })
})
