// @vitest-environment jsdom
//
// 목차가 **본문과 같은 id를 가리키는지** 잠근다.
//
// 왜 이 테스트가 생겼나 (2026-08-18): 목차를 왼쪽에 고정으로 빼고 나서 화면에서
// 발견했다. 개발일지에 이런 소제목이 있다:
//
//     ## 5. 첫 번째 사고 — 화면에 &#39;가 글자로 보였다
//
// 본문은 react-markdown이 `&#39;`를 `'`로 풀어서 그리고, id를 붙이는 rehype-slug도
// **풀린 글자**를 기준으로 만든다. 그런데 목차는 마크다운 원문을 읽으므로 `39`라는
// 숫자가 남아 **서로 다른 id**가 됐다. 즉 그 항목은 눌러도 아무 데도 안 갔다.
//
// 상태코드도 200이고 테스트도 초록이었다 — 링크가 죽었는지는 눌러봐야 아는 종류다.
// 그래서 여기서 잠근다: 목차의 href가 본문 heading의 id와 **같은 문자열**인지.
import { describe, it, expect, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { Toc } from './Toc'

let root: Root | null = null
let host: HTMLDivElement | null = null

function render(md: string, variant: 'inline' | 'aside' = 'inline') {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  act(() => {
    root!.render(<Toc content={md} variant={variant} />)
  })
  return host
}

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  root = null
  host = null
})

/** 목차 링크의 href에서 # 뒤 부분만. */
function hrefs(el: HTMLElement): string[] {
  return [...el.querySelectorAll('a')].map((a) => a.getAttribute('href')!.slice(1))
}

describe('Toc — 목차가 가리키는 id', () => {
  it('HTML 엔티티가 든 소제목도 본문과 같은 id를 가리킨다', () => {
    const el = render(['# 글', '', "## 화면에 &#39;가 글자로 보였다", '', '## 두 번째'].join('\n'))
    // 39가 남아 있으면 rehype-slug가 만든 id와 어긋난다 = 눌러도 안 가는 링크
    expect(hrefs(el)[0]).not.toContain('39')
    expect(hrefs(el)[0]).toBe('화면에-가-글자로-보였다')
  })

  it('엔티티를 화면 글자로도 푼다 — 목차에 &#39;가 그대로 보이면 안 된다', () => {
    const el = render(['## 화면에 &#39;가 글자로 보였다', '', '## 두 번째'].join('\n'))
    expect(el.textContent).toContain("화면에 '가 글자로 보였다")
    expect(el.textContent).not.toContain('&#39;')
  })

  it('&amp;는 한 번만 푼다 — 두 번 풀면 &amp;#39; 가 따옴표가 된다', () => {
    const el = render(['## A &amp;#39; B', '', '## 두 번째'].join('\n'))
    expect(el.textContent).toContain('A &#39; B')
  })

  it('&amp; &lt; &gt; &quot; 와 16진 참조를 푼다', () => {
    const el = render(['## R&amp;D &lt;태그&gt; &quot;따옴표&quot; &#x27;작은따옴표&#x27;', '', '## 둘'].join('\n'))
    expect(el.textContent).toContain('R&D <태그> "따옴표" \'작은따옴표\'')
  })

  it('코드블록 안의 #은 소제목이 아니다', () => {
    const md = ['## 진짜 제목', '', '```', '## 주석입니다', '#!/bin/sh', '```', '', '## 또 진짜'].join('\n')
    const el = render(md)
    expect(el.querySelectorAll('a')).toHaveLength(2)
    expect(el.textContent).not.toContain('주석입니다')
  })

  it('같은 제목이 두 번이면 두 번째에 -1이 붙는다(rehype-slug와 같은 규칙)', () => {
    const el = render(['## 같은 제목', '', '## 같은 제목'].join('\n'))
    expect(hrefs(el)).toEqual(['같은-제목', '같은-제목-1'])
  })

  it('①②③ 같은 기호 숫자는 지운다 — rehype-slug와 같게', () => {
    // \p{N}으로 두면 ①이 남아 본문 id(①이 지워진 것)와 어긋난다.
    // 앞에 남는 하이픈도 그대로 둔다 — rehype-slug가 안 다듬는다.
    const el = render(['## ① 소제목에 id는 있는데', '', '## ② 아이콘 파일은 다 있는데'].join('\n'))
    expect(hrefs(el)).toEqual(['-소제목에-id는-있는데', '-아이콘-파일은-다-있는데'])
  })

  it('보통 숫자는 남긴다 — 기호 숫자만 지우는 것이지 숫자를 지우는 게 아니다', () => {
    const el = render(['## 2.4%만 보고 있었다', '', '## 84개로 늘었다'].join('\n'))
    expect(hrefs(el)).toEqual(['24만-보고-있었다', '84개로-늘었다'])
  })

  it('소제목이 2개 미만이면 아무것도 안 그린다', () => {
    expect(render('## 하나뿐').textContent).toBe('')
  })

  it('고정 목차(aside)도 같은 링크를 낸다 — 두 모양이 갈라지면 안 된다', () => {
    const md = ['## 화면에 &#39;가 글자로 보였다', '', '## 두 번째'].join('\n')
    const inline = hrefs(render(md, 'inline'))
    act(() => root?.unmount())
    host?.remove()
    const aside = hrefs(render(md, 'aside'))
    expect(aside).toEqual(inline)
  })
})
