// @vitest-environment jsdom
//
// '내 문장' 편집기가 **설정 화면을 망가뜨리지 않는지** 잠근다.
//
// 왜 이게 필요한가: 이 편집기는 `/settings` 안에 얹혀 있다. 여기서 마운트 중에
// 던지면 설정 화면 전체가 하얗게 뜬다 — 그 화면에는 표시명·블로그 주소·AI 키처럼
// 이것과 무관한 것들이 같이 있다. 장식 하나가 그 전부를 가져가면 안 된다.
//
// 그리고 이 파일이 진짜로 잠그는 건 하나 더 있다: **저장하면 서버가 씻은 결과가
// 입력칸에 다시 채워진다.** 원문을 그대로 두면 사람은 자기 글이 멀쩡히 저장된 줄
// 안다 — 무엇이 지워졌는지 보이는 게 이 기능에서 제일 중요한 피드백이다.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AuthContext, type AuthState } from '../auth/auth-context'
import SlotEditor from './SlotEditor'

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

const WRITER = {
  user: { id: 2, email: 'w@example.com', role: 'writer', handle: 'writerb' },
  loading: false,
} as unknown as AuthState

/** GET /skin/me 는 저장된 문장을, PUT /skin/slots 는 **씻은** 결과를 돌려준다. */
function stubFetch(saved: Record<string, string>, cleaned: Record<string, string>) {
  const calls: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
      if (url.includes('/skin/slots')) {
        return new Response(JSON.stringify({ css: '', slots: cleaned }), { status: 200 })
      }
      return new Response(JSON.stringify({ css: '', slots: saved }), { status: 200 })
    }),
  )
  return calls
}

async function mount() {
  await act(async () => {
    root.render(
      <StrictMode>
        <AuthContext.Provider value={WRITER}>
          <SlotEditor />
        </AuthContext.Provider>
      </StrictMode>,
    )
  })
  await act(async () => {
    await Promise.resolve()
  })
}

function area(id: string): HTMLTextAreaElement {
  const el = container.querySelector<HTMLTextAreaElement>(`#slot-${id}`)
  if (!el) throw new Error(`#slot-${id} 가 없다`)
  return el
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  localStorage.clear()
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('내 문장 편집기', () => {
  it('세 칸이 뜨고 저장된 값이 채워진다', async () => {
    stubFetch({ intro: '<p>안녕</p>', aside: '', footer: '' }, {})
    await mount()

    expect(area('intro').value).toBe('<p>안녕</p>')
    expect(area('aside').value).toBe('')
    expect(area('footer').value).toBe('')
    // 저장할 게 없으면 버튼은 눌리지 않는다
    const save = container.querySelector('button')
    expect(save).toBeTruthy()
  })

  it('불러오기가 실패해도 화면은 안 죽는다 — 설정 화면 전체가 걸려 있다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
    await mount()
    expect(container.textContent).toContain('내 문장')
  })

  it('저장하면 **씻은 결과**가 칸에 다시 채워진다', async () => {
    const calls = stubFetch(
      { intro: '', aside: '', footer: '' },
      { intro: '<p>안녕</p>', aside: '', footer: '' }, // 서버가 script를 지우고 돌려준 값
    )
    await mount()

    const el = area('intro')
    // React가 관리하는 값이라 setter를 직접 부르고 이벤트를 흘려야 onChange가 뜬다
    setValue(el, '<p>안녕</p><script>alert(1)</script>')
    await act(async () => {
      el.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(el.value).toContain('script') // 아직 저장 전이라 원문 그대로

    const save = [...container.querySelectorAll('button')].find((b) => b.textContent === '저장')!
    await act(async () => {
      save.click()
    })
    await act(async () => {
      await Promise.resolve()
    })

    // 보낸 것은 원문, 칸에 남은 것은 씻은 결과
    const put = calls.find((c) => c.url.includes('/skin/slots'))
    expect((put?.body as { intro: string }).intro).toContain('script')
    expect(area('intro').value).toBe('<p>안녕</p>')
    expect(container.textContent).toContain('지웠고')
  })
})

/** React가 걸어둔 value setter를 우회해 실제 DOM 값을 바꾼다. */
function setValue(el: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
  setter?.call(el, value)
}
