// @vitest-environment jsdom
//
// 글 상세의 **댓글 칸이 언제 그려지는가**를 잠근다.
//
// 왜 이 테스트가 있나 (2026-09-02): 댓글 섹션이 `post` 조건 **밖**에 있어서, 글을 못
// 불러온 화면에도 "댓글 (0)"과 입력 폼이 그대로 떴다. 절전이 이 사이트의 평상시라
// 그게 드문 경우가 아니었다. 거기서 댓글을 보내면 요청이 오래 끌다 실패하는데, 실패
// 문구는 위쪽 `error && !asleep` 조건에 걸려 **화면 어디에도 안 나온다** — 쓴 사람은
// 글을 썼는데 아무 일도 안 일어난 것으로 본다. 무슨 일이 났는지 알 단서가 0이다.
//
// 잠그는 것 넷:
//   ① 글을 못 불러오면 댓글 폼이 아예 없다 (없는 글에 댓글을 받지 않는다)
//   ② 글이 있으면 폼이 있다
//   ③ 폼 제출 실패는 **절전 여부와 무관하게** 화면에 보인다
//   ④ 댓글이 아직 안 왔으면 개수를 단언하지 않는다 ("(0)"은 사실 주장이다)
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import PostDetailPage from './PostDetailPage'
import { AuthContext, type AuthState } from '../auth/auth-context'
import { ServerAsleepError, forgetAsleep } from '../api/http'
import type { Post } from '../types/post'

const POST: Post = {
  id: 7,
  title: '테스트 글',
  content: '본문이다.',
  cover_image: null,
  tags: [],
  series: null,
  owner_id: 1,
  author_name: '유노',
  author_handle: 'yuno',
  visibility: 'public',
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
}

const getPostMock = vi.fn()
const fetchCommentsMock = vi.fn()
const addCommentMock = vi.fn()

vi.mock('../api/posts', async () => {
  const actual = await vi.importActual<typeof import('../api/posts')>('../api/posts')
  return {
    ...actual,
    getPost: (...a: unknown[]) => getPostMock(...a),
    fetchSeries: async () => null,
  }
})
vi.mock('../api/comments', () => ({
  fetchComments: (...a: unknown[]) => fetchCommentsMock(...a),
  addComment: (...a: unknown[]) => addCommentMock(...a),
  deleteComment: async () => {},
}))
// 구독 여부는 이 테스트의 관심사가 아니다(익명이라 부르지도 않는다).
vi.mock('../api/subscriptions', () => ({
  fetchMySubscriptions: async () => [],
  subscribeAuthor: async () => {},
  unsubscribeAuthor: async () => {},
}))

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

const ANON = { user: null, loading: false } as unknown as AuthState

/** jsdom엔 IntersectionObserver가 없다(Reveal이 부른다). 없으면 본문이 안 뜬다. */
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

async function mount() {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={['/blog/posts/7']}>
        <AuthContext.Provider value={ANON}>
          <Routes>
            <Route path="/blog/posts/:id" element={<PostDetailPage />} />
          </Routes>
        </AuthContext.Provider>
      </MemoryRouter>,
    )
  })
  // 글·댓글 응답과 그에 딸린 setState 까지 흘려보낸다.
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

/** React가 듣는 방식으로 값을 넣는다(값만 바꾸면 onChange가 안 돈다). */
function type(el: HTMLInputElement | HTMLTextAreaElement, v: string) {
  const proto =
    el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, v)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

const form = () => container.querySelector('form')
const commentBox = () =>
  container.querySelector<HTMLTextAreaElement>('textarea[aria-label="댓글 내용"]')

beforeEach(() => {
  forgetAsleep() // 절전 기억은 모듈 변수라 테스트 사이에 넘어간다(api/http.ts)
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.stubGlobal('IntersectionObserver', IOStub)
  // 정적 아카이브 인덱스(공유 주소·관련 글). 이 테스트의 관심사가 아니라 404로 둔다.
  vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404 })))
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('글 상세 — 댓글 칸은 글이 있을 때만', () => {
  it('① 절전으로 글을 못 불러오면 댓글 폼이 아예 없다', async () => {
    getPostMock.mockRejectedValue(new ServerAsleepError())
    fetchCommentsMock.mockRejectedValue(new ServerAsleepError())
    await mount()

    expect(container.textContent).toContain('서버가 절전 중이야')
    expect(form()).toBeNull()
    // 없는 글의 댓글 수를 말하지도 않는다
    expect(container.textContent).not.toContain('댓글 (0)')
  })

  it('② 글이 오면 댓글 폼이 있다', async () => {
    getPostMock.mockResolvedValue(POST)
    fetchCommentsMock.mockResolvedValue([])
    await mount()

    expect(container.textContent).toContain('테스트 글')
    expect(form()).not.toBeNull()
    expect(container.textContent).toContain('아직 댓글이 없어')
  })

  it('③ 폼 제출이 실패하면 그 말이 화면에 나온다 — 절전이어도 안 숨긴다', async () => {
    getPostMock.mockResolvedValue(POST)
    fetchCommentsMock.mockResolvedValue([])
    addCommentMock.mockRejectedValue(new ServerAsleepError())
    await mount()

    const name = container.querySelector<HTMLInputElement>('input[aria-label="이름"]')!
    await act(async () => {
      type(name, '지나가던 사람')
      type(commentBox()!, '댓글 본문')
    })
    await act(async () => {
      form()!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      await Promise.resolve()
    })

    expect(addCommentMock).toHaveBeenCalled()
    // 문구가 **폼 안쪽**에 있어야 한다. 위쪽 에러 줄은 절전이면 안 그려진다.
    expect(form()!.textContent).toContain('서버가 절전 중이야')
  })

  it('④ 댓글이 아직 안 왔으면 개수를 말하지 않는다', async () => {
    getPostMock.mockResolvedValue(POST)
    // 영영 안 오는 댓글 조회 — 로딩 상태를 그대로 붙잡아 둔다
    fetchCommentsMock.mockReturnValue(new Promise(() => {}))
    await mount()

    expect(container.textContent).toContain('댓글을 불러오는 중이야')
    expect(container.textContent).not.toContain('(0)')
    expect(container.textContent).not.toContain('아직 댓글이 없어')
  })
})
