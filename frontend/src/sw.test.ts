/**
 * 서비스워커의 **캐시 라우팅 판정**을 잠근다.
 *
 * 왜 이게 필요한가 — 이 판정이 틀리면 증상이 "사이트가 옛 화면에 갇힌다"이고, 그건
 * 배포로도 못 푸는 상태가 될 수 있다(그래서 sw.js에 회수 스위치를 따로 뒀다).
 * 서비스워커는 브라우저 안에서만 도는데, 판정을 순수 함수로 떼어 두면 여기서 잴 수 있다.
 * `terraform/cf-functions.test.mjs`가 CloudFront Function을 잠그는 방식과 같다 —
 * **실제로 배포되는 그 텍스트**를 읽어 함수를 꺼내 부른다.
 *
 * 이 파일이 지키는 핵심 셋:
 *   ① `/api/*`는 어떤 경우에도 캐시하지 않는다 — 504로 절전을 판별하는 게 이 사이트의
 *      핵심 신호이고, 캐시가 그걸 가리면 화면이 "절전 중"이라고 말할 근거를 잃는다.
 *   ② `index.html`(SPA 셸)은 캐시하지 않는다 — 여기를 캐시하면 새 배포가 나가도
 *      옛 앱이 계속 뜬다. 사이트를 벽돌로 만드는 유일한 경로다.
 *   ③ 문서는 network-first다 — 온라인이면 네트워크가 이기므로 '온라인인데 옛 내용'이
 *      구조적으로 불가능하다. 08-17까지 sw.js가 캐싱을 안 한 이유가 그 걱정이었다.
 */
import { describe, it, expect } from 'vitest'
// **배포되는 원문을 그대로 읽는다.** `?raw`는 Vite가 파일 내용을 문자열로 넣어 주는
// 방식이라 node:fs가 필요 없다(이 프로젝트의 tsconfig는 node 타입을 안 싣는다).
// 사본을 만들어 검사하면 진짜 파일이 바뀌어도 테스트가 조용히 통과한다.
import SW_SOURCE from '../public/sw.js?raw'

const ORIGIN = 'https://blog.example'

/** 배포되는 sw.js 원문을 읽어 routeFor를 꺼낸다. 브라우저 전역은 최소한만 흉내 낸다. */
function loadRouteFor(): (url: string) => string {
  const src = SW_SOURCE
  const stubs = {
    self: {
      addEventListener() {},
      location: { origin: ORIGIN },
      clients: { claim() {}, matchAll: async () => [], openWindow() {} },
      registration: { showNotification() {}, unregister: async () => {} },
      skipWaiting() {},
    },
    caches: { keys: async () => [], delete: async () => {}, match: async () => null, open: async () => ({}) },
    fetch: async () => ({ ok: false }),
    module: { exports: {} as { routeFor?: (u: string) => string } },
  }
  const fn = new Function(
    'self',
    'caches',
    'fetch',
    'module',
    `${src}\n; return routeFor;`,
  )
  return fn(stubs.self, stubs.caches, stubs.fetch, stubs.module)
}

const routeFor = loadRouteFor()
const at = (p: string) => routeFor(`${ORIGIN}${p}`)

describe('서비스워커 캐시 라우팅', () => {
  it('/api/* 는 절대 캐시하지 않는다 — 절전(504) 신호가 가리면 안 된다', () => {
    for (const p of ['/api/posts', '/api/status', '/api/skin', '/api/posts?author=yuno']) {
      expect(at(p), p).toBe('network-only')
    }
  })

  it('SPA 셸은 캐시하지 않는다 — 여기를 캐시하면 새 배포가 안 보인다', () => {
    expect(at('/')).toBe('network-only')
    expect(at('/index.html')).toBe('network-only')
  })

  it('SPA 경로는 통째로 통과한다 — 앱 화면은 워커가 없는 것과 같이 돈다', () => {
    for (const p of ['/blog', '/status', '/login', '/settings', '/@yuno', '/blog/posts/48']) {
      expect(at(p), p).toBe('network-only')
    }
  })

  it('정적 문서는 network-first — 온라인이면 네트워크가 이긴다', () => {
    for (const p of ['/devlog.html', '/lessons.html', '/devlog/2026-08-17.html', '/map.html']) {
      expect(at(p), p).toBe('network-first')
    }
    expect(at('/rss.xml')).toBe('network-first')
    expect(at('/devlog-index.json')).toBe('network-first')
  })

  it('해시가 박힌 자산만 cache-first — 이름이 바뀌면 새로 받는다', () => {
    expect(at('/index-A1b2C3d4.js')).toBe('cache-first')
    expect(at('/index-BlfdPFtB.css')).toBe('cache-first')
    // 해시가 없는 같은 확장자는 아니다 — 내용이 바뀌어도 이름이 그대로라 갇힌다
    expect(at('/sw.js')).toBe('network-only')
    expect(at('/devlog-filter.js')).toBe('network-only')
  })

  it('업로드 이미지와 남의 출처는 손대지 않는다', () => {
    expect(at('/uploads/a.png')).toBe('network-only')
    expect(routeFor('https://cdn.jsdelivr.net/x.css')).toBe('network-only')
    expect(routeFor('https://js.tosspayments.com/v2')).toBe('network-only')
  })

  it('모르는 것은 캐시하지 않는다 — 기본값이 안전한 쪽이다', () => {
    expect(at('/manifest.json')).toBe('network-only')
    expect(at('/favicon.svg')).toBe('network-only')
    expect(at('/무엇인가')).toBe('network-only')
  })
})

describe('서비스워커 원문이 지켜야 할 것', () => {
  const src = SW_SOURCE

  it('precache 목록이 없다 — install에서 미리 담으면 그게 벽돌이 되는 경로다', () => {
    expect(src).not.toMatch(/addAll\s*\(/)
  })

  it('회수 스위치(/sw-kill.json)와 등록해제가 들어 있다', () => {
    expect(src).toContain('/sw-kill.json')
    expect(src).toContain('registration.unregister()')
  })

  it('캐시 이름에 빌드 도장이 남아 있다 — 고정 이름은 옛 번들을 영원히 남긴다', () => {
    // **왜 원문을 검사하나 (2026-09-02)** — 08-18부터 이름이 `docs-v1` 고정이었고,
    // 그래서 activate 의 "다른 이름의 통을 지운다"가 지울 게 없는 코드였다. 여기 담기는
    // 건 해시 박힌 번들이라, 배포마다 하나씩 더 쌓이기만 했다(기기당 약 620KB).
    // 이제 `scripts/gen-static.mjs` 가 빌드 때 이 표식을 지문으로 바꾼다. 표식이
    // 사라지면 빌드가 멈추는데(그쪽이 진짜 잠금), 증상이 '아무 일도 안 일어남'이라
    // 여기에도 표식을 남겨 둔다. 빌드를 안 돌려도 이 자리에서 먼저 보인다.
    expect(src).toContain("const CACHE = 'docs-__BUILD_ID__'")
  })

  it('회수 스위치를 activate에서만 보지 않는다', () => {
    // 문자열이 들어 있는지만 보던 테스트가 초록이었는데 **실제로는 안 돌고 있었다**
    // (2026-08-19 보안검사). 부르는 곳이 activate 하나뿐이었고, activate는 새 워커
    // 바이트가 배포될 때만 뜬다 — 즉 "배포 없이 파일 하나로 회수"가 거짓이었다.
    // 아래 '동작' 테스트가 진짜 잠금이고, 이건 그 회귀를 눈에 띄게 하는 표식이다.
    expect(src).toContain('maybeCheckKillSwitch')
  })
})

/**
 * fetch 핸들러의 **행동**을 잰다 — routeFor가 옳아도 핸들러가 잘못 쓰면 소용없다.
 *
 * 실제 sw.js에서 'fetch' 리스너를 꺼내 가짜 이벤트를 넣고, 캐시에 무엇이 들어가고
 * 응답이 어디서 오는지 본다. (브라우저 없이 되는 이유: 핸들러가 쓰는 건 caches·fetch
 * 두 전역뿐이고 둘 다 흉내 낼 수 있다. 헤드리스 크롬으로는 서비스워커 검증이
 * 계속 겉돌아서 이 방식으로 왔다 — 2026-08-18.)
 */
type Store = Map<string, { body: string; ok: boolean }>

function loadWorker(opts: { offline?: boolean; store?: Store; kill?: boolean } = {}) {
  const listeners: Record<string, (e: unknown) => void> = {}
  // 캐시 통을 밖에서 넘길 수 있다 — '온라인에서 받아둔 뒤 오프라인이 됐다'를
  // 재현하려면 **같은 캐시**를 가진 채 네트워크만 끊어야 한다.
  const store: Store = opts.store ?? new Map()
  const cache = {
    async match(req: { url?: string } | string) {
      const k = typeof req === 'string' ? req : (req.url ?? '')
      return store.get(k) ?? null
    },
    async put(req: { url: string }, res: { body: string; ok: boolean }) {
      store.set(req.url, res)
    },
    async keys() {
      return [...store.keys()].map((url) => ({ url }))
    },
  }
  let networkCalls = 0
  // 회수 스위치가 **실제로 도는지** 재려면 세 가지를 세야 한다:
  // 워커가 /sw-kill.json을 부르는가 · 캐시를 지우는가 · 등록해제하는가.
  let killFetches = 0
  let unregisters = 0
  let cacheDeletes = 0
  const self_ = {
    addEventListener(type: string, fn: (e: unknown) => void) {
      listeners[type] = fn
    },
    location: { origin: ORIGIN },
    clients: { claim() {}, matchAll: async () => [], openWindow() {} },
    registration: {
      showNotification() {},
      unregister: async () => {
        unregisters++
      },
    },
    skipWaiting() {},
  }
  const caches_ = {
    async keys() {
      return ['docs-v1']
    },
    async delete() {
      cacheDeletes++
    },
    async match(req: { url?: string } | string) {
      return cache.match(req)
    },
    async open() {
      return cache
    },
  }
  const fetch_ = async (req: { url?: string } | string) => {
    const url = typeof req === 'string' ? req : (req.url ?? '')
    // 회수 파일은 워커가 직접 부르는 것이라 networkCalls에 안 센다 — 다른 테스트가
    // 그 숫자로 '네트워크를 몇 번 갔나'를 재고 있어서 섞이면 그쪽이 거짓말을 한다.
    if (url === '/sw-kill.json') {
      killFetches++
      // 평소에는 이 파일이 **없는 게 정상**이다(404). 그 경로도 같이 잰다.
      if (!opts.kill) return { ok: false, json: async () => ({}) }
      return { ok: true, json: async () => ({ disabled: true }) }
    }
    networkCalls++
    if (opts.offline) throw new Error('offline')
    const res = { ok: true, body: 'NET:' + url, clone: () => res }
    return res
  }
  new Function('self', 'caches', 'fetch', 'module', SW_SOURCE)(self_, caches_, fetch_, { exports: {} })

  return {
    async handle(url: string, method = 'GET') {
      // 객체에 담는다 — 지역 변수로 두면 TS가 "콜백은 안 불릴 수도 있다"고 보고
      // 호출 뒤에도 null로 좁혀서 `never`가 된다.
      const box: { res: Promise<{ body?: string }> | null } = { res: null }
      const event = {
        request: { url, method },
        respondWith(p: Promise<{ body?: string }>) {
          box.res = p
        },
        waitUntil() {},
      }
      listeners.fetch?.(event)
      return box.res ? await box.res : null
    },
    cached: () => [...store.keys()].map((u) => new URL(u).pathname).sort(),
    networkCalls: () => networkCalls,
    killFetches: () => killFetches,
    unregisters: () => unregisters,
    cacheDeletes: () => cacheDeletes,
    store,
  }
}

describe('fetch 핸들러 동작', () => {
  it('문서를 받으면 캐시에 사본이 남는다(network-first)', async () => {
    const w = loadWorker()
    const res = await w.handle(`${ORIGIN}/devlog.html`)
    expect(res?.body).toBe(`NET:${ORIGIN}/devlog.html`) // 네트워크가 이긴다
    expect(w.cached()).toContain('/devlog.html')
  })

  it('네트워크가 죽으면 캐시가 답한다 — 이게 이 워커의 존재 이유다', async () => {
    // ① 온라인에서 한 번 받아 캐시에 넣는다
    const online = loadWorker()
    await online.handle(`${ORIGIN}/devlog.html`)
    expect(online.cached()).toContain('/devlog.html')

    // ② 같은 캐시를 그대로 들고 네트워크만 끊는다(서버 절전 = 이 사이트의 평상시)
    const off = loadWorker({ offline: true, store: online.store })
    const res = await off.handle(`${ORIGIN}/devlog.html`)
    expect(res?.body).toBe(`NET:${ORIGIN}/devlog.html`) // 아까 받아둔 그 사본이다
  })

  it('오프라인인데 캐시에도 없으면 거절한다 — 없는 걸 지어내지 않는다', async () => {
    const off = loadWorker({ offline: true })
    await expect(off.handle(`${ORIGIN}/lessons.html`)).rejects.toThrow()
  })

  it('/api/* 는 핸들러가 아예 손대지 않는다', async () => {
    const w = loadWorker()
    expect(await w.handle(`${ORIGIN}/api/status`)).toBeNull() // respondWith 안 함
    expect(w.networkCalls()).toBe(0)
    expect(w.cached()).toEqual([])
  })

  it('SPA 셸과 SPA 경로도 손대지 않는다', async () => {
    const w = loadWorker()
    for (const p of ['/', '/index.html', '/blog', '/@yuno']) {
      expect(await w.handle(`${ORIGIN}${p}`), p).toBeNull()
    }
    expect(w.cached()).toEqual([])
  })

  it('GET이 아니면 손대지 않는다 — 캐시 API가 던진다', async () => {
    const w = loadWorker()
    expect(await w.handle(`${ORIGIN}/devlog.html`, 'POST')).toBeNull()
    expect(w.cached()).toEqual([])
  })

  it('해시 자산은 두 번째부터 네트워크를 안 탄다(cache-first)', async () => {
    const w = loadWorker()
    await w.handle(`${ORIGIN}/index-A1b2C3d4.js`)
    const after1 = w.networkCalls()
    await w.handle(`${ORIGIN}/index-A1b2C3d4.js`)
    expect(w.networkCalls()).toBe(after1) // 두 번째는 캐시가 답했다
  })
})

/**
 * 회수 스위치가 **말한 대로 도는지**.
 *
 * 이 레버의 약속은 "앱 배포 없이 파일 하나로 모든 기기를 회수한다"이다. 2026-08-19
 * 보안검사가 그 약속이 거짓임을 실측했다 — 부르는 곳이 `activate` 하나뿐이라
 * 이미 설치된 워커는 `/sw-kill.json`을 영영 안 읽었고, 새 워커를 배포해야만 돌았다.
 * 배포가 되는 상황이면 이 레버가 필요 없으니, 필요할 때만 안 되는 물건이었다.
 *
 * 보안 영향은 0이지만 **사고 한복판에서 사람을 잘못된 길로 보낸다**. 문서 세 곳이
 * 다 된다고 적혀 있었다.
 */
/** 워커가 뒤에서 도는 비동기 사슬을 끝까지 흘려보낸다. */
async function flush() {
  for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0))
}

describe('회수 스위치', () => {
  it('평범한 이동에서 /sw-kill.json을 본다 — activate를 기다리지 않는다', async () => {
    const w = loadWorker()
    await w.handle(`${ORIGIN}/devlog.html`)
    expect(w.killFetches()).toBe(1)
  })

  it('true면 캐시를 비우고 스스로 등록해제한다', async () => {
    const w = loadWorker({ kill: true })
    await w.handle(`${ORIGIN}/devlog.html`)
    // checkKillSwitch는 응답을 안 기다리게(await 없이) 부른다 — 이 페이지의 응답을
    // 늦추지 않으려는 것이라, 테스트가 대신 기다려 준다. await가 여러 단이라
    // (fetch → json → caches.keys → delete → unregister) 틱 하나로는 부족하다.
    await flush()
    expect(w.cacheDeletes()).toBeGreaterThan(0)
    expect(w.unregisters()).toBe(1)
  })

  it('파일이 없으면(404) 아무 일도 안 한다 — 그게 평소 상태다', async () => {
    const w = loadWorker()
    await w.handle(`${ORIGIN}/devlog.html`)
    await flush()
    expect(w.unregisters()).toBe(0)
    expect(w.cacheDeletes()).toBe(0)
  })

  it('이동마다 부르지는 않는다 — 요청이 화면 수만큼 늘면 그게 새 부담이다', async () => {
    const w = loadWorker()
    await w.handle(`${ORIGIN}/devlog.html`)
    await w.handle(`${ORIGIN}/lessons.html`)
    await w.handle(`${ORIGIN}/rss.xml`)
    expect(w.killFetches()).toBe(1) // 10분에 한 번(KILL_CHECK_MS)
  })

  it('SPA 만 쓰는 기기에서도 확인한다 — network-only 경로', async () => {
    // ⚠️ 2026-09-05까지 이 확인이 network-first 분기 **안**에 있었다(09-04 검사 FE-10).
    // `/`·`/index.html` 은 network-only 라 그 앞에서 return 하고 정적 문서는 cache-first
    // 라 역시 앞에서 return 하므로, **개발일지를 안 열고 SPA 만 쓰는 기기는 회수 스위치를
    // 영영 확인하지 않았다.** 위 테스트들이 전부 `/devlog.html`(network-first)로만
    // 확인한 탓에 그 사각이 안 보였다 — 시험이 한 갈래만 밟고 있었던 것이다.
    const w = loadWorker({ kill: true })
    await w.handle(`${ORIGIN}/`)
    await flush()
    expect(w.killFetches()).toBe(1)
    expect(w.unregisters()).toBe(1)
  })

  it('cache-first 경로(해시 자산 재방문)에서도 확인한다', async () => {
    const asset = `${ORIGIN}/index-A1b2C3d4.js`
    const store: Store = new Map([[asset, { body: 'cached', ok: true }]])
    const w = loadWorker({ kill: true, store })
    const res = await w.handle(asset)
    await flush()
    // 캐시에서 바로 답한 것이어야 이 경로를 실제로 밟은 것이다 — 네트워크로 샜으면
    // network-first 갈래를 재는 위 테스트와 같은 것을 두 번 재게 된다.
    expect(res?.body).toBe('cached')
    expect(w.networkCalls()).toBe(0)
    expect(w.killFetches()).toBe(1)
    expect(w.unregisters()).toBe(1)
  })

  it('회수 파일 요청이 문서 네트워크 집계에 안 섞인다', async () => {
    // 섞이면 다른 테스트가 '네트워크를 몇 번 갔나'로 재는 것이 조용히 틀어진다.
    const w = loadWorker()
    await w.handle(`${ORIGIN}/devlog.html`)
    expect(w.networkCalls()).toBe(1)
  })
})
