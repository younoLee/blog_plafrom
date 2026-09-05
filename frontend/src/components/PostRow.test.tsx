// @vitest-environment jsdom
//
// 목록 한 줄의 **삭제 확인창**을 잠근다 (09-04 검사 FQ-11).
//
// 이 확인창은 되돌릴 수 없는 동작 앞의 유일한 방어선이다 — 글을 지우면 댓글까지 같이
// 지워지고 복구 경로가 없다. 그런데 `window.confirm` 은 jsdom 에서 기본값이 없어서
// 테스트를 안 쓰면 **취소를 눌렀을 때 정말 안 지우는지**를 아무도 확인하지 않는다.
// 이 컴포넌트는 HomePage·AuthorPage 두 목록이 공유하므로 회귀 하나가 두 화면에 번진다.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { PostRow } from './PostRow'
import type { PostSummary } from '../types/post'

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

const POST: PostSummary = {
  id: 7,
  title: '지울 글',
  excerpt: '발췌',
  reading_minutes: 1,
  cover_image: null,
  tags: [],
  series: null,
  owner_id: 1,
  author_name: '유노',
  author_handle: null,
  visibility: 'public',
  created_at: '2026-09-05T00:00:00Z',
  updated_at: '2026-09-05T00:00:00Z',
}

function render(onDelete: (id: number) => void) {
  act(() => {
    root.render(
      <MemoryRouter>
        <PostRow post={POST} canEdit onDelete={onDelete} />
      </MemoryRouter>,
    )
  })
  const btn = [...container.querySelectorAll('button')].find((b) => b.textContent === '삭제')
  if (!btn) throw new Error('삭제 버튼이 없다')
  return btn
}

beforeEach(() => {
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

describe('PostRow 삭제', () => {
  it('확인창에서 취소하면 지우지 않는다', () => {
    const onDelete = vi.fn()
    vi.stubGlobal('confirm', vi.fn(() => false))
    const btn = render(onDelete)
    act(() => btn.click())
    expect(onDelete).not.toHaveBeenCalled()
  })

  it('확인하면 그 글의 id로 지운다', () => {
    const onDelete = vi.fn()
    vi.stubGlobal('confirm', vi.fn(() => true))
    const btn = render(onDelete)
    act(() => btn.click())
    expect(onDelete).toHaveBeenCalledWith(7)
  })

  it('확인 문구에 글 제목이 들어간다 — 무엇을 지우는지 모르고 누르면 방어선이 아니다', () => {
    const confirmSpy = vi.fn(() => false)
    vi.stubGlobal('confirm', confirmSpy)
    const btn = render(vi.fn())
    act(() => btn.click())
    expect(String(confirmSpy.mock.calls[0])).toContain('지울 글')
  })

  it('권한이 없으면 삭제 버튼 자체가 없다', () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <PostRow post={POST} canEdit={false} onDelete={vi.fn()} />
        </MemoryRouter>,
      )
    })
    expect([...container.querySelectorAll('button')].some((b) => b.textContent === '삭제')).toBe(false)
  })
})
