/**
 * 폴리필이 '옛 사파리처럼' 굴 때 실제로 메워지는지 본다.
 *
 * 그냥 `expect(Object.hasOwn).toBeDefined()`로는 아무것도 못 지킨다 — 테스트가 도는
 * Node에는 원래부터 있어서 폴리필을 지워도 통과한다. 그래서 **일부러 지우고** 모듈을
 * 다시 평가한다. 그게 이 파일이 지키려는 상황(사파리 15.3)이다.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

const original = Object.hasOwn

/** 옛 사파리 흉내: Object.hasOwn을 지우고 폴리필 모듈을 처음부터 다시 평가한다. */
async function loadPolyfillOnOldSafari() {
  // @ts-expect-error 런타임에서 일부러 지운다
  delete Object.hasOwn
  expect(Object.hasOwn).toBeUndefined()
  vi.resetModules() // 모듈 캐시를 비워야 최상위 if 문이 다시 돈다
  await import('./polyfills')
}

afterEach(() => {
  Object.defineProperty(Object, 'hasOwn', {
    value: original,
    writable: true,
    enumerable: false,
    configurable: true,
  })
  vi.resetModules()
})

describe('Object.hasOwn 폴리필 (사파리 15.4 미만)', () => {
  it('없으면 채워 넣고, 자기 속성만 참으로 본다', async () => {
    await loadPolyfillOnOldSafari()
    expect(typeof Object.hasOwn).toBe('function')
    expect(Object.hasOwn({ a: 1 }, 'a')).toBe(true)
    expect(Object.hasOwn({ a: 1 }, 'b')).toBe(false)
    // 프로토타입에서 물려받은 것은 false — 이게 hasOwnProperty와 같은 지점이다
    expect(Object.hasOwn({}, 'toString')).toBe(false)
  })

  it('원시값도 감싸서 처리한다(명세와 같게)', async () => {
    await loadPolyfillOnOldSafari()
    // TS의 시그니처는 object만 받지만 명세는 원시값도 감싸서 처리한다.
    const str = 'ab' as unknown as object
    expect(Object.hasOwn(str, 0)).toBe(true)
    expect(Object.hasOwn(str, 5)).toBe(false)
  })

  it('null·undefined는 TypeError', async () => {
    await loadPolyfillOnOldSafari()
    // @ts-expect-error 일부러 잘못된 입력
    expect(() => Object.hasOwn(null, 'a')).toThrow(TypeError)
  })

  it('열거되지 않는다 — for…in에 끼면 남의 코드가 깨진다', async () => {
    await loadPolyfillOnOldSafari()
    expect(Object.keys(Object)).not.toContain('hasOwn')
  })

  it('이미 있으면 덮어쓰지 않는다', async () => {
    const marker = function hasOwn() {
      return true
    }
    Object.defineProperty(Object, 'hasOwn', { value: marker, configurable: true, writable: true })
    vi.resetModules()
    await import('./polyfills')
    expect(Object.hasOwn).toBe(marker)
  })
})
