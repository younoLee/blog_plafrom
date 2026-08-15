// 라우트별 <head> — 제목·설명·canonical·OG를 화면마다 바꾼다.
//
// **무엇이 문제였나.** index.html의 메타는 사이트 공통 1종이고 SPA는 그걸 그대로 쓴다.
// 그래서 `/blog/posts/41`이든 `/blog/posts/48`이든 검색엔진이 보는 제목·설명이 같고,
// canonical은 **아예 없었다.** 같은 글이 정적 아카이브(`/devlog/2026-08-14.html`)에도
// 있으므로, 표준 주소를 안 알려주면 두 주소가 서로의 중복으로 경쟁한다.
//
// ⚠️ **이걸로 안 고쳐지는 것을 분명히 해둔다.** 카카오톡·트위터·페이스북의 링크
// 미리보기 봇은 **자바스크립트를 돌리지 않는다.** 즉 여기서 og:title을 아무리 바꿔도
// 주소줄을 복사해 SPA 주소를 공유하면 카드는 여전히 사이트 공통 1종이다.
// 그 경로의 해법은 따로 있다 — 글 상세의 '링크 복사'가 정적 아카이브 주소를 준다
// (postUtils.archiveUrlFor). 여기서 얻는 것은 **JS를 실행하는 크롤러**(구글이 그렇다)
// 에게 중복을 정리해주는 것, 그리고 그 크롤러가 보는 제목·설명이 글마다 달라지는 것이다.
// 이 구분을 안 적어두면 다음 사람이 "OG 고쳤는데 카톡 카드가 그대로다"에서 시간을 쓴다.
//
// canonical은 정적 아카이브가 있으면 **그쪽**을 가리킨다. 서버(EC2)가 평소 꺼져 있어
// SPA 주소는 눌러도 글이 안 뜰 확률이 높은 반면 정적 페이지는 항상 열리기 때문이다.

const SITE_NAME = 'DEV 블로그'

export interface HeadMeta {
  /** 글 제목. 비면 사이트 기본값으로 되돌린다. */
  title?: string | null
  description?: string | null
  /** 표준 주소. 비면 현재 주소를 쓴다. */
  canonical?: string | null
  type?: 'website' | 'article'
}

/** 이 모듈이 손대는 태그를 어떻게 찾는지 — 복구할 때도 같은 목록을 쓴다. */
const TAGS = [
  { sel: 'meta[name="description"]', attr: 'content', key: 'description' },
  { sel: 'meta[property="og:title"]', attr: 'content', key: 'title' },
  { sel: 'meta[property="og:description"]', attr: 'content', key: 'description' },
  { sel: 'meta[property="og:url"]', attr: 'content', key: 'url' },
  { sel: 'meta[property="og:type"]', attr: 'content', key: 'type' },
  { sel: 'meta[name="twitter:title"]', attr: 'content', key: 'title' },
  { sel: 'meta[name="twitter:description"]', attr: 'content', key: 'description' },
] as const

/** index.html이 갖고 있던 원래 값. **처음 손대기 전에 한 번만** 뜬다.
 *  여기서 뜨지 않고 매번 현재값을 저장하면, 글 A→B로 이동할 때 "원래값"이
 *  A의 값으로 덮여 사이트 기본값이 영원히 사라진다. */
let baseline: Map<string, string | null> | null = null

function captureBaseline(doc: Document) {
  if (baseline) return
  baseline = new Map()
  baseline.set('__title__', doc.title)
  for (const { sel, attr } of TAGS) {
    const el = doc.querySelector(sel)
    baseline.set(sel, el ? el.getAttribute(attr) : null)
  }
}

/** 없으면 만들어서라도 값을 넣는다. canonical은 index.html에 아예 없어서 필요하다. */
function setTag(doc: Document, sel: string, attr: string, value: string | null) {
  let el = doc.querySelector(sel)
  if (!el) {
    if (value == null) return
    el = createFrom(doc, sel)
    if (!el) return
    doc.head.appendChild(el)
  }
  if (value == null) el.remove()
  else el.setAttribute(attr, value)
}

/** 셀렉터에서 태그를 만든다 — `meta[name="x"]` / `meta[property="x"]` / `link[rel="x"]`만 다룬다. */
function createFrom(doc: Document, sel: string): Element | null {
  const m = sel.match(/^(meta|link)\[(name|property|rel)="([^"]+)"\]$/)
  if (!m) return null
  const el = doc.createElement(m[1])
  el.setAttribute(m[2], m[3])
  return el
}

/** 화면 하나 분의 head를 적용한다. 되돌리는 함수를 준다. */
export function applyHead(meta: HeadMeta, doc: Document = document): () => void {
  captureBaseline(doc)

  // 기본값은 현재 주소지만 **쿼리·해시는 뗀다.** href를 그대로 쓰면
  // `/reset?token=…`·`/verify?token=…`의 1회용 토큰이 canonical·og:url에 박혀
  // 크롤러에게 나가고 브라우저 확장이 읽을 수 있는 DOM에 남는다. canonical은
  // 원래도 정규화된 주소를 넣는 자리라 표준 관행과도 맞다.
  const loc = doc.defaultView?.location
  const url = meta.canonical || (loc ? `${loc.origin}${loc.pathname}` : null)
  const values: Record<string, string | null> = {
    // og:title은 사이트 이름을 덧붙이지 않는다 — 카드에 og:site_name이 따로 뜨므로
    // 붙이면 "제목 — DEV 블로그 · DEV 블로그"가 된다. 탭 제목(document.title)만 붙인다.
    title: meta.title || SITE_NAME,
    description: meta.description || baseline?.get('meta[name="description"]') || null,
    url,
    type: meta.type ?? 'website',
  }

  doc.title = meta.title ? `${meta.title} — ${SITE_NAME}` : SITE_NAME
  for (const { sel, attr, key } of TAGS) setTag(doc, sel, attr, values[key] ?? null)
  setTag(doc, 'link[rel="canonical"]', 'href', url)

  return () => {
    if (!baseline) return
    doc.title = baseline.get('__title__') ?? SITE_NAME
    for (const { sel, attr } of TAGS) setTag(doc, sel, attr, baseline.get(sel) ?? null)
    // canonical은 index.html에 없던 태그다 — 되돌린다 = 지운다.
    doc.querySelector('link[rel="canonical"]')?.remove()
  }
}

/** 테스트용 — 모듈 상태(원래값 스냅샷)를 비운다. */
export function resetHeadBaseline() {
  baseline = null
}
