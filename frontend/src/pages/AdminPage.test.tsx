// @vitest-environment jsdom
//
// 관리자 화면에 시험이 0건이었다 (09-04 검사 FQ-10).
//
// 이 화면은 되돌릴 수 없는 동작만 모아둔 곳이다 — 계정 삭제(글·댓글까지), 차단,
// 초대 발급. 그런데 그중 어느 것도 시험이 없었다. 여기서 잠그는 것 셋:
//   ① 초대 배지의 **우선순위** — 사용된 초대는 만료일이 지나도 '사용됨'이다.
//      만료로 보이면 관리자가 '아무도 안 썼다'고 읽고 다시 발급한다.
//   ② 계정 삭제 확인창에서 **취소하면 정말 안 지운다**.
//   ③ 목록을 못 불러왔을 때 '가입자가 없다'는 사실 주장을 하지 않는다.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import AdminPage from './AdminPage'
import { inviteState } from '../inviteState'
import type { Invite } from '../api/admin'
import { AuthContext, type AuthState } from '../auth/auth-context'
import { forgetAsleep } from '../api/http'

const BASE: Invite = {
  id: 1,
  email: 'x@example.com',
  role: 'pending',
  created_at: '2026-09-01T00:00:00Z',
  expires_at: '2026-09-08T00:00:00Z',
  used_at: null,
  created_by_email: null,
  used_by_email: null,
}

describe('초대 배지 우선순위', () => {
  it('사용된 초대는 만료일이 지나도 사용됨이다', () => {
    const used = { ...BASE, expires_at: '2020-01-01T00:00:00Z', used_at: '2026-09-02T00:00:00Z' }
    expect(inviteState(used).label).toBe('사용됨')
  })

  it('안 쓴 채 기한이 지나면 만료다', () => {
    expect(inviteState({ ...BASE, expires_at: '2020-01-01T00:00:00Z' }).label).toBe('만료')
  })

  it('그 밖에는 대기 중이다', () => {
    expect(inviteState({ ...BASE, expires_at: '2999-01-01T00:00:00Z' }).label).toBe('대기 중')
  })
})

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

const ADMIN = {
  user: { id: 1, email: 'admin@example.com', role: 'admin' },
  loading: false,
} as unknown as AuthState

/** 가입자 목록만 주어진 상태로, 나머지 관리자 조회는 빈 값으로 답한다. */
function stubFetch(usersStatus: number, users: unknown[] = []) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      // 204 는 본문을 가질 수 없다 — `new Response('', {status:204})` 는 던진다.
      if (init?.method === 'DELETE') return new Response(null, { status: 204 })
      if (url.includes('/admin/users')) return new Response(JSON.stringify(users), { status: usersStatus })
      if (url.includes('/admin/invites')) return new Response('[]', { status: 200 })
      return new Response('{}', { status: 500 }) // 인프라·AI 카드는 이 시험의 관심사가 아니다
    },
  )
  vi.stubGlobal('fetch', mock)
  return mock
}

/** 워커가 아니라 컴포넌트의 비동기 사슬(fetch → json → setState)을 흘려보낸다. */
async function flush() {
  await act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve()
  })
}

async function mount() {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <AuthContext.Provider value={ADMIN}>
          <AdminPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )
  })
  await act(async () => {
    await Promise.resolve()
  })
}

beforeEach(() => {
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

const USER = {
  id: 9,
  email: 'writer@example.com',
  role: 'writer',
  email_verified: true,
  is_pro: false,
  handle: null,
}

describe('가입자 관리', () => {
  it('삭제 확인창에서 취소하면 요청을 보내지 않는다', async () => {
    const fetchMock = stubFetch(200, [USER])
    vi.stubGlobal('confirm', vi.fn(() => false))
    await mount()

    const del = [...container.querySelectorAll('button')].find((b) => b.textContent === '삭제')
    expect(del).toBeTruthy()
    await act(async () => del!.click())

    expect(fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === 'DELETE')).toBe(false)
    // 행도 그대로 남아 있어야 한다
    expect(container.textContent).toContain('writer@example.com')
  })

  it('확인하면 그 행이 목록에서 빠진다', async () => {
    stubFetch(200, [USER])
    vi.stubGlobal('confirm', vi.fn(() => true))
    await mount()

    const del = [...container.querySelectorAll('button')].find((b) => b.textContent === '삭제')
    await act(async () => del!.click())
    await flush()
    expect(container.textContent).not.toContain('writer@example.com')
  })
})
