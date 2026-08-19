/**
 * 눌러서 꾸미기의 변환기를 잠근다.
 *
 * 여기서 진짜로 지키는 것은 두 가지다:
 *
 *  1. **남의 CSS를 먹지 않는다.** 옵션은 저장된 CSS 안에 얹혀 사는 구조라, 가르는
 *     규칙이 틀리면 사람이 직접 쓴 CSS가 조용히 사라진다. 표식이 없거나 반쯤 깨진
 *     경우가 그 위험이 실제로 생기는 자리다.
 *  2. **왕복해도 같다.** 저장 → 다시 열기 → 저장을 반복하면 블록이 쌓이거나 값이
 *     흘러내리기 쉽다. 그건 사람 눈에 안 보이는 채로 50KB 상한을 향해 자란다.
 */
import { describe, it, expect } from 'vitest'
import {
  DEFAULT_OPTIONS,
  isDefaultOptions,
  joinSkin,
  normalizeOptions,
  optionsToCss,
  splitSkin,
  type SkinOptions,
} from './skinOptions'

const at = (over: Partial<SkinOptions>): SkinOptions => ({ ...DEFAULT_OPTIONS, ...over })

describe('optionsToCss', () => {
  it('기본값이면 한 글자도 안 쓴다 — 그래야 서버가 NULL로 되돌린다', () => {
    expect(optionsToCss(DEFAULT_OPTIONS)).toBe('')
    expect(isDefaultOptions(DEFAULT_OPTIONS)).toBe(true)
  })

  it('강조색을 바꾸면 그 위 글자색도 같이 나온다', () => {
    // 짝이라 따로 두면 어긋난다 — 화면마다 text-white가 박혀 있던 탓에 스킨이 색을
    // 밝게 옮기면 흰 바탕에 흰 글자가 됐다(다크 기본값 2.0:1, 민트 1.6:1).
    const dark = optionsToCss(at({ accent: '#215ba6' })) // 어두운 파랑 → 흰 글자
    expect(dark).toContain('--color-on-accent: #ffffff')
    const light = optionsToCss(at({ accent: '#f1f3f5' })) // 아주 밝은 회색 → 검은 글자
    expect(light).toContain('--color-on-accent: #111111')
    // 다크모드 강조색은 밝은 쪽으로 옮겨지므로 글자색도 따라 뒤집혀야 한다
    const mint = optionsToCss(at({ accent: '#20c997' }))
    const darkBlock = mint.slice(mint.indexOf(':root.dark'))
    expect(darkBlock).toContain('--color-on-accent: #111111')
  })

  it('밝기는 상대휘도로 잰다 — 채널 평균이 아니라', () => {
    // 초록과 파랑은 채널 합이 비슷한데 눈에 들어오는 밝기는 두 배 넘게 차이 난다.
    // 평균으로 재면 초록 위에 흰 글자를 올려 대비가 무너진다.
    expect(optionsToCss(at({ accent: '#03c75a' }))).toContain('--color-on-accent: #111111')
    expect(optionsToCss(at({ accent: '#1c7ed6' }))).toContain('--color-on-accent: #ffffff')
  })

  it('카드 2열은 divide-y가 긋는 bottom 선을 지운다', () => {
    // `border-top: 0`만 지우면 격자 칸마다 아래에 회색 줄이 한 줄 더 남는다.
    // Tailwind divide-y는 --tw-divide-y-reverse가 0이라 **bottom**에 1px를 준다.
    const css = optionsToCss(at({ list: 'grid' }))
    expect(css).toContain('[data-skin="post-grid"] > * { border-block: 0 }')
    expect(css).not.toContain('border-top: 0')
  })

  it('강조색 하나에서 파생 색 넷이 같이 나온다', () => {
    const css = optionsToCss(at({ accent: '#20c997' }))
    expect(css).toContain('--color-accent: #20c997')
    // 강조색만 바꾸고 나머지를 두면 장식에 옛 색이 남아 반쯤 먹은 것처럼 보인다
    expect(css).toContain('--color-accent-hi:')
    expect(css).toContain('--color-accent-2:')
    expect(css).toContain('--color-accent-3:')
  })

  it('hover는 어두워지고 장식색은 밝아진다', () => {
    const css = optionsToCss(at({ accent: '#808080' }))
    const hi = /--color-accent-hi: (#[0-9a-f]{6})/.exec(css)![1]
    const two = /--color-accent-2: (#[0-9a-f]{6})/.exec(css)![1]
    expect(parseInt(hi.slice(1, 3), 16)).toBeLessThan(0x80)
    expect(parseInt(two.slice(1, 3), 16)).toBeGreaterThan(0x80)
  })

  it('어두운 모드 강조색은 :root.dark로 쓴다 — :root보다 세야 하므로', () => {
    const css = optionsToCss(at({ accent: '#20c997' }))
    expect(css).toContain(':root.dark {')
    // `:root:where(.dark)`는 우선순위 0이라 위의 `:root` 블록에 진다. 쓰면 안 된다.
    expect(css).not.toContain(':where(.dark)')
  })

  it('바탕색은 밝은 모드에만 쓴다(어두운 모드 바탕을 건드리지 않는다)', () => {
    const css = optionsToCss(at({ canvas: '#ffffff' }))
    expect(css).toContain('--color-canvas: #ffffff')
    expect(css).not.toContain(':root.dark')
  })

  it('hex가 아닌 색은 무시한다 — CSS에 그대로 흘려보내지 않는다', () => {
    expect(optionsToCss(at({ accent: 'red; } body { display:none' }))).toBe('')
    expect(optionsToCss(at({ canvas: 'url(x)' }))).toBe('')
  })

  it('숨기기 옵션은 약속된 손잡이만 지목한다', () => {
    const css = optionsToCss(
      at({ thumb: false, excerpt: false, tags: false, meta: false, sidebar: false }),
    )
    for (const k of ['post-thumb', 'post-excerpt', 'post-tags', 'post-meta', 'sidebar']) {
      expect(css).toContain(`[data-skin="${k}"] { display: none }`)
    }
    // 사이드바만 지우면 본문이 원래 폭에 남아 오른쪽이 빈다
    expect(css).toContain('[data-skin="layout"] { grid-template-columns: 1fr }')
  })

  it("머리말 '내 문장만'은 hero를 통째로 숨기지 않는다", () => {
    const css = optionsToCss(at({ hero: 'mine' }))
    expect(css).toContain('[data-skin="hero"] > h1')
    expect(css).not.toContain('[data-skin="hero"] { display: none }')
  })

  it('카드 2열은 격자 칸을 post-grid에 준다', () => {
    const css = optionsToCss(at({ list: 'grid' }))
    expect(css).toContain('grid-template-columns: repeat(2, 1fr)')
  })
})

describe('splitSkin', () => {
  it('표식이 없으면 전부 직접 쓴 것이다 — 지금 저장돼 있는 스킨이 이 경우다', () => {
    const hand = ':root { --color-accent: #00c9b7 }'
    const r = splitSkin(hand)
    expect(r.custom).toBe(hand)
    expect(r.generated).toBe('')
    expect(r.options).toEqual(DEFAULT_OPTIONS)
  })

  it('표식은 있는데 끝이 없으면 아무것도 안 지운다', () => {
    const broken = '/*@skin-options {"accent":"#20c997"}*/\n:root { --color-accent: #20c997 }'
    expect(splitSkin(broken).custom).toBe(broken)
  })

  it('표식 JSON이 깨졌어도 블록은 걷어낸다 — 안 그러면 저장할 때마다 쌓인다', () => {
    const css = '/*@skin-options {깨짐}*/\n:root{}\n/*@skin-end*/\nbody { margin: 0 }'
    const r = splitSkin(css)
    expect(r.options).toEqual(DEFAULT_OPTIONS)
    expect(r.custom).toBe('body { margin: 0 }')
  })

  it('표식 앞에 사람이 써 둔 것도 직접 쓴 것으로 살린다', () => {
    const css = joinSkin(at({ accent: '#20c997' }), 'body { margin: 0 }')
    const r = splitSkin(`/* 내가 위에 쓴 줄 */\n${css}`)
    expect(r.custom).toContain('내가 위에 쓴 줄')
    expect(r.custom).toContain('body { margin: 0 }')
    expect(r.options.accent).toBe('#20c997')
  })
})

describe('joinSkin', () => {
  it('직접 쓴 CSS가 뒤에 온다 — 순서가 곧 권한이다', () => {
    const css = joinSkin(at({ accent: '#20c997' }), '.mine { color: red }')
    expect(css.indexOf('--color-accent: #20c997')).toBeLessThan(css.indexOf('.mine'))
  })

  it('아무것도 안 눌렀으면 표식조차 안 남긴다', () => {
    expect(joinSkin(DEFAULT_OPTIONS, '')).toBe('')
    expect(joinSkin(DEFAULT_OPTIONS, 'body { margin: 0 }')).toBe('body { margin: 0 }')
    // 공백뿐이면 '안 쓴 것'이다 — 그래야 서버가 NULL로 되돌린다
    expect(joinSkin(DEFAULT_OPTIONS, '  \n ')).toBe('')
  })

  it('직접 쓴 CSS의 개행을 안 자른다 — 자르면 타이핑이 막힌다', () => {
    // 편집기의 textarea는 controlled이고 값이 매 렌더 다시 계산되므로, 여기서 trim하면
    // **키 하나 칠 때마다** 개행이 잘려 문서 끝에서 Enter가 아예 안 먹었다.
    expect(joinSkin(DEFAULT_OPTIONS, ':root {\n')).toBe(':root {\n')
    expect(joinSkin(at({ accent: '#20c997' }), 'a{}\n')).toMatch(/a\{\}\n$/)
    // 들여쓰기(앞 공백)도 같은 이유로 살아야 한다
    expect(joinSkin(DEFAULT_OPTIONS, '  color: red')).toBe('  color: red')
  })

  it('왕복해도 자라지 않는다', () => {
    const o = at({ accent: '#20c997', list: 'grid', sidebar: false, hero: 'mine', corner: 'square' })
    const once = joinSkin(o, 'body { margin: 0 }')
    const back = splitSkin(once)
    expect(back.options).toEqual(o)
    expect(joinSkin(back.options, back.custom)).toBe(once)
  })

  it('서버가 막는 글자를 만들지 않는다 (<, @import)', () => {
    const css = joinSkin(at({ accent: '#20c997', list: 'grid', hero: 'hide', canvas: '#ffffff' }), '')
    expect(css).not.toContain('<')
    expect(css.toLowerCase()).not.toContain('@import')
  })
})

describe('normalizeOptions', () => {
  it('서버가 뭘 주든 온전한 한 벌이 된다', () => {
    expect(normalizeOptions(null)).toEqual(DEFAULT_OPTIONS)
    expect(normalizeOptions({ corner: '이상한값', thumb: 'yes' })).toEqual(DEFAULT_OPTIONS)
    expect(normalizeOptions({ accent: '#ABCDEF' }).accent).toBe('#abcdef')
  })
})
