// @vitest-environment jsdom
//
// 알림 종의 **키보드 닫기**를 잠근다 (09-04 검사 FQ-11).
//
// 2026-08-11 공백검사가 잡은 사고가 여기 있었다 — 닫는 경로가 바깥 클릭(mousedown)
// 하나뿐이라, 키보드만 쓰는 사람은 종을 열고 나면 마우스를 쓰거나 페이지를 옮기기
// 전까지 **닫을 수 없었다.** 고치면서 '닫을 때 포커스를 종으로 되돌린다'까지 넣었는데
// (안 그러면 포커스가 사라진 요소에 남는다) 그 둘을 잠그는 시험이 없었다.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { NotificationBell } from './NotificationBell'

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  // 종은 마운트 즉시 알림을 조회한다. 빈 목록으로 답해 화면만 세운다.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ items: [], unread: 0 }), { status: 200 })),
  )
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

async function mount() {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    )
  })
  const btn = container.querySelector('button')
  if (!btn) throw new Error('종 버튼이 없다')
  return btn
}

describe('알림 종', () => {
  it('Escape로 닫히고 포커스가 종으로 돌아온다', async () => {
    const btn = await mount()
    await act(async () => btn.click())
    expect(btn.getAttribute('aria-expanded')).toBe('true')

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    })
    expect(btn.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(btn)
  })

  it('바깥을 누르면 닫힌다', async () => {
    const btn = await mount()
    await act(async () => btn.click())
    await act(async () => {
      document.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    })
    expect(btn.getAttribute('aria-expanded')).toBe('false')
  })

  it('안 읽음이 있으면 배지가 뜬다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ items: [], unread: 3 }), { status: 200 })),
    )
    const btn = await mount()
    expect(btn.textContent).toContain('3')
    expect(btn.getAttribute('aria-label')).toContain('안 읽음 3')
  })
})
