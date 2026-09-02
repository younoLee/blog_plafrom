// @vitest-environment jsdom
//
// 글쓰기 본문 칸의 **이미지 붙여넣기·드래그드롭**을 잠근다.
//
// 왜 이 테스트가 있나 (2026-09-02): 재료는 다 있는데 입구가 없었다. 업로드 함수도,
// 커서 위치 삽입도 진작 있었는데 `onPaste`·`onDrop` 이 0건이라, 스크린샷을 붙여넣는
// 가장 흔한 동작에서 브라우저 기본값이 그대로 나왔다 — 붙여넣기는 아무 일도 안
// 일어나고, 드롭은 **그 파일로 페이지를 이동해** 쓰던 글을 날린다.
//
// 잠그는 것 셋:
//   ① 이미지를 붙여넣으면 업로드하고 `![파일이름](url)` 이 본문에 들어간다
//   ② **일반 텍스트 붙여넣기는 가로채지 않는다** — 글 쓰는 칸에서 제일 흔한 동작이라
//      여기서 preventDefault 를 부르면 평범한 복사·붙여넣기가 통째로 죽는다
//   ③ 드롭도 같은 경로를 탄다
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import WritePostPage from './WritePostPage'
import { AuthContext, type AuthState } from '../auth/auth-context'

const uploadImageMock = vi.fn()

vi.mock('../api/uploads', () => ({ uploadImage: (...a: unknown[]) => uploadImageMock(...a) }))
// AI 칸과 저장은 이 테스트의 관심사가 아니다. 화면이 뜨는 데 필요한 만큼만 채운다.
vi.mock('../api/ai', () => ({
  generateDraft: async () => '',
  fetchAiModels: async () => ({ models: [], default: '' }),
  fetchKeys: async () => [],
  fetchUsage: async () => null,
}))
vi.mock('../api/posts', () => ({
  getPost: async () => null,
  createPost: async () => ({ id: 1 }),
  updatePost: async () => ({ id: 1 }),
}))

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

const WRITER = {
  user: { id: 1, email: 'me@example.com', role: 'writer', is_pro: false, created_at: '' },
  loading: false,
} as unknown as AuthState

async function mount() {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={['/write']}>
        <AuthContext.Provider value={WRITER}>
          <WritePostPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )
  })
  await act(async () => {
    await Promise.resolve()
  })
}

const body = () => container.querySelector<HTMLTextAreaElement>('textarea[aria-label="본문"]')!

function pngFile(name: string) {
  return new File(['fake'], name, { type: 'image/png' })
}

/** jsdom엔 DataTransfer 생성자가 없다. 우리가 읽는 두 가지(files·types)만 흉내 낸다. */
function withData(type: 'paste' | 'drop', data: { files: File[]; types: string[] }) {
  const ev = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(ev, type === 'paste' ? 'clipboardData' : 'dataTransfer', { value: data })
  return ev
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
  vi.clearAllMocks()
  localStorage.clear()
})

describe('글쓰기 — 이미지 붙여넣기·드롭', () => {
  it('① 이미지를 붙여넣으면 업로드하고 마크다운이 들어간다', async () => {
    uploadImageMock.mockResolvedValue('/uploads/a.png')
    await mount()

    const ev = withData('paste', { files: [pngFile('스크린샷.png')], types: ['Files'] })
    await act(async () => {
      body().dispatchEvent(ev)
      await Promise.resolve()
    })

    expect(uploadImageMock).toHaveBeenCalledTimes(1)
    expect(body().value).toContain('![스크린샷](/uploads/a.png)')
    expect(ev.defaultPrevented).toBe(true) // 브라우저 기본 붙여넣기는 막았다
  })

  it('② 일반 텍스트 붙여넣기는 가로채지 않는다', async () => {
    await mount()

    const ev = withData('paste', { files: [], types: ['text/plain'] })
    await act(async () => {
      body().dispatchEvent(ev)
      await Promise.resolve()
    })

    expect(uploadImageMock).not.toHaveBeenCalled()
    expect(ev.defaultPrevented).toBe(false) // 브라우저가 하던 대로 붙여넣는다
  })

  it('③ 드롭도 같은 경로를 탄다', async () => {
    uploadImageMock.mockResolvedValue('/uploads/b.png')
    await mount()

    const ev = withData('drop', { files: [pngFile('사진.png')], types: ['Files'] })
    await act(async () => {
      body().dispatchEvent(ev)
      await Promise.resolve()
    })

    expect(body().value).toContain('![사진](/uploads/b.png)')
    expect(ev.defaultPrevented).toBe(true) // 안 막으면 브라우저가 그 파일로 이동한다
  })

  it('업로드가 실패하면 그 말이 화면에 나온다 — 버튼 경로와 같은 처리다', async () => {
    uploadImageMock.mockRejectedValue(new Error('이미지가 너무 커 (최대 5MB)'))
    await mount()

    await act(async () => {
      body().dispatchEvent(withData('paste', { files: [pngFile('큰그림.png')], types: ['Files'] }))
      await Promise.resolve()
    })

    expect(container.textContent).toContain('이미지가 너무 커')
  })
})
