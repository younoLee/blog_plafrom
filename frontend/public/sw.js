// 서비스워커 — 푸시 알림 + **정적 문서 오프라인 읽기**.
//
// 2026-08-17까지 이 파일은 "일부러 캐싱을 하지 않는다"고 적혀 있었다. 그 주석의 걱정은
// 정확했다 — '캐시된 옛 글 목록'이 절전 안내를 덮으면 절전이 고장으로 보인다.
// 08-18에 캐싱을 넣으면서 그 걱정을 **전략으로 없앴다**: 문서는 network-first다.
// 온라인이면 언제나 네트워크가 이기므로 '온라인인데 옛 내용'이 구조적으로 불가능하다.
// 캐시는 **네트워크가 실패했을 때만** 쓰인다.
//
// 손대는 것과 안 대는 것:
//   · 정적 문서(/devlog/*.html·/lessons.html·…) → network-first, 성공하면 사본 갱신
//   · 해시 자산(/index-A1b2C3d4.js 같은 것)     → cache-first (이름이 바뀌면 새로 받는다)
//   · /api/*                                    → **통과.** 절전(504)을 화면이 판별해야 한다
//   · index.html(SPA 셸)·SPA 경로               → **통과.** precache는 사이트를 벽돌로 만든다
//
// 회수 장치 3겹(분석이 0인 것을 보완한다):
//   ① /sw-kill.json 이 {"disabled":true}면 캐시를 비우고 스스로 등록해제 —
//      **배포 없이 파일 하나로** 전 사용자에게서 회수된다
//   ② 캐시 이름에 **빌드 지문**을 박고 activate에서 다른 이름을 전부 지운다 (아래 CACHE)
//   ③ skipWaiting + clients.claim (아래)
//
// 갱신: 파일 내용이 1바이트라도 바뀌면 브라우저가 새 워커를 받는다. 아래 두 줄이
// 그 새 워커를 즉시 활성화시킨다 — 안 넣으면 기존 탭이 다 닫힐 때까지 옛 워커가
// 남아, 고친 알림 로직이 언제 반영되는지 알 수 없게 된다.

// ── 회수 스위치 ────────────────────────────────────────────────────────────
//
// 이 워커를 되돌리려면 보통 새 워커를 배포해야 한다. 그런데 그건 '배포가 되는 상태'를
// 전제로 한다. 캐시가 잘못돼 사이트가 옛 화면에 갇히면 그 전제가 깨질 수 있다.
// 그래서 **배포와 무관한 출구**를 하나 둔다: /sw-kill.json 에 {"disabled":true}를
// 올리면(파일 하나 업로드) 모든 기기가 **10분 안에** 캐시를 비우고 스스로 등록해제한다.
// 원본은 저장소의 ops/sw-kill.json 이고, 평소 S3에는 **없는 게 정상**이다(404 = 정상).
//
// ⚠️ **이게 실제로는 안 돌고 있었다**(2026-08-19 보안검사). 부르는 곳이 `activate`
// 하나뿐이었는데, activate는 **새 워커 바이트가 배포될 때만** 뜬다. 즉 "배포 없이
// 파일 하나로 회수한다"는 설명이 거짓이었고, 정작 배포가 되는 상황에서는 이 레버가
// 필요 없다. 이미 설치된 워커는 sw-kill.json을 영원히 안 읽었다.
//
// 그래서 fetch에서도 본다. 다만 **이동마다 부르면 안 된다** — 화면 이동 하나에
// 요청이 하나씩 더 붙고, 그 요청이 오리진으로 간다. 10분에 한 번으로 조인다.
// (검사 자체는 await 하지 않는다. 회수는 급하지만 이 페이지의 응답을 늦출 만큼은 아니다.)
const KILL_CHECK_MS = 10 * 60 * 1000
let lastKillCheck = 0

function maybeCheckKillSwitch() {
  const now = Date.now()
  if (now - lastKillCheck < KILL_CHECK_MS) return
  lastKillCheck = now
  checkKillSwitch()
}

async function checkKillSwitch() {
  try {
    const res = await fetch('/sw-kill.json', { cache: 'no-store' })
    if (!res.ok) return false
    const body = await res.json()
    if (body && body.disabled === true) {
      const names = await caches.keys()
      await Promise.all(names.map((n) => caches.delete(n)))
      await self.registration.unregister()
      return true
    }
  } catch {
    // 파일이 없거나 못 읽는 게 정상 상태다(평소엔 안 올려둔다). 조용히 넘어간다.
  }
  return false
}

// ── 캐시 라우팅 ────────────────────────────────────────────────────────────
//
// **판정을 순수 함수로 뗀다.** 서비스워커는 브라우저 안에서만 돌아 테스트가 어렵고,
// 여기가 틀리면 증상이 '사이트가 옛 화면에 갇힌다'라 가장 비싸다. 순수 함수면
// node --test로 잠글 수 있다(terraform/cf-functions.test.mjs와 같은 방식).
//
// 돌려주는 값: 'network-only' | 'network-first' | 'cache-first'
function routeFor(url) {
  const u = new URL(url)
  const p = u.pathname

  // 남의 출처는 손대지 않는다(폰트 CDN·토스 결제창).
  if (u.origin !== self.location.origin) return 'network-only'
  // API는 절대 캐시하지 않는다. 이 사이트는 504로 절전을 판별하고, 그 신호가
  // 캐시에 가리면 화면이 "절전 중"이라고 말할 근거를 잃는다.
  if (p.startsWith('/api/')) return 'network-only'
  // 업로드 이미지는 원본이 S3라 여기서 관리하지 않는다.
  if (p.startsWith('/uploads/')) return 'network-only'
  // SPA 셸. precache 금지 — 여기를 캐시하면 새 배포가 나가도 옛 앱이 계속 뜬다.
  if (p === '/' || p === '/index.html') return 'network-only'

  // 해시가 박힌 자산은 내용이 바뀌면 **이름이 바뀐다**. 그래서 캐시를 믿어도 된다
  // (08-17에 immutable로 바꾼 그 파일들이다). 예: /index-A1b2C3d4.js
  if (/-[A-Za-z0-9_-]{8,}\.(?:js|css|woff2?)$/.test(p)) return 'cache-first'

  // 정적 문서 — 서버 없이 읽히라고 구운 것들. 이것만이 이 워커의 목적이다.
  if (/\.html$/.test(p)) return 'network-first'
  if (p === '/rss.xml' || p === '/devlog-index.json' || p === '/devlog-search.json') {
    return 'network-first'
  }

  // 그 밖(아이콘·manifest 등)은 손대지 않는다. 모르는 것을 캐시하지 않는 쪽이 안전하다.
  return 'network-only'
}

// 테스트가 이 함수를 꺼내 쓸 수 있게 노출한다(브라우저에서는 무해하다).
if (typeof module !== 'undefined') module.exports = { routeFor }

/**
 * 캐시 이름. `__BUILD_ID__` 는 **빌드가 찍는 도장**이다 —
 * `scripts/gen-static.mjs` 의 stampServiceWorker() 가 dist/sw.js 를 쓸 때 dist/index.html
 * 의 지문 8자로 바꾼다. 그래서 번들이 바뀐 배포마다 이름이 달라지고, 아래 activate 가
 * 다른 이름의 통을 전부 지운다.
 *
 * **왜 자동화인가 (2026-09-02)** — 08-18부터 이름이 `docs-v1` 고정이었다. 그러면
 * activate 의 "다른 이름을 지운다"가 **한 번도 지울 게 없는 코드**가 된다. 여기서
 * cache-first 로 담기는 건 해시가 박힌 번들(/index-A1b2C3d4.js)인데, 배포하면 새
 * 이름으로 하나 더 담길 뿐 옛 사본은 그대로 남는다. 이미 방문한 기기마다 옛 번들
 * 약 620KB 가 영원히 누워 있었다.
 *
 * 손으로 v2, v3 을 올리는 방법도 있는데 그건 **절차도 검사도 없는 규칙**이라
 * 이 저장소가 이미 여러 번 겪은 모양이다(사람이 잊는 자리에 규칙만 적어두기).
 * 반대로 sw.js 는 public/ 에 있어 Vite 의 해시를 안 타므로 스스로는 알 길이 없다.
 * 그래서 빌드가 대신 찍는다. 잊을 사람이 없어진다.
 *
 * 이 자리에 그냥 이름을 박으면 빌드가 **멈춘다** — stampServiceWorker() 가
 * `__BUILD_ID__` 를 못 찾으면 실패한다. CI 의 프론트 잡이 `npm run build` 를 돌리므로
 * 회귀는 거기서 걸린다. 원문에 이 표식이 남아 있는지는 src/sw.test.ts 도 본다.
 *
 * 도장을 안 찍은 원문 그대로도 **정상 동작한다**(이름이 리터럴 문자열이라 문법이
 * 깨지지 않는다). dev 서버는 그 이름을 쓰고, 그래서 이 파일을 테스트에서 그대로
 * 읽어 돌릴 수 있다.
 */
const CACHE = 'docs-__BUILD_ID__'

self.addEventListener('fetch', (event) => {
  const req = event.request
  // GET이 아니면 손대지 않는다. POST/PUT을 캐시에 넣으면 Cache API가 던진다.
  if (req.method !== 'GET') return

  // **회수 스위치 확인을 맨 앞에 둔다** (09-04 검사 FE-10).
  // 2026-09-05까지 이 호출이 network-first 분기 안에 있었다. 그런데 `/`·`/index.html` 은
  // network-only 라 위에서 return 하고, 정적 문서(.html·.json)는 cache-first 라 그 앞에서
  // return 한다 — 즉 **SPA 만 쓰는 기기(가장 흔한 방문자)는 스위치를 영영 확인하지 않았다.**
  // 이 파일 상단이 '모든 기기가 10분 안에 등록해제한다'고 약속한 바로 그 장치가,
  // 정작 개발일지 페이지를 도는 기기에서만 돌고 있었다. 회수는 워커가 망가졌을 때
  // 쓰는 마지막 수단이라 '대부분의 기기에서 안 돈다'는 그 자체로 못 쓰는 장치다.
  //
  // 응답은 기다리지 않는다(아래 함수가 fire-and-forget). 그래서 앞으로 옮겨도
  // 요청 처리 경로에 지연이 붙지 않는다.
  maybeCheckKillSwitch()

  const route = routeFor(req.url)
  if (route === 'network-only') return // 워커가 없는 것과 동일하게 돈다

  if (route === 'cache-first') {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone()))
            return res
          }),
      ),
    )
    return
  }

  // network-first: 네트워크가 이긴다. 실패했을 때만 캐시를 쓴다.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone()
          caches.open(CACHE).then((c) => c.put(req, copy))
        }
        return res
      })
      .catch(() => caches.match(req).then((hit) => hit || Promise.reject(new Error('offline')))),
  )
})

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) =>
  event.waitUntil(
    (async () => {
      if (await checkKillSwitch()) return // 회수됐으면 나머지는 할 필요가 없다
      // 옛 버전 캐시를 지운다. 이름에 빌드 지문이 박혀 있어 **새 배포는 새 통을 쓰고**,
      // 여기서 옛 통이 통째로 사라진다. 이게 옛 번들을 회수하는 유일한 장치다.
      const names = await caches.keys()
      await Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)))
      await self.clients.claim()
    })(),
  ),
)

self.addEventListener('push', (event) => {
  // 페이로드가 없거나 깨진 경우에도 알림은 띄운다. 조용히 삼키면 사용자는
  // '알림이 안 온다'고만 느끼고 원인을 찾을 단서가 없다.
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = {}
  }
  const title = data.title || '새 글이 올라왔어'
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      // 같은 tag의 알림은 덮어쓴다 — 글을 연달아 올려도 알림이 쌓이지 않는다.
      //
      // ⚠️ **tag를 하나로 고정하면 종류가 다른 알림끼리 서로를 지운다.** 여기가
      // 'new-post' 고정이었는데, 2026-08-15에 댓글 알림이 생기면서 그 순간
      // "댓글 알림이 새 글 알림을 갈아치우는" 상태가 됐다 — 바로 아래 주석이
      // 경고하는 그 실패(발송은 성공하는데 사람은 못 본다)의 다른 얼굴이다.
      // 그래서 tag를 서버가 정한다: 새 글은 'new-post', 댓글은 'comment-<글번호>'.
      // (같은 글의 댓글끼리는 여전히 합쳐지고, 다른 글·다른 종류는 안 겹친다)
      tag: data.tag || 'new-post',
      // ⚠️ **renotify 없이 tag만 쓰면 두 번째부터 조용히 교체된다.**
      // 2026-08-14에 실제로 겪었다: 첫 알림은 떴는데 그다음부터 "안 온다"는 신고가
      // 왔고, 서버는 멀쩡했다(FCM 201, 대상 조회 정상, 예외 0). 원인은 여기였다 —
      // 앞 알림이 알림 센터에 남아 있으면 새 알림이 그 자리를 소리도 배너도 없이
      // 갈아치운다. 발송은 성공하는데 사람은 못 보는, 가장 찾기 어려운 형태의 실패다.
      // renotify:true면 교체하면서도 다시 알린다 — 쌓지 않되 놓치지도 않는다.
      // (renotify는 tag가 있어야 쓸 수 있다. 둘은 짝이다.)
      renotify: true,
      data: { url: data.url || '/' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(
    // 이미 열려 있는 탭이 있으면 새 창을 띄우지 않고 그 탭을 쓴다.
    // 안 그러면 알림을 누를 때마다 탭이 하나씩 늘어난다.
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ('focus' in client) {
          if ('navigate' in client) client.navigate(target)
          return client.focus()
        }
      }
      return self.clients.openWindow(target)
    }),
  )
})
