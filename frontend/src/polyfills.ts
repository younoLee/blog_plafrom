/**
 * 옛 사파리에서 죽는 API 하나를 메운다.
 *
 * 왜 생겼나 (2026-08-18) — 사용자가 맥북에서 "글을 눌렀는데 화면이 안 뜬다"고 했다.
 * 서버는 200이었고 목록도 멀쩡했다. 번들을 실제로 훑어 원인을 좁혔다:
 *
 *   structuredClone  →  `typeof structuredClone === 'function' ? … : 폴백`  (방어돼 있음)
 *   Object.hasOwn    →  그냥 호출. react-markdown이 쓰는 hast 쪽 코드 안이다  ← 이것
 *
 * `Object.hasOwn`은 사파리 15.4부터다. 그 아래에서는 마크다운을 그리는 순간
 * `TypeError`가 나고 화면이 빈다. **마크다운을 그리는 화면은 글 상세뿐이라**
 * 목록은 멀쩡한데 글만 안 뜨는, 정확히 그 증상이 된다.
 *
 * 왜 빌드 타깃을 낮추는 걸로는 안 되나 — esbuild가 낮추는 건 **문법**이지 API가
 * 아니다. `Object.hasOwn`은 문법이 아니라 함수라 타깃을 아무리 내려도 안 생긴다.
 * 그래서 여기서 직접 메운다.
 *
 * 왜 라이브러리를 안 고치나 — 우리 코드가 아니고, 올려도 다음 버전에서 또 다른
 * 최신 API가 들어온다. 입구에서 메우면 그 종류를 안 쫓아다녀도 된다.
 *
 * ⚠️ 이 파일은 **main.tsx의 첫 import**여야 한다. 모듈은 import 순서대로 실행되므로
 * 아래로 내려가면 react-markdown이 먼저 평가된다.
 */

// `Object.hasOwn(o, k)` = `Object.prototype.hasOwnProperty.call(o, k)`.
// 프로토타입 체인을 안 보는 게 요점이고, 옛 방식과 결과가 같다.
if (typeof Object.hasOwn !== 'function') {
  Object.defineProperty(Object, 'hasOwn', {
    value: function hasOwn(target: object, key: PropertyKey): boolean {
      // 명세대로 원시값도 객체로 감싸 처리한다(`Object.hasOwn('ab', 0)` → true).
      if (target === null || target === undefined) {
        throw new TypeError('Cannot convert undefined or null to object')
      }
      return Object.prototype.hasOwnProperty.call(Object(target), key)
    },
    // 원본 Object.hasOwn과 같은 속성 모양(열거되지 않고, 쓰기·설정 가능)
    writable: true,
    enumerable: false,
    configurable: true,
  })
}

export {}
