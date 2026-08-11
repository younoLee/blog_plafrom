// @vitest-environment jsdom
//
// translateGuard는 **진짜 DOM이 던지는 예외**를 막는 물건이다. 그래서 가짜 Node로
// 검사하면 가드가 아니라 내 가짜를 검사하게 된다 — 그러면 "가드를 지워도 초록"인
// 테스트가 된다. 이 파일만 jsdom에서 돌린다(다른 테스트는 node 환경 그대로).
//
// 잠그는 것 셋:
//   ① 가드 **없이는 실제로 터진다**(= 이 가드가 진짜 무언가를 막고 있다는 증거)
//   ② 정상 경로는 동작이 그대로다(감싸놓고 조용히 망가뜨리지 않았는가)
//   ③ referenceNode가 null이면 **끝에 붙인다** — 여기가 함정이다. `if (referenceNode && …)`를
//      "간결하게" `referenceNode.parentNode !== this`로 고치면 null에서 TypeError가 나고,
//      React는 append를 이 형태로 하기 때문에 **화면 전체가 안 그려진다.**
//
// Node.prototype을 전역으로 덮어쓰는 물건이라 각 테스트가 끝나면 반드시 되돌린다.
// 안 되돌리면 이 파일의 패치가 다른 테스트 파일로 샌다(그게 이 가드의 성질이다).
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { installTranslateGuard } from './translateGuard'

let originalRemoveChild: typeof Node.prototype.removeChild
let originalInsertBefore: typeof Node.prototype.insertBefore

beforeEach(() => {
  originalRemoveChild = Node.prototype.removeChild
  originalInsertBefore = Node.prototype.insertBefore
})

afterEach(() => {
  Node.prototype.removeChild = originalRemoveChild
  Node.prototype.insertBefore = originalInsertBefore
})

/** 자동번역이 만들어내는 상황: 지우려는 노드가 다른 부모 밑에 있다. */
function mismatched() {
  const realParent = document.createElement('div')
  const otherParent = document.createElement('div')
  const child = document.createElement('span')
  realParent.appendChild(child)
  return { realParent, otherParent, child }
}

describe('가드가 없을 때 (이 가드가 무엇을 막는지)', () => {
  it('부모가 아닌 노드를 removeChild 하면 진짜로 예외가 난다', () => {
    const { otherParent, child } = mismatched()
    expect(() => otherParent.removeChild(child)).toThrow()
  })

  it('기준 노드가 남의 자식이면 insertBefore도 진짜로 예외가 난다', () => {
    const { otherParent, child } = mismatched()
    expect(() => otherParent.insertBefore(document.createElement('b'), child)).toThrow()
  })
})

describe('가드가 있을 때', () => {
  beforeEach(() => installTranslateGuard())

  it('부모가 아닌 노드를 지우려 해도 앱이 안 죽는다', () => {
    const { realParent, otherParent, child } = mismatched()
    expect(() => otherParent.removeChild(child)).not.toThrow()
    // 조용히 넘어가는 것이지 **엉뚱한 곳을 건드리는 게 아니다** — 원래 부모에 그대로 있어야 한다
    expect(child.parentNode).toBe(realParent)
  })

  it('지우려던 노드를 그대로 돌려준다(removeChild의 반환 계약)', () => {
    const { otherParent, child } = mismatched()
    expect(otherParent.removeChild(child)).toBe(child)
  })

  it('기준 노드가 남의 자식이면 삽입을 건너뛴다 — 터지지도, 엉뚱한 데 붙지도 않는다', () => {
    const { otherParent, child } = mismatched()
    const fresh = document.createElement('b')
    expect(() => otherParent.insertBefore(fresh, child)).not.toThrow()
    expect(fresh.parentNode).toBeNull()
    expect(otherParent.childNodes.length).toBe(0)
  })

  it('정상 removeChild는 실제로 지운다(감싸놓고 무력화하지 않았는가)', () => {
    const parent = document.createElement('div')
    const child = document.createElement('span')
    parent.appendChild(child)

    expect(parent.removeChild(child)).toBe(child)
    expect(parent.childNodes.length).toBe(0)
    expect(child.parentNode).toBeNull()
  })

  it('정상 insertBefore는 실제로 그 자리에 넣는다', () => {
    const parent = document.createElement('div')
    const anchor = document.createElement('i')
    parent.appendChild(anchor)
    const fresh = document.createElement('b')

    parent.insertBefore(fresh, anchor)
    expect(Array.from(parent.childNodes)).toEqual([fresh, anchor])
  })

  it('referenceNode가 null이면 끝에 붙인다 — React의 append 경로다', () => {
    // 이 한 줄이 이 파일에서 제일 중요하다. 가드의 null 검사를 없애면
    // 여기서 TypeError가 나고 **화면이 통째로 안 그려진다.**
    const parent = document.createElement('div')
    const first = document.createElement('i')
    parent.appendChild(first)
    const fresh = document.createElement('b')

    expect(() => parent.insertBefore(fresh, null)).not.toThrow()
    expect(Array.from(parent.childNodes)).toEqual([first, fresh])
  })

  it('빈 부모에 null 기준으로 넣는 것도 된다(첫 렌더 경로)', () => {
    const parent = document.createElement('div')
    const fresh = document.createElement('b')
    parent.insertBefore(fresh, null)
    expect(fresh.parentNode).toBe(parent)
  })
})
