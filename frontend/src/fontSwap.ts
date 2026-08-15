// 폰트 CSS를 '받되 막지 않게' 실은 뒤, 실제로 적용시키는 쪽.
//
// index.html은 Pretendard CSS를 `media="print"`로 싣는다 — 그래야 남의 CDN이 느리거나
// 죽어도 첫 페인트가 멈추지 않는다. 대신 그대로 두면 폰트가 **영영 안 붙으므로**
// 다 받은 뒤 media를 all로 되돌려야 한다. 그 되돌리기가 이 파일이다.
//
// 왜 `<link onload="this.media='all'">`이 아닌가: CSP가 `script-src 'self'`라
// 인라인 이벤트 핸들러가 차단된다(terraform/csp-function.js). 차단돼도 화면은
// system-ui로 그럭저럭 보여서 **고장난 걸 눈으로는 못 잡는다.** 그래서 스왑을
// 자기 출처 모듈로 옮겼다.
//
// 타이밍: main.tsx가 React 렌더 **전에** 부른다. 이 시점이면 파서는 <head>를 지났으니
// 링크는 이미 DOM에 있고, 파일이 아직 안 왔더라도 media만 미리 바꿔두면 도착하는 즉시
// 적용된다(도착을 기다릴 필요가 없다).
//
// JS가 아예 안 도는 경우엔 폰트가 안 붙고 system-ui로 남는다. 그건 감수한다 —
// 이 화면 자체가 JS로 그려지고, JS 실패 경로에는 index.html의 <noscript>가
// 정적 아카이브로 내보내기 때문이다.

/** index.html이 `data-font-swap`으로 표시한 스타일시트를 실제 적용 상태로 되돌린다. */
export function swapFontStylesheets(doc: Document = document): number {
  const links = doc.querySelectorAll<HTMLLinkElement>('link[data-font-swap]')
  links.forEach((link) => {
    link.media = 'all'
  })
  return links.length
}
