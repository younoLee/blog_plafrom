// @vitest-environment jsdom
//
// 복사 버튼이 **실제로 복사하는가**를 잠근다. 이 버튼은 실패해도 화면이 안 깨져서,
// 망가지면 아무도 모른 채 '눌러도 아무 일 없는 버튼'으로 남는다.
//
// 잠그는 것 셋:
//   ① 코드블록은 마크다운 원문이 아니라 **렌더된 텍스트**를 복사한다
//      (원문을 복사하면 ```와 언어 태그가 딸려가 붙여넣은 쪽에서 안 돌아간다)
//   ② navigator.clipboard가 없어도 동작한다 — https·localhost 밖에서는 undefined다.
//      그냥 부르면 TypeError로 죽어서 조용히 아무 일도 안 일어난다
//   ③ 복사에 실패하면 '복사됨'이라고 하지 않는다 (버튼이 거짓말을 하면 안 된다)
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CopyButton } from './CopyButton'
import { CodeBlock } from '../pages/PostDetailPage'

let container: HTMLDivElement
let root: Root

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
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
  if (execStubbed) {
    delete (document as { execCommand?: unknown }).execCommand
    execStubbed = false
  }
  vi.useRealTimers()
})

const click = async (btn: HTMLButtonElement) => {
  await act(async () => {
    btn.click()
  })
}

// jsdom에는 execCommand가 **없다**(undefined). 그래서 폴백 검사는 목을 심어야 하는데,
// `vi.stubGlobal('document', Object.assign(document, …))`는 새 객체로 바꾸는 게 아니라
// **진짜 document를 그 자리에서 변형**한다 → `unstubAllGlobals()` 뒤에도 목이 남아
// 같은 파일의 다음 테스트로 샌다(2026-08-12 검사에서 실측). 직접 넣고 직접 지운다.
let execStubbed = false
function stubExecCommand(fn: () => boolean) {
  Object.defineProperty(document, 'execCommand', { value: fn, configurable: true, writable: true })
  execStubbed = true
}

describe('CopyButton', () => {
  it('① 코드블록은 렌더된 텍스트를 복사한다 (원문 펜스가 아니라)', async () => {
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText } })

    await act(async () => {
      root.render(
        <CodeBlock>
          <code>sudo docker compose up -d --build</code>
        </CodeBlock>,
      )
    })

    const btn = container.querySelector('button')!
    // jsdom은 레이아웃이 없어 innerText를 textContent로 대신 채워야 한다
    const pre = container.querySelector('pre')!
    Object.defineProperty(pre, 'innerText', { value: pre.textContent, configurable: true })

    await click(btn)
    expect(writeText).toHaveBeenCalledWith('sudo docker compose up -d --build')
    expect(btn.textContent).toBe('복사됨')
  })

  it('② clipboard API가 없는 환경에서도 복사한다', async () => {
    vi.stubGlobal('navigator', {}) // 보안 컨텍스트가 아니면 clipboard 자체가 없다
    const exec = vi.fn(() => true)
    stubExecCommand(exec)

    await act(async () => {
      root.render(<CopyButton value="https://example.test/devlog/2026-08-11.html" label="링크 복사" />)
    })

    const btn = container.querySelector('button')!
    await click(btn)
    expect(exec).toHaveBeenCalledWith('copy')
    expect(btn.textContent).toBe('복사됨')
    // 임시 textarea를 남기지 않는다
    expect(document.querySelectorAll('textarea').length).toBe(0)
  })

  it('②-B 폴백이 false를 돌려주면 "복사됨"이라고 하지 않는다', async () => {
    // **이 저장소가 실제로 틀렸던 자리다.** execCommand는 실패해도 던지지 않고 false를
    // 준다(권한 거부·user-gesture 밖). 반환값을 안 보면 아무것도 복사 안 됐는데 '복사됨'이
    // 뜬다. 앞선 ②는 성공만 고정해서 이 갈래를 **구조적으로 못 봤다**.
    vi.stubGlobal('navigator', {})
    const exec = vi.fn(() => false)
    stubExecCommand(exec)

    await act(async () => {
      root.render(<CopyButton value="https://example.test/x.html" label="링크 복사" />)
    })

    const btn = container.querySelector('button')!
    await click(btn)
    expect(exec).toHaveBeenCalledWith('copy')
    expect(btn.textContent).toBe('링크 복사') // 거짓말하지 않는다
    expect(document.querySelectorAll('textarea').length).toBe(0) // 실패해도 안 남긴다
  })

  it('③ 브라우저가 막으면 "복사됨"이라고 하지 않는다', async () => {
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText: async () => {
          throw new Error('NotAllowedError')
        },
      },
    })

    await act(async () => {
      root.render(<CopyButton value="x" label="링크 복사" />)
    })

    const btn = container.querySelector('button')!
    await click(btn)
    expect(btn.textContent).toBe('링크 복사')
  })

  it('빈 값이면 아무 일도 하지 않는다', async () => {
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText } })

    await act(async () => {
      root.render(<CopyButton value={() => ''} label="복사" />)
    })

    await click(container.querySelector('button')!)
    expect(writeText).not.toHaveBeenCalled()
  })
})
