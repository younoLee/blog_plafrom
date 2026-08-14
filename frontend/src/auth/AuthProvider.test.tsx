// @vitest-environment jsdom
//
// 세션이 끊겼을 때 화면이 **왜 풀렸는지 말하는가**를 잠근다.
//
// 왜 이게 테스트할 값이 있는가 — 여기서 구분해야 하는 두 상황이 겉으로 똑같다.
// 둘 다 '토큰이 사라지고 비로그인이 된다'로 끝난다.
//   ① 내가 로그아웃을 눌렀다        → 안내가 뜨면 안 된다(내가 한 일이다)
//   ② 다른 기기가 내 세션을 끊었다   → 안내가 떠야 한다(안 뜨면 내가 뭘 잘못했다고 믿는다)
// 구분은 api/auth.ts의 logout이 **보내기 전에 토큰을 지우는** 한 줄에 걸려 있다.
// 그 줄은 지워도 아무 화면도 안 깨지고 테스트도 안 깨지는 종류라, 여기서 잡는다.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { AuthProvider } from './AuthProvider'
import { useAuth } from './auth-context'
import { apiFetch } from '../api/http'
import { clearToken, setToken } from '../api/session'
import * as authApi from '../api/auth'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

let container: HTMLDivElement
let root: Root

// 안내 띠는 Layout에 있고 Layout은 라우터를 요구한다. 여기서 보려는 건 '띠의 모양'이
// 아니라 **provider가 sessionEnded를 켜는가**이므로, 그 값만 찍는 최소 소비자를 쓴다.
function Probe() {
  const { user, sessionEnded } = useAuth()
  return (
    <div>
      <span data-testid="ended">{String(sessionEnded)}</span>
      <span data-testid="user">{user ? user.email : 'none'}</span>
    </div>
  )
}

const ended = () => container.querySelector('[data-testid="ended"]')?.textContent

async function mount() {
  await act(async () => {
    root.render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
  })
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  clearToken()
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
  clearToken()
})

describe('세션 만료 안내', () => {
  it('처음엔 꺼져 있다 — 익명 방문자에게 뜨면 안 된다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })))
    await mount()
    expect(ended()).toBe('false')
  })

  it('인증 요청이 401을 받으면 켜진다 (다른 기기가 세션을 끊은 경우)', async () => {
    setToken('t')
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })))
    await mount()
    expect(ended()).toBe('false')

    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })))
    await act(async () => {
      await apiFetch('/x', { headers: { Authorization: 'Bearer t' } })
    })

    expect(ended()).toBe('true')
  })

  it('내가 누른 로그아웃에서는 안 켜진다 — 서버가 401을 줘도', async () => {
    // 화면은 정상 로그인 상태로 떠 있고(마운트 때 200), 그 사이 서버에서는 토큰이
    // 죽어 있다. 그 상태로 로그아웃을 누르면 서버는 401을 준다.
    // 그래도 이건 **내가 한 일**이므로 안내가 뜨면 안 된다.
    setToken('t')
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })))
    await mount()

    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })))
    await act(async () => {
      await authApi.logout()
    })

    expect(ended()).toBe('false')
  })

  it('앱을 열 때 토큰이 이미 죽어 있으면 켜진다 — 자리 비운 새 세션이 끝난 경우', async () => {
    // 위 테스트와 겉모습이 같다(마운트 → 401). 다른 건 '내가 눌렀는가'뿐이고,
    // 그 차이가 실제로 화면을 다르게 만든다는 걸 여기서 못박는다.
    setToken('expired')
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })))
    await mount()

    expect(ended()).toBe('true')
  })
})
