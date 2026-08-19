// @vitest-environment jsdom
//
// `/@handle`을 열 때 **남의 문장이 그 사람 말처럼 보이지 않는지** 잠근다.
//
// 이 사이트는 서버(EC2)를 평소 꺼둔다. 그래서 스킨은 localStorage에 캐시해 두고
// 첫 페인트 전에 바른다 — 그 캐시는 '이 사이트의 기본 외형', 즉 **주인 것**이다.
// 그 상태로 `/@남의주소`를 열면 요청이 실패하고, 주인의 자기소개와 연락처가 남의
// 블로그에 그대로 남아 있었다(2026-08-19 검사). 색이 남는 건 덜 예쁜 것뿐이지만
// 문장이 남는 건 거짓말이다.
//
// 두 번째로 잠그는 것은 **늦게 온 응답**이다. `/@a`에서 `/@b`로 옮긴 뒤 a가 도착하면
// 지금 보고 있는 b의 화면이 a의 색·문장으로 덮인다.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { applySkinFor, applyCachedSkin } from './skin'
import { getSlots } from './slots'

const OWNER = {
  css: ':root { --color-accent: #215ba6 }',
  slots: { intro: '<p>주인 머리말</p>', aside: '<p>주인 연락처</p>', footer: '<p>주인 푸터</p>' },
}
const WRITER = {
  css: ':root { --color-accent: #20c997 }',
  slots: { intro: '<p>글쓴이 머리말</p>', aside: '', footer: '' },
}

/** 주인 것이 캐시에 들어 있는 상태 = 이 사이트를 한 번이라도 연 사람의 평상시 상태. */
function seedOwnerCache() {
  localStorage.setItem('blog_skin_css', OWNER.css)
  localStorage.setItem('blog_skin_slots', JSON.stringify(OWNER.slots))
  applyCachedSkin()
}

function allSlotText(): string {
  const s = getSlots()
  return `${s.intro}${s.aside}${s.footer}`
}

beforeEach(() => {
  localStorage.clear()
  document.getElementById('blog-skin')?.remove()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('applySkinFor — 남의 문장이 남지 않는다', () => {
  it('서버가 꺼져 있으면 주인 문장을 지운다 (색은 남겨도 된다)', async () => {
    seedOwnerCache()
    expect(allSlotText()).toContain('주인 머리말') // 출발점 확인

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('네트워크 실패(절전)')
      }),
    )
    await applySkinFor('writerb')

    // 문장은 하나도 남으면 안 된다 — 이게 이 파일의 핵심이다
    expect(allSlotText()).toBe('')
    // 색은 남아도 된다. 지우면 캐시를 만든 이유(깜빡임 제거)가 되돌아간다
    expect(document.getElementById('blog-skin')?.textContent).toBe(OWNER.css)
  })

  it('응답이 오기 전에도 주인 문장이 안 보인다', async () => {
    seedOwnerCache()
    let release: (() => void) | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise((resolve) => {
            release = () =>
              resolve(new Response(JSON.stringify(WRITER), { status: 200 }) as never)
          }),
      ),
    )
    const pending = applySkinFor('writerb')
    // 아직 응답 전 — 화면이 그려지는 순간이다
    expect(allSlotText()).toBe('')
    release!()
    await pending
    expect(getSlots().intro).toBe('<p>글쓴이 머리말</p>')
  })

  it('그 사람 문장이 도착하면 그것만 보인다', async () => {
    seedOwnerCache()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(WRITER), { status: 200 })),
    )
    await applySkinFor('writerb')
    expect(getSlots().intro).toBe('<p>글쓴이 머리말</p>')
    expect(allSlotText()).not.toContain('주인')
  })

  it('늦게 온 응답은 지금 보고 있는 화면을 안 덮는다', async () => {
    seedOwnerCache()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(WRITER), { status: 200 })),
    )
    // 이미 다른 곳으로 떠난 뒤에 도착한 상황
    await applySkinFor('writerb', () => true)
    expect(allSlotText()).toBe('')
    expect(document.getElementById('blog-skin')?.textContent).toBe(OWNER.css)
  })

  it('되돌리기는 사이트 것으로 돌아간다', async () => {
    seedOwnerCache()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(WRITER), { status: 200 })),
    )
    const restore = await applySkinFor('writerb')
    restore()
    expect(getSlots().intro).toBe('<p>주인 머리말</p>')
    expect(document.getElementById('blog-skin')?.textContent).toBe(OWNER.css)
  })
})
