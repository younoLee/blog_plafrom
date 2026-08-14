// 서비스워커 — 푸시 수신과 알림 클릭만 담당한다.
//
// **일부러 캐싱을 하지 않는다.** 서비스워커를 붙이면 오프라인 캐시부터 떠오르지만,
// 이 사이트는 서버를 평소 꺼두는 구조라 '캐시된 옛 글 목록'이 절전 안내를 덮어버리면
// 오히려 고장으로 보인다. 화면이 8초 안에 "절전 중"이라고 말해주는 게 지금의 설계고,
// 여기서 그걸 흐리지 않는다. 이 파일은 알림 배달만 한다.
//
// 갱신: 파일 내용이 1바이트라도 바뀌면 브라우저가 새 워커를 받는다. 아래 두 줄이
// 그 새 워커를 즉시 활성화시킨다 — 안 넣으면 기존 탭이 다 닫힐 때까지 옛 워커가
// 남아, 고친 알림 로직이 언제 반영되는지 알 수 없게 된다.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

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
      tag: 'new-post',
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
