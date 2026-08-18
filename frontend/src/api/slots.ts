/**
 * 블로그 '내 문장' — 제목 아래 머리말·사이드바 소개·푸터.
 *
 * 스킨(api/skin.ts)이 '어떻게 보이나'라면 이건 '무엇이 적히나'다. 서버가 한 응답에
 * 같이 실어 보내므로(GET /api/skin), 받아오는 일은 skin.ts가 한다 — 여기 있는 건
 * **받은 뒤의 처리**(세척·보관·구독)뿐이다.
 *
 * 왜 별도 저장소(구독형)인가: 문장이 나가는 자리가 화면 세 곳에 흩어져 있고
 * (Layout의 푸터, Sidebar, 각 목록 화면의 머리말) 그중 둘은 라우트 바깥이라
 * props로 내려줄 길이 없다. `/@handle`로 들어가면 그 사람 문장으로 **한꺼번에**
 * 바뀌어야 하는데, 화면마다 따로 받아오면 셋이 서로 다른 사람 것을 보여주는
 * 중간 상태가 생긴다. 스킨이 <style> 한 장으로 한꺼번에 바뀌는 것과 같은 이유다.
 */
import { useSyncExternalStore } from 'react'

export const SLOT_KEYS = ['intro', 'aside', 'footer'] as const
export type SlotKey = (typeof SLOT_KEYS)[number]
export type Slots = Record<SlotKey, string>

export const EMPTY_SLOTS: Slots = { intro: '', aside: '', footer: '' }

/** 서버가 뭘 주든 세 칸짜리 모양으로 맞춘다(키가 빠져도 화면이 안 깨지게). */
export function normalizeSlots(raw: unknown): Slots {
  const src = (raw ?? {}) as Record<string, unknown>
  return {
    intro: typeof src.intro === 'string' ? src.intro : '',
    aside: typeof src.aside === 'string' ? src.aside : '',
    footer: typeof src.footer === 'string' ? src.footer : '',
  }
}

export function hasAnySlot(s: Slots): boolean {
  return SLOT_KEYS.some((k) => s[k].trim() !== '')
}

/* ------------------------------------------------------------------ 세척 */

// 서버가 이미 허용 목록으로 다시 썼다(backend/app/core/html_slots.py). 여기서 또 하는
// 이유는 **여기가 마지막 문이기 때문**이다:
//   · localStorage 캐시를 통해서도 들어온다 — 서버를 안 거치는 경로다.
//   · 서버 검사는 나중에 완화될 수 있고, 그때 이 파일이 유일한 방어선이 된다.
//   · 이건 저장 때 한 번이 아니라 **그릴 때마다** 도는 검사라, 검사가 생기기 전에
//     DB에 들어간 옛 값에도 걸린다.
//
// 서버 것과 달리 여긴 '다시 쓰기'가 아니라 '위험한 것 제거'다. 파서가 만들어 준 DOM
// 위에서 지우므로 문자열 변형이 아니고, 지우는 대상이 눈에 보인다.
const KILL =
  'script,style,iframe,object,embed,link,meta,form,input,button,svg,math,noscript,template'

// 서버의 허용 목록과 같은 집합이다(backend/app/core/html_slots.py의 _ALLOWED).
// **왜 여기도 허용 목록인가** — 이름으로 지우는 방식만으로는 부족하다는 걸 실측했다:
// `<scr<script>ipt>`를 파서에 넣으면 `scr<script`라는 **이름의 태그**가 만들어진다
// (HTML5 태그 이름에는 `<`가 들어갈 수 있다). 그건 `querySelectorAll('script')`에
// 안 걸리고, 다시 직렬화하면 `<scr<script>`라는 글자가 그대로 남는다. 실행되지는
// 않지만, 출력에 그런 게 남는다는 건 이 함수가 "무엇을 내보내는지 모른다"는 뜻이다.
// 모르는 것은 껍데기만 벗기고 안의 글자는 남긴다 — 서버와 같은 규칙이다.
const ALLOWED = new Set([
  'p', 'br', 'hr', 'strong', 'b', 'em', 'i', 'u', 's', 'small', 'span', 'div',
  'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'blockquote', 'code', 'pre',
  'figure', 'figcaption', 'a', 'img',
])

// 허용: http(s):, mailto:, `/경로`(단 `//다른출처`는 아님), `#앵커`, 스킴 없는 상대 경로.
const OK_SCHEME = /^(?:https?:|mailto:|\/(?!\/)|#|[^:/?#]*$)/i

/** 주소에서 공백·제어문자를 뺀다 — `jav\tascript:`를 브라우저는 실행한다. */
function bareUrl(v: string): string {
  let out = ''
  for (const ch of v) if (ch.codePointAt(0)! > 0x20) out += ch
  return out
}

/**
 * 그리기 직전 한 번 더 씻는다. **DOMParser로 파싱한다** — 정규식으로 태그를 지우면
 * `<scr<script>ipt>` 같은 변형이 남는다. 브라우저가 실제로 만들 DOM을 만들어 두고
 * 그 위에서 지우는 쪽이 브라우저와 같은 눈으로 보는 방법이다.
 *
 * 별도 문서에서 파싱하므로(DOMParser) 여기서는 이미지·스크립트가 로드되지 않는다.
 * 살아 있는 DOM의 innerHTML에 먼저 넣고 지우면 그 사이에 요청이 나간다.
 */
export function scrubHtml(html: string): string {
  if (!html) return ''
  try {
    const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html')
    // **`doc.body` 아래만 훑는다.** `doc.querySelectorAll('*')`은 html·head·body
    // 자신을 포함하고, 그 셋은 허용 목록에 없어서 ②가 문서를 통째로 벗겨 버린다
    // (결과가 항상 빈 문자열이 된다 — 실제로 그렇게 만들었다가 테스트가 잡았다).
    const root = doc.body
    // ① 내용까지 통째로 버리는 것 — 태그만 지우면 `alert(1)`이 본문 글자로 남는다.
    root.querySelectorAll(KILL).forEach((el) => el.remove())
    // ② 허용 목록 밖은 껍데기만 벗긴다(안의 글자는 살린다). 벗긴 자리의 자식들은
    //    이 반복이 계속 훑으므로 중첩돼 있어도 다 벗겨진다.
    root.querySelectorAll('*').forEach((el) => {
      if (!ALLOWED.has(el.tagName.toLowerCase())) el.replaceWith(...el.childNodes)
    })
    root.querySelectorAll('*').forEach((el) => {
      for (const attr of [...el.attributes]) {
        const name = attr.name.toLowerCase()
        if (name.startsWith('on')) {
          el.removeAttribute(attr.name) // 인라인 이벤트 핸들러
        } else if (
          (name === 'href' || name === 'src' || name === 'srcset') &&
          !OK_SCHEME.test(bareUrl(attr.value))
        ) {
          el.removeAttribute(attr.name)
        }
      }
    })
    return root.innerHTML
  } catch {
    // DOMParser가 없거나 던지면 **아무것도 안 그린다.** 못 씻은 걸 그리느니 빈 칸이 낫다.
    return ''
  }
}

/** 세 칸을 한꺼번에 씻는다. */
export function scrubSlots(s: Slots): Slots {
  return { intro: scrubHtml(s.intro), aside: scrubHtml(s.aside), footer: scrubHtml(s.footer) }
}

/* ------------------------------------------------------------- 지금 적용값 */

let current: Slots = EMPTY_SLOTS
const listeners = new Set<() => void>()

/** 지금 화면에 걸린 문장을 바꾼다. 세 자리가 같은 순간에 함께 바뀐다. */
export function setSlots(next: Slots): void {
  // 내용이 같으면 알리지 않는다 — useSyncExternalStore가 매번 새 객체를 받으면
  // 구독한 화면이 전부 다시 그려진다(스킨을 갱신할 때마다 푸터·사이드바가 깜빡인다).
  if (SLOT_KEYS.every((k) => current[k] === next[k])) return
  current = next
  listeners.forEach((fn) => fn())
}

export function getSlots(): Slots {
  return current
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

/** 화면에서 쓰는 훅. `useSlots().footer` 처럼 읽는다. */
export function useSlots(): Slots {
  return useSyncExternalStore(subscribe, getSlots, () => EMPTY_SLOTS)
}
