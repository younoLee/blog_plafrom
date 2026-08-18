import { describe, it, expect } from 'vitest'
import { excerpt, readingTime, archiveUrlFor, relatedPosts, coverLabel } from './postUtils'

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

describe('relatedPosts', () => {
  // 실제 데이터 모양대로: '개발일지'가 **모든 편**에 붙어 있다.
  const index = [
    { title: '#31 알림', slug: 'devlog/2026-08-14.html', date: '2026-08-14', tags: ['개발일지', '알림', '테스트'] },
    { title: '#30 검사', slug: 'devlog/2026-08-12.html', date: '2026-08-12', tags: ['개발일지', '보안', '테스트'] },
    { title: '#29 초록', slug: 'devlog/2026-08-11.html', date: '2026-08-11', tags: ['개발일지', '테스트'] },
    { title: '#28 입구', slug: 'devlog/2026-08-10.html', date: '2026-08-10', tags: ['개발일지', '보안'] },
    { title: '#27 목록', slug: 'devlog/2026-08-09.html', date: '2026-08-09', tags: ['개발일지', '운영'] },
  ]

  it('모든 편에 붙은 태그는 셈에서 뺀다 — 안 빼면 그냥 최신 3편이 된다', () => {
    // '#27 목록'은 '운영' 하나뿐이라 겹치는 게 없다. '개발일지'를 세면 여기 끼어든다.
    const r = relatedPosts(index, '#31 알림', ['개발일지', '알림', '테스트'])
    expect(r.map((x) => x.post.title)).not.toContain('#27 목록')
    expect(r.every((x) => !x.shared.includes('개발일지'))).toBe(true)
  })

  it('겹치는 태그가 많은 순, 같으면 최신 순', () => {
    const r = relatedPosts(index, '#31 알림', ['개발일지', '보안', '테스트'])
    expect(r[0].post.title).toBe('#30 검사') // 보안+테스트 2개
    expect(r[0].shared).toEqual(['보안', '테스트'])
    expect(r[1].post.title).toBe('#29 초록') // 테스트 1개, 더 최신
    expect(r[2].post.title).toBe('#28 입구') // 보안 1개
  })

  it('자기 자신은 빼고, 겹치는 게 없으면 빈 배열 (억지로 채우지 않는다)', () => {
    expect(relatedPosts(index, '#31 알림', ['개발일지', '알림', '테스트']).map((x) => x.post.title))
      .not.toContain('#31 알림')
    expect(relatedPosts(index, '#27 목록', ['개발일지', '운영'])).toEqual([])
  })

  it('구별되는 태그가 하나도 없으면(공통 태그뿐) 빈 배열', () => {
    expect(relatedPosts(index, '#31 알림', ['개발일지'])).toEqual([])
  })

  it('인덱스가 없거나(정적 산출물 미배포) 태그가 비면 빈 배열', () => {
    expect(relatedPosts(undefined, '#31 알림', ['보안'])).toEqual([])
    expect(relatedPosts([], '#31 알림', ['보안'])).toEqual([])
    expect(relatedPosts(index, '#31 알림', [])).toEqual([])
  })

  it('max로 개수를 자른다', () => {
    expect(relatedPosts(index, '#31 알림', ['보안', '테스트'], 2)).toHaveLength(2)
  })
})

describe('coverLabel — 커버 없는 글의 자리표시 글자', () => {
  it('연재 글은 편 번호를 쓴다 (첫 글자를 쓰면 목록이 온통 같은 글자가 된다)', () => {
    expect(coverLabel('블로그 만들기 #33 — 다 만들고 나서야 안 도는 걸 알았다')).toBe('#33')
    expect(coverLabel('블로그 만들기 #1 — 빈 폴더에서')).toBe('#1')
  })

  it('실제 33편이 서로 다른 값을 낸다 — 이게 이 함수의 존재 이유다', () => {
    const titles = Array.from({ length: 33 }, (_, i) => `블로그 만들기 #${i + 1} — 어떤 제목`)
    const labels = new Set(titles.map(coverLabel))
    expect(labels.size).toBe(33)
    // 고치기 전 방식(첫 글자)은 33편이 전부 '블' 하나로 뭉쳤다
    expect(new Set(titles.map((t) => t[0])).size).toBe(1)
  })

  it('제목 뒤쪽 숫자를 편 번호로 잘못 집지 않는다', () => {
    // 샵 뒤 숫자만 본다 — 안 그러면 '403'이나 '18'이 편 번호가 된다
    expect(coverLabel('한글 태그 허브 18장이 라이브에서 403이었다')).toBe('한')
  })

  it('연재가 아닌 글은 앞머리 기호를 걷어낸 첫 글자', () => {
    expect(coverLabel('   AWS 비용 줄이기')).toBe('A')
    expect(coverLabel('— 어떤 글')).toBe('어')
  })

  it('제목이 없거나 비면 # 로 떨어진다 (빈 칸을 그리지 않는다)', () => {
    expect(coverLabel('')).toBe('#')
    expect(coverLabel(null)).toBe('#')
    expect(coverLabel(undefined)).toBe('#')
    expect(coverLabel('   ')).toBe('#')
  })
})
