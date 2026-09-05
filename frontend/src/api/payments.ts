import { apiFetch, failWith, fetchWithTimeout } from './http'
import { authHeaders, type User } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

export interface Checkout {
  order_id: string
  amount: number
  order_name: string
}

// 결제 주문 생성 (서버가 orderId·금액을 정함 → 위변조 방지의 기준)
export async function createCheckout(): Promise<Checkout> {
  const res = await apiFetch(`${BASE}/payments/checkout`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (res.status === 401) throw new Error('로그인이 필요해')
  if (res.status === 400) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? '결제를 시작할 수 없어')
  }
  if (res.status === 429) throw new Error('요청이 너무 잦아. 잠시 후 다시 해줘')
  if (!res.ok) await failWith(res, '결제를 시작하지 못했어')
  return res.json()
}

// 토스 결제창 성공 리다이렉트 후, 서버가 토스 승인 API로 검증 → 성공 시 is_pro=true된 User 반환
export async function confirmPayment(paymentKey: string, orderId: string, amount: number): Promise<User> {
  const res = await apiFetch(`${BASE}/payments/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ payment_key: paymentKey, order_id: orderId, amount }),
  })
  if (res.status === 401) throw new Error('로그인이 필요해')
  if (!res.ok) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail ?? '결제 승인에 실패했어')
  }
  return res.json()
}

// 구독 해지 (is_pro 끔)
// 내 결제 내역. **실패·대기 주문도 함께 온다** — 성공만 보여주면 '결제가 안 됐는데
// 돈이 빠져나간 것 같다'는 상황에서 화면이 아무 말도 안 하게 된다(09-04 검사 GAP-7).
export interface PaymentRow {
  order_id: string
  order_name: string
  amount: number
  /** pending(주문만 만듦) · confirming(확인 중, 실패가 아니다) · paid · failed */
  status: string
  receipt_url: string | null
  created_at: string
  paid_at: string | null
}

export async function fetchMyPayments(): Promise<PaymentRow[]> {
  const res = await fetchWithTimeout(`${BASE}/payments/me`, { headers: authHeaders() })
  if (!res.ok) await failWith(res, '결제 내역을 불러오지 못했어')
  return res.json()
}

export async function unsubscribe(): Promise<User> {
  const res = await apiFetch(`${BASE}/payments/unsubscribe`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (res.status === 401) throw new Error('로그인이 필요해')
  if (res.status === 429) throw new Error('요청이 너무 잦아. 잠시 후 다시 해줘')
  if (!res.ok) await failWith(res, '구독 해지에 실패했어')
  return res.json()
}
