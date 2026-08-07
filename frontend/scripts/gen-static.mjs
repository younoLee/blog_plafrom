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
import { marked } from 'marked'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..', '..', 'content', 'devlog')
const OUT = join(HERE, '..', 'dist')
const SITE = process.env.VITE_SITE_URL ?? 'https://d2j66m9udyg9yq.cloudfront.net'
const TITLE = 'DEV 블로그'
const DESC = '개발과 인프라를 기록하는 블로그. 글 작성·구독·AI 초안까지 직접 만든 풀스택 사이트.'

const esc = (s) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

/** 마크다운 한 편 읽기. 제목은 첫 H1, 날짜는 파일명 — 프론트매터가 없어서다. */
function readPost(file) {
  const date = file.replace(/\.md$/, '')
  const raw = readFileSync(join(SRC, file), 'utf8')
  const h1 = raw.match(/^#\s+(.+)$/m)
  // H1은 본문에서 뺀다. 아래 템플릿이 <h1>을 따로 넣으므로 남기면 제목이 두 번 나온다.
  const body = raw.replace(/^#\s+.+$/m, '').trim()
  return {
    date,
    slug: `devlog/${date}.html`,
    title: h1 ? h1[1].trim() : date,
    // 요약: 첫 인용문(> …)이 대개 그 편의 한 줄 소개라 그걸 쓰고, 없으면 첫 문단.
    summary: (body.match(/^>\s*(.+)$/m)?.[1] ?? body.split('\n\n')[0] ?? '')
      .replace(/[#*`>_]/g, '')
      .slice(0, 200)
      .trim(),
    html: marked.parse(body),
  }
}

const page = ({ title, description, url, body, article }) => `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
<link rel="canonical" href="${url}">
<link rel="alternate" type="application/rss+xml" title="${esc(TITLE)}" href="${SITE}/rss.xml">
<meta property="og:type" content="${article ? 'article' : 'website'}">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(description)}">
<meta property="og:url" content="${url}">
<meta property="og:image" content="${SITE}/og-image.png">
<meta property="og:locale" content="ko_KR">
<meta name="twitter:card" content="summary_large_image">
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
.meta{color:#86868b;font-size:.9rem}
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
}
</style>
</head>
<body><main>
<p class="nav"><a href="/">← ${esc(TITLE)}</a> · <a href="/devlog.html">개발일지 전체</a> · <a href="/rss.xml">RSS</a></p>
${body}
</main></body>
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

  mkdirSync(join(OUT, 'devlog'), { recursive: true })

  // 1) 편별 정적 페이지 — 크롤러와 사람 모두 서버 없이 전문을 읽는다.
  //    SPA 라우트(/blog/posts/{id})와 달리 여기엔 편마다 제 OG 태그가 붙는다.
  for (const p of posts) {
    writeFileSync(
      join(OUT, 'devlog', `${p.date}.html`),
      page({
        title: `${p.title} — ${TITLE}`,
        description: p.summary || DESC,
        url: `${SITE}/${p.slug}`,
        article: true,
        body: `<h1>${esc(p.title)}</h1><p class="meta">${p.date}</p>${p.html}`,
      }),
    )
  }

  // 2) 아카이브 인덱스. /devlog/ 가 아니라 /devlog.html 인 이유는 위 주석 참고.
  writeFileSync(
    join(OUT, 'devlog.html'),
    page({
      title: `개발일지 — ${TITLE}`,
      description: `개발일지 ${posts.length}편. 서버 없이도 읽을 수 있습니다.`,
      url: `${SITE}/devlog.html`,
      body:
        `<h1>개발일지</h1><p class="meta">${posts.length}편 · 이 페이지는 서버 없이 동작합니다</p><ul class="list">` +
        posts
          .map(
            (p) =>
              `<li><a href="/${p.slug}">${esc(p.title)}</a><p>${p.date}${p.summary ? ` — ${esc(p.summary)}` : ''}</p></li>`,
          )
          .join('') +
        '</ul>',
    }),
  )

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
<content:encoded><![CDATA[${p.html.replace(/]]>/g, ']]&gt;')}]]></content:encoded>
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
    `  정적 산출물: 개발일지 ${posts.length}편 + devlog.html + ` +
      `rss.xml(최근 ${feedPosts.length}편) + sitemap.xml + robots.txt`,
  )
}

main()
