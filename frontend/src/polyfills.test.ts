/**
 * 폴리필이 '옛 사파리처럼' 굴 때 실제로 메워지는지 본다.
 *
 * 그냥 `expect(Object.hasOwn).toBeDefined()`로는 아무것도 못 지킨다 — 테스트가 도는
 * Node에는 원래부터 있어서 폴리필을 지워도 통과한다. 그래서 `hasOwn`이 **없는**
 * 가짜 Object에 설치해 본다. 그게 이 파일이 지키려는 상황(사파리 15.3)이다.
 *
 * 진짜 전역을 지우지 않는 이유 — vitest 5의 모듈 로더가 import 도중에
 * `Object.hasOwn`을 써서, 지운 채로 import하면 테스트 도구가 먼저 죽는다(2026-10-17).
 */
import { describe, expect, it } from 'vitest'
import { installHasOwn } from './polyfills'

type WithHasOwn = { hasOwn: (o: object, k: PropertyKey) => boolean }

/** 옛 사파리 흉내: hasOwn이 없는 Object에 폴리필을 설치한다. */
function oldSafariObject(): WithHasOwn {
  const fake: { hasOwn?: unknown } = {}
  installHasOwn(fake)
  return fake as WithHasOwn
}

describe('Object.hasOwn 폴리필 (사파리 15.4 미만)', () => {
  it('없으면 채워 넣고, 자기 속성만 참으로 본다', () => {
    const O = oldSafariObject()
    expect(typeof O.hasOwn).toBe('function')
    expect(O.hasOwn({ a: 1 }, 'a')).toBe(true)
    expect(O.hasOwn({ a: 1 }, 'b')).toBe(false)
    // 프로토타입에서 물려받은 것은 false — 이게 hasOwnProperty와 같은 지점이다
    expect(O.hasOwn({}, 'toString')).toBe(false)
  })

  it('원시값도 감싸서 처리한다(명세와 같게)', () => {
    const O = oldSafariObject()
    // TS의 시그니처는 object만 받지만 명세는 원시값도 감싸서 처리한다.
    const str = 'ab' as unknown as object
    expect(O.hasOwn(str, 0)).toBe(true)
    expect(O.hasOwn(str, 5)).toBe(false)
  })

  it('null·undefined는 TypeError', () => {
    const O = oldSafariObject()
    expect(() => O.hasOwn(null as unknown as object, 'a')).toThrow(TypeError)
  })

  it('열거되지 않는다 — for…in에 끼면 남의 코드가 깨진다', () => {
    const O = oldSafariObject()
    expect(Object.keys(O)).not.toContain('hasOwn')
  })

  it('이미 있으면 덮어쓰지 않는다', () => {
    const marker = function hasOwn() {
      return true
    }
    const O = { hasOwn: marker }
    installHasOwn(O)
    expect(O.hasOwn).toBe(marker)
  })

  it('모듈을 import하면 진짜 Object에도 걸려 있다', () => {
    // Node엔 원래 있으니 '덮어쓰지 않았다'만 확인된다. 그래도 import가 부작용 없이
    // 끝나는지(main.tsx의 첫 줄이 터지지 않는지)는 이걸로 본다.
    expect(typeof Object.hasOwn).toBe('function')
  })
})
