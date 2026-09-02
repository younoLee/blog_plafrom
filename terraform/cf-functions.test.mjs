// CloudFront Function 테스트 — `node --test terraform/`
//
// **왜 이게 필요한가.** spa-routing-function.js는 이 사이트의 모든 정적 요청이
// 지나가는 한 자리에서 "S3로 보낼지 / index.html로 바꿀지 / 404를 만들지"를 정한다.
// 여기가 틀리면 증상이 '사이트 전체가 404' 또는 '봇 스캔에 원시 XML 노출'인데,
// 지금까지 이 파일을 검사하는 것은 아무것도 없었다 — terraform validate는 문법만 보고,
// 배포되면 그때부터 라이브다.
//
// 함수는 CloudFront 런타임에서 도므로 import 할 수 없다(export가 없다).
// 소스를 읽어 `handler`를 꺼내 부른다 — 실제로 배포되는 그 텍스트를 검사하는 셈이다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))

function load(file) {
  const src = readFileSync(join(HERE, file), 'utf8')
  return new Function(`${src}; return handler;`)()
}

const spa = load('spa-routing-function.js')
const call = (uri) => spa({ request: { uri, headers: {} } })

test('확장자 없는 경로는 SPA 딥링크 → /index.html', () => {
  for (const uri of ['/nope', '/', '/blog/posts/48', '/login', '/settings']) {
    assert.equal(call(uri).uri, '/index.html', uri)
  }
})

test('실제 산출물 확장자는 그대로 S3로 간다', () => {
  // dist가 내는 것 + 업로드(png·jpg). 하나라도 여기서 막히면 그 자산이 사이트에서
  // 통째로 사라진다 — 이 목록이 이 테스트의 요점이다.
  const assets = [
    '/index-abc123.js',
    '/index-abc123.css',
    '/devlog.html',
    '/devlog/2026-08-14.html',
    '/about.html',
    '/about.md',
    '/devlog-index.json',
    '/devlog-filter.js',
    '/manifest.json',
    '/rss.xml',
    '/sitemap.xml',
    '/robots.txt',
    '/favicon.svg',
    '/icon-192.png',
    '/og-image.png',
    '/sw.js',
    '/uploads/photo.jpg',
    '/uploads/photo.jpeg',
    '/uploads/shot.png',
  ]
  for (const uri of assets) {
    const r = call(uri)
    assert.equal(r.statusCode, undefined, `${uri} 가 404로 막혔다`)
    assert.equal(r.uri, uri)
  }
})

test('대문자 확장자도 통과한다 (S3 키는 대소문자를 가린다)', () => {
  assert.equal(call('/UPLOADS/PHOTO.JPG').uri, '/UPLOADS/PHOTO.JPG')
})

test('이 사이트가 낼 리 없는 확장자는 엣지에서 404를 만들어 돌려준다', () => {
  // 2026-08-15 실측: 이것들이 전부 S3의 원시 XML(403 AccessDenied)을 받고 있었다.
  for (const uri of ['/nope.bar', '/wp-login.php', '/.env', '/x.php7', '/admin.aspx']) {
    const r = call(uri)
    assert.equal(r.statusCode, 404, uri)
    assert.match(r.headers['content-type'].value, /text\/html/)
    assert.match(r.body, /그런 주소는 없어/)
    // 원시 XML의 흔적이 남아 있으면 안 된다
    assert.doesNotMatch(r.body, /AccessDenied/)
  }
})

test('엣지 응답에 인라인 스크립트가 없다 (CSP script-src self)', () => {
  const r = call('/nope.bar')
  assert.doesNotMatch(r.body, /<script/i)
  // 인라인 이벤트 핸들러(onload=·onclick=…). 앞의 \s가 없으면 `content=`의
  // "ontent="에 걸려 오탐이 난다 — 처음 짤 때 실제로 그랬다.
  assert.doesNotMatch(r.body, /\son[a-z]+\s*=/i)
})

test('생성 응답 본문이 CloudFront Function 상한(40KB) 안이다', () => {
  assert.ok(Buffer.byteLength(call('/nope.bar').body) < 40 * 1024)
})

// ── reqsize-function.js ─────────────────────────────────────────────────────
// 2026-09-02 추가. 이 함수는 경로마다 다른 상한을 고르는데, 그 판정이 틀리면 증상이
// 둘 중 하나다: (a) 업로드가 413으로 전부 죽거나, (b) /api/auth/login 같은 무인증
// 경로가 6MB를 도로 얻어 t2.micro 메모리 고갈 경로가 열린다. 둘 다 배포 뒤에야 보인다.
const reqsize = load('reqsize-function.js')
const send = (uri, contentLength) =>
  reqsize({
    request: {
      uri,
      headers:
        contentLength === undefined ? {} : { 'content-length': { value: String(contentLength) } },
    },
  })
const blocked = (r) => r.statusCode === 413

test('업로드 경로는 6MB까지 통과하고 1바이트만 넘어도 413', () => {
  // 경계값 그 자체. 6291456 = 6 * 1024 * 1024.
  assert.equal(blocked(send('/api/upload', 6291456)), false)
  assert.equal(blocked(send('/api/upload', 6291457)), true)
  assert.equal(send('/api/upload', 6291457).statusDescription, 'Payload Too Large')
})

test('업로드가 아닌 경로의 상한은 512KB다', () => {
  // 6MB는 이미지 업로드 하나 때문에 잡은 값이라 무인증 JSON 경로가 나눠 가지면 안 된다.
  assert.equal(blocked(send('/api/auth/login', 524288)), false)
  assert.equal(blocked(send('/api/auth/login', 524289)), true)
  assert.equal(blocked(send('/api/posts', 6291456)), true, '/api/posts가 6MB를 얻고 있다')
})

test('후행 슬래시와 쿼리스트링은 업로드 판정을 흔들지 않는다', () => {
  for (const uri of ['/api/upload/', '/api/upload//', '/api/upload?x=1', '/api/upload/?x=1']) {
    assert.equal(blocked(send(uri, 6291456)), false, uri)
  }
})

test('/api/uploadsomething 은 큰 상한을 얻지 못한다', () => {
  // 접두사 매칭으로 짰다면 여기서 통과해버린다 — 이 테스트가 그걸 잡는 자리다.
  for (const uri of ['/api/uploadsomething', '/api/uploads', '/api/upload-x', '/api/uploadz/1']) {
    assert.equal(blocked(send(uri, 6291456)), true, uri)
    assert.equal(blocked(send(uri, 524288)), false, uri)
  }
})

test('content-length 헤더가 없으면 통과한다 (본문 없는 GET)', () => {
  const r = send('/api/posts', undefined)
  assert.equal(r.statusCode, undefined)
  assert.equal(r.uri, '/api/posts', '요청 객체를 그대로 돌려줘야 한다')
})

test('숫자가 아닌 content-length는 엣지에서 막지 않고 앱으로 넘긴다', () => {
  // 의도한 선택이다. 엣지는 헤더가 말하는 크기만 보는 보조 방어이고, 실제 바이트는
  // 앱의 BodySizeLimitMiddleware가 스트림을 세면서 끊는다(chunked 우회도 거기서 막힌다).
  // 여기서 413을 내면 엣지가 앱보다 엄격해져 정책이 갈린다.
  for (const bad of ['abc', '', 'NaN']) {
    const r = send('/api/posts', bad)
    assert.equal(r.statusCode, undefined, `content-length: ${JSON.stringify(bad)}`)
    assert.equal(r.uri, '/api/posts')
  }
})

test('CSP 함수는 script-src에 unsafe-inline을 넣지 않는다', () => {
  // 이게 뚫리면 index.html·devlog.html이 인라인 스크립트를 쓰기 시작하고,
  // 그 순간 이 저장소가 두 번 밟은 함정(폰트 스왑·아카이브 필터)이 되살아난다.
  const csp = load('csp-function.js')
  const res = csp({ response: { headers: {} } })
  const value = res.headers['content-security-policy'].value
  const scriptSrc = value.split(';').find((d) => d.trim().startsWith('script-src'))
  assert.ok(scriptSrc, 'script-src 지시문이 없다')
  assert.doesNotMatch(scriptSrc, /unsafe-inline|unsafe-eval/)
})
