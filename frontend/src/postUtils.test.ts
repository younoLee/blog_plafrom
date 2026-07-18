import { describe, it, expect } from 'vitest'
import { excerpt, readingTime } from './postUtils'

describe('excerpt', () => {
  it('마크다운 기호를 벗긴다(헤딩·불릿·강조·코드)', () => {
    const out = excerpt('# 제목\n\n- **굵게** 그리고 `코드`')
    expect(out).not.toContain('#')
    expect(out).not.toContain('*')
    expect(out).not.toContain('`')
    expect(out).toContain('굵게')
  })

  it('이미지는 통째로 제거하고 링크는 표시 텍스트만 남긴다', () => {
    const out = excerpt('![alt](http://x/y.png) [클릭](http://z)')
    expect(out).not.toContain('http')
    expect(out).not.toContain('alt')
    expect(out).toContain('클릭')
  })

  it('개행·연속공백을 한 칸으로 접는다', () => {
    expect(excerpt('a\n\n\nb   c')).toBe('a b c')
  })

  it('max를 넘으면 잘라내고 …를 붙인다', () => {
    const out = excerpt('가'.repeat(200), 10)
    expect(out.endsWith('…')).toBe(true)
    expect(out.length).toBeLessThanOrEqual(11) // 10자 + …
  })

  it('짧으면 그대로 두고 …를 안 붙인다', () => {
    expect(excerpt('짧은 글')).toBe('짧은 글')
  })
})

describe('readingTime', () => {
  it('최소 1분은 보장한다(짧은 글·빈 글)', () => {
    expect(readingTime('')).toBe(1)
    expect(readingTime('안녕')).toBe(1)
  })

  it('분당 약 500자로 반올림한다', () => {
    expect(readingTime('가'.repeat(500))).toBe(1)
    expect(readingTime('가'.repeat(1500))).toBe(3)
  })
})
