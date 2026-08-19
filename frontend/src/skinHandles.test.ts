/**
 * 손잡이 계약이 **두 군데에서 같은 말을 하는지** 검사한다.
 *
 *   1. 마크업 — `data-skin="…"` (진짜로 화면에 있는 것)
 *   2. `skinHandles.ts` — 설정 화면의 안내가 읽는 목록
 *
 * 셋이 될 뻔했는데(index.css 주석에도 표가 있었다) 그건 지웠다 — Vitest는 CSS를
 * 빈 문자열로 주기 때문에 대조할 방법이 없었고, 대조 못 하는 사본은 갈라지기만 한다.
 * 지금 index.css에는 규칙과 '목록은 저기 있다'는 표시만 남아 있다.
 *
 * 둘이 갈라져도 **아무것도 안 깨진다.** 안내에만 있는 손잡이는 CSS를 써 놓고
 * "왜 안 먹지"에 갇히게 하고, 마크업에만 있는 손잡이는 아무도 안 쓴다. 둘 다
 * 조용한 고장이라 화면으로는 안 잡힌다 — 그래서 여기서 잡는다.
 *
 * 이 저장소가 반복해 밟은 모양이기도 하다: 만들어져 있는데 닿는 길이 없는 것.
 */
import { describe, it, expect } from 'vitest'
import { SKIN_HANDLE_NAMES } from './skinHandles'

// 소스를 **글자 그대로** 읽는다. node:fs가 아니라 Vite의 glob을 쓰는 이유는
// 이 프로젝트의 tsconfig가 앱 쪽에 node 타입을 안 넣기 때문이다 — 검사 하나를 위해
// 타입 패키지를 늘리는 것보다, 이미 있는 도구로 읽는 편이 싸다.
const TSX = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true })

/** 마크업에 실제로 박혀 있는 이름들. */
function fromMarkup(): Set<string> {
  const found = new Set<string>()
  for (const [path, code] of Object.entries(TSX)) {
    if (path.endsWith('.test.tsx')) continue
    const src = code as string
    for (const m of src.matchAll(/data-skin="([a-z-]+)"/g)) found.add(m[1])
    // HtmlSlot만 이름을 조립한다: data-skin={`slot-${slot}`}
    if (/data-skin=\{`slot-\$\{slot\}`\}/.test(src)) {
      for (const s of ['intro', 'aside', 'footer']) found.add(`slot-${s}`)
    }
  }
  return found
}

describe('data-skin 계약', () => {
  it('편집기 목록에 중복이 없다', () => {
    expect(new Set(SKIN_HANDLE_NAMES).size).toBe(SKIN_HANDLE_NAMES.length)
  })

  it('안내에 적힌 손잡이는 전부 마크업에 실제로 있다', () => {
    // 없으면: CSS를 써도 아무 일이 안 일어난다.
    const markup = fromMarkup()
    expect(SKIN_HANDLE_NAMES.filter((n) => !markup.has(n))).toEqual([])
  })

  it('마크업의 손잡이는 전부 안내에 적혀 있다', () => {
    // 없으면: 만들어 놨는데 아무도 모른다.
    const missing = [...fromMarkup()].filter((n) => !SKIN_HANDLE_NAMES.includes(n))
    expect(missing).toEqual([])
  })

  it('목록과 글 상세는 이름을 나눠 쓴다', () => {
    // post-title을 키우는 스킨이 글 본문 제목까지 키우면 쓴 사람이 예상 못 한
    // 자리가 바뀐다. 두 화면이 같은 이름을 쓰기 시작하면 여기서 걸린다.
    const list = SKIN_HANDLE_NAMES.filter((n) => n.startsWith('post-'))
    const detail = SKIN_HANDLE_NAMES.filter((n) => n.startsWith('article-'))
    expect(list.length).toBeGreaterThan(0)
    expect(detail.length).toBeGreaterThan(0)
    expect(list.some((n) => detail.includes(n))).toBe(false)
  })
})
