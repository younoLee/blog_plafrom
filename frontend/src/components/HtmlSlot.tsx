import { useSlots, type SlotKey } from '../api/slots'

/**
 * '내 문장' 한 칸을 그린다. 비어 있으면 **아무것도 렌더하지 않는다**(빈 div도 아니다) —
 * 대부분의 블로그는 이걸 안 쓸 테고, 안 쓰는 사람 화면에 여백만 생기면 안 된다.
 *
 * `dangerouslySetInnerHTML`을 쓰는 건 이 파일이 유일하다. 그래서 씻는 곳도 한 곳이면
 * 된다 — 값은 이미 세 번 걸러져서 온다:
 *   ① 서버가 저장할 때 허용 목록으로 다시 씀 (backend/app/core/html_slots.py)
 *   ② 프론트가 받거나 캐시에서 읽을 때 한 번 더 세척 (api/slots.ts의 scrubHtml)
 *   ③ CSP `script-src 'self'` — 인라인 핸들러가 실행되지 않는다
 * 여기서 또 씻지 않는 이유는 이게 **렌더 경로**라서다. 매 렌더마다 DOMParser를 돌리면
 * 목록 화면에서 눈에 띄게 느려진다. 세척은 값이 바뀔 때 한 번(api/slots.ts) 한다.
 *
 * `data-skin` 손잡이를 단다 — 스킨 CSS가 이 칸을 통째로 숨기거나 옮길 수 있게.
 * 문장 안에 쓴 `class`도 스킨에서 그대로 잡힌다. 그게 두 기능을 잇는 지점이다.
 */
export function HtmlSlot({ slot, className }: { slot: SlotKey; className?: string }) {
  const html = useSlots()[slot]
  if (!html) return null
  return (
    <div
      data-skin={`slot-${slot}`}
      className={`blog-slot ${className ?? ''}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export default HtmlSlot
