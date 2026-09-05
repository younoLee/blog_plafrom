// @vitest-environment jsdom
//
// 결제 화면에 시험이 0건이었다 (09-04 검사 GAP-10 · GAP-7).
//
// 이 사이트에서 돈이 오가는 유일한 화면인데, 그 화면의 어떤 문장도 잠겨 있지 않았다.
// 여기서 잠그는 것 셋:
//   ① 해지 확인창이 **남은 기간이 사라진다는 사실**을 말한다. 환불이 없으므로 이 동작은
//      '다음 결제를 안 한다'가 아니라 '지금 산 것을 지금 버린다'다(09-04 검사 GAP-7).
//   ② 확인창에서 취소하면 해지 요청이 나가지 않는다.
//   ③ 결제 내역이 실패·대기 주문도 보여주고, '확인 중'을 실패로 적지 않는다.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import PaymentPage from './PaymentPage'
import { AuthContext, type AuthState } from '../auth/auth-context'
import { forgetAsleep } from '../api/http'

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

function proUser(daysLeft: number) {
  return {
    user: {
      id: 1,
      email: 'me@example.com',
      role: 'writer',
      is_pro: true,
      pro_until: new Date(Date.now() + daysLeft * 86400000).toISOString(),
    },
    loading: false,
    refreshUser: vi.fn(),
  } as unknown as AuthState
}

function stubFetch(payments: unknown[] = []) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/payments/me')) return new Response(JSON.stringify(payments), { status: 200 })
    if (url.includes('/payments/unsubscribe'))
      return new Response(JSON.stringify({ id: 1, is_pro: false }), { status: 200 })
    return new Response('{}', { status: 200 })
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

async function mount(auth: AuthState) {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <AuthContext.Provider value={auth}>
          <PaymentPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )
  })
  await act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve()
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

function unsubBtn() {
  const btn = [...container.querySelectorAll('button')].find((b) => b.textContent === '구독 해지')
  if (!btn) throw new Error('구독 해지 버튼이 없다')
  return btn
}

describe('구독 해지', () => {
  it('확인창이 남은 기간이 사라진다고 말한다', async () => {
    stubFetch()
    const confirmSpy = vi.fn(() => false)
    vi.stubGlobal('confirm', confirmSpy)
    await mount(proUser(12))

    await act(async () => unsubBtn().click())

    const said = String(confirmSpy.mock.calls[0])
    expect(said).toContain('12일')
    expect(said).toContain('환불은 없어')
  })

  it('취소하면 해지 요청이 나가지 않는다', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('confirm', vi.fn(() => false))
    await mount(proUser(3))

    await act(async () => unsubBtn().click())

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('unsubscribe'))).toBe(false)
  })

  it('확인하면 해지 요청이 나간다', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('confirm', vi.fn(() => true))
    await mount(proUser(3))

    await act(async () => unsubBtn().click())
    await act(async () => {
      for (let i = 0; i < 10; i++) await Promise.resolve()
    })

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('unsubscribe'))).toBe(true)
  })
})

describe('결제 내역', () => {
  it('실패·대기 주문도 보여준다', async () => {
    stubFetch([
      {
        order_id: 'o1',
        order_name: 'Pro',
        amount: 9900,
        status: 'pending',
        receipt_url: null,
        created_at: '2026-09-01T00:00:00Z',
        paid_at: null,
      },
    ])
    vi.stubGlobal('confirm', vi.fn(() => false))
    await mount(proUser(5))

    expect(container.textContent).toContain('9,900원')
    expect(container.textContent).toContain('결제 안 함')
  })

  it("'확인 중'을 실패라고 적지 않는다", async () => {
    // 실패로 읽히면 사용자가 다시 결제해서 두 번 낼 수 있다.
    stubFetch([
      {
        order_id: 'o2',
        order_name: 'Pro',
        amount: 9900,
        status: 'confirming',
        receipt_url: null,
        created_at: '2026-09-01T00:00:00Z',
        paid_at: null,
      },
    ])
    vi.stubGlobal('confirm', vi.fn(() => false))
    await mount(proUser(5))

    expect(container.textContent).toContain('확인 중')
    expect(container.textContent).not.toContain('실패')
  })

  it('영수증이 있으면 링크를 건다', async () => {
    stubFetch([
      {
        order_id: 'o3',
        order_name: 'Pro',
        amount: 9900,
        status: 'paid',
        receipt_url: 'https://receipt.example/abc',
        created_at: '2026-09-01T00:00:00Z',
        paid_at: '2026-09-01T00:01:00Z',
      },
    ])
    vi.stubGlobal('confirm', vi.fn(() => false))
    await mount(proUser(5))

    const link = container.querySelector('a[href="https://receipt.example/abc"]')
    expect(link?.textContent).toBe('영수증')
  })

  it('아직 결제한 적이 없으면 그렇게 말한다', async () => {
    stubFetch([])
    vi.stubGlobal('confirm', vi.fn(() => false))
    await mount(proUser(5))
    expect(container.textContent).toContain('아직 결제한 적이 없어')
  })
})
