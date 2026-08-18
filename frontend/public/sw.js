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
//   ② 캐시 이름에 버전을 박고 activate에서 다른 이름을 전부 지운다
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
// 올리면(파일 하나 업로드) 다음 이동에서 모든 기기가 캐시를 비우고 스스로 등록해제한다.
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

const CACHE = 'docs-v1'

self.addEventListener('fetch', (event) => {
  const req = event.request
  // GET이 아니면 손대지 않는다. POST/PUT을 캐시에 넣으면 Cache API가 던진다.
  if (req.method !== 'GET') return
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
      // 옛 버전 캐시를 지운다. 이름에 버전이 박혀 있어 새 워커는 새 통을 쓴다.
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
