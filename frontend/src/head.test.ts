// @vitest-environment jsdom
//
// head.ts는 index.html의 태그를 **덮어쓰고 되돌리는** 물건이다. 되돌리기가 틀리면
// 증상이 "두 번째 글부터 설명이 이전 글 것"처럼 나타나는데, 화면에는 아무 표시가
// 없어서 눈으로는 못 잡는다. 그래서 원래값 복구를 정면으로 잠근다.
import { describe, it, expect, beforeEach } from 'vitest'
import { applyHead, resetHeadBaseline } from './head'

const BASE_DESC = '개발과 인프라를 기록하는 블로그.'

beforeEach(() => {
  resetHeadBaseline()
  // 순서 주의: head.innerHTML을 갈아끼우면 <title> 엘리먼트가 같이 날아가
  // document.title이 ''이 된다. 제목은 **그 뒤에** 넣는다.
  document.head.innerHTML = `
    <meta name="description" content="${BASE_DESC}">
    <meta property="og:type" content="website">
    <meta property="og:title" content="블로그 만들기">
    <meta property="og:description" content="${BASE_DESC}">
    <meta property="og:url" content="https://example.test/">
    <meta name="twitter:title" content="블로그 만들기">
    <meta name="twitter:description" content="${BASE_DESC}">`
  document.title = '블로그 만들기'
})

const get = (sel: string, attr = 'content') => document.querySelector(sel)?.getAttribute(attr)

describe('applyHead', () => {
  it('index.html에 없던 canonical을 만들어 붙인다', () => {
    expect(document.querySelector('link[rel="canonical"]')).toBeNull()
    applyHead({ title: '있는데 닿지 않았다', canonical: 'https://example.test/devlog/2026-08-14.html' })
    expect(get('link[rel="canonical"]', 'href')).toBe('https://example.test/devlog/2026-08-14.html')
  })

  it('canonical을 안 주면 현재 주소를 쓰되 쿼리·해시는 뗀다', () => {
    // `/reset?token=…`의 1회용 토큰이 메타 태그로 새 나가면 안 된다.
    window.history.replaceState({}, '', '/reset?token=secret-123#부분')
    applyHead({ title: '비밀번호 재설정' })
    const href = get('link[rel="canonical"]', 'href')!
    expect(href).toBe(`${window.location.origin}/reset`)
    expect(href).not.toContain('secret-123')
    expect(get('meta[property="og:url"]')).not.toContain('secret-123')
  })

  it('탭 제목엔 사이트명을 붙이고 og:title엔 안 붙인다', () => {
    applyHead({ title: '제목' })
    expect(document.title).toBe('제목 — 블로그 만들기')
    // og:site_name이 카드에 따로 뜨므로 여기 붙이면 이름이 두 번 나온다.
    expect(get('meta[property="og:title"]')).toBe('제목')
    expect(get('meta[name="twitter:title"]')).toBe('제목')
  })

  it('설명을 안 주면 사이트 기본 설명이 남는다 (빈 카드가 되지 않는다)', () => {
    applyHead({ title: '제목' })
    expect(get('meta[property="og:description"]')).toBe(BASE_DESC)
  })

  it('되돌리면 원래값으로 정확히 복구되고 canonical은 사라진다', () => {
    const undo = applyHead({ title: '제목', description: '글 발췌', type: 'article' })
    expect(get('meta[property="og:type"]')).toBe('article')

    undo()

    expect(document.title).toBe('블로그 만들기')
    expect(get('meta[name="description"]')).toBe(BASE_DESC)
    expect(get('meta[property="og:title"]')).toBe('블로그 만들기')
    expect(get('meta[property="og:type"]')).toBe('website')
    expect(document.querySelector('link[rel="canonical"]')).toBeNull()
  })

  it('글 A→B로 이어서 걸어도 "원래값"이 A로 오염되지 않는다', () => {
    // 여기가 진짜 함정이다. 스냅샷을 apply마다 다시 뜨면 B를 되돌렸을 때
    // 사이트 기본 설명이 아니라 **A의 발췌**가 남는다.
    const undoA = applyHead({ title: 'A', description: 'A 발췌' })
    undoA()
    const undoB = applyHead({ title: 'B', description: 'B 발췌' })
    undoB()
    expect(get('meta[name="description"]')).toBe(BASE_DESC)
    expect(document.title).toBe('블로그 만들기')
  })

  it('되돌리기 없이 A 위에 B를 겹쳐 걸어도 마찬가지다', () => {
    applyHead({ title: 'A', description: 'A 발췌' })
    const undoB = applyHead({ title: 'B', description: 'B 발췌' })
    expect(get('meta[property="og:description"]')).toBe('B 발췌')
    undoB()
    expect(get('meta[name="description"]')).toBe(BASE_DESC)
  })
})
