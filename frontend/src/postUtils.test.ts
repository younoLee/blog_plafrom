import { describe, it, expect } from 'vitest'
import { excerpt, readingTime, archiveUrlFor } from './postUtils'

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

describe('archiveUrlFor — 공유 주소 고르기', () => {
  const posts = [
    { title: '블로그 만들기 #29 — 검사가 실패하지 않은 것과 통과한 것은 다르다', slug: 'devlog/2026-08-11.html' },
    { title: '블로그 만들기 #28 — 고친 자리 옆에 안 쓸린 입구가 있다', slug: 'devlog/2026-08-10.html' },
  ]
  const ORIGIN = 'https://d2j66m9udyg9yq.cloudfront.net'

  it('제목이 같은 편이 있으면 정적 아카이브 주소를 준다', () => {
    expect(archiveUrlFor(posts, posts[1].title, ORIGIN)).toBe(`${ORIGIN}/devlog/2026-08-10.html`)
  })

  it('없는 글이면 null — 부르는 쪽이 현재 주소를 쓴다', () => {
    expect(archiveUrlFor(posts, '어제 뭐 먹었나', ORIGIN)).toBeNull()
  })

  it('목록이 없거나(서버리스 산출물 미배포) 제목이 비면 null', () => {
    expect(archiveUrlFor(undefined, posts[0].title, ORIGIN)).toBeNull()
    expect(archiveUrlFor([], posts[0].title, ORIGIN)).toBeNull()
    expect(archiveUrlFor(posts, undefined, ORIGIN)).toBeNull()
  })

  it('슬래시가 겹치지 않는다', () => {
    // origin 끝의 /와 slug 앞의 /가 만나면 //devlog/... 가 되어 404가 난다
    expect(archiveUrlFor([{ title: 'ㄱ', slug: '/devlog/x.html' }], 'ㄱ', `${ORIGIN}/`)).toBe(
      `${ORIGIN}/devlog/x.html`,
    )
  })

  it('부분 일치로 엉뚱한 편을 주지 않는다', () => {
    // '#2'로 시작하는 제목이 여럿이라 startsWith/includes로 바꾸면 #28이 #29 자리에 온다
    expect(archiveUrlFor(posts, '블로그 만들기 #2', ORIGIN)).toBeNull()
  })
})
