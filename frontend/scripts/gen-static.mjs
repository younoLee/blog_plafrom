// 빌드 후 정적 산출물 생성: 개발일지 아카이브 · RSS · sitemap · robots.txt
//
// **왜 필요한가 — 24편을 써놓고 아무도 찾아올 수 없는 구조였다.**
// 세 가지가 겹쳐 있었다:
//   1. Vite SPA라 초기 HTML에 글이 없다. 크롤러가 받는 건 빈 <div id="root">
//   2. 글은 /api/*(EC2)에서 오는데 그 서버는 평소 꺼져 있다 → 크롤러는 504를 본다
//   3. sitemap도 RSS도 없어 크롤러에게 알릴 경로 자체가 없다
// 즉 검색 유입이 적은 게 아니라 **구조적으로 0**이었다.
//
// 그래서 sitemap만 넣는 걸로는 안 된다 — 가리킬 페이지에 내용이 없으면 의미가 없다.
// 마크다운 원본(content/devlog/)에서 **서버가 필요 없는 정적 페이지**를 만들어 함께 낸다.
// 이러면 EC2가 꺼져 있어도 살아 있는 유일한 경로가 되고, README가 이미 말하던
// "글 내용은 서버 없이도 읽을 수 있습니다"가 웹에서도 사실이 된다.
//
// **경로에 반드시 확장자가 있어야 한다.** CloudFront Function(spa-routing-function.js)이
// "마지막 경로 조각에 점이 없으면 index.html"로 되돌린다. 그래서 /devlog/ 같은
// 디렉터리형 인덱스는 SPA에 삼켜진다 → 아카이브 인덱스를 /devlog.html로 둔다.
//
// vite build 뒤에 dist/에 직접 쓴다(public/에 두면 생성물이 저장소에 쌓인다).
import { readdirSync, readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Marked } from 'marked'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..', '..', 'content', 'devlog')
const OUT = join(HERE, '..', 'dist')
const SITE = process.env.VITE_SITE_URL ?? 'https://d2j66m9udyg9yq.cloudfront.net'
const TITLE = 'DEV 블로그'
const DESC = '개발과 인프라를 기록하는 블로그. 글 작성·구독·AI 초안까지 직접 만든 풀스택 사이트.'

const esc = (s) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

// **원시 HTML을 글자로 취급한다.** marked에는 새니타이저가 없어 마크다운 안의 raw
// HTML을 그대로 통과시킨다. 이 개발일지는 주제가 보안이라 본문에 <script> 같은 걸
// 산문으로 쓴다 — 실제로 2026-07-30.md의 "글 본문에 <script>를 넣어도 렌더러가
// 글자로만 취급한다"는 문장이 닫히지 않은 <script>가 되어 **그 편의 마지막 15%가
// 통째로 안 보이고 있었다**(2026-08-07 검사에서 발견). 게다가 같은 HTML이 rss.xml의
// content:encoded로 나가는데, 피드 리더에는 우리 CSP가 안 걸린다.
// 저자를 믿는 대신 파싱 단계에서 중화한다.
/**
 * 소제목 id — 절 단위 딥링크용. 편마다 초기화한다(아래 readPost).
 *
 * 왜 필요한가: 이 아카이브 페이지들이 '링크 복사'가 권하는 주소이고 검색 유입도
 * 이쪽인데, h2/h3에 id가 **하나도 없어서** 긴 글의 특정 절을 가리킬 방법이 없었다.
 * (SPA 쪽은 rehypeSlug가 id를 붙인다 — 정적만 빠져 있었다.)
 *
 * 같은 제목이 두 번 나오면 뒤엣것에 -1, -2를 붙인다. 안 하면 id가 겹쳐서
 * 브라우저가 항상 첫 번째로만 뛴다.
 */
const slugCounts = new Map()
function slugify(raw) {
  const base =
    raw
      .toLowerCase()
      .trim()
      // 마크다운 강조 문자와 문장부호를 뺀다. \p{L}은 한글을 살린다 — 이 연재는
      // 제목이 거의 전부 한글이라 ASCII만 남기면 id가 죄다 빈 문자열이 된다.
      .replace(/[^\p{L}\p{N}\s-]/gu, '')
      .replace(/\s+/g, '-') || 'section'
  const n = slugCounts.get(base) ?? 0
  slugCounts.set(base, n + 1)
  return n ? `${base}-${n}` : base
}

const md = new Marked({
  renderer: {
    html({ text }) {
      return esc(text)
    },
    heading({ tokens, depth, text }) {
      const inner = this.parser.parseInline(tokens)
      return `<h${depth} id="${esc(slugify(text))}">${inner}</h${depth}>\n`
    },
  },
})

/** 요약 뽑기 — meta description·OG·RSS·목록에 함께 쓴다.
 *
 * 첫 인용문을 쓰면 안 된다. 이 저장소의 개발일지는 그 자리에 **글쓰기 지침**을
 * 적어두는 관례라(“입문자가 읽어도 이해되게 —”), 24편 중 21편이 같은 접두사로
 * 시작하는 설명을 갖게 된다. 거의 같은 설명은 검색엔진이 버리는 신호고, 이 기능은
 * 애초에 '검색 유입이 구조적으로 0'인 걸 고치려고 만든 것이다.
 * 그래서 첫 ## 섹션 아래의 실제 본문 문단을 쓴다. */
function summarize(body) {
  const afterFirstHeading = body.replace(/^[\s\S]*?\n##\s+.+\n/, '')
  for (const source of [afterFirstHeading, body]) {
    for (const block of source.split(/\n{2,}/).map((s) => s.trim())) {
      if (!block || /^[#>|]|^```/.test(block)) continue
      // 불릿은 **구분자로 바꾼다.** 예전엔 `^[-*]\s+`를 빈 문자열로 지우고 곧바로
      // `\s+ → ' '`로 줄바꿈까지 없앴는데, 불릿 목록은 항목 사이에 빈 줄이 없어
      // 한 덩어리(block)다 → 항목 여러 개가 **구분자 없이 이어붙었다.**
      // 실측(2026-08-11): 28편 중 9편이 그 상태였고, 예컨대 2026-08-07 편의 설명이
      // "…배포·스모크까지 끝 공개 데모 계정을 폐지했다…"로 나갔다. 검색결과 스니펫이
      // 중간에 잘린 비문이 되는데, 이 기능은 애초에 검색 유입을 만들려고 넣은 것이다.
      const text = block
        .replace(/^[-*]\s+/gm, '· ')
        .replace(/[#*`>_[\]]/g, '')
        .replace(/\s+/g, ' ')
        .replace(/^·\s*/, '') // 첫 항목의 구분자는 군더더기다
        .trim()
      // '이번 편의 형식:'도 편마다 거의 같은 메타 문장이라 건너뛴다.
      if (text.length >= 40 && !/^이번 편의 형식/.test(text)) return text.slice(0, 200)
    }
  }
  return ''
}

/** 날짜 → 태그. 원본 표는 scripts/devlog_posts.py의 POSTS이고, 그 파이썬이
 *  content/devlog/tags.json으로 내보낸 것을 여기서 읽는다.
 *
 *  왜 이렇게까지 하나: 태그는 발행 스크립트가 DB에 넣는 값과 **같은 값이어야 한다.**
 *  여기서 마크다운을 다시 파싱하거나 손으로 적으면 두 벌이 되고, 두 벌은 갈라진다.
 *  Node가 파이썬 소스를 읽을 수는 없으니 json이 다리다(생성물이지만 커밋한다 —
 *  CI·배포는 docx도 파이썬도 돌리지 않는다). */
function readTagMap() {
  const path = join(SRC, 'tags.json')
  if (!existsSync(path)) {
    console.error(`\n❌ ${path} 가 없다. \`python scripts/devlog_posts.py\`로 만들어라.\n`)
    process.exit(1)
  }
  return JSON.parse(readFileSync(path, 'utf8'))
}

/** 마크다운 한 편 읽기. 제목은 첫 H1, 날짜는 파일명 — 프론트매터가 없어서다. */
function readPost(file) {
  const date = file.replace(/\.md$/, '')
  const raw = readFileSync(join(SRC, file), 'utf8')
  const h1 = raw.match(/^#\s+(.+)$/m)
  // H1은 본문에서 뺀다(템플릿이 <h1>을 따로 넣으므로 남기면 제목이 두 번 나온다).
  // **matched 문자열만 지운다** — 정규식으로 다시 지우면 H1이 없는 파일에서
  // 코드펜스 안의 `# 주석` 첫 줄이 조용히 사라진다(이 일지들은 쉘 주석이 많다).
  const body = (h1 ? raw.replace(h1[0], '') : raw).trim()
  slugCounts.clear() // id 중복 카운터는 **편마다** 초기화한다(안 하면 2편부터 -1이 붙는다)
  return {
    date,
    slug: `devlog/${date}.html`,
    title: h1 ? h1[1].trim() : date,
    summary: summarize(body),
    html: md.parse(body),
    body, // GFM 가드가 원문을 본다(아래 gfmOnly 참고)
  }
}

/** /devlog.html의 검색·태그 필터. 별도 파일로 낸다(인라인은 CSP가 막는다).
 *
 *  의존성 없이 맨 DOM만 쓴다 — 이 페이지는 '서버도 번들도 없이 도는 곳'이고,
 *  여기에 프레임워크를 끌어오면 그 성질을 잃는다.
 *
 *  목록은 이미 HTML에 다 있다. 이 스크립트는 **줄을 숨기고 보이는 일만** 한다.
 *  그래서 스크립트가 실패하면 필터가 안 뜰 뿐, 31편은 그대로 읽힌다. */
const FILTER_JS = `// 생성물 — frontend/scripts/gen-static.mjs가 만든다. 직접 고치지 말 것.
(function () {
  var filter = document.getElementById('filter')
  var list = document.getElementById('posts')
  if (!filter || !list) return

  var items = Array.prototype.slice.call(list.children)
  var input = document.getElementById('q')
  var count = document.getElementById('count')
  var empty = document.getElementById('empty')
  var buttons = Array.prototype.slice.call(filter.querySelectorAll('[data-tag]'))
  var active = ''

  function apply() {
    var q = input.value.trim().toLowerCase()
    var shown = 0
    items.forEach(function (li) {
      var tags = (li.getAttribute('data-tags') || '').split('|')
      var ok =
        (!active || tags.indexOf(active) !== -1) &&
        (!q || (li.getAttribute('data-text') || '').indexOf(q) !== -1)
      li.hidden = !ok
      if (ok) shown++
    })
    count.textContent =
      active || q ? shown + '편 (전체 ' + items.length + '편 중)' : ''
    empty.hidden = shown !== 0

    // 주소에 태그를 남긴다 — 편별 페이지의 태그 칩이 ?tag=로 오고, 걸러진 상태를
    // 그대로 공유·북마크할 수 있어야 한다. pushState가 아니라 replaceState인 이유:
    // 글자를 칠 때마다 히스토리가 쌓이면 뒤로가기가 먹통이 된다.
    var url = location.pathname + (active ? '?tag=' + encodeURIComponent(active) : '')
    history.replaceState(null, '', url)
  }

  function select(tag) {
    active = active === tag ? '' : tag
    buttons.forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-tag') === active))
    })
    apply()
  }

  buttons.forEach(function (b) {
    b.addEventListener('click', function () {
      select(b.getAttribute('data-tag'))
    })
  })
  input.addEventListener('input', apply)

  // 들어올 때 ?tag=가 있으면 그 상태로 시작한다.
  var initial = new URLSearchParams(location.search).get('tag')
  if (initial && buttons.some(function (b) { return b.getAttribute('data-tag') === initial })) {
    select(initial)
  }

  filter.hidden = false // 여기까지 왔으면 필터가 실제로 동작한다 — 그때 보여준다
  apply()
})()
`

const page = ({ title, description, url, body, article, published, script }) => `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
<link rel="canonical" href="${url}">
<link rel="alternate" type="application/rss+xml" title="${esc(TITLE)}" href="${SITE}/rss.xml">
<meta property="og:type" content="${article ? 'article' : 'website'}">
<meta property="og:site_name" content="${esc(TITLE)}">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(description)}">
<meta property="og:url" content="${url}">
<meta property="og:image" content="${SITE}/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ko_KR">${published ? `
<meta property="article:published_time" content="${published}">` : ''}
<meta name="twitter:card" content="summary_large_image">
<!-- twitter:*는 og로 폴백되지만 title/description/image는 폴백이 보장되지 않는다
     (2026-08-12 실측: 이 페이지들엔 twitter:card만 있었다). 명시한다. -->
<meta name="twitter:title" content="${esc(title)}">
<meta name="twitter:description" content="${esc(description)}">
<meta name="twitter:image" content="${SITE}/og-image.png">${article && published ? `
<script type="application/ld+json">${JSON.stringify({
  '@context': 'https://schema.org',
  '@type': 'BlogPosting',
  headline: title,
  description,
  datePublished: published,
  url,
  image: `${SITE}/og-image.png`,
  inLanguage: 'ko',
  isPartOf: { '@type': 'Blog', name: TITLE, url: `${SITE}/devlog.html` },
}).replace(/</g, '\\u003c')}</script>` : ''}
<style>
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1.25rem 5rem;font:16px/1.75 -apple-system,BlinkMacSystemFont,"Pretendard","Segoe UI",sans-serif;color:#1d1d1f;background:#fff}
main{max-width:44rem;margin:0 auto}
a{color:#0071e3}
h1{font-size:1.9rem;line-height:1.3;letter-spacing:-.02em;margin:.5rem 0 1rem}
h2{font-size:1.35rem;margin:2.5rem 0 .75rem;letter-spacing:-.01em}
h3{font-size:1.1rem;margin:2rem 0 .5rem}
pre{background:#f5f5f7;padding:1rem;border-radius:12px;overflow-x:auto;font-size:.86rem;line-height:1.6}
code{background:#f5f5f7;padding:.15em .4em;border-radius:6px;font-size:.88em}
pre code{background:none;padding:0}
blockquote{margin:1.5rem 0;padding:.75rem 1.25rem;border-left:3px solid #d2d2d7;color:#515154}
table{border-collapse:collapse;width:100%;margin:1.5rem 0;font-size:.92rem;display:block;overflow-x:auto}
th,td{border:1px solid #d2d2d7;padding:.5rem .75rem;text-align:left}
img{max-width:100%;height:auto}
.nav{font-size:.9rem;margin-bottom:2rem}
.seriesnav{display:flex;gap:1rem;margin:3rem 0 1rem;padding-top:1.5rem;border-top:1px solid #e8e8ed}
.seriesnav-item{flex:1;min-width:0;text-decoration:none;display:block}
.seriesnav-item:last-child{text-align:right}
.seriesnav-empty{pointer-events:none}
.seriesnav-label{display:block;color:#6e6e73;font-size:.8rem;margin-bottom:.25rem}
.seriesnav-title{display:block;font-weight:600;font-size:.95rem;line-height:1.4}
.seriesnav-all{margin:0 0 1rem}
@media(max-width:34rem){.seriesnav{flex-direction:column;gap:1.25rem}.seriesnav-item:last-child{text-align:left}}
/* 태그 칩 · 필터 · 관련 글 */
.tags{display:flex;flex-wrap:wrap;gap:.4rem;margin:.5rem 0 1.75rem}
.tag{display:inline-block;padding:.2rem .6rem;border:1px solid #d2d2d7;border-radius:999px;
  background:none;color:#515154;font:inherit;font-size:.82rem;text-decoration:none;cursor:pointer}
.tag:hover{border-color:#0071e3;color:#0071e3}
.tag[aria-pressed="true"]{background:#0071e3;border-color:#0071e3;color:#fff}
.tag-n{opacity:.6;font-size:.9em}
.filter{margin:0 0 1.5rem}
.filter input{width:100%;padding:.6rem .8rem;font:inherit;font-size:.95rem;color:inherit;
  background:none;border:1px solid #d2d2d7;border-radius:10px}
.tagbar{display:flex;flex-wrap:wrap;gap:.4rem;margin:.75rem 0 0}
.filter-count,.filter-empty{color:#6e6e73;font-size:.85rem;margin:.75rem 0 0}
.related{margin:3rem 0 0;padding-top:1.5rem;border-top:1px solid #e8e8ed}
.related-h{font-size:1rem;margin:0;color:#6e6e73;letter-spacing:0}
.related .list li:last-child{border-bottom:none}
/* 화면에선 안 보이되 스크린리더는 읽는다(검색칸 라벨). display:none이면 안 읽힌다. */
.visually-hidden{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
  clip:rect(0 0 0 0);white-space:nowrap;border:0}
/* #86868b는 흰 배경에서 3.7:1이라 WCAG AA(4.5:1)에 못 미쳤다 — 날짜·요약이
   본문 읽기 경로 위에 있어서 저시력 독자에게 바로 걸린다. #6e6e73은 5.1:1. */
.meta{color:#6e6e73;font-size:.9rem}
.list{list-style:none;padding:0}
.list li{padding:1rem 0;border-bottom:1px solid #e8e8ed}
.list a{font-weight:600;text-decoration:none;font-size:1.05rem}
.list p{margin:.35rem 0 0;color:#515154;font-size:.92rem}
@media(prefers-color-scheme:dark){
body{color:#f5f5f7;background:#000}
a{color:#0a84ff}
pre,code{background:#1c1c1e}
blockquote{border-color:#38383a;color:#a1a1a6}
th,td{border-color:#38383a}
.list li{border-color:#1c1c1e}
.meta,.list p{color:#a1a1a6}
.seriesnav{border-color:#1c1c1e}
.seriesnav-label{color:#a1a1a6}
.tag{border-color:#38383a;color:#a1a1a6}
.tag:hover{border-color:#0a84ff;color:#0a84ff}
.tag[aria-pressed="true"]{background:#0a84ff;border-color:#0a84ff;color:#fff}
.filter input{border-color:#38383a}
.filter-count,.filter-empty{color:#a1a1a6}
.related{border-color:#1c1c1e}
.related-h{color:#a1a1a6}
}
</style>
</head>
<body><main>
<p class="nav"><a href="/">← ${esc(TITLE)}</a> · <a href="/devlog.html">개발일지 전체</a> · <a href="/rss.xml">RSS</a></p>
${body}
</main>${
  script
    ? // ⚠️ **인라인 <script>를 쓰면 안 된다.** CSP가 script-src 'self'라
      // (terraform/csp-function.js) 인라인은 차단되고, 차단돼도 목록은 그대로
      // 보여서 "필터가 왜 안 뜨지" 말고는 아무 단서가 없다. 자기 출처 파일로 낸다.
      `\n<script src="${script}" defer></script>`
    : ''
}</body>
</html>
`

function main() {
  // content/는 저장소 루트에 있는데 **프론트 Docker 이미지의 빌드 컨텍스트는
  // frontend/ 뿐이라** 그 안에서는 보이지 않는다(로컬 compose의 frontend 서비스).
  // 반면 배포는 GitHub Actions가 저장소 전체를 체크아웃한 뒤 빌드하므로 보인다.
  //
  // 그래서 없으면 건너뛴다 — 로컬 컨테이너 빌드를 이것 때문에 깨뜨릴 이유가 없다.
  // 대신 **조용히 넘어가면 안 되는 곳(배포)에서는 시끄럽게 실패**하도록,
  // deploy.yml이 빌드 뒤 rss.xml·sitemap.xml 존재를 확인한다. 여기서 fail-open,
  // 거기서 fail-closed — 어느 쪽도 혼자서는 충분하지 않다.
  if (!existsSync(SRC)) {
    console.log(`  (건너뜀) ${SRC} 없음 — 정적 아카이브·RSS·sitemap을 만들지 않았다`)
    return
  }

  const posts = readdirSync(SRC)
    .filter((f) => f.endsWith('.md'))
    .sort()
    .map(readPost)
    .reverse() // 최신순

  // 태그를 붙인다. **없으면 멈춘다.** 조용히 빈 배열로 넘어가면 그 편만 필터·관련
  // 글에서 사라지는데, 페이지는 멀쩡히 만들어져서 아무도 모른다 — 새 편을 쓰고
  // tags.json 내보내기를 잊는 게 정확히 그 경로다(devlog_to_markdown.py가 이제
  // 마크다운을 쓸 때 같이 내보낸다).
  const tagMap = readTagMap()
  const missing = posts.filter((p) => !tagMap[p.date]?.tags?.length).map((p) => p.date)
  if (missing.length) {
    console.error(`\n❌ content/devlog/tags.json에 태그가 없는 편: ${missing.join(', ')}`)
    console.error('   → scripts/devlog_posts.py의 POSTS에 추가하고 `python scripts/devlog_posts.py`.\n')
    process.exit(1)
  }
  for (const p of posts) p.tags = tagMap[p.date].tags

  // ── 두 렌더러가 같은 원문을 다르게 읽는 것을 막는 가드 ──────────────────
  // 이 파일은 marked(GFM 지원)로 정적 아카이브를 만들고, **같은 마크다운**이
  // build_devlog_payload.py를 거쳐 DB 글이 되어 앱의 react-markdown으로 렌더된다.
  // react-markdown은 v6부터 GFM을 기본 제공하지 않고 이 앱은 remark-gfm을 안 쓴다
  // (넣으면 gzip +11.2 KB 실측 — 2026-08-11에 재보고 안 넣기로 했다. 지금 GFM을
  //  쓰는 발행 글이 0건이라 값을 못 한다).
  //
  // 그래서 개발일지에 표·취소선·체크박스를 쓰면 **아카이브에선 멀쩡하고 앱에서만
  // 원문이 그대로 보인다.** 그건 아무 데도 안 뜨는 조용한 어긋남이라 여기서 막는다.
  // 되살리려면 remark-gfm을 넣고 이 가드를 지우면 된다 — 둘 중 하나는 반드시 참이어야 한다.
  // ⚠️ **코드블록과 인라인 코드를 먼저 걷어낸다.** 이 일지들은 주제가 개발이라
  //    마크다운 문법 자체를 코드펜스 안에 인용한다 — 실제로 첫 구현이 2026-08-09.md의
  //    ```로 감싼 로드맵 인용(`- [ ] ECS`)을 물어서 오탐을 냈다. 렌더링되지 않는 자리를
  //    문제로 보고하면 이 검사는 곧 무시당한다(check_runbook_drift.sh D번이 주석에
  //    매치하던 것과 같은 병이다).
  const stripCode = (s) =>
    s
      .replace(/^```[\s\S]*?^```/gm, '') // 펜스 블록
      .replace(/^(?: {4}|\t).*$/gm, '') // 들여쓰기 코드블록
      .replace(/`[^`\n]*`/g, '') // 인라인 코드
      // 아래 autolink 검사를 위해 **정상적인 링크 표기**도 걷어낸다. 이 셋은 양쪽
      // 렌더러가 똑같이 링크로 만들므로 어긋남이 아니다: 마크다운 링크 []()
      // , CommonMark 명시 autolink <http://…>, <메일주소>.
      .replace(/\]\([^)]*\)/g, '')
      .replace(/<https?:\/\/[^>]*>/g, '')
      .replace(/<[^@\s>]+@[^\s>]+>/g, '')
  const gfmOnly = [
    [/^\|[ :|-]+\|\s*$/m, '표(| --- |)'],
    [/~~[^~\n]+~~/, '취소선(~~)'],
    [/^\s*[-*] \[[ xX]\] /m, '체크박스(- [ ])'],
    // ⚠️ **맨몸 URL·이메일도 GFM 전용이다**(autolink 확장). 2026-08-14 검사에서
    // 이 가드가 그걸 안 보고 있다는 걸 알았고, 실제로 1편이 그 상태로 라이브였다 —
    // 정적 아카이브에선 링크가 되고 앱에선 글자로 남았는데, 하필 그 링크가
    // localhost와 **폐지된 데모 계정 주소**였다. 클릭하면 죽는 링크가 표면 하나에만
    // 생긴 것이다. 쓰려면 백틱으로 감싸거나 []() 로 명시하라.
    [/(^|[\s(])https?:\/\/[^\s)<]+/m, '맨몸 URL(autolink)'],
    [/(^|[\s(])[\w.+-]+@[\w-]+\.[\w.-]+/m, '맨몸 이메일(autolink)'],
  ]
  // about.md도 같은 가드를 받는다 — 이 파일 역시 두 렌더러가 함께 읽는다
  // (여기서 /about.html, 앱에서 react-markdown). 실제로 처음 쓸 때 표를 넣었다가
  // 앱에서 파이프 문자가 그대로 보일 뻔했다.
  const aboutPath = join(SRC, '..', 'about.md')
  const aboutRaw = existsSync(aboutPath) ? readFileSync(aboutPath, 'utf8') : null

  const offenders = []
  for (const p of posts) {
    const prose = stripCode(p.body)
    for (const [re, label] of gfmOnly) {
      if (re.test(prose)) offenders.push(`${p.date}: ${label}`)
    }
  }
  if (aboutRaw) {
    const prose = stripCode(aboutRaw)
    for (const [re, label] of gfmOnly) {
      if (re.test(prose)) offenders.push(`about.md: ${label}`)
    }
  }
  if (offenders.length) {
    console.error('\n❌ 앱이 렌더 못 하는 GFM 문법이 개발일지에 있다 (정적 아카이브에서만 보인다):')
    for (const o of offenders) console.error(`     ${o}`)
    console.error('   → 그 문법을 안 쓰게 고치거나, frontend에 remark-gfm을 넣고 이 가드를 지워라.\n')
    process.exit(1)
  }

  mkdirSync(join(OUT, 'devlog'), { recursive: true })

  /**
   * 연재 이동 링크. **이 페이지들이 막다른 길이었다**(2026-08-14 검사).
   *
   * SPA 쪽엔 이미 이전/다음 편 이동이 있는데(PostDetailPage의 SeriesPrevNext) 정적
   * 아카이브엔 없었다. 그런데 sitemap에 30편이 전부 올라가 있어서 **검색으로 들어오는
   * 독자는 이쪽에 떨어진다.** 게다가 서버가 평소 꺼져 있어 RSS·공유 링크도 이쪽을 가리킨다.
   * 즉 24만 자 연재의 주 유입 경로에서, 한 편을 다 읽은 사람이 다음 편으로 갈 길이 없었다.
   *
   * ⚠️ `posts`는 **최신순**이다. i+1이 이전 편(더 오래된 것), i-1이 다음 편이다.
   * 여기서 방향을 뒤집으면 30편짜리 연재가 거꾸로 읽힌다.
   */
  const seriesNav = (i) => {
    const older = posts[i + 1] // 이전 편
    const newer = posts[i - 1] // 다음 편
    if (!older && !newer) return ''
    const link = (p, label) =>
      p
        ? `<a class="seriesnav-item" href="/${p.slug}"><span class="seriesnav-label">${label}</span>` +
          `<span class="seriesnav-title">${esc(p.title)}</span></a>`
        : // 첫 편·마지막 편은 한쪽이 없다. 빈 칸을 남겨야 남은 하나가 제자리를 지킨다
          // (안 남기면 '이전 편'만 있는 마지막 편에서 그 링크가 오른쪽으로 붙는다).
          '<span class="seriesnav-item seriesnav-empty"></span>'
    return (
      `<nav class="seriesnav" aria-label="연재 이동">` +
      link(older, '← 이전 편') +
      link(newer, '다음 편 →') +
      `</nav>` +
      `<p class="nav seriesnav-all"><a href="/devlog.html">개발일지 ${posts.length}편 전체 보기</a></p>`
    )
  }

  /** 모든 편에 붙는 태그는 관련도 계산에서 뺀다.
   *  '개발일지'가 31편 전부에 있어서, 그대로 두면 아무 두 편이나 1점씩 겹쳐
   *  "관련 글"이 사실상 최신 3편 고정이 된다 — 추천처럼 보이지만 정보가 0이다. */
  const universal = new Set(posts[0].tags.filter((t) => posts.every((p) => p.tags.includes(t))))
  const distinct = (p) => p.tags.filter((t) => !universal.has(t))

  /**
   * 같은 주제의 다른 편. **이전/다음 편은 뺀다** — 바로 위 seriesNav가 이미 보여준다.
   * 겹치는 태그가 많은 순, 같으면 최신 순. 겹치는 게 없으면 아예 안 그린다
   * (억지로 채우면 '관련'이라는 말이 거짓이 된다).
   */
  const relatedNav = (i) => {
    const mine = new Set(distinct(posts[i]))
    if (!mine.size) return ''
    const hits = posts
      .map((p, j) => ({ p, j, shared: distinct(p).filter((t) => mine.has(t)) }))
      .filter(({ j, shared }) => j !== i && j !== i - 1 && j !== i + 1 && shared.length)
      .sort((a, b) => b.shared.length - a.shared.length || (a.p.date < b.p.date ? 1 : -1))
      .slice(0, 3)
    if (!hits.length) return ''
    return (
      `<nav class="related" aria-labelledby="related-h">` +
      `<h2 id="related-h" class="related-h">비슷한 주제의 편</h2><ul class="list">` +
      hits
        .map(
          ({ p, shared }) =>
            `<li><a href="/${p.slug}">${esc(p.title)}</a>` +
            `<p>${p.date} · ${shared.map((t) => esc(t)).join(' · ')}</p></li>`,
        )
        .join('') +
      `</ul></nav>`
    )
  }

  /** 태그 칩. 누르면 아카이브 인덱스가 그 태그로 걸러진 채 열린다(?tag=). */
  const tagChips = (p) =>
    `<p class="tags">` +
    p.tags
      .map((t) => `<a class="tag" href="/devlog.html?tag=${encodeURIComponent(t)}">${esc(t)}</a>`)
      .join('') +
    `</p>`

  // 1) 편별 정적 페이지 — 크롤러와 사람 모두 서버 없이 전문을 읽는다.
  //    SPA 라우트(/blog/posts/{id})와 달리 여기엔 편마다 제 OG 태그가 붙는다.
  for (const [i, p] of posts.entries()) {
    writeFileSync(
      join(OUT, 'devlog', `${p.date}.html`),
      page({
        title: `${p.title} — ${TITLE}`,
        description: p.summary || DESC,
        url: `${SITE}/${p.slug}`,
        article: true,
        // 날짜만 있는 원고라 자정 기준으로 만든다. 타임존을 빼면 읽는 쪽이 UTC로 보고
        // 하루 앞당겨 표시하는 일이 생긴다(작성 시각은 애초에 날짜 단위로만 안다).
        published: `${p.date}T00:00:00+09:00`,
        body:
          `<h1>${esc(p.title)}</h1><p class="meta">${p.date}</p>${tagChips(p)}` +
          `${p.html}${seriesNav(i)}${relatedNav(i)}`,
      }),
    )
  }

  // 2) 아카이브 인덱스. /devlog/ 가 아니라 /devlog.html 인 이유는 위 주석 참고.
  //
  //   31편이 한 줄씩 날짜순으로만 쌓여 있어서, "보안 얘기 어느 편이었지"를 찾으려면
  //   제목 31개를 눈으로 훑는 수밖에 없었다. 검색·태그 필터를 붙인다.
  //
  //   **점진적 향상으로 짠다.** 목록 자체는 그대로 HTML에 다 들어 있고(크롤러도
  //   JS 없는 브라우저도 전편을 본다), 필터 UI만 `hidden`으로 숨겨 두었다가
  //   스크립트가 벗긴다. 반대로 짜면 — 필터로 목록을 그리면 — JS가 막히는 순간
  //   이 페이지가 백지가 되는데, 그건 이 페이지의 존재 이유("서버도 스크립트도
  //   없이 읽힌다")를 정면으로 부순다.
  const tagCounts = new Map()
  for (const p of posts) for (const t of p.tags) tagCounts.set(t, (tagCounts.get(t) ?? 0) + 1)
  const tagbar = [...tagCounts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ko'))
    .map(
      ([t, n]) =>
        `<button type="button" class="tag" data-tag="${esc(t)}" aria-pressed="false">` +
        `${esc(t)} <span class="tag-n">${n}</span></button>`,
    )
    .join('')

  writeFileSync(
    join(OUT, 'devlog.html'),
    page({
      title: `개발일지 — ${TITLE}`,
      description: `개발일지 ${posts.length}편. 서버 없이도 읽을 수 있습니다.`,
      url: `${SITE}/devlog.html`,
      script: '/devlog-filter.js',
      body:
        `<h1>개발일지</h1><p class="meta">${posts.length}편 · 이 페이지는 서버 없이 동작합니다</p>` +
        `<div class="filter" id="filter" hidden>` +
        `<label class="visually-hidden" for="q">제목·요약 검색</label>` +
        `<input id="q" type="search" placeholder="제목·요약에서 찾기" autocomplete="off">` +
        `<div class="tagbar">${tagbar}</div>` +
        // role=status: 필터링 결과 건수가 스크린리더에도 읽히게 한다. 시각적으로는
        // 목록이 줄어드는 게 보이지만, 안 보이는 사람에게는 아무 일도 안 일어난 것과 같다.
        `<p class="filter-count" id="count" role="status"></p>` +
        `</div>` +
        `<ul class="list" id="posts">` +
        posts
          .map(
            (p) =>
              `<li data-tags="${esc(p.tags.join('|'))}" ` +
              `data-text="${esc(`${p.title} ${p.summary} ${p.date}`.toLowerCase())}">` +
              `<a href="/${p.slug}">${esc(p.title)}</a>` +
              `<p>${p.date}${p.summary ? ` — ${esc(p.summary)}` : ''}</p></li>`,
          )
          .join('') +
        '</ul>' +
        `<p class="filter-empty" id="empty" hidden>찾는 편이 없다. 검색어나 태그를 지워봐.</p>`,
    }),
  )

  // (2의 짝) 필터 스크립트. 인라인이 아니라 파일인 이유는 page() 안 주석 참고(CSP).
  writeFileSync(join(OUT, 'devlog-filter.js'), FILTER_JS)

  // 2-B) 포털용 목록 JSON — **첫 화면이 빈 채로 뜨는 문제를 서버 없이 고친다.**
  //
  //   진단(2026-08-12): 이 사이트의 랜딩(/)은 입구 카드 두 장뿐이라 글 제목·날짜가
  //   0개였다. 반면 자산은 개발일지 29편 23.9만 자다 → 첫 화면 노출이 0%였다.
  //   글 목록은 전량 /api에서 오는데 이 사이트는 EC2를 평소 꺼둔다. 즉 방문자가
  //   **가장 흔하게 보는 상태가 빈 화면**이었고, 서버 없이 읽히는 유일한 경로인
  //   /devlog.html은 푸터의 12px 회색 글씨였다.
  //
  //   그래서 API가 아니라 **여기서** 목록을 낸다. 이 파일은 이미 content/devlog를
  //   읽고 있으니 추가 비용이 거의 없고, S3에 정적으로 놓이므로 EC2와 무관하게 산다.
  //   링크도 SPA 라우트가 아니라 정적 아카이브(/devlog/*.html)로 건다 — 서버가
  //   꺼져 있어도 클릭이 살아 있어야 이 작업이 의미가 있다.
  //
  //   요약은 이미 만든 summarize()를 그대로 쓴다(같은 값이 OG·RSS·아카이브에 쓰인다).
  //   글자 수는 본문 기준이라 마크다운 기호가 섞이지만, 첫 화면에 쓰는 근사치다.
  writeFileSync(
    join(OUT, 'devlog-index.json'),
    JSON.stringify({
      total: posts.length,
      chars: posts.reduce((n, p) => n + p.body.length, 0),
      posts: posts.map(({ date, title, slug, summary, tags }) => ({
        date,
        title,
        slug,
        summary,
        tags,
      })),
    }),
  )

  // 2-C) 소개(About). **한 벌만 쓴다** — content/about.md가 유일한 원본이고,
  //   여기서 정적 페이지 /about.html을 만들고 **원문도 그대로 배포한다**(/about.md).
  //   앱의 /about 화면은 그 원문을 받아 렌더한다.
  //
  //   왜 앱에 같은 글을 또 안 박는가: 두 벌이 되면 반드시 갈라진다(이 저장소가
  //   반복해서 당한 병이다 — 문서와 코드가 어긋나 있던 자리를 몇 번이나 고쳤다).
  //   왜 import가 아니라 fetch인가: content/는 저장소 루트에 있는데 **프론트 Docker
  //   이미지의 빌드 컨텍스트는 frontend/뿐이라** 안 보인다(위 main() 머리말과 같은 사정).
  //   빌드 타임 import로 묶으면 로컬 compose의 프론트 빌드가 깨진다.
  if (aboutRaw) {
    writeFileSync(join(OUT, 'about.md'), aboutRaw)
    const h1 = aboutRaw.match(/^#\s+(.+)$/m)
    const aboutBody = (h1 ? aboutRaw.replace(h1[0], '') : aboutRaw).trim()
    writeFileSync(
      join(OUT, 'about.html'),
      page({
        title: `소개 — ${TITLE}`,
        description: `${TITLE}를 만든 사람과, 이 사이트를 만든 방식.`,
        url: `${SITE}/about.html`,
        body: `<h1>${esc(h1 ? h1[1].trim() : '소개')}</h1>${md.parse(aboutBody)}`,
      }),
    )
  }

  // 3) RSS — 전문을 싣는다. 구독자는 이 파일 하나로 사이트에 들어오지 않고도
  //    전부 읽는다. 서버가 꺼져 있어도 동작하는 성질을 그대로 이어받는다.
  //
  //    **최근 20편으로 끊는다.** 전문을 싣기 때문에 24편에 이미 400KB이고,
  //    편수에 비례해 계속 커진다. 리더는 이걸 주기적으로 다시 받으므로 그대로 두면
  //    CloudFront 전송량이 글 쓸수록 늘어난다(이 프로젝트에서 비용은 실제 제약이다).
  //    피드는 '새 글을 알리는' 물건이고, 과거 전부는 /devlog.html과 sitemap이 맡는다.
  const FEED_MAX = 20
  const feedPosts = posts.slice(0, FEED_MAX)
  const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>${esc(TITLE)}</title>
<link>${SITE}/</link>
<description>${esc(DESC)}</description>
<language>ko</language>
<atom:link href="${SITE}/rss.xml" rel="self" type="application/rss+xml"/>
${feedPosts
  .map(
    (p) => `<item>
<title>${esc(p.title)}</title>
<link>${SITE}/${p.slug}</link>
<guid isPermaLink="true">${SITE}/${p.slug}</guid>
<pubDate>${new Date(`${p.date}T09:00:00+09:00`).toUTCString()}</pubDate>
<description>${esc(p.summary)}</description>
<content:encoded><![CDATA[${p.html.replace(/]]>/g, ']]]]><![CDATA[>')}]]></content:encoded>
</item>`,
  )
  .join('\n')}
</channel>
</rss>
`
  writeFileSync(join(OUT, 'rss.xml'), rss)

  // 4) sitemap — 정적 페이지만 싣는다. SPA 라우트(/blog/posts/{id})는 일부러 뺐다:
  //    크롤러가 가면 빈 껍데기이거나(서버 꺼짐) 504다. 없는 내용을 색인하라고
  //    부르는 건 도움이 안 된다.
  const urls = [
    { loc: `${SITE}/`, pri: '1.0' },
    { loc: `${SITE}/devlog.html`, pri: '0.9' },
    // about.html도 서버 없이 열리는 정적 페이지라 색인해도 빈 껍데기가 아니다.
    ...(aboutRaw ? [{ loc: `${SITE}/about.html`, pri: '0.5' }] : []),
    ...posts.map((p) => ({ loc: `${SITE}/${p.slug}`, pri: '0.8', lastmod: p.date })),
  ]
  writeFileSync(
    join(OUT, 'sitemap.xml'),
    `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls
  .map(
    (u) =>
      `<url><loc>${u.loc}</loc>${u.lastmod ? `<lastmod>${u.lastmod}</lastmod>` : ''}<priority>${u.pri}</priority></url>`,
  )
  .join('\n')}
</urlset>
`,
  )

  // 5) robots.txt — /api/*는 크롤링해봐야 JSON이고 서버를 깨울 뿐이라 막는다.
  writeFileSync(
    join(OUT, 'robots.txt'),
    `User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: ${SITE}/sitemap.xml\n`,
  )

  console.log(
    `  정적 산출물: 개발일지 ${posts.length}편 + devlog.html + devlog-index.json + ` +
      `rss.xml(최근 ${feedPosts.length}편) + sitemap.xml + robots.txt`,
  )
}

main()
