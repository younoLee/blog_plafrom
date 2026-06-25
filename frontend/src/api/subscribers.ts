const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 구독 등록. 성공 시 등록된 구독자 반환, 실패 시 상태별 메시지로 에러
export async function subscribe(email: string): Promise<void> {
  const res = await fetch(`${BASE}/subscribers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (res.status === 409) throw new Error('이미 구독 중인 이메일이야')
  if (res.status === 422) throw new Error('이메일 형식이 올바르지 않아')
  if (!res.ok) throw new Error('구독 실패')
}
