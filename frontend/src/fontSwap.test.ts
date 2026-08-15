// @vitest-environment jsdom
//
// 이 테스트가 감시하는 건 함수 하나가 아니라 **두 파일 사이의 짝**이다.
//
// index.html이 폰트 CSS를 `media="print"`로 실어 렌더 블로킹을 없앴다. 그 대가로
// **누군가 media를 all로 되돌려야 폰트가 붙는다.** 되돌리는 쪽이 사라지면 화면은
// system-ui로 그럭저럭 보이고, 콘솔에도 아무 말이 없고, 테스트도 초록이다 —
// 즉 **눈으로도 CI로도 안 잡히는 고장**이다. 이 저장소가 반복해서 밟은 모양
// ("만들어져 있는데 연결이 없었다")이라 파일 두 개를 실제로 읽어 잠근다.
import { describe, it, expect } from 'vitest'
import { swapFontStylesheets } from './fontSwap'
// 소스를 **글자 그대로** 읽는다(`?raw`). node:fs가 아닌 이유: 이 폴더는 tsconfig.app의
// 검사 대상이고 거기엔 node 타입이 없다 — fs를 쓰면 `tsc -b`(= 빌드)가 깨진다.
import indexHtml from '../index.html?raw'
import mainSource from './main.tsx?raw'

const FONT_LINK = /<link[^>]*pretendard[^>]*>/is

describe('폰트 논블로킹 로드', () => {
  it('index.html의 폰트 링크는 media="print"로 실려 렌더를 막지 않는다', () => {
    const link = indexHtml.match(FONT_LINK)?.[0]
    expect(link, '폰트 stylesheet 링크를 못 찾았다').toBeTruthy()
    expect(link).toMatch(/media="print"/)
    expect(link).toMatch(/data-font-swap/)
  })

  it('main.tsx가 스왑을 실제로 호출한다 (안 하면 폰트가 영영 안 붙는다)', () => {
    expect(mainSource).toMatch(/swapFontStylesheets\s*\(\s*\)/)
  })

  it('CSP가 막는 인라인 onload 처방을 쓰지 않는다', () => {
    // `onload="this.media='all'"`은 웹에 흔한 처방이지만 script-src 'self'에서
    // 차단된다. 차단돼도 화면은 멀쩡해 보여서 되돌아오기 쉬운 코드다.
    expect(indexHtml.match(FONT_LINK)?.[0] ?? '').not.toMatch(/onload=/i)
  })

  it('표시된 링크의 media를 all로 되돌린다', () => {
    document.head.innerHTML =
      '<link rel="stylesheet" media="print" data-font-swap href="https://cdn.example/f.css">' +
      '<link rel="stylesheet" media="print" href="https://cdn.example/other.css">'

    expect(swapFontStylesheets(document)).toBe(1)

    const [font, other] = Array.from(document.querySelectorAll('link'))
    expect(font.media).toBe('all')
    // 표시 안 한 건 안 건드린다 — 이 함수의 대상은 data-font-swap뿐이다.
    expect(other.media).toBe('print')
  })

  it('링크가 하나도 없어도 터지지 않는다', () => {
    document.head.innerHTML = ''
    expect(() => swapFontStylesheets(document)).not.toThrow()
  })
})
