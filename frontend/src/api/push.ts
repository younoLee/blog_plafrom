import { authHeaders } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

export interface PushStatus {
  enabled: boolean // 서버에 VAPID 키가 설정돼 있는가
  devices: number // 이 계정이 알림받는 기기 수
}

/** 브라우저가 이 기능을 지원하는가. iOS 사파리는 **홈화면에 설치된 뒤에만** 지원한다. */
export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

/** 서버 VAPID 공개키. 503(키 미설정)이면 null — 화면이 기능을 숨기는 근거가 된다. */
async function fetchPublicKey(): Promise<string | null> {
  const res = await fetch(`${BASE}/push/key`)
  if (res.status === 503) return null
  if (!res.ok) throw new Error('알림 설정을 불러오지 못했어')
  return (await res.json()).public_key
}

export async function fetchPushStatus(): Promise<PushStatus> {
  const res = await fetch(`${BASE}/push`, { headers: authHeaders() })
  if (!res.ok) throw new Error('알림 상태를 불러오지 못했어')
  return res.json()
}

// base64url 문자열 → ArrayBuffer.
// 브라우저의 applicationServerKey는 **문자열이 아니라 바이트**만 받는다.
// 그냥 넘기면 InvalidCharacterError가 나는데 원인이 잘 안 보인다.
//
// Uint8Array가 아니라 그 buffer를 돌려주는 이유: TS 5.7부터 Uint8Array가
// 버퍼 타입에 대해 제네릭이 됐고, 기본 인자 ArrayBufferLike는 SharedArrayBuffer를
// 포함해 BufferSource에 안 맞는다. ArrayBuffer를 직접 주면 그 문제가 사라진다.
function urlBase64ToBytes(base64: string): ArrayBuffer {
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i)
  return bytes.buffer
}

/** 구독 객체에서 서버가 저장할 세 값을 꺼낸다(브라우저가 주는 형식 그대로). */
function toPayload(sub: PushSubscription) {
  const json = sub.toJSON()
  return {
    endpoint: sub.endpoint,
    p256dh: json.keys?.p256dh ?? '',
    auth: json.keys?.auth ?? '',
  }
}

/** 서비스워커를 등록(이미 있으면 재사용)하고 준비될 때까지 기다린다. */
async function registration(): Promise<ServiceWorkerRegistration> {
  await navigator.serviceWorker.register('/sw.js')
  return navigator.serviceWorker.ready
}

export type SubscribeResult = 'ok' | 'denied' | 'unsupported' | 'disabled'

/**
 * 알림 켜기 — 권한 요청 → 구독 → 서버 등록.
 *
 * 실패를 뭉뚱그리지 않고 구분해 돌려준다. 'denied'(사용자가 거부)는 다시
 * 물어봐도 브라우저가 프롬프트를 안 띄우므로, 화면이 "설정에서 직접 허용해야
 * 한다"고 안내해야 한다 — 버튼을 다시 누르라고 하면 영원히 안 된다.
 */
export async function subscribePush(): Promise<SubscribeResult> {
  if (!pushSupported()) return 'unsupported'
  const key = await fetchPublicKey()
  if (!key) return 'disabled'

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') return 'denied'

  const reg = await registration()
  // 이미 구독돼 있으면 그걸 그대로 쓴다. 다시 subscribe()를 부르면 옛 구독이
  // 무효가 되면서 서버 DB에 죽은 endpoint가 남는다.
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true, // 브라우저 요구사항 — 무음 푸시는 허용되지 않는다
      applicationServerKey: urlBase64ToBytes(key),
    }))

  const res = await fetch(`${BASE}/push`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(toPayload(sub)),
  })
  if (!res.ok) throw new Error('알림 등록에 실패했어')
  return 'ok'
}

/** 이 기기만 알림 끄기 — 브라우저 구독도 함께 해제한다.
 *
 * **로컬 구독이 없으면 서버를 건드리지 않는다.** 예전엔 endpoint 없이 DELETE를
 * 보냈는데, 서버는 그걸 '이 계정의 전 기기 해제'로 해석한다(routers/push.py).
 * 그래서 노트북에서 구독이 만료·삭제된 상태로 '이 기기 알림 끄기'를 누르면
 * **폰 알림까지 같이 꺼졌다.** 버튼이 약속한 것과 다른 일을 하면 안 된다. */
export async function unsubscribePush(): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration()
  const sub = await reg?.pushManager.getSubscription()
  if (!sub) return // 이 기기엔 이미 없다 — 지울 것도 없다

  // 서버를 먼저 지운다. 순서를 뒤집으면 브라우저 구독은 사라졌는데 서버엔 남아,
  // 다음 발송이 죽은 endpoint로 나가고 그제서야 정리된다.
  const res = await fetch(`${BASE}/push?endpoint=${encodeURIComponent(sub.endpoint)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('알림 해제에 실패했어')
  await sub.unsubscribe()
}

/** 이 브라우저가 지금 구독 중인지 (화면의 켜짐/꺼짐 표시용). */
export async function isSubscribedHere(): Promise<boolean> {
  if (!pushSupported()) return false
  const reg = await navigator.serviceWorker.getRegistration()
  return !!(await reg?.pushManager.getSubscription())
}
