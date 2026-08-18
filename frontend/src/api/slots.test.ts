// @vitest-environment jsdom
/**
 * '내 문장'의 **프론트 쪽 마지막 문**을 잠근다.
 *
 * 서버가 이미 허용 목록으로 다시 쓴다(backend/app/core/html_slots.py, test_slots.py가
 * 잠근다). 그럼에도 여기를 따로 재는 이유는, 이 경로로 들어오는 값 중 **서버를 안
 * 거치는 것이 있기 때문**이다 — localStorage 캐시. 캐시는 서버가 꺼져 있을 때 화면을
 * 그리는 유일한 원천이라 없앨 수 없고, 그러면 세척도 여기 있어야 한다.
 *
 * scrubHtml은 '다시 쓰기'가 아니라 '위험한 것 제거'다. 그래서 여기 테스트는
 * "무엇이 남았나"가 아니라 **"실행되는 것이 사라졌나"**를 본다.
 */
import { describe, it, expect } from 'vitest'
import { scrubHtml, normalizeSlots, hasAnySlot, setSlots, getSlots, EMPTY_SLOTS } from './slots'

describe('scrubHtml — 실행되는 것은 남기지 않는다', () => {
  it('script는 통째로 사라진다', () => {
    expect(scrubHtml('<p>안녕</p><script>alert(1)</script>')).toBe('<p>안녕</p>')
  })

  it('안쪽 태그를 지우면 바깥이 완성되는 형태에도 안 샌다', () => {
    // 문자열 치환 방식이 정확히 여기서 샌다. DOMParser는 브라우저와 같게 읽는다.
    const out = scrubHtml('<scr<script>ipt>alert(1)</script>')
    expect(out.toLowerCase()).not.toContain('<script')
  })

  it('인라인 이벤트 핸들러가 사라진다', () => {
    const out = scrubHtml('<img src="/a.png" onerror="alert(1)" onload="alert(2)">')
    expect(out).not.toContain('onerror')
    expect(out).not.toContain('onload')
    expect(out).toContain('/a.png') // 이미지 자체는 남는다
  })

  it('javascript: 주소가 사라진다 — 탭·대소문자로 숨겨도', () => {
    for (const href of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'jav\tascript:alert(1)']) {
      const out = scrubHtml(`<a href="${href}">클릭</a>`)
      expect(out.toLowerCase().replace(/\s/g, ''), href).not.toContain('javascript:')
    }
  })

  it('iframe·object·form 같은 것이 사라진다', () => {
    const out = scrubHtml(
      '<iframe src="https://evil"></iframe><object data="x"></object><form><input></form>',
    ).toLowerCase()
    expect(out).not.toContain('<iframe')
    expect(out).not.toContain('<object')
    expect(out).not.toContain('<form')
    expect(out).not.toContain('<input')
  })

  it('평범한 문장과 이미지·링크는 그대로 산다', () => {
    const out = scrubHtml('<p>안녕 <strong>반가워</strong></p><img src="/uploads/a.png" alt="사진">')
    expect(out).toContain('<strong>반가워</strong>')
    expect(out).toContain('/uploads/a.png')
    expect(scrubHtml('<a href="https://example.com">예시</a>')).toContain('https://example.com')
    expect(scrubHtml('<a href="mailto:me@example.com">메일</a>')).toContain('mailto:')
    expect(scrubHtml('<a href="#tail">아래로</a>')).toContain('#tail')
  })

  it('빈 값은 빈 값이다', () => {
    expect(scrubHtml('')).toBe('')
  })
})

describe('세 칸 모양', () => {
  it('서버가 뭘 주든 세 칸으로 맞춘다', () => {
    expect(normalizeSlots(null)).toEqual(EMPTY_SLOTS)
    expect(normalizeSlots({ intro: 1, aside: '<p>x</p>' })).toEqual({
      intro: '', // 문자열이 아니면 버린다
      aside: '<p>x</p>',
      footer: '',
    })
  })

  it('빈 칸만 있으면 없는 것으로 센다', () => {
    expect(hasAnySlot(EMPTY_SLOTS)).toBe(false)
    expect(hasAnySlot({ ...EMPTY_SLOTS, footer: '   ' })).toBe(false)
    expect(hasAnySlot({ ...EMPTY_SLOTS, footer: '<p>x</p>' })).toBe(true)
  })
})

describe('저장소', () => {
  it('내용이 같으면 알리지 않는다 — 안 그러면 스킨 갱신마다 푸터가 깜빡인다', () => {
    setSlots({ intro: '<p>a</p>', aside: '', footer: '' })
    const first = getSlots()
    setSlots({ intro: '<p>a</p>', aside: '', footer: '' })
    // 같은 객체가 그대로 있어야 useSyncExternalStore가 다시 그리지 않는다
    expect(getSlots()).toBe(first)

    setSlots({ intro: '<p>b</p>', aside: '', footer: '' })
    expect(getSlots()).not.toBe(first)
  })
})
