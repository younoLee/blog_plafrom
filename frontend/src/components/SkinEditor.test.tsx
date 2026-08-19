// @vitest-environment jsdom
//
// 스킨 편집기가 **직접 쓴 CSS를 먹지 않는지** 잠근다.
//
// 이 화면은 CSS 문자열 하나를 두 층으로 갈라 보여준다 — 위는 눌러서 꾸미기, 아래는
// 사람이 쓴 CSS. 가르고 합치는 과정에서 한쪽이 사라져도 화면은 멀쩡해 보이고, 사라진
// 건 **저장 버튼을 누른 다음**에야 알게 된다. 그때는 이미 서버에 덮였다.
//
// skinOptions.test.ts가 변환 자체를 잠근다면 여기서 잠그는 건 그 둘을 이어붙인
// 자리다: 체크박스를 눌렀을 때 아래층이 그대로 남는가, 저장이 두 층을 다 보내는가.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AuthContext, type AuthState } from '../auth/auth-context'
import SkinEditor from './SkinEditor'

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

const WRITER = {
  user: { id: 2, email: 'w@example.com', role: 'writer', handle: 'writerb' },
  loading: false,
} as unknown as AuthState

/** GET /skin/me 는 저장된 CSS를, PUT 은 받은 걸 그대로 돌려준다(서버는 CSS를 안 고친다). */
function stubFetch(saved: string) {
  const sent: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = init?.body ? (JSON.parse(String(init.body)) as { custom_css: string }) : null
      if (init?.method === 'PUT') {
        sent.push(body!.custom_css)
        return new Response(JSON.stringify({ css: body!.custom_css, slots: {} }), { status: 200 })
      }
      return new Response(JSON.stringify({ css: saved, slots: {} }), { status: 200 })
    }),
  )
  return sent
}

async function mount() {
  await act(async () => {
    root.render(
      <StrictMode>
        <AuthContext.Provider value={WRITER}>
          <SkinEditor />
        </AuthContext.Provider>
      </StrictMode>,
    )
  })
  await act(async () => {
    await Promise.resolve()
  })
}

function area(): HTMLTextAreaElement {
  const el = container.querySelector('textarea')
  if (!el) throw new Error('CSS 입력칸이 없다')
  return el
}

/** 이름표로 버튼을 찾는다(aria-label 또는 글자). 클래스는 손볼 때마다 바뀌므로 안 쓴다. */
function button(name: string): HTMLButtonElement {
  const all = [...container.querySelectorAll('button')]
  const hit = all.find((b) => b.getAttribute('aria-label') === name || b.textContent?.trim() === name)
  if (!hit) throw new Error(`'${name}' 버튼이 없다`)
  return hit
}

function click(el: HTMLElement) {
  act(() => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  localStorage.clear()
  document.getElementById('blog-skin')?.remove()
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('스킨 편집기 — 두 층', () => {
  it('표식 없는 옛 CSS는 통째로 입력칸에 남는다', async () => {
    // 지금 저장돼 있는 스킨이 전부 이 모양이다. 한 글자도 옮겨지면 안 된다.
    const old = ':root { --color-accent: #00c9b7 }'
    stubFetch(old)
    await mount()
    expect(area().value).toBe(old)
  })

  it('클릭해도 직접 쓴 CSS가 입력칸에 그대로 남는다', async () => {
    stubFetch('.mine { color: red }')
    await mount()

    click(button('민트'))
    expect(area().value).toBe('.mine { color: red }')

    click(button('각지게'))
    expect(area().value).toBe('.mine { color: red }')
  })

  it('저장하면 두 층이 한 문자열로 나가고, 직접 쓴 게 뒤에 온다', async () => {
    const sent = stubFetch('.mine { color: red }')
    await mount()

    click(button('민트'))
    click(button('저장'))
    await act(async () => {
      await Promise.resolve()
    })

    expect(sent).toHaveLength(1)
    const css = sent[0]
    expect(css).toContain('--color-accent: #20c997')
    // 순서가 곧 권한이다 — 뒤에 오는 쪽이 이긴다
    expect(css.indexOf('--color-accent: #20c997')).toBeLessThan(css.indexOf('.mine'))
  })

  it("'전부 기본으로'는 눌러서 만든 것과 직접 쓴 것을 같이 지운다", async () => {
    stubFetch('.mine { color: red }')
    await mount()

    click(button('민트'))
    click(button('전부 기본으로'))
    expect(area().value).toBe('')
    // 빈 문자열이어야 서버가 NULL로 되돌린다(기본 스킨)
    expect(document.getElementById('blog-skin')?.textContent).toBe('')
  })

  it('누르는 즉시 화면에 발라진다 — 저장을 기다리지 않는다', async () => {
    stubFetch('')
    await mount()

    click(button('민트'))
    expect(document.getElementById('blog-skin')?.textContent).toContain('#20c997')
  })
})
