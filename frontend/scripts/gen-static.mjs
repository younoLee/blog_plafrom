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
import { execFileSync } from 'node:child_process'
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

/** 방금 판 편의 소제목들 — 목차를 만드는 재료다.
 *
 *  **렌더러가 실제로 붙인 id를 그대로 모은다.** 목차용으로 slug를 다시 계산하면
 *  중복 번호(`-1`)나 기호 처리가 어긋나 링크가 죽는 자리가 생긴다. 앱 쪽 Toc.tsx의
 *  slug()도 규칙이 달라서 복사하면 안 된다 — 같은 값을 두 번 계산하지 않는 게 요점이다. */
let headings = []

const md = new Marked({
  renderer: {
    html({ text }) {
      return esc(text)
    },
    heading({ tokens, depth, text }) {
      const inner = this.parser.parseInline(tokens)
      const id = esc(slugify(text))
      if (depth <= 3) headings.push({ id, depth, text })
      return `<h${depth} id="${id}">${inner}</h${depth}>\n`
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
  headings = [] // 같은 이유로 목차 재료도 편마다 비운다
  // ⚠️ `html`을 먼저 만들어야 headings가 찬다 — 렌더러가 도는 시점이 여기다.
  const html = md.parse(body)
  return {
    date,
    slug: `devlog/${date}.html`,
    title: h1 ? h1[1].trim() : date,
    summary: summarize(body),
    html,
    headings: headings.slice(),
    body, // GFM 가드가 원문을 본다(아래 gfmOnly 참고)
  }
}

/** git 이력 — /log.html과 편별 '그날의 커밋'의 재료.
 *
 *  왜 git을 직접 읽나: 커밋 제목은 이 저장소의 **두 번째 연재**다. 315개가 쌓여 있고
 *  개발일지가 '그날 무엇을 배웠나'라면 커밋은 '그날 무엇을 건드렸나'인데, 후자를
 *  볼 수 있는 자리가 웹에 없었다. 스냅샷 파일로 커밋해두는 방법(tags.json 방식)도
 *  있지만 그건 매 커밋마다 낡는다 — 자기를 갱신하는 커밋을 자기가 담을 수 없어서다.
 *
 *  ⚠️ **얕은 체크아웃이면 이력이 1개뿐이다.** deploy.yml에 `fetch-depth: 0`을 넣어뒀고
 *  그 이유도 거기 적어뒀다. git이 아예 없으면(프론트 Docker 빌드 컨텍스트) 빈 배열을
 *  주고 경고한다 — 배포 쪽은 산출물 존재를 따로 검사하므로 조용히 넘어가지 않는다. */
function readCommits() {
  try {
    const out = execFileSync(
      'git',
      ['log', '--no-merges', '--date=short', '--format=%ad\u0001%h\u0001%s'],
      { cwd: join(HERE, '..', '..'), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 },
    )
    return out
      .trim()
      .split('\n')
      .filter(Boolean)
      .map((line) => {
        const [date, hash, subject] = line.split('\u0001')
        return { date, hash, subject }
      })
  } catch {
    console.warn('  (건너뜀) git 이력을 못 읽었다 — /log.html과 그날의 커밋을 만들지 않는다')
    return []
  }
}

/** 편 하나에서 **함정·전문가 노트 콜아웃**을 뽑아 절에 귀속시킨다.
 *
 *  왜 필요한가 (2026-08-17): 32편에 함정 73건·전문가 노트 166건이 쌓여 있는데,
 *  접근 경로가 **날짜 하나**뿐이었다. "그 함정 어느 편이었지"를 찾으려면 27만 자를
 *  훑는 수밖에 없다. 이 저장소가 반복해서 겪은 병이 '적어둔 교훈을 다시 안 읽는 것'이라
 *  (같은 실수를 네 번 반복한 기록이 실제로 있다) 꺼내 보는 자리를 만든다.
 *
 *  ⚠️ **마크다운을 다시 파싱하지 않는다.** slugify의 slugCounts가 전역 카운터라
 *  두 번째로 돌리면 중복 제목의 접미사(-1, -2)가 어긋나 앵커가 조용히 죽는다.
 *  이미 렌더된 html을 훑어 `<h2 id>`로 현재 절을 따라간다 — 링크가 가리킬 id와
 *  **같은 문자열**을 쓰는 게 요점이다.
 *
 *  지시어로 시작하는 항목(그·이·세 번째… 실측 73건 중 21건)은 혼자 두면 뜻이 안 선다.
 *  그때만 앞 문단 한 줄을 같이 넣는다 — 전부에 붙이면 페이지가 두 배가 되고,
 *  안 붙이면 그 21건이 미아가 된다. */
const ANAPHORIC = /^(그|이|저|여기|거기|첫|두|세|네|다섯|또|게다가|그리고|그런데|그래서|반면|하지만)\S*\s/

function extractLessons(post) {
  const out = []
  let sectionId = null
  let sectionTitle = null
  let prevText = ''
  // 블록 단위로 훑는다. 제목이면 현재 절을 갱신하고, 콜아웃이면 그 절에 귀속시킨다.
  const blocks = post.html.split(/\n(?=<)/)
  for (const block of blocks) {
    const h = block.match(/^<h([23]) id="([^"]+)">([\s\S]*?)<\/h\1>/)
    if (h) {
      sectionId = h[2]
      sectionTitle = stripTags(h[3])
      prevText = ''
      continue
    }
    const text = stripTags(block).trim()
    if (!text) continue
    const mark = text.match(/^(⚠️\s*함정|🛠\s*전문가 노트)\s*—?\s*/)
    if (mark) {
      // ⚠️ 종류는 **맨 앞 표식**으로 정한다. `text.includes('함정')`으로 했더니
      // 본문에 '함정'이라는 낱말이 든 전문가 노트 3건이 함정으로 분류됐다
      // (73/166이 76/163이 되어 처음 빌드에서 잡혔다). 이 연재는 '함정'이 주제어라
      // 본문 어디에나 나온다 — 내용으로 종류를 추측하면 안 되는 자리다.
      const kind = mark[1].includes('함정') ? 'trap' : 'note'
      const body = text.slice(mark[0].length).trim()
      out.push({
        date: post.date,
        slug: post.slug,
        sectionId,
        sectionTitle,
        kind,
        text: body,
        // 앞 문장은 지시어로 시작할 때만. 없으면 빈 문자열이고 렌더가 알아서 뺀다.
        lead: ANAPHORIC.test(body) ? prevText.slice(-160) : '',
      })
    } else {
      prevText = text
    }
  }
  return out
}

/** 태그를 걷어낸 평문. 콜아웃 본문에 <strong>·<code>가 섞여 있어서 필요하다.
 *
 *  ⚠️ **숫자 실체참조(&#39;)도 풀어야 한다.** 안 풀면 그 글자가 다시 esc()를 지나
 *  `&amp;#39;`가 되어 화면에 `&#39;`가 그대로 보인다 — 첫 배포에서 라이브에 **1,388곳**
 *  나왔다. marked가 작은따옴표를 그렇게 내보내는데 이 연재는 제목에 '따옴표'를 자주 쓴다.
 *
 *  ⚠️ **&amp;를 마지막에 푼다.** 먼저 풀면 `&amp;lt;`가 `<`가 되어, 글자로 쓴 태그가
 *  진짜 태그로 되살아난다(이 저장소가 원시 HTML을 글자로 취급하려고 애쓰는 이유와 같은 함정). */
const stripTags = (s) =>
  s
    .replace(/<[^>]*>/g, '')
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')

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

  // 본문 색인. data-text(제목+요약+날짜)는 본문의 2.4%뿐이라 "CSP"처럼 본문에만 있는
  // 낱말이 0건으로 나왔다 — 있는 것을 없다고 답하는 검색이었다(2026-08-17 실측:
  // CSP 5편→0건, CloudFront 22편→1건). 그래서 평문 본문을 따로 굽고 여기서 읽는다.
  //
  // **첫 타건 때 한 번만** 받는다: 목록만 보는 사람에겐 한 바이트도 더 안 받게.
  // 도착 전이나 실패했을 땐 지금까지처럼 제목·요약으로만 거른다(fail-soft) —
  // 이 페이지의 성질은 '서버도 번들도 없이 돈다'이고, 색인은 거기 얹는 덤이다.
  var bodyText = null
  var bodyLoading = false
  function loadBody() {
    if (bodyText || bodyLoading || !window.fetch) return
    bodyLoading = true
    fetch('/devlog-search.json')
      .then(function (r) { return r.ok ? r.json() : null })
      .then(function (d) {
        if (!d) return
        bodyText = {}
        for (var i = 0; i < d.length; i++) bodyText[d[i].slug] = d[i].text
        apply() // 도착한 뒤 한 번 더 — 그 사이에 친 검색어에 본문이 반영된다
      })
      .catch(function () {})
  }

  function apply() {
    var q = input.value.trim().toLowerCase()
    var shown = 0
    items.forEach(function (li) {
      var tags = (li.getAttribute('data-tags') || '').split('|')
      var hay = li.getAttribute('data-text') || ''
      if (bodyText) {
        var extra = bodyText[li.getAttribute('data-slug') || '']
        if (extra) hay += ' ' + extra
      }
      var ok =
        (!active || tags.indexOf(active) !== -1) &&
        (!q || hay.indexOf(q) !== -1)
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
  input.addEventListener('input', function () {
    loadBody()
    apply()
  })

  // 들어올 때 ?tag=가 있으면 그 상태로 시작한다.
  var initial = new URLSearchParams(location.search).get('tag')
  if (initial && buttons.some(function (b) { return b.getAttribute('data-tag') === initial })) {
    select(initial)
  }

  filter.hidden = false // 여기까지 왔으면 필터가 실제로 동작한다 — 그때 보여준다
  apply()
})()
`

/** /lessons.html의 검색 필터. devlog-filter.js와 같은 원칙이다 —
 *  목록은 이미 HTML에 다 있고, 이 스크립트는 **줄을 숨기고 보이는 일만** 한다.
 *  그래서 JS가 죽어도 239건은 그대로 읽힌다(필터 UI만 안 보인다).
 *  별도 파일인 이유는 CSP: 인라인 <script>는 차단되고, 차단돼도 화면은 멀쩡해 보인다. */
const LESSONS_FILTER_JS = `// 생성물 — frontend/scripts/gen-static.mjs가 만든다. 직접 고치지 말 것.
(function () {
  var filter = document.getElementById('filter')
  var input = document.getElementById('q')
  var count = document.getElementById('count')
  var empty = document.getElementById('empty')
  if (!filter || !input) return

  var items = Array.prototype.slice.call(document.querySelectorAll('.lesson'))
  var notes = document.querySelector('.notes')

  function apply() {
    var q = input.value.trim().toLowerCase()
    var shown = 0
    items.forEach(function (li) {
      var ok = !q || (li.getAttribute('data-text') || '').indexOf(q) !== -1
      li.hidden = !ok
      if (ok) shown++
    })
    // 검색 중엔 접힌 노트도 펼친다 — 안 그러면 '0건'처럼 보이는데 실은 접혀 있는 것이다.
    if (notes && q) notes.open = true
    count.textContent = q ? shown + '건 (전체 ' + items.length + '건 중)' : ''
    if (empty) empty.hidden = shown !== 0
  }

  input.addEventListener('input', apply)
  filter.hidden = false // 여기까지 왔으면 실제로 동작한다 — 그때 보여준다
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
<!-- 아이콘·manifest. **파일은 원래부터 다 있었는데(favicon.svg·icon-192·manifest.json 전부 200)
     이 정적 판 34장에만 선언이 0개였다** — index.html엔 넷 다 있었다(2026-08-17 실측).
     서버가 평소 꺼져 있어 실제로 읽히는 게 이 34장인데, 거기서만 탭·북마크 아이콘이
     기본 회색이었다. start_url·scope가 둘 다 "/"라 manifest도 여기 넣는 쪽이 맞다. -->
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/icon-192.png">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#863bff">
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
/* 목차. <details>라 접고 펴는 데 스크립트가 필요 없다 — 이 집은 CSP가 인라인을 막아서
   '스크립트 없이 되는 것'을 고르는 게 원칙이다. 기본은 열어둔다(open). */
.toc{margin:0 0 2rem;padding:.9rem 1.1rem;border:1px solid #d2d2d7;border-radius:.75rem;background:#fbfbfd}
.toc>summary{cursor:pointer;font-size:.9rem;font-weight:600;color:#6e6e73}
.toc ul{list-style:none;margin:.75rem 0 0;padding:0}
.toc li{margin:.35rem 0;line-height:1.45}
.toc li.d3{padding-left:1rem;font-size:.9rem}
.toc a{color:inherit;text-decoration:none}
.toc a:hover{color:#0071e3;text-decoration:underline}
.commits{margin:2.5rem 0 0;font-size:.9rem}
.commits>summary{cursor:pointer;color:#6e6e73}
.commits ul{list-style:none;padding:0;margin:.75rem 0 0}
.commits li{padding:.3rem 0;line-height:1.5}
.commit-date{color:#86868b;font-size:.8rem;margin-right:.25rem}
.commits-all{margin:.75rem 0 0;font-size:.85rem}
.logday{margin:2rem 0}
.logday h2{font-size:1.05rem;margin:0 0 .5rem;letter-spacing:0}
.logday-n{color:#86868b;font-weight:400;font-size:.85rem}
.logday-post{margin:0 0 .5rem;font-size:.9rem}
.loglist{list-style:none;padding:0;margin:0}
.loglist li{padding:.25rem 0;line-height:1.5;font-size:.9rem}
.taghubs{font-size:.85rem;color:#6e6e73;margin:0 0 1.25rem;line-height:2}
.taghubs a{color:#6e6e73;text-decoration:none;border-bottom:1px solid #d2d2d7}
.taghubs a:hover{color:#0071e3;border-color:#0071e3}
/* 교훈 색인 */
.lessons{list-style:none;padding:0;margin:1.5rem 0}
.lesson{padding:1rem 0;border-top:1px solid #e8e8ed}
.lesson-src{display:block;font-size:.8rem;color:#6e6e73;text-decoration:none;margin-bottom:.4rem}
.lesson-src:hover{color:#0071e3;text-decoration:underline}
.lesson-lead{margin:0 0 .35rem;font-size:.85rem;color:#86868b;font-style:italic}
.lesson-text{margin:0;line-height:1.65}
.notes{margin:2.5rem 0 0}
.notes>summary{cursor:pointer;font-weight:600;color:#6e6e73}
/* 태그 칩 · 필터 · 관련 글 */
.tags{display:flex;flex-wrap:wrap;gap:.4rem;margin:.5rem 0 1.75rem}
/* 테두리가 #d2d2d7(표·인용구와 같은 값)이면 흰 배경에서 **1.51:1**이다. 본문 구분선은
   장식이라 그래도 되지만 이 칩은 **누르는 것**이라, 경계가 안 보이면 버튼인 줄 모른다
   (WCAG 1.4.11은 UI 컴포넌트 경계에 3:1을 요구한다). #8e8e93 = 3.26:1.
   2026-08-15에 계산으로 재고 고쳤다 — 눈으로는 "회색이네"로 넘어가는 자리다. */
.tag{display:inline-block;padding:.2rem .6rem;border:1px solid #8e8e93;border-radius:999px;
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
/* 라이트와 같은 이유로 테두리를 올린다: #38383a는 검은 배경에서 1.79:1, #636366은 3.51:1.
   선택된 칩은 배경을 **어둡게** 바꾼다 — #0a84ff 위의 흰 글자는 3.65:1로 본문 기준(4.5)에
   못 미친다. #0060df면 5.62:1이고, '파랑 위 흰 글자'라는 모양은 라이트와 그대로 같다
   (글자를 검게 뒤집으면 대비는 되지만 라이트/다크가 서로 다른 물건처럼 보인다). */
.tag{border-color:#636366;color:#a1a1a6}
.tag:hover{border-color:#0a84ff;color:#0a84ff}
.tag[aria-pressed="true"]{background:#0060df;border-color:#0060df;color:#fff}
.filter input{border-color:#38383a}
.filter-count,.filter-empty{color:#a1a1a6}
.related{border-color:#1c1c1e}
.related-h{color:#a1a1a6}
.toc{border-color:#38383a;background:#151517}
.commits>summary,.commit-date,.logday-n{color:#a1a1a6}
.taghubs,.taghubs a{color:#a1a1a6}
.taghubs a{border-color:#48484a}
.lesson{border-color:#1c1c1e}
.lesson-src{color:#a1a1a6}
.lesson-lead{color:#8e8e93}
.notes>summary{color:#a1a1a6}
.toc>summary{color:#a1a1a6}
.toc a:hover{color:#0a84ff}
}
</style>
</head>
<body><main>
<p class="nav"><a href="/">← ${esc(TITLE)}</a> · <a href="/devlog.html">개발일지 전체</a> · <a href="/lessons.html">함정과 교훈</a> · <a href="/keywords.html">용어</a> · <a href="/log.html">커밋 로그</a> · <a href="/rss.xml">RSS</a></p>
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

  // ── 커밋 이력 ────────────────────────────────────────────────────────────
  // 편별 '그날의 커밋'은 **그 편의 날짜부터 다음 편 전날까지**를 묶는다. 하루로 자르면
  // 대부분의 편이 빈 목록이 된다 — 이 연재는 작업한 날 밤에 쓰고 날짜를 소급해 붙이기
  // 때문에, 커밋은 그 앞뒤로 흩어져 있다(실측: 08-11 하루에 20커밋, 08-12엔 5커밋).
  const commits = readCommits()
  const commitsFor = (i) => {
    // posts는 최신순이다. i-1이 더 최신 편, i+1이 더 오래된 편.
    const from = posts[i].date
    const to = i > 0 ? posts[i - 1].date : '9999-99-99'
    return commits.filter((c) => c.date >= from && c.date < to)
  }

  // 태그별 편수 — 허브 페이지를 만들지(2편 이상), 칩을 어디로 걸지 여기서 정한다.
  // **글 페이지보다 먼저 계산해야 한다** — 칩이 이 값을 쓴다.
  const tagCount = new Map()
  for (const p of posts) for (const t of p.tags) tagCount.set(t, (tagCount.get(t) ?? 0) + 1)
  // 파일명에 못 쓰는 글자가 든 태그는 허브를 안 만든다(지금은 없지만, 태그는 사람이 적는 값이다).
  const hubTags = [...tagCount.entries()]
    .filter(([t, n]) => n >= 2 && !/[/\\.]|[\u0000-\u001f]/.test(t))
    .map(([t]) => t)
  // ⚠️ **파일명은 원문(UTF-8), 링크만 인코딩한다.** 처음엔 파일명도 인코딩해서 저장했는데,
  // 그러면 S3 키에 `%EB…`가 **글자 그대로** 들어간다. 브라우저는 `/tag/보안.html`을
  // `%EB%B3%B4…`로 인코딩해 보내고 S3가 그걸 디코딩해 `보안.html`을 찾으므로 서로 어긋난다
  // — 라이브에서 한글 태그 18장이 전부 **403**이었다(영문 `AWS.html`만 200이라 더 헷갈렸다).
  // 2026-08-17 배포 후 실측으로 잡았다.
  const tagFile = (t) => `${t}.html`
  const tagHref = (t) => `/tag/${encodeURIComponent(t)}.html`
  const hasHub = (t) => hubTags.includes(t)


  // **제목이 두 곳에 산다 — 갈라지기 전에 잠근다.**
  //   ① scripts/devlog_posts.py의 POSTS (발행 스크립트가 DB에 넣는 제목, tags.json으로 내보냄)
  //   ② content/devlog/<날짜>.md의 H1 (정적 페이지·RSS·공유 카드가 쓰는 제목)
  // 지금은 32편 전부 일치한다(2026-08-17 실측). 즉 이 가드는 깨진 것을 고치는 게 아니라
  // **아직 안 갈라진 것을 갈라지기 전에 붙잡는다** — 이 저장소가 반복해서 당한 병이
  // '같은 값이 두 벌 살다가 조용히 어긋나는 것'이고, 제목은 어긋나도 두 화면을 나란히
  // 놓고 보기 전엔 아무도 모른다(DB의 글 제목과 아카이브의 제목이 다른 상태).
  // 제목을 고칠 땐 마크다운과 POSTS를 **같이** 고치고 `python scripts/devlog_posts.py`를 돌려라.
  const titleDrift = posts
    .filter((p) => (tagMap[p.date].title ?? '').trim() !== p.title.trim())
    .map((p) => `${p.date}\n       tags.json: ${tagMap[p.date].title}\n       마크다운 H1: ${p.title}`)
  if (titleDrift.length) {
    console.error(`\n❌ 제목이 두 곳에서 다르다 (${titleDrift.length}편):`)
    for (const d of titleDrift) console.error(`     ${d}`)
    console.error('   → 마크다운 H1과 scripts/devlog_posts.py의 POSTS를 맞추고')
    console.error('     `python scripts/devlog_posts.py`로 tags.json을 다시 써라.\n')
    process.exit(1)
  }

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

  // 교훈 색인의 재료를 **렌더보다 먼저** 뽑고 가드한다(GFM 가드와 같은 자리·같은 방식).
  // 앵커가 죽으면 페이지는 멀쩡히 만들어지고 링크만 아무 데도 안 간다 — 조용한 실패다.
  const lessons = posts.flatMap((p) => extractLessons(p))
  const traps = lessons.filter((l) => l.kind === 'trap')
  const notes = lessons.filter((l) => l.kind === 'note')
  {
    const problems = []
    // ⚠️ **'편당 최소 1건'으로 걸면 안 된다.** 실측(2026-08-17) 함정을 가진 편은 32편 중
    // 15편이고 17편은 0건이다 — 초기 편들이 이 표기 관례를 쓰기 전이라 그렇다.
    // 그걸 실패로 세면 빌드가 영영 안 도는 가드가 된다. 그래서 **총량**으로 건다.
    if (traps.length < 60) problems.push(`함정이 ${traps.length}건뿐이다(60 미만) — 추출이 깨졌을 가능성`)
    if (notes.length < 140) problems.push(`전문가 노트가 ${notes.length}건뿐이다(140 미만)`)
    // 절에 안 붙은 항목 = 링크가 갈 곳이 없다
    const orphan = lessons.filter((l) => !l.sectionId)
    if (orphan.length) problems.push(`절에 안 붙은 항목 ${orphan.length}건 (${orphan[0].date})`)
    // 앵커가 그 편 HTML에 실제로 있는가 — 이게 두 번째 조용한 실패다
    const htmlByDate = new Map(posts.map((p) => [p.date, p.html]))
    const dead = lessons.filter((l) => !(htmlByDate.get(l.date) ?? '').includes(`id="${l.sectionId}"`))
    if (dead.length) problems.push(`가리키는 id가 그 편에 없는 항목 ${dead.length}건 (${dead[0]?.date}#${dead[0]?.sectionId})`)
    // 이중 이스케이프 — 첫 배포에서 라이브에 1,388곳 나갔다(`&#39;`가 글자로 보였다).
    // 화면이 깨지지 않고 **글자만 이상해서** 눈으로는 지나치기 쉬운 종류라 여기서 센다.
    const doubled = lessons.filter((l) => /&(amp|lt|gt|quot|#\d)/.test(l.text + l.sectionTitle))
    if (doubled.length) problems.push(`실체참조가 안 풀린 항목 ${doubled.length}건 (${doubled[0].date}: ${doubled[0].sectionTitle.slice(0, 30)})`)
    if (problems.length) {
      console.error('\n❌ 교훈 색인(lessons.html)을 만들 수 없다:')
      for (const p of problems) console.error(`     ${p}`)
      console.error('   → 콜아웃 표기(**⚠️ 함정** / > **🛠 전문가 노트**)가 바뀌었는지 확인하라.\n')
      process.exit(1)
    }
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

  /** 목차. 소제목 id는 **원래부터 붙어 있었는데**(절 단위 딥링크용) 그 id로 가는 링크가
   *  한 개도 없었다 — 실측(2026-08-17) 2026-08-04편은 h2가 21개인데 `href="#`이 0개다.
   *  절 20개·코드블록 35개짜리 편에서 "이 글에 뭐가 있나"를 알 방법이 없었고, 서버가
   *  평소 꺼져 있어 **독자 전원이 보는 판이 이쪽**이다(SPA엔 Toc.tsx가 이미 있다).
   *
   *  소제목이 3개 미만이면 넣지 않는다 — 목차가 본문보다 길면 방해만 된다. */
  const toc = (p) => {
    if (p.headings.length < 3) return ''
    return (
      `<details class="toc" open><summary>목차 (${p.headings.length})</summary><ul>` +
      p.headings
        .map((h) => `<li class="d${h.depth}"><a href="#${h.id}">${esc(h.text)}</a></li>`)
        .join('') +
      `</ul></details>`
    )
  }

  /** 그날의 커밋. 개발일지가 '무엇을 배웠나'라면 이건 '무엇을 건드렸나'다.
   *  둘을 한 화면에 두면 글이 실제 작업과 어떻게 이어지는지가 보인다.
   *  접어둔다 — 20개가 펼쳐져 있으면 본문의 결론을 밀어낸다. */
  const dayCommits = (i) => {
    const cs = commitsFor(i)
    if (!cs.length) return ''
    return (
      // 최신 편은 "그 뒤 지금까지"다 — 다음 편이 아직 없으니 범위의 끝이 열려 있다.
      // 그걸 "이 편 기간"이라고 부르면 오늘 친 커밋이 지난 편의 것처럼 보인다.
      `<details class="commits"><summary>${i === 0 ? `이 편 이후 지금까지의 커밋` : `이 편 기간의 커밋`} ${cs.length}개</summary><ul>` +
      cs
        .map(
          (c) =>
            `<li><code>${esc(c.hash)}</code> <span class="commit-date">${c.date}</span> ${esc(c.subject)}</li>`,
        )
        .join('') +
      `</ul><p class="commits-all"><a href="/log.html">전체 커밋 ${commits.length}개 →</a></p></details>`
    )
  }

  /** 태그 칩. 누르면 아카이브 인덱스가 그 태그로 걸러진 채 열린다(?tag=). */
  const tagChips = (p) =>
    `<p class="tags">` +
    p.tags
      // 허브가 있으면 **주소가 있는 쪽**으로 보낸다. 1편짜리 태그는 허브를 안 만들므로
      // (그 편으로 가는 링크 하나가 전부인 페이지가 된다) 예전처럼 아카이브 필터로 간다.
      .map(
        (t) =>
          `<a class="tag" href="${hasHub(t) ? tagHref(t) : `/devlog.html?tag=${encodeURIComponent(t)}`}">${esc(t)}</a>`,
      )
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
          `<h1>${esc(p.title)}</h1><p class="meta">${p.date}</p>${tagChips(p)}${toc(p)}` +
          `${p.html}${dayCommits(i)}${seriesNav(i)}${relatedNav(i)}`,
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
        `<label class="visually-hidden" for="q">제목·본문 검색</label>` +
        `<input id="q" type="search" placeholder="제목·본문에서 찾기" autocomplete="off">` +
        `<div class="tagbar">${tagbar}</div>` +
        // role=status: 필터링 결과 건수가 스크린리더에도 읽히게 한다. 시각적으로는
        // 목록이 줄어드는 게 보이지만, 안 보이는 사람에게는 아무 일도 안 일어난 것과 같다.
        `<p class="filter-count" id="count" role="status"></p>` +
        `</div>` +
        // JS가 죽으면 위의 태그 버튼(필터)이 통째로 안 보인다. 그때도 주제별로
        // 갈 수 있게 허브 링크를 **HTML에** 둔다 — 이 페이지의 성질이 '서버도 번들도
        // 없이 돈다'인데 태그 탐색만 JS에 매여 있었다.
        `<p class="taghubs">주제별: ` +
        hubTags
          .map((t) => `<a href="${tagHref(t)}">#${esc(t)}</a>`)
          .join(' ') +
        `</p>` +
        `<ul class="list" id="posts">` +
        posts
          .map(
            (p) =>
              // data-slug는 본문 색인(devlog-search.json)과 줄을 잇는 열쇠다.
              `<li data-tags="${esc(p.tags.join('|'))}" data-slug="${esc(p.slug)}" ` +
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

  // 2-A-1) **/infra.html — 이 블로그가 실제로 무엇 위에 서 있나.**
  //
  //   개발일지가 인프라 얘기를 32편 하는데, 정작 "그래서 지금 뭐가 떠 있나"를 보여주는
  //   자리가 없었다. 값은 **AWS에 직접 물어서** 잰다(scripts/infra_snapshot.sh) — 사람이
  //   기억으로 적으면 그 순간부터 낡고, 이 저장소는 그 병을 여러 번 앓았다.
  //
  //   ⚠️ 스냅샷이라 **낡는다**. 빌드가 AWS를 부르지 않는 이유(배포 역할에 describe 권한을
  //   주지 않으려고)는 그 스크립트 주석에 있다. 대신 **언제 잰 값인지 화면에 크게 적는다** —
  //   낡을 수 있는 값을 낡지 않는 척 보여주는 게 이 저장소가 반복해서 만든 사고다.
  const infraPath = join(HERE, '..', '..', 'content', 'infra.json')
  if (existsSync(infraPath)) {
    const inf = JSON.parse(readFileSync(infraPath, 'utf8'))
    const rows = [
      ['컴퓨트', inf.ec2.map((e) => `${e.type} (${e.state}) · ${e.az}`).join(', ') || '없음'],
      ['디스크', inf.volumes.map((v) => `${v.size}GB ${v.type}`).join(', ') || '없음'],
      ['고정 IP(EIP)', `${inf.eips}개 — 0이면 정지 중 과금이 없다는 뜻이다`],
      ['보안 그룹', `${inf.security_groups}개`],
      ['CDN', inf.cloudfront.map((c) => `CloudFront ${c.status} · ${c.http}`).join(', ') || '없음'],
      ['S3 버킷', `${inf.s3_buckets}개 — 정적 사이트·백업·업로드·tfstate`],
      ['Lambda', `${inf.lambda}개 — 엣지 로직은 Lambda@Edge가 아니라 CloudFront Function이다(더 싸다)`],
      ['알람', `${inf.alarms}개 — EC2 상태검사·예산`],
    ]
    writeFileSync(
      join(OUT, 'infra.html'),
      page({
        title: `인프라 실측 — ${TITLE}`,
        description: `이 블로그가 실제로 올라가 있는 AWS 자원. ${inf.measured_at} 실측.`,
        url: `${SITE}/infra.html`,
        body:
          `<h1>인프라 실측</h1>` +
          `<p class="meta"><strong>${inf.measured_at}</strong>에 AWS에 직접 물어본 값 · ${inf.region} · 이 페이지는 서버 없이 동작합니다</p>` +
          `<table><thead><tr><th>항목</th><th>실측</th></tr></thead><tbody>` +
          rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('') +
          `</tbody></table>` +
          `<p>이 표는 사람이 적은 게 아니라 <code>scripts/infra_snapshot.sh</code>가 잰 것이다. ` +
          `그래도 <strong>스냅샷이라 낡는다</strong> — 인프라를 바꾼 날 다시 재서 커밋한다. ` +
          `무엇 때문에 이렇게 생겼는지는 <a href="/devlog.html">개발일지</a>와 ` +
          `<a href="/lessons.html">함정과 교훈</a>에 있다.</p>` +
          `<p class="meta"><a href="/map.html">사이트가 두 갈래로 사는 구조 →</a></p>`,
      }),
    )
  }

  // 2-A0) **/map.html — 이 사이트가 두 갈래로 산다는 것을 한 장으로.**
  //
  //   이 블로그의 가장 특이한 성질은 "서버가 평소 꺼져 있는데도 블로그로 기능한다"인데,
  //   그걸 알려면 글 몇 편을 읽어야 했다. 방문자가 절전 안내를 보고 "고장인가?" 하는
  //   자리이기도 하다(오늘 상태 페이지 톤을 고친 것과 같은 뿌리).
  //
  //   **인라인 SVG로 그린다** — 이미지 파일이면 다크모드에서 안 맞고, 스크립트를 쓰면
  //   CSP가 막는다. currentColor를 쓰면 두 테마에서 그대로 산다.
  const alwaysAlive = [
    `개발일지 ${posts.length}편 (본문 전체)`,
    '아카이브 · 제목/본문 검색 · 태그 허브',
    '함정과 교훈 · 용어 색인 · 커밋 로그',
    'RSS · sitemap · 소개',
  ]
  const serverOnly = ['로그인 · 계정', '댓글 쓰기/읽기', '글쓰기 · 이미지 업로드', '구독 · 새 글 알림', '관리자 · AI 초안']
  const row = (t, i, x) =>
    `<text x="${x}" y="${104 + i * 26}" font-size="13" fill="currentColor" opacity="0.85">· ${esc(t)}</text>`
  writeFileSync(
    join(OUT, 'map.html'),
    page({
      title: `사이트 구조 — ${TITLE}`,
      description: '이 블로그는 두 갈래로 산다 — 서버 없이 항상 열리는 쪽과, 서버를 켠 날만 도는 쪽.',
      url: `${SITE}/map.html`,
      body:
        `<h1>이 사이트는 두 갈래로 산다</h1>` +
        `<p class="meta">비용을 아끼려고 서버(EC2)를 평소 꺼둔다. 그래서 기능이 두 층으로 갈린다.</p>` +
        `<svg viewBox="0 0 720 300" role="img" aria-labelledby="map-t" style="width:100%;height:auto;color:inherit">` +
        `<title id="map-t">서버 없이 항상 열리는 경로와, 서버를 켠 날만 도는 경로</title>` +
        `<rect x="8" y="40" width="340" height="240" rx="14" fill="none" stroke="currentColor" opacity="0.25"/>` +
        `<rect x="372" y="40" width="340" height="240" rx="14" fill="none" stroke="currentColor" opacity="0.25" stroke-dasharray="6 5"/>` +
        `<text x="24" y="26" font-size="15" font-weight="600" fill="currentColor">항상 열린다 — S3 + CloudFront</text>` +
        `<text x="388" y="26" font-size="15" font-weight="600" fill="currentColor" opacity="0.75">서버를 켠 날만 — EC2</text>` +
        `<text x="24" y="66" font-size="12" fill="currentColor" opacity="0.6">빌드 때 미리 만들어 둔 정적 파일</text>` +
        `<text x="388" y="66" font-size="12" fill="currentColor" opacity="0.6">FastAPI + PostgreSQL (평소 정지)</text>` +
        alwaysAlive.map((t, i) => row(t, i, 24)).join('') +
        serverOnly.map((t, i) => row(t, i, 388)).join('') +
        `</svg>` +
        `<p>왼쪽은 <strong>지금 이 순간에도</strong> 열린다 — 지금 읽고 있는 이 페이지가 그쪽이다. ` +
        `오른쪽은 운영자가 서버를 켠 날에만 돈다. 꺼져 있을 때 그쪽 화면은 고장이 아니라 ` +
        `<a href="/status">절전</a>이라고 말한다.</p>` +
        `<p class="meta">읽는 데는 서버가 필요 없다: ` +
        `<a href="/devlog.html">개발일지 ${posts.length}편</a> · ` +
        `<a href="/lessons.html">함정과 교훈</a> · <a href="/keywords.html">용어</a> · <a href="/log.html">커밋</a></p>`,
    }),
  )

  // 2-A1) **용어 색인 /k/<용어>.html — 도구 이름으로 들어오는 길.**
  //
  //   이 연재는 제목이 서술형 한국어라("…가 아니었다") 도구·개념 이름이 제목에 거의 없다.
  //   그런데 사람이 찾을 때 치는 말은 정확히 그쪽이다(오늘 본문 검색을 붙인 것도 같은 이유).
  //   검색은 '치는 사람'을 위한 것이고, 이 페이지들은 **검색엔진과 링크를 위한 것**이다 —
  //   "이 블로그에서 CloudFront 얘기가 나온 편들"에 해당하는 주소가 생긴다.
  //
  //   용어는 **손으로 고른다.** 본문에서 자동 추출해봤더니 api/API/posts/env 같은 잡음이
  //   섞였다(2026-08-17 실측 53종). 자동화가 값을 못 하는 자리는 표가 낫다.
  //   ⚠️ 파일명은 ASCII 슬러그다 — 한글 파일명이 라이브에서 403이 됐던 그 함정을 아예 피한다.
  const TERMS = [
    { slug: 'cloudfront', name: 'CloudFront', alias: ['CloudFront'] },
    { slug: 'ec2', name: 'EC2', alias: ['EC2'] },
    { slug: 's3', name: 'S3', alias: ['S3'] },
    { slug: 'rds', name: 'RDS', alias: ['RDS'] },
    { slug: 'ecs', name: 'ECS', alias: ['ECS', 'Fargate'] },
    { slug: 'terraform', name: 'Terraform', alias: ['terraform', 'Terraform'] },
    { slug: 'docker', name: 'Docker', alias: ['Docker', 'docker compose', 'Dockerfile'] },
    { slug: 'alembic', name: 'Alembic (마이그레이션)', alias: ['alembic', 'Alembic'] },
    { slug: 'postgres', name: 'PostgreSQL', alias: ['PostgreSQL', 'postgres', 'psql'] },
    { slug: 'fastapi', name: 'FastAPI', alias: ['FastAPI'] },
    { slug: 'react', name: 'React', alias: ['React'] },
    { slug: 'vite', name: 'Vite', alias: ['Vite', 'vite'] },
    { slug: 'pytest', name: 'pytest', alias: ['pytest'] },
    { slug: 'vitest', name: 'Vitest', alias: ['vitest', 'Vitest'] },
    { slug: 'github-actions', name: 'GitHub Actions', alias: ['GitHub Actions', 'Actions', 'workflow_dispatch'] },
    { slug: 'csp', name: 'CSP (콘텐츠 보안 정책)', alias: ['CSP'] },
    { slug: 'ses', name: 'SES (메일)', alias: ['SES'] },
    { slug: 'sns', name: 'SNS (알림)', alias: ['SNS'] },
    { slug: 'cloudwatch', name: 'CloudWatch', alias: ['CloudWatch'] },
    { slug: 'iam', name: 'IAM', alias: ['IAM'] },
    { slug: 'waf', name: 'WAF', alias: ['WAF'] },
    { slug: 'jwt', name: 'JWT (토큰)', alias: ['JWT'] },
    { slug: 'byok', name: 'BYOK (내 키로 AI)', alias: ['BYOK'] },
    { slug: 'web-push', name: 'Web Push', alias: ['Web Push', 'VAPID', '웹 푸시'] },
    { slug: 'prompt-injection', name: '프롬프트 인젝션', alias: ['프롬프트 인젝션'] },
    { slug: 'ssrf', name: 'SSRF', alias: ['SSRF'] },
    { slug: 'xss', name: 'XSS', alias: ['XSS'] },
    { slug: 'backup', name: '백업·복원', alias: ['pg_dump', '복원 훈련', '백업'] },
    { slug: 'ratelimit', name: '레이트리밋', alias: ['레이트리밋', 'slowapi', '429'] },
    { slug: 'oidc', name: 'OIDC (키 없는 배포)', alias: ['OIDC'] },
  ]

  // 용어가 나오는 편 + 그 편에서 처음 나온 문장 한 줄(맥락이 없으면 목록이 이름의 나열이다)
  const stripCodeFences = (t) => t.replace(/```[\s\S]*?```/g, ' ')
  const termHits = TERMS.map((t) => {
    const hits = []
    for (const p of posts) {
      const prose = stripCodeFences(p.body)
      if (!t.alias.some((a) => prose.includes(a))) continue
      const sentence =
        prose
          .split(/\n+/)
          .map((l) => l.trim())
          .filter((l) => l && !l.startsWith('#') && !l.startsWith('|') && t.alias.some((a) => l.includes(a)))
          .map((l) => l.replace(/[*`>#[\]]/g, '').replace(/\s+/g, ' ').trim())
          .find((l) => l.length >= 30) ?? ''
      hits.push({ post: p, sentence: sentence.slice(0, 180) })
    }
    return { ...t, hits }
  }).filter((t) => t.hits.length >= 3) // 2편 이하는 페이지를 만들 값이 없다(태그 허브와 같은 규칙)

  mkdirSync(join(OUT, 'k'), { recursive: true })
  for (const t of termHits) {
    writeFileSync(
      join(OUT, 'k', `${t.slug}.html`),
      page({
        title: `${t.name} — ${TITLE}`,
        description: `'${t.name}'이(가) 나오는 개발일지 ${t.hits.length}편.`,
        url: `${SITE}/k/${t.slug}.html`,
        body:
          `<h1>${esc(t.name)}</h1>` +
          `<p class="meta">개발일지 ${t.hits.length}편에 나옵니다 · 이 페이지는 서버 없이 동작합니다</p>` +
          `<ul class="list">` +
          t.hits
            .map(
              (h) =>
                `<li><a href="/${h.post.slug}">${esc(h.post.title)}</a>` +
                `<p>${h.post.date}${h.sentence ? ` — ${esc(h.sentence)}` : ''}</p></li>`,
            )
            .join('') +
          `</ul>` +
          `<p class="meta"><a href="/keywords.html">← 용어 전체</a> · <a href="/devlog.html">개발일지 전체</a></p>`,
      }),
    )
  }

  // 용어 색인 목차
  if (termHits.length) {
    writeFileSync(
      join(OUT, 'keywords.html'),
      page({
        title: `용어 색인 — ${TITLE}`,
        description: `이 블로그에 나오는 도구·개념 ${termHits.length}가지. 각 용어가 나오는 편으로 갑니다.`,
        url: `${SITE}/keywords.html`,
        body:
          `<h1>용어 색인</h1><p class="meta">${termHits.length}가지 · 이 페이지는 서버 없이 동작합니다</p>` +
          `<ul class="list">` +
          termHits
            .sort((a, b) => b.hits.length - a.hits.length)
            .map(
              (t) =>
                `<li><a href="/k/${t.slug}.html">${esc(t.name)}</a> <span class="logday-n">${t.hits.length}편</span></li>`,
            )
            .join('') +
          `</ul>`,
      }),
    )
  }

  // 2-A2) **/log.html — 커밋 315개를 두 번째 연재로 읽는다.**
  //
  //   개발일지가 '그날 무엇을 배웠나'라면 커밋 제목은 '그날 무엇을 건드렸나'다. 이 저장소는
  //   커밋 제목을 문장으로 쓰는 관례라(“…가 아니었다”, “…에서만 빨간불이었다”) 그 자체로
  //   읽힌다. 그런데 웹에서 볼 자리가 없었다 — GitHub에 가야 한다.
  //
  //   날짜별로 묶고, 개발일지가 있는 날은 그 편으로 링크를 건다(양방향: 편 → 커밋은
  //   dayCommits, 커밋 → 편은 여기). 서버 없이 도는 정적 페이지다.
  if (commits.length) {
    const byDate = new Map()
    for (const c of commits) {
      if (!byDate.has(c.date)) byDate.set(c.date, [])
      byDate.get(c.date).push(c)
    }
    const postByDate = new Map(posts.map((p) => [p.date, p]))
    const days = [...byDate.entries()] // 이미 최신순(git log 순서)
    writeFileSync(
      join(OUT, 'log.html'),
      page({
        title: `커밋 로그 — ${TITLE}`,
        description: `이 블로그를 만든 커밋 ${commits.length}개. 개발일지 ${posts.length}편과 날짜로 이어집니다.`,
        url: `${SITE}/log.html`,
        body:
          `<h1>커밋 로그</h1>` +
          `<p class="meta">${commits.length}개 · ${days[days.length - 1][0]} ~ ${days[0][0]} · 이 페이지는 서버 없이 동작합니다</p>` +
          days
            .map(([date, cs]) => {
              const post = postByDate.get(date)
              return (
                `<div class="logday"><h2 id="d${date}">${date} <span class="logday-n">${cs.length}개</span></h2>` +
                (post ? `<p class="logday-post">📝 <a href="/${post.slug}">${esc(post.title)}</a></p>` : '') +
                `<ul class="loglist">` +
                cs
                  .map((c) => `<li><code>${esc(c.hash)}</code> ${esc(c.subject)}</li>`)
                  .join('') +
                `</ul></div>`
              )
            })
            .join(''),
      }),
    )
  }

  // 2-B) **태그 허브 /tag/<이름>.html** — `?tag=`는 주소가 아니라 상태였다.
  //
  //   태그 칩은 `/devlog.html?tag=보안`으로 갔는데, 쿼리는 **정적 파일 하나를 가리키지
  //   않는다**: 크롤러에겐 devlog.html 한 장이고(그래서 sitemap에도 못 올린다),
  //   JS가 죽으면 필터가 안 걸려 전체 목록이 나온다. 즉 "보안 얘기 모아 보기"에
  //   해당하는 **주소가 없었다.**
  //
  //   2편 이상인 태그만 만든다 — 실측(2026-08-17) 41종 중 19종이고, 나머지 22종은
  //   1편짜리라 페이지를 만들어봐야 그 편으로 가는 링크 하나가 전부다(검색엔진에는
  //   '내용 없는 페이지'가 늘어나는 쪽이 손해다). 1편짜리 칩은 `?tag=`로 그대로 둔다.
  //
  //   ⚠️ 파일명은 **인코딩**한다(태그가 한글이다). 링크도 같은 함수로 만들어야
  //   파일과 링크가 어긋나지 않는다.
  // 파일명에 %가 들어가면 위 함정을 다시 밟은 것이다(인코딩된 이름으로 저장한 상태).
  // 화면상 아무 증상이 없고 **라이브에서만 403**이라 여기서 센다.
  const encodedNames = hubTags.filter((t) => tagFile(t).includes('%'))
  if (encodedNames.length) {
    console.error(`\n❌ 태그 허브 파일명이 인코딩돼 있다: ${encodedNames[0]}`)
    console.error('   → 파일명은 원문(UTF-8), 링크만 encodeURIComponent. 라이브에서 403이 된다.\n')
    process.exit(1)
  }

  mkdirSync(join(OUT, 'tag'), { recursive: true })
  for (const t of hubTags) {
    const inTag = posts.filter((p) => p.tags.includes(t))
    writeFileSync(
      join(OUT, 'tag', tagFile(t)),
      page({
        title: `#${t} — ${TITLE}`,
        description: `'${t}' 태그가 붙은 개발일지 ${inTag.length}편.`,
        url: `${SITE}${tagHref(t)}`,
        body:
          `<h1>#${esc(t)}</h1><p class="meta">${inTag.length}편 · 이 페이지는 서버 없이 동작합니다</p>` +
          `<ul class="list">` +
          inTag
            .map(
              (p) =>
                `<li><a href="/${p.slug}">${esc(p.title)}</a>` +
                `<p>${p.date}${p.summary ? ` — ${esc(p.summary)}` : ''}</p></li>`,
            )
            .join('') +
          `</ul>` +
          `<p class="meta"><a href="/devlog.html">← 개발일지 전체 ${posts.length}편</a></p>`,
      }),
    )
  }

  // 2-C) **교훈 색인 /lessons.html** — 날짜가 아닌 축으로 27만 자를 한 번 꺼낸다.
  //
  //   32편에 함정 73건·전문가 노트 166건이 쌓여 있는데 접근 경로가 날짜뿐이었다.
  //   이 저장소가 반복해서 겪은 병이 '적어둔 교훈을 다시 안 읽는 것'이고(같은 실수를
  //   네 번 반복한 기록이 실제로 있다), 그건 기억력 문제가 아니라 **꺼내 보는 자리가
  //   없어서**다. 링크는 편별 정적 페이지의 **절 앵커**로 건다 — 서버 없이 열린다.
  //
  //   함정이 본문, 전문가 노트는 <details>로 접는다. 239건을 한 번에 펼치면
  //   '읽을 것'이 아니라 '스크롤할 것'이 된다.
  const lessonItem = (l) =>
    `<li class="lesson" data-text="${esc(`${l.text} ${l.sectionTitle} ${l.date}`.toLowerCase())}">` +
    `<a class="lesson-src" href="/${l.slug}#${l.sectionId}">${l.date} · ${esc(l.sectionTitle)}</a>` +
    (l.lead ? `<p class="lesson-lead">…${esc(l.lead)}</p>` : '') +
    `<p class="lesson-text">${esc(l.text)}</p></li>`

  writeFileSync(
    join(OUT, 'lessons.html'),
    page({
      title: `함정과 교훈 — ${TITLE}`,
      description: `개발일지 ${posts.length}편에서 뽑은 함정 ${traps.length}건과 전문가 노트 ${notes.length}건. 서버 없이 읽을 수 있습니다.`,
      url: `${SITE}/lessons.html`,
      script: '/lessons-filter.js',
      body:
        `<h1>함정과 교훈</h1>` +
        `<p class="meta">개발일지 ${posts.length}편에서 뽑은 ${traps.length + notes.length}건 · 각 항목은 그 대목으로 바로 갑니다</p>` +
        `<div class="filter" id="filter" hidden>` +
        `<label class="visually-hidden" for="q">교훈 검색</label>` +
        `<input id="q" type="search" placeholder="함정·교훈에서 찾기" autocomplete="off">` +
        `<p class="filter-count" id="count" role="status"></p>` +
        `</div>` +
        `<h2 id="traps">함정 ${traps.length}건</h2>` +
        `<ul class="lessons" id="traps-list">${traps.map(lessonItem).join('')}</ul>` +
        `<details class="notes"><summary>전문가 노트 ${notes.length}건 — 펼치기</summary>` +
        `<ul class="lessons" id="notes-list">${notes.map(lessonItem).join('')}</ul></details>` +
        `<p class="filter-empty" id="empty" hidden>찾는 것이 없다. 검색어를 지워봐.</p>`,
    }),
  )
  writeFileSync(join(OUT, 'lessons-filter.js'), LESSONS_FILTER_JS)

  // (2의 짝 2) **본문 색인.** 아카이브 검색이 보던 data-text는 제목+요약+날짜뿐이라
  //   본문의 2.4%였다 — 제목이 서술형 한국어라 도구·에러 이름(CSP·pytest·CloudFront)이
  //   거의 안 들어가는데, 독자가 치는 말은 정확히 그쪽이다. 그래서 평문 본문을 따로 낸다.
  //
  //   목록 HTML에 그냥 넣지 않는 이유: devlog.html이 43 KB에서 300 KB대로 불어나
  //   **목록만 보는 사람에게도** 그 무게가 간다. 별도 파일이면 검색을 실제로 친 사람만 받고,
  //   못 받아도 필터는 지금까지처럼 제목·요약으로 돈다(FILTER_JS의 fail-soft 주석 참고).
  //
  //   마크다운 기호만 걷어낸다 — 코드블록 안의 명령·에러 문구는 **남긴다**. 그게 이 연재에서
  //   가장 자주 찾게 되는 말이고, 지우면 이 작업의 목적이 절반 사라진다.
  const searchIndex = posts.map((p) => ({
    slug: p.slug,
    text: p.body
      .replace(/```/g, ' ')
      .replace(/[#*`>_[\]|]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase(),
  }))
  writeFileSync(join(OUT, 'devlog-search.json'), JSON.stringify(searchIndex))

  // 2-B) 정적 목록 JSON — **화면이 빈 채로 뜨는 문제를 서버 없이 고친다.**
  //
  //   ⚠️ 이름과 달리 지금 이걸 읽는 건 랜딩이 아니다. 2026-08-17에 사용자 결정으로
  //   랜딩(/)의 '최근 개발일지' 섹션을 걷어냈다(첫 화면은 서비스 입구만 둔다).
  //   현재 소비처는 **/blog(절전 중 목록)**와 **글 상세(관련 글)** 둘이다.
  //   즉 이 산출물은 여전히 필요하다 — 지우면 서버 꺼진 날 /blog가 다시 빈다.
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
    // 교훈 색인도 서버 없이 열리는 정적 페이지다. 32편에서 뽑은 239건이 한 장에 있어
    // 색인 가치가 개별 편 못지않다.
    { loc: `${SITE}/lessons.html`, pri: '0.9' },
    // 태그 허브. `?tag=`는 쿼리라 sitemap에 올릴 수 없었다 — 주소가 생기니 올린다.
    ...(commits.length ? [{ loc: `${SITE}/log.html`, pri: '0.6' }] : []),
    { loc: `${SITE}/map.html`, pri: '0.7' },
    ...(existsSync(infraPath) ? [{ loc: `${SITE}/infra.html`, pri: '0.5' }] : []),
    ...(termHits.length ? [{ loc: `${SITE}/keywords.html`, pri: '0.7' }] : []),
    ...termHits.map((t) => ({ loc: `${SITE}/k/${t.slug}.html`, pri: '0.6' })),
    ...hubTags.map((t) => ({ loc: `${SITE}${tagHref(t)}`, pri: '0.6' })),
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
      `lessons.html(함정 ${traps.length}·노트 ${notes.length}) + devlog-search.json + ` +
      `태그 허브 ${hubTags.length}장 + 용어 ${termHits.length}종 + log.html(커밋 ${commits.length}) + ` +
      `rss.xml(최근 ${feedPosts.length}편) + sitemap.xml + robots.txt`,
  )
}

main()
